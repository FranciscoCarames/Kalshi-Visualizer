"""Unit tests for the pure chart-data prep (no Streamlit)."""
from __future__ import annotations

import pandas as pd

import viz


def _frame(rows):
    return pd.DataFrame(rows)


def test_payoff_chart_data_roles_and_order():
    pay = {
        "scenarios": [
            {"label": "Win Tournament", "payout_c": 100, "profit_c": 2, "is_bonus": False, "is_risk": False, "is_guaranteed_floor": True},
            {"label": "Reach Final, not Win Tournament", "payout_c": 200, "profit_c": 102, "is_bonus": True, "is_risk": False, "is_guaranteed_floor": False},
            {"label": "Not Reach Final", "payout_c": 100, "profit_c": 2, "is_bonus": False, "is_risk": False, "is_guaranteed_floor": True},
        ],
    }
    out = viz.payoff_chart_data(pay)
    assert list(out.columns) == ["scenario", "payout_c", "profit_c", "role"]
    assert list(out["payout_c"]) == [100, 200, 100]          # order preserved
    assert list(out["role"]) == ["Floor", "Bonus", "Floor"]


def test_payoff_chart_data_keeps_risk_row_and_handles_empty():
    pay = {
        "scenarios": [
            {"label": "X (aligned)", "payout_c": 100, "profit_c": 2, "is_bonus": False, "is_risk": False},
            {"label": "Not X (aligned)", "payout_c": 100, "profit_c": 2, "is_bonus": False, "is_risk": False},
            {"label": "Rules diverge", "payout_c": None, "profit_c": None, "is_bonus": False, "is_risk": True},
        ],
    }
    out = viz.payoff_chart_data(pay)
    assert list(out["role"]) == ["Floor", "Floor", "Risk"]
    assert out["payout_c"].isna().sum() == 1                 # risk row kept, payout None
    # Empty / None inputs return the typed empty frame.
    assert viz.payoff_chart_data(None).empty
    assert list(viz.payoff_chart_data({}).columns) == ["scenario", "payout_c", "profit_c", "role"]


def test_ladder_prices_flags_inversion_broad_to_deep():
    # Deeper "Win" (40) priced ABOVE broader "Reach Final" (35) → inverted.
    chain = [
        {"Layer": "Reach Semifinal", "Display %": 60.0},
        {"Layer": "Reach Final", "Display %": 35.0},
        {"Layer": "Win Tournament", "Display %": 40.0},
    ]
    out = viz.ladder_prices(chain)
    assert list(out["layer"]) == ["Reach Semifinal", "Reach Final", "Win Tournament"]
    assert list(out["rank"]) == [0, 1, 2]
    assert list(out["inverted"]) == [False, False, True]   # only the deeper-above-broader step


def test_ladder_prices_missing_price_compares_to_nearest_broader():
    # Middle layer has no price; the deepest compares to the nearest priced broader neighbour.
    chain = [
        {"Layer": "Reach Semifinal", "Display %": 50.0},
        {"Layer": "Reach Final", "Display %": None},
        {"Layer": "Win Tournament", "Display %": 55.0},   # > 50 (nearest broader with a price)
    ]
    out = viz.ladder_prices(chain)
    assert pd.isna(out.loc[1, "display_pct"])   # None becomes NaN in a float column
    assert list(out["inverted"]) == [False, False, True]


def test_ladder_prices_sub_tolerance_inversion_is_not_flagged():
    # A8: a sub-cent (≤ DISPLAY_TOL_C) "inversion" is rounding noise the engine ignores → not flagged.
    chain = [
        {"Layer": "Reach Final", "Display %": 50.0},
        {"Layer": "Win Tournament", "Display %": 50.5},   # only 0.5pp above → within tolerance
    ]
    out = viz.ladder_prices(chain)
    assert list(out["inverted"]) == [False, False]


def test_ladder_prices_empty():
    out = viz.ladder_prices([])
    assert out.empty and list(out.columns) == ["layer", "display_pct", "rank", "inverted"]
