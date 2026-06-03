"""Unit tests for the 2-outcome dutch-book / MECE detector (no network).

Covers the 2-outcome detector: tennis matches + NBA/WNBA playoff series + per-game (m1.1), both
directions (underround / overround), executable-vs-blocked precedence, and false-positive guards.
"""
from __future__ import annotations

import pandas as pd

import dutchbook

BLOCKERS_size = "0 contracts are available"  # substring of glossary BLOCKERS["size_missing"]
NAN = float("nan")


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


# --- Finding fields + dashboard routing (task #4 integration) -----------------------
def test_finding_carries_player_keys_and_resolve_time():
    a = market("Alcaraz", player_key="k_alc", yes_ask_c=45)
    a["time_value"] = "2026-06-05T10:00:00Z"
    b = market("Sinner", player_key="k_sin", yes_ask_c=48)
    b["time_value"] = "2026-06-04T10:00:00Z"
    f = dutchbook.find_dutch_books([a, b])[0]
    assert f["player_key_a"] == "k_alc" and f["player_key_b"] == "k_sin"
    assert f["resolve_time"] == "2026-06-04T10:00:00Z"   # earliest leg


def test_actionable_dutch_book_routes_via_bucket_of():
    import consistency
    a = market("A", player_key="a", yes_ask_c=45)
    b = market("B", player_key="b", yes_ask_c=48)
    f = dutchbook.find_dutch_books([a, b])[0]
    # The shared dashboard router recognizes the dutch-book status (string contract held in sync).
    assert consistency.STATUS_GROUP[dutchbook.EXECUTABLE_DUTCH_BOOK] == "Broken"
    assert consistency.bucket_of(f) == "actionable"


def test_blocked_dutch_book_routes_to_blocked_bucket():
    import consistency
    a = market("A", player_key="a", yes_ask_c=45, yes_ask_size=0)   # no size -> not tradable
    b = market("B", player_key="b", yes_ask_c=48)
    f = dutchbook.find_dutch_books([a, b])[0]
    assert f["tradable_now"] == "No"
    assert consistency.bucket_of(f) == "blocked"


# --- Sport-agnostic: NBA / WNBA head-to-head playoff series (task #5) ----------------
def test_fires_on_nba_playoff_series():
    # KXNBASERIES is NBA's head-to-head family (kind 'match'): one team wins the series, no draw.
    a = market("Celtics", series="KXNBASERIES", event="KXNBASERIES-26BOSIND",
               player_key="bos", yes_ask_c=47)
    b = market("Pacers", series="KXNBASERIES", event="KXNBASERIES-26BOSIND",
               player_key="ind", yes_ask_c=50)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    assert out[0]["direction"] == "underround" and out[0]["exec_gap_c"] == 3


def test_fires_on_wnba_playoff_series():
    a = market("Aces", series="KXWNBASERIES", event="KXWNBASERIES-26LVNY", player_key="lv", yes_ask_c=40)
    b = market("Liberty", series="KXWNBASERIES", event="KXWNBASERIES-26LVNY", player_key="ny", yes_ask_c=52)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1 and out[0]["exec_gap_c"] == 8


def test_fires_on_nba_per_game():
    # m1.1: per-game (kind 'game') is a 2-outcome MECE event too -> now in scope. Underround 45+48=93.
    g1 = market("Celtics", series="KXNBAGAME", event="KXNBAGAME-26JUN03", player_key="bos", yes_ask_c=45)
    g1["kind"] = "game"
    g2 = market("Pacers", series="KXNBAGAME", event="KXNBAGAME-26JUN03", player_key="ind", yes_ask_c=48)
    g2["kind"] = "game"
    out = dutchbook.find_dutch_books([g1, g2])
    assert len(out) == 1 and out[0]["direction"] == "underround" and out[0]["exec_gap_c"] == 7


def test_fires_on_wnba_per_game():
    g1 = market("Aces", series="KXWNBAGAME", event="KXWNBAGAME-26JUN03", player_key="lv", yes_ask_c=44)
    g1["kind"] = "game"
    g2 = market("Liberty", series="KXWNBAGAME", event="KXWNBAGAME-26JUN03", player_key="ny", yes_ask_c=50)
    g2["kind"] = "game"
    out = dutchbook.find_dutch_books([g1, g2])
    assert len(out) == 1 and out[0]["exec_gap_c"] == 6


def test_ignores_props_and_three_outcome_game():
    # A non-two-way prop/other row is ignored regardless of price.
    p = market("Award", series="KXNBAMVP", event="KXNBAMVP-26", player_key="x", yes_ask_c=10)
    p["kind"] = "other"
    assert dutchbook.find_dutch_books([p]) == []
    # A draw-prone (3-outcome) game lists 3 markets -> rejected by the exactly-2 MECE guard.
    rows = []
    for n, k in (("Home", "h"), ("Away", "a"), ("Draw", "d")):
        r = market(n, series="KXSOCCERGAME", event="KXSOCCERGAME-1", player_key=k, yes_ask_c=30)
        r["kind"] = "game"
        rows.append(r)
    assert dutchbook.find_dutch_books(rows) == []


# --- Robustness: the production DataFrame->records path (NaN, not None) -------------
def test_pandas_records_roundtrip_fires():
    # app.py feeds dutchbook.find_dutch_books(df.to_dict("records")) — exercise that exact path.
    a = market("A", player_key="a", yes_bid_c=43, yes_ask_c=45)
    b = market("B", player_key="b", yes_bid_c=46, yes_ask_c=48)
    rows = pd.DataFrame([a, b]).to_dict("records")
    out = dutchbook.find_dutch_books(rows)
    assert len(out) == 1 and out[0]["exec_gap_c"] == 7 and out[0]["tradable_now"] == "Yes"


def test_nan_sizes_block_tradability():
    # Missing sizes arrive as float NaN through pandas; the cross still shows but isn't tradable.
    a = market("A", player_key="a", yes_bid_c=43, yes_ask_c=45, yes_ask_size=NAN)
    b = market("B", player_key="b", yes_bid_c=46, yes_ask_c=48, yes_ask_size=NAN)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    assert out[0]["exec_gap_c"] == 7
    assert out[0]["tradable_now"] == "No" and out[0]["exec_min_size"] is None


def test_nan_price_leg_is_not_firm():
    # A NaN ask (with an otherwise-fine quote) is not a firm price -> no underround on that pair.
    a = market("A", player_key="a", yes_bid_c=10, yes_ask_c=NAN, no_ask_c=90)
    b = market("B", player_key="b", yes_bid_c=46, yes_ask_c=48, no_ask_c=54)
    # underround impossible (A ask NaN); overround no_ask 90+54=144 > 100 -> nothing.
    assert dutchbook.find_dutch_books([a, b]) == []


# --- Robustness: boundary + one-sided book ------------------------------------------
def test_exact_100_sum_is_not_a_dutch_book():
    # Sum exactly 100 is fair, not an edge (gap must be strictly > 0).
    a = market("A", player_key="a", yes_bid_c=49, yes_ask_c=50, no_ask_c=51)
    b = market("B", player_key="b", yes_bid_c=49, yes_ask_c=50, no_ask_c=51)
    assert dutchbook.find_dutch_books([a, b]) == []   # ask 50+50=100; no_ask 51+51=102


def test_one_sided_book_with_present_ask_can_underround():
    # 'One-sided' is NOT excluded (only No quote / Crossed are): a present ask is a real, hittable order.
    a = market("A", player_key="a", yes_bid_c=None, yes_ask_c=45, quality="One-sided")
    b = market("B", player_key="b", yes_bid_c=46, yes_ask_c=48, quality="Tight")
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1 and out[0]["direction"] == "underround" and out[0]["exec_gap_c"] == 7


def test_resolve_time_none_when_legs_have_no_time():
    a = market("A", player_key="a", yes_ask_c=45)
    b = market("B", player_key="b", yes_ask_c=48)
    assert dutchbook.find_dutch_books([a, b])[0]["resolve_time"] is None


# --- m1.1 breadth: per-game eligibility correctness & isolation ---------------------
def test_unknown_series_with_game_kind_is_ignored():
    # A 'game'-kind row from an UNRECOGNIZED series must still be excluded (a foreign ticker
    # never enters the detector) — the game clause must not bypass the unknown-sport guard.
    a = market("A", series="KXNOTASPORT", event="X-1", player_key="a", yes_ask_c=45)
    a["kind"] = "game"
    b = market("B", series="KXNOTASPORT", event="X-1", player_key="b", yes_ask_c=48)
    b["kind"] = "game"
    assert dutchbook.find_dutch_books([a, b]) == []


def test_overround_on_per_game():
    g1 = market("Celtics", series="KXNBAGAME", event="KXNBAGAME-1", player_key="bos",
                yes_bid_c=55, yes_ask_c=57, no_ask_c=45)
    g1["kind"] = "game"
    g2 = market("Pacers", series="KXNBAGAME", event="KXNBAGAME-1", player_key="ind",
                yes_bid_c=52, yes_ask_c=54, no_ask_c=48)
    g2["kind"] = "game"
    out = dutchbook.find_dutch_books([g1, g2])
    assert len(out) == 1 and out[0]["direction"] == "overround" and out[0]["exec_gap_c"] == 7  # 100-(45+48)


def test_mixed_match_and_game_in_one_df_both_fire():
    # A tennis match event and an NBA game event in the same frame -> two independent findings.
    t1 = market("Alcaraz", series="KXATPMATCH", event="KXATPMATCH-1", player_key="alc", yes_ask_c=45)
    t2 = market("Sinner", series="KXATPMATCH", event="KXATPMATCH-1", player_key="sin", yes_ask_c=48)
    g1 = market("Celtics", series="KXNBAGAME", event="KXNBAGAME-1", player_key="bos", yes_ask_c=40)
    g1["kind"] = "game"
    g2 = market("Pacers", series="KXNBAGAME", event="KXNBAGAME-1", player_key="ind", yes_ask_c=52)
    g2["kind"] = "game"
    out = dutchbook.find_dutch_books([t1, t2, g1, g2])
    assert {f["event_ticker"] for f in out} == {"KXATPMATCH-1", "KXNBAGAME-1"}
    assert sorted(f["exec_gap_c"] for f in out) == [7, 8]   # tennis 7, nba game 8


def _kinded(player, *, kind, **kw):
    r = market(player, **kw)
    r["kind"] = kind
    return r


def test_cross_sport_mix_only_two_way_events_fire():
    rows = []
    # tennis match (fires) + NBA game (fires)
    rows += [market("A", series="KXATPMATCH", event="M1", player_key="a", yes_ask_c=45),
             market("B", series="KXATPMATCH", event="M1", player_key="b", yes_ask_c=48)]
    rows += [_kinded("C", kind="game", series="KXNBAGAME", event="G1", player_key="c", yes_ask_c=40),
             _kinded("D", kind="game", series="KXNBAGAME", event="G1", player_key="d", yes_ask_c=50)]
    # 3-market winner field (excluded: not 2 markets)
    rows += [_kinded(n, kind="winner", series="KXFOMEN", event="W1", player_key=k, yes_ask_c=20)
             for n, k in (("E", "e"), ("F", "f"), ("G", "g"))]
    # prop (excluded) + unknown series (excluded)
    rows += [_kinded("H", kind="other", series="KXNBAMVP", event="P1", player_key="h", yes_ask_c=10),
             market("I", series="KXZZZ", event="U1", player_key="i", yes_ask_c=10)]
    out = dutchbook.find_dutch_books(rows)
    assert {f["event_ticker"] for f in out} == {"M1", "G1"}


# --- Two events at once: strongest edge first ---------------------------------------
def test_multiple_events_sorted_by_gap_desc():
    e1 = [market("A", event="EV1", player_key="a", yes_ask_c=45),
          market("B", event="EV1", player_key="b", yes_ask_c=48)]          # gap 7
    e2 = [market("C", event="EV2", player_key="c", yes_ask_c=40),
          market("D", event="EV2", player_key="d", yes_ask_c=50)]          # gap 10
    out = dutchbook.find_dutch_books(e1 + e2)
    assert [f["event_ticker"] for f in out] == ["EV2", "EV1"]
    assert [f["exec_gap_c"] for f in out] == [10, 7]


# --- Stage 1: opportunity schema (relationship_type / opportunity_id / bucket / blocked_reason) ---
def test_finding_is_stamped_with_relationship_type_and_stable_order_independent_id():
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    f = dutchbook.find_dutch_books([a, b])[0]
    assert f["relationship_type"] == "dutch_book"
    assert isinstance(f["opportunity_id"], str) and len(f["opportunity_id"]) == 16
    # Deterministic and leg-order-independent (recipe sorts the participant keys).
    swapped = dutchbook.find_dutch_books([b, a])[0]
    assert swapped["opportunity_id"] == f["opportunity_id"]


def test_actionable_finding_has_actionable_bucket_and_empty_blocked_reason():
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    f = dutchbook.find_dutch_books([a, b])[0]
    assert f["tradable_now"] == "Yes"
    assert f["bucket"] == "actionable"
    assert f["blocked_reason"] == ""             # non-empty IFF blocked


def test_blocked_finding_has_blocked_bucket_and_nonempty_blocked_reason():
    # Zero size -> still a flagged dutch book, but not tradable -> blocked, with a reason.
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45, yes_ask_size=0)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    f = dutchbook.find_dutch_books([a, b])[0]
    assert f["tradable_now"] == "No"
    assert f["bucket"] == "blocked"
    assert f["blocked_reason"]                    # non-empty
    assert f["blocked_reason"] == f["blockers"]   # sourced from the same plain-English text


def test_finding_carries_market_status():
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    assert dutchbook.find_dutch_books([a, b])[0]["market_status"] == "active"
    # an inactive leg flips the normalized market_status (used by the lifecycle diff)
    a_in = market("Alcaraz", yes_bid_c=43, yes_ask_c=45, status="finalized")
    assert dutchbook.find_dutch_books([a_in, b])[0]["market_status"] == "inactive"
