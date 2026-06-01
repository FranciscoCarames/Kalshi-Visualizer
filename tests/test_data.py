"""Unit tests for the pure data layer (no network)."""
from __future__ import annotations

import pytest

import config
import data
import kalshi_client


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


def test_build_contracts_drops_non_french_open():
    ev = _fo_match_event()
    ev["product_metadata"]["competition"] = "Wimbledon Women Singles"
    ev["title"] = "Andreeva vs Cirstea"
    for m in ev["markets"]:
        m["title"] = "Will X win the match?"   # no FO keyword anywhere
        m["occurrence_datetime"] = "2026-07-01T12:00:00Z"  # outside FO window
        m["close_time"] = "2026-07-10T12:00:00Z"
    assert data.build_contracts("KXWTAMATCH", [ev]) == []
