"""Unit tests for the 2-outcome dutch-book / MECE detector (no network).

Scope mirrors the m1 milestone: tennis head-to-head match events only, both directions
(underround / overround), with the executable-vs-blocked precedence and the false-positive guards.
"""
from __future__ import annotations

import dutchbook

BLOCKERS_size = "0 contracts are available"  # substring of glossary BLOCKERS["size_missing"]


def market(player, *, series="KXATPMATCH", event="KXATPMATCH-26JUN03AB", player_key=None,
           yes_bid_c=None, yes_ask_c=None, no_ask_c=None,
           yes_bid_size=100, yes_ask_size=100, quality="Tight", status="active"):
    """Minimal per-player match-market row as produced by data.build_contracts."""
    return {
        "series": series,
        "event_ticker": event,
        "kind": "match",                       # tennis match family
        "player": player,
        "player_key": player_key or player.lower(),
        "contract": f"Beat opponent ({player})",
        "tournament": "French Open",
        "tour": "ATP",
        "yes_bid_c": yes_bid_c,
        "yes_ask_c": yes_ask_c,
        "no_ask_c": no_ask_c,
        "yes_bid_size": yes_bid_size,
        "yes_ask_size": yes_ask_size,
        "quote_quality": quality,
        "status": status,
        "market_ticker": f"{event}-{player[:3].upper()}",
        "kalshi_url": "https://kalshi.com/markets/kxatpmatch",
        "event_title": "A vs B",
    }


# --- Underround (Buy YES both) -------------------------------------------------------
def test_underround_yes_sum_below_100_is_executable():
    # yes_ask 45 + 48 = 93 < 100 -> 7c locked per unit, both YES buys.
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK
    assert f["direction"] == "underround"
    assert f["cost_c"] == 93 and f["exec_gap_c"] == 7
    assert f["action_1_side"] == "buy_yes" and f["action_2_side"] == "buy_yes"
    assert f["action_1_price_c"] == 45 and f["action_2_price_c"] == 48
    assert f["tradable_now"] == "Yes"
    assert f["exec_min_size"] == 100
    assert f["exec_max_profit_dollars"] == round(7 * 100 / 100, 2)  # 7.0
    assert f["blockers"] == ""


# --- Overround (Buy NO both) ---------------------------------------------------------
def test_overround_no_sum_below_100_is_executable():
    # no_ask 46 + 49 = 95 < 100 -> 5c locked per unit, both NO buys.
    # (Equivalently yes_bid 54 + 51 = 105 > 100.)
    a = market("Sabalenka", yes_bid_c=54, yes_ask_c=56, no_ask_c=46)
    b = market("Shnaider", yes_bid_c=51, yes_ask_c=53, no_ask_c=49)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    f = out[0]
    assert f["direction"] == "overround"
    assert f["cost_c"] == 95 and f["exec_gap_c"] == 5
    assert f["action_1_side"] == "buy_no" and f["action_2_side"] == "buy_no"
    assert f["action_1_price_c"] == 46 and f["action_2_price_c"] == 49
    assert f["tradable_now"] == "Yes"


def test_overround_falls_back_to_100_minus_yes_bid_when_no_ask_absent():
    # no_ask_c missing -> use 100 - yes_bid_c: (100-54)+(100-51) = 46+49 = 95 < 100.
    a = market("Sabalenka", yes_bid_c=54, yes_ask_c=56, no_ask_c=None)
    b = market("Shnaider", yes_bid_c=51, yes_ask_c=53, no_ask_c=None)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    assert out[0]["direction"] == "overround" and out[0]["exec_gap_c"] == 5


# --- No dutch book ------------------------------------------------------------------
def test_no_dutch_book_when_sums_straddle_100():
    # yes_ask 52 + 50 = 102 (no underround); yes_bid 50 + 48 = 98 (no overround).
    a = market("A", yes_bid_c=50, yes_ask_c=52, no_ask_c=50)
    b = market("B", yes_bid_c=48, yes_ask_c=50, no_ask_c=52)
    assert dutchbook.find_dutch_books([a, b]) == []


# --- Blocked: cross exists but no size ----------------------------------------------
def test_underround_with_zero_size_is_flagged_but_not_tradable():
    a = market("A", yes_bid_c=43, yes_ask_c=45, yes_ask_size=0)
    b = market("B", yes_bid_c=46, yes_ask_c=48, yes_ask_size=100)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK   # still flagged
    assert f["exec_gap_c"] == 7
    assert f["tradable_now"] == "No"
    assert f["exec_min_size"] is None
    assert f["exec_max_profit_dollars"] is None
    assert BLOCKERS_size in f["blockers"]


# --- Inactive leg blocks tradability ------------------------------------------------
def test_inactive_leg_blocks_tradability():
    a = market("A", yes_bid_c=43, yes_ask_c=45, status="finalized")
    b = market("B", yes_bid_c=46, yes_ask_c=48)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    assert out[0]["tradable_now"] == "No"
    assert "not open for trading" in out[0]["blockers"]


# --- False-positive guards ----------------------------------------------------------
def test_no_quote_leg_yields_no_underround():
    # An empty (0/1) book on A -> 'No quote' -> no firm ask, so the underround can't be priced.
    a = market("A", yes_bid_c=None, yes_ask_c=None, quality="No quote")
    b = market("B", yes_bid_c=46, yes_ask_c=48)
    assert dutchbook.find_dutch_books([a, b]) == []


def test_crossed_book_is_excluded():
    a = market("A", yes_bid_c=60, yes_ask_c=45, quality="Crossed")  # ask < bid
    b = market("B", yes_bid_c=46, yes_ask_c=48)
    assert dutchbook.find_dutch_books([a, b]) == []


def test_single_market_event_is_skipped():
    a = market("A", yes_bid_c=43, yes_ask_c=45)
    assert dutchbook.find_dutch_books([a]) == []


def test_three_market_event_is_out_of_scope():
    ev = "KXATPMATCH-26JUN03ABC"
    rows = [market(n, event=ev, yes_bid_c=20, yes_ask_c=22) for n in ("A", "B", "C")]
    assert dutchbook.find_dutch_books(rows) == []


def test_non_match_rows_are_ignored():
    # Winner-family rows (kind != match) never enter the detector, even if priced to a 'sum'.
    a = market("A", yes_ask_c=45)
    a["kind"] = "winner"
    b = market("B", yes_ask_c=48)
    b["kind"] = "winner"
    assert dutchbook.find_dutch_books([a, b]) == []


def test_unknown_series_row_is_ignored():
    # A foreign ticker (UNKNOWN sport, empty match_family) must not be treated as a match.
    a = market("A", series="KXNOTASPORT", yes_ask_c=45)
    b = market("B", series="KXNOTASPORT", yes_ask_c=48)
    assert dutchbook.find_dutch_books([a, b]) == []


# --- Two events at once: strongest edge first ---------------------------------------
def test_multiple_events_sorted_by_gap_desc():
    e1 = [market("A", event="EV1", player_key="a", yes_ask_c=45),
          market("B", event="EV1", player_key="b", yes_ask_c=48)]          # gap 7
    e2 = [market("C", event="EV2", player_key="c", yes_ask_c=40),
          market("D", event="EV2", player_key="d", yes_ask_c=50)]          # gap 10
    out = dutchbook.find_dutch_books(e1 + e2)
    assert [f["event_ticker"] for f in out] == ["EV2", "EV1"]
    assert [f["exec_gap_c"] for f in out] == [10, 7]
