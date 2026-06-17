"""Real-time Stage 2C/2D — live-price overlay, per-leg coverage gating, parity, and the engine re-run.

The risk-bearing logic is the price overlay (display + executable fields stay consistent; empty side →
0.00/1.00), the per-leg coverage classifier, and the Actionable gate (a stale/uncovered leg or a NEW
live-only edge in 2C is demoted, never silently). These are unit-tested pure. `build_live_feed` is
integration-tested end-to-end against a seeded store + a stubbed live book.
"""
from __future__ import annotations

import pytest

import live_feed
import live_overlay
import store


@pytest.fixture(autouse=True)
def _clean():
    live_feed.reset()
    yield
    live_feed.reset()


def _fresh_book(yes_bid_c, yes_ask_c, *, synced=True, fresh=True, age=0.5):
    """A stub derived-book dict matching LiveBook.derived() — where `fresh` is True only when synced (a
    desynced book is never fresh), so the stub can't drift from the real invariant."""
    return {"yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_bid_c": 100 - yes_ask_c,
            "no_ask_c": 100 - yes_bid_c, "yes_bid_size": 5, "yes_ask_size": 4,
            "no_bid_size": 4, "no_ask_size": 5, "synced": synced, "age_s": age,
            "fresh": bool(fresh and synced)}


class _StubBook:
    """A LiveBook-shaped stub: ticker → derived dict (None = uncovered)."""
    def __init__(self, mapping): self._m = mapping
    def derived(self, tk): return self._m.get(tk)
    def tickers(self): return list(self._m)


# --- overlay_row_prices --------------------------------------------------------------------------------

def test_overlay_recomputes_consistent_fields():
    row = {"market_ticker": "KXT", "last_c": 50, "yes_bid_c": 10, "yes_ask_c": 20}
    out = live_overlay.overlay_row_prices(row, _fresh_book(55, 62))
    assert out["yes_bid_c"] == 55 and out["yes_ask_c"] == 62
    assert out["no_bid_c"] == 38 and out["no_ask_c"] == 45
    assert out["yes_bid_pct"] == 55.0 and out["yes_ask_pct"] == 62.0
    assert out["spread_cents"] == 7.0 and out["quote_quality"] == "OK"
    assert out["display_pct"] == 58.5            # midpoint of 55/62 (reasonable spread)
    assert out["price_source"] == "live"
    assert row["yes_bid_c"] == 10               # input not mutated (returns a copy)


def test_overlay_empty_side_is_no_quote_never_fifty():
    row = {"market_ticker": "KXT", "last_c": None}
    # empty book → yes_bid_c 0 / yes_ask_c 100
    out = live_overlay.overlay_row_prices(row, _fresh_book(0, 100))
    assert out["quote_quality"] == "No quote"
    assert out["display_pct"] is None           # no mid, no last → blank (never a fake 50)


# --- leg_coverage --------------------------------------------------------------------------------------

def _rec(*tickers, bucket="actionable"):
    """A unified record with synthesized 2-leg tickers (scanner.legs_of reads ticker_1/ticker_2 + the
    action_N_text that marks a real leg)."""
    r = {"opportunity_id": "o1", "bucket": bucket}
    if len(tickers) >= 1:
        r["ticker_1"] = tickers[0]
        r["action_1_text"] = "Buy YES"
    if len(tickers) >= 2:
        r["ticker_2"] = tickers[1]
        r["action_2_text"] = "Buy NO"
    return r


def test_leg_coverage_all_live():
    book = _StubBook({"A": _fresh_book(55, 62), "B": _fresh_book(40, 45)})
    cov = live_overlay.leg_coverage(_rec("A", "B"), book)
    assert cov["all_legs_live"] is True and cov["live_legs"] == 2 and cov["legs_total"] == 2
    assert cov["price_source"] == "live"


def test_leg_coverage_uncovered_and_stale_and_desynced():
    book = _StubBook({"A": _fresh_book(55, 62), "C": _fresh_book(40, 45, fresh=False),
                      "D": _fresh_book(40, 45, synced=False)})
    assert live_overlay.leg_coverage(_rec("A", "B"), book)["any_uncovered"] is True      # B missing
    assert live_overlay.leg_coverage(_rec("A", "C"), book)["any_stale"] is True
    assert live_overlay.leg_coverage(_rec("A", "C"), book)["all_legs_live"] is False
    d = live_overlay.leg_coverage(_rec("A", "D"), book)
    assert d["any_desynced"] is True and d["price_source"] == "mixed"


# --- gate_record ---------------------------------------------------------------------------------------

ALL_LIVE = {"all_legs_live": True, "any_uncovered": False, "any_desynced": False, "any_stale": False,
            "price_source": "live", "live_coverage": True, "live_legs": 2, "legs_total": 2,
            "price_age_s": 0.5}


def test_gate_keeps_actionable_when_2d_and_fully_live():
    rec, extra = live_overlay.gate_record(_rec("A", "B"), ALL_LIVE, rest_bucket="actionable",
                                          allow_actionability=True)
    assert rec["bucket"] == "actionable" and "live_demoted" not in extra


def test_gate_2c_keeps_rest_confirmed_demotes_new_edge():
    # 2C: a row Actionable on the last REST scan stays Actionable...
    rec, _ = live_overlay.gate_record(_rec("A", "B"), ALL_LIVE, rest_bucket="actionable",
                                      allow_actionability=False)
    assert rec["bucket"] == "actionable"
    # ...but a NEW live-only Actionable (not Actionable in REST) is demoted to review.
    rec2, extra2 = live_overlay.gate_record(_rec("A", "B"), ALL_LIVE, rest_bucket=None,
                                            allow_actionability=False)
    assert rec2["bucket"] == "review_signal" and extra2["live_demoted"] is True


def test_gate_demotes_stale_leg_even_in_2d():
    cov = {**ALL_LIVE, "all_legs_live": False, "any_stale": True, "live_coverage": False}
    rec, extra = live_overlay.gate_record(_rec("A", "B"), cov, rest_bucket="actionable",
                                          allow_actionability=True)
    assert rec["bucket"] == "review_signal" and "stale" in extra["live_block_reason"]


def test_gate_leaves_non_actionable_untouched():
    rec, _ = live_overlay.gate_record(_rec("A", "B", bucket="risk_budget"), ALL_LIVE,
                                      rest_bucket=None, allow_actionability=False)
    assert rec["bucket"] == "risk_budget"


# --- parity_compare ------------------------------------------------------------------------------------

def test_parity_compare_counts_mismatches():
    live = {"A": {"yes_bid_c": 55}, "B": {"yes_bid_c": 40}, "C": {"yes_bid_c": 10}}
    rest = {"A": {"yes_bid_c": 55}, "B": {"yes_bid_c": 47}}        # C not shared; B differs
    rep = live_overlay.parity_compare(live, rest)
    assert rep["compared"] == 2 and rep["mismatched"] == 1
    assert rep["mismatch_rate"] == 0.5
    assert rep["samples"][0]["ticker"] == "B"


# --- build_live_feed (integration: seeded store + stub book) -------------------------------------------

def _contract_row(ticker, contract, **kw):
    return {
        "player_key": kw.get("pk", "p1"), "tournament": "T1", "contract": contract,
        "category": "match", "stage": "", "opponent": "", "display_pct": 50.0,
        "quote_quality": "Tight", "stage_rank": 1, "yes_bid_c": 48, "yes_ask_c": 52,
        "yes_bid_pct": 48.0, "yes_ask_pct": 52.0, "last_c": 50, "volume": 10, "status": "active",
        "kalshi_url": "u", "market_ticker": ticker, "rules_primary": "settle X", "series": "KXATPMATCH",
        "event_ticker": "EV", "event_title": "M", "tournament_source": "competition",
        "player_key_source": "uuid", "mapping_confidence": "high", "kind": "match",
    }


def test_build_live_feed_runs_end_to_end(tmp_path):
    db = str(tmp_path / "ov.db")
    frames = [{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": [
        _contract_row("TK-A", "Beat A"), _contract_row("TK-B", "Beat B", pk="p2")]}]
    store.write_snapshot("2026-06-03 12:00:00 UTC", [], frames=frames, db_path=db)

    stub = _StubBook({"TK-A": _fresh_book(60, 64)})    # one ticker has a fresh live book
    out = live_overlay.build_live_feed(db, live_seq=7, allow_actionability=False, book=stub)
    assert out is not None
    assert out["meta"]["live_seq"] == 7
    assert out["meta"]["price_source"] == "live"
    assert out["meta"]["live_actionability"] is False
    assert isinstance(out["opps"], list)               # pipeline ran; rows (if any) carry live fields


def test_build_live_feed_none_without_snapshot(tmp_path):
    db = str(tmp_path / "empty.db")
    assert live_overlay.build_live_feed(db, book=_StubBook({})) is None
