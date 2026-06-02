"""Unit tests for the pure dashboard filters (membership vs thresholds)."""
from __future__ import annotations

import pandas as pd

import filters

_BASE = dict(
    child_category="Tournament winner", parent_category="Stage advancement",
    competition="French Open Women Singles", layers=("Reach Final", "Win Tournament"),
    child_event_ticker="KXFOWOMEN-26", parent_event_ticker="KXWTAADVANCE-26AND",
    player="Aryna Sabalenka", volume=100, executable_gap=3, exec_min_size=50,
    comp_quote_quality="Tight", child_status="active", parent_status="active", bucket="actionable",
)


def _row(**kw):
    r = dict(_BASE)
    r.update(kw)
    return r


def _df(*rows):
    return pd.DataFrame(list(rows))


# --- membership ----------------------------------------------------------------------
def test_membership_empty_selection_is_passthrough():
    df = _df(_row(), _row(player="Iga Swiatek"))
    assert len(filters.apply_membership(df)) == 2


def test_membership_category_keeps_in_scope_and_blank():
    df = _df(
        _row(child_category="Tournament winner", parent_category="Stage advancement"),
        _row(child_category="Match result", parent_category="Stage advancement"),
        _row(child_category="Stage advancement", parent_category=""),   # blank parent leg kept
    )
    out = filters.apply_membership(df, categories=["Tournament winner", "Stage advancement"])
    # The Match-result row is dropped; the other two stay.
    assert len(out) == 2
    assert "Match result" not in set(out["child_category"])


def test_membership_competition_layers_event_player_volume():
    df = _df(
        _row(player="Aryna Sabalenka", competition="French Open Women Singles",
             layers=("Reach Final", "Win Tournament"), parent_event_ticker="KXWTAADVANCE-26AND", volume=100),
        _row(player="Carlos Alcaraz", competition="French Open Men Singles",
             layers=("Reach Semifinal",), parent_event_ticker="KXATPADVANCE-26Z", volume=5),
    )
    assert set(filters.apply_membership(df, competitions=["French Open Women Singles"])["player"]) == {"Aryna Sabalenka"}
    assert set(filters.apply_membership(df, layers=["Reach Semifinal"])["player"]) == {"Carlos Alcaraz"}
    assert set(filters.apply_membership(df, event_query="and")["player"]) == {"Aryna Sabalenka"}   # ticker substring
    assert set(filters.apply_membership(df, player_query="alcaraz")["player"]) == {"Carlos Alcaraz"}
    assert set(filters.apply_membership(df, min_volume=50)["player"]) == {"Aryna Sabalenka"}


def test_membership_empty_frame_keeps_columns():
    empty = pd.DataFrame(columns=list(_BASE))
    out = filters.apply_membership(empty, categories=["Tournament winner"], min_volume=10)
    assert out.empty and list(out.columns) == list(_BASE)


# --- thresholds ----------------------------------------------------------------------
def test_threshold_min_edge_and_size():
    df = _df(_row(executable_gap=4, exec_min_size=80), _row(executable_gap=1, exec_min_size=10))
    assert len(filters.apply_thresholds(df, min_edge_c=2)) == 1
    assert len(filters.apply_thresholds(df, min_size=50)) == 1


def test_threshold_quote_and_status():
    df = _df(
        _row(comp_quote_quality="Tight", child_status="active", parent_status="active"),
        _row(comp_quote_quality="Wide", child_status="active", parent_status="finalized"),
    )
    assert len(filters.apply_thresholds(df, quote_mode="Tight/OK only")) == 1
    assert len(filters.apply_thresholds(df, status_mode="Active only")) == 1   # finalized parent dropped


def test_threshold_nan_safe_and_passthrough():
    df = _df(_row(executable_gap=None, exec_min_size=None))
    # no thresholds -> unchanged; min_edge with NaN gap -> dropped (treated as -inf)
    assert len(filters.apply_thresholds(df)) == 1
    assert len(filters.apply_thresholds(df, min_edge_c=1)) == 0


def test_thresholds_spare_actionable_two_pass():
    # An actionable row with a small (sub-threshold) gap survives the membership pass but would be
    # dropped by thresholds — which is why the app takes Actionable from `universe`, not `thresholded`.
    df = _df(_row(bucket="actionable", executable_gap=1))
    universe = filters.apply_membership(df)
    thresholded = filters.apply_thresholds(universe, min_edge_c=2)
    assert len(universe[universe["bucket"] == "actionable"]) == 1   # Actionable keeps it
    assert len(thresholded) == 0                                    # other sections would not
