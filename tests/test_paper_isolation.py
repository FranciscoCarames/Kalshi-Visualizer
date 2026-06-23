"""Isolation guarantees for the forward-test harness (the audit's hard requirement).

The harness is DEFAULT-OFF and runs only AFTER ``store.write_snapshot``, reading the scan frame without
mutating it — so scanner/engine output is identical whether the flag is on or off. These tests pin that.
"""
from __future__ import annotations

import pandas as pd

import config
import paper_recorder


def _frame():
    """A unified-style frame: one real opportunity (has a buy plan) + one CLEAN row (no plan)."""
    return pd.DataFrame([
        {"opportunity_id": "opp-1", "sport": "tennis", "bucket": "actionable",
         "relationship_type": "dutch_book", "exec_gap_c": 5, "cost_c": 95,
         "legs": [{"side": "buy_yes", "ticker": "A", "price_c": 48, "size": 3},
                  {"side": "buy_yes", "ticker": "B", "price_c": 47, "size": 3}]},
        {"opportunity_id": "clean-1", "sport": "tennis", "bucket": "clean",
         "relationship_type": "containment", "exec_gap_c": None, "cost_c": None, "legs": None},
    ])


def test_default_off(monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING_ENABLED", False)
    monkeypatch.delenv("PAPER_TRADING_ENABLED", raising=False)
    assert paper_recorder.paper_enabled() is False


def test_env_enables(monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING_ENABLED", False)
    monkeypatch.setenv("PAPER_TRADING_ENABLED", "1")
    assert paper_recorder.paper_enabled() is True


def test_config_default_enables(monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING_ENABLED", True)
    monkeypatch.delenv("PAPER_TRADING_ENABLED", raising=False)
    assert paper_recorder.paper_enabled() is True


def test_recorder_does_not_mutate_the_scan_frame(tmp_path):
    df = _frame()
    before = df.copy(deep=True)
    paper_recorder.record_from_unified(df, 1, opened_ts=1.0, db_path=str(tmp_path / "p.db"))
    # The scan frame the engine/SPA reads is untouched by recording.
    pd.testing.assert_frame_equal(df, before)


def test_records_only_rows_with_a_plan(tmp_path):
    db = str(tmp_path / "p.db")
    opened = paper_recorder.record_from_unified(_frame(), 1, opened_ts=1.0, db_path=db)
    assert opened == 1                       # the CLEAN row (no legs) is skipped, only the opportunity opens

    import paper_store
    rep = paper_store.report(db_path=db)
    assert rep["unscorable"] == 0            # a real priced opportunity, not malformed
    assert sorted(paper_store.open_tickers(db_path=db)) == ["A", "B"]
