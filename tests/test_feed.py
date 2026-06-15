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
    for k in ("id", "bucket", "zone", "section", "sport", "sub", "status", "tradable", "legs", "spark",
              "cond", "cond_child", "cond_success", "parent_over_maxloss", "fees", "net_edge", "nlegs"):
        assert k in row
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
    # conditional: child/parent = 18/30 = 60% deeper-given-reached; 40% success-given-reached
    assert k["cond"] == 60.0 and k["cond_child"] == 60.0 and k["cond_success"] == 40.0
    # ripeness: parent_display 30 ÷ max loss 4 (= -worst_case_profit_c) = 7.5
    assert k["parent_over_maxloss"] == 7.5
    # an exec row with no parent/child priceable pair has no conditional / ripeness
    a = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "a")
    assert a["cond"] is None and a["parent_over_maxloss"] is None


def test_legs_trimmed_to_view_fields():
    a = next(r for r in feed.feed_from_snapshot(_snapshot())["opps"] if r["id"] == "a")
    # `u` is now the per-participant + per-side deep link (see test_leg_deep_link_*); other fields verbatim.
    assert a["legs"] == [{"side": "buy_yes", "c": "A", "p": 60.0, "sz": 100.0, "tk": "TA",
                          "u": "ua?op_market_ticker=TA&op_order_side=yes"}]


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
