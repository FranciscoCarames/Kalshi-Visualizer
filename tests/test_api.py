"""Unit tests for the FastAPI engine API (Stage 4). FastAPI TestClient with dependency overrides →
a seeded tmp store + a stub fetch, so NO network and deterministic. Covers every endpoint's status +
schema, /opportunities filtering, 404, /coverage (meta / no-meta / empty), /alerts, and POST /scan
(stub-fetch write + store-backed TTL-guard skip + force)."""
from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
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
    c = TestClient(api.app)
    yield c, db
    api.app.dependency_overrides.clear()


def test_healthz_and_docs(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/docs").status_code == 200
    assert c.get("/openapi.json").status_code == 200


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
    # A snapshot with no meta (e.g. written by the Streamlit app) -> meta_present False, counts not faked.
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
    res = c.post("/scan").json()    # no prior snapshot -> runs
    assert res["skipped"] is False and res["opportunities"] >= 1
    assert res["scanned"] >= 2 and res["loaded"] >= 2
    # the scan persisted a snapshot with coverage meta
    assert store.latest(db_path=db) is not None
    assert c.get("/coverage").json()["meta_present"] is True


def test_scan_ttl_guard_skip_and_force(client):
    c, db = client
    store.write_snapshot(time.time(), [op("a")], db_path=db)   # a very recent snapshot
    before = len(store.snapshots_since(10 ** 9, db_path=db))
    skipped = c.post("/scan").json()
    assert skipped["skipped"] is True
    assert len(store.snapshots_since(10 ** 9, db_path=db)) == before   # wrote NOTHING
    forced = c.post("/scan?force=true").json()
    assert forced["skipped"] is False
    assert len(store.snapshots_since(10 ** 9, db_path=db)) == before + 1   # force scanned + wrote
