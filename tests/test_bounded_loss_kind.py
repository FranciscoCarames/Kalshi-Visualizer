"""PR B — Bounded-Loss Vertical (simultaneous) vs Calendar (sequential) resolution split.

Classification is STRUCTURAL and per-pair (never per-sport, no timestamps): a finishing-position ladder
(golf Top-N / motorsport) resolves all rungs at one event -> vertical; a stage-advancement ladder settles
across rounds -> calendar; a match-alignment equivalence resolves at one match -> vertical; the soccer
"Win group" -> "Reach Round of 32" leaf is calendar (best-third qualifiers settle after all groups finish)
and carries a non-blocking settlement caveat. The `_row`-level computation is covered in test_consistency.
"""
import scanner
import sports
from webui import viewmodel as vm


def test_finishing_ladders_are_simultaneous_advancement_ladders_are_not():
    assert sports.GOLF.ladder.simultaneous is True
    # motorsport's per-race finishing ladders (built by _motor_ladder, returned by ladder_fn) are simultaneous
    assert sports._motor_ladder("Top 5", "Win Race").simultaneous is True
    # every stage-advancement ladder settles across rounds -> sequential (the conservative default)
    for cfg in (sports.TENNIS, sports.NBA, sports.WNBA, sports.MLB, sports.NHL, sports.NFL, sports.SOCCER):
        assert cfg.ladder.simultaneous is False


def test_containment_row_propagates_resolution_mode():
    d = scanner._to_unified_consistency(
        {"child_node": "Top 5", "parent_node": "Top 10", "resolution_mode": "vertical",
         "relationship_type": "containment_adjacent"}, sports.GOLF)
    assert d["resolution_mode"] == "vertical"
    assert d["settlement_caveat"] == ""        # only the soccer leaf attaches a caveat


def test_soccer_qualifier_leaf_is_calendar_with_best_third_caveat():
    d = scanner._to_unified_consistency(
        {"player": "Brazil", "player_key": "k", "chain": "Win group <= Reach Round of 32",
         "child_node": "Win group", "parent_node": "Reach Round of 32",
         "relationship_type": "containment_adjacent", "resolution_mode": "calendar"}, sports.SOCCER)
    assert d["resolution_mode"] == "calendar"
    assert "best-third" in d["settlement_caveat"]
    assert d["setup_type"] == "qualifier_not_winner"       # still the qualifier-not-winner tag


def test_dutchbook_default_resolution_mode_is_calendar():
    # A non-containment shape never sets resolution_mode; _finalize_unified defaults it to calendar.
    d = scanner._to_unified_dutchbook(
        {"match": "A vs B", "direction": "underround", "cost_c": 98}, sports.TENNIS)
    assert d["resolution_mode"] == "calendar"


def test_split_by_resolution_partitions_and_defaults_calendar():
    rows = [{"opportunity_id": "v", "resolution_mode": "vertical"},
            {"opportunity_id": "c", "resolution_mode": "calendar"},
            {"opportunity_id": "old"}]                       # missing (old snapshot) -> calendar
    vertical, calendar = vm.split_by_resolution(rows)
    assert [o["opportunity_id"] for o in vertical] == ["v"]
    assert [o["opportunity_id"] for o in calendar] == ["c", "old"]   # order preserved
    assert vm.split_by_resolution(None) == ([], [])
