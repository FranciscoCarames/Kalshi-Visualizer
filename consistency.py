"""Layer-consistency checker for French Open per-player contracts.

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

from config import DISPLAY_TOL_C
from data import CATEGORY

# Canonical containment ladder, broad -> deep. A deeper node is a subset of the broader one.
NODE_ORDER = ["Reach Semifinal", "Reach Final", "Win Tournament"]
# Adjacent (child = deeper, parent = broader): child price must be <= parent price.
ADJACENT_PAIRS = [("Win Tournament", "Reach Final"), ("Reach Final", "Reach Semifinal")]
# Winning your current match <=> reaching the next stage (only when the round maps confidently).
MATCH_STAGE_TO_NODE = {
    "Quarterfinal": "Reach Semifinal",
    "Semifinal": "Reach Final",
    "Final": "Win Tournament",
}
ADVANCE_STAGE_TO_NODE = {"Semifinal": "Reach Semifinal", "Final": "Reach Final"}

# Settlement-rule nuance tokens; a difference between two markets means the equivalence may
# not hold exactly (e.g. walkover / "ball has been played" handling differs).
_RULE_TOKENS = ["ball has been played", "walkover", "retire", "withdraw", "forfeit", "cancel"]

_QUALITY_RANK = {"Tight": 0, "OK": 1, "Wide": 2, "Very wide": 3, "One-sided": 4, "No quote": 5}

STATUS_GROUP = {
    "CLEAN": "Clean",
    "EXECUTABLE_VIOLATION": "Broken",
    "DISPLAY_VIOLATION": "Warning",
    "WIDE_QUOTE": "Warning",
    "MISSING_QUOTE": "Missing data",
    "MISSING_LAYER": "Missing data",
    "QUOTE_SIZE_MISSING": "Missing data",
    "UNKNOWN_RELATIONSHIP": "Unknown relationship",
}


def node_of(row: dict[str, Any]) -> str | None:
    """Map a contract row to its containment node, or None if it doesn't map confidently."""
    kind = row.get("kind")
    if kind == "winner":
        return "Win Tournament"
    if kind == "advance":
        return ADVANCE_STAGE_TO_NODE.get(row.get("stage"))
    if kind == "match":
        return MATCH_STAGE_TO_NODE.get(row.get("stage"))
    return None


def build_player_nodes(player_rows: list[dict[str, Any]]) -> dict[str, dict[str, dict]]:
    """Group a player's contracts into {node: {"market": row?, "match": row?}}."""
    nodes: dict[str, dict[str, dict]] = {}
    for row in player_rows:
        node = node_of(row)
        if not node:
            continue
        source = "match" if row.get("kind") == "match" else "market"
        nodes.setdefault(node, {})[source] = row
    return nodes


def expected_nodes(player_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit expected-vs-found ladder for a player.

    For any player that appears in the French Open data we expect the full progression ladder
    (Reach Semifinal, Reach Final, Win Tournament) to be quotable; this makes a missing layer
    explicit rather than implied-by-omission. `source` is "market" (advance/winner), "match"
    (a confident match-implied node), or "" when absent.
    """
    nodes = build_player_nodes(player_rows)
    out: list[dict[str, Any]] = []
    for node in NODE_ORDER:
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


def _leg(row: dict[str, Any], side: str) -> tuple[int | None, Any]:
    """Return (cents, size) for a contract's firm bid/ask side.

    An empty 0/1 book ("No quote") has no real order on either side.
    """
    if row.get("quote_quality") == "No quote":
        return None, None
    if side == "bid":
        return row.get("yes_bid_c"), row.get("yes_bid_size")
    return row.get("yes_ask_c"), row.get("yes_ask_size")


def _worst_quality(a: str, b: str) -> str:
    return a if _QUALITY_RANK.get(a, 0) >= _QUALITY_RANK.get(b, 0) else b


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
    cd, pd_ = child.get("display_c"), parent.get("display_c")

    # --- executable test: firm legs + positive sizes only ---
    directions: list[tuple[int, bool]] = []
    cb, cbs = _leg(child, "bid")
    pa, pas = _leg(parent, "ask")
    if cb is not None and pa is not None:
        directions.append((cb - pa, _pos(cbs) and _pos(pas)))
    if equivalence:
        pb, pbs = _leg(parent, "bid")
        ca, cas = _leg(child, "ask")
        if pb is not None and ca is not None:
            directions.append((pb - ca, _pos(pbs) and _pos(cas)))

    exec_evaluable = bool(directions)
    exec_gap, sizes_ok = (max(directions, key=lambda d: d[0]) if directions else (None, False))

    # --- display test ---
    display_evaluable = cd is not None and pd_ is not None
    display_gap = (cd - pd_) if display_evaluable else None
    display_violation = display_evaluable and display_gap > DISPLAY_TOL_C

    cq, pq = child.get("quote_quality", ""), parent.get("quote_quality", "")
    worst = _worst_quality(cq, pq)

    # --- precedence ---
    if exec_evaluable and exec_gap > 0 and sizes_ok:
        status = "EXECUTABLE_VIOLATION"
        reason = f"child bid {cb}c > parent ask {pa}c → {exec_gap}c executable cross (sizes {cbs}/{pas})"
    elif exec_evaluable and exec_gap > 0 and not sizes_ok:
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

    return {
        "status": status,
        "status_group": STATUS_GROUP[status],
        "rule_flag": rule_flag,
        "reason": reason,
        "executable_gap": exec_gap if exec_evaluable else None,
        "display_gap": display_gap,
        "quote_quality": worst,
    }


def _row(player: str, chain: str, child: dict | None, parent: dict | None, comp: dict) -> dict:
    """Assemble one consistency-table row."""
    vols = [r.get("volume") for r in (child, parent) if r and r.get("volume") is not None]
    return {
        "player": player,
        "chain": chain,
        "child_contract": child.get("contract") if child else "",
        "parent_contract": parent.get("contract") if parent else "",
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
        "comp_quote_quality": comp.get("quote_quality", ""),
        "child_ticker": child.get("market_ticker") if child else "",
        "parent_ticker": parent.get("market_ticker") if parent else "",
        "child_url": child.get("kalshi_url") if child else "",
        "parent_url": parent.get("kalshi_url") if parent else "",
        "child_category": CATEGORY.get(child.get("kind")) if child else "",
        "parent_category": CATEGORY.get(parent.get("kind")) if parent else "",
    }


def build_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Build the full layer-consistency table from the per-player contract DataFrame."""
    columns = [
        "player", "chain", "child_contract", "parent_contract", "child_display_pct",
        "parent_display_pct", "child_bid_pct", "parent_ask_pct", "executable_gap",
        "display_gap", "status", "status_group", "rule_flag", "reason", "volume",
        "comp_quote_quality", "child_ticker", "parent_ticker", "child_url", "parent_url",
        "child_category", "parent_category",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    out: list[dict] = []
    for player, group in df.groupby("player"):
        rows = group.to_dict("records")
        nodes = build_player_nodes(rows)
        if not nodes:
            continue

        # Adjacent containment pairs (market sources only).
        for child_node, parent_node in ADJACENT_PAIRS:
            child = nodes.get(child_node, {}).get("market")
            parent = nodes.get(parent_node, {}).get("market")
            chain = f"{child_node} ≤ {parent_node}"
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
                out.append(_row(player, chain, child, parent, comp))
            else:
                out.append(_row(player, chain, child, parent, _classify(child, parent, False)))

        # Match-alignment (equivalence) rows where both a market and a confident match exist.
        for node, sources in nodes.items():
            if "market" in sources and "match" in sources:
                match_row, market_row = sources["match"], sources["market"]
                chain = f"{match_row.get('stage')} win ≡ {node}"
                out.append(_row(player, chain, match_row, market_row, _classify(match_row, market_row, True)))

        # Surface match contracts whose round does NOT map to a tracked layer (e.g. R16) as
        # UNKNOWN_RELATIONSHIP so they are acknowledged, never silently treated as violations.
        for row in rows:
            if row.get("kind") == "match" and row.get("stage") not in MATCH_STAGE_TO_NODE:
                comp = {
                    "status": "UNKNOWN_RELATIONSHIP",
                    "status_group": STATUS_GROUP["UNKNOWN_RELATIONSHIP"],
                    "rule_flag": "",
                    "reason": f"match round '{row.get('stage') or 'unknown'}' has no tracked containment layer",
                    "executable_gap": None,
                    "display_gap": None,
                    "quote_quality": row.get("quote_quality", ""),
                }
                out.append(_row(player, f"{row.get('stage') or '?'} match", row, None, comp))

    return pd.DataFrame(out, columns=columns)
