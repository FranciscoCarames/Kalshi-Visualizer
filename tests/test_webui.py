"""Unit tests for the NiceGUI dashboard's engine layer (Stage 5). The correctness backbone is the
in-process accessors in `webui.engine` over a tmp-seeded store (no network, no browser); plus a smoke
test that `webui.dashboard` imports and registers its page. Interactive rendering is verified by the
live `serve.py` boot. Engine/API suites remain the correctness backbone."""
from __future__ import annotations

import pandas as pd
import pytest

import config
import store
from webui import dashboard as dash
from webui import engine


def op(oid, *, sport="tennis", bucket="actionable", **kw):
    return {
        "opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": "dutch_book",
        "name": kw.get("name", "A vs B"), "detail": "underround", "tournament": "T", "tour": "ATP",
        "action_1_text": "Buy YES — A @ 45¢", "action_2_text": "Buy YES — B @ 48¢",
        "action_1_price_c": 45, "action_2_price_c": 48, "cost_c": 93,
        "exec_gap_c": kw.get("exec_gap_c", 7), "exec_min_size": 100, "exec_max_profit_dollars": 7.0,
        "bucket": bucket, "status": kw.get("status", "EXECUTABLE_DUTCH_BOOK"),
        "tradable_now": kw.get("tradable_now", "Yes"), "blocked_reason": kw.get("blocked_reason", ""),
        "market_status": kw.get("market_status", "active"), "rule_flag": "",
        "relationship_type": "dutch_book", "ticker_1": "T-a", "ticker_2": "T-b",
        "url": "u1", "url_2": "",
    }


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    db = str(tmp_path / "webui.db")
    monkeypatch.setattr(config, "SNAPSHOT_DB_PATH", db)   # engine calls store with db_path=None -> uses this
    return db


def test_latest_and_bucket_split(tmpdb):
    store.write_snapshot("2026-06-04 12:00:00 UTC",
                         [op("a", bucket="actionable"), op("b", bucket="blocked")])
    assert {o["opportunity_id"] for o in engine.latest_opportunities()} == {"a", "b"}
    assert [o["opportunity_id"] for o in engine.opportunities_in_bucket("blocked")] == ["b"]
    assert [o["opportunity_id"] for o in engine.opportunities_in_bucket("actionable")] == ["a"]


def test_coverage_empty_then_with_meta(tmpdb):
    cov = engine.coverage()
    assert cov["meta_present"] is False and cov["fetched_at"] is None and cov["opportunities"] == 0
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("a")],
                         meta={"scanned": 5, "loaded": 4, "failed": 1, "excluded": 0})
    cov = engine.coverage()
    assert cov["meta_present"] and cov["scanned"] == 5 and cov["loaded"] == 4 and cov["opportunities"] == 1
    assert isinstance(cov["data_age_seconds"], (int, float))


def test_backlog_and_alerts(tmpdb):
    store.write_snapshot(1000, [op("x", bucket="actionable")])
    store.write_snapshot(2000, [op("x", bucket="blocked", market_status="active"),
                                op("y", bucket="actionable")])
    bl = engine.backlog(10 ** 9)
    assert any(b["opportunity_id"] == "x" and b["reason_left"] == "went blocked" for b in bl)
    al = engine.alerts()
    assert [r["opportunity_id"] for r in al["new_actionable"]] == ["y"]
    assert any(c["opportunity_id"] == "x" and c["transitioned"] for c in al["blocked_changes"])


def test_run_scan_now_offline(tmpdb, monkeypatch):
    def _df():
        def mk(p, k, ask):
            return {"series": "KXATPMATCH", "event_ticker": "EV", "kind": "match", "player": p,
                    "player_key": k, "contract": f"Beat ({p})", "tournament": "T", "tour": "ATP",
                    "yes_bid_c": ask - 2, "yes_ask_c": ask, "no_ask_c": None, "yes_bid_size": 100,
                    "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
                    "market_ticker": f"T-{k}", "kalshi_url": "", "event_title": "M", "time_value": None}
        return pd.DataFrame([mk("A", "ka", 45), mk("B", "kb", 48)])

    def stub(sport_id):
        return (_df(), "fa", [], 2, 2, 0, 0) if sport_id == "tennis" else (pd.DataFrame(), "fa", [], 1, 0, 0, 0)
    monkeypatch.setattr(engine, "fetch_dep", lambda: stub)   # no network
    cov = engine.run_scan_now()
    assert cov["scanned"] >= 2 and cov["fetched_at"]
    assert engine.latest_opportunities()                     # something was persisted


def test_dashboard_imports_and_registers_page():
    import webui.dashboard
    assert callable(webui.dashboard.dashboard)


# --- dashboard pure builders (no NiceGUI runtime needed) ------------------------------
def test_opp_row_new_marker_and_fields():
    o = op("AAA", bucket="actionable")
    r = dash._opp_row(o, {"AAA"})
    assert r["new"] == "🆕" and r["opportunity_id"] == "AAA"
    assert r["sport"] == "Tennis" and r["edge"] == 7 and r["units"] == 100 and r["profit"] == 7.0
    assert dash._opp_row(o, set())["new"] == ""            # not new -> blank marker


def test_opp_row_handles_none_numbers():
    o = op("Z", bucket="blocked")
    o["exec_gap_c"] = o["exec_min_size"] = o["exec_max_profit_dollars"] = None
    r = dash._opp_row(o, set())
    assert r["edge"] is None and r["units"] is None and r["profit"] is None   # no crash on None


def test_ts_disp_and_backlog_row():
    assert dash._ts_disp(None, "UTC") == "—"
    assert dash._ts_disp(1000.0, "UTC") != "—"             # formats an epoch
    b = {"sport": "nba", "name": "X vs Y", "became_ts": 1000.0, "left_ts": 1180.0,
         "duration_s": 180.0, "reason_left": "went blocked", "last_edge_c": 4,
         "current_status": "blocked"}
    row = dash._backlog_row(b, "UTC")
    assert row["mins"] == 3.0 and row["reason"] == "went blocked" and row["last_edge"] == 4
    # None duration / timestamps are safe
    safe = dash._backlog_row({"became_ts": None, "left_ts": None, "duration_s": None}, "UTC")
    assert safe["became"] == "—" and safe["left"] == "—" and safe["mins"] is None


def test_explanation_lines_content():
    o = op("AAA", bucket="blocked", blocked_reason="leg inactive")
    lines = dash.explanation_lines(o, show_ids=True)
    blob = "\n".join(lines)
    assert "Leg 1: Buy YES — A @ 45¢" in blob and "Leg 2:" in blob
    assert "Cost: 93¢" in blob and "Gross edge: 7¢" in blob and "Gross profit: $7.0" in blob
    assert "Relationship: dutch_book" in blob and "Market: active" in blob
    assert "Caveat: leg inactive" in blob                 # blocked_reason surfaced
    assert any("T-a / T-b" in line for line in lines)      # show_ids -> tickers
    # without show_ids and without a caveat, those lines are omitted
    plain = dash.explanation_lines(op("BBB", bucket="actionable"), show_ids=False)
    assert not any("T-a / T-b" in line for line in plain) and not any(line.startswith("Caveat") for line in plain)
