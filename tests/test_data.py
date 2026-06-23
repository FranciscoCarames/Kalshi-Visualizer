"""Unit tests for the pure data layer (no network)."""
from __future__ import annotations

import pytest

import config
import data
import kalshi_client
import numeric_ladder


# --- AUDIT-007: pagination cap surfaces truncation instead of silent partial data -----
def test_pagination_cap_raises_on_remaining_cursor(monkeypatch):
    # _get always returns a fresh cursor -> never terminates -> cap must raise, not truncate.
    monkeypatch.setattr(kalshi_client, "_get",
                        lambda path, params: {"events": [{"i": 1}], "cursor": "more"})
    with pytest.raises(kalshi_client.KalshiError):
        kalshi_client.get_paginated("/events", {}, "events")


def test_pagination_stops_cleanly_when_cursor_empties(monkeypatch):
    pages = [{"events": [{"i": 1}], "cursor": "c"}, {"events": [{"i": 2}], "cursor": None}]
    monkeypatch.setattr(kalshi_client, "_get", lambda path, params: pages.pop(0))
    assert kalshi_client.get_paginated("/events", {}, "events") == [{"i": 1}, {"i": 2}]


# --- AUDIT-008: a present non-FO competition is disqualifying (no date-window guess) ---
def _evt(competition, occurrence):
    return {
        "product_metadata": {"competition": competition},
        "title": "Some vs Body", "sub_title": "",
        "markets": [{"title": "Will X win the match?", "rules_primary": "",
                     "occurrence_datetime": occurrence, "close_time": occurrence}],
    }


def test_non_fo_competition_in_window_is_rejected():
    # In-window date, but the event names a different tournament -> not French Open.
    assert data.is_french_open_event(_evt("Stuttgart Open", "2026-06-02T12:00:00Z")) is False


def test_fo_competition_is_accepted():
    assert data.is_french_open_event(_evt("French Open Women Singles", "2026-06-02T12:00:00Z")) is True


def test_date_window_fallback_only_when_no_competition():
    # No competition info at all + in-window -> last-resort fallback still includes it.
    assert data.is_french_open_event(_evt("", "2026-06-02T12:00:00Z")) is True
    # No competition + out-of-window -> excluded.
    assert data.is_french_open_event(_evt("", "2026-09-02T12:00:00Z")) is False


# --- AUDIT-004: every configured FO winner ticker maps to the intended tour ----------
def test_winner_ticker_tour_map_all_variants():
    women = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}
    for t in config.FO_WINNER_TICKERS:
        expected = "WTA" if t in women else "ATP"
        assert data.tour_of(t) == expected, f"{t} -> {data.tour_of(t)}, expected {expected}"
    # the specific variant that the old substring check misclassified:
    assert data.tour_of("KXFOPENWMENSINGLE") == "WTA"


# --- AUDIT-005: crossed books (ask < bid) are malformed, never Tight or a midpoint ----
def test_crossed_book_is_rejected():
    assert data.quote_quality(0.60, 0.40) == "Crossed"      # not "Tight"
    assert data.yes_mid(0.60, 0.40) is None
    assert data.spread(0.60, 0.40) is None
    assert data.display_prob(0.60, 0.40, None) is None       # no midpoint from a crossed book
    assert data.display_cents(60, 40, None) is None
    # a normal book is unaffected
    assert data.quote_quality(0.34, 0.36) == "Tight"


# --- parsing -------------------------------------------------------------------------
def test_to_float_parses_and_guards():
    assert data.to_float("0.6500") == 0.65
    assert data.to_float("15919.84") == 15919.84
    assert data.to_float("") is None      # empty != 0.0
    assert data.to_float(None) is None
    assert data.to_float("abc") is None


def test_to_cents_is_exact_integer():
    assert data.to_cents("0.37") == 37
    assert data.to_cents("0.6500") == 65
    assert data.to_cents("1") == 100
    assert data.to_cents("0.00") == 0
    assert data.to_cents("") is None
    assert data.to_cents(None) is None
    assert data.to_cents("abc") is None


# --- quote quality / mids / spread ---------------------------------------------------
def test_quote_quality_buckets():
    assert data.quote_quality(None, None) == "No quote"
    assert data.quote_quality(0.0, 1.0) == "No quote"        # empty 0/1 book
    assert data.quote_quality(0.40, None) == "One-sided"
    assert data.quote_quality(0.34, 0.36) == "Tight"          # 2c
    assert data.quote_quality(0.30, 0.40) == "OK"             # 10c
    assert data.quote_quality(0.20, 0.40) == "Wide"           # 20c
    assert data.quote_quality(0.10, 0.60) == "Very wide"      # 50c


def test_yes_mid_and_spread_handle_empty_book():
    assert data.yes_mid(0.34, 0.36) == 0.35
    assert data.yes_mid(0.0, 1.0) is None
    assert data.yes_mid(None, 0.5) is None
    assert round(data.spread(0.34, 0.38), 2) == 0.04
    assert data.spread(0.0, 1.0) is None


def test_display_prob_midpoint_else_last_else_blank():
    # reasonable spread -> midpoint
    assert data.display_prob(0.19, 0.35, 0.92) == 0.27
    # empty book -> falls back to last
    assert data.display_prob(0.0, 1.0, 0.01) == 0.01
    # nothing available -> blank
    assert data.display_prob(None, None, None) is None


def test_display_cents_matches_prob_logic():
    assert data.display_cents(19, 35, 92) == 27   # mid, reasonable spread
    assert data.display_cents(0, 100, 1) == 1     # empty book -> last
    assert data.display_cents(None, None, None) is None


# --- classification ------------------------------------------------------------------
def test_classify_kind_order_and_values():
    assert data.classify_kind("KXFOMEN") == "winner"
    assert data.classify_kind("KXFOWOMEN") == "winner"
    assert data.classify_kind("KXATPADVANCE") == "advance"
    assert data.classify_kind("KXATPEXACTMATCH") == "exact_score"   # before MATCH
    assert data.classify_kind("KXWTASETWINNER") == "set_winner"
    assert data.classify_kind("KXATPMATCH") == "match"
    assert data.classify_kind("KXWTAGRANDSLAM") == "grand_slam"
    assert data.classify_kind("KXSOMETHINGELSE") == "other"


def test_tour_of():
    assert data.tour_of("KXWTAMATCH") == "WTA"
    assert data.tour_of("KXFOWOMEN") == "WTA"
    assert data.tour_of("KXATPMATCH") == "ATP"
    assert data.tour_of("KXFOMEN") == "ATP"


def test_extract_round_word_boundaries():
    assert data._extract_round("Will X win the QF: Quarterfinal match?") == "Quarterfinal"
    assert data._extract_round("Will X qualify for Semifinals ...") == "Semifinal"
    assert data._extract_round("Will X qualify for Final ...") == "Final"
    assert data._extract_round("... Round of 16 ...") == "Round of 16"
    assert data._extract_round("no round mentioned here") == ""


def test_mapping_confidence_levels():
    conf, reason = data._mapping_confidence("uuid-123", "Sorana Cirstea")
    assert conf == "high" and "uuid-123" in reason
    conf, reason = data._mapping_confidence(None, "Sorana Cirstea")
    assert conf == "low"
    conf, _ = data._mapping_confidence(None, "")
    assert conf == "none"


# --- build_contracts end to end (synthetic FO event, no network) ---------------------
def _fo_match_event():
    """A minimal French Open match event with two player-side markets."""
    def market(ticker, player, uuid, bid, ask):
        return {
            "ticker": ticker, "yes_sub_title": player,
            "custom_strike": {"tennis_competitor": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
            "volume_fp": "1000", "open_interest_fp": "500", "status": "active",
            "title": f"Will {player} win the A vs B: Quarterfinal match?",
            "occurrence_datetime": "2026-06-02T12:00:00Z",
            "close_time": "2026-06-16T09:00:00Z",
        }
    return {
        "event_ticker": "KXWTAMATCH-26JUN02ANDCIR",
        "title": "Andreeva vs Cirstea",
        "product_metadata": {"competition": "French Open Women Singles"},
        "markets": [
            market("KXWTAMATCH-26JUN02ANDCIR-AND", "Mirra Andreeva", "uuid-and", "0.62", "0.63"),
            market("KXWTAMATCH-26JUN02ANDCIR-CIR", "Sorana Cirstea", "uuid-cir", "0.37", "0.38"),
        ],
    }


def test_build_contracts_typing_and_mapping():
    rows = data.build_contracts("KXWTAMATCH", [_fo_match_event()])
    assert len(rows) == 2
    for r in rows:
        assert r["kind"] == "match"
        assert r["category"] == "Match result"
        assert r["mapping_confidence"] == "high"          # competitor UUID present
        assert r["mapping_reason"]
        assert r["tour"] == "WTA"
        assert r["yes_bid_c"] is not None and r["yes_ask_c"] is not None
    cir = next(r for r in rows if r["player"] == "Sorana Cirstea")
    assert cir["opponent"] == "Mirra Andreeva"            # opponent from sibling market
    assert cir["stage"] == "Quarterfinal"
    assert cir["display_pct"] == 37.5                     # midpoint of 0.37/0.38


# --- v1.2: clean, user-facing display names ------------------------------------------
def test_display_name_prefers_source_verbatim():
    # A clean source name (accents, real casing, lowercase particles) is shown as-is.
    row = {"player_key": "uuid-x", "player_name_raw": "Stéphane de Robert"}
    assert data.display_player_name(row) == "Stéphane de Robert"


def test_display_name_alias_overrides_source(monkeypatch):
    monkeypatch.setattr(data, "NAME_ALIASES", {"uuid-x": "Official Name"})
    row = {"player_key": "uuid-x", "player_name_raw": "drifted source name"}
    assert data.display_player_name(row) == "Official Name"


def test_display_name_titleizes_bare_key():
    row = {"player_key": "aryna_sabalenka", "player_name_raw": "aryna_sabalenka"}
    assert data.display_player_name(row) == "Aryna Sabalenka"


def test_build_contracts_exposes_internal_identifiers():
    rows = data.build_contracts("KXWTAMATCH", [_fo_match_event()])
    cir = next(r for r in rows if r["player"] == "Sorana Cirstea")
    assert cir["player"] == "Sorana Cirstea"              # clean user-facing name
    assert cir["player_key"] == "uuid-cir"
    assert cir["player_key_source"] == "competitor_uuid"
    assert cir["player_name_raw"] == "Sorana Cirstea"     # raw source name kept for debug
    assert cir["player_name_normalized"] == "sorana cirstea"
    assert cir["competitor_uuid"] == "uuid-cir"


# --- v1.3: real deep links + NO-side prices ------------------------------------------
def test_slugify_matches_kalshi_series_slug():
    assert data._slugify("French Open Women's") == "french-open-womens"
    assert data._slugify("French Open Men's") == "french-open-mens"
    assert data._slugify("ATP Stage Qualifiers") == "atp-stage-qualifiers"
    assert data._slugify("") == ""


def test_kalshi_market_url_deep_link_and_fallback():
    # Verified live format: /markets/<series_lower>/<slug>/<event_lower>
    assert data.kalshi_market_url("KXFOWOMEN", "French Open Women's", "KXFOWOMEN-26") == \
        "https://kalshi.com/markets/kxfowomen/french-open-womens/kxfowomen-26"
    # No title -> can't build the slug -> fall back to the always-resolving series page.
    assert data.kalshi_market_url("KXFOWOMEN", "", "KXFOWOMEN-26") == \
        "https://kalshi.com/markets/kxfowomen"
    # No event ticker -> series page too.
    assert data.kalshi_market_url("KXFOWOMEN", "French Open Women's", "") == \
        "https://kalshi.com/markets/kxfowomen"


def _fo_winner_event_with_no_prices():
    return {
        "event_ticker": "KXFOWOMEN-26",
        "title": "Women's French Open Winner",
        "product_metadata": {"competition": "French Open Women Singles"},
        "markets": [{
            "ticker": "KXFOWOMEN-26-SAB", "yes_sub_title": "Aryna Sabalenka",
            "custom_strike": {"tennis_competitor": "uuid-sab"},
            "yes_bid_dollars": "0.34", "yes_ask_dollars": "0.36", "last_price_dollars": "0.35",
            "no_bid_dollars": "0.64", "no_ask_dollars": "0.66",
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
            "volume_fp": "10", "open_interest_fp": "5", "status": "active",
            "title": "Will Aryna Sabalenka win the KXFOWOMEN-26?",
            "close_time": "2026-06-08T09:00:00Z",
        }],
    }


def test_build_contracts_parses_no_side_prices_and_deep_link():
    rows = data.build_contracts("KXFOWOMEN", [_fo_winner_event_with_no_prices()],
                                series_title="French Open Women's")
    assert len(rows) == 1
    r = rows[0]
    # NO-side prices are read from the API (no_ask = 1 - yes_bid on Kalshi).
    assert r["no_bid_c"] == 64 and r["no_ask_c"] == 66
    assert r["no_bid_pct"] == 64.0 and r["no_ask_pct"] == 66.0
    assert r["raw_no_ask"] == "0.66"
    # Deep link built from the series title + event ticker.
    assert r["kalshi_url"] == "https://kalshi.com/markets/kxfowomen/french-open-womens/kxfowomen-26"


def test_build_contracts_url_falls_back_without_title():
    rows = data.build_contracts("KXFOWOMEN", [_fo_winner_event_with_no_prices()])  # no series_title
    assert rows[0]["kalshi_url"] == "https://kalshi.com/markets/kxfowomen"


def test_link_audit_maps_url_to_identifiers():
    rows = data.build_contracts("KXFOWOMEN", [_fo_winner_event_with_no_prices()],
                                series_title="French Open Women's")
    audit = data.link_audit(rows)
    assert len(audit) == 1
    entry = audit[0]
    assert entry["series"] == "KXFOWOMEN"
    assert entry["event_ticker"] == "KXFOWOMEN-26"
    assert entry["contracts"] == 1
    assert "kxfowomen-26" in entry["url"]


def test_build_contracts_includes_all_tennis_and_stamps_tournament():
    # Generalized: a non-French-Open tennis event is NO LONGER dropped — it's included and stamped
    # with its own tournament (so its ladder never mixes with another tournament's).
    ev = _fo_match_event()
    ev["product_metadata"]["competition"] = "Wimbledon Women Singles"
    ev["title"] = "Andreeva vs Cirstea"
    for m in ev["markets"]:
        m["title"] = "Will X win the match?"
    rows = data.build_contracts("KXWTAMATCH", [ev])
    assert len(rows) == 2
    assert all(r["tournament"] == "Wimbledon" for r in rows)
    assert all(r["tournament_source"] == "competition" for r in rows)


# --- v1.4: tournament derivation (generalization grouping key) -----------------------
def test_tournament_of_sources_and_never_empty():
    # 1) cleaned competition (gender/discipline stripped)
    assert data.tournament_of("French Open Men Singles", "KXATPMATCH", "E1", "t") == ("French Open", "competition")
    assert data.tournament_of("French Open Women Singles", "KXWTAADVANCE", "E2", "t")[0] == "French Open"
    # 2) winner ticker when competition absent (winner events often lack it)
    assert data.tournament_of("", "KXFOWOMEN", "KXFOWOMEN-26", "x") == ("French Open", "winner_ticker")
    # 3) keyword from title
    assert data.tournament_of("", "KXATPMATCH", "E3", "Wimbledon — R1") == ("Wimbledon", "title_keyword")
    # 4) fallback is never empty and is stable/unique
    key, src = data.tournament_of("", "KXATPMATCH", "KXATPMATCH-99XYZ", "")
    assert src == "fallback" and key and "KXATPMATCH-99XYZ" in key
    # fully empty inputs still yield a non-empty key
    assert data.tournament_of("", "", "", "")[0] != ""


def test_series_for_families_filters_fetch_list():
    series = ["KXATPMATCH", "KXWTAMATCH", "KXATPADVANCE", "KXFOMEN", "KXATPSETWINNER", "KXATP1RANK"]
    # Only the enabled families' series are returned (this is what reduces fetching).
    assert set(data.series_for_families(series, ["Match result"])) == {"KXATPMATCH", "KXWTAMATCH"}
    assert set(data.series_for_families(series, ["Tournament winner"])) == {"KXFOMEN"}
    assert set(data.series_for_families(series, ["Stage advancement", "Set winner"])) == {"KXATPADVANCE", "KXATPSETWINNER"}
    # "Other" series (rankings) are never fetched for the recognized families; empty selection = none.
    assert data.series_for_families(series, []) == []
    assert "KXATP1RANK" not in data.series_for_families(series, ["Match result", "Tournament winner"])


def test_clean_tournament_strips_only_gender_discipline():
    assert data._clean_tournament("French Open Men Singles") == "French Open"
    assert data._clean_tournament("Wimbledon Mixed Doubles") == "Wimbledon"
    assert data._clean_tournament("") == ""


def test_fmt_time_formats_and_falls_back_safely():
    s = "2026-06-03 12:00:00 UTC"
    assert data.fmt_time(s, "UTC").startswith("2026-06-03 12:00:00")
    # Lisbon in June is WEST (UTC+1) when tzdata is present → 13:00; if tzdata is absent the formatter
    # falls back to UTC (12:00). Either way it must not raise and must return a formatted string.
    assert data.fmt_time(s, "Europe/Lisbon").startswith("2026-06-03 1")
    # Unknown zone → UTC fallback, never an exception.
    assert data.fmt_time(s, "Not/AZone").startswith("2026-06-03 12:00:00")
    # Missing / unparseable input → "".
    assert data.fmt_time("", "UTC") == ""
    assert data.fmt_time(None, "UTC") == ""
    assert data.fmt_time("garbage", "UTC") == ""


def test_data_age_and_is_stale():
    from datetime import datetime, timezone
    fetched = "2026-06-03 12:00:00 UTC"
    now = datetime(2026, 6, 3, 12, 5, 0, tzinfo=timezone.utc)   # exactly 5 minutes later
    age = data.data_age_seconds(fetched, now=now)
    assert age == 300
    assert data.is_stale(age, 299) is True
    assert data.is_stale(age, 300) is False        # strictly greater-than, not >=
    assert data.is_stale(None, 10) is False         # unknown age is not stale
    assert data.data_age_seconds("garbage") is None


def test_gate_stale_tradability_downgrades_only_actionable_on_stale():
    opps = [
        {"opportunity_id": "a", "sport": "tennis", "tradable_now": "Yes", "bucket": "actionable", "status": "X"},
        {"opportunity_id": "b", "sport": "tennis", "tradable_now": "Yes — rule-dependent", "bucket": "actionable"},
        {"opportunity_id": "c", "sport": "tennis", "tradable_now": "No", "bucket": "blocked"},
    ]
    # Fresh (age below threshold) → untouched.
    fresh = data.gate_stale_tradability(opps, 100, 300)
    assert [o["tradable_now"] for o in fresh] == ["Yes", "Yes — rule-dependent", "No"]
    # Stale → the two "Yes…" rows downgrade; the already-"No" row and bucket/status are untouched.
    stale = data.gate_stale_tradability(opps, 400, 300)
    assert stale[0]["tradable_now"] == data.STALE_TRADABILITY
    assert stale[1]["tradable_now"] == data.STALE_TRADABILITY
    assert stale[2]["tradable_now"] == "No"
    assert stale[0]["bucket"] == "actionable" and stale[0]["status"] == "X"   # classification untouched
    # The input list is never mutated.
    assert opps[0]["tradable_now"] == "Yes"
    # Unknown age → no-op; per-sport override tightens the threshold.
    assert data.gate_stale_tradability(opps, None, 300)[0]["tradable_now"] == "Yes"
    tightened = data.gate_stale_tradability(opps, 150, 300, by_sport={"tennis": 120})
    assert tightened[0]["tradable_now"] == data.STALE_TRADABILITY      # 150 > 120 sport override


# --- Stage 1: opportunity_id shared helper -------------------------------------------
def test_opportunity_id_is_deterministic_and_stable():
    a = data.opportunity_id("containment_adjacent", "uuid-x", "French Open", "Reach Final", "Win Tournament")
    b = data.opportunity_id("containment_adjacent", "uuid-x", "French Open", "Reach Final", "Win Tournament")
    assert a == b                       # identical inputs -> identical id (no randomness/time)
    assert isinstance(a, str) and len(a) == 16


def test_opportunity_id_distinguishes_different_recipes():
    base = ("containment_adjacent", "uuid-x", "French Open", "Reach Final", "Win Tournament")
    assert data.opportunity_id(*base) != data.opportunity_id("match_alignment", *base[1:])
    assert data.opportunity_id(*base) != data.opportunity_id(*base[:-1], "Reach Semifinal")
    # A None part is positional (normalizes to "") and does not collide with the empty-token recipe.
    assert data.opportunity_id("dutch_book", "EVT", None, "k") != data.opportunity_id("dutch_book", "EVT", "k")


# --- exact-score data capture + identity hardening (synthetic-bundle gates) -----------
def _exact_score_event():
    """A BO5 exact-score event: one player's 3 win-states, with the binary/settlement fields a real
    KXATPEXACTMATCH market carries (verified live: market_type=binary, strike_type=custom,
    fractional_trading_enabled=True, Set Score in custom_strike)."""
    def market(score, ask):
        return {
            "ticker": f"KXATPEXACTMATCH-26JUN05MENZVE-MEN{score.replace('-', '')}",
            "yes_sub_title": f"Jakub Mensik wins {score}",
            "custom_strike": {"Set Score": score, "tennis_competitor": "uuid-men"},
            "market_type": "binary", "strike_type": "custom", "fractional_trading_enabled": True,
            "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
            "rules_secondary": "The following market refers to the Mensik vs Zverev match.",
            "close_time": "2026-06-19T12:30:00Z", "expiration_time": "2026-06-19T12:30:00Z",
            "yes_bid_dollars": "0.10", "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active",
            "title": f"Mensik vs Zverev exact score {score}?",
        }
    return {
        "event_ticker": "KXATPEXACTMATCH-26JUN05MENZVE", "title": "Mensik vs Zverev",
        "mutually_exclusive": True, "product_metadata": {"competition": "ATP Wimbledon"},
        "markets": [market("3-0", "0.12"), market("3-1", "0.14"), market("3-2", "0.16")],
    }


def test_build_contracts_captures_exact_score_settlement_metadata():
    rows = data.build_contracts("KXATPEXACTMATCH", [_exact_score_event()])
    assert len(rows) == 3
    r = next(x for x in rows if x["score_state"] == "3-0")
    assert r["kind"] == "exact_score"
    assert r["market_type"] == "binary" and r["strike_type"] == "custom"
    assert r["fractional_trading_enabled"] is True              # NORMAL: order-size granularity, not scalar
    assert r["rules_secondary"].startswith("The following market")
    assert r["close_time"] == "2026-06-19T12:30:00Z" and r["expiration_time"] == "2026-06-19T12:30:00Z"
    assert isinstance(r["price_ranges"], list)
    assert {x["score_state"] for x in rows} == {"3-0", "3-1", "3-2"}     # the BO5 win-state set


def test_exact_score_rows_key_on_uuid_not_scoreline():
    # Identity hardening (#27): a player's 3 score-states share the stable tennis_competitor UUID, so the
    # synthetic detector groups them correctly and is never split by the scoreline display text.
    rows = data.build_contracts("KXATPEXACTMATCH", [_exact_score_event()])
    assert {r["player_key"] for r in rows} == {"uuid-men"}


# --- numeric strike bounds reach the row + drive the ladder builder (Phase 1a regression) -------------
def _numeric_total_event():
    """A live-shaped ATP total-games event: two monotone 'Over N games' markets carrying machine-readable
    numeric strikes (strike_type=greater + floor_strike), as KXATPGTOTAL markets do (live 2026-06-17)."""
    def market(floor, ask):
        return {
            "ticker": f"KXATPGTOTAL-26JUN17MEDHUM-T{str(floor).replace('.', '')}",
            "yes_sub_title": f"Over {floor} games", "custom_strike": {},
            "market_type": "binary", "strike_type": "greater", "floor_strike": floor, "cap_strike": None,
            "yes_bid_dollars": "0.40", "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active",
            "title": f"ATP total games over {floor}?",
        }
    return {
        "event_ticker": "KXATPGTOTAL-26JUN17MEDHUM", "title": "Medvedev vs Humbert total games",
        "markets": [market(19.5, "0.46"), market(29.5, "0.20")],
    }


def test_build_contracts_surfaces_numeric_strike_bounds():
    # Regression: build_contracts previously dropped floor_strike/cap_strike, so numeric_ladder (which reads
    # them) found nothing on LIVE rows. They must now ride the contract row as raw passthrough.
    rows = data.build_contracts("KXATPGTOTAL", [_numeric_total_event()])
    assert len(rows) == 2
    assert sorted(r["floor_strike"] for r in rows) == [19.5, 29.5]
    assert all(r["cap_strike"] is None for r in rows)


def test_numeric_ladder_builds_from_build_contracts_output():
    # The REAL path (not a hand-built fixture): numeric_ladder must build a monotone ladder straight from
    # build_contracts output — proves the Phase 1a plumbing actually enables the payoff-state demo on live data.
    rows = data.build_contracts("KXATPGTOTAL", [_numeric_total_event()])
    ladders = numeric_ladder.build_numeric_ladders(rows)
    assert len(ladders) == 1
    lad = ladders[0]
    assert lad.direction == "ge"
    assert [s for s, _ in lad.rungs] == [19.5, 29.5]      # broad -> deep (ascending ge strikes)


def test_score_state_helper_normalizes_and_blank_for_non_exact_score():
    assert data.score_state({"Set Score": "3 - 0"}) == "3-0"
    assert data.score_state({"Set Score": "2-1"}) == "2-1"
    assert data.score_state({"tennis_competitor": "x"}) == ""           # no Set Score → blank
    assert data.score_state(None) == ""


def test_within_window_survives_misconfigured_fo_window(monkeypatch):
    # C7: a malformed FO_WINDOW (operator typo when updating the year-specific window) must NOT raise inside
    # build_contracts — _within_window logs once and returns False (date-fallback disabled), never crashes.
    monkeypatch.setattr(data, "_fo_window_parsed", False)
    monkeypatch.setattr(data, "_FO_WINDOW_BOUNDS", None)
    monkeypatch.setattr(data, "FO_WINDOW", ("not-a-real-date", "also-bad"))
    assert data._within_window("2026-05-30T10:00:00+00:00") is False
    # And a valid window still matches inside / rejects outside.
    monkeypatch.setattr(data, "_fo_window_parsed", False)
    monkeypatch.setattr(data, "_FO_WINDOW_BOUNDS", None)
    monkeypatch.setattr(data, "FO_WINDOW", ("2026-05-24", "2026-06-08"))
    assert data._within_window("2026-05-30T10:00:00+00:00") is True
    assert data._within_window("2026-07-01T10:00:00+00:00") is False
