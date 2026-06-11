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


# --- cascaded_options (cascading filter lists) ----------------------------------------
def _copp(oid, *, sport, tournament, pk, label):
    return {"opportunity_id": oid, "sport": sport, "sport_label": sport.title(),
            "tournament": tournament, "participant_keys": [pk], "participant_labels": [label]}


def test_cascaded_options_sport_is_full_tournaments_narrow_by_sport():
    opps = [_copp("a", sport="tennis", tournament="French Open", pk="k1", label="Alcaraz"),
            _copp("b", sport="golf", tournament="The Masters", pk="k2", label="Scheffler"),
            _copp("c", sport="nba", tournament="NBA Finals", pk="k3", label="Celtics")]
    out = vm.cascaded_options(opps, sports=["tennis", "golf"])
    assert set(out["sports"]) == {"tennis", "golf", "nba"}        # sport list is never narrowed
    assert out["tournaments"] == ["French Open", "The Masters"]   # only the selected sports' tournaments
    assert {p["value"] for p in out["participants"]} == {"k1", "k2"}   # and their participants


def test_cascaded_options_participants_narrow_by_sport_and_tournament():
    opps = [_copp("a", sport="tennis", tournament="French Open", pk="k1", label="Alcaraz"),
            _copp("b", sport="tennis", tournament="Wimbledon", pk="k2", label="Sinner")]
    out = vm.cascaded_options(opps, sports=["tennis"], tournaments=["French Open"])
    assert out["tournaments"] == ["French Open", "Wimbledon"]     # both in-scope for tennis
    assert {p["value"] for p in out["participants"]} == {"k1"}    # only the French Open player


def test_cascaded_options_empty_selection_is_full():
    opps = [_copp("a", sport="tennis", tournament="French Open", pk="k1", label="Alcaraz"),
            _copp("b", sport="golf", tournament="The Masters", pk="k2", label="Scheffler")]
    out = vm.cascaded_options(opps)
    assert set(out["sports"]) == {"tennis", "golf"}
    assert out["tournaments"] == ["French Open", "The Masters"]
    assert {p["value"] for p in out["participants"]} == {"k1", "k2"}


def test_filter_opps_participant_or_match_by_key():
    opps = [{"participant_keys": ["ka", "kb"], "name": "A vs B"},
            {"participant_keys": ["kc"], "name": "C ladder"}]
    assert {o["name"] for o in vm.filter_opps(opps, participant=["kb"])} == {"A vs B"}     # B side reachable
    assert {o["name"] for o in vm.filter_opps(opps, participant=["ka", "kc"])} == {"A vs B", "C ladder"}  # OR
    assert len(vm.filter_opps(opps, participant=[])) == 2                                  # empty = no filter
    assert {o["name"] for o in vm.filter_opps(opps, participant="ladder")} == {"C ladder"}  # legacy substring


# --- ranking modes (#1/#9) — payoff geometry, no probability ----------------------------------------
def _o(oid, bucket="actionable", gap=None, roi=None, wc=None, bc=None,
       child_c=None, parent_c=None, soc=None, sop=None, ds=None):
    return {"opportunity_id": oid, "bucket": bucket, "exec_gap_c": gap, "roi_pct": roi,
            "worst_case_profit_c": wc, "best_case_profit_c": bc,
            "child_display_c": child_c, "parent_display_c": parent_c,
            "spread_over_child": soc, "spread_over_parent": sop, "display_spread_c": ds}


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


# --- implied EV (PR C) — chance-weighted ranking aid; cents-only; gross, market-implied prob ----------
def test_implied_ev_c_is_cents_only_no_unit_mixup():
    # band 12¢ (=12% implied chance), overpay 10¢ (max loss = -wc) -> EV = +2¢. NOT a probability-mixed
    # value like 0.12*88 - 0.88*10 (which would be ~1.8) and NOT 1190 etc.
    assert vm._implied_ev_c({"display_spread_c": 12, "worst_case_profit_c": -10}) == 2
    # missing either input -> None (never silently 0)
    assert vm._implied_ev_c({"display_spread_c": None, "worst_case_profit_c": -10}) is None
    assert vm._implied_ev_c({"display_spread_c": 12, "worst_case_profit_c": None}) is None


def test_implied_ev_orders_chance_weighted_and_flips_vs_ratio():
    # "longshot": band 1% / overpay 2¢ -> EV = -1; upside:risk = 98/2 = 49.
    # "likely":   band 32% / overpay 8¢ -> EV = +24; upside:risk = 88/8 = 11.
    rows = [_o("longshot", "risk_budget", wc=-2, bc=98, ds=1),
            _o("likely", "risk_budget", wc=-8, bc=88, ds=32)]
    # Implied EV is chance-weighted: the far-likelier lower-ratio bet ranks first...
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "implied_ev")] == ["likely", "longshot"]
    # ...the exact opposite of pure upside:risk geometry, which leads with the 49x longshot.
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "spread_upside")] == ["longshot", "likely"]


def test_implied_ev_missing_inputs_sort_last_not_zero():
    rows = [_o("scored", "risk_budget", wc=-2, bc=98, ds=10),     # EV = +8
            _o("noband", "risk_budget", wc=-2, bc=98),            # no display_spread -> EV None
            _o("noloss", "risk_budget", ds=10)]                   # no worst_case -> EV None
    ordered = [o["opportunity_id"] for o in vm.rank_opps(rows, "implied_ev")]
    assert ordered[0] == "scored" and set(ordered[1:]) == {"noband", "noloss"}


def test_implied_ev_negative_band_not_attractive():
    # A negative band (child priced ABOVE parent — a ladder inversion) yields a worse EV than a normal
    # positive-band bet, so it never floats to the top of the implied-EV ranking.
    rows = [_o("inverted", "risk_budget", wc=-2, bc=98, ds=-5),   # EV = -7
            _o("normal", "risk_budget", wc=-2, bc=98, ds=10)]     # EV = +8
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "implied_ev")] == ["normal", "inverted"]


def test_implied_ev_falls_back_to_edge_for_non_risk_budget():
    rows = [_o("a", "actionable", gap=2), _o("b", "actionable", gap=9)]
    assert [o["opportunity_id"] for o in vm.rank_opps(rows, "implied_ev")] == ["b", "a"]


def test_risk_budget_row_exposes_implied_ev_field():
    row = vm.risk_budget_row({"opportunity_id": "x", "bucket": "risk_budget",
                              "display_spread_c": 12, "worst_case_profit_c": -10,
                              "best_case_profit_c": 90}, set())
    assert row["ev"] == 2
    # missing display gap -> blank EV, never 0
    row2 = vm.risk_budget_row({"opportunity_id": "y", "bucket": "risk_budget",
                               "worst_case_profit_c": -10}, set())
    assert row2["ev"] is None


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


# --- considered_inventory (debug "what the app is considering" coverage) ---------------
def _crow(*, series, tournament, player, player_key, kind, category, market_ticker,
          ladder_eligible=False, tournament_source="competition", mapping_confidence="high"):
    return {"series": series, "tournament": tournament, "player": player, "player_key": player_key,
            "kind": kind, "category": category, "market_ticker": market_ticker,
            "ladder_eligible": ladder_eligible, "tournament_source": tournament_source,
            "mapping_confidence": mapping_confidence}


def test_considered_inventory_distinct_counts_and_dedup_across_sports():
    rows = [
        _crow(series="KXATPMATCH", tournament="French Open", player="Alcaraz", player_key="k1",
              kind="match", category="Match result", market_ticker="T-1"),
        _crow(series="KXATPMATCH", tournament="French Open", player="Alcaraz", player_key="k1",
              kind="match", category="Match result", market_ticker="T-2"),    # same player, 2nd contract
        _crow(series="KXATPADVANCE", tournament="French Open", player="Sinner", player_key="k2",
              kind="advance", category="Stage advancement", market_ticker="T-3", ladder_eligible=True),
        _crow(series="KXMLBGAME", tournament="MLB", player="Cubs", player_key="m1",
              kind="game", category="Game", market_ticker="T-4"),
    ]
    inv = vm.considered_inventory(rows)
    # sport derived from series (rows carry no sport tag); per-sport at-a-glance
    tennis = next(s for s in inv["sports"] if s["sport"] == "Tennis")
    assert (tennis["tournaments"], tennis["participants"], tennis["contracts"], tennis["kinds"]) == (1, 2, 3, 2)
    mlb = next(s for s in inv["sports"] if s["sport"] == "MLB")
    assert mlb["contracts"] == 1 and mlb["participants"] == 1
    # participant deduped across its two markets -> ONE row, 2 contracts
    alc = next(p for p in inv["participants"] if p["participant"] == "Alcaraz")
    assert alc["contracts"] == 2 and alc["sport"] == "Tennis" and alc["tournament"] == "French Open"
    assert {p["participant"] for p in inv["participants"]} == {"Alcaraz", "Sinner", "Cubs"}
    # tournament row joins DISTINCT kinds present (no first-row-wins)
    fo = next(t for t in inv["tournaments"] if t["tournament"] == "French Open")
    assert fo["participants"] == 2 and fo["contracts"] == 3
    assert "advance" in fo["kinds"] and "match" in fo["kinds"]
    # kind grouped by (sport, kind, category); advance is ladder-eligible
    adv = next(k for k in inv["kinds"] if k["kind"] == "advance")
    assert adv["contracts"] == 1 and adv["laddered"] == 1 and adv["category"] == "Stage advancement"


def test_considered_inventory_blank_player_key_does_not_collapse():
    rows = [
        _crow(series="KXATPMATCH", tournament="T", player="A", player_key="", market_ticker="T-1",
              kind="match", category="Match result"),
        _crow(series="KXATPMATCH", tournament="T", player="B", player_key="", market_ticker="T-2",
              kind="match", category="Match result"),
    ]
    inv = vm.considered_inventory(rows)
    # blank player_key falls back to the distinct market_ticker -> two participants, not one phantom
    assert len(inv["participants"]) == 2


def test_considered_inventory_keeps_unknown_sport_and_empty_is_empty():
    assert vm.considered_inventory([]) == {"sports": [], "tournaments": [], "participants": [], "kinds": []}
    rows = [_crow(series="ZZZ_NOT_A_SPORT", tournament="T", player="X", player_key="x1",
                  kind="other", category="Other", market_ticker="T-1")]
    inv = vm.considered_inventory(rows)
    assert len(inv["sports"]) == 1 and inv["sports"][0]["contracts"] == 1   # unknown sport kept (honest)


# --- exact-order top-two bundle (#4 redux): two-tier UI, comparator-not-leg, ordering ----------------
def _eo_opp(oid="eo1", *, status="EXACT_ORDER_DIAGNOSTIC", setup_type="exact_order_top2_bundle",
            premium=-70, synth=120, q=50, name="Alpha", tradable="Diagnostic only", legs=None):
    return {"opportunity_id": oid, "bucket": "qualifier_setup", "source": "exact_order",
            "sport": "soccer", "sport_label": "Soccer (World Cup)", "name": name, "tournament": "2026 WC",
            "detail": "Group A", "status": status, "setup_type": setup_type, "tradable_now": tradable,
            "relationship_type": setup_type, "qualifier_yes_ask_c": q, "synthetic_top_two_cost_c": synth,
            "qualifier_vs_top2_premium_c": premium, "top2_net_if_top2_c": 100 - synth,
            "top2_loss_if_not_top2_c": synth, "top2_max_units": 100, "worst_bundle_quote_quality": "OK",
            "wide_bundle_leg_count": 0, "comparator_quote_quality": "OK", "settlement_caveat": "best-third...",
            "legs": legs if legs is not None else
            [{"side": "buy_yes", "text": f"Buy YES — ord{i} @ 10¢", "ticker": f"T-{i}", "url": "u"}
             for i in range(12)]}


def test_explanation_lines_exact_order_has_no_leg13_or_none_cost():
    lines = vm.explanation_lines(_eo_opp(premium=-70))
    blob = "\n".join(lines)
    assert "Leg 13" not in blob
    assert "Cost: None" not in blob and "Gross edge: None" not in blob
    assert any(ln.startswith("Trade:") for ln in lines)
    assert any(ln.startswith("Comparator:") for ln in lines)
    assert "If top two:" in blob and "If not top two:" in blob
    assert "more expensive" in blob                      # premium negative → sign-aware wording
    assert any("best-third" in ln.lower() for ln in lines)


def test_explanation_lines_speculative_says_cheaper():
    lines = vm.explanation_lines(_eo_opp(status="SPECULATIVE_TOP2_RELATIVE_VALUE",
                                         setup_type="exact_order_top2_relative_value",
                                         premium=10, synth=84, q=94, tradable="Review execution"))
    blob = "\n".join(lines)
    assert "cheaper" in blob and "Review execution" in blob


def test_explanation_lines_filters_legacy_comparator_leg():
    legacy = [{"side": "buy_yes", "text": f"Buy YES — ord{i} @ 10¢", "ticker": f"T-{i}"} for i in range(12)]
    legacy.append({"side": "buy_yes", "contract": "Alpha qualify", "text": "Buy YES — Alpha qualify @ 50¢"})
    lines = vm.explanation_lines(_eo_opp(legs=legacy))
    assert "Leg 13" not in "\n".join(lines)               # the stale comparator leg is dropped
    assert "qualify" not in " ".join(ln for ln in lines if ln.startswith("Leg "))


def test_game_support_row_not_treated_as_exact_order():
    gs = {"opportunity_id": "gs1", "bucket": "qualifier_setup", "source": "game_support",
          "sport_label": "Soccer", "name": "Japan", "detail": "Group X", "status": "GAME_SUPPORT_SIGNAL",
          "setup_type": "game_support_signal", "tradable_now": "Diagnostic only",
          "relationship_type": "game_support_signal", "ask_support_score_total_c": 470,
          "settlement_caveat": "not expected points", "cost_c": None}
    blob = "\n".join(vm.explanation_lines(gs))
    assert "finishes top two" not in blob and "12 exact-order" not in blob


def test_leg_rows_drops_legacy_comparator_leg():
    legacy = [{"side": "buy_yes", "text": f"Buy YES — ord{i} @ 10¢", "ticker": f"T-{i}",
               "price_c": 10, "size": 100} for i in range(12)]
    legacy.append({"side": "buy_yes", "contract": "Alpha qualify", "text": "Buy YES — Alpha qualify @ 50¢",
                   "price_c": 50, "size": 100, "ticker": "Q-1"})
    rows = vm.leg_rows(_eo_opp(legs=legacy))
    assert len(rows) == 12 and all("qualify" not in r["market"].lower() for r in rows)


def test_severity_badge_for_review_execution():
    badges = vm.severity_badges(_eo_opp(status="SPECULATIVE_TOP2_RELATIVE_VALUE", tradable="Review execution"))
    assert any(b["severity"] == "review_required" for b in badges)


def test_relationship_explanation_resolves_both_tiers_and_legacy():
    for rel in ("exact_order_top2_bundle", "exact_order_top2_relative_value", "exact_order_top2_proxy"):
        txt = vm.relationship_explanation({"relationship_type": rel}).lower()
        assert "not arbitrage" in txt and "comparator" in txt


def test_order_qualifier_rows_speculative_first():
    diag = _eo_opp("d", premium=-70)
    spec = _eo_opp("s", status="SPECULATIVE_TOP2_RELATIVE_VALUE",
                   setup_type="exact_order_top2_relative_value", premium=10, synth=84, q=94)
    gs = {"opportunity_id": "g", "bucket": "qualifier_setup", "source": "game_support",
          "status": "GAME_SUPPORT_SIGNAL", "name": "Z"}
    ordered = [o["opportunity_id"] for o in vm.order_qualifier_rows([gs, diag, spec])]
    assert ordered[0] == "s" and ordered.index("d") < ordered.index("g")


# --- PR M: breakeven decomposition + signal class (show both; never a negative "chance") --------------
def test_breakeven_and_gap_vs_breakeven_decomposition():
    o = _o("x", "risk_budget", wc=-5, bc=95, ds=12)
    assert vm._breakeven_pct(o) == 5.0                       # max_loss/(max_loss+max_profit)*100 = 5/100*100
    assert vm._gap_vs_breakeven_pp(o) == 7.0                 # market gap 12 − breakeven 5
    assert vm._gap_vs_breakeven_pp(o) == vm._implied_ev_c(o) # equals Implied EV for the canonical 2-leg spread
    # missing inputs → None, never a fake 0
    assert vm._breakeven_pct(_o("y", "risk_budget", ds=12)) is None
    assert vm._gap_vs_breakeven_pp(_o("z", "risk_budget", wc=-5, bc=95)) is None   # no display gap


def test_signal_class_is_descriptive_and_flags_inverted():
    assert vm._signal_class(_o("d", "risk_budget")) == "Data quality"                       # no display gap
    assert vm._signal_class(_o("i", "risk_budget", wc=-5, bc=95, ds=-3)) == "Inverted / diagnostic"
    assert vm._signal_class(_o("c", "risk_budget", wc=-5, bc=95, ds=12)) == "Candidate"     # gap−be = +7
    assert vm._signal_class(_o("b", "risk_budget", wc=-5, bc=95, ds=5)) == "Breakeven"      # gap−be = 0
    assert vm._signal_class(_o("n", "risk_budget", wc=-5, bc=95, ds=3)) == "Negative proxy" # gap−be = −2


def test_risk_budget_row_exposes_decomposition_fields():
    row = vm.risk_budget_row({"opportunity_id": "x", "bucket": "risk_budget", "display_spread_c": 12,
                              "worst_case_profit_c": -5, "best_case_profit_c": 95}, set())
    assert row["breakeven"] == 5.0 and row["gap_vs_be"] == 7.0
    assert row["signal"] == "Candidate" and row["ev"] == 7      # ev == gap_vs_be for the canonical spread


def test_derived_indicators_from_chain_generalized():
    chain = [{"layer": "Top 20", "display_pct": 18.0}, {"layer": "Top 10", "display_pct": 9.0}]
    out = vm.derived_indicators(chain, "golf")
    labels = [i["label"] for i in out]
    assert "In contention (Top 20)" in labels                                  # broad-rung (PR G)
    assert any(i["label"] == "Make the cut" and i["value_pct"] == 18.0 for i in out)   # golf floor still present
    assert "P(Top 10 | Top 20)" in labels                                      # conditional ratio 9/18*100
    # generalized beyond golf — tennis now gets an in-contention indicator too
    assert any(i["label"] == "In contention (Reach Semifinal)"
               for i in vm.derived_indicators([{"layer": "Reach Semifinal", "display_pct": 60.0}], "tennis"))
    assert vm.derived_indicators(None, "golf") == []


# --- PR E: trader columns + $100 sizing + wins-if + speculative explainer ----------------------------
def test_wins_if_from_ladder_rungs():
    assert vm._wins_if({"parent_node": "Reach Final", "child_node": "Win Tournament"}) \
        == "Reach Final but not Win Tournament"
    assert vm._wins_if({"parent_node": "", "child_node": "Win Tournament"}) == ""   # blank when a rung missing


def test_sized_at_budget_caps_by_book_size():
    o = {"cost_c": 102, "exec_min_size": 50, "worst_case_profit_c": -2, "best_case_profit_c": 98}
    assert vm._sized_at_budget(o) == (50, 100, 4900)          # min(10000//102=98, 50)=50; loss 2*50, upside 98*50
    assert vm._sized_at_budget({**o, "exec_min_size": 1000})[0] == 98   # not capped when the book is deep
    assert vm._sized_at_budget({"cost_c": None, "worst_case_profit_c": -2, "best_case_profit_c": 98}) is None


def test_risk_budget_row_trader_columns():
    row = vm.risk_budget_row({"opportunity_id": "x", "bucket": "risk_budget", "cost_c": 102,
                              "exec_min_size": 50, "worst_case_profit_c": -2, "best_case_profit_c": 98,
                              "parent_node": "Reach Final", "child_node": "Win Tournament",
                              "comp_quote_quality": "OK", "resolution_mode": "calendar",
                              "display_spread_c": 12}, set())
    assert row["resolution"] == "Calendar"
    assert row["wins_if"] == "Reach Final but not Win Tournament"
    assert row["max_units"] == 50 and row["quote_health"] == "OK"
    assert row["units_100"] == 50 and row["loss_100"] == 1.0 and row["upside_100"] == 49.0


def test_speculative_explainer_only_for_risk_budget_and_conservative():
    assert vm.speculative_explainer({"bucket": "actionable"}) == []
    lines = vm.speculative_explainer({"bucket": "risk_budget", "worst_case_profit_c": -2,
                                      "best_case_profit_c": 98, "display_spread_c": 12,
                                      "parent_node": "Reach Final", "child_node": "Win Tournament"})
    labels = [lbl for lbl, _ in lines]
    assert "Can I lose money?" in labels and "Why ranked here" in labels
    assert any("doing nothing" in lbl for lbl in labels)
    blob = " ".join(t for _, t in lines).lower()
    for banned in ("riskless", "locked", "true arbitrage", "guaranteed"):
        assert banned not in blob


# --- PR F: peer-relative cheapness (same-sport, display-only badge) -----------------------------------
def _rb(oid, sport, band, overpay, soc=None):
    return {"opportunity_id": oid, "sport": sport, "bucket": "risk_budget",
            "display_spread_c": band, "worst_case_profit_c": -overpay, "spread_over_child": soc}


def test_flag_peer_cheapness_flags_same_sport_outlier():
    bets = [_rb("cheap", "golf", 10, 1, 0.1), _rb("g1", "golf", 10, 5, 0.5),
            _rb("g2", "golf", 11, 5, 0.5), _rb("g3", "golf", 9, 6, 0.6), _rb("g4", "golf", 10, 4, 0.4)]
    vm.flag_peer_cheapness(bets)
    cheap = next(b for b in bets if b["opportunity_id"] == "cheap")
    g1 = next(b for b in bets if b["opportunity_id"] == "g1")
    assert cheap["cheap_cost"] and cheap["cheap_ratio"]      # far below the peer median on both metrics
    assert not g1["cheap_cost"]                              # mid-pack -> not flagged


def test_flag_peer_cheapness_cross_sport_isolation():
    # a cheap golf bet whose only peers are tennis -> not enough SAME-SPORT peers -> never flagged
    bets = [_rb("g", "golf", 10, 1, 0.1)] + [_rb(f"t{i}", "tennis", 10, 5, 0.5) for i in range(4)]
    vm.flag_peer_cheapness(bets)
    assert not bets[0]["cheap_cost"] and not bets[0]["cheap_ratio"]


def test_flag_peer_cheapness_insufficient_peers_not_flagged():
    bets = [_rb("a", "golf", 10, 1, 0.1), _rb("b", "golf", 10, 5, 0.5)]   # 1 peer each (< min 4)
    vm.flag_peer_cheapness(bets)
    assert not any(b["cheap_cost"] for b in bets)


def test_peer_cheap_mad_zero_requires_strict_undercut():
    assert vm._peer_cheap(3, [5, 5, 5, 5], 1.5) is True      # strictly below a constant peer level
    assert vm._peer_cheap(5, [5, 5, 5, 5], 1.5) is False     # equal -> not cheap
    assert vm._peer_cheap(None, [5, 5, 5, 5], 1.5) is False  # None -> not cheap


def test_flag_peer_cheapness_missing_band_not_flagged():
    bets = [_rb("nb", "golf", None, 1, 0.1)] + [_rb(f"g{i}", "golf", 10, 5, 0.5) for i in range(4)]
    vm.flag_peer_cheapness(bets)
    assert not bets[0]["cheap_cost"]                         # no band -> skipped


def test_risk_budget_row_cheap_badge():
    assert vm.risk_budget_row({"opportunity_id": "x", "bucket": "risk_budget",
                               "cheap_cost": True, "cheap_ratio": False}, set())["cheap"] == "cost"
    assert vm.risk_budget_row({"opportunity_id": "y", "bucket": "risk_budget",
                               "cheap_cost": True, "cheap_ratio": True}, set())["cheap"] == "cost, ratio"


# --- stale-selection guard (UI trust fix 2): pure predicate ----------------------------
# The headless browser suite cannot click-select table rows (documented limit), so the clear/keep
# decision lives in this pure helper and is unit-tested here; the dashboard wiring is a manual check.
def test_selection_left_view_none_selection_never_clears():
    assert vm.selection_left_view(None, [_opp("a")]) is False
    assert vm.selection_left_view({}, [_opp("a")]) is False     # falsy dict == no selection


def test_selection_left_view_selected_still_present_keeps():
    view = [_opp("a"), _opp("b")]
    assert vm.selection_left_view(_opp("a"), view) is False


def test_selection_left_view_selected_absent_clears():
    assert vm.selection_left_view(_opp("gone"), [_opp("a"), _opp("b")]) is True
    assert vm.selection_left_view(_opp("gone"), []) is True     # empty view: any selection departed
    assert vm.selection_left_view(_opp("gone"), None) is True   # None-safe view


def test_selection_left_view_missing_id_keys_are_none_safe():
    # A selection lacking opportunity_id can't match a normal view -> treated as departed.
    assert vm.selection_left_view({"name": "x"}, [_opp("a")]) is True


# --- Phase 1 likelihood / comparability metrics (display-only) -----------------------------------------
def test_cond_success_pct_is_conditional_and_fails_closed():
    # spread_over_parent = 1 - child/parent = P(success | reached); shown as a %.
    assert vm._cond_success_pct({"spread_over_parent": 0.4}) == 40.0
    # fail closed: missing / <= 0 -> None (never 0.0), so an inverted ladder never reads as a chance.
    assert vm._cond_success_pct({"spread_over_parent": None}) is None
    assert vm._cond_success_pct({"spread_over_parent": 0}) is None
    assert vm._cond_success_pct({"spread_over_parent": -0.1}) is None


def test_cond_child_pct_is_complement_and_fails_closed():
    # P(child | parent) = child/parent, as a %. SF: 4/8 -> 50.0; Spain: 42/58 -> 72.4.
    assert vm._cond_child_pct({"parent_display_c": 8, "child_display_c": 4}) == 50.0
    assert vm._cond_child_pct({"parent_display_c": 58, "child_display_c": 42}) == 72.4
    # complementary: cond_child + cond_success ~= 100 on a CONSISTENT row (0.1 rounding tolerance), so a
    # later change to one helper but not the other is caught.
    o = {"parent_display_c": 58, "child_display_c": 42, "spread_over_parent": 1 - 42 / 58}
    assert abs(vm._cond_child_pct(o) + vm._cond_success_pct(o) - 100.0) <= 0.1
    # fail closed: missing leg, parent <= 0, or inverted (child > parent) -> None (never 0.0)
    assert vm._cond_child_pct({"parent_display_c": 8}) is None
    assert vm._cond_child_pct({"child_display_c": 4}) is None
    assert vm._cond_child_pct({"parent_display_c": 0, "child_display_c": 0}) is None
    assert vm._cond_child_pct({"parent_display_c": 4, "child_display_c": 8}) is None


def test_explanation_lines_conditional_for_containment_only():
    # Spain: parent (Reach QF) 58¢, child (Reach SF) 42¢ -> deeper 72.4%, success 27.6%, raw gap 16.0pp.
    spain = {"sport": "Soccer", "name": "Spain", "source": "containment",
             "detail": "Reach SF ≤ Reach QF", "tournament": "World Cup", "bucket": "risk_budget",
             "parent_display_c": 58, "child_display_c": 42}
    blob = "\n".join(vm.explanation_lines(spain))
    assert "Conditional (market-implied)" in blob
    assert "72.4%" in blob and "27.6%" in blob and "16pp" in blob   # 42/58, complement, raw gap 58−42
    # audit: NOT a future-price promise, and flags quote health
    assert "not a promise about the future traded price" in blob
    assert "wide / stale / one-sided books" in blob
    # gated off when the outrights are absent (dutch / synthetic rows) — no conditional line
    dutch = {"sport": "NFL", "name": "x", "source": "dutch_book", "detail": "", "tournament": "t"}
    assert "Conditional (market-implied)" not in "\n".join(vm.explanation_lines(dutch))


def test_firm_spread_c_is_parent_bid_minus_child_ask():
    assert vm._firm_spread_c({"parent_yes_bid_c": 48, "child_yes_ask_c": 22}) == 26
    # a firm gap CAN be negative (that's the signal) -> returned as-is, not clamped
    assert vm._firm_spread_c({"parent_yes_bid_c": 20, "child_yes_ask_c": 35}) == -15
    # missing either firm quote -> None
    assert vm._firm_spread_c({"parent_yes_bid_c": 48}) is None
    assert vm._firm_spread_c({"child_yes_ask_c": 22}) is None


def test_firm_success_pct_never_negative_only_positive_shown():
    assert vm._firm_success_pct({"parent_yes_bid_c": 50, "child_yes_ask_c": 30}) == 40.0   # 20/50
    # firm gap <= 0 -> None (a negative "chance" is nonsense, suppressed)
    assert vm._firm_success_pct({"parent_yes_bid_c": 30, "child_yes_ask_c": 40}) is None
    assert vm._firm_success_pct({"parent_yes_bid_c": 0, "child_yes_ask_c": 0}) is None


def test_optimistic_only_flags_midpoint_only_rows():
    # display positive but firm basis not -> Midpoint-only
    assert vm._optimistic_only({"display_spread_c": 12, "parent_yes_bid_c": 20, "child_yes_ask_c": 25}) is True
    # both bases positive -> not flagged
    assert vm._optimistic_only({"display_spread_c": 12, "parent_yes_bid_c": 48, "child_yes_ask_c": 22}) is False
    # firm basis missing -> can't claim a mismatch -> not flagged
    assert vm._optimistic_only({"display_spread_c": 12}) is False


def test_parent_over_maxloss():
    # parent's in-the-money probability (¢) ÷ MAX LOSS (cost − 100, the overpay); higher = better.
    assert vm._parent_over_maxloss({"cost_c": 107, "parent_display_c": 35}) == round(35 / 7, 2)   # 5.0
    # a likely-to-reach parent scores HIGHER than a deep-longshot parent at the same max loss
    live = vm._parent_over_maxloss({"cost_c": 102, "parent_display_c": 50})
    longshot = vm._parent_over_maxloss({"cost_c": 102, "parent_display_c": 2})
    assert live > longshot
    # fail closed: missing inputs, or max loss (cost − 100) <= 0 -> None
    assert vm._parent_over_maxloss({"parent_display_c": 35}) is None
    assert vm._parent_over_maxloss({"cost_c": 100, "parent_display_c": 35}) is None   # max loss 0
    assert vm._parent_over_maxloss({"cost_c": 95, "parent_display_c": 35}) is None    # max loss < 0


def test_risk_budget_row_exposes_phase1_likelihood_fields_and_flags():
    row = vm.risk_budget_row({
        "opportunity_id": "x", "bucket": "risk_budget",
        "display_spread_c": 12, "worst_case_profit_c": -10, "best_case_profit_c": 90,
        "spread_over_parent": 0.4, "parent_yes_bid_c": 20, "child_yes_ask_c": 25,
        "cost_c": 107, "parent_display_c": 35, "child_display_c": 30,
        "comp_quote_quality": "Very wide",
    }, set())
    assert row["cond_success"] == 40.0
    assert row["cond_child"] == round(30 / 35 * 100, 1)   # child 30 ÷ parent 35 = 85.7
    assert row["firm_gap"] == -5            # 20 - 25
    assert row["firm_pct"] is None          # not shown when gap <= 0
    assert row["midpoint_only"] is True     # display + but firm -
    assert row["parent_over_maxloss"] == round(35 / 7, 2)   # parent 35 ÷ max loss (107 − 100)
    labels = {f["label"] for f in row["flags"]}
    assert "Midpoint-only" in labels and "Wide basis" in labels


def test_risk_budget_row_old_snapshot_missing_new_fields_renders_blank():
    # An old snapshot row lacks every new key -> blank (None) cells, no flags, no crash.
    row = vm.risk_budget_row({"opportunity_id": "old", "bucket": "risk_budget",
                              "worst_case_profit_c": -10, "best_case_profit_c": 90}, set())
    assert row["cond_success"] is None
    assert row["cond_child"] is None
    assert row["firm_gap"] is None
    assert row["firm_pct"] is None
    assert row["midpoint_only"] is False
    assert row["parent_over_maxloss"] is None
    assert row["flags"] == []
