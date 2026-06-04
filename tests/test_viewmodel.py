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
    assert "1493 contracts scanned · 1098 checks tested" in s and "48 Kalshi requests" in s


def test_scope_banner_honest_when_no_scan_or_no_meta():
    assert vm.scope_banner({"fetched_at": None}, "UTC").startswith("No scan yet")
    s = vm.scope_banner({"meta_present": False, "fetched_at": "2026-06-04 12:00:00 UTC", "opportunities": 0}, "UTC")
    assert "no coverage meta" in s


# --- URL state round-trip + graceful reset --------------------------------------------
def test_url_state_round_trip():
    state = {"sports": ["tennis", "nba"], "tournaments": ["French Open"], "participant": "Alc",
             "min_size": 50.0, "active_only": True}
    q = vm.query_from_state(state)
    assert q == {"sport": "tennis,nba", "tournament": "French Open", "participant": "Alc",
                 "min_size": "50.0", "active": "1"}
    back = vm.state_from_query(q)   # no options -> accept all
    assert back["sports"] == ["tennis", "nba"] and back["tournaments"] == ["French Open"]
    assert back["participant"] == "Alc" and back["min_size"] == 50.0 and back["active_only"] is True


def test_url_state_gracefully_drops_unknown_sport_and_tournament():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"]}
    q = {"sport": "tennis,golf", "tournament": "Wimbledon", "participant": "x"}
    st = vm.state_from_query(q, options=options)
    assert st["sports"] == ["tennis"]            # golf isn't in the snapshot -> dropped, not errored
    assert "tournaments" not in st               # Wimbledon absent -> the whole (now-empty) key omitted
    assert st["participant"] == "x"              # participant is free text -> kept


def test_active_filter_chips_labels():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"]}
    chips = vm.active_filter_chips({"sports": ["tennis"], "participant": "Alc", "min_size": 50.0,
                                    "active_only": True}, options)
    assert "sport: Tennis" in chips and "participant: “Alc”" in chips
    assert "min size ≥ 50" in chips and "active only" in chips
    assert vm.active_filter_chips({}) == []


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
