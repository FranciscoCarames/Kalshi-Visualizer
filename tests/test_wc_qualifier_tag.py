"""PR1 — World Cup Qualifier Setups: the `setup_family`/`setup_type` cross-cutting tag + UI badge.

The tag flags setups #1/#2/#3 IN PLACE — they keep their actionable/blocked bucket; only the tag is
added. These tests pin that: the right rows get the right tag, unrelated rows stay untagged, and the
tag never changes routing.
"""

import api
import scanner
import sports
from webui import viewmodel

SOCCER = sports.SOCCER
TENNIS = sports.TENNIS


def _basket_finding(direction="yes_basket", bucket="actionable", status="EXECUTABLE_GROUP_BASKET"):
    return {"match": "World Cup group basket", "direction": direction, "bucket": bucket, "status": status,
            "tradable_now": "Yes", "cost_c": 180, "exec_gap_c": 20, "payout_floor_c": 200,
            "action_1_text": "Buy YES — A @ 45", "action_2_text": "Buy YES — B @ 45",
            "action_1_price_c": 45, "action_2_price_c": 45,
            "player_key_a": "a", "player_a": "A", "player_key_b": "b", "player_b": "B",
            "relationship_type": "group_cardinality_floor", "opportunity_id": "oid-basket"}


def _containment_row(child_node, parent_node, *, bucket="actionable", status="EXECUTABLE_VIOLATION"):
    return {"player": "Canada", "player_key": "can", "chain": f"{child_node} ≤ {parent_node}",
            "child_node": child_node, "parent_node": parent_node, "bucket": bucket, "status": status,
            "tradable_now": "Yes", "action_1_price_c": 35, "action_2_price_c": 63,
            "opportunity_id": "oid-cont", "relationship_type": "containment_adjacent"}


# --- #2/#3 group baskets ----------------------------------------------------------------------------
def test_yes_basket_tagged_and_bucket_unchanged():
    d = scanner._to_unified_group_basket(_basket_finding("yes_basket", bucket="actionable"), SOCCER)
    assert d["setup_family"] == "wc_qualifier"
    assert d["setup_type"] == "qualifier_yes_basket"
    assert d["bucket"] == "actionable"        # tag does NOT move it out of its section
    assert d["source"] == "group_basket"


def test_no_basket_tagged():
    d = scanner._to_unified_group_basket(_basket_finding("no_basket", bucket="blocked"), SOCCER)
    assert d["setup_type"] == "qualifier_no_basket"
    assert d["bucket"] == "blocked"


# --- #1 qualifier-not-winner containment leaf -------------------------------------------------------
def test_win_group_leaf_tagged_as_qualifier_not_winner():
    d = scanner._to_unified_consistency(_containment_row("Win group", "Reach Round of 32"), SOCCER)
    assert d["setup_family"] == "wc_qualifier"
    assert d["setup_type"] == "qualifier_not_winner"
    assert d["bucket"] == "actionable"


def test_other_soccer_containment_not_tagged():
    # A different soccer ladder pair must NOT be tagged (tight gate on the exact node pair).
    d = scanner._to_unified_consistency(
        _containment_row("Win the World Cup", "Reach Finals"), SOCCER)
    assert d["setup_family"] == ""
    assert d["setup_type"] == ""


def test_non_soccer_rows_untagged():
    # A tennis containment row and a non-soccer basket-shaped dutch book carry empty tags.
    cont = scanner._to_unified_consistency(_containment_row("Win Tournament", "Reach Final"), TENNIS)
    assert cont["setup_family"] == "" and cont["setup_type"] == ""
    book = scanner._to_unified_dutchbook(_basket_finding(), TENNIS)
    assert book["setup_family"] == "" and book["setup_type"] == ""


# --- schema / defaults ------------------------------------------------------------------------------
def test_unified_columns_declare_tag_fields():
    assert "setup_family" in scanner.UNIFIED_COLUMNS
    assert "setup_type" in scanner.UNIFIED_COLUMNS


def test_every_mapper_defaults_tag_to_empty_string():
    # _finalize_unified backfills "" so old snapshots / untagged shapes never KeyError.
    syn = scanner._to_unified_synthetic({"legs": []}, TENNIS)
    assert syn["setup_family"] == "" and syn["setup_type"] == ""


def test_api_opportunity_preserves_tag_fields():
    # extra="ignore" would drop undeclared fields — assert they survive the model round-trip.
    d = scanner._to_unified_group_basket(_basket_finding("yes_basket"), SOCCER)
    model = api.Opportunity(**d)
    assert model.setup_family == "wc_qualifier"
    assert model.setup_type == "qualifier_yes_basket"


# --- UI badge ---------------------------------------------------------------------------------------
def test_detail_badge_prefixed_for_tagged_rows_only():
    tagged = {"setup_family": "wc_qualifier", "detail": "yes_basket"}
    assert viewmodel._detail_with_badge(tagged).startswith("🏆 WC Qualifier")
    assert "yes_basket" in viewmodel._detail_with_badge(tagged)
    untagged = {"setup_family": "", "detail": "Win ≤ Final"}
    assert viewmodel._detail_with_badge(untagged) == "Win ≤ Final"


def test_opp_row_carries_tag_and_badges_detail():
    o = scanner._to_unified_group_basket(_basket_finding("yes_basket"), SOCCER)
    o["opportunity_id"] = "oid-basket"
    row = viewmodel.opp_row(o, new_ids=set())
    assert row["setup_family"] == "wc_qualifier"
    assert row["setup_type"] == "qualifier_yes_basket"
    assert row["detail"].startswith("🏆 WC Qualifier")
