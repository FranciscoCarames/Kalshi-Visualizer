"""Streamlit AppTest smoke test — the full UI render pipeline, no network.

The three Kalshi network entry points are mocked so the REAL data/consistency/filter layers run
end to end on deterministic synthetic events. The bar is "renders without raising": this catches
app.py wiring bugs (tuple unpacking, column references, widget config) that the pure-layer unit
tests cannot. A second run drives the Participant selector to exercise the per-player detail and
the `expected_nodes` ladder path.

Mock targets are on `kalshi_client.*` because `app.py` re-imports those names on every AppTest run,
so the patched attributes are what the freshly-executed script binds to.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

_COMPETITION = "French Open Women Singles"


def _market(ticker: str, player: str, uuid: str, bid: str, ask: str, title: str) -> dict:
    """One player-side market in the proven build_contracts schema (mirrors test_data)."""
    return {
        "ticker": ticker, "yes_sub_title": player,
        "custom_strike": {"tennis_competitor": uuid},
        "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
        "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
        "volume_fp": "1000", "open_interest_fp": "500", "status": "active",
        "title": title,
        "occurrence_datetime": "2026-06-02T12:00:00Z",
        "close_time": "2026-06-16T09:00:00Z",
    }


def _synthetic_results() -> list[tuple[str, list[dict]]]:
    """Match + advance(Reach Final) + winner(Win Tournament) for one player in one tournament,
    so build_checks yields real adjacent-ladder comparisons (populated diagnostics)."""
    match_event = {
        "event_ticker": "KXWTAMATCH-26JUN02ANDCIR",
        "title": "Andreeva vs Cirstea",
        "product_metadata": {"competition": _COMPETITION},
        "markets": [
            _market("KXWTAMATCH-26JUN02ANDCIR-AND", "Mirra Andreeva", "uuid-and", "0.62", "0.63",
                    "Will Mirra Andreeva win the Andreeva vs Cirstea: Quarterfinal match?"),
            _market("KXWTAMATCH-26JUN02ANDCIR-CIR", "Sorana Cirstea", "uuid-cir", "0.37", "0.38",
                    "Will Sorana Cirstea win the Andreeva vs Cirstea: Quarterfinal match?"),
        ],
    }
    advance_event = {
        "event_ticker": "KXWTAADVANCE-26FOFIN",
        "title": "Reach the Final",
        "product_metadata": {"competition": _COMPETITION},
        "markets": [
            _market("KXWTAADVANCE-26FOFIN-AND", "Mirra Andreeva", "uuid-and", "0.30", "0.31",
                    "Will Mirra Andreeva reach the Final?"),
        ],
    }
    winner_event = {
        "event_ticker": "KXFOWOMEN-26",
        "title": "Win the tournament",
        "product_metadata": {"competition": _COMPETITION},
        "markets": [
            _market("KXFOWOMEN-26-AND", "Mirra Andreeva", "uuid-and", "0.10", "0.11",
                    "Will Mirra Andreeva win the KXFOWOMEN-26?"),
        ],
    }
    return [
        ("KXWTAMATCH", [match_event]),
        ("KXWTAADVANCE", [advance_event]),
        ("KXFOWOMEN", [winner_event]),
    ]


def test_app_renders_without_exception():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    results = _synthetic_results()
    tickers = [t for t, _ in results]
    titles = {"KXWTAMATCH": "WTA Match", "KXWTAADVANCE": "WTA Advance", "KXFOWOMEN": "French Open Women's"}

    with patch("kalshi_client.discover_series_for_sport", return_value=tickers), \
         patch("kalshi_client.get_events_for_series", return_value=(results, [])), \
         patch("kalshi_client.get_series_titles", return_value=titles):
        at = AppTest.from_file(APP_PATH, default_timeout=60).run()
        assert not at.exception

        # Drive the Participant selector to exercise the per-player detail + expected_nodes path.
        # Locate it by its options (robust to sidebar control ordering) rather than by index.
        participant = next(sb for sb in at.selectbox if "Mirra Andreeva" in sb.options)
        participant.set_value("Mirra Andreeva")
        at.run()
        assert not at.exception


def _nba_market(ticker: str, team: str, uuid: str, bid: str, ask: str, title: str) -> dict:
    return {
        "ticker": ticker, "yes_sub_title": team, "custom_strike": {"basketball_team": uuid},
        "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
        "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
        "volume_fp": "1000", "open_interest_fp": "500", "status": "active",
        "title": title, "close_time": "2026-06-16T09:00:00Z",
    }


def _nba_results() -> list[tuple[str, list[dict]]]:
    """Championship + conference (a real Win Championship ⊆ Win Conference ladder) + a per-game
    market (ineligible — must surface in the unmapped table, never in ladder checks)."""
    comp = {"competition": "Pro Basketball (M)"}
    champ = {"event_ticker": "KXNBA-26", "title": "Finals", "product_metadata": comp,
             "markets": [_nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                                     "Will the Boston win the 2026 Pro Basketball Finals?")]}
    conf = {"event_ticker": "KXNBAEAST-26", "title": "East", "product_metadata": comp,
            "markets": [_nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.55", "0.57",
                                    "Will the Boston win the Eastern Conference Championship?")]}
    game = {"event_ticker": "KXNBAGAME-26JUN10", "title": "Game 4",
            "product_metadata": {"competition": "Pro Basketball (M)", "competition_scope": "Game"},
            "markets": [_nba_market("KXNBAGAME-26JUN10-BOS", "Boston", "uuid-bos", "0.50", "0.52",
                                    "Game 4 Winner?")]}
    return [("KXNBA", [champ]), ("KXNBAEAST", [conf]), ("KXNBAGAME", [game])]


def test_app_renders_nba_and_unmapped_table():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    results = _nba_results()
    tickers = [t for t, _ in results]
    with patch("kalshi_client.discover_series_for_sport", return_value=tickers), \
         patch("kalshi_client.get_events_for_series", return_value=(results, [])), \
         patch("kalshi_client.get_series_titles", return_value={}):
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.session_state["sport_id"] = "nba"          # select NBA before the first render
        at.run()
        assert not at.exception

        # Turn on the non-laddered table → the per-game market must render there.
        toggle = next(t for t in at.toggle if "non-laddered" in t.label.lower())
        toggle.set_value(True)
        at.run()
        assert not at.exception


def _nhl_market(ticker: str, team: str, uuid: str, bid: str, ask: str, title: str) -> dict:
    return {
        "ticker": ticker, "yes_sub_title": team, "custom_strike": {"hockey_team": uuid},
        "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
        "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
        "volume_fp": "1000", "open_interest_fp": "500", "status": "active",
        "title": title, "close_time": "2026-06-16T09:00:00Z",
    }


def _nhl_results() -> list[tuple[str, list[dict]]]:
    """Stanley Cup winner + conference (a real Win Championship ⊆ Win Conference ladder) + a per-game
    market (ineligible — must surface in the unmapped table, never in ladder checks)."""
    comp = {"competition": "Pro Hockey"}
    champ = {"event_ticker": "KXNHL-26", "title": "Stanley Cup", "product_metadata": comp,
             "markets": [_nhl_market("KXNHL-26-BOS", "Bruins", "uuid-bos", "0.40", "0.42",
                                     "Will the Bruins win the 2026 Stanley Cup?")]}
    conf = {"event_ticker": "KXNHLEAST-26", "title": "East", "product_metadata": comp,
            "markets": [_nhl_market("KXNHLEAST-26-BOS", "Bruins", "uuid-bos", "0.55", "0.57",
                                    "Will the Bruins win the Eastern Conference?")]}
    game = {"event_ticker": "KXNHLGAME-26JUN10", "title": "Game 4",
            "product_metadata": {"competition": "Pro Hockey", "competition_scope": "Game"},
            "markets": [_nhl_market("KXNHLGAME-26JUN10-BOS", "Bruins", "uuid-bos", "0.50", "0.52",
                                    "Game 4 Winner?")]}
    return [("KXNHL", [champ]), ("KXNHLEAST", [conf]), ("KXNHLGAME", [game])]


def test_app_renders_nhl_and_unmapped_table():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    results = _nhl_results()
    tickers = [t for t, _ in results]
    with patch("kalshi_client.discover_series_for_sport", return_value=tickers), \
         patch("kalshi_client.get_events_for_series", return_value=(results, [])), \
         patch("kalshi_client.get_series_titles", return_value={}):
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.session_state["sport_id"] = "nhl"          # select NHL before the first render
        at.session_state["scan_all_toggle"] = False
        at.run()
        assert not at.exception

        toggle = next(t for t in at.toggle if "non-laddered" in t.label.lower())
        toggle.set_value(True)
        at.run()
        assert not at.exception


def test_dutch_plan_text_lists_all_n_legs():
    """The dutch-book table's plan cell lists EVERY leg for an n-outcome (soccer 3-way) finding, and
    falls back to the positional action_1/2 fields for a 2-leg book."""
    import app
    n_leg = {"legs": [{"text": "Buy YES — Mexico @ 40¢"}, {"text": "Buy YES — South Africa @ 30¢"},
                      {"text": "Buy YES — Tie @ 25¢"}]}
    plan = app.dutch_plan_text(n_leg)
    assert "Mexico" in plan and "South Africa" in plan and "Tie" in plan   # all 3 legs shown
    two_leg = {"legs": None, "action_1_text": "Buy YES — A @ 45¢", "action_2_text": "Buy NO — B @ 49¢"}
    plan2 = app.dutch_plan_text(two_leg)
    assert "A @ 45¢" in plan2 and "B @ 49¢" in plan2
