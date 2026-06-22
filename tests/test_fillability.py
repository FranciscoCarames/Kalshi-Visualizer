"""Unit tests for the visible-depth gross-edge curve (`fillability.py`) — pure, no network.

Books are hand-built ``{"yes": [[price_c, size], ...], "no": [[...]], "ok": True}`` (resting BIDS in
integer cents, exactly as ``kalshi_client.get_orderbook`` returns). Covers the book-side mapping, the
defensive sort, the N-leg water-fill, marginal-vs-cumulative edge, and every fail-closed path.
"""
from __future__ import annotations

import fillability


def book(yes=None, no=None, ok=True, fetched_ms=0):
    return {"yes": list(yes or []), "no": list(no or []), "ok": ok, "fetched_ms": fetched_ms}


def yes_leg(ticker, contract="YES"):
    return {"side": "buy_yes", "ticker": ticker, "contract": contract}


def no_leg(ticker, contract="NO"):
    return {"side": "buy_no", "ticker": ticker, "contract": contract}


# --- book-side mapping -------------------------------------------------------------

def test_buy_yes_consumes_no_bids():
    # a NO bid at 40 ⇒ a YES ask at 60.
    assert fillability.effective_levels("buy_yes", book(no=[[40, 100]])) == [[60, 100]]


def test_buy_no_consumes_yes_bids():
    # a YES bid at 52 ⇒ a NO ask at 48.
    assert fillability.effective_levels("buy_no", book(yes=[[52, 100]])) == [[48, 100]]


def test_levels_sorted_best_ask_first_regardless_of_input_order():
    # NO bids arrive ascending (best last, per Kalshi); the ladder must put the cheapest ask first.
    levels = fillability.effective_levels("buy_yes", book(no=[[40, 100], [55, 50]]))
    assert levels == [[45, 50], [60, 100]]


def test_unknown_side_and_empty_side_yield_empty():
    assert fillability.effective_levels("sell_yes", book(no=[[40, 100]])) == []
    assert fillability.effective_levels("buy_yes", book(no=[])) == []
    # malformed / non-positive-size rungs are dropped
    assert fillability.effective_levels("buy_yes", book(no=[[40, 0], ["x", 5], [55, 10]])) == [[45, 10]]


# --- 2-leg curves ------------------------------------------------------------------

def test_two_way_underround_single_segment():
    # YES asks 45 + 48 = 93 < 100 ⇒ edge 7¢, 100 units deep on each side.
    legs = [yes_leg("A"), yes_leg("B")]
    books = {"A": book(no=[[55, 100]]), "B": book(no=[[52, 100]])}
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    assert out["ok"]
    assert out["summary"]["current_top_edge_c"] == 7
    assert len(out["curve"]) == 1
    seg = out["curve"][0]
    assert (seg["from_units"], seg["to_units"], seg["marginal_edge_c"]) == (0, 100, 7)
    assert seg["cumulative_profit_c"] == 700
    assert out["summary"]["positive_visible_units"] == 100
    # edge never observed dying within visible depth ⇒ truncated / positive through depth
    assert out["summary"]["break_even_found"] is False
    assert out["summary"]["truncated"] is True


def test_two_way_overround_buy_no():
    # NO asks (100 - yes_bid): yes bids 47 & 49 ⇒ no asks 53 & 51 = 104 > 100 ⇒ negative top edge.
    legs = [no_leg("A"), no_leg("B")]
    books = {"A": book(yes=[[47, 100]]), "B": book(yes=[[49, 100]])}
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    assert out["ok"]
    assert out["summary"]["current_top_edge_c"] == -4
    # first (and only) bundle unit is already negative ⇒ edge dies immediately, no positive units
    assert out["summary"]["positive_visible_units"] == 0
    assert out["summary"]["break_even_found"] is True


def test_edge_dies_mid_walk_marginal_negative_cumulative_still_positive():
    # Leg A buy_yes: asks 40(50) then 45(100).  Leg B buy_no: asks 42(50) then 60(100).
    legs = [yes_leg("A"), no_leg("B")]
    books = {"A": book(no=[[60, 50], [55, 100]]), "B": book(yes=[[58, 50], [40, 100]])}
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    assert out["ok"]
    c = out["curve"]
    assert (c[0]["marginal_edge_c"], c[0]["to_units"]) == (18, 50)      # 100-(40+42)
    assert (c[1]["marginal_edge_c"], c[1]["to_units"]) == (-5, 150)     # 100-(45+60)
    s = out["summary"]
    assert s["break_even_found"] is True
    assert s["last_positive_marginal_unit"] == 50
    assert s["max_cumulative_profit_c"] == 900                          # 18 * 50
    assert s["positive_visible_units"] == 50


def test_unequal_leg_sizes_water_fills_by_min_block():
    legs = [yes_leg("A"), yes_leg("B")]
    books = {"A": book(no=[[55, 30], [50, 100]]), "B": book(no=[[52, 100]])}
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    # first block limited by A's 30; then A steps to a worse ask (50) while B stays at 48
    assert out["curve"][0]["to_units"] == 30 and out["curve"][0]["marginal_edge_c"] == 7
    assert out["curve"][1]["marginal_edge_c"] == 2                      # 100-(50+48)


def test_shallow_leg_exhausts_before_edge_dies_is_truncated():
    legs = [yes_leg("A"), no_leg("B")]
    books = {"A": book(no=[[55, 30]]), "B": book(yes=[[52, 100]])}     # A only 30 deep
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    assert out["ok"]
    assert out["summary"]["positive_visible_units"] == 30
    assert out["summary"]["truncated"] is True
    assert out["summary"]["weakest_leg_ticker"] == "A"


# --- N-leg ------------------------------------------------------------------------

def test_three_leg_water_fill():
    legs = [yes_leg("A"), yes_leg("B"), yes_leg("C")]
    books = {"A": book(no=[[70, 100]]), "B": book(no=[[70, 100]]), "C": book(no=[[70, 100]])}
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    # three YES asks of 30 each = 90 ⇒ edge 10
    assert out["summary"]["current_top_edge_c"] == 10
    assert out["summary"]["n_legs"] == 3


# --- fail-closed paths -------------------------------------------------------------

def test_no_payout_floor_is_unsupported():
    out = fillability.fill_curve([yes_leg("A"), yes_leg("B")], {}, payout_floor_c=None)
    assert out["ok"] is False and "floor" in out["reason"]


def test_fewer_than_two_legs_unsupported():
    out = fillability.fill_curve([yes_leg("A")], {"A": book(no=[[55, 10]])}, payout_floor_c=100)
    assert out["ok"] is False


def test_missing_book_fails_closed():
    legs = [yes_leg("A"), yes_leg("B")]
    out = fillability.fill_curve(legs, {"A": book(no=[[55, 100]]), "B": book(ok=False)},
                                 payout_floor_c=100)
    assert out["ok"] is False and out.get("truncation_reason") == "missing_book"


def test_empty_opposite_side_fails_closed_no_synthetic_ask():
    legs = [yes_leg("A"), yes_leg("B")]
    out = fillability.fill_curve(legs, {"A": book(no=[[55, 100]]), "B": book(no=[])},
                                 payout_floor_c=100)
    assert out["ok"] is False and "no visible ask" in out["reason"]


def test_crossed_book_warns_but_does_not_crash():
    legs = [yes_leg("A"), yes_leg("B")]
    books = {"A": book(no=[[100, 50]]), "B": book(no=[[52, 100]])}     # no bid 100 ⇒ yes ask 0
    out = fillability.fill_curve(legs, books, payout_floor_c=100)
    assert out["ok"] and out["warnings"]
