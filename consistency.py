"""Layer-consistency checker for Kalshi tennis per-player contracts.

A deeper/more-restrictive outcome must not price higher than the prerequisite that contains
it. We only compare pairs whose logical containment we can prove; uncertain relationships are
marked UNKNOWN_RELATIONSHIP and never treated as violations.

All price comparisons use EXACT integer cents (parsed via Decimal upstream in data.py). Floats
are only ever used for Streamlit display. Findings are called "executable inconsistencies",
never "arbitrage": true arbitrage also needs the two markets' settlement rules to be
compatible, which we do not auto-verify — so match-alignment findings carry a RULE_CHECK_REQUIRED
flag (RULE_MISMATCH if a light rules-text compare clearly differs).

No Streamlit imports here — this module is independently testable.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

import sports
from config import DISPLAY_TOL_C, NEAR_EDGE_MIN_C
from data import CATEGORY, opportunity_id
from glossary import BLOCKERS, WATCHLIST_NOTE

# Statuses that represent an actual price inconsistency with a buy direction (get a Buy YES / Buy NO
# action plan). WIDE_QUOTE is deliberately excluded: ordering is consistent there, so it's
# watchlist-only, not an opportunity to act on.
ACTION_STATUSES = {"EXECUTABLE_VIOLATION", "DISPLAY_VIOLATION", "QUOTE_SIZE_MISSING"}

# The containment ladder is now per-sport (sports.py). These module-level names are back-compat
# aliases that REFERENCE the tennis ladder (never copies), so `from consistency import NODE_ORDER`
# (app.py) and the tennis consistency tests resolve exactly as before. Multi-sport code resolves the
# ladder from each row/group's series via `_sport_for_row(s)` below.
NODE_ORDER = sports.TENNIS.ladder.node_order
ADJACENT_PAIRS = sports.TENNIS.ladder.adjacent_pairs
MATCH_STAGE_TO_NODE = sports.TENNIS.ladder.match_stage_to_node
ADVANCE_STAGE_TO_NODE = sports.TENNIS.ladder.advance_stage_to_node


def _sport_for_row(row: dict[str, Any]):
    """Resolve the sport that owns a contract row, from its `series`. Falls back to TENNIS for
    unit-test fixtures that carry no series ticker (Stage-A back-compat; real rows always have one)."""
    cfg = sports.sport_for_series(row.get("series"))
    return cfg if cfg.sport_id != "unknown" else sports.TENNIS


def _sport_for_rows(rows: list[dict[str, Any]]):
    """Resolve the sport for a group of one player's rows (all one sport). TENNIS fallback."""
    for r in rows or []:
        cfg = sports.sport_for_series(r.get("series"))
        if cfg.sport_id != "unknown":
            return cfg
    return sports.TENNIS

# Settlement-rule nuance tokens; a difference between two markets means the equivalence may
# not hold exactly (e.g. walkover / "ball has been played" handling differs).
_RULE_TOKENS = ["ball has been played", "walkover", "retire", "withdraw", "forfeit", "cancel"]

_QUALITY_RANK = {"Tight": 0, "OK": 1, "Wide": 2, "Very wide": 3, "One-sided": 4, "No quote": 5, "Crossed": 6}

STATUS_GROUP = {
    "CLEAN": "Clean",
    "EXECUTABLE_VIOLATION": "Broken",
    # Dutch-book findings come from the sibling `dutchbook` module (status string kept as a literal
    # here to avoid importing it — `dutchbook.EXECUTABLE_DUTCH_BOOK`). Grouped with executable edges.
    "EXECUTABLE_DUTCH_BOOK": "Broken",
    "DISPLAY_VIOLATION": "Warning",
    "WIDE_QUOTE": "Warning",
    "MISSING_QUOTE": "Missing data",
    "MISSING_LAYER": "Missing data",
    "QUOTE_SIZE_MISSING": "Missing data",
    "UNKNOWN_RELATIONSHIP": "Unknown relationship",
}


def node_of(row: dict[str, Any]) -> str | None:
    """Map a contract row to its containment node, or None if it doesn't map confidently.

    Prefers the `ladder_node` stamped by `data.build_contracts` (the sport's classification). Falls
    back to recomputing from the resolved sport's family/stage maps — this serves unit-test fixtures
    that carry family/stage but no stamped node. Ineligible/non-laddered markets have node None and
    are thus excluded from the ladder.
    """
    stamped = row.get("ladder_node")
    if stamped:
        return stamped
    cfg = _sport_for_row(row)
    return cfg.node_fn(cfg, row.get("kind"), row.get("stage"))


def _representative_key(row: dict[str, Any]) -> tuple:
    """Deterministic ordering key when several rows map to the same node/source: prefer a row
    with a usable display price, then higher volume, then the lexically-smallest ticker. This
    makes the chosen representative independent of (concurrent, non-deterministic) fetch order."""
    has_price = 0 if row.get("display_pct") is not None else 1   # 0 sorts first
    vol = row.get("volume") or 0
    return (has_price, -vol, str(row.get("market_ticker") or ""))


def build_player_nodes(player_rows: list[dict[str, Any]]) -> dict[str, dict[str, dict]]:
    """Group a player's contracts into {node: {"market": row?, "match": row?}}.

    If multiple rows map to the same (node, source) — e.g. two winner series under a full scan —
    the representative is chosen deterministically (see `_representative_key`), not by arrival order.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in player_rows:
        node = node_of(row)
        if not node:
            continue
        source = "match" if row.get("kind") == "match" else "market"
        buckets.setdefault((node, source), []).append(row)

    nodes: dict[str, dict[str, dict]] = {}
    for (node, source), rows in buckets.items():
        nodes.setdefault(node, {})[source] = min(rows, key=_representative_key)
    return nodes


def duplicate_node_sources(player_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diagnostic: (node, source, count) where more than one row competed for the same slot,
    so the UI/debug can flag that a representative was chosen among duplicates."""
    buckets: dict[tuple[str, str], int] = {}
    for row in player_rows:
        node = node_of(row)
        if not node:
            continue
        source = "match" if row.get("kind") == "match" else "market"
        buckets[(node, source)] = buckets.get((node, source), 0) + 1
    return [
        {"node": node, "source": source, "count": n}
        for (node, source), n in buckets.items() if n > 1
    ]


def _isna(x: Any) -> bool:
    """True for None or float NaN. Needed because a `None` price round-trips to float NaN
    through pandas (`DataFrame` → `to_dict("records")`), so a plain `is None` check misses it."""
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    """Normalize a possibly-NaN numeric to None so downstream `is None` checks work."""
    return None if _isna(x) else x


def representative(node_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The single price-carrying contract row for a node: prefer the market source
    (advance/winner), else the match-implied source. Shared by the progression chain and the
    ladder-spread view so source selection lives in exactly one place."""
    if not node_entry:
        return None
    return node_entry.get("market") or node_entry.get("match")


def layer_spreads(player_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Raw price gaps between adjacent ladder layers (broad → deep).

    These are RAW stage-ladder spreads, not a probability model: `spread_pct` is a
    percentage-point difference and `spread_cents` a cents difference between the broader and the
    deeper layer's display price. A node that is absent gives status "missing_layer"; a node that
    exists but has no usable display price gives "missing_price"; both yield `spread_* = None`.
    """
    nodes = build_player_nodes(player_rows)
    ladder = _sport_for_rows(player_rows).ladder
    out: list[dict[str, Any]] = []
    for broader, deeper in zip(ladder.node_order, ladder.node_order[1:]):
        b = representative(nodes.get(broader))
        d = representative(nodes.get(deeper))
        # NaN-safe: a missing price arrives as float NaN via the DataFrame→records path.
        b_pct = _num(b.get("display_pct")) if b else None
        d_pct = _num(d.get("display_pct")) if d else None
        b_c = _num(b.get("display_c")) if b else None
        d_c = _num(d.get("display_c")) if d else None
        # Worst-of-two quote quality, so a spread built on illiquid books is visible.
        quote = _worst_quality(b.get("quote_quality") or "", d.get("quote_quality") or "") if (b and d) else ""

        if b is None or d is None:
            status, spread_pct, spread_cents = "missing_layer", None, None
        elif b_pct is None or d_pct is None:
            status, spread_pct, spread_cents = "missing_price", None, None
        else:
            status = "ok"
            spread_pct = round(b_pct - d_pct, 1)
            spread_cents = (b_c - d_c) if (b_c is not None and d_c is not None) else None

        out.append(
            {
                "from_layer": broader,
                "to_layer": deeper,
                "from_pct": b_pct,
                "to_pct": d_pct,
                "spread_pct": spread_pct,
                "spread_cents": spread_cents,
                "status": status,
                "quote": quote,
                "inverted": spread_pct is not None and spread_pct < 0,
            }
        )
    return out


def expected_nodes(player_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit expected-vs-found ladder for a player.

    Only produces output when the player has at least one `advance` or `winner` contract — those
    are the kinds that populate the containment ladder. Players with only match/set/score data have
    no applicable ladder, so an empty list is returned (avoiding spurious MISSING_LAYER noise).

    `source` is "market" (advance/winner), "match" (a confident match-implied node), or "" when absent.
    """
    if not any(r.get("kind") in ("advance", "winner") for r in player_rows):
        return []
    nodes = build_player_nodes(player_rows)
    out: list[dict[str, Any]] = []
    for node in _sport_for_rows(player_rows).ladder.node_order:
        src = nodes.get(node, {})
        if "market" in src:
            source, found = "market", True
        elif "match" in src:
            source, found = "match", True
        else:
            source, found = "", False
        out.append({"layer": node, "expected": True, "found": found, "source": source})
    return out


def _pos(size: Any) -> bool:
    return size is not None and size > 0


def _min_size(a: Any, b: Any) -> Any:
    """Tradable units behind a two-legged fill: the smaller of the two firm sizes, or None
    if either side has no usable size."""
    if a is None or b is None:
        return None
    return min(a, b)


def spread_certainty_label(rule_flag: str) -> str:
    """Honest certainty wording for an executable inconsistency. Strict containment pairs
    (no rule flag) lock a gross spread; match-alignment pairs depend on settlement rules
    matching, which we never confirm — so they are only ever 'rule-dependent'."""
    if rule_flag in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH"):
        return "Rule-dependent gross spread"
    return "Locked gross spread"


def _leg(row: dict[str, Any], side: str) -> tuple[int | None, Any]:
    """Return (cents, size) for a contract's firm bid/ask side.

    An empty 0/1 book ("No quote") or a malformed crossed book ("Crossed") has no usable order.
    """
    if row.get("quote_quality") in ("No quote", "Crossed"):
        return None, None
    if side == "bid":
        return _num(row.get("yes_bid_c")), row.get("yes_bid_size")
    return _num(row.get("yes_ask_c")), row.get("yes_ask_size")


def _worst_quality(a: str, b: str) -> str:
    return a if _QUALITY_RANK.get(a, 0) >= _QUALITY_RANK.get(b, 0) else b


def _buy_no_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY NO on this leg — the literal "Buy NO" price.

    Prefer Kalshi's reported `no_ask_c`; fall back to the structural identity `100 - yes_bid_c`
    when the NO field is absent (on Kalshi's unified book the two are equal by construction)."""
    api = _num(row.get("no_ask_c"))
    if api is not None:
        return api
    yb = _num(row.get("yes_bid_c"))
    return (100 - yb) if yb is not None else None


def _is_active(row: dict[str, Any]) -> bool:
    """Whether a leg's market is currently open for trading (Kalshi `status` == 'active')."""
    return str(row.get("status") or "") == "active"


def _rule_flag(child: dict[str, Any], parent: dict[str, Any]) -> tuple[str, str]:
    """Rule compatibility for an equivalence pair: (flag, note)."""
    cr = str(child.get("rules_primary") or "").lower()
    pr = str(parent.get("rules_primary") or "").lower()
    c_tokens = {t for t in _RULE_TOKENS if t in cr}
    p_tokens = {t for t in _RULE_TOKENS if t in pr}
    if c_tokens != p_tokens:
        diff = sorted(c_tokens.symmetric_difference(p_tokens))
        return "RULE_MISMATCH", f"settlement nuance differs: {', '.join(diff)}"
    return "RULE_CHECK_REQUIRED", "rules not auto-verified"


def _classify(
    child: dict[str, Any], parent: dict[str, Any], equivalence: bool
) -> dict[str, Any]:
    """Compare a child (deeper) against a parent (broader). Executable and display tests are
    independent: a missing display blocks only the display test; a missing firm bid/ask or
    size blocks only the executable test."""
    cd, pd_ = _num(child.get("display_c")), _num(parent.get("display_c"))

    # --- executable test: firm legs + positive sizes only ---
    # Track each direction's evidence so the reason always quotes the winning direction's legs
    # (equivalence checks both ways; a reverse cross must not be described as a forward one).
    # Each candidate also carries how to ACT on it: the forward cross is exploited by going
    # long the broader leg / short the deeper leg; the reverse (equivalence-only) cross is the
    # mirror. The trade construction is derived from whichever candidate wins — never hardcoded.
    candidates: list[dict[str, Any]] = []
    cb, cbs = _leg(child, "bid")
    pa, pas = _leg(parent, "ask")
    if cb is not None and pa is not None:
        candidates.append({
            "gap": cb - pa, "sizes_ok": _pos(cbs) and _pos(pas),
            "frag": f"child bid {cb}c > parent ask {pa}c", "sizes": f"{cbs}/{pas}",
            "min_size": _min_size(cbs, pas),
            "direction_label": "Long broader / short deeper",
            "long_side": "parent", "long_ask_c": pa,    # buy YES on the broader leg @ its ask
            "short_side": "child", "short_bid_c": cb,   # short (buy NO) the deeper leg vs its bid
        })
    if equivalence:
        pb, pbs = _leg(parent, "bid")
        ca, cas = _leg(child, "ask")
        if pb is not None and ca is not None:
            candidates.append({
                "gap": pb - ca, "sizes_ok": _pos(pbs) and _pos(cas),
                "frag": f"parent bid {pb}c > child ask {ca}c", "sizes": f"{pbs}/{cas}",
                "min_size": _min_size(pbs, cas),
                "direction_label": "Long deeper / short broader",
                "long_side": "child", "long_ask_c": ca,   # buy YES on the deeper leg @ its ask
                "short_side": "parent", "short_bid_c": pb, # short (buy NO) the broader leg vs its bid
            })

    exec_evaluable = bool(candidates)
    best = max(candidates, key=lambda c: c["gap"]) if candidates else None
    exec_gap = best["gap"] if best else None
    sizes_ok = best["sizes_ok"] if best else False

    # --- display test ---
    display_evaluable = cd is not None and pd_ is not None
    display_gap = (cd - pd_) if display_evaluable else None
    display_violation = display_evaluable and display_gap > DISPLAY_TOL_C

    cq, pq = child.get("quote_quality", ""), parent.get("quote_quality", "")
    worst = _worst_quality(cq, pq)

    # --- precedence ---
    if exec_evaluable and exec_gap > 0 and sizes_ok:
        status = "EXECUTABLE_VIOLATION"
        reason = f"{best['frag']} → {exec_gap}c executable cross (sizes {best['sizes']})"
    elif exec_evaluable and exec_gap > 0 and not sizes_ok:
        # Product decision (AUDIT-002): when display prices also cross, DISPLAY_VIOLATION takes
        # precedence over QUOTE_SIZE_MISSING — a display cross is the more informative signal
        # (tells the user prices look wrong AND you can't execute, not just "no size").
        if display_violation:
            status = "DISPLAY_VIOLATION"
            reason = f"prices cross {exec_gap}c but size missing/zero; display child {cd}c > parent {pd_}c"
        else:
            status = "QUOTE_SIZE_MISSING"
            reason = f"prices cross {exec_gap}c but order size missing/zero — cannot confirm executable"
    elif display_violation:
        status = "DISPLAY_VIOLATION"
        reason = f"display child {cd}c > parent {pd_}c (gap {display_gap}c); no executable cross"
    elif not exec_evaluable:
        status = "MISSING_QUOTE"
        reason = "no firm bid/ask on a leg (empty/one-sided book)"
    elif not display_evaluable:
        status = "MISSING_QUOTE"
        reason = "no display price on a leg"
    elif worst in ("Wide", "Very wide"):
        status = "WIDE_QUOTE"
        reason = f"ordering consistent but wide quote (child {cq}, parent {pq})"
    else:
        status = "CLEAN"
        reason = "child ≤ parent on executable and display"

    rule_flag, rule_note = ("", "")
    if equivalence:
        rule_flag, rule_note = _rule_flag(child, parent)
        reason = f"{reason}; {rule_note}"

    # Profit / trade-construction context for the ONE actionable status. All None otherwise so
    # the table columns stay blank and the per-player trade block renders nothing.
    exec_fields: dict[str, Any] = {
        "exec_gap_c": None, "exec_min_size": None, "exec_max_profit_dollars": None,
        "exec_direction_label": None, "exec_long_side": None, "exec_long_ask_c": None,
        "exec_short_side": None, "exec_short_bid_c": None,
    }
    if status == "EXECUTABLE_VIOLATION" and best is not None:
        gap_c, min_size = best["gap"], best.get("min_size")
        exec_fields = {
            "exec_gap_c": gap_c,
            "exec_min_size": min_size,
            "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
            "exec_direction_label": best["direction_label"],
            "exec_long_side": best["long_side"],
            "exec_long_ask_c": best["long_ask_c"],
            "exec_short_side": best["short_side"],
            "exec_short_bid_c": best["short_bid_c"],
        }

    # --- Buy-only action plan (Buy YES on one leg, Buy NO on the other) ----------------
    # Every actionable inconsistency is expressed as two BUYS — never "sell"/"long"/"short".
    # Direction follows the winning firm cross when one exists (gap > 0); otherwise it defaults to
    # the forward containment direction (Buy YES the broader/parent, Buy NO the deeper/child), which
    # is what a display-only inconsistency implies.
    firm_cross = exec_evaluable and exec_gap is not None and exec_gap > 0
    action_fields = {
        "action_1_side": None, "action_1_leg": None, "action_1_price_c": None,
        "action_2_side": None, "action_2_leg": None, "action_2_price_c": None,
    }
    if status in ACTION_STATUSES:
        if firm_cross and best is not None:
            long_leg, short_leg = best["long_side"], best["short_side"]
        else:
            long_leg, short_leg = "parent", "child"
        long_row = parent if long_leg == "parent" else child
        short_row = child if short_leg == "child" else parent
        action_fields = {
            "action_1_side": "buy_yes", "action_1_leg": long_leg,
            "action_1_price_c": _num(long_row.get("yes_ask_c")),
            "action_2_side": "buy_no", "action_2_leg": short_leg,
            "action_2_price_c": _buy_no_c(short_row),
        }

    # --- Tradable now? + plain-English blockers ---------------------------------------
    both_active = _is_active(child) and _is_active(parent)
    if status == "EXECUTABLE_VIOLATION" and both_active:
        tradable_now = "Yes — rule-dependent" if rule_flag else "Yes"
    else:
        tradable_now = "No"

    blockers: list[str] = []
    if status in ACTION_STATUSES:
        if status == "QUOTE_SIZE_MISSING" or (firm_cross and not sizes_ok):
            blockers.append(BLOCKERS["size_missing"])
        elif status == "DISPLAY_VIOLATION":
            blockers.append(BLOCKERS["display_only"])
        for leg_label, row in (("broader", parent), ("deeper", child)):
            q = row.get("quote_quality")
            if q in ("No quote", "One-sided"):
                blockers.append(BLOCKERS["no_quote"].format(leg=leg_label))
            elif q == "Crossed":
                blockers.append(BLOCKERS["crossed"].format(leg=leg_label))
            s = str(row.get("status") or "")
            if s and s != "active":
                blockers.append(BLOCKERS["inactive"].format(leg=leg_label, status=s))
        if rule_flag:
            blockers.append(BLOCKERS["rule"])

    watchlist_note = WATCHLIST_NOTE if status == "WIDE_QUOTE" else ""

    return {
        "status": status,
        "status_group": STATUS_GROUP[status],
        "rule_flag": rule_flag,
        "reason": reason,
        "executable_gap": exec_gap if exec_evaluable else None,
        "display_gap": display_gap,
        "quote_quality": worst,
        "tradable_now": tradable_now,
        "blockers": "; ".join(blockers),
        "watchlist_note": watchlist_note,
        **exec_fields,
        **action_fields,
    }


def _buy_text(side: str | None, leg: str | None, price_c: Any,
              child_contract: str, parent_contract: str) -> str:
    """Compose the buy-only action line, e.g. 'Buy YES — Reach Final @ 46¢'. '' when no action."""
    if side is None or leg is None:
        return ""
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    contract = parent_contract if leg == "parent" else child_contract
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract} @ {price}"


def _row(player: str, player_key: str, chain: str, child: dict | None, parent: dict | None, comp: dict,
         child_node: str = "", parent_node: str = "", tournament: str = "",
         relationship_type: str = "", opp_id: str = "") -> dict:
    """Assemble one consistency-table row.

    `relationship_type` (`containment_adjacent` | `match_alignment`) and `opp_id` (a stable
    `data.opportunity_id`) are stamped by `build_checks`. `bucket` and the REQUIRED `blocked_reason`
    are derived here from the assembled row: `blocked_reason` is non-empty IFF the row's dashboard
    bucket is `blocked` (Stage 1 invariant), reusing the plain-English `blockers` text."""
    vols = [r.get("volume") for r in (child, parent) if r and r.get("volume") is not None]
    # Time-to-resolution: the EARLIER of the two legs' times — the soonest the opportunity starts
    # settling (capital frees / the edge expires). ISO-8601 strings sort chronologically.
    times = [r.get("time_value") for r in (child, parent) if r and r.get("time_value")]
    resolve_time = min(times) if times else None
    child_contract = child.get("contract") if child else ""
    parent_contract = parent.get("contract") if parent else ""
    a1_leg, a2_leg = comp.get("action_1_leg"), comp.get("action_2_leg")
    # Market-universe fields (for dashboard filters). `tournament` is the group key (passed in, so it's
    # correct even when both legs are missing); tour/competition come off whichever leg exists.
    tour = (child or parent or {}).get("tour", "") if (child or parent) else ""
    competition = (child or parent or {}).get("competition", "") if (child or parent) else ""
    # Layers this comparison touches: the containment node names + any match-round stage.
    layer_tokens = {n for n in (child_node, parent_node) if n}
    for r in (child, parent):
        if r and r.get("kind") == "match" and r.get("stage"):
            layer_tokens.add(r.get("stage"))
    result = {
        "player": player,
        "player_key": player_key,
        "chain": chain,
        "relationship_type": relationship_type,
        "opportunity_id": opp_id,
        "tour": tour,
        "competition": competition,
        "tournament": tournament,
        "child_node": child_node,
        "parent_node": parent_node,
        "child_event_ticker": child.get("event_ticker", "") if child else "",
        "parent_event_ticker": parent.get("event_ticker", "") if parent else "",
        "layers": tuple(sorted(layer_tokens)),
        "child_contract": child_contract,
        "parent_contract": parent_contract,
        "child_display_pct": child.get("display_pct") if child else None,
        "parent_display_pct": parent.get("display_pct") if parent else None,
        "child_bid_pct": child.get("yes_bid_pct") if child else None,
        "parent_ask_pct": parent.get("yes_ask_pct") if parent else None,
        "executable_gap": comp.get("executable_gap"),
        "display_gap": comp.get("display_gap"),
        "status": comp["status"],
        "status_group": comp["status_group"],
        "rule_flag": comp.get("rule_flag", ""),
        "reason": comp["reason"],
        "volume": min(vols) if vols else None,
        "resolve_time": resolve_time,
        "comp_quote_quality": comp.get("quote_quality", ""),
        "child_status": child.get("status") if child else "",
        "parent_status": parent.get("status") if parent else "",
        # Buy-only action plan + tradability (populated for inconsistency statuses).
        "tradable_now": comp.get("tradable_now", "No"),
        "blockers": comp.get("blockers", ""),
        "watchlist_note": comp.get("watchlist_note", ""),
        "action_1_side": comp.get("action_1_side"),
        "action_1_leg": a1_leg,
        "action_1_price_c": comp.get("action_1_price_c"),
        "action_1_contract": (parent_contract if a1_leg == "parent" else child_contract) if a1_leg else "",
        "action_1_text": _buy_text(comp.get("action_1_side"), a1_leg, comp.get("action_1_price_c"),
                                   child_contract, parent_contract),
        "action_2_side": comp.get("action_2_side"),
        "action_2_leg": a2_leg,
        "action_2_price_c": comp.get("action_2_price_c"),
        "action_2_contract": (parent_contract if a2_leg == "parent" else child_contract) if a2_leg else "",
        "action_2_text": _buy_text(comp.get("action_2_side"), a2_leg, comp.get("action_2_price_c"),
                                   child_contract, parent_contract),
        # Profit / trade-construction context (populated only for EXECUTABLE_VIOLATION).
        "exec_gap_c": comp.get("exec_gap_c"),
        "exec_min_size": comp.get("exec_min_size"),
        "exec_max_profit_dollars": comp.get("exec_max_profit_dollars"),
        "exec_direction_label": comp.get("exec_direction_label"),
        "exec_long_side": comp.get("exec_long_side"),
        "exec_long_ask_c": comp.get("exec_long_ask_c"),
        "exec_short_side": comp.get("exec_short_side"),
        "exec_short_bid_c": comp.get("exec_short_bid_c"),
        "child_ticker": child.get("market_ticker") if child else "",
        "parent_ticker": parent.get("market_ticker") if parent else "",
        "child_url": child.get("kalshi_url") if child else "",
        "parent_url": parent.get("kalshi_url") if parent else "",
        "child_category": CATEGORY.get(child.get("kind")) if child else "",
        "parent_category": CATEGORY.get(parent.get("kind")) if parent else "",
    }
    # Dashboard bucket + REQUIRED blocked_reason (Stage 1): blocked_reason is non-empty IFF the row is
    # bucketed `blocked`. Reuse the plain-English `blockers`; fall back to a generic reason if a blocked
    # row somehow carries none (keeps the iff-invariant total).
    bucket = bucket_of(result)
    result["bucket"] = bucket
    result["blocked_reason"] = (result.get("blockers") or "not executable now") if bucket == "blocked" else ""
    return result


def build_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Build the full layer-consistency table from the per-player contract DataFrame."""
    columns = [
        "player", "player_key", "chain",
        "relationship_type", "opportunity_id", "bucket", "blocked_reason",
        "tour", "competition", "child_node", "parent_node",
        "child_event_ticker", "parent_event_ticker", "layers",
        "child_contract", "parent_contract", "child_display_pct",
        "parent_display_pct", "child_bid_pct", "parent_ask_pct", "executable_gap",
        "display_gap", "status", "status_group", "rule_flag", "reason", "volume",
        "resolve_time", "comp_quote_quality", "child_status", "parent_status", "tournament",
        "tradable_now", "blockers", "watchlist_note",
        "action_1_side", "action_1_leg", "action_1_price_c", "action_1_contract", "action_1_text",
        "action_2_side", "action_2_leg", "action_2_price_c", "action_2_contract", "action_2_text",
        "exec_gap_c", "exec_min_size", "exec_max_profit_dollars",
        "exec_direction_label", "exec_long_side", "exec_long_ask_c", "exec_short_side",
        "exec_short_bid_c", "child_ticker", "parent_ticker", "child_url", "parent_url",
        "child_category", "parent_category",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    # A competitor can appear in more than one tournament (same UUID across events); group by
    # (player_key, tournament) so containment ladders never mix across tournaments. `tournament` is a
    # never-empty key from data.tournament_of; guard for unit-test frames that don't carry it.
    if "tournament" not in df.columns:
        df = df.assign(tournament="")

    out: list[dict] = []
    # Group by the STABLE player_key (never the display name) AND tournament: two distinct competitors
    # who share a display name must not merge, and one competitor's two tournaments must not merge.
    for (player_key, _tournament), group in df.groupby(["player_key", "tournament"]):
        rows = group.to_dict("records")
        player = rows[0].get("player", "") if rows else ""  # display label
        nodes = build_player_nodes(rows)
        if not nodes:
            continue
        # The containment ladder is per-sport — resolve it from this group's series.
        cfg = _sport_for_rows(rows)
        ladder = cfg.ladder

        # Adjacent containment pairs (market sources only). Id recipe: the relationship type + the
        # stable (player_key, tournament) group + the node pair — unique per group since each adjacent
        # pair is checked once, and node-based (not ticker-based) so the id survives a representative
        # flip between refreshes (same logical opportunity).
        for child_node, parent_node in ladder.adjacent_pairs:
            child = nodes.get(child_node, {}).get("market")
            parent = nodes.get(parent_node, {}).get("market")
            chain = f"{child_node} ≤ {parent_node}"
            rel = "containment_adjacent"
            oid = opportunity_id(rel, player_key, _tournament, child_node, parent_node)
            if child is None or parent is None:
                missing = child_node if child is None else parent_node
                comp = {
                    "status": "MISSING_LAYER",
                    "status_group": STATUS_GROUP["MISSING_LAYER"],
                    "rule_flag": "",
                    "reason": f"missing market layer: {missing}",
                    "executable_gap": None,
                    "display_gap": None,
                    "quote_quality": "",
                }
                out.append(_row(player, player_key, chain, child, parent, comp,
                                child_node=child_node, parent_node=parent_node, tournament=_tournament,
                                relationship_type=rel, opp_id=oid))
            else:
                out.append(_row(player, player_key, chain, child, parent, _classify(child, parent, False),
                                child_node=child_node, parent_node=parent_node, tournament=_tournament,
                                relationship_type=rel, opp_id=oid))

        # Match-alignment (equivalence) rows where both a market and a confident match exist. One
        # equivalence per node (build_player_nodes keeps a single representative per source), so the
        # node alone disambiguates within the group.
        for node, sources in nodes.items():
            if "market" in sources and "match" in sources:
                match_row, market_row = sources["match"], sources["market"]
                chain = f"{match_row.get('stage')} win ≡ {node}"
                rel = "match_alignment"
                oid = opportunity_id(rel, player_key, _tournament, node, node)
                out.append(_row(player, player_key, chain, match_row, market_row,
                                _classify(match_row, market_row, True),
                                child_node=node, parent_node=node, tournament=_tournament,
                                relationship_type=rel, opp_id=oid))

        # Surface match contracts whose round does NOT map to a tracked layer (e.g. R16) as
        # UNKNOWN_RELATIONSHIP so they are acknowledged, never silently treated as violations.
        for row in rows:
            if row.get("kind") == cfg.match_family and row.get("stage") not in ladder.match_stage_to_node:
                comp = {
                    "status": "UNKNOWN_RELATIONSHIP",
                    "status_group": STATUS_GROUP["UNKNOWN_RELATIONSHIP"],
                    "rule_flag": "",
                    "reason": f"match round '{row.get('stage') or 'unknown'}' has no tracked containment layer",
                    "executable_gap": None,
                    "display_gap": None,
                    "quote_quality": row.get("quote_quality", ""),
                }
                # These are match-derived rows with no mapped node, so the node-pair recipe would
                # collide across several unmapped matches for one player. Disambiguate on the match's
                # own (stable) event ticker; classify as match_alignment (the relationship we would
                # have checked had the round mapped).
                rel = "match_alignment"
                oid = opportunity_id(rel, player_key, _tournament,
                                     f"unmapped:{row.get('event_ticker', '')}:{row.get('stage', '')}")
                out.append(_row(player, player_key, f"{row.get('stage') or '?'} match", row, None, comp,
                                tournament=_tournament, relationship_type=rel, opp_id=oid))

    return pd.DataFrame(out, columns=columns)


def scenario_payoffs(check_row: dict[str, Any], units: Any = None) -> dict[str, Any] | None:
    """Per-unit settlement-scenario payoffs for an opportunity's two-buy position.

    Every actionable inconsistency is a pair of BUYS — Buy YES on one leg, Buy NO on the other —
    and each contract settles to exactly 100c (its outcome happens) or 0c (it doesn't). This
    enumerates the terminal states and reports, per single unit (one YES + one NO), the up-front
    `cost_c`, the `payout_c` in each state, and the `profit_c` (= payout − cost). It makes the
    edge concrete: you can see the money in every outcome, and the worst row is the guaranteed floor.

    Two shapes, distinguished by `rule_flag` (set only for match-alignment equivalence pairs):

    - **containment** (broader ⊇ deeper): THREE distinct states. The two 100c states are the
      guaranteed floor; the broader-but-not-deeper state pays an extra $1 — a directional BONUS,
      not the edge. The worst-case profit equals the engine's `exec_gap_c` by construction.
    - **equivalence** (the two legs are the same event): TWO aligned states that both pay the floor,
      PLUS a 'rules diverge' RISK state whose payout is NOT guaranteed (the legs may settle
      differently on walkover/retire nuance — the existing RULE_CHECK_REQUIRED caveat). Its payout
      and profit are left None so we never imply a guaranteed number where the rules are unverified.

    Returns None when the row carries no buy-only action plan. `cost_c`/`profit_c`/`roc_pct` are
    None when a leg price is missing (e.g. a display-only row with no firm ask to buy at).

    When `units` (the tradable size) is given, also reports `capital_c` (= cost × units, what you
    stake) and `total_floor_profit_c` (= worst-case × units, the guaranteed take); both None if the
    per-unit number or `units` is missing.
    """
    if check_row.get("status") not in ACTION_STATUSES:
        return None
    if check_row.get("action_1_side") != "buy_yes" or check_row.get("action_2_side") != "buy_no":
        return None

    yes_price = _num(check_row.get("action_1_price_c"))   # cost to Buy YES on the long leg @ its ask
    no_price = _num(check_row.get("action_2_price_c"))    # cost to Buy NO on the short leg @ the NO ask
    cost_c = (yes_price + no_price) if (yes_price is not None and no_price is not None) else None

    equivalence = bool(check_row.get("rule_flag"))

    def _scn(label: str, yes_pay: int | None, no_pay: int | None,
             *, bonus: bool = False, risk: bool = False) -> dict[str, Any]:
        payout = None if risk else (yes_pay + no_pay)
        profit = (payout - cost_c) if (payout is not None and cost_c is not None) else None
        return {
            "label": label,
            "yes_leg_payout_c": None if risk else yes_pay,
            "no_leg_payout_c": None if risk else no_pay,
            "payout_c": payout,
            "profit_c": profit,
            "is_bonus": bonus,
            "is_risk": risk,
            "is_guaranteed_floor": False,   # set below once worst-case is known
        }

    if equivalence:
        # The two legs settle on the same underlying outcome; use the node name as its label.
        event = check_row.get("parent_node") or check_row.get("child_node") or "the outcome"
        scenarios = [
            _scn(f"{event} (legs settle aligned)", 100, 0),
            _scn(f"Not {event} (legs settle aligned)", 0, 100),
            _scn("Settlement rules diverge (not auto-verified)", None, None, risk=True),
        ]
        kind = "equivalence"
    else:
        # Containment: action is always Buy YES the broader (parent), Buy NO the deeper (child).
        broader = check_row.get("parent_node") or "the broader outcome"
        deeper = check_row.get("child_node") or "the deeper outcome"
        scenarios = [
            _scn(f"{deeper}", 100, 0),
            _scn(f"{broader}, not {deeper}", 100, 100, bonus=True),
            _scn(f"Not {broader}", 0, 100),
        ]
        kind = "containment"

    # Worst/best across the GUARANTEED (non-risk) states only — the rule-risk state is unknown,
    # never counted as a floor.
    guaranteed = [s["profit_c"] for s in scenarios if not s["is_risk"] and s["profit_c"] is not None]
    worst = min(guaranteed) if guaranteed else None
    best = max(guaranteed) if guaranteed else None
    if worst is not None:
        for s in scenarios:
            if not s["is_risk"] and s["profit_c"] == worst:
                s["is_guaranteed_floor"] = True

    roc_pct = round(worst / cost_c * 100, 1) if (worst is not None and cost_c) else None

    units = _num(units)
    capital_c = (cost_c * units) if (cost_c is not None and units is not None) else None
    total_floor_profit_c = (worst * units) if (worst is not None and units is not None) else None

    return {
        "kind": kind,
        "cost_c": cost_c,
        "scenarios": scenarios,
        "worst_case_profit_c": worst,
        "best_case_profit_c": best,
        "roc_pct": roc_pct,
        "has_rule_risk": equivalence,
        "units": units,
        "capital_c": capital_c,
        "total_floor_profit_c": total_floor_profit_c,
    }


# Trader-dashboard buckets. Pure mapping from one consistency-check row to the dashboard section it
# belongs in — reads only fields already produced by build_checks; no math, no side effects.
DASHBOARD_BUCKETS = (
    "actionable", "blocked", "near_edge", "display_signal", "wide_signal", "data_quality", "clean",
)


def bucket_of(check_row: dict[str, Any]) -> str:
    """Classify a check row into a dashboard bucket (see DASHBOARD_BUCKETS).

    - actionable     : firm executable cross that is tradable now (incl. rule-dependent, shown with a caveat)
    - blocked        : a real/firm cross that cannot be traded now (no size, or an inactive/finalized leg)
    - near_edge      : consistent but within NEAR_EDGE_MIN_C cents of crossing, on Tight/OK quotes
    - display_signal : display-only inconsistency (DISPLAY_VIOLATION)
    - wide_signal    : ordering consistent but the quote is wide (WIDE_QUOTE)
    - data_quality   : missing firm quote / missing layer / unverifiable relationship
    - clean          : consistent and not near the edge
    """
    status = check_row.get("status")
    if status in ("EXECUTABLE_VIOLATION", "EXECUTABLE_DUTCH_BOOK"):
        # Both are firm executable edges: tradable now -> actionable, else blocked (no size / inactive
        # leg). A dutch book carries no rule caveat, so its tradable_now is a plain Yes/No.
        return "actionable" if str(check_row.get("tradable_now") or "").startswith("Yes") else "blocked"
    if status == "QUOTE_SIZE_MISSING":
        return "blocked"
    if status == "DISPLAY_VIOLATION":
        return "display_signal"
    if status == "WIDE_QUOTE":
        return "wide_signal"
    if status in ("MISSING_QUOTE", "MISSING_LAYER", "UNKNOWN_RELATIONSHIP"):
        return "data_quality"
    if status == "CLEAN":
        gap = _num(check_row.get("executable_gap"))
        if gap is not None and NEAR_EDGE_MIN_C <= gap <= 0 and check_row.get("comp_quote_quality") in ("Tight", "OK"):
            return "near_edge"
        return "clean"
    return "data_quality"
