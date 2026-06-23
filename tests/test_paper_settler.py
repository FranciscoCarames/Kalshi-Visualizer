"""Settlement-sweep tests for the forward-test harness (``get_market`` mocked — no network)."""
from __future__ import annotations

import paper_engine as pe
import paper_settler
import paper_store


def _open_entry(db):
    row = {"opportunity_id": "opp-1", "sport": "tennis", "bucket": "actionable",
           "relationship_type": "dutch_book", "exec_gap_c": 5, "cost_c": 95,
           "legs": [{"side": "buy_yes", "ticker": "A", "price_c": 48, "size": 3},
                    {"side": "buy_yes", "ticker": "B", "price_c": 47, "size": 3}]}
    paper_store.record_entries([pe.extract_entry(row, opened_ts=1.0)], 1, db_path=db)


def test_settle_once_closes_an_entry(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    _open_entry(db)

    markets = {
        "A": {"ticker": "A", "status": "settled", "result": "yes", "settlement_value_dollars": "1.00"},
        "B": {"ticker": "B", "status": "settled", "result": "no", "settlement_value_dollars": "0.00"},
    }
    monkeypatch.setattr(paper_settler.kalshi_client, "get_market", lambda tk: markets[tk])

    summary = paper_settler.settle_once(db_path=db, now_ts=100.0)
    assert summary["checked"] == 2
    assert summary["newly_settled"] == 1

    rep = paper_store.report(db_path=db)
    assert rep["overall"]["settled"] == 1
    assert rep["overall"]["wins"] == 1
    assert paper_store.open_tickers(db_path=db) == []


def test_per_run_cap_defers_remaining(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    _open_entry(db)
    monkeypatch.setattr(paper_settler.kalshi_client, "get_market",
                        lambda tk: {"ticker": tk, "status": "active", "result": ""})
    summary = paper_settler.settle_once(db_path=db, max_requests=1, now_ts=100.0)
    assert summary["checked"] == 1
    assert summary["deferred"] == 1          # 2 open tickers, cap 1 → one deferred (logged, not dropped)


def test_parse_real_kalshi_market_shape():
    # Exact field shape from a LIVE settled Kalshi market (KXNBA-26-ATL, captured 2026-06-23):
    # settlement_ts is an ISO-8601 STRING, result/status/settlement_value_dollars as below.
    market = {"ticker": "KXNBA-26-ATL", "status": "finalized", "result": "no",
              "settlement_value_dollars": "0.0000", "settlement_ts": "2026-05-01T01:57:36.708679Z"}
    s = paper_settler._parse_settlement(market)
    assert s["status_raw"] == "finalized"
    assert s["result"] == "no"
    assert s["settlement_value_c"] == 0
    assert isinstance(s["settled_ts"], float) and s["settled_ts"] > 0   # ISO string parsed to epoch


def test_finalized_status_settles(tmp_path, monkeypatch):
    # Live shape uses status "finalized" (not "settled") — confirm it finalizes P&L.
    db = str(tmp_path / "p.db")
    _open_entry(db)
    markets = {
        "A": {"ticker": "A", "status": "finalized", "result": "yes", "settlement_value_dollars": "1.0000",
              "settlement_ts": "2026-05-01T01:57:36.708679Z"},
        "B": {"ticker": "B", "status": "finalized", "result": "no", "settlement_value_dollars": "0.0000",
              "settlement_ts": "2026-05-01T01:57:36.708679Z"},
    }
    monkeypatch.setattr(paper_settler.kalshi_client, "get_market", lambda tk: markets[tk])
    summary = paper_settler.settle_once(db_path=db, now_ts=100.0)
    assert summary["newly_settled"] == 1
    assert paper_store.report(db_path=db)["overall"]["settled"] == 1


def test_still_open_when_market_active(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    _open_entry(db)
    monkeypatch.setattr(paper_settler.kalshi_client, "get_market",
                        lambda tk: {"ticker": tk, "status": "active", "result": ""})
    paper_settler.settle_once(db_path=db, now_ts=100.0)
    rep = paper_store.report(db_path=db)
    assert rep["overall"]["settled"] == 0
    assert rep["overall"]["open"] == 1       # outcomes not known yet → stays open
