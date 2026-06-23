"""Generic payoff-state engine (foundation) — pure, UI-free, exact integer cents.

A cluster of range/band/box strategies (#19/#20/#21/#22/#26) share ONE shape: a set of **buy-only** legs,
a finite set of **mutually-exclusive, exhaustive** world-states, and a payout per leg per state. Rather
than five overlapping one-off detectors, this module is the single computational core they all reduce to.
Each future strategy becomes a thin ADAPTER that only *defines its states* and calls `evaluate_payoff`.

What it does: given priced buy-only `legs` and a dense `states` × `legs` payout matrix, it returns total
cost, worst-/best-case payout and profit, and a structural CLASSIFICATION (structural_floor / bounded_loss
/ speculative / diagnostic). It also echoes the legs and emits a per-state `scenarios` table for inspection.

What it does NOT do — and CANNOT do — is *prove* the state set is MECE or exhaustive. A dense table carries
no such proof. The engine validates SHAPE ONLY (buy-only sides, payout-row width, soft size caps) and
otherwise TRUSTS the adapter's `StatesProof`. The adapter owns that assertion, exactly as
`dutchbook.MeceProof` is an adapter-side settlement-phrase assertion, not a mathematical proof. If the
proof is not `ok` (or any leg is unpriced, or the matrix is too large), the worst-case is NOT treated as
authoritative: the result is classified `diagnostic` and `floor_authoritative` is False.

This module surfaces NOTHING on its own — it assigns no `status`/`bucket`/`tradable_now`. Value comes from
the adapters built on top (see `numeric_box_adapter.py`). Gross / top-of-book; no fees, no de-vig, no
conditional-probability model — same DNA as `dutchbook.py` / `synthetic_bundle.py`. No pandas / nicegui /
streamlit imports, so it is independently testable.
"""
from __future__ import annotations

from typing import Any, NamedTuple

# --- structural classifications (the single descriptive verdict; drives NOTHING by itself) -------------
# These name the gross PAYOFF SHAPE, not executability. `structural_floor` is unreachable unless the
# adapter's proof is ok AND every leg is priced AND the matrix is within caps (else -> `diagnostic`); the
# adapter/scanner additionally floors the finding out of Actionable (exec_gap_c=None + a diagnostic bucket).
STRUCTURAL_FLOOR = "structural_floor"   # worst-case payout >= cost: every state returns at least the cost
BOUNDED_LOSS = "bounded_loss"           # 0 < worst-case payout < cost: capped partial loss, always recovers some
SPECULATIVE = "speculative"             # worst-case payout == 0: an uncovered tail can lose the whole stake
DIAGNOSTIC = "diagnostic"               # unpriced / unproven / over-cap: worst-case is NOT authoritative

# Soft caps (audit #8): an oversized matrix never reaches SQLite/JSON. Exceeding -> diagnostic + truncated,
# with the per-state `scenarios` table omitted. Generous: real range/band/box adapters are far smaller.
DEFAULT_MAX_LEGS = 24
DEFAULT_MAX_STATES = 64

_VALID_SIDES = ("buy_yes", "buy_no")    # buy-only enforcement: a sell/short side is rejected outright


class StatesProof(NamedTuple):
    """The adapter's ASSERTION that its state set is exhaustive + mutually exclusive (NOT an engine proof).

    Mirrors `dutchbook.MeceProof`: the engine cannot verify MECE/exhaustiveness from a dense table, so it
    trusts this and refuses to treat the worst-case as a floor unless `ok` is True. `reason` explains the
    verdict; `source` records WHERE the assertion came from and ITS ASSUMPTIONS (audit #5), so an
    inspector sees them instead of having them buried (e.g. "numeric ge/le structured strikes; assumes an
    integer-valued settlement variable").
    """
    ok: bool
    exhaustive: bool
    mutually_exclusive: bool
    reason: str
    source: str = ""


def _isna(x: Any) -> bool:
    """True for None or float NaN (a None round-trips to NaN through pandas)."""
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    """Normalize a possibly-NaN numeric to None so `is None` checks work."""
    return None if _isna(x) else x


def _payout_int(x: Any) -> int:
    """A state's per-leg payout as exact integer cents. A missing/NaN/non-numeric entry is a malformed
    table (not a 0 payout — that would silently understate the worst case), so it RAISES."""
    v = _num(x)
    if v is None or isinstance(v, bool):
        raise ValueError(f"payoff_engine: payout entry must be a number in cents, got {x!r}")
    try:
        return int(round(float(v)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"payoff_engine: payout entry must be a number in cents, got {x!r}") from exc


def evaluate_payoff(
    legs: list[dict[str, Any]],
    states: list[dict[str, Any]],
    proof: StatesProof,
    *,
    max_legs: int = DEFAULT_MAX_LEGS,
    max_states: int = DEFAULT_MAX_STATES,
    _diag: dict | None = None,
) -> dict[str, Any]:
    """Evaluate a buy-only payoff matrix and return its cost / worst / best / classification.

    ``legs`` are canonical buy-only legs (the `dutchbook._leg` shape: ``side`` in {"buy_yes","buy_no"},
    ``contract``, ``price_c``, ``size``, ``ticker``, ``url``, ``text``). ``states`` is the dense
    states × legs matrix: each ``{"label": str, "payouts": [c0, c1, ...]}`` has exactly ``len(legs)``
    integer-cent entries. ``proof`` is the adapter's MECE/exhaustiveness assertion.

    HARD validation (raises ``ValueError`` — same severity as a malformed MECE set):
      1. buy-only — every ``leg["side"]`` is "buy_yes" or "buy_no";
      2. shape — at least one leg and one state; every ``payouts`` row is exactly ``len(legs)`` wide.

    SOFT caps (never raise): over ``max_legs`` / ``max_states`` -> ``classification="diagnostic"`` +
    ``scenarios_truncated=True`` and the per-state ``scenarios`` table is omitted.

    Returns a dict with ``cost_c``, ``worst_case_payout_c``, ``best_case_payout_c``,
    ``worst_case_profit_c``, ``best_case_profit_c``, ``classification``, ``floor_authoritative``,
    ``proof_reason``, ``proof_source``, ``n_legs``, ``legs`` (echoed), ``min_bundle_size``,
    ``size_complete``, ``scenarios_truncated``, and ``scenarios`` (omitted when truncated). It assigns NO
    ``status``/``bucket``/``tradable_now`` — that is the adapter/scanner's job.
    """
    if not legs:
        raise ValueError("payoff_engine: need at least one leg")
    if not states:
        raise ValueError("payoff_engine: need at least one state")
    for leg in legs:
        side = leg.get("side")
        if side not in _VALID_SIDES:
            # Buy-only is the invariant that keeps the exact-band adapter (#20) honest — reject sell/short.
            raise ValueError(f"payoff_engine: buy-only — leg side must be one of {_VALID_SIDES}, got {side!r}")

    n = len(legs)
    for st in states:
        payouts = st.get("payouts")
        if not isinstance(payouts, (list, tuple)) or len(payouts) != n:
            raise ValueError(
                f"payoff_engine: each state's payouts must have exactly {n} entries (one per leg), "
                f"got {payouts!r}")

    # --- prices (exact integer cents) ---
    prices = [_num(leg.get("price_c")) for leg in legs]
    all_priced = all(p is not None for p in prices)
    cost_c = sum(int(p) for p in prices) if all_priced else None

    # --- executable size (audit #4): never imply a 10-leg floor is fillable at arbitrary size ---
    sizes = [_num(leg.get("size")) for leg in legs]
    positive = [int(s) for s in sizes if s is not None and s > 0]
    size_complete = len(positive) == n
    min_bundle_size = min(positive) if positive else None

    # --- caps (audit #8) ---
    truncated = n > max_legs or len(states) > max_states

    # --- per-state payouts (exact integer cents) ---
    state_payout_c = [sum(_payout_int(c) for c in st["payouts"]) for st in states]
    worst_payout_c = min(state_payout_c)
    best_payout_c = max(state_payout_c)
    worst_profit_c = (worst_payout_c - cost_c) if cost_c is not None else None
    best_profit_c = (best_payout_c - cost_c) if cost_c is not None else None

    # --- the worst-case is AUTHORITATIVE only on a proven, fully-priced, untruncated state space ---
    floor_authoritative = bool(proof.ok and all_priced and not truncated)
    if not floor_authoritative:
        classification = DIAGNOSTIC
    elif worst_payout_c >= cost_c:
        classification = STRUCTURAL_FLOOR
    elif worst_payout_c > 0:
        classification = BOUNDED_LOSS
    else:
        classification = SPECULATIVE

    # --- per-state scenarios table (the F25 card renders this); omitted when truncated ---
    scenarios: list[dict[str, Any]] | None = None
    if not truncated:
        scenarios = []
        for st, payout in zip(states, state_payout_c):
            scenarios.append({
                "label": st.get("label"),
                "payouts": [_payout_int(c) for c in st["payouts"]],   # per-leg, for the states × legs matrix
                "payout_c": payout,
                "profit_c": (payout - cost_c) if cost_c is not None else None,
                "is_floor": payout == worst_payout_c,
                "is_ceiling": payout == best_payout_c,
            })

    if _diag is not None:
        _diag.setdefault("payoff_engine", []).append({
            "classification": classification, "floor_authoritative": floor_authoritative,
            "truncated": truncated, "all_priced": all_priced, "proof_ok": proof.ok,
            "n_legs": n, "n_states": len(states), "reason": proof.reason,
        })

    return {
        "cost_c": cost_c,
        "worst_case_payout_c": worst_payout_c,
        "best_case_payout_c": best_payout_c,
        "worst_case_profit_c": worst_profit_c,
        "best_case_profit_c": best_profit_c,
        "classification": classification,
        "floor_authoritative": floor_authoritative,
        "proof_reason": proof.reason,
        "proof_source": proof.source,
        "n_legs": n,
        "legs": list(legs),
        "min_bundle_size": min_bundle_size,
        "size_complete": size_complete,
        "scenarios_truncated": truncated,
        "scenarios": scenarios,
    }
