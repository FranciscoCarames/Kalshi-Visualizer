"""Unit tests for the generic payoff-state engine (pure core). No network, no UI.

Anchors map to the worked examples in the plan: the corridor (structural floor) and the uncovered-tail
range box (speculative). Also pins the hard invariants the audit asked for: buy-only rejection, the
diagnostic gate when the state set is unproven or any leg is unpriced (the worst-case is NEVER reported as
a floor), size semantics, the soft caps, and import hygiene (no pandas / nicegui / streamlit)."""
from __future__ import annotations

import pathlib

import pytest

import payoff_engine as pe


def leg(side="buy_yes", price_c=46, size=100, contract="x"):
    return {"side": side, "contract": contract, "price_c": price_c, "size": size,
            "ticker": "T", "url": "U", "text": "Buy"}


def proof(ok=True, exhaustive=True, me=True):
    return pe.StatesProof(ok=ok, exhaustive=exhaustive, mutually_exclusive=me, reason="r", source="s")


# --- anchors -------------------------------------------------------------------------
def test_corridor_is_structural_floor():
    # Buy YES >44.5 @46 + Buy YES <50.5 @47 — the plan's corridor: pays 100/200/100 across the 3 bands.
    legs = [leg("buy_yes", 46), leg("buy_yes", 47)]
    states = [
        {"label": "<=44", "payouts": [0, 100]},
        {"label": "45-50", "payouts": [100, 100]},
        {"label": ">=51", "payouts": [100, 0]},
    ]
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["cost_c"] == 93
    assert r["worst_case_payout_c"] == 100
    assert r["best_case_payout_c"] == 200
    assert r["worst_case_profit_c"] == 7      # +7¢ floor
    assert r["best_case_profit_c"] == 107
    assert r["classification"] == pe.STRUCTURAL_FLOOR
    assert r["floor_authoritative"] is True
    assert r["n_legs"] == 2 and r["legs"] == legs
    assert len(r["scenarios"]) == 3
    assert [s["is_floor"] for s in r["scenarios"]] == [True, False, True]
    assert [s["is_ceiling"] for s in r["scenarios"]] == [False, True, False]
    assert r["scenarios"][0]["payouts"] == [0, 100] and r["scenarios"][0]["payout_c"] == 100


def test_range_box_uncovered_tails_is_speculative():
    legs = [leg("buy_yes", 30), leg("buy_yes", 30)]
    states = [
        {"label": "low", "payouts": [0, 0]},      # uncovered tail -> 0
        {"label": "mid", "payouts": [100, 100]},
        {"label": "high", "payouts": [0, 0]},      # uncovered tail -> 0
    ]
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["worst_case_payout_c"] == 0
    assert r["classification"] == pe.SPECULATIVE
    assert r["floor_authoritative"] is True       # proven + priced, just an uncovered tail


def test_bounded_loss():
    legs = [leg("buy_yes", 60), leg("buy_yes", 60)]   # cost 120
    states = [{"label": "a", "payouts": [100, 0]},     # 100
              {"label": "b", "payouts": [100, 100]}]    # 200
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["cost_c"] == 120 and r["worst_case_payout_c"] == 100
    assert r["classification"] == pe.BOUNDED_LOSS      # 0 < 100 < 120


# --- hard validation -----------------------------------------------------------------
def test_buy_only_rejected():
    with pytest.raises(ValueError):
        pe.evaluate_payoff([leg("sell_yes")], [{"label": "x", "payouts": [100]}], proof())


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        pe.evaluate_payoff([leg(), leg()], [{"label": "a", "payouts": [100]}], proof())


def test_empty_legs_or_states_raise():
    with pytest.raises(ValueError):
        pe.evaluate_payoff([], [{"label": "a", "payouts": []}], proof())
    with pytest.raises(ValueError):
        pe.evaluate_payoff([leg()], [], proof())


def test_malformed_payout_entry_raises():
    with pytest.raises(ValueError):
        pe.evaluate_payoff([leg(), leg()], [{"label": "a", "payouts": [None, 100]}], proof())


# --- the diagnostic gate: worst-case is never reported as a floor when unverified ----
def test_unproven_states_are_diagnostic_even_when_profitable_looking():
    legs = [leg("buy_yes", 10), leg("buy_yes", 10)]    # cheap -> would *look* like a floor
    states = [{"label": "a", "payouts": [100, 100]}, {"label": "b", "payouts": [100, 100]}]
    r = pe.evaluate_payoff(legs, states, proof(ok=False))
    assert r["classification"] == pe.DIAGNOSTIC
    assert r["floor_authoritative"] is False


def test_missing_firm_price_is_diagnostic():
    legs = [leg("buy_yes", None), leg("buy_yes", 47)]
    states = [{"label": "a", "payouts": [0, 100]}, {"label": "b", "payouts": [100, 100]},
              {"label": "c", "payouts": [100, 0]}]
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["cost_c"] is None
    assert r["classification"] == pe.DIAGNOSTIC
    assert r["floor_authoritative"] is False
    assert r["worst_case_profit_c"] is None


# --- size semantics (audit #4) -------------------------------------------------------
def test_size_min_and_complete():
    legs = [leg("buy_yes", 46, size=5), leg("buy_yes", 47, size=200)]
    states = [{"label": "a", "payouts": [0, 100]}, {"label": "b", "payouts": [100, 100]},
              {"label": "c", "payouts": [100, 0]}]
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["min_bundle_size"] == 5 and r["size_complete"] is True


def test_size_incomplete_when_a_leg_is_zero_or_missing():
    legs = [leg("buy_yes", 46, size=0), leg("buy_yes", 47, size=None)]
    states = [{"label": "a", "payouts": [0, 100]}, {"label": "b", "payouts": [100, 100]},
              {"label": "c", "payouts": [100, 0]}]
    r = pe.evaluate_payoff(legs, states, proof())
    assert r["size_complete"] is False and r["min_bundle_size"] is None


# --- soft caps (audit #8) ------------------------------------------------------------
def test_over_cap_states_degrade_to_diagnostic_without_scenarios():
    legs = [leg("buy_yes", 10), leg("buy_yes", 10)]
    states = [{"label": str(i), "payouts": [100, 100]} for i in range(5)]
    r = pe.evaluate_payoff(legs, states, proof(), max_states=4)
    assert r["scenarios_truncated"] is True
    assert r["classification"] == pe.DIAGNOSTIC
    assert r["floor_authoritative"] is False
    assert r["scenarios"] is None


def test_over_cap_legs_degrade_to_diagnostic():
    legs = [leg("buy_yes", 1) for _ in range(3)]
    states = [{"label": "a", "payouts": [100, 100, 100]}]
    r = pe.evaluate_payoff(legs, states, proof(), max_legs=2)
    assert r["scenarios_truncated"] is True and r["classification"] == pe.DIAGNOSTIC


# --- import hygiene ------------------------------------------------------------------
def test_engine_imports_no_pandas_or_ui():
    src = pathlib.Path(pe.__file__).read_text(encoding="utf-8")
    for banned in ("import pandas", "from pandas", "import nicegui", "from nicegui",
                   "import streamlit", "from streamlit"):
        assert banned not in src, f"payoff_engine must not {banned}"
