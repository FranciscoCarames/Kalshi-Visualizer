"""Unit tests for the synthetic-bundle parsing + format layer (Stage m5, Task 2). No network."""
from __future__ import annotations

import sports
import synthetic_bundle as sb


# --- parse_scoreline ------------------------------------------------------------------------
def test_parse_scoreline_from_structured_custom_strike():
    # Primary, verified-live source: custom_strike["Set Score"] (stamped as raw_custom_strike).
    row = {"raw_custom_strike": {"Set Score": "3-0", "tennis_competitor": "uuid-x"}}
    assert sb.parse_scoreline(row) == "3-0"
    assert sb.parse_scoreline({"raw_custom_strike": {"Set Score": " 2 - 1 "}}) == "2-1"


def test_parse_scoreline_falls_back_to_subtitle_regex():
    # No structured strike -> recover the score from the display subtitle.
    assert sb.parse_scoreline({"yes_sub_title": "Jakub Mensik wins 3-1"}) == "3-1"
    assert sb.parse_scoreline({"raw_custom_strike": {}, "player_name_raw": "X wins 2-0"}) == "2-0"


def test_parse_scoreline_none_when_absent_or_unparseable():
    assert sb.parse_scoreline({}) is None
    assert sb.parse_scoreline({"raw_custom_strike": None, "yes_sub_title": "no score here"}) is None
    assert sb.parse_scoreline({"raw_custom_strike": {"Set Score": ""}}) is None


# --- score_format resolver (the format must be PROVEN, not assumed from ATP/WTA alone) ------
def test_score_format_mens_grand_slam_is_best_of_5():
    assert sports.TENNIS.score_format("ATP", "French Open") == "tennis_bo5"
    assert sports.TENNIS.score_format("ATP", "Wimbledon") == "tennis_bo5"


def test_score_format_wta_and_non_slam_atp_are_best_of_3():
    assert sports.TENNIS.score_format("WTA", "French Open") == "tennis_bo3"   # women's Slam = bo3
    assert sports.TENNIS.score_format("ATP", "Rome Masters") == "tennis_bo3"  # ATP NON-Slam = bo3


def test_score_format_unprovable_tournament_returns_none():
    assert sports.TENNIS.score_format("ATP", "") is None
    assert sports.TENNIS.score_format("ATP", "Unknown · KXATPEXACTMATCH-26XYZ") is None


def test_score_format_absent_for_sports_without_bundles():
    # NBA/WNBA have no score_format_fn -> always None (so adding a sport stays one register() call).
    assert sports.NBA.score_format("ATP", "French Open") is None
    assert sports.NBA.state_bundles == {}


# --- expected_states (format-gated; independent of discovered markets) ----------------------
def test_expected_states_resolves_per_format():
    assert sb.expected_states(sports.TENNIS, "ATP", "French Open") == ("3-0", "3-1", "3-2")
    assert sb.expected_states(sports.TENNIS, "WTA", "French Open") == ("2-0", "2-1")
    assert sb.expected_states(sports.TENNIS, "ATP", "Rome Masters") == ("2-0", "2-1")


def test_expected_states_none_when_format_unprovable_or_unsupported():
    assert sb.expected_states(sports.TENNIS, "ATP", "Unknown · x") is None
    assert sb.expected_states(sports.NBA, "ATP", "French Open") is None
