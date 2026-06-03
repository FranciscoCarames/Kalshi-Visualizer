"""Unit tests for the cross-sport scanner (Stage 2). No network: the per-sport fetch is a stub.

The stub returns tennis-shaped fixtures regardless of sport_id — the scanner stamps `sport` from the
sport it fetched FOR (by design; per-sport classification is covered by test_consistency/test_dutchbook/
test_sports). These tests cover aggregation, sport stamping, ranking, partial-failure tolerance, and the
injected snapshot write."""
from __future__ import annotations

import pandas as pd

import scanner
import store


def _containment_df(prefix="t", gap=5):
    """One player whose Win-Tournament bid crosses the Reach-Final ask by `gap`, both legs active ->
    an actionable EXECUTABLE_VIOLATION. Also yields a MISSING_LAYER (Reach Semifinal absent)."""
    parent_ask = 40
    child_bid = parent_ask + gap

    def row(series, kind, stage, bid, ask):
        return {
            "series": series, "kind": kind, "stage": stage,
            "player": f"P{prefix}", "player_key": f"uuid-{prefix}", "contract": f"{kind}-{stage}",
            "display_pct": float(bid), "display_c": bid, "yes_bid_c": bid, "yes_ask_c": ask,
            "yes_bid_pct": float(bid), "yes_ask_pct": float(ask), "yes_bid_size": 100,
            "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
            "market_ticker": f"T-{prefix}-{stage}", "kalshi_url": "x", "status": "active",
            "tournament": "French Open", "event_ticker": f"E-{prefix}-{stage}",
        }
    return pd.DataFrame([
        row("KXFOWOMEN", "winner", "Champion", child_bid, child_bid + 1),   # Win Tournament (deeper)
        row("KXWTAADVANCE", "advance", "Final", parent_ask - 1, parent_ask),  # Reach Final (broader)
    ])


def _dutchbook_df(gap=7):
    """Two match markets whose YES asks sum to 100-gap -> underround dutch book, actionable."""
    a_ask = 45
    b_ask = (100 - gap) - a_ask

    def mk(player, key, ask):
        return {
            "series": "KXATPMATCH", "event_ticker": "EV", "kind": "match", "player": player,
            "player_key": key, "contract": f"Beat opp ({player})", "tournament": "French Open",
            "tour": "ATP", "yes_bid_c": ask - 2, "yes_ask_c": ask, "no_ask_c": None,
            "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
            "market_ticker": f"T-{key}", "kalshi_url": "x", "event_title": "M", "time_value": None,
        }
    return pd.DataFrame([mk("A", "ka", a_ask), mk("B", "kb", b_ask)])


def _fetch(sport_id):
    if sport_id == "tennis":
        return _containment_df(gap=5)
    if sport_id == "nba":
        return _dutchbook_df(gap=7)
    return pd.DataFrame()   # wnba (and anything else): no open contracts


def test_aggregates_multiple_sports_and_stamps_sport():
    unified, errors = scanner.unified_opportunities(_fetch)
    assert errors == []
    assert set(unified["sport"]) == {"tennis", "nba"}                 # ≥2 sports in one frame
    assert set(unified["source"]) == {"containment", "dutch_book"}    # both detectors represented
    # The dutch-book row was fetched for nba -> stamped nba; the containment rows for tennis.
    assert (unified.loc[unified["source"] == "dutch_book", "sport"] == "nba").all()
    assert (unified.loc[unified["source"] == "containment", "sport"] == "tennis").all()
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS


def test_ranking_actionable_first_then_edge():
    unified, _ = scanner.unified_opportunities(_fetch)
    # nba dutch book (actionable, edge 7) outranks tennis containment (actionable, edge 5);
    # the MISSING_LAYER data-quality row sorts last.
    assert unified.iloc[0]["source"] == "dutch_book" and unified.iloc[0]["exec_gap_c"] == 7
    assert unified.iloc[1]["source"] == "containment" and unified.iloc[1]["exec_gap_c"] == 5
    assert unified.iloc[0]["bucket"] == "actionable" and unified.iloc[1]["bucket"] == "actionable"
    assert unified.iloc[-1]["bucket"] == "data_quality"


def test_partial_failure_does_not_blank_other_sports():
    def fetch_raises(sport_id):
        if sport_id == "tennis":          # first sport in the registry order -> proves no blanking
            raise RuntimeError("boom")
        return _fetch(sport_id)
    unified, errors = scanner.unified_opportunities(fetch_raises)
    assert errors == [{"sport": "tennis", "error": "boom"}]
    assert set(unified["sport"]) == {"nba"}            # nba still present despite tennis failing
    assert not unified.empty


def test_snapshot_written_via_injected_store(tmp_path):
    db = str(tmp_path / "scan.db")
    unified, _ = scanner.unified_opportunities(
        _fetch,
        store_writer=lambda fa, df: store.write_snapshot(fa, df, db_path=db),
        fetched_at="2026-06-03 12:00:00 UTC",
    )
    back = store.latest_two(db_path=db)[0]["opportunities"]
    assert {o["opportunity_id"] for o in back} == set(unified["opportunity_id"])
    assert len(back) == len(unified)


def test_empty_when_all_sports_empty():
    unified, errors = scanner.unified_opportunities(lambda sid: pd.DataFrame())
    assert unified.empty
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS    # columns intact even when empty
    assert errors == []


# --- Stage 3: unified row carries the lifecycle-diff fields (rule_flag + market_status) ---
def test_unified_columns_include_lifecycle_fields():
    assert "rule_flag" in scanner.UNIFIED_COLUMNS
    assert "market_status" in scanner.UNIFIED_COLUMNS


def test_rows_carry_market_status_and_rule_flag():
    unified, _ = scanner.unified_opportunities(_fetch)
    assert set(unified["market_status"]) <= {"active", "inactive"}
    # containment rows expose rule_flag (possibly ""), dutch-book rows never carry a rule caveat
    assert (unified.loc[unified["source"] == "dutch_book", "rule_flag"] == "").all()


def test_market_status_derived_from_leg_statuses():
    # consistency mapper: inactive iff any present leg is non-active (blank does not count).
    assert scanner._market_status_consistency({"child_status": "active", "parent_status": "active"}) == "active"
    assert scanner._market_status_consistency({"child_status": "active", "parent_status": ""}) == "active"
    assert scanner._market_status_consistency({"child_status": "finalized", "parent_status": "active"}) == "inactive"


# --- Stage 4: run_scan coverage aggregation -------------------------------------------
def test_run_scan_aggregates_coverage_and_unifies():
    def fetch_fn(sid):
        if sid == "tennis":
            return _containment_df(gap=5), "fa", [("KXBAD", "boom")], 6, 5, 1, 2
        if sid == "nba":
            return _dutchbook_df(gap=7), "fa", [], 6, 6, 0, 0
        return pd.DataFrame(), "fa", [], 6, 0, 0, 0   # wnba: empty
    unified, cov = scanner.run_scan(fetch_fn, fetched_at="FA")
    assert cov["fetched_at"] == "FA"
    assert cov["scanned"] == 18 and cov["loaded"] == 11          # 6+6+6 / 5+6+0
    assert cov["failed"] == 1 and cov["excluded"] == 2 and cov["skipped_no_name"] == 1
    assert len(cov["series_errors"]) == 1 and cov["series_errors"][0]["series"] == "KXBAD"
    assert not unified.empty and set(unified["sport"]) <= {"tennis", "nba"}


def test_run_scan_records_sport_fetch_failure_without_blanking():
    def fetch_fn(sid):
        if sid == "tennis":
            raise RuntimeError("down")
        if sid == "nba":
            return _dutchbook_df(gap=7), "fa", [], 6, 6, 0, 0
        return pd.DataFrame(), "fa", [], 6, 0, 0, 0
    unified, cov = scanner.run_scan(fetch_fn, fetched_at="FA")
    assert any(e["sport"] == "tennis" and "down" in e["error"] for e in cov["sport_errors"])
    assert set(unified["sport"]) <= {"nba"}                      # tennis failed; others still scanned
