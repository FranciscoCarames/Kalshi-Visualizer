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


def test_still_open_when_market_active(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    _open_entry(db)
    monkeypatch.setattr(paper_settler.kalshi_client, "get_market",
                        lambda tk: {"ticker": tk, "status": "active", "result": ""})
    paper_settler.settle_once(db_path=db, now_ts=100.0)
    rep = paper_store.report(db_path=db)
    assert rep["overall"]["settled"] == 0
    assert rep["overall"]["open"] == 1       # outcomes not known yet → stays open
