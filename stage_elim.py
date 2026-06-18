"""Stage-of-elimination detector for KXWCSTAGEOFELIM (World Cup, soccer).

Two SEPARATE checks over a team's 7 elimination-stage buckets (one event per team; exactly ONE bucket
settles YES — the stage where the team is eliminated, FW = wins the final). Both are pure (records-in,
no UI / no pandas beyond the caller's `to_dict`), so this module is independently testable.

  1. ``find_stage_elim_books`` — the STANDALONE within-event MECE book. The 7 buckets are mutually
     exclusive AND exhaustive, so they are a clean n-way dutch book: underround = Buy YES all 7 (one wins
     -> floor 100¢); overround = Buy NO all 7 (six lose -> floor (n-1)·100¢). Actionable-eligible like any
     clean MECE book, gated on a full 7-bucket proof (all present, same team UUID, firm + sized + active).

  2. ``find_stage_elim_synthetics`` — the CROSS-FAMILY tail-sum vs the advance ladder. Each advance rung
     equals a tail-sum of buckets (Reach Final = lost-Final + Winner; Win = Winner; Reach RO32 = 1 − Group
     Stage; …), so {Buy YES the tail buckets} replicates {the advance market YES}. Priced against the direct
     advance market it is a settlement-SENSITIVE discrepancy, NOT a dutch book and NOT arbitrage (a walkover
     can advance a team without the buckets settling the matching way). ALWAYS review-only, never Actionable
     — mirrors ``synthetic_bundle.py``.

All comparisons are EXACT integer cents (parsed upstream by ``data.to_cents``); subpenny rows are excluded
by the caller-side guard. Reuses ``dutchbook``'s leaf price/size helpers so the firm-quote / NO-fallback
logic can never drift from the dutch-book detector.
"""
from __future__ import annotations

from typing import Any

import data
import sports
from dutchbook import _buy_text, _firm_no_ask_c, _firm_yes_ask_c, _is_active, _num, _pos, _record
from glossary import BLOCKERS, STAGE_ELIM_BOOK_BASIS, STAGE_ELIM_SYNTH_BASIS

# Statuses (kept as literals in consistency.STATUS_GROUP / bucket_of to avoid an import cycle).
EXECUTABLE_STAGE_ELIM_BOOK = "EXECUTABLE_STAGE_ELIM_BOOK"   # standalone 7-way MECE book (actionable-eligible)
STAGE_ELIM_SYNTHETIC = "STAGE_ELIM_SYNTHETIC"               # cross-family tail-sum (review-only)
BOOK_CHECK_TYPE = "stage_elim_book"
SYNTH_CHECK_TYPE = "stage_elim_synth"
FAMILY = "stage_of_elim"

# Ordered buckets broad→deep (the market-ticker suffix), single-sourced from sports.
_BUCKETS = tuple(s for s, _ in sports.WC_STAGE_ELIM_BUCKETS)        # ("GS","R32","R16","QF","SF","FL","FW")
_EXPECTED_N = len(_BUCKETS)                                        # 7
_BUCKET_SET = frozenset(_BUCKETS)
# suffix -> human bucket label ("R32" -> "Eliminated: Round of 32"), single-sourced from sports. Used to make
# each LEG say WHICH ROUND it refers to (not just the team name, which is identical across all 7 buckets).
_BUCKET_LABELS = dict(sports.WC_STAGE_ELIM_BUCKETS)

# Cross-family rungs: advance-ladder node -> the tail-bucket suffixes whose Buy-YES sum replicates it.
# (Reach a stage S == NOT eliminated before S == the union of all buckets from S onward.) "Win the World
# Cup" is the single FW bucket — cleanest, but the KXMENWORLDCUP outright is sub-cent (display-only).
_RUNG_TAILS = {
    "Reach Round of 32": ("R32", "R16", "QF", "SF", "FL", "FW"),
    "Reach Round of 16": ("R16", "QF", "SF", "FL", "FW"),
    "Reach Quarterfinals": ("QF", "SF", "FL", "FW"),
    "Reach Semifinals": ("SF", "FL", "FW"),
    "Reach Finals": ("FL", "FW"),
    "Win the World Cup": ("FW",),
}


def _bucket_suffix(row: dict[str, Any]) -> str:
    """The elimination bucket suffix (…-R32 → 'R32') from a stage-elim row's market ticker."""
    return str(row.get("market_ticker") or "").rsplit("-", 1)[-1].upper()


def _team_key(rows: list[dict[str, Any]]) -> str:
    return str(rows[0].get("player_key") or "") if rows else ""


def _team_name(rows: list[dict[str, Any]]) -> str:
    """The team's display name (e.g. 'USA'), falling back to its UUID key — for the opportunity title."""
    return str(rows[0].get("player") or _team_key(rows)) if rows else ""


def _leg_label(row: dict[str, Any]) -> str:
    """Per-leg label that states WHAT the leg is: the elimination round ('Eliminated: Round of 32') for a
    bucket leg, else the market's own contract / participant (e.g. the advance-market hedge)."""
    return _BUCKET_LABELS.get(_bucket_suffix(row)) or str(row.get("contract") or row.get("player") or _bucket_suffix(row))


def _leg(side: str, row: dict[str, Any], price_c: int) -> dict[str, Any]:
    label = _leg_label(row)
    size = row.get("yes_ask_size") if side == "buy_yes" else row.get("yes_bid_size")
    return {"side": side, "contract": label, "price_c": price_c, "size": _num(size),
            "ticker": row.get("market_ticker", ""), "url": row.get("kalshi_url", ""),
            "player_key": row.get("player_key", ""), "text": _buy_text(side, label, price_c)}


def _blockers_for(rows: list[dict[str, Any]], min_size: Any) -> list[str]:
    """Standard leg blockers (size / quote / inactivity), reusing the dutch-book wording."""
    out: list[str] = []
    if min_size is None:
        out.append(BLOCKERS["size_missing"])
    for r in rows:
        q = r.get("quote_quality")
        label = _leg_label(r)
        if q in ("No quote", "One-sided"):
            out.append(BLOCKERS["no_quote"].format(leg=label))
        elif q == "Crossed":
            out.append(BLOCKERS["crossed"].format(leg=label))
        s = str(r.get("status") or "")
        if s and s != "active":
            out.append(BLOCKERS["inactive"].format(leg=label, status=s))
    return out


# ---- (1) standalone within-event 7-way MECE book ---------------------------------------------------
def _book_proof(event: str, rows: list[dict[str, Any]], diag: dict | None) -> bool:
    """Prove the event is a complete single-team 7-bucket MECE set. Fails CLOSED on any gap."""
    if len(rows) != _EXPECTED_N:
        _record(diag, "rejected", event, f"stage-elim: expected {_EXPECTED_N} buckets, got {len(rows)}")
        return False
    suffixes = {_bucket_suffix(r) for r in rows}
    if suffixes != _BUCKET_SET:
        _record(diag, "rejected", event, f"stage-elim: bucket set {sorted(suffixes)} != expected")
        return False
    if len({str(r.get("player_key") or "") for r in rows}) != 1:
        _record(diag, "rejected", event, "stage-elim: buckets span more than one team UUID")
        return False
    return True


def _detect_book(event: str, rows: list[dict[str, Any]], diag: dict | None) -> dict[str, Any] | None:
    if not _book_proof(event, rows, diag):
        return None
    ordered = sorted(rows, key=lambda r: _BUCKETS.index(_bucket_suffix(r)))
    n = len(ordered)

    # Both directions, exact cents. Underround floor 100¢ (one bucket wins); overround floor (n-1)·100¢.
    yes_prices = [_firm_yes_ask_c(r) for r in ordered]
    no_prices = [_firm_no_ask_c(r) for r in ordered]
    candidates = []
    if all(p is not None for p in yes_prices):
        candidates.append(("underround", "buy_yes", yes_prices, 100, sum(yes_prices)))
    if all(p is not None for p in no_prices):
        candidates.append(("overround", "buy_no", no_prices, (n - 1) * 100, sum(no_prices)))
    firing = [c for c in candidates if c[3] - c[4] > 0]               # floor - cost > 0
    if not firing:
        _record(diag, "eligible_non_firing", event, "stage-elim book: priced, no positive gap")
        return None
    direction, side, prices, floor, cost = max(firing, key=lambda c: c[3] - c[4])
    gap_c = floor - cost

    legs = [_leg(side, r, p) for r, p in zip(ordered, prices)]
    sizes = [leg["size"] for leg in legs]
    min_size = min(sizes) if all(_pos(s) for s in sizes) else None
    all_active = all(_is_active(r) for r in ordered)
    tradable_now = "Yes" if (min_size is not None and all_active) else "No"
    blockers = _blockers_for(ordered, min_size)
    bucket = "actionable" if tradable_now == "Yes" else "blocked"
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""
    word = "buy YES" if side == "buy_yes" else "buy NO"
    reason = (f"{direction}: {word} all {n} elimination-stage buckets costs {cost}c < {floor}c floor "
              f"-> {gap_c}c gross per unit, under normal progression settlement")
    team = _team_key(ordered)
    return {
        "check_type": BOOK_CHECK_TYPE, "relationship_type": BOOK_CHECK_TYPE,
        "opportunity_id": data.opportunity_id(BOOK_CHECK_TYPE, event, team),
        "status": EXECUTABLE_STAGE_ELIM_BOOK, "bucket": bucket, "direction": direction,
        "blocked_reason": blocked_reason, "tradable_now": tradable_now,
        "market_status": "active" if all_active else "inactive", "blockers": blockers_str,
        "settlement_caveat": "",                                     # a clean MECE set carries no caveat
        "settlement_basis": STAGE_ELIM_BOOK_BASIS,
        "event_ticker": event, "series": ordered[0].get("series", ""),
        "tournament": ordered[0].get("tournament", ""), "tour": ordered[0].get("tour", ""),
        "match": f"{_team_name(ordered)} — World Cup: how far do they go? (stage-of-elimination)",
        "player_a": ordered[0].get("player", ""), "player_b": ordered[-1].get("player", ""),
        "player_key_a": team, "player_key_b": team,
        "legs": legs, "n_legs": n, "payout_floor_c": floor,
        "cost_c": cost, "exec_gap_c": gap_c,
        "worst_case_profit_c": gap_c, "best_case_profit_c": gap_c,   # flat MECE payout
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "action_1_side": legs[0]["side"], "action_1_contract": legs[0]["contract"],
        "action_1_price_c": legs[0]["price_c"], "action_1_text": legs[0]["text"],
        "action_2_side": legs[1]["side"], "action_2_contract": legs[1]["contract"],
        "action_2_price_c": legs[1]["price_c"], "action_2_text": legs[1]["text"],
        "reason": reason, "event_title": ordered[0].get("event_title", ""),
        "ticker_a": legs[0]["ticker"], "ticker_b": legs[1]["ticker"],
        "url": ordered[0].get("kalshi_url", ""),
    }


def find_stage_elim_books(records: list[dict[str, Any]],
                          _diag: dict | None = None) -> list[dict[str, Any]]:
    """One standalone 7-way book finding per KXWCSTAGEOFELIM event (possibly empty). Groups stage-elim rows
    by event_ticker; subpenny rows are excluded (rounded cents can't be trusted)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records or []:
        if r.get("kind") != FAMILY:
            continue
        ev = r.get("event_ticker") or ""
        if not ev:
            continue
        if r.get("subpenny"):
            _record(_diag, "rejected", ev, "subpenny price (variable tick) — rounded cents not trusted")
            continue
        groups.setdefault(ev, []).append(r)
    out = [f for ev, rows in groups.items() if (f := _detect_book(ev, rows, _diag)) is not None]
    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"]))
    return out


# ---- (2) cross-family tail-sum vs the advance ladder (review-only) ---------------------------------
def _advance_index(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index the per-team advance/winner markets by (team UUID, ladder node) for the hedge join."""
    idx: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records or []:
        if r.get("kind") not in ("advance", "winner"):
            continue
        node = r.get("ladder_node")
        key = str(r.get("player_key") or "")
        if node and key:
            idx.setdefault((key, str(node)), r)
    return idx


def _detect_synthetic(event: str, rows: list[dict[str, Any]], node: str, tail_suffixes: tuple[str, ...],
                      hedge: dict[str, Any], diag: dict | None) -> dict[str, Any] | None:
    """Price one rung's tail-sum replication vs its direct advance market. Best of forward/reverse."""
    by_suffix = {_bucket_suffix(r): r for r in rows}
    tail = [by_suffix[s] for s in tail_suffixes if s in by_suffix]
    if len(tail) != len(tail_suffixes):
        _record(diag, "rejected", event, f"stage-elim synth {node}: missing tail bucket(s)")
        return None
    n_tail = len(tail)

    # Forward: Buy YES tail + Buy NO hedge -> always exactly 1 pays (floor 100¢).
    fwd_tail = [_firm_yes_ask_c(r) for r in tail]
    fwd_hedge = _firm_no_ask_c(hedge)
    # Reverse: Buy NO tail + Buy YES hedge -> always n_tail pay (floor n_tail·100¢).
    rev_tail = [_firm_no_ask_c(r) for r in tail]
    rev_hedge = _firm_yes_ask_c(hedge)

    cands = []
    if all(p is not None for p in fwd_tail) and fwd_hedge is not None:
        cost = sum(fwd_tail) + fwd_hedge
        cands.append(("forward", "buy_yes", "buy_no", fwd_tail, fwd_hedge, 100, cost))
    if all(p is not None for p in rev_tail) and rev_hedge is not None:
        cost = sum(rev_tail) + rev_hedge
        cands.append(("reverse", "buy_no", "buy_yes", rev_tail, rev_hedge, n_tail * 100, cost))
    firing = [c for c in cands if c[5] - c[6] > 0]
    if not firing:
        _record(diag, "eligible_non_firing", event, f"stage-elim synth {node}: priced, no positive gap")
        return None
    direction, tail_side, hedge_side, tail_prices, hedge_price, floor, cost = \
        max(firing, key=lambda c: c[5] - c[6])
    gap_c = floor - cost

    legs = [_leg(tail_side, r, p) for r, p in zip(tail, tail_prices)]
    legs.append(_leg(hedge_side, hedge, hedge_price))
    sizes = [leg["size"] for leg in legs]
    min_size = min(sizes) if all(_pos(s) for s in sizes) else None
    all_active = all(_is_active(r) for r in tail) and _is_active(hedge)
    # ALWAYS review-only: a settlement gap (walkover/abandonment) can break the replication, so even a
    # fully firm + sized + active finding is "Review rules", never "Yes".
    tradable_now = "Review rules" if (min_size is not None and all_active) else "No"
    bucket = "review_signal" if tradable_now == "Review rules" else "blocked"
    blockers = _blockers_for(tail + [hedge], min_size)
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""
    team = _team_key(tail)
    reason = (f"{direction}: a sum of {n_tail} elimination buckets replicates \"{node}\"; priced vs the "
              f"direct advance market costs {cost}c < {floor}c -> {gap_c}c gross per unit (settlement-"
              f"sensitive — REVIEW the rules, not arbitrage)")
    return {
        "check_type": SYNTH_CHECK_TYPE, "relationship_type": SYNTH_CHECK_TYPE,
        "opportunity_id": data.opportunity_id(SYNTH_CHECK_TYPE, event, team, node),
        "status": STAGE_ELIM_SYNTHETIC, "bucket": bucket, "direction": direction,
        "rule_flag": "SETTLEMENT_CHECK_REQUIRED",
        "blocked_reason": blocked_reason, "tradable_now": tradable_now,
        "market_status": "active" if all_active else "inactive", "blockers": blockers_str,
        "settlement_caveat": BLOCKERS["stage_elim_synthetic"], "settlement_basis": STAGE_ELIM_SYNTH_BASIS,
        "event_ticker": event, "series": tail[0].get("series", ""),
        "tournament": tail[0].get("tournament", ""), "tour": tail[0].get("tour", ""),
        "match": f"{_team_name(tail)} — {node}: World Cup stage-of-elimination synthetic vs advance",
        "player_a": tail[0].get("player", ""), "player_b": hedge.get("player", ""),
        "player_key_a": team, "player_key_b": str(hedge.get("player_key") or ""),
        "legs": legs, "n_legs": len(legs), "payout_floor_c": floor,
        "cost_c": cost, "exec_gap_c": gap_c,
        "worst_case_profit_c": gap_c, "best_case_profit_c": gap_c,
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "action_1_side": legs[0]["side"], "action_1_contract": legs[0]["contract"],
        "action_1_price_c": legs[0]["price_c"], "action_1_text": legs[0]["text"],
        "action_2_side": legs[-1]["side"], "action_2_contract": legs[-1]["contract"],
        "action_2_price_c": legs[-1]["price_c"], "action_2_text": legs[-1]["text"],
        "reason": reason, "event_title": tail[0].get("event_title", ""),
        "ticker_a": legs[0]["ticker"], "ticker_b": legs[-1]["ticker"],
        "url": tail[0].get("kalshi_url", ""), "rung_node": node,
    }


def find_stage_elim_synthetics(records: list[dict[str, Any]],
                               _diag: dict | None = None) -> list[dict[str, Any]]:
    """One cross-family tail-sum finding per (event, rung) where the full tail + the matching advance
    market are present (possibly empty). REVIEW-ONLY by construction (never Actionable)."""
    adv = _advance_index(records)
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records or []:
        if r.get("kind") != FAMILY or r.get("subpenny"):
            continue
        ev = r.get("event_ticker") or ""
        if ev:
            groups.setdefault(ev, []).append(r)

    out: list[dict[str, Any]] = []
    for ev, rows in groups.items():
        if len(rows) != _EXPECTED_N or {_bucket_suffix(r) for r in rows} != _BUCKET_SET:
            continue                                                 # need the complete bucket set to tail-sum
        team = _team_key(rows)
        for node, tail_suffixes in _RUNG_TAILS.items():
            hedge = adv.get((team, node))
            if hedge is None:
                continue                                             # no direct advance market to hedge against
            f = _detect_synthetic(ev, rows, node, tail_suffixes, hedge, _diag)
            if f is not None:
                out.append(f)
    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"], f["rung_node"]))
    return out


def proof_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    """For tests / live smoke: run both detectors with a diagnostic collector and report what fired vs why
    a candidate was rejected / non-firing (mirrors dutchbook.proof_audit's spirit)."""
    diag: dict[str, Any] = {}
    books = find_stage_elim_books(records, diag)
    synths = find_stage_elim_synthetics(records, diag)
    return {"books": books, "synthetics": synths, "diag": diag}
