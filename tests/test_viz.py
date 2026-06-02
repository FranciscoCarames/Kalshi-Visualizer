"""Unit tests for the pure chart-data prep (no Streamlit)."""
from __future__ import annotations

import pandas as pd

import viz


def _frame(rows):
    return pd.DataFrame(rows)


def test_opportunity_ranking_sorts_and_tags_kind():
    actionable = _frame([
        {"player": "A", "tournament": "French Open", "chain": "c1", "exec_gap_c": 2},
        {"player": "B", "tournament": "French Open", "chain": "c2", "exec_gap_c": 5},
    ])
    near = _frame([
        {"player": "C", "tournament": "Wimbledon", "chain": "c3", "executable_gap": -3},
    ])
    out = viz.opportunity_ranking(actionable, near)
    assert list(out["edge_c"]) == [5, 2, -3]               # sorted desc, near-edge last (negative)
    assert list(out["kind"]) == ["Actionable", "Actionable", "Near-edge"]
    assert out.iloc[0]["label"].startswith("B · French Open · c2")


def test_opportunity_ranking_top_n_and_empty():
    actionable = _frame([{"player": f"P{i}", "tournament": "T", "chain": "c", "exec_gap_c": i} for i in range(30)])
    assert len(viz.opportunity_ranking(actionable, _frame([]), top=10)) == 10
    empty = pd.DataFrame(columns=["player", "tournament", "chain", "exec_gap_c"])
    out = viz.opportunity_ranking(empty, empty)
    assert out.empty and list(out.columns) == ["label", "edge_c", "kind"]


def test_opportunity_ranking_unique_labels():
    # Same player/tournament/chain twice -> labels disambiguated so the chart axis keeps both.
    actionable = _frame([
        {"player": "A", "tournament": "T", "chain": "c", "exec_gap_c": 3},
        {"player": "A", "tournament": "T", "chain": "c", "exec_gap_c": 4},
    ])
    out = viz.opportunity_ranking(actionable, _frame([]))
    assert out["label"].is_unique
