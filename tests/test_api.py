"""Unit tests for the FastAPI engine API (Stage 4). FastAPI TestClient with dependency overrides →
a seeded tmp store + a stub fetch, so NO network and deterministic. Covers every endpoint's status +
schema, /opportunities filtering, 404, /coverage (meta / no-meta / empty), /alerts, and POST /scan
(stub-fetch write + store-backed TTL-guard skip + force)."""
from __future__ import annotations

import os
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import scan_manager
import store


def op(oid, *, sport="tennis", bucket="actionable", status="OK", **kw):
    return {
        "opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": "dutch_book",
        "name": kw.get("name", "A vs B"), "detail": "underround", "tournament": "T", "tour": "ATP",
        "action_1_text": "Buy YES", "action_2_text": "Buy NO", "exec_gap_c": kw.get("exec_gap_c", 5),
        "exec_min_size": 10, "exec_max_profit_dollars": 0.5, "bucket": bucket, "status": status,
        "tradable_now": kw.get("tradable_now", "Yes"), "blocked_reason": kw.get("blocked_reason", ""),
        "market_status": kw.get("market_status", "active"), "rule_flag": "",
        "relationship_type": "dutch_book", "url": "",
    }


def _dutchbook_df():
    """Two match markets, underround -> one actionable dutch book (so run_scan yields ≥1 opportunity)."""
    def mk(player, key, ask):
        return {"series": "KXATPMATCH", "event_ticker": "EV", "kind": "match", "player": player,
                "player_key": key, "contract": f"Beat ({player})", "tournament": "T", "tour": "ATP",
                "yes_bid_c": ask - 2, "yes_ask_c": ask, "no_ask_c": None, "yes_bid_size": 100,
                "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
                "market_ticker": f"T-{key}", "kalshi_url": "", "event_title": "M", "time_value": None}
    return pd.DataFrame([mk("A", "ka", 45), mk("B", "kb", 48)])


def _stub_fetch(sport_id):
    """Stub for fetch_dep: a 7-tuple per sport (no network)."""
    if sport_id == "tennis":
        return _dutchbook_df(), "2026-06-03 12:00:00 UTC", [], 2, 2, 0, 0
    return pd.DataFrame(), "2026-06-03 12:00:00 UTC", [], 1, 0, 0, 0


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "api.db")
    api.app.dependency_overrides[api.db_path_dep] = lambda: db
    api.app.dependency_overrides[api.fetch_dep] = lambda: _stub_fetch
    scan_manager.manager.reset()                 # the singleflight is a singleton — isolate each test
    api._scan_limiter.reset()                    # the HTTP /scan rate limiter is a singleton too (PR 26b)
    os.environ.pop("SCAN_TOKEN", None)           # gate OFF by default unless a test sets it
    c = TestClient(api.app)
    yield c, db
    api.app.dependency_overrides.clear()
    scan_manager.manager.reset()
    api._scan_limiter.reset()
    os.environ.pop("SCAN_TOKEN", None)


def _tennis_field_rows():
    """Four tennis players, each with the 3-node ladder priced (Reach Semifinal/Final/Win), so the
    field-de-vig conditional has a real distribution to normalise over (survivors 4/2/1)."""
    rows = []
    for pk, name, sf, fin, win in (("p1", "Alpha", 80, 55, 30), ("p2", "Bravo", 70, 40, 18),
                                   ("p3", "Charlie", 60, 30, 10), ("p4", "Delta", 50, 25, 8)):
        for node, pct in (("Reach Semifinal", sf), ("Reach Final", fin), ("Win Tournament", win)):
            rows.append({"series": "KXATPADVANCE", "player_key": pk, "player": name,
                         "tournament": "Wimbledon 2026", "ladder_node": node, "kind": "advance",
                         "market_family": "advance", "display_pct": pct, "display_c": pct,
                         "yes_bid_c": pct - 1, "yes_ask_c": pct + 1, "quote_quality": "Tight",
                         "status": "active", "market_ticker": f"KXATPADVANCE-{pk}-{node[:3]}"})
    return rows


def test_terminal_detail_includes_field_devig_conditional(client):
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a")],
                         frames=[{"sport": "tennis", "frame_type": "contracts",
                                  "schema_version": 1, "rows": _tennis_field_rows()}], db_path=db)
    r = c.get("/api/terminal/detail",
              params={"sport": "tennis", "player_key": "p1", "tournament": "Wimbledon 2026"})
    assert r.status_code == 200
    cps = r.json()["conditional_probabilities"]
    assert cps, "expected conditional-probability rows for a 3-node ladder"
    sf = next(x for x in cps if x["parent"] == "Reach Semifinal")
    # both the raw price ratio AND the field-implied de-vig estimate are present (display-only)
    assert sf["win_cond_raw"] is not None and sf["win_cond_dv"] is not None
    assert sf["next_node"] == "Reach Final" and "partial" in sf and "ladder_inverted" in sf


def test_terminal_detail_devig_blank_without_field(client):
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a")], db_path=db)   # no contracts frame
    r = c.get("/api/terminal/detail",
              params={"sport": "tennis", "player_key": "nobody", "tournament": "T"})
    assert r.status_code == 200
    cps = r.json()["conditional_probabilities"]
    # ladder-shaped placeholder rows are emitted, but with NO real probabilities (the SPA hides the panel)
    assert all(x["win_cond_raw"] is None and x["win_cond_dv"] is None for x in cps)


def test_healthz_and_docs(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/docs").status_code == 200
    assert c.get("/openapi.json").status_code == 200


# --- /api/terminal/fill (visible-depth gross-edge curve) ---------------------------

def _fill_opp(oid="f1", *, payout_floor_c=100, exec_gap_c=7, legs=None):
    """A 2-leg buy-YES underround opp with a structural floor + explicit legs/tickers."""
    o = op(oid, source="dutch_book")
    o["payout_floor_c"] = payout_floor_c
    o["exec_gap_c"] = exec_gap_c
    o["legs"] = legs if legs is not None else [
        {"side": "buy_yes", "ticker": "TKA", "contract": "A"},
        {"side": "buy_yes", "ticker": "TKB", "contract": "B"}]
    return o


def _reset_orderbook_state():
    api._orderbook_cache.clear()
    api._orderbook_limiter.reset()


def _stub_books(mapping):
    """Return a get_orderbook stub serving {ticker: {"yes": [...], "no": [...]}} (cents, like the client)."""
    def _gb(ticker, depth=10):
        b = mapping.get(ticker.upper(), {})
        return {"ticker": ticker, "yes": b.get("yes", []), "no": b.get("no", [])}
    return _gb


def test_fill_curve_basic_and_supports_scanned_edge(client, monkeypatch):
    c, db = client
    _reset_orderbook_state()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_fill_opp("f1")], db_path=db)
    # buy_yes consumes NO bids: NO bid 55 -> yes ask 45; NO bid 52 -> yes ask 48; sum 93 < 100 -> edge 7.
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        _stub_books({"TKA": {"no": [[55, 100]]}, "TKB": {"no": [[52, 100]]}}))
    r = c.get("/api/terminal/fill", params={"opportunity_id": "f1"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["summary"]["current_top_edge_c"] == 7
    assert j["scanned_edge_c"] == 7
    assert j["book_supports_scanned_edge"] is True
    assert j["curve"][0]["marginal_edge_c"] == 7


def test_fill_curve_flags_decayed_book(client, monkeypatch):
    c, db = client
    _reset_orderbook_state()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_fill_opp("f2", exec_gap_c=7)], db_path=db)
    # live book worse than scan: yes asks 47 + 49 = 96 -> live edge 4 < scanned 7.
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        _stub_books({"TKA": {"no": [[53, 100]]}, "TKB": {"no": [[51, 100]]}}))
    j = c.get("/api/terminal/fill", params={"opportunity_id": "f2"}).json()
    assert j["summary"]["current_top_edge_c"] == 4
    assert j["book_supports_scanned_edge"] is False


def test_fill_unknown_opportunity_is_404(client):
    c, _ = client
    assert c.get("/api/terminal/fill", params={"opportunity_id": "nope"}).status_code == 404


def test_fill_floorless_shape_degrades(client, monkeypatch):
    c, db = client
    _reset_orderbook_state()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_fill_opp("f3", payout_floor_c=None)], db_path=db)
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        _stub_books({"TKA": {"no": [[55, 100]]}, "TKB": {"no": [[52, 100]]}}))
    j = c.get("/api/terminal/fill", params={"opportunity_id": "f3"}).json()
    assert j["ok"] is False and "floor" in j["reason"]


def test_fill_empty_book_degrades_cleanly(client, monkeypatch):
    c, db = client
    _reset_orderbook_state()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_fill_opp("f4")], db_path=db)
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        _stub_books({"TKA": {"no": [[55, 100]]}, "TKB": {}}))   # TKB has no NO bids
    j = c.get("/api/terminal/fill", params={"opportunity_id": "f4"}).json()
    assert j["ok"] is False and "no visible ask" in j["reason"]


def test_fill_does_not_alter_feed_row(client, monkeypatch):
    """The fill endpoint is display-only: a feed row must be byte-identical before and after calling it."""
    c, db = client
    _reset_orderbook_state()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_fill_opp("f5")], db_path=db)
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        _stub_books({"TKA": {"no": [[55, 100]]}, "TKB": {"no": [[52, 100]]}}))
    before = c.get("/api/terminal/feed").json()
    c.get("/api/terminal/fill", params={"opportunity_id": "f5"})
    after = c.get("/api/terminal/feed").json()
    assert before == after


def test_opportunities_and_filters(client):
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", [
        op("a", sport="tennis", bucket="actionable", status="OK"),
        op("b", sport="nba", bucket="blocked", status="BAD"),
    ], db_path=db)
    allrows = c.get("/opportunities").json()
    assert {r["opportunity_id"] for r in allrows} == {"a", "b"}
    assert [r["opportunity_id"] for r in c.get("/opportunities?sport=nba").json()] == ["b"]
    assert [r["opportunity_id"] for r in c.get("/opportunities?bucket=actionable").json()] == ["a"]
    assert [r["opportunity_id"] for r in c.get("/opportunities?status=BAD").json()] == ["b"]


def test_opportunity_by_id_and_404(client):
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a")], db_path=db)
    assert c.get("/opportunities/a").json()["opportunity_id"] == "a"
    assert c.get("/opportunities/nope").status_code == 404


def test_backlog(client):
    c, db = client
    store.write_snapshot(1000, [op("x", bucket="actionable")], db_path=db)
    store.write_snapshot(2000, [op("x", bucket="blocked", market_status="active")], db_path=db)
    items = c.get("/backlog?window_s=1000000000").json()
    assert [i["opportunity_id"] for i in items] == ["x"]
    assert items[0]["reason_left"] == "went blocked"


def test_backlog_unchanged_with_durable_table(client):
    # Back-compat: the live /backlog (recently_actionable) response is unaffected by the v4 durable table.
    c, db = client
    store.write_snapshot(1000, [op("x", bucket="actionable")], db_path=db)
    store.write_snapshot(2000, [op("x", bucket="blocked", market_status="active")], db_path=db)
    items = c.get("/backlog?window_s=1000000000").json()
    assert [i["opportunity_id"] for i in items] == ["x"]
    assert set(items[0]) >= {"became_ts", "left_ts", "reason_left", "current_bucket"}


def test_backlog_events_durable(client):
    c, db = client
    # x: actionable then leaves; y: bounded_loss (risk_budget) stays open.
    store.write_snapshot(1000, [op("x", bucket="actionable"),
                                op("y", bucket="risk_budget")], db_path=db)
    store.write_snapshot(2000, [op("y", bucket="risk_budget")], db_path=db)   # x dropped out, y advances
    rows = c.get("/backlog/events?days=7").json()
    by_id = {r["opportunity_id"]: r for r in rows}
    assert by_id["x"]["category"] == "actionable" and by_id["x"]["is_open"] is False
    assert by_id["y"]["category"] == "bounded_loss" and by_id["y"]["is_open"] is True
    # category filter
    bl = c.get("/backlog/events?category=bounded_loss").json()
    assert {r["opportunity_id"] for r in bl} == {"y"}
    # closed-only filter
    closed = c.get("/backlog/events?include_open=false").json()
    assert {r["opportunity_id"] for r in closed} == {"x"}


def test_backlog_events_reappearance_two_intervals(client):
    # The audit-point-3 regression at the API boundary: appear -> leave -> reappear = TWO intervals.
    c, db = client
    store.write_snapshot(1000, [op("z", bucket="actionable")], db_path=db)
    store.write_snapshot(2000, [op("q", bucket="actionable")], db_path=db)   # z leaves
    store.write_snapshot(3000, [op("z", bucket="actionable")], db_path=db)   # z returns
    z_rows = [r for r in c.get("/backlog/events").json() if r["opportunity_id"] == "z"]
    assert len(z_rows) == 2
    assert sorted(r["is_open"] for r in z_rows) == [False, True]


def test_coverage_meta_present(client):
    c, db = client
    meta = {"fetched_at": "2026-06-03 12:00:00 UTC", "scanned": 5, "loaded": 4, "failed": 1,
            "excluded": 2, "skipped_no_name": 0, "sport_errors": [],
            "series_errors": [{"sport": "tennis", "series": "X", "error": "boom"}]}
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a")], meta=meta, db_path=db)
    cov = c.get("/coverage").json()
    assert cov["meta_present"] is True
    assert cov["scanned"] == 5 and cov["loaded"] == 4 and cov["failed"] == 1 and cov["excluded"] == 2
    assert cov["series_errors"][0]["series"] == "X"
    assert isinstance(cov["data_age_seconds"], (int, float))


def test_coverage_no_meta_and_empty(client):
    c, db = client
    # No snapshot yet -> honest empty, not faked.
    empty = c.get("/coverage").json()
    assert empty["meta_present"] is False and empty["scanned"] == 0 and empty["fetched_at"] is None
    # A snapshot with no meta (e.g. written by an older writer) -> meta_present False, counts not faked.
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a")], db_path=db)
    nom = c.get("/coverage").json()
    assert nom["meta_present"] is False and nom["fetched_at"] is not None and nom["scanned"] == 0


def test_alerts(client):
    c, db = client
    store.write_snapshot(1000, [op("A", bucket="actionable", tradable_now="Yes")], db_path=db)
    store.write_snapshot(2000, [op("A", bucket="blocked", tradable_now="No"),
                                op("B", bucket="actionable")], db_path=db)
    alerts = c.get("/alerts").json()
    assert [r["opportunity_id"] for r in alerts["new_actionable"]] == ["B"]
    assert any(ch["opportunity_id"] == "A" and ch["transitioned"] for ch in alerts["blocked_changes"])


def test_scan_writes_via_stub_fetch(client):
    c, db = client
    # PR 21b: non-blocking 202. ?wait=true joins the (fast stub) scan so the assertion is deterministic.
    res = c.post("/scan?wait=true")
    assert res.status_code == 202
    st = res.json()
    assert st["status"] == "done" and st["last_snapshot_id"] is not None
    assert store.latest(db_path=db) is not None
    assert c.get("/coverage").json()["meta_present"] is True
    # GET /scan/status reflects the completed scan (coverage carried in last_result).
    status = c.get("/scan/status").json()
    assert status["status"] == "done" and status["last_result"]["scanned"] >= 2


def test_scan_ttl_guard_skip_and_force(client):
    c, db = client
    store.write_snapshot(time.time(), [op("a")], db_path=db)   # a very recent snapshot
    before = len(store.snapshots_since(10 ** 9, db_path=db))
    skipped = c.post("/scan")
    assert skipped.status_code == 202 and skipped.json()["status"] == "skipped"
    assert skipped.json()["reason"] == "ttl"
    assert len(store.snapshots_since(10 ** 9, db_path=db)) == before   # wrote NOTHING
    forced = c.post("/scan?force=true&wait=true").json()
    assert forced["status"] == "done"
    assert len(store.snapshots_since(10 ** 9, db_path=db)) == before + 1   # force scanned + wrote


def test_scan_status_idle_before_any_scan(client):
    c, _ = client
    assert c.get("/scan/status").json()["status"] == "idle"


def test_empty_store_endpoints_are_honest(client):
    # No snapshot yet: read endpoints return empty/None — never error, never fake data.
    c, _ = client
    assert c.get("/opportunities").json() == []
    assert c.get("/opportunities/anything").status_code == 404
    assert c.get("/backlog?window_s=3600").json() == []
    assert c.get("/alerts").json() == {"new_actionable": [], "blocked_changes": []}
    cov = c.get("/coverage").json()
    assert cov["meta_present"] is False and cov["fetched_at"] is None and cov["scanned"] == 0


# --- PR 13: schema fields survive the API boundary -----------------------------------
def test_opportunity_model_preserves_pr13_fields():
    # extra="ignore" drops UNDECLARED fields, so every persisted column the UI/export needs must be
    # declared. PR 13 added payout_floor_c/roi_pct/cost_c/settlement_caveat/ticker_1/2/url_2 + N-leg legs.
    row = op("x")
    row.update(cost_c=93, action_1_price_c=45, action_2_price_c=48, payout_floor_c=100, roi_pct=7.5,
              settlement_caveat="per-game", ticker_1="TA", ticker_2="TB", url_2="u2",
              legs=[{"text": "a"}, {"text": "b"}], n_legs=2)
    o = api.Opportunity(**row)
    assert o.cost_c == 93 and o.payout_floor_c == 100 and o.roi_pct == 7.5
    assert o.settlement_caveat == "per-game" and o.ticker_1 == "TA" and o.ticker_2 == "TB" and o.url_2 == "u2"
    assert o.n_legs == 2 and isinstance(o.legs, list) and len(o.legs) == 2


def test_opportunity_model_carries_top2_bundle_fields():
    # The exact-order two-tier economics must survive extra="ignore" for the API/export consumers.
    row = op("x")
    row.update(opportunity_class="speculative_top2_bundle", top2_net_if_top2_c=16,
               top2_loss_if_not_top2_c=84, top2_max_units=100, worst_bundle_quote_quality="Tight",
               wide_bundle_leg_count=0, comparator_quote_quality="OK",
               legs=[{"text": f"l{i}"} for i in range(12)], n_legs=12)
    o = api.Opportunity(**row)
    assert o.opportunity_class == "speculative_top2_bundle" and o.top2_net_if_top2_c == 16
    assert o.top2_loss_if_not_top2_c == 84 and o.top2_max_units == 100
    assert o.worst_bundle_quote_quality == "Tight" and o.wide_bundle_leg_count == 0
    assert o.comparator_quote_quality == "OK" and o.n_legs == 12 and len(o.legs) == 12


def test_opportunity_model_carries_participant_lists():
    # PR6 (#13): the participant multi-select needs every leg's key/label to survive extra="ignore".
    row = op("x")
    row.update(participant_keys=["ka", "kb"], participant_labels=["A", "B"])
    o = api.Opportunity(**row)
    assert o.participant_keys == ["ka", "kb"] and o.participant_labels == ["A", "B"]
    assert api.Opportunity(**op("y")).participant_keys == []   # default empty, never required


def test_backlog_model_carries_last_legs():
    item = api.BacklogItem(opportunity_id="x", last_legs=[{"text": "a"}], payout_floor_c=100, roi_pct=9.0)
    assert isinstance(item.last_legs, list) and item.payout_floor_c == 100 and item.roi_pct == 9.0


def test_metrics_empty_then_seeded(client):
    c, db = client
    m = c.get("/metrics")
    assert m.status_code == 200
    body = m.json()
    assert body["snapshot_id"] is None and body["opportunities"] == 0 and body["scan_status"] == "idle"

    store.write_snapshot("2026-06-03 12:00:00 UTC",
                         [op("a", bucket="actionable"), op("b", bucket="blocked")],
                         meta={"scanned": 6, "loaded": 5, "failed": 1, "kalshi_requests": 18,
                               "contracts_scanned": 9, "checks_tested": 4,
                               "sport_errors": [{"sport": "nba", "error": "boom"}]},
                         db_path=db)
    body = c.get("/metrics").json()
    assert body["snapshot_id"] and body["opportunities"] == 2 and body["actionable"] == 1
    assert body["kalshi_requests"] == 18 and body["failed_series"] == 1 and body["sport_error_count"] == 1
    assert body["contracts_scanned"] == 9 and body["checks_tested"] == 4


def test_metrics_reflects_scan_status_after_scan(client):
    c, db = client
    assert c.post("/scan?wait=true").status_code == 202
    body = c.get("/metrics").json()
    assert body["snapshot_id"] is not None and body["scan_status"] in ("done", "in_progress")


def test_metrics_viewer_count_present(client):
    c, db = client
    import presence
    presence.reset()
    body = c.get("/metrics").json()
    assert body["viewer_count"] == 0          # no websocket clients in the test client
    presence.reset()


# --- scan-token gate + HTTP rate limit (PR 26b) ---------------------------------------
def test_scan_open_by_default_when_token_unset(client):
    c, _ = client
    assert "SCAN_TOKEN" not in os.environ
    assert c.post("/scan").status_code == 202          # no header needed when the gate is off


def test_scan_token_required_when_set(client):
    c, _ = client
    os.environ["SCAN_TOKEN"] = "s3cret"
    assert c.post("/scan").status_code == 401                                  # no header
    assert c.post("/scan", headers={"X-Scan-Token": "wrong"}).status_code == 401
    assert c.post("/scan", headers={"X-Scan-Token": "s3cret"}).status_code == 202   # correct token


def test_scan_http_rate_limited(client, monkeypatch):
    c, _ = client
    # Shrink the window cap so a couple of calls trip it; the limiter is reset per-test by the fixture.
    monkeypatch.setattr(api._scan_limiter, "max_events", 2)
    assert c.post("/scan").status_code == 202
    assert c.post("/scan").status_code == 202
    assert c.post("/scan").status_code == 429          # third within the window is rejected


def test_scan_status_not_gated(client):
    c, _ = client
    os.environ["SCAN_TOKEN"] = "s3cret"
    assert c.get("/scan/status").status_code == 200     # read-only status stays open


def test_telemetry_computed_once_per_snapshot(client, monkeypatch):
    # B6: the per-snapshot telemetry cache (now lock-guarded) computes the heavy liquidity_panel at most
    # once per snapshot — a second poll is served from cache.
    c, db = client
    store.write_snapshot("2026-06-03 12:00:00 UTC", [op("a", bucket="actionable")], db_path=db)
    api._telemetry_cache["snapshot_id"], api._telemetry_cache["data"] = object(), None   # isolate the global
    from webui import viewmodel
    calls = []
    real = viewmodel.liquidity_panel
    monkeypatch.setattr(viewmodel, "liquidity_panel", lambda contracts: (calls.append(1), real(contracts))[1])
    r1 = c.get("/api/terminal/telemetry")
    r2 = c.get("/api/terminal/telemetry")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["snapshot_id"] == r2.json()["snapshot_id"]
    assert len(calls) == 1                       # second poll hit the cache — computed once
    api._telemetry_cache["snapshot_id"], api._telemetry_cache["data"] = object(), None
