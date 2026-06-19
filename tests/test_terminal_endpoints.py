"""Tests for the Terminal Pro parity endpoints (`/api/terminal/detail|payoff|ladder|diagnostics|export`).

These are read-only VIEWS that reuse existing engine/viewmodel/viz/export functions. The guards here are
the ones the plan's audit called out:
- **tournament scoping** — detail/ladder MUST scope to one tournament (the engine groups ladders by
  `(player_key, tournament)`); a player in two tournaments must NOT merge into one false ladder.
- **error rules** — missing tournament → 400; unknown payoff id → 404; dutch-book/no-checks → honest-empty
  scenarios; no snapshot → 409 on export.
- **read-only** — calling the endpoints never mutates the stored snapshot.
- **export parity** — the ZIP's `opportunities.csv` is exactly the posted `opportunity_ids`.
"""
from __future__ import annotations

import csv
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import api
import data
import presence
import scan_manager
import store
from webui import engine


def op(oid, *, sport="tennis", bucket="actionable", player_key="p1", tournament="T1", **kw):
    return {
        "opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": "dutch_book",
        "name": kw.get("name", "A vs B"), "detail": "underround", "tournament": tournament, "tour": "ATP",
        "action_1_text": "Buy YES", "action_2_text": "Buy NO", "exec_gap_c": 5, "exec_min_size": 10,
        "exec_max_profit_dollars": 0.5, "bucket": bucket, "status": kw.get("status", "OK"),
        "tradable_now": "Yes", "blocked_reason": "", "market_status": "active", "rule_flag": "",
        "relationship_type": "dutch_book", "url": "", "participant_key": player_key,
    }


def _contract(player_key, tournament, contract, **kw):
    """A stored contracts-frame row, minimally populated for the detail builders + raw-fields audit."""
    return {
        "player_key": player_key, "tournament": tournament, "contract": contract,
        "category": kw.get("category", "match"), "stage": kw.get("stage", ""), "opponent": "",
        "display_pct": kw.get("display_pct", 50.0), "quote_quality": "Tight", "stage_rank": kw.get("rank", 1),
        "yes_bid_pct": 48.0, "yes_ask_pct": 52.0, "volume": 10, "status": "active",
        "kalshi_url": "u", "market_ticker": f"TK-{contract}", "rules_primary": kw.get("rules", "settle X"),
        "series": "KXATPMATCH", "event_ticker": "EV", "event_title": "M", "tournament_source": "competition",
        "player_key_source": "uuid", "mapping_confidence": "high", "kind": "match",
    }


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "term.db")
    api.app.dependency_overrides[api.db_path_dep] = lambda: db
    scan_manager.manager.reset()
    # Engine caches are process-local singletons; _FRAME_CACHE is keyed without the db path, so clear all
    # three so a previous test's frames (same snapshot_id, different tmp db) can never leak in.
    engine._LATEST_CACHE.update(key=None, snap=None)
    engine._LATEST_TWO_CACHE.update(key=None, two=None)
    engine._FRAME_CACHE.clear()
    api._telemetry_cache.update(snapshot_id=object(), data=None)   # per-snapshot cache; isolate per test
    c = TestClient(api.app)
    yield c, db
    api.app.dependency_overrides.clear()
    scan_manager.manager.reset()
    engine._FRAME_CACHE.clear()


def _seed_two_tournaments(db):
    """One player_key in two tournaments — the cross-tournament-merge trap."""
    frames = [{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": [
        _contract("p1", "T1", "Beat A", rules="rules T1"),
        _contract("p1", "T2", "Beat B", rules="rules T2"),
    ]}]
    store.write_snapshot("2026-06-03 12:00:00 UTC",
                         [op("a", tournament="T1"), op("b", tournament="T2")], frames=frames, db_path=db)


def test_detail_scopes_to_tournament(client):
    c, db = client
    _seed_two_tournaments(db)
    d1 = c.get("/api/terminal/detail", params={"sport": "tennis", "player_key": "p1", "tournament": "T1"})
    d2 = c.get("/api/terminal/detail", params={"sport": "tennis", "player_key": "p1", "tournament": "T2"})
    assert d1.status_code == 200 and d2.status_code == 200
    c1 = {r["contract"] for r in d1.json()["contracts"]}
    c2 = {r["contract"] for r in d2.json()["contracts"]}
    assert c1 == {"Beat A"} and c2 == {"Beat B"}        # DISJOINT — no cross-tournament merge
    assert c1.isdisjoint(c2)
    # rules + raw-fields are scoped too
    assert {r["text"] for r in d1.json()["rules"]} == {"rules T1"}
    assert {r["tournament"] for r in d1.json()["raw_fields"]} == {"T1"}


def test_detail_requires_tournament(client):
    c, db = client
    _seed_two_tournaments(db)
    # blank tournament → 400 (our guard); never a silent fallback that merges all tournaments
    r = c.get("/api/terminal/detail", params={"sport": "tennis", "player_key": "p1", "tournament": ""})
    assert r.status_code == 400


def test_staleness_gate_is_uniform_across_opps_and_export(client):
    """N3 PROOF: the snapshot-staleness downgrade is applied in api._opps, which feeds BOTH /opportunities and
    the ZIP export (export.build_export_zip is a pure serializer of the opps it's handed). So a STALE snapshot
    can never ship a fresh 'Yes' tradable_now in the export while the live grid shows 'No — stale'. A fresh
    snapshot is the control. (CompareView reads the gated feed; the feed path is covered by test_feed.)"""
    c, db = client
    # far-past fetched_at → age >> STALE_AFTER_SECONDS → the gate downgrades the actionable 'Yes'
    store.write_snapshot("2020-01-01 12:00:00 UTC", [op("a", tradable_now="Yes")],
                         frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": []}],
                         db_path=db)
    assert api._opps(db)[0]["tradable_now"] == data.STALE_TRADABILITY      # /opportunities path gated
    r = c.post("/api/terminal/export", json={"opportunity_ids": ["a"], "snapshot_id": None})
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(
        zipfile.ZipFile(io.BytesIO(r.content)).read("opportunities.csv").decode("utf-8"))))
    assert rows[0]["tradable_now"] == data.STALE_TRADABILITY               # export path gated identically


def test_staleness_gate_fresh_snapshot_keeps_yes(client):
    """Control for the N3 proof: a fresh snapshot keeps tradable_now='Yes' through the export."""
    c, db = client
    import datetime as _dt
    fresh = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    store.write_snapshot(fresh, [op("a", tradable_now="Yes")],
                         frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": []}],
                         db_path=db)
    assert api._opps(db)[0]["tradable_now"] == "Yes"
    r = c.post("/api/terminal/export", json={"opportunity_ids": ["a"], "snapshot_id": None})
    rows = list(csv.DictReader(io.StringIO(
        zipfile.ZipFile(io.BytesIO(r.content)).read("opportunities.csv").decode("utf-8"))))
    assert rows[0]["tradable_now"] == "Yes"
    # missing param entirely → FastAPI validation 422
    assert c.get("/api/terminal/detail", params={"sport": "tennis", "player_key": "p1"}).status_code == 422


def test_ladder_scopes_to_tournament(client):
    c, db = client
    _seed_two_tournaments(db)
    r = c.get("/api/terminal/ladder", params={"sport": "tennis", "player_key": "p1", "tournament": "T1"})
    assert r.status_code == 200 and "layers" in r.json()
    assert c.get("/api/terminal/ladder",
                 params={"sport": "tennis", "player_key": "p1", "tournament": ""}).status_code == 400


def test_payoff_404_and_honest_empty(client):
    c, db = client
    _seed_two_tournaments(db)
    assert c.get("/api/terminal/payoff", params={"opportunity_id": "nope"}).status_code == 404
    # 'a' has no checks frame → no payoff matrix → honest-empty scenarios (never a fabricated curve)
    r = c.get("/api/terminal/payoff", params={"opportunity_id": "a"})
    assert r.status_code == 200 and r.json()["scenarios"] == []


def test_diagnostics_shape(client):
    c, db = client
    _seed_two_tournaments(db)
    r = c.get("/api/terminal/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert {"checks", "contracts", "category", "failures", "checks_truncated", "contracts_truncated"} <= body.keys()
    assert {row["contract"] for row in body["contracts"]} == {"Beat A", "Beat B"}   # all sports/tournaments
    assert body["contracts_truncated"] == 0


def test_export_matches_posted_ids(client):
    c, db = client
    _seed_two_tournaments(db)
    r = c.post("/api/terminal/export", json={"opportunity_ids": ["a"]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert "opportunities.csv" in names and "manifest.json" in names
        csv_text = z.read("opportunities.csv").decode()
    assert "a" in csv_text and "\nb," not in csv_text and ",b," not in csv_text   # only the posted id


def test_export_409_without_snapshot(client):
    c, _ = client
    assert c.post("/api/terminal/export", json={"opportunity_ids": ["a"]}).status_code == 409


def test_telemetry_shape_and_cache(client):
    c, db = client
    _seed_two_tournaments(db)
    r = c.get("/api/terminal/telemetry")
    assert r.status_code == 200
    body = r.json()
    assert {"snapshot_id", "top_sports", "top_contracts", "tightest", "most_traded", "volatility"} <= body.keys()
    assert body["snapshot_id"] is not None
    assert c.get("/api/terminal/telemetry").json()["snapshot_id"] == body["snapshot_id"]   # cached, no error


def test_telemetry_empty_without_snapshot(client):
    c, _ = client
    assert c.get("/api/terminal/telemetry").json() == {
        "snapshot_id": None, "top_sports": [], "top_contracts": [], "tightest": [], "most_traded": [], "volatility": None}


def test_feed_touches_terminal_presence_others_do_not(client):
    c, db = client
    _seed_two_tournaments(db)
    presence.reset()
    for path in ("/healthz", "/opportunities", "/coverage", "/metrics"):
        c.get(path)
    assert presence.recently_active(30) is False        # unrelated endpoints never heartbeat the terminal
    c.get("/api/terminal/feed")
    assert presence.recently_active(30) is True          # only the feed poll does
    presence.reset()


def test_endpoints_are_read_only(client):
    c, db = client
    _seed_two_tournaments(db)
    before = store.latest_snapshot_id(db_path=db)
    c.get("/api/terminal/detail", params={"sport": "tennis", "player_key": "p1", "tournament": "T1"})
    c.get("/api/terminal/payoff", params={"opportunity_id": "a"})
    c.get("/api/terminal/diagnostics")
    c.post("/api/terminal/export", json={"opportunity_ids": ["a"]})
    assert store.latest_snapshot_id(db_path=db) == before                          # no new snapshot written


# --- live order book (GET /api/terminal/orderbook) ----------------------------------------------------
@pytest.fixture(autouse=False)
def _reset_orderbook():
    api._orderbook_cache.clear()
    api._orderbook_limiter.reset()
    yield
    api._orderbook_cache.clear()
    api._orderbook_limiter.reset()


def test_orderbook_returns_parsed_book(client, monkeypatch, _reset_orderbook):
    c, _ = client
    seen = {}
    def fake(ticker, depth=10):
        seen["ticker"], seen["depth"] = ticker, depth
        return {"ticker": ticker, "yes": [[60, 100]], "no": [[37, 80]]}
    monkeypatch.setattr(api.kalshi_client, "get_orderbook", fake)
    r = c.get("/api/terminal/orderbook", params={"ticker": "KXNBA-27-BOS"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["yes"] == [[60, 100]] and body["no"] == [[37, 80]]
    assert seen["ticker"] == "KXNBA-27-BOS"


def test_orderbook_clamps_depth(client, monkeypatch, _reset_orderbook):
    c, _ = client
    seen = {}
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        lambda ticker, depth=10: seen.update(depth=depth) or {"ticker": ticker, "yes": [], "no": []})
    c.get("/api/terminal/orderbook", params={"ticker": "TKAAA", "depth": 9999})
    assert seen["depth"] == api._ORDERBOOK_MAX_DEPTH                  # clamped to 100, never unbounded


def test_orderbook_rejects_bad_ticker(client, _reset_orderbook):
    c, _ = client
    assert c.get("/api/terminal/orderbook", params={"ticker": "a b!"}).status_code == 400
    assert c.get("/api/terminal/orderbook", params={"ticker": "x"}).status_code == 400   # too short


def test_orderbook_degrades_honestly_on_upstream_error(client, monkeypatch, _reset_orderbook):
    c, _ = client
    def boom(*_a, **_k):
        raise api.kalshi_client.KalshiError("HTTP 503")
    monkeypatch.setattr(api.kalshi_client, "get_orderbook", boom)
    r = c.get("/api/terminal/orderbook", params={"ticker": "TKAAA"})
    assert r.status_code == 200                                      # never a 500 to the SPA
    assert r.json()["ok"] is False and "unavailable" in r.json()["error"]


def test_orderbook_caches_within_ttl(client, monkeypatch, _reset_orderbook):
    c, _ = client
    calls = {"n": 0}
    def fake(ticker, depth=10):
        calls["n"] += 1
        return {"ticker": ticker, "yes": [[60, 1]], "no": []}
    monkeypatch.setattr(api.kalshi_client, "get_orderbook", fake)
    c.get("/api/terminal/orderbook", params={"ticker": "TKAAA"})
    c.get("/api/terminal/orderbook", params={"ticker": "TKAAA"})
    assert calls["n"] == 1                                           # second poll served from the TTL cache


def test_orderbook_rate_limited(client, monkeypatch, _reset_orderbook):
    c, _ = client
    monkeypatch.setattr(api.kalshi_client, "get_orderbook",
                        lambda *a, **k: {"ticker": "T", "yes": [], "no": []})
    monkeypatch.setattr(api._orderbook_limiter, "allow", lambda _now: False)
    r = c.get("/api/terminal/orderbook", params={"ticker": "TKAAA"})
    assert r.status_code == 200 and r.json()["ok"] is False and "rate limited" in r.json()["error"]
