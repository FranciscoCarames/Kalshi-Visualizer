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

    with patch("kalshi_client.discover_tennis_series", return_value=tickers), \
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
