"""Pure data logic: parsing, French Open filtering, and the per-player contract index.

Deliberately free of any Streamlit (or pandas) imports so it can be unit-tested and
reused on its own. Functions accept the raw JSON dicts returned by kalshi_client.

Data model (verified against the live API):
  - Each EVENT is one match, e.g. "KXATPMATCH-26JUN02MENFON" / "Mensik vs Fonseca".
  - Each event contains one MARKET per player, a "Will <player> win?" binary contract
    whose `yes_sub_title` is that player and whose YES mid-price is that player's win
    probability. (The two players' YES prices sum to ~1.0 — mutually exclusive.)
  - `custom_strike.tennis_competitor` is a stable per-player UUID, used as the player key
    so the same player links across events (rounds) regardless of name formatting.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from config import FO_KEYWORDS, FO_WINDOW, FO_WINNER_TICKERS, NAME_ALIASES

# Rounds checked most-specific first; \b boundaries stop "final" matching "quarterfinal".
_ROUND_PATTERNS = [
    ("Final", r"\bfinal\b"),
    ("Semifinal", r"\bsemi-?final(?:s)?\b"),
    ("Quarterfinal", r"\bquarter-?final(?:s)?\b"),
    ("Round of 16", r"\bround of 16\b|\bfourth round\b"),
    ("Round of 32", r"\bround of 32\b|\bthird round\b"),
    ("Round of 64", r"\bround of 64\b|\bsecond round\b"),
    ("Round of 128", r"\bround of 128\b|\bfirst round\b"),
]

# Tournament progression order, used to sort a player's contracts QF -> SF -> Final -> title.
_STAGE_RANK = {
    "Round of 128": 1,
    "Round of 64": 2,
    "Round of 32": 3,
    "Round of 16": 4,
    "Quarterfinal": 5,
    "Semifinal": 6,
    "Final": 7,
    "Champion": 8,
}

# Map each contract kind to a user-facing category label (shown/filterable in the UI).
CATEGORY = {
    "match": "Match result",
    "advance": "Stage advancement",
    "winner": "Tournament winner",
    "set_winner": "Set winner",
    "exact_score": "Exact score",
    "grand_slam": "Grand Slam (season)",
    "other": "Other",
}


def to_float(value: Any) -> float | None:
    """Parse a Kalshi fixed-point string (e.g. "0.6500", "15919.84") into a float.

    Returns None for missing/empty values so "no quote" stays distinct from a real 0.0.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _text_has_keyword(*texts: Any) -> bool:
    blob = " ".join(str(t) for t in texts if t).casefold()
    return any(kw in blob for kw in FO_KEYWORDS)


def _within_window(*timestamps: Any) -> bool:
    start = datetime.fromisoformat(FO_WINDOW[0]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(FO_WINDOW[1]).replace(tzinfo=timezone.utc)
    for ts in timestamps:
        dt = _parse_ts(ts)
        if dt is not None and start <= dt <= end:
            return True
    return False


def _extract_round(*texts: Any) -> str:
    blob = " ".join(str(t) for t in texts if t)
    for label, pattern in _ROUND_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            return label
    return ""


def is_french_open_event(event: dict[str, Any]) -> bool:
    """Decide whether a (generic ATP/WTA) match event belongs to the French Open."""
    markets = event.get("markets") or []
    competition = (event.get("product_metadata") or {}).get("competition", "")

    # Primary signal: explicit competition name on the event.
    if _text_has_keyword(competition):
        return True

    # Secondary signal: tournament name embedded in event/market titles or market rules.
    market_texts: list[Any] = []
    for m in markets:
        market_texts.append(m.get("title"))
        market_texts.append(m.get("rules_primary"))
    if _text_has_keyword(event.get("title"), event.get("sub_title"), *market_texts):
        return True

    # Last-resort fallback (only when no keyword anywhere): match time inside FO window.
    return any(
        _within_window(m.get("occurrence_datetime"), m.get("close_time")) for m in markets
    )


def filter_french_open(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the events that are part of the French Open."""
    return [e for e in (events or []) if is_french_open_event(e)]


def _player_win_prob(market: dict[str, Any]) -> float | None:
    """Implied win probability for this market's player = YES mid (or last price).

    A 0.00/1.00 quote is an EMPTY order book, not a real 50% market, so it is ignored and we
    fall back to the last traded price (or None -> shown blank) rather than inventing a mid.
    """
    bid = to_float(market.get("yes_bid_dollars"))
    ask = to_float(market.get("yes_ask_dollars"))
    if bid == 0.0 and ask == 1.0:  # full-width book = no liquidity
        bid = ask = None
    legs = [x for x in (bid, ask) if x is not None]
    if legs:
        return sum(legs) / len(legs)
    return to_float(market.get("last_price_dollars"))


def classify_kind(series_ticker: str) -> str:
    """Classify a tennis series into a contract kind.

    Order matters: the explicit winner tickers and the EXACTMATCH/SETWINNER checks must run
    before the generic MATCH check (EXACTMATCH contains the substring "MATCH").
    """
    t = (series_ticker or "").upper()
    if t in FO_WINNER_TICKERS:
        return "winner"
    if "ADVANCE" in t:
        return "advance"
    if "EXACTMATCH" in t or "EXACTSCORE" in t:
        return "exact_score"
    if "SETWINNER" in t:
        return "set_winner"
    if "GRANDSLAM" in t:
        return "grand_slam"
    if "MATCH" in t:
        return "match"
    return "other"


def tour_of(series_ticker: str) -> str:
    """Men's (ATP) vs women's (WTA) from the series ticker."""
    t = (series_ticker or "").upper()
    if t.startswith("KXWTA") or "WOMEN" in t:
        return "WTA"
    return "ATP"


def _clean_title(title: Any) -> str:
    """Turn a verbose Kalshi market title into a compact contract label."""
    text = str(title or "").strip()
    text = re.sub(r"^will\s+", "", text, flags=re.IGNORECASE)
    # Drop the "... at the 2026 French Open ... tennis tournament" boilerplate suffix.
    text = re.sub(r"\s+at the .*tennis tournament", "", text, flags=re.IGNORECASE)
    text = text.rstrip("?").strip()
    return text or "Contract"


def _contract_label(kind: str, market: dict[str, Any], opponent: str, stage: str) -> str:
    """Human-readable description of what a contract pays out on."""
    if kind == "match":
        base = f"Beat {opponent}" if opponent else "Win match"
        return f"{base} — {stage}" if stage else base
    if kind == "advance":
        return f"Reach {stage}" if stage else "Reach next stage"
    if kind == "winner":
        return "Win the French Open"
    return _clean_title(market.get("title"))


def build_contracts(series_ticker: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten one series' French Open events into per-player contract rows.

    Each row is one market from a single player's perspective. Players are keyed by their
    stable `tennis_competitor` UUID so the same player merges across every series/event.
    Opponent is derived (from sibling markets) ONLY for head-to-head match events; winner /
    advancement / set / score markets are single-sided and have no opponent.
    """
    kind = classify_kind(series_ticker)
    tour = tour_of(series_ticker)
    category = CATEGORY.get(kind, "Other")

    rows: list[dict[str, Any]] = []
    for event in events or []:
        if not is_french_open_event(event):
            continue
        markets = event.get("markets") or []
        competition = (event.get("product_metadata") or {}).get("competition", "")
        names = [((m.get("yes_sub_title") or "").strip()) for m in markets]

        for idx, market in enumerate(markets):
            name = names[idx]
            if not name:
                continue  # need a display name for the player selector
            competitor = (market.get("custom_strike") or {}).get("tennis_competitor")
            player_key = competitor or name.casefold()
            display = NAME_ALIASES.get(player_key, name) or name

            if kind == "match":
                opponents = [n for j, n in enumerate(names) if j != idx and n and n != name]
                opponent = " / ".join(opponents)
            else:
                opponent = ""

            stage = "Champion" if kind == "winner" else _extract_round(
                market.get("title"), market.get("rules_primary")
            )
            prob = _player_win_prob(market)
            rows.append(
                {
                    "player": display,
                    "player_key": player_key,
                    "tour": tour,
                    "kind": kind,
                    "category": category,
                    "contract": _contract_label(kind, market, opponent, stage),
                    "stage": stage,
                    "stage_rank": _STAGE_RANK.get(stage, 0),
                    "opponent": opponent,
                    "competition": competition,
                    "implied_prob": prob,
                    "implied_pct": round(prob * 100, 1) if prob is not None else None,
                    "yes_bid": to_float(market.get("yes_bid_dollars")),
                    "yes_ask": to_float(market.get("yes_ask_dollars")),
                    "last_price": to_float(market.get("last_price_dollars")),
                    "volume": to_float(market.get("volume_fp")),
                    "open_interest": to_float(market.get("open_interest_fp")),
                    "status": market.get("status", ""),
                    "match_time": market.get("occurrence_datetime", ""),
                    "close_time": market.get("close_time", ""),
                    "series": series_ticker,
                    "event_ticker": event.get("event_ticker", ""),
                    "market_ticker": market.get("ticker", ""),
                }
            )
    return rows
