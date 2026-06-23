"""Unit + wiring tests for the numeric-box demonstrator adapter (DEFAULT-OFF, diagnostic-only).

Covers: the corridor it builds from a monotone ladder, the never-Actionable routing, fail-closed on
cross-event rows, and the audit #3 SURVIVAL proof — that `payoff_scenarios` lives in UNIFIED_COLUMNS + the
api.Opportunity model and survives scanner -> store -> /opportunities + the terminal feed. Plus the
flag-OFF regression (zero new rows when the flag is off)."""
from __future__ import annotations

import pandas as pd

import api
import config
import consistency
import numeric_box_adapter as nba
import scanner
import sports
import store
import webui.feed as feed


def ge_row(event, floor, *, yes_ask_c, no_ask_c=None, yes_bid_c=None, size=100, series="KXATPGTOTAL",
           quote_quality="OK", status="active"):
    """A live-shaped 'Over N games' market row carrying both the numeric strike AND firm pricing, so
    numeric_ladder parses it and dutchbook's firm-ask helpers can price the legs."""
    return {
        "series_ticker": series, "series": series, "event_ticker": event,
        "strike_type": "greater", "floor_strike": floor, "cap_strike": None, "market_type": "binary",
        "kind": "other", "player_key": "", "stage": "", "tour": "ATP", "tournament": "Test Open",
        "yes_sub_title": f"Over {floor} games", "contract": f"Over {floor}", "event_title": "ATP total games",
        "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c, "yes_bid_c": yes_bid_c,
        "yes_ask_size": size, "yes_bid_size": size, "quote_quality": quote_quality, "status": status,
        "market_ticker": f"{event}-{floor}", "kalshi_url": f"http://k/{event}/{floor}",
    }


# --- adapter unit tests --------------------------------------------------------------
def test_corridor_structural_floor():
    # Buy YES Over 19.5 @46 + Buy NO Over 29.5 @47 -> cost 93, 100¢ floor -> structural_floor.
    rows = [ge_row("E1", 19.5, yes_ask_c=46), ge_row("E1", 29.5, yes_ask_c=20, no_ask_c=47)]
    out = nba.find_payoff_boxes(rows)
    assert len(out) == 1
    f = out[0]
    assert f["status"] == nba.PAYOFF_STATE_DIAGNOSTIC
    assert f["cost_c"] == 93
    assert f["classification"] == "structural_floor"
    assert f["floor_authoritative"] is True
    assert f["n_legs"] == 2
    assert [leg["side"] for leg in f["legs"]] == ["buy_yes", "buy_no"]
    assert len(f["payoff_scenarios"]) == 3
    assert f["payout_floor_c"] == 100


def test_three_rungs_yield_two_adjacent_corridors():
    rows = [ge_row("E1", 19.5, yes_ask_c=46, no_ask_c=55),
            ge_row("E1", 24.5, yes_ask_c=30, no_ask_c=47),
            ge_row("E1", 29.5, yes_ask_c=20, no_ask_c=40)]
    out = nba.find_payoff_boxes(rows)
    assert len(out) == 2     # adjacent pairs only: (19.5,24.5) and (24.5,29.5)


def test_no_cross_event_pairing():
    # Two different events -> two single-rung groups -> no ladder (needs >=2 rungs) -> nothing paired.
    rows = [ge_row("E1", 19.5, yes_ask_c=46), ge_row("E2", 29.5, yes_ask_c=20, no_ask_c=47)]
    assert nba.find_payoff_boxes(rows) == []


def test_no_firm_quote_is_diagnostic_not_a_floor():
    # No firm YES ask on the broad leg -> unpriced -> diagnostic, floor not authoritative (but still emitted).
    rows = [ge_row("E1", 19.5, yes_ask_c=46, quote_quality="No quote"),
            ge_row("E1", 29.5, yes_ask_c=20, no_ask_c=47)]
    out = nba.find_payoff_boxes(rows)
    assert len(out) == 1
    assert out[0]["classification"] == "diagnostic"
    assert out[0]["floor_authoritative"] is False
    assert out[0]["cost_c"] is None


# --- schema / model declarations -----------------------------------------------------
def test_payoff_scenarios_in_schema_and_model():
    assert "payoff_scenarios" in scanner.UNIFIED_COLUMNS
    assert "payoff_classification" in scanner.UNIFIED_COLUMNS
    o = api.Opportunity(payoff_scenarios=[{"label": "x", "payout_c": 100}],
                        payoff_classification="structural_floor", floor_authoritative=True)
    assert o.payoff_scenarios[0]["payout_c"] == 100
    assert o.floor_authoritative is True


def test_bucket_of_routes_payoff_state_never_actionable():
    assert consistency.bucket_of({"status": "PAYOFF_STATE_DIAGNOSTIC"}) == "payoff_state"
    assert "payoff_state" in consistency.DASHBOARD_BUCKETS
    assert consistency.STATUS_GROUP["PAYOFF_STATE_DIAGNOSTIC"] == "Diagnostic"


# --- scanner -> store -> feed survival (audit #3) ------------------------------------
def _fetch_numeric(sport_id):
    if sport_id == "tennis":
        return pd.DataFrame([ge_row("E1", 19.5, yes_ask_c=46), ge_row("E1", 29.5, yes_ask_c=20, no_ask_c=47)])
    return pd.DataFrame()


def test_flag_off_emits_no_payoff_rows(monkeypatch):
    monkeypatch.setattr(config, "PAYOFF_ENGINE_DEMO_ENABLED", False)
    monkeypatch.delenv("PAYOFF_ENGINE_DEMO_ENABLED", raising=False)
    unified, errors = scanner.unified_opportunities(_fetch_numeric)
    assert errors == []
    assert (unified["bucket"] == "payoff_state").sum() == 0     # OFF -> zero new rows
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS     # schema still intact


def test_flag_on_survives_scanner_store_opportunities_and_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PAYOFF_ENGINE_DEMO_ENABLED", True)
    db = str(tmp_path / "snap.db")
    store._reset_init_cache()
    unified, errors = scanner.unified_opportunities(_fetch_numeric)
    assert errors == []

    pay = unified[unified["bucket"] == "payoff_state"]
    assert len(pay) == 1
    row = pay.iloc[0]
    # never Actionable; diagnostic wording; non-ranking gap.
    assert row["bucket"] != "actionable"
    assert row["exec_gap_c"] != row["exec_gap_c"] or row["exec_gap_c"] is None  # NaN/None -> never ranked
    assert str(row["tradable_now"]).startswith("No")
    assert row["status"] == "PAYOFF_STATE_DIAGNOSTIC"

    # scanner -> store -> store.latest(): payoff_scenarios survives the JSON round-trip.
    store.write_snapshot("2026-06-23 12:00:00 UTC", unified, db_path=db)
    snap = store.latest(db_path=db)
    persisted = [o for o in snap["opportunities"] if o.get("bucket") == "payoff_state"]
    assert len(persisted) == 1
    assert isinstance(persisted[0]["payoff_scenarios"], list) and len(persisted[0]["payoff_scenarios"]) == 3

    # /opportunities boundary (Opportunity, extra="ignore") keeps the field.
    o = api.Opportunity(**persisted[0])
    assert o.payoff_scenarios is not None and len(o.payoff_scenarios) == 3
    assert o.payoff_classification == "structural_floor"

    # /api/terminal/feed view also carries it (the F25 card's data source).
    built = feed.feed_from_snapshot(snap)
    fed = [r for r in built["opps"] if r.get("bucket") == "payoff_state"]
    assert len(fed) == 1
    assert isinstance(fed[0]["payoff_scenarios"], list) and len(fed[0]["payoff_scenarios"]) == 3
    assert fed[0]["payoff_classification"] == "structural_floor"


def test_converter_floors_out_of_actionable_directly():
    finding = nba.find_payoff_boxes(
        [ge_row("E1", 19.5, yes_ask_c=46), ge_row("E1", 29.5, yes_ask_c=20, no_ask_c=47)])[0]
    cfg = sports.sport_for_series("KXATPMATCH")     # any registered sport for the label
    row = scanner._to_unified_payoff_demo(finding, cfg)
    assert row["bucket"] == "payoff_state" and row["exec_gap_c"] is None
    assert row["tradable_now"].startswith("No")
    assert consistency.bucket_of(row) == "payoff_state"
