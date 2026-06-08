"""Unit tests for webui.viewmodel (PR 22) — pure filtering / options / scope banner / URL state."""
from __future__ import annotations

from webui import viewmodel as vm


def _opp(oid, *, sport="tennis", bucket="blocked", source="containment", tournament="French Open",
         name="Alcaraz", size=100, market_status="active"):
    return {"opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": source,
            "bucket": bucket, "tournament": tournament, "name": name,
            "exec_min_size": size, "market_status": market_status, "exec_gap_c": 5}


# --- membership narrows every bucket --------------------------------------------------
def test_membership_sport_and_tournament_narrow_all():
    opps = [_opp("a", sport="tennis", bucket="actionable", tournament="French Open"),
            _opp("b", sport="nba", bucket="blocked", tournament="NBA Finals")]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, sports=["tennis"])] == ["a"]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, tournaments=["NBA Finals"])] == ["b"]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps)] == ["a", "b"]   # no filter = identity


def test_participant_is_a_case_insensitive_substring():
    opps = [_opp("a", name="Alcaraz vs Sinner"), _opp("b", name="Gauff vs Swiatek")]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, participant="sinner")] == ["a"]
    assert vm.filter_opps(opps, participant="nobody") == []


# --- thresholds spare Actionable + dutch-book -----------------------------------------
def test_min_size_spares_actionable_and_dutchbook():
    opps = [_opp("act", bucket="actionable", source="containment", size=1),   # spared (actionable)
            _opp("db", bucket="blocked", source="dutch_book", size=1),        # spared (dutch_book)
            _opp("blk", bucket="blocked", source="containment", size=1),      # subject -> dropped
            _opp("big", bucket="blocked", source="containment", size=500)]
    assert {o["opportunity_id"] for o in vm.filter_opps(opps, min_size=50)} == {"act", "db", "big"}


def test_active_only_spares_actionable_and_dutchbook():
    opps = [_opp("act", bucket="actionable", source="containment", market_status="finalized"),  # spared
            _opp("db", bucket="blocked", source="dutch_book", market_status="finalized"),        # spared
            _opp("blk_in", bucket="blocked", source="containment", market_status="finalized"),   # dropped
            _opp("blk_ok", bucket="blocked", source="containment", market_status="active")]
    assert {o["opportunity_id"] for o in vm.filter_opps(opps, active_only=True)} == {"act", "db", "blk_ok"}


def test_min_size_is_nan_safe():
    nan = float("nan")
    assert vm.filter_opps([_opp("n", bucket="blocked", source="containment", size=nan)], min_size=10) == []
    # a spared (actionable) row with no size survives — thresholds never touch it.
    assert len(vm.filter_opps([_opp("n", bucket="actionable", size=nan)], min_size=10)) == 1


# --- per-bucket counts (PR 4) ---------------------------------------------------------
def test_bucket_counts_membership_vs_threshold_split():
    opps = [
        _opp("a", bucket="actionable", source="containment", size=1),      # spared -> shown despite tiny size
        _opp("r1", bucket="review_signal", source="containment", size=500),
        _opp("r2", bucket="review_signal", source="containment", size=1),   # threshold drops at min_size
        _opp("b", bucket="blocked", sport="nba", source="containment", size=500),  # membership drops on sport
    ]
    c = vm.bucket_counts(opps, {})                                          # no filters -> all equal totals
    assert c["actionable"] == {"total": 1, "in_scope": 1, "shown": 1}
    assert c["review_signal"]["total"] == 2 and c["review_signal"]["shown"] == 2
    c2 = vm.bucket_counts(opps, {"sports": ["tennis"]})                     # membership hides the nba blocked row
    assert c2["blocked"]["total"] == 1 and c2["blocked"]["in_scope"] == 0
    c3 = vm.bucket_counts(opps, {"min_size": 50})                           # threshold hides the tiny review row
    assert c3["review_signal"]["in_scope"] == 2 and c3["review_signal"]["shown"] == 1
    assert c3["actionable"]["shown"] == 1                                   # Actionable spared from thresholds


def test_bucket_counts_line_distinguishes_toggle_and_threshold():
    counts = {"actionable": {"total": 4, "in_scope": 4, "shown": 4},
              "review_signal": {"total": 3, "in_scope": 3, "shown": 3},
              "blocked": {"total": 9, "in_scope": 9, "shown": 9},
              "risk_budget": {"total": 0, "in_scope": 0, "shown": 0}}
    line = vm.bucket_counts_line(counts, {"review_signal": True, "blocked": False})
    assert "Actionable: 4 shown" in line and "Review: 3 shown" in line
    assert "Blocked: hidden by settings (9 in scope)" in line              # toggle-off, content exists
    assert "Speculative" not in line                                       # 0 in scope -> omitted
    line2 = vm.bucket_counts_line({"review_signal": {"total": 3, "in_scope": 3, "shown": 1}},
                                  {"review_signal": True})
    assert "Review: 1 shown / 3 in scope" in line2                         # threshold-hidden -> shown/in-scope


# --- derive_options -------------------------------------------------------------------
def test_derive_options_only_present_sorted():
    opps = [_opp("a", sport="tennis", tournament="French Open"),
            _opp("b", sport="nba", tournament="NBA Finals"),
            _opp("c", sport="tennis", tournament="French Open")]
    opt = vm.derive_options(opps)
    assert opt["sports"] == {"nba": "Nba", "tennis": "Tennis"}        # id->label, sorted, deduped
    assert opt["tournaments"] == ["French Open", "NBA Finals"]


# --- scope banner ---------------------------------------------------------------------
def test_scope_banner_with_meta_shows_both_counters():
    cov = {"meta_present": True, "fetched_at": "2026-06-04 12:00:00 UTC", "opportunities": 7,
           "scanned": 30, "failed": 2, "contracts_scanned": 1493, "checks_tested": 1098,
           "kalshi_requests": 48}
    s = vm.scope_banner(cov, "UTC")
    assert "7 opportunities" in s and "30 series · 2 failed" in s
    # Thousands separators on the large counts (readability).
    assert "1,493 contracts scanned · 1,098 checks tested" in s and "48 Kalshi requests" in s


def test_scope_banner_honest_when_no_scan_or_no_meta():
    assert vm.scope_banner({"fetched_at": None}, "UTC").startswith("No scan yet")
    s = vm.scope_banner({"meta_present": False, "fetched_at": "2026-06-04 12:00:00 UTC", "opportunities": 0}, "UTC")
    assert "no coverage meta" in s


# --- URL state round-trip + graceful reset --------------------------------------------
def test_url_state_round_trip():
    # participant is now a LIST of keys (PR6); keys with commas/spaces survive via URL-encoding.
    state = {"sports": ["tennis", "nba"], "tournaments": ["French Open"],
             "participant": ["uuid-a", "key, with space"], "min_size": 50.0, "active_only": True}
    q = vm.query_from_state(state)
    assert q["sport"] == "tennis,nba" and q["tournament"] == "French Open"
    assert q["participant"] == "uuid-a,key%2C%20with%20space"   # comma/space encoded, not corrupting the join
    assert q["min_size"] == "50.0" and q["active"] == "1"
    back = vm.state_from_query(q)   # no options -> accept all
    assert back["sports"] == ["tennis", "nba"] and back["tournaments"] == ["French Open"]
    assert back["participant"] == ["uuid-a", "key, with space"]   # round-trips exactly
    assert back["min_size"] == 50.0 and back["active_only"] is True


def test_url_state_gracefully_drops_unknown_sport_tournament_and_participant():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"],
               "participants": [{"value": "uuid-a", "label": "Alcaraz"}]}
    q = {"sport": "tennis,golf", "tournament": "Wimbledon", "participant": "uuid-a,uuid-gone"}
    st = vm.state_from_query(q, options=options)
    assert st["sports"] == ["tennis"]            # golf isn't in the snapshot -> dropped, not errored
    assert "tournaments" not in st               # Wimbledon absent -> the whole (now-empty) key omitted
    assert st["participant"] == ["uuid-a"]       # the absent participant key is dropped (stale-link reset)


def test_active_filter_chips_labels():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"],
               "participants": [{"value": "uuid-a", "label": "Alcaraz"}]}
    chips = vm.active_filter_chips({"sports": ["tennis"], "participant": ["uuid-a"], "min_size": 50.0,
                                    "active_only": True}, options)
    assert "sport: Tennis" in chips and "participant: Alcaraz" in chips   # key -> label for display
    assert "min size ≥ 50" in chips and "active only" in chips
    assert vm.active_filter_chips({}) == []


def test_derive_options_participants_keyed_and_disambiguated():
    opps = [
        {"sport": "tennis", "participant_keys": ["k1"], "participant_labels": ["Alcaraz"]},
        {"sport": "tennis", "participant_keys": ["k2", "k3"], "participant_labels": ["Smith", "Smith"]},
    ]
    labels = {p["value"]: p["label"] for p in vm.derive_options(opps)["participants"]}
    assert labels["k1"] == "Alcaraz"                          # unique label stays clean
    assert labels["k2"] == "Smith [k2]" and labels["k3"] == "Smith [k3]"   # same name, diff key -> suffixed


def test_filter_opps_participant_or_match_by_key():
    opps = [{"participant_keys": ["ka", "kb"], "name": "A vs B"},
            {"participant_keys": ["kc"], "name": "C ladder"}]
    assert {o["name"] for o in vm.filter_opps(opps, participant=["kb"])} == {"A vs B"}     # B side reachable
    assert {o["name"] for o in vm.filter_opps(opps, participant=["ka", "kc"])} == {"A vs B", "C ladder"}  # OR
    assert len(vm.filter_opps(opps, participant=[])) == 2                                  # empty = no filter
    assert {o["name"] for o in vm.filter_opps(opps, participant="ladder")} == {"C ladder"}  # legacy substring


# --- ranking modes (#1/#9) — payoff geometry, no probability ----------------------------------------
def _o(oid, bucket="actionable", gap=None, roi=None, wc=None, bc=None,
       child_c=None, parent_c=None, soc=None, sop=None):
    return {"opportunity_id": oid, "bucket": bucket, "exec_gap_c": gap, "roi_pct": roi,
            "worst_case_profit_c": wc, "best_case_profit_c": bc,
            "child_display_c": child_c, "parent_display_c": parent_c,
            "spread_over_child": soc, "spread_over_parent": sop}


def test_risk_budget_geometry_from_payoff_fields():
    assert vm._geometry({"worst_case_profit_c": -3, "best_case_profit_c": 97}) == (3, 97, 97 / 3)
    assert vm._geometry({"worst_case_profit_c": 0, "best_case_profit_c": 5}) == (0, 5, float("inf"))
    assert vm._geometry({"worst_case_profit_c": None, "best_case_profit_c": 5}) is None


def test_spread_upside_orders_by_ratio_then_upside_then_loss():
    rows = [_o("low", "risk_budget", gap=-2, wc=-4, bc=8),   # ratio 2.0
            _o("hi", "risk_budget", gap=-2, wc=-2, bc=8),    # ratio 4.0
            _o("inf", "risk_budget", gap=-2, wc=0, bc=1)]    # ratio +inf -> top
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_upside")] == ["inf", "hi", "low"]


def test_spread_upside_falls_back_to_edge_for_non_risk_budget():
    rows = [_o("a", "actionable", gap=2), _o("b", "actionable", gap=9)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_upside")] == ["b", "a"]


def test_unknown_risk_budget_geometry_sorts_last():
    rows = [_o("known", "risk_budget", gap=-2, wc=-2, bc=8), _o("missing", "risk_budget", gap=-1)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_upside")] == ["known", "missing"]
    rows2 = [_o("hasinputs", "risk_budget", gap=-2, roi=5.0, wc=-2, bc=8), _o("none", "risk_budget")]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows2, "blended")][-1] == "none"


def test_spread_ratio_ranks_higher_probability_outright_first():
    # spread/outright is scale-invariant: 3/2 and 30/20 both have spread_over_child 0.5. The rank mode is
    # probability-LED, so the 30/20 pair (deeper outright 20) must rank ABOVE the 3/2 pair (deeper 2).
    rows = [_o("longshot", "risk_budget", child_c=2, parent_c=3, soc=0.5, sop=1 / 3),
            _o("meaningful", "risk_budget", child_c=20, parent_c=30, soc=0.5, sop=10 / 30)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_ratio")] == ["meaningful", "longshot"]


def test_spread_ratio_breaks_ties_by_lower_spread_over_child():
    # Equal deeper outright -> the lower display spread/outright (relative risk) wins.
    rows = [_o("wide", "risk_budget", child_c=20, parent_c=30, soc=0.5, sop=10 / 30),
            _o("tight", "risk_budget", child_c=20, parent_c=24, soc=0.2, sop=4 / 24)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_ratio")] == ["tight", "wide"]


def test_spread_ratio_falls_back_to_edge_for_non_risk_budget():
    rows = [_o("a", "actionable", gap=2), _o("b", "actionable", gap=9)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_ratio")] == ["b", "a"]


def test_spread_ratio_unknown_outright_sorts_last():
    # An older snapshot lacking child_display_c (or a zero/No-quote outright) sorts after rows that have it.
    rows = [_o("has", "risk_budget", child_c=10, parent_c=15, soc=0.5, sop=1 / 3),
            _o("missing", "risk_budget"),
            _o("zero", "risk_budget", child_c=0, parent_c=0)]
    ordered = [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_ratio")]
    assert ordered[0] == "has" and set(ordered[1:]) == {"missing", "zero"}


def test_blended_uses_edge_roi_geometry_no_probability():
    rows = [_o("x", "risk_budget", gap=-2, roi=4.0, wc=-2, bc=8),
            _o("y", "risk_budget", gap=-1, roi=8.0, wc=-4, bc=2)]
    ordered = vm.rank_opps(rows, "blended")
    assert {o["opportunity_id"] for o in ordered} == {"x", "y"}
    assert all("p_bonus" not in o and "expected_profit_c" not in o for o in ordered)   # no probability fields


def test_blended_ranks_relative_above_absolute():
    rows = [_o("smallhighroi", "actionable", gap=2, roi=30.0), _o("biglowroi", "actionable", gap=9, roi=5.0)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "blended")][0] == "smallhighroi"   # ROI tilt
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "edge")][0] == "biglowroi"          # pure absolute


def test_blended_normalizes_within_bucket():
    a = [_o("a1", "actionable", gap=2, roi=30.0), _o("a2", "actionable", gap=9, roi=5.0)]
    alone = [o["opportunity_id"] for o in vm.rank_opps(a, "blended") if o["bucket"] == "actionable"]
    b = a + [_o("r", "risk_budget", gap=100, roi=999.0, wc=-1, bc=99)]   # extreme row in ANOTHER bucket
    withother = [o["opportunity_id"] for o in vm.rank_opps(b, "blended") if o["bucket"] == "actionable"]
    assert alone == withother                                            # other bucket didn't reorder this one


def test_mode_switch_no_rescan():
    rows = [_o("a", "actionable", gap=2, roi=30.0), _o("b", "actionable", gap=9, roi=5.0)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "edge")] == ["b", "a"]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "blended")] == ["a", "b"]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_ratio")] == ["b", "a"]  # non-risk -> edge
    assert [o["opportunity_id"] for o in rows] == ["a", "b"]             # pure: input list not mutated


# --- change signal (#3) ------------------------------------------------------------------------------
def test_classify_changes_new_returned_up_down():
    prev = {"a": {"exec_gap_c": 5}, "b": {"exec_gap_c": 10}}
    cur = {"a": {"exec_gap_c": 7}, "b": {"exec_gap_c": 8}, "c": {"exec_gap_c": 3}, "d": {"exec_gap_c": 1}}
    ever = {"a", "b", "d"}        # d seen before but absent in prev -> returned; c never seen -> new
    assert vm.classify_changes(prev, cur, ever) == {"a": "up", "b": "down", "c": "new", "d": "returned"}
    # unchanged value, or a missing metric on either side -> "" (no phantom delta)
    assert vm.classify_changes({"a": {"exec_gap_c": 5}}, {"a": {"exec_gap_c": 5}}, {"a"}) == {"a": ""}
    assert vm.classify_changes({"a": {}}, {"a": {"exec_gap_c": 5}}, {"a"}) == {"a": ""}


# --- "most volatile now" (#12b) ----------------------------------------------------------------------
def test_volatility_leader_max_mid_delta_two_sided():
    frames = [
        {"fetched_ts": 0, "rows": [
            {"market_ticker": "X", "player": "P", "contract": "Beat", "yes_bid_c": 40, "yes_ask_c": 42},
            {"market_ticker": "Y", "yes_bid_c": 10, "yes_ask_c": 12}]},
        {"fetched_ts": 120, "rows": [
            {"market_ticker": "X", "player": "P", "contract": "Beat", "yes_bid_c": 58, "yes_ask_c": 60},  # 41->59 = 18
            {"market_ticker": "Y", "yes_bid_c": 11, "yes_ask_c": 13}]},                                   # 11->12 = 1
    ]
    msg = vm.volatility_leader(frames)
    assert msg and "moved 18¢" in msg and "2 obs" in msg and "Beat" in msg     # X is the most volatile
    assert "unavailable" in vm.volatility_leader([frames[0]])                   # <2 frames -> truthful note
    flat = [{"fetched_ts": 0, "rows": [{"market_ticker": "Z", "yes_bid_c": 0, "yes_ask_c": 100}]},
            {"fetched_ts": 60, "rows": [{"market_ticker": "Z", "yes_bid_c": 0, "yes_ask_c": 100}]}]
    assert "unavailable" in vm.volatility_leader(flat)                          # empty 0/100 books -> no mid


# --- participant detail builders (PR 24) — pure over a single participant's contract rows ----------
import consistency  # noqa: E402  — used by the payoff-chart test


def _contract(node, kind, *, pct=None, bid=None, ask=None, quote="OK", rank=0, contract="C",
              category="Cat", stage="", opp="", vol=10, status="active", url="u", series="KXATPADVANCE"):
    """A minimal build_contracts-shaped row for one ladder node (tennis fixture; no series → TENNIS)."""
    return {"ladder_node": node, "kind": kind, "player_key": "p1", "series": series,
            "display_pct": pct, "display_c": None if pct is None else int(round(pct)),
            "yes_bid_pct": bid, "yes_ask_pct": ask, "quote_quality": quote, "stage_rank": rank,
            "contract": contract, "category": category, "stage": stage, "opponent": opp,
            "volume": vol, "status": status, "kalshi_url": url}


def _tennis_prows():
    # Reach Semifinal via a match row (match-implied), Reach Final via advance, Win Tournament via winner.
    return [
        _contract("Reach Semifinal", "match", pct=60, bid=58, ask=62, quote="Tight", rank=1,
                  contract="SF", series="KXATPMATCH"),
        _contract("Reach Final", "advance", pct=40, bid=38, ask=42, quote="OK", rank=2, contract="Final"),
        _contract("Win Tournament", "winner", pct=50, bid=48, ask=52, quote="Wide", rank=3,
                  contract="Win", series="KXFOMEN"),  # 50 > 40 → inverted vs Reach Final
    ]


def test_detail_chain_orders_nodes_and_labels_source():
    chain = vm.detail_chain(_tennis_prows(), "tennis")
    assert [r["layer"] for r in chain] == ["Reach Semifinal", "Reach Final", "Win Tournament"]
    assert [r["source"] for r in chain] == ["match-implied", "advance/winner", "advance/winner"]
    assert [r["display_pct"] for r in chain] == [60, 40, 50]


def test_detail_chain_marks_missing_layers():
    chain = vm.detail_chain([_contract("Win Tournament", "winner", pct=30, series="KXFOMEN")], "tennis")
    by = {r["layer"]: r for r in chain}
    assert by["Reach Final"]["source"] == "— missing —" and by["Reach Final"]["display_pct"] is None
    assert by["Win Tournament"]["display_pct"] == 30


def test_detail_chain_empty_for_unknown_sport():
    assert vm.detail_chain(_tennis_prows(), "unknown") == []


def test_detail_spreads_and_expected_and_contracts():
    prows = _tennis_prows()
    spreads = vm.detail_spreads(prows)
    pair = {(s["from_layer"], s["to_layer"]): s for s in spreads}
    assert pair[("Reach Semifinal", "Reach Final")]["spread_pct"] == 20.0
    rf_win = pair[("Reach Final", "Win Tournament")]
    assert rf_win["spread_pct"] == -10.0 and rf_win["inverted"] is True

    expected = vm.detail_expected(prows)
    assert {e["layer"]: e["found"] for e in expected} == {
        "Reach Semifinal": True, "Reach Final": True, "Win Tournament": True}

    contracts = vm.detail_contracts(prows)
    assert [c["contract"] for c in contracts] == ["SF", "Final", "Win"]   # sorted by stage_rank


def test_relationship_explanation_branches_and_safe_fallback():
    assert "Containment ladder" in vm.relationship_explanation({"relationship_type": "containment"})
    assert "Dutch book" in vm.relationship_explanation({"source": "dutch_book"})
    assert "Synthetic bundle" in vm.relationship_explanation({"relationship_type": "synthetic_bundle"})
    assert "equivalence" in vm.relationship_explanation(
        {"relationship_type": "containment", "rule_flag": "RULE_CHECK_REQUIRED"}).lower()
    # Unknown / future relationship type must never raise — safe fallback.
    assert "weird_future" in vm.relationship_explanation({"relationship_type": "weird_future"})
    assert vm.relationship_explanation({}) == "Relationship: unknown — see the legs above."


def test_ladder_chart_option_none_for_empty_dict_for_real_chain():
    assert vm.ladder_chart_option([]) is None
    opt = vm.ladder_chart_option(vm.detail_chain(_tennis_prows(), "tennis"))
    assert opt is not None and opt["series"][0]["type"] == "bar"
    # The Win Tournament bar (50 > Reach Final 40) is flagged inverted → red.
    colors = [d["itemStyle"]["color"] for d in opt["series"][0]["data"]]
    assert "#c62828" in colors


def test_payoff_chart_option_none_for_none_dict_for_real_payoff():
    assert vm.payoff_chart_option(None) is None
    check = {"status": "EXECUTABLE_VIOLATION", "action_1_side": "buy_yes", "action_2_side": "buy_no",
             "action_1_price_c": 40, "action_2_price_c": 55,
             "parent_node": "Reach Final", "child_node": "Win Tournament"}
    pay = consistency.scenario_payoffs(check, 10)
    opt = vm.payoff_chart_option(pay)
    assert opt is not None and opt["series"][0]["markLine"]["data"][0]["yAxis"] == 95   # cost line at 95¢


# --- diagnostics / debug display builders (PR 25b) ------------------------------------
def test_diagnostics_rows_projection_nan_safe():
    rows = vm.diagnostics_rows([
        {"player": "Alcaraz", "chain": "Final⊇Win", "tournament": "FO", "status": "EXECUTABLE_VIOLATION",
         "status_group": "Broken", "rule_flag": "", "executable_gap": 3, "display_gap": None,
         "reason": "cross"},
    ])
    r = rows[0]
    assert r["player"] == "Alcaraz" and r["status_group"] == "Broken" and r["executable_gap"] == 3
    assert r["display_gap"] is None
    assert vm.diagnostics_rows(None) == []


def test_non_laddered_rows_filters_and_sorts():
    contracts = [
        {"contract": "Ladder", "ladder_eligible": True, "market_family": "advance"},
        {"contract": "GameA", "ladder_eligible": False, "market_family": "game", "volume": 5},
        {"contract": "GameB", "ladder_eligible": False, "market_family": "game", "volume": 50},
        {"contract": "Prop", "ladder_eligible": False, "market_family": "props", "volume": 1},
    ]
    out = vm.non_laddered_rows(contracts)
    assert [r["contract"] for r in out] == ["GameB", "GameA", "Prop"]   # family asc, volume desc
    assert all(not c.get("contract") == "Ladder" for c in out)         # eligible row excluded


def test_raw_fields_rows_and_passthroughs():
    prows = [{"series": "KXATPADVANCE", "event_ticker": "EV", "tournament": "FO",
              "tournament_source": "competition", "kind": "advance", "player_key": "p1",
              "mapping_confidence": "high", "raw_yes_bid": "0.40", "raw_yes_ask": "0.42",
              "market_ticker": "T-1", "kalshi_url": "u"}]
    rf = vm.raw_fields_rows(prows)
    assert rf[0]["tournament_source"] == "competition" and rf[0]["raw_yes_bid"] == "0.40"
    assert isinstance(vm.link_audit_rows(prows), list)                 # delegates to data.link_audit
    assert isinstance(vm.duplicate_rows(prows), list)                  # delegates to consistency


def test_sum_row_maxima_only_actionable_nan_safe():
    opps = [
        {"bucket": "actionable", "exec_max_profit_dollars": 7.5},
        {"bucket": "actionable", "exec_max_profit_dollars": 2.5},
        {"bucket": "blocked", "exec_max_profit_dollars": 100.0},      # not actionable → excluded
        {"bucket": "actionable", "exec_max_profit_dollars": None},    # NaN-safe → skipped
    ]
    assert vm.sum_row_maxima(opps) == 10.0
    assert vm.sum_row_maxima(None) == 0.0


# --- truthful empty states (PR 26a) ---------------------------------------------------
def test_empty_state_no_scan_and_scanning():
    assert vm.empty_state(cov=None, total_opps=0, shown_opps=0) == \
        "No scan yet — press “Refresh snapshot”."
    assert vm.empty_state(cov={"fetched_at": None}, total_opps=0, shown_opps=0,
                          scan_status={"status": "in_progress"}) == "Scanning… results will appear here."


def test_empty_state_no_opportunities_vs_scan_failed():
    cov = {"fetched_at": 1000}
    assert vm.empty_state(cov=cov, total_opps=0, shown_opps=0) == \
        "Scan complete — no opportunities right now (between rounds, this is normal)."
    failed = vm.empty_state(cov=cov, total_opps=0, shown_opps=0,
                            scan_status={"status": "error", "last_result": {"error": "boom"}})
    assert "Last scan failed: boom" in failed


def test_empty_state_filter_hid_all_and_has_content():
    cov = {"fetched_at": 1000}
    assert vm.empty_state(cov=cov, total_opps=7, shown_opps=0) == \
        "All 7 opportunities are hidden by the current filters — clear filters to see them."
    # Content present → no message at all.
    assert vm.empty_state(cov=cov, total_opps=7, shown_opps=3) is None
