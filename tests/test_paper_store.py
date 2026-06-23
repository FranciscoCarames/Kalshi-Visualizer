"""Round-trip tests for the paper-position store (open-once, settle, report)."""
from __future__ import annotations

import config
import paper_engine as pe
import paper_store
import roundtrip_cost


def _entry(**over):
    row = {
        "opportunity_id": over.get("opportunity_id", "opp-1"),
        "sport": "tennis", "bucket": "actionable", "relationship_type": "dutch_book",
        "exec_gap_c": over.get("exec_gap_c", 5), "cost_c": over.get("cost_c", 95),
        "legs": over.get("legs", [
            {"side": "buy_yes", "ticker": "TICK_A", "price_c": 48, "size": 10},
            {"side": "buy_yes", "ticker": "TICK_B", "price_c": 47, "size": 8},
        ]),
    }
    return pe.extract_entry(row, opened_ts=over.get("opened_ts", 1.0))


def _db(tmp_path):
    # A real file (not :memory:) — each store call opens its own connection, so the DB must persist.
    return str(tmp_path / "paper.db")


def test_open_once(tmp_path):
    db = _db(tmp_path)
    e = _entry()
    assert paper_store.record_entries([e], 1, db_path=db) == 1
    assert paper_store.record_entries([e], 2, db_path=db) == 0     # same edge re-seen → no re-open
    assert sorted(paper_store.open_tickers(db_path=db)) == ["TICK_A", "TICK_B"]


def test_settle_and_report(tmp_path):
    db = _db(tmp_path)
    paper_store.record_entries([_entry()], 1, db_path=db)
    paper_store.cache_settlements([
        {"ticker": "TICK_A", "result": "yes", "status_raw": "settled", "settled_ts": 10.0, "settlement_value_c": 100},
        {"ticker": "TICK_B", "result": "no", "status_raw": "settled", "settled_ts": 10.0, "settlement_value_c": 0},
    ], fetched_ts=5.0, db_path=db)
    assert paper_store.rescore(db_path=db) == 1

    rep = paper_store.report(db_path=db)
    fees = (roundtrip_cost.fee_c(1, 48, config.FEE_TAKER_BASE_COEFF)
            + roundtrip_cost.fee_c(1, 47, config.FEE_TAKER_BASE_COEFF))
    assert rep["overall"]["settled"] == 1
    assert rep["overall"]["wins"] == 1
    assert rep["overall"]["net_c"] == 5 - fees
    assert rep["overall"]["win_rate"] == 1.0
    assert "executable" in rep["by_class"]
    assert rep["by_sport"]["tennis"]["settled"] == 1
    assert paper_store.open_tickers(db_path=db) == []              # nothing left open


def test_unscorable_excluded_from_headline(tmp_path):
    db = _db(tmp_path)
    bad = pe.extract_entry({"opportunity_id": "bad", "exec_gap_c": None, "cost_c": None,
                            "legs": [{"side": "buy_yes", "ticker": "T", "price_c": None}]}, opened_ts=1.0)
    assert bad.scorable is False
    paper_store.record_entries([bad], 1, db_path=db)
    rep = paper_store.report(db_path=db)
    assert rep["unscorable"] == 1
    assert rep["overall"]["settled"] == 0
    assert paper_store.open_tickers(db_path=db) == []             # unscorable legs aren't polled


def test_list_positions_carries_legs(tmp_path):
    db = _db(tmp_path)
    paper_store.record_entries([_entry()], 7, db_path=db)
    pos = paper_store.list_positions(db_path=db)
    assert len(pos) == 1
    assert pos[0]["first_snapshot_id"] == 7
    assert len(pos[0]["legs"]) == 2
    assert pos[0]["legs"][0]["ticker"] == "TICK_A"
