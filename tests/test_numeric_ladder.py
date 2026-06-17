"""Unit tests for the S2 numeric-strike ladder builder (no network).

Row shapes mirror live Kalshi data captured 2026-06-17 (event KXATPGTOTAL-26JUN17MEDHUM):
`Over 19.5/24.5/29.5 games`, each market_type=binary, strike_type=greater, floor_strike=N, cap_strike=null.
"""
from __future__ import annotations

import numeric_ladder as nl


def _ge(event, floor, *, series="KXATPGTOTAL", st="greater"):
    return {"series_ticker": series, "event_ticker": event, "strike_type": st,
            "floor_strike": floor, "cap_strike": None, "market_type": "binary",
            "yes_sub_title": f"Over {floor} games"}


def _le(event, cap, *, series="KXNBA1HTOTAL", st="less"):
    return {"series_ticker": series, "event_ticker": event, "strike_type": st,
            "floor_strike": None, "cap_strike": cap, "market_type": "binary",
            "yes_sub_title": f"Under {cap} points"}


# --- parse_numeric_strike ------------------------------------------------------------
def test_parse_greater_uses_floor_strike():
    assert nl.parse_numeric_strike(_ge("E", 19.5)) == ("ge", 19.5)


def test_parse_greater_or_equal():
    assert nl.parse_numeric_strike(_ge("E", 20, st="greater_or_equal")) == ("ge", 20.0)


def test_parse_less_uses_cap_strike():
    assert nl.parse_numeric_strike(_le("E", 30)) == ("le", 30.0)


def test_parse_less_or_equal():
    assert nl.parse_numeric_strike(_le("E", 30, st="less_or_equal")) == ("le", 30.0)


def test_parse_rejects_custom_structured_between_and_missing():
    # custom = exact-score; structured = leader fields; between = bracket (S3, not monotone here).
    assert nl.parse_numeric_strike({"strike_type": "custom", "floor_strike": None}) is None
    assert nl.parse_numeric_strike({"strike_type": "structured", "floor_strike": None}) is None
    assert nl.parse_numeric_strike({"strike_type": "between", "floor_strike": 10, "cap_strike": 20}) is None
    assert nl.parse_numeric_strike({"strike_type": "", "floor_strike": 5}) is None


def test_parse_rejects_missing_or_nonnumeric_value():
    assert nl.parse_numeric_strike(_ge("E", None)) is None           # greater but no floor_strike
    assert nl.parse_numeric_strike(_le("E", None)) is None           # less but no cap_strike
    assert nl.parse_numeric_strike({"strike_type": "greater", "floor_strike": "n/a"}) is None


# --- build_numeric_ladders -----------------------------------------------------------
def test_builds_ge_ladder_broad_to_deep_ascending():
    rows = [_ge("E1", 29.5), _ge("E1", 19.5), _ge("E1", 24.5)]   # deliberately unsorted
    ladders = nl.build_numeric_ladders(rows)
    assert len(ladders) == 1
    lad = ladders[0]
    assert lad.direction == "ge"
    strikes = [s for s, _r in lad.rungs]
    assert strikes == [19.5, 24.5, 29.5]                         # broad (low bar) -> deep (high bar)


def test_builds_le_ladder_broad_to_deep_descending():
    rows = [_le("E1", 20), _le("E1", 30), _le("E1", 25)]
    ladders = nl.build_numeric_ladders(rows)
    assert len(ladders) == 1
    assert ladders[0].direction == "le"
    assert [s for s, _ in ladders[0].rungs] == [30.0, 25.0, 20.0]  # broad (high cap) -> deep (low cap)


def test_mixed_directions_split_into_two_ladders_never_one():
    rows = [_ge("E1", 19.5), _ge("E1", 24.5), _le("E1", 30, series="KXATPGTOTAL"),
            _le("E1", 25, series="KXATPGTOTAL")]
    ladders = nl.build_numeric_ladders(rows)
    dirs = sorted(lad.direction for lad in ladders)
    assert dirs == ["ge", "le"]                                   # two separate monotone ladders


def test_single_rung_group_is_not_a_ladder():
    assert nl.build_numeric_ladders([_ge("E1", 19.5)]) == []


def test_ineligible_rows_are_dropped_silently():
    rows = [_ge("E1", 19.5), _ge("E1", 24.5),
            {"series_ticker": "KXATPEXACTMATCH", "event_ticker": "E1", "strike_type": "custom"}]
    ladders = nl.build_numeric_ladders(rows)
    assert len(ladders) == 1 and len(ladders[0].rungs) == 2


def test_duplicate_strike_does_not_fabricate_a_rung():
    dup = [_ge("E1", 19.5), _ge("E1", 19.5)]                     # same strike twice
    assert nl.build_numeric_ladders(dup) == []                   # < 2 DISTINCT strikes
    three = [_ge("E1", 19.5), _ge("E1", 19.5), _ge("E1", 24.5)]
    out = nl.build_numeric_ladders(three)
    assert len(out) == 1 and [s for s, _ in out[0].rungs] == [19.5, 24.5]


def test_different_events_are_separate_ladders():
    rows = [_ge("E1", 19.5), _ge("E1", 24.5), _ge("E2", 19.5), _ge("E2", 24.5)]
    ladders = nl.build_numeric_ladders(rows)
    assert len(ladders) == 2
    assert {lad.group_key for lad in ladders} == {
        ("KXATPGTOTAL", "E1"), ("KXATPGTOTAL", "E2")}


def test_per_participant_family_needs_a_richer_group_key():
    # Two players' spread ladders in ONE event are DIFFERENT scalars. The default (series,event) key
    # would wrongly merge them; a participant-aware key separates them (documents the identity caveat).
    rows = [
        {"series_ticker": "KXATPGSPREAD", "event_ticker": "E1", "strike_type": "greater",
         "floor_strike": 1.5, "player": "A"},
        {"series_ticker": "KXATPGSPREAD", "event_ticker": "E1", "strike_type": "greater",
         "floor_strike": 4.5, "player": "A"},
        {"series_ticker": "KXATPGSPREAD", "event_ticker": "E1", "strike_type": "greater",
         "floor_strike": 1.5, "player": "B"},
        {"series_ticker": "KXATPGSPREAD", "event_ticker": "E1", "strike_type": "greater",
         "floor_strike": 4.5, "player": "B"},
    ]
    merged = nl.build_numeric_ladders(rows)                       # default key: wrongly 1 group, dup strikes
    assert len(merged) == 1 and len(merged[0].rungs) == 2        # 1.5 & 4.5 (dups collapsed) — WRONG scalar
    split = nl.build_numeric_ladders(
        rows, group_key_fn=lambda r: (r["series_ticker"], r["event_ticker"], r.get("player")))
    assert len(split) == 2                                        # one clean ladder per player
