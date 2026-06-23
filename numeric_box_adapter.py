"""Numeric-box demonstrator adapter for the generic payoff-state engine — DEFAULT-OFF, DIAGNOSTIC-ONLY.

This is the FIRST thin adapter on top of `payoff_engine.py`: it proves the engine end-to-end on live data
without adding any ranked / Actionable surface. It is NOT a strategy — the real range/band/box detectors
(#19/#20/#21/#22/#26) land later, each as its own adapter that "defines its states".

What it builds: from a single monotone numeric ladder (`numeric_ladder.build_numeric_ladders`, consumed
READ-ONLY), it takes each ADJACENT rung pair (broader ⊇ deeper) and expresses the simplest buy-only box —
a vertical corridor: **Buy YES the broader rung + Buy NO the deeper rung**. Because the deeper rung is
NESTED in the broader one (numeric_ladder proves this from structured strikes), exactly THREE world-states
are reachable — the truth-combinations of the two thresholds:

| State (broad, deep) | Buy YES broad | Buy NO deep | total |
|---|--:|--:|--:|
| outside both        | 0   | 100 | 100 |
| inside broad only   | 100 | 100 | 200 |
| inside deep (⊆broad)| 100 | 0   | 100 |

The fourth combo (deep true, broad false) is IMPOSSIBLE by the nesting, so the state set is exhaustive +
mutually exclusive **purely from the proven containment** — no integer / strike-inclusivity assumption is
needed (audit #6: this sidesteps the inclusivity trap entirely; we fail closed if containment can't be
established). The corridor pays a guaranteed 100¢ floor in every state, so the engine classifies it
`structural_floor` when the cost is ≤ 100¢ and `bounded_loss` otherwise — proving the engine's verdict on
real prices.

Every finding is `exec_gap_c=None`, `tradable_now="No — diagnostic only"`, bucket `payoff_state` — it can
NEVER reach Actionable. Gross / top-of-book; no fees, no de-vig. No pandas / nicegui / streamlit imports.
"""
from __future__ import annotations

from typing import Any

import data
import dutchbook  # reuse the canonical _leg + firm-ask helpers (single-sourced pricing)
import numeric_ladder
import payoff_engine
from glossary import PAYOFF_ENGINE_BASIS

# The one status this adapter emits. A guarded literal mirrored in consistency.STATUS_GROUP / bucket_of.
PAYOFF_STATE_DIAGNOSTIC = "PAYOFF_STATE_DIAGNOSTIC"
CHECK_TYPE = "payoff_state"


def _fmt(strike: float) -> str:
    """Compact strike label (drops a trailing .0)."""
    return f"{strike:g}"


def _band_labels(direction: str, broad: float, deep: float) -> tuple[str, str, str]:
    """Human (display-only) labels for the three reachable states, by ladder direction. Correctness rests
    on the truth-combinations, NOT these labels — they only annotate the scenarios table."""
    if direction == "ge":           # broad: X > {broad}; deep: X > {deep}; deep > broad
        return (f"≤ {_fmt(broad)}", f"{_fmt(broad)} < X ≤ {_fmt(deep)}", f"> {_fmt(deep)}")
    # le: broad: X < {broad} (higher cap); deep: X < {deep} (lower cap); broad > deep
    return (f"≥ {_fmt(broad)}", f"{_fmt(deep)} ≤ X < {_fmt(broad)}", f"< {_fmt(deep)}")


def _box_finding(ladder: numeric_ladder.NumericLadder, broad: tuple[float, dict[str, Any]],
                 deep: tuple[float, dict[str, Any]], *, max_legs: int, max_states: int,
                 _diag: dict | None = None) -> dict[str, Any] | None:
    """Build one diagnostic corridor finding for an adjacent (broader, deeper) rung pair, or None to skip."""
    broad_strike, broad_row = broad
    deep_strike, deep_row = deep
    if broad_strike == deep_strike:          # defensive — build_numeric_ladders already dedups strikes
        return None

    # SCALAR-IDENTITY GUARD (no false numeric findings — confirmed live on KXATPGSPREAD): numeric_ladder's
    # default group key is (series, event), which is correct for a single-scalar whole-event TOTAL but WRONG
    # for per-participant SPREADS — it would merge e.g. "Struff −1.5" with "Borges −2.5", two DIFFERENT
    # participants' margins, into a bogus "ladder" that fabricates a structural floor. A whole-event total
    # carries a LOW-confidence fallback identity (no competitor resolved), so two distinct HIGH-confidence
    # competitor keys prove this is a per-participant family the demo can't safely pair → skip. (The real
    # #21 adapter must instead pass a participant-aware group_key_fn; the demo just refuses the unsafe pair.)
    if broad_row.get("player_key") != deep_row.get("player_key") and \
            "high" in (broad_row.get("mapping_confidence"), deep_row.get("mapping_confidence")):
        return None

    # Buy-only legs (single-sourced pricing + canonical leg shape from dutchbook).
    leg_yes = dutchbook._leg("buy_yes", broad_row, dutchbook._firm_yes_ask_c(broad_row))
    leg_no = dutchbook._leg("buy_no", deep_row, dutchbook._firm_no_ask_c(deep_row))
    legs = [leg_yes, leg_no]

    below, middle, inside = _band_labels(ladder.direction, broad_strike, deep_strike)
    states = [
        {"label": below, "payouts": [0, 100]},     # outside the broader set: YES=0, NO(deep)=100
        {"label": middle, "payouts": [100, 100]},  # inside broad, outside deep: both pay
        {"label": inside, "payouts": [100, 0]},     # inside the deeper (⊆ broader) set: YES=100, NO(deep)=0
    ]

    # The state space is proven from numeric_ladder's monotone containment — NOT from any inclusivity guess.
    proof = payoff_engine.StatesProof(
        ok=True, exhaustive=True, mutually_exclusive=True,
        reason="3 reachable truth-combinations of two NESTED numeric thresholds (deeper rung ⊆ broader rung)",
        source=(f"numeric_ladder {ladder.direction} monotone containment on {ladder.group_key!r}; "
                f"deeper rung ⊆ broader rung proves MECE+exhaustive without any strike-inclusivity assumption"),
    )
    result = payoff_engine.evaluate_payoff(legs, states, proof, max_legs=max_legs, max_states=max_states,
                                           _diag=_diag)

    oid = data.opportunity_id(CHECK_TYPE, broad_row.get("event_ticker") or "", str(ladder.group_key),
                              ladder.direction, _fmt(broad_strike), _fmt(deep_strike))
    name = str(broad_row.get("event_title") or broad_row.get("contract") or "Numeric box")
    return {
        "check_type": CHECK_TYPE,
        "status": PAYOFF_STATE_DIAGNOSTIC,
        "opportunity_id": oid,
        "event_ticker": broad_row.get("event_ticker") or "",
        "name": name,
        "detail": f"Corridor (Buy YES broad + Buy NO deep) — pays 200¢ in {middle}, 100¢ floor elsewhere",
        "tournament": broad_row.get("tournament") or "",
        "tour": broad_row.get("tour") or "",
        "direction": ladder.direction,
        # Engine verdict (display-only; never ranked / Actionable).
        "classification": result["classification"],
        "floor_authoritative": result["floor_authoritative"],
        "cost_c": result["cost_c"],
        "worst_case_payout_c": result["worst_case_payout_c"],
        "best_case_payout_c": result["best_case_payout_c"],
        "worst_case_profit_c": result["worst_case_profit_c"],
        "best_case_profit_c": result["best_case_profit_c"],
        "payout_floor_c": result["worst_case_payout_c"],     # guaranteed gross floor = the worst-case payout
        "min_bundle_size": result["min_bundle_size"],
        "size_complete": result["size_complete"],
        "n_legs": result["n_legs"],
        "legs": result["legs"],
        "payoff_scenarios": result["scenarios"],
        "scenarios_truncated": result["scenarios_truncated"],
        "proof_reason": result["proof_reason"],
        "proof_source": result["proof_source"],
        # Conservative, single-sourced basis — NOT arbitrage, never executable.
        "settlement_note": PAYOFF_ENGINE_BASIS,
        # Per-leg links for the detail panel (the converter also reads these).
        "ticker_1": leg_yes.get("ticker") or "", "url": leg_yes.get("url") or "",
        "ticker_2": leg_no.get("ticker") or "", "url_2": leg_no.get("url") or "",
    }


def find_payoff_boxes(
    rows: list[dict[str, Any]],
    *,
    max_legs: int = payoff_engine.DEFAULT_MAX_LEGS,
    max_states: int = payoff_engine.DEFAULT_MAX_STATES,
    _diag: dict | None = None,
) -> list[dict[str, Any]]:
    """Diagnostic numeric-box findings for `rows` (a sport's contract records, NaN-safe via the helpers).

    Consumes `numeric_ladder.build_numeric_ladders(rows)` READ-ONLY and emits one corridor finding per
    ADJACENT rung pair (bounded: ≤ len(rungs)−1 per ladder). Empty when no monotone numeric ladder exists.
    Every finding is diagnostic-only (`exec_gap_c=None`, never Actionable) — see module docstring.
    """
    out: list[dict[str, Any]] = []
    for ladder in numeric_ladder.build_numeric_ladders(rows or []):
        for i in range(len(ladder.rungs) - 1):
            finding = _box_finding(ladder, ladder.rungs[i], ladder.rungs[i + 1],
                                   max_legs=max_legs, max_states=max_states, _diag=_diag)
            if finding is not None:
                out.append(finding)
    return out
