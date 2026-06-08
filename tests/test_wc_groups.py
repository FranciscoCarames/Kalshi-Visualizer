"""Offline tests for the fail-closed WC group helpers (PR0 — no product behaviour yet).

Fixture-backed where it matters: the captured Group B fixtures pin the two real ticker shapes and the
qualifier↔exact-order name match the PR4 join depends on."""

import json
from pathlib import Path

import pytest

import wc_groups
from sports import SOCCER_TIE_UUID

_FIX = Path(__file__).parent / "fixtures" / "wc_qualifier"


def _load(name):
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


# --- parse_wc_group_key -----------------------------------------------------------------------------
@pytest.mark.parametrize("ticker,expected", [
    ("KXWCGROUPQUAL-26B", "B"),               # group AFTER season
    ("KXWCGROUPWIN-26B", "B"),
    ("KXWCGROUPQUAL-26L", "L"),
    ("KXWCGROUPQUAL-26B-CAN", "B"),           # per-market suffix, after-shape
    ("KXWCGROUPORDER-B26", "B"),              # group BEFORE season
    ("KXWCGROUPORDER-B26-CANBIHQATSUI", "B"), # per-market suffix, before-shape
    ("KXWCGROUPORDER-L26", "L"),
])
def test_parse_group_key_both_shapes(ticker, expected):
    assert wc_groups.parse_wc_group_key(ticker) == expected


@pytest.mark.parametrize("ticker", [
    "", None, "KXWCGAME-26JUN12CANBIH",       # no group token
    "KXWCGROUPQUAL-26",                        # missing letter
    "KXWCGROUPQUAL-26Z",                        # out-of-range group letter (only A–L exist)
    "KXWCGROUPORDER-Z26",
    "KXNFLGAME-26-KC",                          # unrelated series
    "GROUPB",                                   # no season anchor
])
def test_parse_group_key_fails_closed(ticker):
    assert wc_groups.parse_wc_group_key(ticker) is None


# --- normalize_country_name -------------------------------------------------------------------------
def test_normalize_strips_newlines_and_collapses():
    # The exact-order custom_strike form vs the qualifier yes_sub_title form must key identically.
    assert wc_groups.normalize_country_name("\nBosnia and Herzegovina\n") == \
        wc_groups.normalize_country_name("Bosnia and Herzegovina")
    assert wc_groups.normalize_country_name("  Canada  ") == "canada"
    assert wc_groups.normalize_country_name("Bosnia   and\nHerzegovina") == "bosnia and herzegovina"


def test_normalize_strips_accents_and_casefolds():
    assert wc_groups.normalize_country_name("Türkiye") == wc_groups.normalize_country_name("Turkiye")
    assert wc_groups.normalize_country_name("CÔTE D'IVOIRE") == wc_groups.normalize_country_name("Côte d'Ivoire")


def test_normalize_distinct_names_do_not_collide():
    assert wc_groups.normalize_country_name("Canada") != wc_groups.normalize_country_name("Qatar")
    assert wc_groups.normalize_country_name("") == ""


# --- is_tie_row -------------------------------------------------------------------------------------
def test_is_tie_row_structured_signals():
    assert wc_groups.is_tie_row({"participant_type": "tie"}) is True
    assert wc_groups.is_tie_row({"custom_strike": {"soccer_team": SOCCER_TIE_UUID}}) is True
    assert wc_groups.is_tie_row({"raw_custom_strike": {"soccer_team": SOCCER_TIE_UUID}}) is True


def test_is_tie_row_fails_closed_on_string_only():
    # A real team row, even one literally named in the title, is NOT a tie unless a structured signal says so.
    assert wc_groups.is_tie_row({"participant_type": "participant",
                                 "yes_sub_title": "Tie", "custom_strike": {"soccer_team": "abc"}}) is False
    assert wc_groups.is_tie_row({}) is False


# --- fixture-backed: the PR4 join surface holds on real captured data --------------------------------
def test_fixtures_qualifier_and_order_names_match_under_normalization():
    qual = _load("KXWCGROUPQUAL-26B.json")
    order = _load("KXWCGROUPORDER-B26.json")
    qual_names = {wc_groups.normalize_country_name(m["yes_sub_title"]) for m in qual["markets"]}
    order_names = set()
    for m in order["markets"]:
        for v in m["custom_strike"].values():
            order_names.add(wc_groups.normalize_country_name(v))
    assert len(qual_names) == 4
    assert qual_names == order_names                                  # the name join is total
    # Both event tickers resolve to the same group.
    assert wc_groups.parse_wc_group_key(qual["event_ticker"]) == "B"
    assert wc_groups.parse_wc_group_key(order["event_ticker"]) == "B"


def test_fixture_exact_order_is_24_way_mece_without_uuid():
    order = _load("KXWCGROUPORDER-B26.json")
    assert order["mutually_exclusive"] is True
    assert len(order["markets"]) == 24
    # No soccer_team UUID on exact-order markets — identity is placement NAMES only.
    assert all("soccer_team" not in (m.get("custom_strike") or {}) for m in order["markets"])
    assert all(len(m["custom_strike"]) == 4 for m in order["markets"])
