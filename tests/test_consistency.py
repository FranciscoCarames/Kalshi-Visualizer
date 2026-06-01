"""Unit tests for the layer-consistency classifier (no network)."""
from __future__ import annotations

import consistency


def leg(display_c=None, bid_c=None, ask_c=None, bid_size=100, ask_size=100,
        quality="Tight", rules=""):
    """Build a minimal contract row as consumed by consistency._classify/_leg."""
    return {
        "display_c": display_c,
        "yes_bid_c": bid_c,
        "yes_ask_c": ask_c,
        "yes_bid_size": bid_size,
        "yes_ask_size": ask_size,
        "quote_quality": quality,
        "rules_primary": rules,
    }


def test_executable_violation_requires_cross_and_size():
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["status_group"] == "Broken"
    assert out["executable_gap"] == 2


def test_cross_without_size_downgrades_to_quote_size_missing():
    child = leg(display_c=30, bid_c=37, ask_c=38, bid_size=0)   # no firm size behind the bid
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "QUOTE_SIZE_MISSING"
    assert out["status_group"] == "Missing data"


def test_display_violation_is_warning_not_broken():
    child = leg(display_c=50, bid_c=20, ask_c=22)
    parent = leg(display_c=40, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "DISPLAY_VIOLATION"
    assert out["status_group"] == "Warning"


def test_missing_quote_when_no_firm_book():
    child = leg(display_c=10, bid_c=0, ask_c=100, quality="No quote")  # empty 0/1 book
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "MISSING_QUOTE"


def test_missing_quote_when_no_display():
    child = leg(display_c=None, bid_c=10, ask_c=12)
    parent = leg(display_c=40, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "MISSING_QUOTE"


def test_wide_quote_when_ordered_but_wide():
    child = leg(display_c=20, bid_c=10, ask_c=30, quality="Wide")
    parent = leg(display_c=50, bid_c=40, ask_c=60, quality="Wide")
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "WIDE_QUOTE"
    assert out["status_group"] == "Warning"


def test_clean_when_ordered_and_tight():
    child = leg(display_c=20, bid_c=10, ask_c=12)
    parent = leg(display_c=50, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "CLEAN"
    assert out["status_group"] == "Clean"


def test_equivalence_checks_both_directions():
    # No forward cross (child_bid 19 vs parent_ask 40), but reverse crosses
    # (parent_bid 37 vs child_ask 35) -> executable violation via the equivalence path.
    child = leg(display_c=30, bid_c=19, ask_c=35)
    parent = leg(display_c=30, bid_c=37, ask_c=40)
    out = consistency._classify(child, parent, equivalence=True)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["executable_gap"] == 2


def test_equivalence_sets_rule_flag():
    child = leg(display_c=30, bid_c=10, ask_c=12, rules="match resolves after a ball has been played; walkover voids")
    parent = leg(display_c=50, bid_c=58, ask_c=60, rules="market resolves when player qualifies")
    out = consistency._classify(child, parent, equivalence=True)
    assert out["rule_flag"] in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH")
    # differing settlement-nuance tokens -> mismatch
    assert out["rule_flag"] == "RULE_MISMATCH"

    same = consistency._classify(
        leg(display_c=30, bid_c=10, ask_c=12, rules="plain rules"),
        leg(display_c=50, bid_c=58, ask_c=60, rules="plain rules"),
        equivalence=True,
    )
    assert same["rule_flag"] == "RULE_CHECK_REQUIRED"
    # containment pairs carry no rule flag
    assert consistency._classify(leg(display_c=20, bid_c=10, ask_c=12),
                                 leg(display_c=50, bid_c=58, ask_c=60),
                                 equivalence=False)["rule_flag"] == ""


def test_expected_nodes_marks_missing_layer():
    # A player with only a winner market -> Reach SF / Reach Final missing.
    rows = [{"kind": "winner", "stage": "Champion"}]
    nodes = {n["layer"]: n for n in consistency.expected_nodes(rows)}
    assert nodes["Win Tournament"]["found"] is True
    assert nodes["Win Tournament"]["source"] == "market"
    assert nodes["Reach Semifinal"]["found"] is False
    assert nodes["Reach Final"]["found"] is False
