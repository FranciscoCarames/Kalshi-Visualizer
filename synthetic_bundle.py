"""Synthetic exact-score / state-bundle discrepancy detector (Stage m5).

A synthetic bundle replicates a player's "wins" outcome from the MECE set of exact-set-score contracts
(men's best-of-5 → {3-0, 3-1, 3-2}; women's/best-of-3 → {2-0, 2-1}) and prices it against a broader
**hedge** — here the same match's **match-winner** market (the spike-proven, reliably-joinable hedge; the
reach-next-round advance hedge is a later PR). Two directions, both pairs/sets of BUYS:

  * **forward** — Buy YES on every score state + Buy NO on the hedge. Pays 100¢ in every normal covered
    outcome, so it is a gross discrepancy when ``Σ yes_ask(states) + no_ask(hedge) < 100¢``.
  * **reverse** — Buy NO on every score state + Buy YES on the hedge. With ``N`` states this pays
    ``N×100¢`` in every covered outcome, so the condition is ``Σ no_ask(states) + yes_ask(hedge) < N×100¢``.

It is a **gross pricing discrepancy, NEVER riskless**: an exact score is not equivalent to the
match-winner, and on a retirement / no-ball-played the score legs resolve to Fair Market Price while the
hedge settles cleanly (verified live). So every finding carries a settlement caveat — `rule_flag =
"SETTLEMENT_CHECK_REQUIRED"`, `tradable_now = "Review rules"` — and is routed review/blocked, **never
Actionable**. Labels say gross / top-of-book (full-depth fill + fees not modeled).

Gates before any emit (any failure → silent skip, never a false positive):
  1. **Format proven** — the expected state set comes from a verified signal (division + tournament), not
     the discovered markets (`expected_states`); unprovable → skip.
  2. **Exhaustive** — the per-player found state set (grouped by `player_key` UUID) == the expected set;
     missing / duplicate / extra → skip.
  3. **Hedge present + same round** — a match-winner row for the player in the same match (joined by the
     event's player-key set); a stage/round mismatch is a hard rules-conflict → skip.
  4. **Bundle proven SAFE (`_unsafe_reason`)** — three hard suppression gates that prove a bundle's legs
     cannot settle as a clean 0-or-100¢ MECE set, applied to the score legs + hedge together. Each only
     suppresses on PROVEN-unsafe evidence (absent metadata never suppresses — a legacy/sparse row passes):
       a. **Per-leg binary settlement** — any leg whose `market_type` is present and ≠ ``"binary"`` can
          settle scalar / fair-price, breaking the bundle math (`fractional_trading_enabled` is True for
          normal exact-score markets, so it is NOT a gate — only `market_type` is).
       b. **Close-time sync** — the legs must close/resolve at ~the same time (within
          ``_CLOSE_TIME_TOLERANCE_S``) to settle together; clearly-divergent `close_time` → suppress.
       c. **Settlement-rule divergence** — a divergent `data.rule_tokens(rules_primary)` set across the
          legs (one voids on retirement, another doesn't) is a hard mismatch → suppress. (The residual
          matching-but-unverified case keeps the always-present `SETTLEMENT_CHECK_REQUIRED` caveat.)
     A suppressed bundle is recorded in the optional `_diag` (Debug / live smoke), never shown.
  5. **Firm executable ask per leg** for a direction; a leg priced but with no size / inactive → the
     finding is emitted **blocked/review** (visible), not dropped.

NO streamlit / pandas imports — independently testable. Exact-score shape (verified live, French Open
2026): ``custom_strike = {"Set Score": "3-0", "tennis_competitor": "<uuid>"}``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import data
import sports
from glossary import BLOCKERS

# The one status this module emits (mirrors dutchbook's EXECUTABLE_DUTCH_BOOK literal-kept pattern).
EXECUTABLE_SYNTHETIC_BUNDLE = "EXECUTABLE_SYNTHETIC_BUNDLE"
CHECK_TYPE = "synthetic_bundle"

# A set score is "<sets won by winner>-<sets won by loser>", each a single digit (0–3 in practice).
_SCORELINE_RE = re.compile(r"\b([0-9])\s*-\s*([0-9])\b")
_NO_FIRM_QUALITY = ("No quote", "Crossed")  # a leg with this quote has no usable resting order

# Legs of one bundle must settle together for the hedge to hold. `close_time` is the SCHEDULED close,
# identical across markets of the same match, so a generous tolerance suppresses only clearly-different
# times (different match / day) while never false-suppressing a real same-match bundle (6h ≫ any match).
_CLOSE_TIME_TOLERANCE_S = 6 * 3600


# ============================================================================================
# Parsing + format layer (Task 2)
# ============================================================================================
def parse_scoreline(row: dict[str, Any]) -> str | None:
    """The exact-set-score state for one market, normalized to ``"<w>-<l>"`` (e.g. ``"3-0"``), or None.

    Primary source is the **structured** ``custom_strike["Set Score"]`` (stamped onto the row as
    ``raw_custom_strike`` by ``data.build_contracts`` — verified live). Falls back to a regex over the
    display subtitle ("Jakub Mensik wins 3-0") so a market missing the strike field still parses.
    """
    cs = row.get("raw_custom_strike")
    raw = cs.get("Set Score") if isinstance(cs, dict) else None
    if not raw:
        for text in (row.get("yes_sub_title"), row.get("player_name_raw"), row.get("contract")):
            if text:
                m = _SCORELINE_RE.search(str(text))
                if m:
                    return f"{m.group(1)}-{m.group(2)}"
        return None
    m = _SCORELINE_RE.search(str(raw))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def expected_states(cfg: Any, division: str, tournament: str) -> tuple[str, ...] | None:
    """The per-player **expected** exact-score set for an event, or None when the format is unprovable.

    The format is resolved from a verified *independent* signal (``division`` + ``tournament`` via the
    sport's ``score_format`` resolver), NEVER from the discovered markets — otherwise the downstream
    completeness check (found == expected) would be circular. A ``None`` here means "do not emit".
    """
    fmt = cfg.score_format(division, tournament)
    return cfg.state_bundles.get(fmt) if fmt else None


# ============================================================================================
# Pricing helpers (mirrors dutchbook.py; kept local so each detector's invariants stay separate)
# ============================================================================================
def _isna(x: Any) -> bool:
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    return None if _isna(x) else x


def _pos(size: Any) -> bool:
    return size is not None and size > 0


def _firm_yes_ask_c(row: dict[str, Any]) -> int | None:
    if row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    return _num(row.get("yes_ask_c"))


def _firm_no_ask_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY NO — the real ``no_ask_c``, else the structural identity ``100 − yes_bid_c``."""
    if row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    api = _num(row.get("no_ask_c"))
    if api is not None:
        return api
    yb = _num(row.get("yes_bid_c"))
    return (100 - yb) if yb is not None else None


def _is_active(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "") == "active"


def _leg_label(row: dict[str, Any]) -> str:
    return str(row.get("player") or row.get("contract") or "this leg")


def _buy_text(side: str, contract: str, price_c: int | None) -> str:
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract} @ {price}"


# ============================================================================================
# Safety gates (PR: synthetic hardening 2) — prove the bundle's legs settle as a clean MECE set.
# Each gate suppresses ONLY on proven-unsafe evidence; absent metadata never suppresses (so a legacy
# row without the captured fields passes, preserving behavior). A suppressed bundle is recorded in
# `_diag` and never shown — distinct from the residual settlement *risk* that keeps the review caveat.
# ============================================================================================
def _record(diag: dict | None, kind: str, event_ticker: str, reason: str) -> None:
    """Fold a suppressed bundle into the optional `_diag` (Debug / live smoke). Mirrors dutchbook."""
    if diag is not None:
        diag.setdefault(kind, []).append({"event_ticker": event_ticker, "reason": reason})


def _nonbinary_leg(leg_rows: list[dict]) -> str | None:
    """The label of the first leg that can settle non-binary (scalar / fair-price), else None.

    Keys on ``market_type`` only: a value present and not ``"binary"`` proves the leg won't settle
    0-or-100¢. ``fractional_trading_enabled`` is True for normal exact-score markets (verified live), so
    it is deliberately NOT a gate. Absent/blank ``market_type`` is unprovable → not unsafe → passes.
    """
    for r in leg_rows:
        mt = str(r.get("market_type") or "").strip().lower()
        if mt and mt != "binary":
            return f"{_leg_label(r)} (market_type={mt})"
    return None


def _parse_iso(ts: Any) -> datetime | None:
    """Parse an ISO-8601 close/expiration timestamp (accepts a trailing ``Z``), else None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _close_times_diverge(leg_rows: list[dict]) -> bool:
    """True only when EVERY leg has a parseable ``close_time`` and their spread exceeds the tolerance.

    Partial / unparseable times are unprovable → False (don't suppress). Mixed tz-aware/naive raises on
    ``max`` → treated as unprovable.
    """
    times = [_parse_iso(r.get("close_time")) for r in leg_rows]
    if any(t is None for t in times) or len(times) < 2:
        return False  # can't prove divergence without a clean time on every leg
    try:
        spread = (max(times) - min(times)).total_seconds()
    except TypeError:
        return False  # mixed aware/naive — unprovable
    return spread > _CLOSE_TIME_TOLERANCE_S


def _rule_token_divergence(leg_rows: list[dict]) -> set[str]:
    """Settlement-nuance tokens NOT shared by all legs (empty = the legs agree, so no divergence).

    Reuses the shared ``data.rule_tokens`` helper. A non-empty result means at least one leg carries a
    settlement nuance (retire / walkover / cancel …) the others don't — a hard rules mismatch.
    """
    sets = [data.rule_tokens(r.get("rules_primary")) for r in leg_rows]
    union = set().union(*sets) if sets else set()
    shared = set.intersection(*sets) if sets else set()
    return union - shared


def _unsafe_reason(leg_rows: list[dict]) -> str | None:
    """The first hard-suppression reason for this bundle's legs (score legs + hedge), or None if safe."""
    label = _nonbinary_leg(leg_rows)
    if label is not None:
        return f"non-binary leg: {label}"
    if _close_times_diverge(leg_rows):
        return "legs resolve at different times"
    diff = _rule_token_divergence(leg_rows)
    if diff:
        return f"settlement-rule divergence: {', '.join(sorted(diff))}"
    return None


# ============================================================================================
# Detector (Task 3a) — match-winner hedge, both directions
# ============================================================================================
def _direction(direction: str, state_rows: list[dict], hedge_row: dict, n: int) -> dict[str, Any] | None:
    """Price one direction. Returns None when any leg lacks a firm ask (→ that direction can't emit).

    forward: Buy YES each state + Buy NO hedge, threshold 100¢. reverse: Buy NO each state + Buy YES
    hedge, threshold N×100¢. `gap_c` (= threshold − cost) > 0 means a gross discrepancy exists.
    """
    if direction == "forward":
        legs_spec = [("buy_yes", r) for r in state_rows] + [("buy_no", hedge_row)]
        threshold = 100
    else:
        legs_spec = [("buy_no", r) for r in state_rows] + [("buy_yes", hedge_row)]
        threshold = n * 100

    legs: list[dict[str, Any]] = []
    for side, row in legs_spec:
        price = _firm_yes_ask_c(row) if side == "buy_yes" else _firm_no_ask_c(row)
        if price is None:
            return None  # missing firm price → this direction is unpriceable → no emit
        # Buy YES hits resting asks (yes_ask_size); Buy NO hits resting YES bids (yes_bid_size).
        size = _num(row.get("yes_ask_size") if side == "buy_yes" else row.get("yes_bid_size"))
        legs.append({"side": side, "row": row, "price_c": price, "size": size})

    sizes = [leg["size"] for leg in legs]
    min_size = min(sizes) if all(_pos(s) for s in sizes) else None
    cost = sum(leg["price_c"] for leg in legs)
    return {"direction": direction, "threshold_c": threshold, "cost_c": cost,
            "gap_c": threshold - cost, "legs": legs, "min_size": min_size}


def _detect_player_bundle(event_ticker: str, cfg: Any, player_key: str,
                          score_rows: list[dict], hedge_row: dict,
                          diag: dict | None = None) -> dict[str, Any] | None:
    """One player's bundle vs their match-winner hedge, or None when a gate fails / no direction fires."""
    expected = expected_states(cfg, score_rows[0].get("tour"), score_rows[0].get("tournament"))
    if not expected:
        return None  # gate 1: format unprovable

    found: dict[str, dict] = {}
    for r in score_rows:
        s = parse_scoreline(r)
        if s:
            found[s] = r
    if set(found) != set(expected):
        return None  # gate 2: not exhaustive (missing / duplicate / extra state)

    # gate 3: states + hedge must reference the SAME round; a stage mismatch means the hedge replicates a
    # different event (hard rules-conflict) → no emit.
    if {r.get("stage") for r in score_rows} | {hedge_row.get("stage")} != {hedge_row.get("stage")}:
        return None

    state_rows = [found[s] for s in expected]  # canonical order

    # gate 4: the bundle's legs must settle as a clean MECE set. A proven-unsafe leg (non-binary
    # settlement / split close-time / divergent settlement rules) is SUPPRESSED (recorded in _diag),
    # never shown — distinct from the residual settlement risk that keeps the review caveat.
    reason = _unsafe_reason(state_rows + [hedge_row])
    if reason is not None:
        _record(diag, "suppressed", event_ticker, f"{player_key}: {reason}")
        return None
    fired = [c for c in (_direction("forward", state_rows, hedge_row, len(expected)),
                         _direction("reverse", state_rows, hedge_row, len(expected)))
             if c is not None and c["gap_c"] > 0]
    if not fired:
        return None
    best = max(fired, key=lambda c: c["gap_c"])
    return _build_finding(event_ticker, cfg, player_key, hedge_row, best)


def _build_finding(event_ticker: str, cfg: Any, player_key: str, hedge_row: dict,
                   cand: dict[str, Any]) -> dict[str, Any]:
    legs = cand["legs"]
    gap, min_size = cand["gap_c"], cand["min_size"]
    player = str(hedge_row.get("player") or _leg_label(legs[0]["row"]))
    n_states = len(legs) - 1

    all_active = all(_is_active(leg["row"]) for leg in legs)
    # Blockers: the settlement caveat ALWAYS (the bundle is never riskless), plus execution blockers.
    blockers = [BLOCKERS["synthetic_settlement"]]
    if min_size is None:
        blockers.append(BLOCKERS["size_missing"])
    for leg in legs:
        q = leg["row"].get("quote_quality")
        if q in ("No quote", "One-sided"):
            blockers.append(BLOCKERS["no_quote"].format(leg=_leg_label(leg["row"])))
        elif q == "Crossed":
            blockers.append(BLOCKERS["crossed"].format(leg=_leg_label(leg["row"])))
        s = str(leg["row"].get("status") or "")
        if s and s != "active":
            blockers.append(BLOCKERS["inactive"].format(leg=_leg_label(leg["row"]), status=s))

    # tradable_now is "Review rules" (priced, sized, active — but settlement-caveated) or "No" (blocked);
    # NEVER plain "Yes" → bucket routing keeps it out of Actionable.
    tradable_now = "Review rules" if (min_size is not None and all_active) else "No"

    times = [t for t in (leg["row"].get("time_value") for leg in legs) if t]
    if cand["direction"] == "forward":
        reason = (f"Forward: Buy YES {n_states} score states + Buy NO {player} (match winner) = "
                  f"{cand['cost_c']}¢ < 100¢ → {gap}¢ gross per unit. Settlement-caveated (not riskless).")
    else:
        reason = (f"Reverse: Buy NO {n_states} score states + Buy YES {player} (match winner) = "
                  f"{cand['cost_c']}¢ < {cand['threshold_c']}¢ → {gap}¢ gross per unit. "
                  f"Settlement-caveated (not riskless).")

    out_legs = [{
        "side": leg["side"], "contract": _leg_label(leg["row"]), "price_c": leg["price_c"],
        "size": leg["size"], "ticker": leg["row"].get("market_ticker", ""),
        "url": leg["row"].get("kalshi_url", ""), "text": _buy_text(leg["side"], _leg_label(leg["row"]), leg["price_c"]),
    } for leg in legs]

    finding = {
        "check_type": CHECK_TYPE, "relationship_type": CHECK_TYPE,
        "opportunity_id": data.opportunity_id(CHECK_TYPE, event_ticker, player_key, cand["direction"]),
        "status": EXECUTABLE_SYNTHETIC_BUNDLE,
        "bucket": "blocked",  # review-only: every synthetic bundle is settlement-caveated, never Actionable
        "direction": cand["direction"],
        "event_ticker": event_ticker, "series": hedge_row.get("series", ""),
        "tournament": hedge_row.get("tournament", ""), "tour": hedge_row.get("tour", ""),
        "stage": hedge_row.get("stage", ""), "player": player, "player_key": player_key,
        "hedge": f"{player} (match winner)",
        "match": f"{player} — {hedge_row.get('tournament', '')} {hedge_row.get('stage', '')}".strip(),
        "resolve_time": min(times) if times else None,
        "tradable_now": tradable_now, "rule_flag": "SETTLEMENT_CHECK_REQUIRED",
        "market_status": "active" if all_active else "inactive",
        "blockers": "; ".join(blockers),
        "blocked_reason": "; ".join(blockers),  # non-empty by construction (settlement caveat always present)
        "n_legs": len(out_legs), "legs": out_legs,
        "cost_c": cand["cost_c"], "exec_gap_c": gap, "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap * min_size / 100, 2) if min_size is not None else None,
        "reason": reason,
        "event_title": hedge_row.get("event_title", ""), "url": hedge_row.get("kalshi_url", ""),
    }
    # Backfill the positional 2-leg action fields from the first two legs so existing 2-leg consumers keep
    # working; the full N-leg plan lives in `legs` (the scanner/API plumbing surfaces it in a later PR).
    for i in (0, 1):
        if i < len(out_legs):
            leg = out_legs[i]
            finding[f"action_{i + 1}_side"] = leg["side"]
            finding[f"action_{i + 1}_contract"] = leg["contract"]
            finding[f"action_{i + 1}_price_c"] = leg["price_c"]
            finding[f"action_{i + 1}_text"] = leg["text"]
    return finding


def _match_hedge_index(rows: list[dict]) -> dict[str, dict]:
    """Map ``player_key`` → that player's **match-winner** row (their hedge).

    Only rows from a genuine two-participant match event qualify (the head-to-head family of a recognized
    sport), so a player resolves to their single current match-winner market. Ticker-agnostic — no suffix
    parsing. (The same-round `stage` gate in `_detect_player_bundle` backstops the same-match assumption.)
    """
    by_event: dict[str, dict[str, dict]] = {}
    for r in rows:
        cfg = sports.sport_for_series(r.get("series"))
        if cfg.sport_id == "unknown" or r.get("kind") != cfg.match_family:
            continue
        pk = r.get("player_key")
        if pk:
            by_event.setdefault(r.get("event_ticker") or "", {})[pk] = r
    index: dict[str, dict] = {}
    for by_key in by_event.values():
        if len(by_key) == 2:  # a real head-to-head match (exactly two distinct participants)
            index.update(by_key)
    return index


def find_synthetic_bundles(rows: list[dict[str, Any]],
                           _diag: dict | None = None) -> list[dict[str, Any]]:
    """Scan per-player contract rows; return synthetic-bundle findings (possibly empty).

    Groups exact-score rows by event and by ``player_key`` (UUID — NOT the display name, which carries
    the scoreline subtitle), joins each player's bundle to their match-winner hedge, and emits at most one
    finding per (player, best-firing direction). The optional ``_diag`` dict collects bundles SUPPRESSED
    by a hard safety gate (`{"suppressed": [{event_ticker, reason}, …]}`) for Debug / live smoke.
    """
    rows = rows or []
    score_rows = [r for r in rows if r.get("kind") == "exact_score"]
    if not score_rows:
        return []
    hedge_index = _match_hedge_index(rows)

    # event_ticker -> {player_key: [score rows]}
    score_events: dict[str, dict[str, list[dict]]] = {}
    for r in score_rows:
        pk = r.get("player_key")
        if pk:
            score_events.setdefault(r.get("event_ticker") or "", {}).setdefault(pk, []).append(r)

    out: list[dict[str, Any]] = []
    for event_ticker, by_player in score_events.items():
        for player_key, player_rows in by_player.items():
            hedge_row = hedge_index.get(player_key)
            if hedge_row is None:
                continue  # no match-winner hedge for this player → skip (advance hedge is a later PR)
            cfg = sports.sport_for_series(player_rows[0].get("series"))
            finding = _detect_player_bundle(event_ticker, cfg, player_key, player_rows, hedge_row, _diag)
            if finding is not None:
                out.append(finding)

    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"], f["player_key"]))
    return out
