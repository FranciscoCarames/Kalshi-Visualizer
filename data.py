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

from config import FO_KEYWORDS, FO_WINDOW, NAME_ALIASES

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
    """Implied win probability for this market's player = YES mid (or last price)."""
    bid = to_float(market.get("yes_bid_dollars"))
    ask = to_float(market.get("yes_ask_dollars"))
    legs = [x for x in (bid, ask) if x is not None]
    if legs:
        return sum(legs) / len(legs)
    return to_float(market.get("last_price_dollars"))


def contracts_from_events(
    events: list[dict[str, Any]], tour: str
) -> list[dict[str, Any]]:
    """Flatten events into one contract row per market (i.e. per player per match).

    The opponent(s) and the match label come from the sibling markets / event metadata,
    so selecting a player later yields all their contracts across every event they appear in.
    """
    rows: list[dict[str, Any]] = []
    for event in events or []:
        markets = event.get("markets") or []
        competition = (event.get("product_metadata") or {}).get("competition", "")
        match_label = event.get("sub_title") or event.get("title") or event.get("event_ticker", "")

        # Pre-compute each market's player name to derive opponents within the event.
        names = [((m.get("yes_sub_title") or "").strip()) for m in markets]

        for idx, market in enumerate(markets):
            name = names[idx]
            if not name:
                continue
            competitor = (market.get("custom_strike") or {}).get("tennis_competitor")
            player_key = competitor or name.casefold()
            display = NAME_ALIASES.get(player_key, name)

            opponents = [n for j, n in enumerate(names) if j != idx and n and n != name]
            opponent = " / ".join(opponents)

            prob = _player_win_prob(market)
            rows.append(
                {
                    "player": display,
                    "player_key": player_key,
                    "opponent": opponent,
                    "tour": tour,
                    "competition": competition,
                    "round": _extract_round(market.get("title"), market.get("rules_primary")),
                    "match": match_label,
                    "event_ticker": event.get("event_ticker", ""),
                    "market_ticker": market.get("ticker", ""),
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
                }
            )
    return rows
