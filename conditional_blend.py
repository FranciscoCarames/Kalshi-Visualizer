"""Conditional-blend (opponent-resolution) dynamic detector — PURE, no UI, no pandas-of-its-own.

THE STRATEGY. Player A is already through to a round R and is WAITING for an opponent; players B and C
compete THIS round (the round before R) to decide who plays A in round R. A's price to **win the next
round (round R)** should be a market-implied blend over the two possible opponents:

    A_winNext_fair = P(B wins this round)·P(A beats B) + P(C wins this round)·P(A beats C)

All inputs are market-implied. In ladder terms, for an adjacent rung pair ``(deeper, broader)``:
  * ``broader`` = "win this round" / reach-this-stage. A is LOCKED here (≈100); B and C contest it.
  * ``deeper``  = "win the next round" / reach-the-next-stage. A's ``deeper`` price is the leg we test.
  * P(A beats B) = 1 − B_deeper / B_broader  (if B reaches ``broader`` its next opponent is A, so B going
    further means B beat A). Same for C.
  * Blend = (B_broader − B_deeper) + (C_broader − C_deeper); the signal is ``blend − A_deeper_ask``.

This is a MODEL-BASED, market-implied CONVERGENCE CANDIDATE — **not arbitrage, not fair value, can lose
money** (A can still lose round R; the blend is built from gross top-of-book prices). Every row carries
``exec_gap_c=None`` and is display-only / never ranked. Never the words fair / true / edge / arb.

FAIL-CLOSED LINKAGE. With no bracket metadata, the detector PROVES the structure purely from prices: at
``broader`` there must be exactly three non-eliminated participants — one LOCKED (A) and two LIVE,
COMPLEMENTARY contenders (B, C) — with everyone else eliminated at ``broader``. That price shape is a
self-contained proof that exactly one of B/C joins A at ``broader`` and is A's round-R opponent; it holds
at the final today (and would hold at any earlier stage only once the local field has narrowed to those
three, which without bracket data effectively means the final). Any deviation → silent SKIP.

Phase 0 is a DARK validator: this module + ``roundtrip_cost`` + a sampler script writing a throwaway CSV.
Nothing here is wired into the scanner, the SPA, ``consistency.bucket_of``, lifecycle, or any ranking.
"""
from __future__ import annotations

import hashlib
from typing import Any

import consistency
import roundtrip_cost
import sports

CHECK_TYPE = "conditional_blend"
SCHEMA_VERSION = 1
MODEL_BLEND_CANDIDATE = "MODEL_BLEND_CANDIDATE"
FIELD_UNDERROUND_DIAGNOSTIC = "FIELD_UNDERROUND_DIAGNOSTIC"

# Tunable price thresholds (cents). Kept as module constants so Phase 0 touches no existing config file.
LOCK_FLOOR_C = 98          # A's "win this round" bid at/above this ⇒ A is locked into the round.
DEAD_FLOOR_C = 2           # a "win this round" ask at/below this ⇒ that participant is eliminated.
COMPLEMENT_TOL_C = 10      # |B_broader_mid + C_broader_mid − 100| must be within this (one of B/C advances).

_NO_FIRM_QUALITY = ("No quote", "Crossed")


def _isna(x: Any) -> bool:
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    return None if _isna(x) else x


def _firm_ask_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY YES on this leg (its firm ask), or None when there's no usable resting order."""
    if row is None or row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    return _num(row.get("yes_ask_c"))


def _bid_c(row: dict[str, Any]) -> int | None:
    if row is None or row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    return _num(row.get("yes_bid_c"))


def _mid_c(row: dict[str, Any]) -> float | None:
    b, a = _bid_c(row), _firm_ask_c(row)
    if b is not None and a is not None:
        return (b + a) / 2.0
    return float(a) if a is not None else (float(b) if b is not None else None)


def _is_active(row: dict[str, Any]) -> bool:
    return row is not None and str(row.get("status") or "") == "active"


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _leg(row: dict[str, Any], node: str) -> dict[str, Any]:
    """Compact per-leg record for the CSV / offline audit."""
    return {
        "node": node,
        "player": row.get("player") or "",
        "ticker": row.get("market_ticker") or row.get("event_ticker") or "",
        "series": row.get("series") or "",
        "bid_c": _bid_c(row), "ask_c": _firm_ask_c(row), "mid_c": _mid_c(row),
        "ask_size": _num(row.get("yes_ask_size")), "bid_size": _num(row.get("yes_bid_size")),
        "status": row.get("status") or "", "quote_quality": row.get("quote_quality") or "",
        "close_time": row.get("time_value") or "", "rules": (row.get("rules_primary") or "")[:80],
    }


def _candidate_id(sport: str, tournament: str, deeper: str, broader: str,
                  a_key: str, b_key: str, c_key: str) -> str:
    bc = "|".join(sorted([str(b_key), str(c_key)]))          # stable under B/C ordering
    raw = "::".join([CHECK_TYPE, str(sport), str(tournament), str(deeper), str(broader), str(a_key), bc])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def find_conditional_blends(records: list[dict[str, Any]], *, snapshot_ts: str | None = None,
                            fee_rates: dict[str, Any] | None = None,
                            diag: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Scan contract rows for opponent-resolution convergence candidates. Groups by (sport, tournament),
    iterates each ladder's adjacent ``(deeper, broader)`` pairs, and emits at most one
    ``MODEL_BLEND_CANDIDATE`` per proven (pair, A) plus an optional ``FIELD_UNDERROUND_DIAGNOSTIC``.
    Returns flat dicts (CSV rows). ``fee_rates`` maps ``UPPER_series → {fee_type, fee_multiplier}``."""
    fee_rates = {str(k).upper(): v for k, v in (fee_rates or {}).items()}
    out: list[dict[str, Any]] = []

    # group rows by tournament, resolving a single sport per group
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records or []:
        cfg = sports.sport_for_series(r.get("series"))
        if cfg.sport_id == "unknown":
            continue
        by_group.setdefault((cfg.sport_id, str(r.get("tournament") or "")), []).append(r)

    for (sport_id, tournament), rows in by_group.items():
        cfg = sports.get_sport(sport_id)
        spec = cfg.ladder_for(rows)
        order = list(getattr(spec, "node_order", ()) or ())
        pairs = list(getattr(spec, "adjacent_pairs", ()) or ())
        if not order or not pairs:
            continue
        win_node = order[-1]

        # per-player ladder nodes → representative price row per node
        by_player: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            pk = r.get("player_key")
            if pk:
                by_player.setdefault(str(pk), []).append(r)
        nodes_by_player = {pk: consistency.build_player_nodes(prows) for pk, prows in by_player.items()}

        def rep(pk: str, node: str) -> dict[str, Any] | None:
            return consistency.representative((nodes_by_player.get(pk) or {}).get(node))

        for deeper, broader in pairs:
            if broader not in order or deeper not in order:
                continue                                      # side-branch leaf (e.g. "Win group") — skip
            # the broader rung must be a genuine 2-survivor HEAD-TO-HEAD slot: exactly two reach it, so
            # "win this round" is a head-to-head whose winner becomes A's opponent. Field rungs (golf
            # "Top 5"=5, motorsport, etc.) have no such decider — the blend P(A beats B) is meaningless
            # there — and an earlier bracket rung (survivors 4/8/…) can't be a clean 2-way pair.
            if cfg.survivors_of(broader, spec) != 2:
                _record(diag, tournament, broader, "broader rung is not a 2-survivor head-to-head slot")
                continue

            # classify every player at the `broader` rung: locked / live / eliminated / unpriced
            locked, live, names = [], [], {}
            for pk in by_player:
                br = rep(pk, broader)
                names[pk] = (br or rep(pk, deeper) or {}).get("player") or pk
                if br is None:
                    continue
                b_bid, b_ask = _bid_c(br), _firm_ask_c(br)
                if b_ask is not None and b_ask <= DEAD_FLOOR_C:
                    continue                                  # eliminated at this rung
                if b_bid is not None and b_bid >= LOCK_FLOOR_C:
                    locked.append(pk)
                elif _is_active(br) and _mid_c(br) is not None:
                    live.append(pk)
                else:
                    live.append(pk)                           # non-firm live → fails the proof below, recorded

            # PROOF: exactly one locked A + exactly two live contenders B,C + nobody else alive at `broader`
            if len(locked) != 1 or len(live) != 2:
                _record(diag, tournament, broader, f"shape {len(locked)} locked / {len(live)} live (need 1/2)")
                continue
            a_key = locked[0]
            b_key, c_key = live

            a_dp = rep(a_key, deeper)
            b_br, b_dp = rep(b_key, broader), rep(b_key, deeper)
            c_br, c_dp = rep(c_key, broader), rep(c_key, deeper)

            # all legs must be active with firm quotes; A needs a firm target ask; B/C need broader+deeper
            a_target = _firm_ask_c(a_dp)
            a_exit_bid = _bid_c(a_dp)            # a convergence exit needs a bid to SELL into
            b_bm, b_dm = _mid_c(b_br), _mid_c(b_dp)
            c_bm, c_dm = _mid_c(c_br), _mid_c(c_dp)
            if a_target is None or None in (b_bm, b_dm, c_bm, c_dm):
                _record(diag, tournament, broader, "missing firm quote on a required leg")
                continue
            if not (_is_active(a_dp) and _is_active(b_br) and _is_active(c_br)):
                _record(diag, tournament, broader, "a required leg is not active")
                continue

            # B/C must be complementary for the slot (exactly one of them advances to face A)
            if abs((b_bm + c_bm) - 100) > COMPLEMENT_TOL_C:
                _record(diag, tournament, broader, f"B/C win-this-round not complementary ({b_bm:.0f}+{c_bm:.0f})")
                continue

            # ratios must be non-inverted (deeper ≤ broader) and have positive denominators
            if b_bm <= 0 or c_bm <= 0 or b_dm > b_bm or c_dm > c_bm:
                _record(diag, tournament, broader, "inverted/undefined opponent ratio")
                continue

            # --- blend (cents) ---
            # normalized this-round weights (removes the per-market vig double-count) from mids
            wsum = b_bm + c_bm
            w_b, w_c = b_bm / wsum, c_bm / wsum
            # optimistic (midpoint) matchup probabilities
            q_b_mid = _clamp01(1 - b_dm / b_bm)
            q_c_mid = _clamp01(1 - c_dm / c_bm)
            blend_mid_c = round(100 * (w_b * q_b_mid + w_c * q_c_mid))
            # conservative lower bound: maximize P(opp beats A) using its ask over the broader bid
            b_bid, c_bid = _bid_c(b_br), _bid_c(c_br)
            b_da, c_da = _firm_ask_c(b_dp), _firm_ask_c(c_dp)
            if None in (b_bid, c_bid, b_da, c_da) or b_bid <= 0 or c_bid <= 0:
                blend_lower_c = None
            else:
                q_b_lo = _clamp01(1 - b_da / b_bid)
                q_c_lo = _clamp01(1 - c_da / c_bid)
                blend_lower_c = round(100 * (w_b * q_b_lo + w_c * q_c_lo))

            gap_mid_c = blend_mid_c - a_target
            gap_lower_c = (blend_lower_c - a_target) if blend_lower_c is not None else None

            # model-free baseline: A_deeper should ≈ 100 − B_deeper − C_deeper
            b_dask, c_dask = _firm_ask_c(b_dp), _firm_ask_c(c_dp)
            complement_gap_c = (100 - b_dask - c_dask - a_target) if None not in (b_dask, c_dask) else None

            # cost paths from the A target leg's series fee metadata
            a_series = str((a_dp or {}).get("series") or "").upper()
            costs = roundtrip_cost.cost_paths(a_target, fee_rates.get(a_series))
            # exit liquidity: a convergence thesis is only tradable if A's target has a BID to sell into.
            # A one-sided (ask-only) book lets you buy but never exit at the blend — block the gate.
            exit_liquidity = "two_sided" if a_exit_bid is not None else "one_sided_no_exit_bid"
            gate_pass = bool(
                gap_lower_c is not None and gap_lower_c > 0
                and costs["fee_known"] and gap_lower_c > costs["cost_roundtrip_taker_c"]
                and a_exit_bid is not None
            )

            adjacency = "closed_pair_final" if deeper == win_node else "closed_pair_earlier"
            out.append({
                "schema_version": SCHEMA_VERSION, "check_type": CHECK_TYPE,
                "status": MODEL_BLEND_CANDIDATE,
                "candidate_id": _candidate_id(sport_id, tournament, deeper, broader, a_key, b_key, c_key),
                "snapshot_ts": snapshot_ts or "", "adjacency_proof": adjacency,
                "sport": sport_id, "tournament": tournament, "round_broader": broader, "round_deeper": deeper,
                "A_key": a_key, "A_name": names.get(a_key, a_key),
                "B_key": b_key, "B_name": names.get(b_key, b_key),
                "C_key": c_key, "C_name": names.get(c_key, c_key),
                "A_winNext_ask_c": a_target, "A_winNext_bid_c": a_exit_bid,
                "exit_liquidity": exit_liquidity,
                "B_winThis_mid_c": round(b_bm, 1), "C_winThis_mid_c": round(c_bm, 1),
                "B_winNext_mid_c": round(b_dm, 1), "C_winNext_mid_c": round(c_dm, 1),
                "A_beats_B_mid": round(q_b_mid, 4), "A_beats_C_mid": round(q_c_mid, 4),
                "market_implied_blend_mid_c": blend_mid_c,
                "market_implied_blend_lower_c": blend_lower_c,
                "model_gap_to_ask_mid_c": gap_mid_c,
                "model_gap_to_ask_lower_c": gap_lower_c,
                "complement_gap_c": complement_gap_c,
                "cost_hold_c": costs["cost_hold_c"],
                "cost_roundtrip_taker_c": costs["cost_roundtrip_taker_c"],
                "cost_maker_entry_taker_exit_c": costs["cost_maker_entry_taker_exit_c"],
                "fee_known": costs["fee_known"], "fee_status": costs["fee_status"],
                "gate_pass": gate_pass,
                "A_target_ask_size": _num((a_dp or {}).get("yes_ask_size")),
                "legs": [_leg(a_dp, deeper), _leg(b_br, broader), _leg(b_dp, deeper),
                         _leg(c_br, broader), _leg(c_dp, deeper)],
                "exec_gap_c": None,
                "settlement_note": ("market-implied blend, NOT fair value; convergence candidate, NOT "
                                    "arbitrage — A can lose round R; gross/top-of-book, fees & slippage only "
                                    "partially modeled; display-only, never Actionable"),
                "linkage_reason": f"1 locked (A) + 2 complementary live (B,C) at '{broader}', rest eliminated",
            })

            # separate also-true note: the buy-all-three winner field is underround (logging-only)
            if deeper == win_node and None not in (a_target, b_dask, c_dask) and (a_target + b_dask + c_dask) < 100:
                out.append({
                    "schema_version": SCHEMA_VERSION, "check_type": CHECK_TYPE,
                    "status": FIELD_UNDERROUND_DIAGNOSTIC, "snapshot_ts": snapshot_ts or "",
                    "candidate_id": _candidate_id(sport_id, tournament, deeper, broader, a_key, b_key, c_key),
                    "sport": sport_id, "tournament": tournament,
                    "A_key": a_key, "B_key": b_key, "C_key": c_key,
                    "field_ask_sum_c": a_target + b_dask + c_dask,
                    "field_underround_c": 100 - (a_target + b_dask + c_dask),
                    "exec_gap_c": None,
                    "settlement_note": ("buy-all-three winner field priced under 100¢ — diagnostic only; "
                                        "exhaustiveness/settlement NOT proven here, not an executable book"),
                })
    return out


def _record(diag: list[dict[str, Any]] | None, tournament: str, node: str, reason: str) -> None:
    if diag is not None:
        diag.append({"tournament": tournament, "node": node, "reason": reason})
