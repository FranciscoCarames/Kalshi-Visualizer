"""Tests for the terminal-feed adapter (`webui/feed.py`) — the read-only VIEW the Terminal Pro SPA reads.

Locks the PRIME INVARIANT: the feed is a faithful 1:1 VIEW of the engine's opportunities, never a second
engine. Three guards:
- **contract** — the documented `{meta, opps[]}` shape, the display-only derived fields, JSON-serializable;
- **parity** — same snapshot → same count + same id set + verbatim `bucket`/`status`/`tradable`, and
  `meta.totals` equals the per-bucket counts over the FULL snapshot;
- **isolation** — the adapter never mutates the engine rows and never re-derives the bucket.
"""
from __future__ import annotations

import copy
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

import api
import store
from webui import feed


def _opp(oid, *, bucket="actionable", status="OK", sport="tennis", **kw):
    base = {
        "opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": "dutch_book",
        "name": kw.get("name", "A vs B"), "detail": "underround", "tournament": "T",
        "action_1_text": "Buy YES", "action_2_text": "Buy NO",
        "exec_gap_c": kw.get("exec_gap_c", 5), "exec_min_size": 10, "exec_max_profit_dollars": 0.5,
        "roi_pct": 2.0, "cost_c": 98, "bucket": bucket, "status": status,
        "tradable_now": kw.get("tradable_now", "Yes"), "blocked_reason": kw.get("blocked_reason", ""),
        "market_status": "active", "rule_flag": kw.get("rule_flag", ""),
        "relationship_type": "dutch_book", "url": "u1", "url_2": "u2",
        "legs": kw.get("legs", [{"side": "buy_yes", "contract": "A", "price_c": 60, "size": 100,
                                 "ticker": "TA", "url": "ua"}]),
    }
    base.update(kw.get("extra", {}))
    return base


def _snapshot_with_legs(legs):
    """A one-opportunity snapshot whose single opp carries the given engine legs (for deep-link tests)."""
    return {"snapshot_id": 8, "fetched_at": "2026-06-03 12:00:00 UTC",
            "opportunities": [_opp("z", legs=legs)], "meta": {}}


def _snapshot():
    opps = [
        _opp("a", bucket="actionable"),
        _opp("b", bucket="blocked", tradable_now="No"),
        _opp("r", bucket="review_signal", status="EXECUTABLE_SYNTHETIC_BUNDLE",
             rule_flag="SETTLEMENT_CHECK_REQUIRED"),
        _opp("k", bucket="risk_budget", extra={"worst_case_profit_c": -4, "best_case_profit_c": 20,
             "parent_display_c": 30, "child_display_c": 18, "resolution_mode": "vertical",
             "spread_over_parent": 0.4,    # engine field = 1 − child/parent; drives the viewmodel cond_success
             "parent_yes_bid_c": 30, "child_yes_ask_c": 18}),
        _opp("n", bucket="no_structure", extra={"no_structure_scope": "championship"}),
        _opp("d", bucket="data_quality"),
    ]
    return {"snapshot_id": 7, "fetched_at": "2026-06-03 12:00:00 UTC", "opportunities": opps,
            "meta": {"contracts_scanned": 100, "checks_tested": 50, "kalshi_requests": 9,
                     "scanned": 10, "failed": 1, "retry_count": 0, "series_errors": {}}}


# --- contract -----------------------------------------------------------------------------------------
def test_feed_shape_and_json_serializable():
    f = feed.feed_from_snapshot(_snapshot())
    assert set(f) == {"meta", "opps"}
    for k in ("snapshot_id", "fetched_at", "n_total", "totals", "sports", "resolution_counts",
              "scope_counts"):
        assert k in f["meta"]
    assert f["meta"]["snapshot_id"] == 7 and f["meta"]["n_total"] == 6
    row = next(r for r in f["opps"] if r["id"] == "a")
    for k in ("id", "bucket", "zone", "section", "sport", "sub", "status", "tradable", "legs",
              "cond_child", "cond_success", "cond_child_firm", "cond_success_firm",
              "parent_over_maxloss", "fees", "net_edge", "nlegs"):
        assert k in row
    assert "spark" not in row and "cond" not in row     # fabricated sparkline + single-basis cond removed
    json.dumps(f, default=str)        # no circular refs; wire-serializable (the route uses FastAPI's encoder)


def test_zone_section_mapping():
    by = {r["id"]: r for r in feed.feed_from_snapshot(_snapshot())["opps"]}
    assert (by["a"]["zone"], by["a"]["section"]) == ("exec", "act")
    assert (by["b"]["zone"], by["b"]["section"]) == ("exec", "blk")
    assert (by["r"]["zone"], by["r"]["section"]) == ("exec", "rev")
    assert (by["k"]["zone"], by["k"]["section"]) == ("spec", "bounded")
    assert (by["n"]["zone"], by["n"]["section"]) == ("spec", "cheapno")
    assert (by["d"]["zone"], by["d"]["section"]) == ("diag", "diag")


def test_display_only_derived_fields():
    k = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "k")
    # conditional on BOTH bases: child/parent = 18/30 = 60% deeper-given-reached; 40% success-given-reached
    # (the fixture's display and firm prices happen to match).
    assert k["cond_child"] == 60.0 and k["cond_success"] == 40.0
    assert k["cond_child_firm"] == 60.0 and k["cond_success_firm"] == 40.0
    assert "cond" not in k                       # the buggy single-basis field is gone
    # ripeness: parent_display 30 ÷ max loss 4 (= -worst_case_profit_c) = 7.5
    assert k["parent_over_maxloss"] == 7.5
    # an exec row with no parent/child priceable pair has no conditional (either basis) / ripeness
    a = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "a")
    assert a["cond_child"] is None and a["cond_child_firm"] is None and a["parent_over_maxloss"] is None


def test_display_conditional_is_viewmodel_value_verbatim():
    """Parity (audit point 4): the feed's DISPLAY conditional is the viewmodel value verbatim, not a
    re-derivation — so the SPA's '(display)' columns can never silently drift from the old dashboard."""
    from webui import viewmodel as vm
    k_opp = next(o for o in _snapshot()["opportunities"] if o["opportunity_id"] == "k")
    k_row = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "k")
    assert k_row["cond_child"] == vm._cond_child_pct(k_opp)
    assert k_row["cond_success"] == vm._cond_success_pct(k_opp)


def test_conditional_guards_fail_closed_and_preserve_zero():
    """Both bases (audit point 2): an inverted pair (child > parent) fails closed to None; a legitimate
    child == 0 yields 0.0% (NOT None — the old truthiness bug dropped it)."""
    snap = {"snapshot_id": 9, "fetched_at": "2026-06-03 12:00:00 UTC", "meta": {}, "opportunities": [
        _opp("inv", bucket="risk_budget", extra={                       # inverted: child > parent
            "worst_case_profit_c": -4, "best_case_profit_c": 20,
            "parent_display_c": 30, "child_display_c": 40,
            "parent_yes_bid_c": 30, "child_yes_ask_c": 40}),
        _opp("zero", bucket="risk_budget", extra={                      # child == 0 → 0% / 100%
            "worst_case_profit_c": -4, "best_case_profit_c": 20,
            "parent_display_c": 30, "child_display_c": 0, "spread_over_parent": 1.0,
            "parent_yes_bid_c": 30, "child_yes_ask_c": 0})]}
    by = {r["id"]: r for r in feed.feed_from_snapshot(snap)["opps"]}
    assert by["inv"]["cond_child"] is None and by["inv"]["cond_child_firm"] is None
    assert by["inv"]["cond_success"] is None and by["inv"]["cond_success_firm"] is None
    assert by["zero"]["cond_child"] == 0.0 and by["zero"]["cond_success"] == 100.0
    assert by["zero"]["cond_child_firm"] == 0.0 and by["zero"]["cond_success_firm"] == 100.0


def test_feed_is_display_only_isolation():
    """Isolation (audit point 3): the adapter never mutates the engine rows, and the display-only
    diagnostics live ONLY in the feed row — they are never written back onto the engine opportunity."""
    snap = _snapshot()
    before = copy.deepcopy(snap["opportunities"])
    feed.feed_from_snapshot(snap)
    assert snap["opportunities"] == before          # no mutation of engine rows
    display_only = ("cond_child", "cond_success", "cond_child_firm", "cond_success_firm",
                    "parent_over_maxloss", "spark", "ev", "breakeven", "midpoint_only", "wide_basis")
    for o in snap["opportunities"]:
        for k in display_only:
            assert k not in o


def test_legs_trimmed_to_view_fields():
    a = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "a")
    # `u` is now the per-participant + per-side deep link (see test_leg_deep_link_*); other fields verbatim.
    assert a["legs"] == [{"side": "buy_yes", "c": "A", "p": 60.0, "sz": 100.0, "tk": "TA", "bo": False,
                          "u": "ua?op_market_ticker=TA&op_order_side=yes"}]


def test_trim_legs_backfills_outright_ticker_from_slot_1():
    # cheap-NO outright: real market in ticker_1, only an action_2 (Buy-NO) leg → synthesized with empty tk.
    # The leg must gain the ticker so the depth panel can load its book (and it stays a real trade leg).
    o = {"ticker_1": "KX-MKT", "ticker_2": "", "url": "http://e",
         "legs": [{"side": "buy_no", "contract": "No fade", "price_c": 12, "ticker": "", "url": "http://e"}]}
    legs = feed._trim_legs(o)
    assert len(legs) == 1
    assert legs[0]["tk"] == "KX-MKT" and legs[0]["bo"] is False
    assert legs[0]["u"] == "http://e?op_market_ticker=KX-MKT&op_order_side=no"


def test_trim_legs_appends_book_only_leg_for_unrepresented_market():
    # single-sided containment: parent leg has its ticker; the deeper child market (ticker_2) has no leg →
    # a BOOK-ONLY pseudo-leg so the panel can show its book, flagged bo=True (never an executable instruction).
    o = {"ticker_1": "KX-P", "ticker_2": "KX-C",
         "legs": [{"side": "buy_yes", "contract": "Parent", "price_c": 40, "ticker": "KX-P", "url": "http://p"}]}
    legs = feed._trim_legs(o)
    assert [(x["tk"], x["bo"]) for x in legs] == [("KX-P", False), ("KX-C", True)]
    assert legs[1]["side"] == "" and legs[1]["p"] is None       # book-only carries no trade side/price


def test_trim_legs_leaves_full_nleg_field_untouched():
    o = {"legs": [{"side": "buy_no", "contract": "A", "price_c": 5, "ticker": "KX-A", "url": "u"},
                  {"side": "buy_no", "contract": "B", "price_c": 6, "ticker": "KX-B", "url": "u"}]}
    legs = feed._trim_legs(o)
    assert [x["tk"] for x in legs] == ["KX-A", "KX-B"]
    assert all(x["bo"] is False for x in legs)


def test_leg_deep_link_yes_and_no_sides():
    legs = [{"side": "buy_yes", "contract": "A", "price_c": 60, "size": 100, "ticker": "TA", "url": "ua"},
            {"side": "buy_no", "contract": "B", "price_c": 41, "size": 80, "ticker": "TB", "url": "ub"}]
    a = next(r for r in feed.feed_from_snapshot(_snapshot_with_legs(legs))["opps"] if r["id"] == "z")
    assert a["legs"][0]["u"] == "ua?op_market_ticker=TA&op_order_side=yes"
    assert a["legs"][1]["u"] == "ub?op_market_ticker=TB&op_order_side=no"


def test_leg_deep_link_falls_back_when_ticker_missing():
    # no ticker → keep the bare event url (the link still works, just not per-market)
    legs = [{"side": "buy_yes", "contract": "A", "price_c": 60, "size": 100, "ticker": "", "url": "ua"}]
    a = next(r for r in feed.feed_from_snapshot(_snapshot_with_legs(legs))["opps"] if r["id"] == "z")
    assert a["legs"][0]["u"] == "ua"


def test_leg_deep_link_appends_with_ampersand_when_url_has_query():
    legs = [{"side": "buy_yes", "contract": "A", "price_c": 60, "size": 100, "ticker": "TA", "url": "ua?x=1"}]
    a = next(r for r in feed.feed_from_snapshot(_snapshot_with_legs(legs))["opps"] if r["id"] == "z")
    assert a["legs"][0]["u"] == "ua?x=1&op_market_ticker=TA&op_order_side=yes"


def test_meta_exposes_config_band_defaults():
    import config
    f = feed.feed_from_snapshot(_snapshot())
    d = f["meta"]["defaults"]
    assert d == {"bounded_max_loss_c": config.RISK_BUDGET_DEFAULT_MAX_LOSS_C,
                 "nearmiss_overpay_c": config.NEAR_MISS_DEFAULT_OVER_C,
                 "cheapno_max_loss_c": config.NO_STRUCTURE_DEFAULT_MAX_LOSS_C,
                 "cheapno_max_buy_no_c": config.NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C}
    # present on the empty feed too, so the SPA always has defaults to seed the SecBar
    assert feed.feed_from_snapshot(None)["meta"]["defaults"] == d


# --- parity -------------------------------------------------------------------------------------------
def test_feed_is_1to1_with_engine_rows():
    snap = _snapshot()
    f = feed.feed_from_snapshot(snap)
    src = snap["opportunities"]
    assert len(f["opps"]) == len(src)                                  # no cap, no drop, no dedupe
    assert {r["id"] for r in f["opps"]} == {o["opportunity_id"] for o in src}
    assert [r["id"] for r in f["opps"]] == [o["opportunity_id"] for o in src]   # ORDER preserved


def test_feed_copies_executable_fields_verbatim():
    snap = _snapshot()
    by = {r["id"]: r for r in feed.feed_from_snapshot(snap)["opps"]}
    for o in snap["opportunities"]:
        r = by[o["opportunity_id"]]
        assert r["bucket"] == o["bucket"]
        assert r["status"] == o["status"]
        assert r["tradable"] == o["tradable_now"]
        assert r["rule"] == o["rule_flag"]


def test_meta_totals_match_full_snapshot_counts():
    snap = _snapshot()
    f = feed.feed_from_snapshot(snap)
    assert f["meta"]["totals"] == dict(Counter(o["bucket"] for o in snap["opportunities"]))
    assert f["meta"]["scope_counts"] == {"championship": 1}
    assert f["meta"]["resolution_counts"] == {"vertical": 1}


# --- isolation ----------------------------------------------------------------------------------------
def test_feed_never_mutates_the_engine_rows():
    snap = _snapshot()
    before = copy.deepcopy(snap["opportunities"])
    feed.feed_from_snapshot(snap)
    assert snap["opportunities"] == before          # read-only adapter — the engine rows are untouched


def test_empty_snapshot_is_honest():
    f = feed.feed_from_snapshot(None)
    assert f["opps"] == [] and f["meta"]["n_total"] == 0 and f["meta"]["snapshot_id"] is None


# --- endpoint -----------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "feed.db")
    api.app.dependency_overrides[api.db_path_dep] = lambda: db
    yield TestClient(api.app), db
    api.app.dependency_overrides.clear()


def test_endpoint_serves_feed(client):
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", _snapshot()["opportunities"], db_path=db)
    resp = c.get("/api/terminal/feed")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"meta", "opps"}
    assert {r["id"] for r in body["opps"]} == {"a", "b", "r", "k", "n", "d"}
    # the feed's id set equals what /opportunities serves from the same store (single source of truth)
    opp_ids = {o["opportunity_id"] for o in c.get("/opportunities").json()}
    assert {r["id"] for r in body["opps"]} == opp_ids


def test_endpoint_empty_store(client):
    c, _ = client
    body = c.get("/api/terminal/feed").json()
    assert body["opps"] == [] and body["meta"]["n_total"] == 0


# --- Fee estimation (DISPLAY-ONLY): per-leg event-override -> series -> fallback, two scenarios ---------
def _fee_opp(oid, series, event, **kw):
    """A 2-leg opp whose leg tickers encode `series`/`event` (series = prefix; event = ticker − strike)."""
    return _opp(oid, exec_gap_c=7, **{"extra": kw.get("extra", {})}, legs=[
        {"side": "buy_yes", "contract": "A", "price_c": 50, "size": 100, "ticker": f"{event}-A", "url": "u"},
        {"side": "buy_no", "contract": "B", "price_c": 50, "size": 100, "ticker": f"{event}-B", "url": "u"},
    ]) | {"exec_min_size": 100}


def test_feed_resolves_series_fees_two_scenarios():
    snap = {"snapshot_id": 1, "fetched_at": "2026-06-16 00:00:00 UTC",
            "opportunities": [_fee_opp("a", "KXATPMATCH", "KXATPMATCH-26")],
            "meta": {"fee_rates": {"KXATPMATCH": {"fee_type": "quadratic_with_maker_fees",
                                                  "fee_multiplier": 1}},
                     "event_fee_overrides": {}, "fee_data_status": "ok"}}
    row = feed.feed_from_snapshot(snap)["opps"][0]
    # 100 contracts @ 50c: taker 175c/leg, maker 44c/leg -> 350 / 88 over two legs.
    assert row["fees_taker"] == 350 and row["fees_maker"] == 88
    assert row["fees"] == row["fees_taker"]                    # primary = taker (immediate-fill)
    assert row["taker_complete"] and row["maker_complete"]
    assert row["fee_source"] == "series" and row["fee_breakeven"] == 4
    assert len(row["fee_legs"]) == 2 and row["fee_legs"][0]["fee_type_source"] == "series"
    assert feed.feed_from_snapshot(snap)["meta"]["fee_data_status"] == "ok"


def test_feed_event_override_beats_series():
    snap = {"snapshot_id": 2, "fetched_at": "2026-06-16 00:00:00 UTC",
            "opportunities": [_fee_opp("a", "KXATPMATCH", "KXATPMATCH-26")],
            "meta": {"fee_rates": {"KXATPMATCH": {"fee_type": "quadratic_with_maker_fees",
                                                  "fee_multiplier": 1}},
                     "event_fee_overrides": {"KXATPMATCH-26": {
                         "fee_type_override": "quadratic_with_maker_fees", "fee_multiplier_override": 2}}}}
    row = feed.feed_from_snapshot(snap)["opps"][0]
    assert row["fees_taker"] == 700 and row["fee_source"] == "event_override"   # mult 2 -> double
    assert row["fee_legs"][0]["fee_multiplier"] == 2


def test_feed_no_fee_rates_falls_back_labeled():
    snap = {"snapshot_id": 3, "fetched_at": "2026-06-16 00:00:00 UTC",
            "opportunities": [_fee_opp("a", "KXATPMATCH", "KXATPMATCH-26")], "meta": {}}
    out = feed.feed_from_snapshot(snap)
    assert out["opps"][0]["fee_source"] == "fallback"
    assert out["meta"]["fee_data_status"] == "fallback"


def test_cond_pair_with_reason_explains_each_missing_cause():
    from webui.feed import _cond_pair, _cond_pair_with_reason
    assert _cond_pair_with_reason(60, 30) == (50.0, 50.0, "")        # computable -> empty reason
    assert _cond_pair_with_reason(None, 30)[2] == "no valid parent quote"
    assert _cond_pair_with_reason(60, None)[2] == "no valid child quote"
    assert _cond_pair_with_reason(0, 30)[2] == "empty book (no parent midpoint)"
    assert "inverted" in _cond_pair_with_reason(30, 60)[2]            # child > parent
    # the value-only wrapper keeps its original 2-tuple contract
    assert _cond_pair(60, 30) == (50.0, 50.0)
    assert _cond_pair(None, 30) == (None, None)
