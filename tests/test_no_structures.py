"""Unit tests for the NO-anchored structures detector (`no_structures.find_no_structures`) + its viewmodel
section. Synthetic rows shaped like `data.build_contracts` output; assertions on band/outright economics,
duplicate suppression, skip rules, and the speculative-isolation contract.
"""
import pandas as pd

import config
import consistency
import no_structures
import scanner
import sports
import webui.viewmodel as vm

# Tennis advance ladder (broad→deep): Reach Semifinal ⊇ Reach Final ⊇ Win Tournament.
_PARENT = "Reach Semifinal"   # broader
_CHILD = "Reach Final"        # deeper


def market(node, *, yes_ask_c=None, yes_bid_c=None, no_ask_c=None, display_c=None,
           yes_bid_size=200, yes_ask_size=200, quality="Tight", status="active", subpenny=False,
           player="Sinner", player_key="uuid-sinner", tournament="French Open", kind="advance",
           series="KXATPADVANCE", category="Stage advancement"):
    """One advance-market row as produced by data.build_contracts (only the fields the detector reads)."""
    return {
        "player": player, "player_key": player_key, "tournament": tournament, "tour": "ATP",
        "series": series, "kind": kind, "ladder_node": node, "stage": None, "category": category,
        "quote_quality": quality, "status": status, "subpenny": subpenny,
        "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c,
        "yes_bid_size": yes_bid_size, "yes_ask_size": yes_ask_size,
        "display_c": display_c, "display_pct": None,
        "contract": node, "market_ticker": f"KXATPADVANCE-{node.replace(' ', '')}",
        "kalshi_url": "https://kalshi.com/x",
    }


def _bands(findings):
    return [f for f in findings if f["status"] == no_structures.NO_STRUCTURE_BAND]


def _outrights(findings):
    return [f for f in findings if f["status"] == no_structures.NO_STRUCTURE_OUTRIGHT]


# --- band economics ----------------------------------------------------------------------------------
def test_band_cost_over_100_is_bounded_loss():
    # parent Reach SF YES ask 96; child Reach Final NO ask 10 → cost 106, max loss 6, band pays 200.
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    bands = _bands(no_structures.find_no_structures([parent, child]))
    assert len(bands) == 1
    b = bands[0]
    assert b["cost_c"] == 106 and b["max_loss_c"] == 6
    assert b["worst_case_profit_c"] == -6 and b["best_case_profit_c"] == 94
    assert b["buy_no_c"] == 10 and b["action_1_price_c"] == 96
    assert b["child_node"] == _CHILD and b["parent_node"] == _PARENT
    assert b["exec_min_size"] == 200 and b["display_spread_c"] == 6


def test_band_cost_below_100_suppressed_as_strict_cross():
    # parent ask 80, child NO ask 10 (child YES bid 90 > parent ask 80) → cost 90 < 100 = an EXECUTABLE
    # containment cross the consistency checker owns. No band emitted.
    parent = market(_PARENT, yes_ask_c=80, yes_bid_c=78, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=92, yes_bid_c=90, no_ask_c=10)
    assert _bands(no_structures.find_no_structures([parent, child])) == []


def test_band_cost_exactly_100_emitted_zero_loss_with_caveat():
    parent = market(_PARENT, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    child = market(_CHILD, yes_ask_c=88, yes_bid_c=86, no_ask_c=10, display_c=85)
    bands = _bands(no_structures.find_no_structures([parent, child]))
    assert len(bands) == 1 and bands[0]["cost_c"] == 100 and bands[0]["max_loss_c"] == 0
    assert "free money" in bands[0]["settlement_caveat"]


def test_band_over_maxloss_cap_skipped():
    # cost 141 → max loss 41 > NO_STRUCTURE_BAND_MAX_LOSS_C (40) → skipped.
    assert config.NO_STRUCTURE_BAND_MAX_LOSS_C == 40
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=50, yes_bid_c=48, no_ask_c=45)   # cost 96+45=141
    assert _bands(no_structures.find_no_structures([parent, child])) == []


def test_band_breakeven_equals_max_loss():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    band = scanner._to_unified_no_structure(_bands(no_structures.find_no_structures([parent, child]))[0],
                                            sports.TENNIS)
    assert vm._breakeven_pct(band) == 6.0          # == max loss ¢, by the containment band identity


# --- outright economics ------------------------------------------------------------------------------
def test_outright_cheap_no_emitted_dear_no_skipped():
    cheap = market(_CHILD, yes_ask_c=92, yes_bid_c=90, no_ask_c=10)   # buy NO 10 ≤ 25 → emitted
    dear = market(_PARENT, yes_ask_c=72, yes_bid_c=70, no_ask_c=30)   # buy NO 30 > 25 → skipped
    outs = _outrights(no_structures.find_no_structures([cheap, dear]))
    assert {o["buy_no_c"] for o in outs} == {10}
    o = outs[0]
    assert o["cost_c"] == 10 and o["max_loss_c"] == 10
    assert o["worst_case_profit_c"] == -10 and o["best_case_profit_c"] == 90
    assert o["action_2_side"] == "buy_no" and o["action_1_side"] is None


def test_outright_buy_no_falls_back_to_yes_bid():
    # no no_ask_c field → buy NO = 100 − yes_bid_c = 100 − 88 = 12.
    r = market(_CHILD, yes_ask_c=90, yes_bid_c=88)
    outs = _outrights(no_structures.find_no_structures([r]))
    assert len(outs) == 1 and outs[0]["buy_no_c"] == 12


# --- skip rules --------------------------------------------------------------------------------------
def test_skips_inactive_no_quote_crossed_subpenny_zero_size():
    base = dict(yes_ask_c=92, yes_bid_c=90, no_ask_c=10)
    assert no_structures.find_no_structures([market(_CHILD, status="finalized", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="No quote", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="Crossed", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="One-sided", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, subpenny=True, **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, yes_bid_size=0, **base)]) == []


def test_band_requires_both_legs_firm():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, status="finalized")
    assert _bands(no_structures.find_no_structures([parent, child])) == []


# --- viewmodel: filtering, ranking, isolation --------------------------------------------------------
def _unified(rows):
    def fetch(sid):
        return pd.DataFrame(rows) if sid == "tennis" else None
    unified, _ = scanner.unified_opportunities(fetch)
    return unified.to_dict("records")


def test_view_filters_kind_maxloss_and_buy_no():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    opps = _unified([parent, child])
    assert all(o["exec_gap_c"] != o["exec_gap_c"] or o["exec_gap_c"] is None      # exec_gap_c NaN/None
               for o in opps if o["bucket"] == "no_structure")
    bands = vm.no_structure_view(opps, max_loss_c=10, kind="band")
    assert len(bands) == 1 and bands[0]["status"] == no_structures.NO_STRUCTURE_BAND
    outs = vm.no_structure_view(opps, max_loss_c=100, kind="outright")
    assert outs and all(not vm._is_band(o) for o in outs)
    # max Buy-NO gate: the 6¢ outright (parent NO) passes a 6¢ cap; the 10¢ child NO does not.
    capped = vm.no_structure_view(opps, max_loss_c=100, kind="outright", max_buy_no_c=6)
    assert {o["action_2_price_c"] for o in capped} == {6}


def test_view_good_quote_only_default_filters_wide():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95, quality="Wide")
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89, quality="Wide")
    opps = _unified([parent, child])
    assert vm.no_structure_view(opps, max_loss_c=100) == []                       # wide hidden by default
    assert vm.no_structure_view(opps, max_loss_c=100, good_quote_only=False)      # shown when opted out


def test_order_leads_with_lowest_max_loss_then_breakeven():
    a = {"opportunity_id": "a", "bucket": "no_structure", "worst_case_profit_c": -12,
         "best_case_profit_c": 88, "best_payout": 100, "action_2_price_c": 12}
    b = {"opportunity_id": "b", "bucket": "no_structure", "worst_case_profit_c": -3,
         "best_case_profit_c": 97, "action_2_price_c": 3}
    ordered = vm._no_structure_order([a, b])
    assert [o["opportunity_id"] for o in ordered] == ["b", "a"]   # lower max loss (3) first


def test_row_builder_fields():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    opps = _unified([parent, child])
    band = vm.no_structure_view(opps, max_loss_c=10, kind="band")[0]
    row = vm.no_structure_row(band, set())
    assert row["kind"] == "Band" and row["buy_no"] == 10 and row["parent_yes"] == 96
    assert row["cost"] == 106 and row["max_loss"] == 6 and row["bonus_profit"] == 94
    assert row["convexity"] == round(200 / 106, 2) and row["breakeven"] == 6.0
    assert "but not" in row["wins_if"]


def test_bucket_sets_in_sync():
    assert set(scanner.BUCKET_PRIORITY) == set(consistency.DASHBOARD_BUCKETS)
    assert consistency.bucket_of({"status": "NO_STRUCTURE_BAND"}) == "no_structure"
    assert consistency.bucket_of({"status": "NO_STRUCTURE_OUTRIGHT"}) == "no_structure"
