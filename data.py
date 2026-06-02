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
from decimal import Decimal, InvalidOperation
from typing import Any

from config import (
    FO_KEYWORDS,
    FO_WINDOW,
    FO_WINNER_TICKERS,
    KALSHI_WEB_BASE,
    NAME_ALIASES,
    SPREAD_REASONABLE,
)

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


def to_cents(value: Any) -> int | None:
    """Parse a Kalshi dollar string ("0.3700") into an exact integer of cents (37).

    Uses Decimal so comparison logic is free of binary-float drift. Returns None for
    missing/empty/unparseable values.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
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

    # No French Open keyword anywhere. If the event names a (non-FO) competition, trust that
    # negative signal — do NOT guess from dates (a concurrent non-FO tennis event in the same
    # window would otherwise be mis-included). Only date-fallback when competition is absent.
    if str(competition).strip():
        return False

    # Last-resort fallback (only when no competition info at all): match time inside FO window.
    return any(
        _within_window(m.get("occurrence_datetime"), m.get("close_time")) for m in markets
    )


def filter_french_open(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the events that are part of the French Open."""
    return [e for e in (events or []) if is_french_open_event(e)]


def _is_empty_book(bid: float | None, ask: float | None) -> bool:
    """A 0.00/1.00 quote means there are no real orders, not a genuine market."""
    return bid == 0.0 and ask == 1.0


def yes_mid(bid: float | None, ask: float | None) -> float | None:
    """Midpoint of the YES bid/ask, or None when the book is empty/one-sided/crossed."""
    if bid is None or ask is None or _is_empty_book(bid, ask) or ask < bid:
        return None
    return (bid + ask) / 2


def spread(bid: float | None, ask: float | None) -> float | None:
    """YES bid/ask spread in dollars, or None when not a two-sided real book (or crossed)."""
    if bid is None or ask is None or _is_empty_book(bid, ask) or ask < bid:
        return None
    return ask - bid


def quote_quality(bid: float | None, ask: float | None) -> str:
    """Human label for how trustworthy the quote is, flagging wide/empty/malformed books."""
    if (bid is None and ask is None) or _is_empty_book(bid, ask):
        return "No quote"
    if bid is None or ask is None:
        return "One-sided"
    if ask < bid:
        return "Crossed"  # malformed/locked book — ask below bid; never trust as a price
    s = ask - bid
    if s <= 0.05:
        return "Tight"
    if s <= 0.15:
        return "OK"
    if s <= 0.30:
        return "Wide"
    return "Very wide"


def display_prob(bid: float | None, ask: float | None, last: float | None) -> float | None:
    """Best single price to show: midpoint if the spread is reasonable, else last, else blank."""
    mid = yes_mid(bid, ask)
    sp = spread(bid, ask)
    if mid is not None and sp is not None and sp <= SPREAD_REASONABLE:
        return mid
    if last is not None and last > 0:
        return last
    return None


def display_cents(bid_c: int | None, ask_c: int | None, last_c: int | None) -> int | None:
    """Integer-cent twin of `display_prob`: midpoint when the spread is reasonable, else last.

    Used by the consistency checker so comparisons stay in exact integer cents.
    """
    empty = bid_c == 0 and ask_c == 100
    if bid_c is not None and ask_c is not None and not empty and ask_c >= bid_c:
        if (ask_c - bid_c) <= int(SPREAD_REASONABLE * 100):
            return round((bid_c + ask_c) / 2)
    if last_c is not None and last_c > 0:
        return last_c
    return None


def _pct(value: float | None) -> float | None:
    return round(value * 100, 1) if value is not None else None


def _kalshi_url(series_ticker: str) -> str:
    """Best-effort link to the contract's Kalshi page (the series page)."""
    return f"{KALSHI_WEB_BASE}/{(series_ticker or '').lower()}"


def _mapping_confidence(competitor: Any, name: Any) -> tuple[str, str]:
    """How confidently this row is keyed to a player: (confidence, reason).

    A stable Kalshi competitor UUID is high confidence; a name-only fallback is low because
    name spellings can drift or collide across markets.
    """
    if competitor:
        return "high", f"keyed to stable tennis_competitor UUID {competitor}"
    if name:
        return "low", "no competitor UUID; keyed to normalized player name (may drift/collide)"
    return "none", "no competitor UUID and no player name"


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


# Explicit tour for the French Open winner-ticker variants, because some (e.g.
# KXFOPENWMENSINGLE = Open Women Singles) split the "W"/"MEN" so substring checks misfire.
_WOMEN_WINNER_TICKERS = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}
_MEN_WINNER_TICKERS = {"KXFOMEN", "KXFOMENSINGLES", "KXFOPENMENSINGLE"}


def tour_of(series_ticker: str) -> str:
    """Men's (ATP) vs women's (WTA) from the series ticker."""
    t = (series_ticker or "").upper()
    if t in _WOMEN_WINNER_TICKERS:
        return "WTA"
    if t in _MEN_WINNER_TICKERS:
        return "ATP"
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


def _titleize_fallback(text: Any) -> str:
    """Turn a normalized key like 'aryna_sabalenka' into 'Aryna Sabalenka'. Words that already
    carry uppercase are left untouched so real names ('de Minaur', 'McEnroe') aren't mangled."""
    cleaned = re.sub(r"\s+", " ", re.sub(r"[_\-]+", " ", str(text or ""))).strip()
    if not cleaned:
        return ""
    words = [(w[:1].upper() + w[1:]) if w == w.lower() else w for w in cleaned.split(" ")]
    return " ".join(words)


def display_player_name(row: dict[str, Any]) -> str:
    """Clean, user-facing player name. Priority (owner decision — alias overrides source):
      1. NAME_ALIASES override, keyed by the player's competitor UUID / player_key (its
         documented purpose is to correct drifted source names).
      2. The explicit source display name (yes_sub_title), preserved verbatim so accents,
         punctuation and real casing survive.
      3. A title-cased fallback from a bare normalized token (e.g. 'aryna_sabalenka').
    Reads NAME_ALIASES at call time so it stays patchable/configurable.
    """
    key = row.get("player_key")
    alias = NAME_ALIASES.get(key) if key is not None else None
    if alias:
        return alias
    raw = str(row.get("player_name_raw") or "").strip()
    # A clean source name (any uppercase or a space) is shown as-is; only a bare lowercase
    # token like 'aryna_sabalenka' is title-cased.
    if raw and (raw != raw.lower() or " " in raw):
        return raw
    return _titleize_fallback(raw or key) or raw


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
            player_key_source = "competitor_uuid" if competitor else "name_fallback"
            mapping_confidence, mapping_reason = _mapping_confidence(competitor, name)
            # Clean, user-facing name via the single shared helper (alias > source > titleized
            # fallback). Internal identifiers are kept as separate fields for debug/export.
            display = display_player_name({"player_key": player_key, "player_name_raw": name})

            if kind == "match":
                opponents = [n for j, n in enumerate(names) if j != idx and n and n != name]
                opponent = " / ".join(opponents)
            else:
                opponent = ""

            stage = "Champion" if kind == "winner" else _extract_round(
                market.get("title"), market.get("rules_primary")
            )

            bid = to_float(market.get("yes_bid_dollars"))
            ask = to_float(market.get("yes_ask_dollars"))
            last = to_float(market.get("last_price_dollars"))
            mid = yes_mid(bid, ask)
            sp = spread(bid, ask)

            # Exact integer-cent prices + order sizes for the consistency checker.
            bid_c = to_cents(market.get("yes_bid_dollars"))
            ask_c = to_cents(market.get("yes_ask_dollars"))
            last_c = to_cents(market.get("last_price_dollars"))
            bid_size = to_float(market.get("yes_bid_size_fp"))
            ask_size = to_float(market.get("yes_ask_size_fp"))

            # Time label depends on contract type: match-result contracts have a real match
            # time (occurrence); everything else shows when the market closes/expires.
            occurrence = market.get("occurrence_datetime") or ""
            close_t = market.get("close_time") or ""
            expiration_t = market.get("expiration_time") or ""
            if kind == "match" and occurrence:
                time_value, time_kind = occurrence, "Match time"
            else:
                time_value = close_t or expiration_t
                time_kind = "Close time" if close_t else "Expiration"

            rows.append(
                {
                    "player": display,
                    "player_key": player_key,
                    "player_key_source": player_key_source,
                    "player_name_raw": name,
                    "player_name_normalized": name.casefold(),
                    "competitor_uuid": competitor or "",
                    "mapping_confidence": mapping_confidence,
                    "mapping_reason": mapping_reason,
                    "tour": tour,
                    "kind": kind,
                    "category": category,
                    "contract": _contract_label(kind, market, opponent, stage),
                    "stage": stage,
                    "stage_rank": _STAGE_RANK.get(stage, 0),
                    "opponent": opponent,
                    "competition": competition,
                    # Pricing — display price plus every component, clearly named.
                    "display_pct": _pct(display_prob(bid, ask, last)),
                    "yes_mid_pct": _pct(mid),
                    "last_pct": _pct(last),
                    "yes_bid_pct": _pct(bid),
                    "yes_ask_pct": _pct(ask),
                    "spread_cents": round(sp * 100, 1) if sp is not None else None,
                    "quote_quality": quote_quality(bid, ask),
                    # Exact integer-cent prices + sizes for layer-consistency comparisons.
                    "yes_bid_c": bid_c,
                    "yes_ask_c": ask_c,
                    "last_c": last_c,
                    "display_c": display_cents(bid_c, ask_c, last_c),
                    "yes_bid_size": bid_size,
                    "yes_ask_size": ask_size,
                    "volume": to_float(market.get("volume_fp")),
                    "open_interest": to_float(market.get("open_interest_fp")),
                    "status": market.get("status", ""),
                    "time_value": time_value,
                    "time_kind": time_kind,
                    "kalshi_url": _kalshi_url(series_ticker),
                    # Identifiers + raw fields for the debug expander.
                    "series": series_ticker,
                    "event_ticker": event.get("event_ticker", ""),
                    "market_ticker": market.get("ticker", ""),
                    "event_title": event.get("title", ""),
                    "market_title": market.get("title", ""),
                    "raw_yes_bid": market.get("yes_bid_dollars"),
                    "raw_yes_ask": market.get("yes_ask_dollars"),
                    "raw_last": market.get("last_price_dollars"),
                    "rules_primary": market.get("rules_primary", ""),
                }
            )
    return rows
