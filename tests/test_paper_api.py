"""API surface for the forward-test endpoints (disabled-shape + enabled report)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import api
import config
import paper_engine as pe
import paper_store


def _client(tmp_path):
    db = str(tmp_path / "paper.db")
    # Pin the app's db_path dependency to our temp DB (override keyed on the real dependency object).
    api.app.dependency_overrides[api.db_path_dep] = lambda: db
    return TestClient(api.app), db


def test_paper_report_disabled_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING_ENABLED", False)
    monkeypatch.delenv("PAPER_TRADING_ENABLED", raising=False)
    client, _ = _client(tmp_path)
    try:
        r = client.get("/api/terminal/paper")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["overall"]["settled"] == 0      # empty report, degrades cleanly
    finally:
        api.app.dependency_overrides.clear()


def test_paper_report_enabled_reflects_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING_ENABLED", True)
    client, db = _client(tmp_path)
    try:
        row = {"opportunity_id": "opp-1", "sport": "tennis", "bucket": "actionable",
               "relationship_type": "dutch_book", "exec_gap_c": 5, "cost_c": 95,
               "legs": [{"side": "buy_yes", "ticker": "A", "price_c": 48, "size": 3},
                        {"side": "buy_yes", "ticker": "B", "price_c": 47, "size": 3}]}
        paper_store.record_entries([pe.extract_entry(row, opened_ts=1.0)], 1, db_path=db)

        r = client.get("/api/terminal/paper")
        assert r.json()["enabled"] is True

        pos = client.get("/api/terminal/paper/positions").json()
        assert pos["enabled"] is True
        assert len(pos["positions"]) == 1
        assert len(pos["positions"][0]["legs"]) == 2
    finally:
        api.app.dependency_overrides.clear()
