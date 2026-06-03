"""Pure data logic: parsing, contract filtering, and the per-player contract index for Kalshi tennis markets.

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

import sports
from config import (
    FO_KEYWORDS,
    FO_WINDOW,
    FO_WINNER_TICKERS,
    KALSHI_WEB_BASE,
    NAME_ALIASES,
    SPREAD_REASONABLE,
)

# Tennis round patterns, stage ranks, and category labels now live on the tennis SportConfig
# (sports.py) so the engine is sport-agnostic. Kept here as back-compat aliases that REFERENCE the
# tennis config (never copies), so existing imports/tests (`data.CATEGORY`, `data._STAGE_RANK`, …)
# and the tennis-only direct calls below resolve exactly as before.
_ROUND_PATTERNS = sports.TENNIS.round_patterns
_STAGE_RANK = sports.TENNIS.stage_rank
CATEGORY = sports.TENNIS.category_labels


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
    """Tennis round label from the joined texts (delegates to the shared, sport-parameterized helper)."""
    return sports.extract_round(_ROUND_PATTERNS, *texts)


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


def _slugify(text: Any) -> str:
    """Slug used in Kalshi web URLs, derived from the SERIES title.

    e.g. "French Open Women's" -> "french-open-womens" (matches the live
    kalshi.com/markets/<series>/<slug>/<event> path). Apostrophes are dropped (not turned into a
    hyphen) so "Women's" -> "womens", then any other non-alphanumeric run becomes a single hyphen.
    """
    t = str(text or "").lower().replace("'", "").replace("’", "")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def kalshi_market_url(series_ticker: str, series_title: Any, event_ticker: str) -> str:
    """Deep link to the specific market's Kalshi page, with a guaranteed-resolving fallback.

    Verified live format: ``https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`` where
    ``slug = _slugify(series_title)`` (the event page lists that contract's player markets). When the
    series title or event ticker is missing we cannot build the slugged deep link, so we fall back to
    the always-resolving series page ``https://kalshi.com/markets/<series_lower>`` rather than emit a
    URL that would 404.
    """
    series_lower = (series_ticker or "").lower()
    slug = _slugify(series_title)
    event_lower = (event_ticker or "").lower()
    if series_lower and slug and event_lower:
        return f"{KALSHI_WEB_BASE}/{series_lower}/{slug}/{event_lower}"
    return f"{KALSHI_WEB_BASE}/{series_lower}"


def link_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each unique contract URL, the identifiers it should encode — the deterministic
    "links go to the correct page" check.

    Returns one record per distinct `kalshi_url` with the `series`, `event_ticker`, and how many
    contracts share it, so a test (or the Debug panel) can confirm the URL matches the contract's
    identifiers without hitting the (bot-throttled) Kalshi website.
    """
    seen: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        url = r.get("kalshi_url")
        if not url:
            continue
        entry = seen.setdefault(
            url, {"url": url, "series": r.get("series", ""),
                  "event_ticker": r.get("event_ticker", ""), "contracts": 0}
        )
        entry["contracts"] += 1
    return sorted(seen.values(), key=lambda d: d["url"])


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
    """Classify a series into a contract family (kind).

    Delegates to the sport that owns the ticker (`sports.sport_for_series`). An unrecognized series
    resolves to the UNKNOWN sport and family ``"other"`` (today's behavior for unknown tickers) —
    never silently treated as tennis.
    """
    return sports.sport_for_series(series_ticker).family_of(series_ticker)


def tour_of(series_ticker: str) -> str:
    """Division (tennis: ATP/WTA) from the series ticker, via the resolved sport.

    Sports without a division concept (e.g. NBA) return ``""``.
    """
    return sports.sport_for_series(series_ticker).division_of(series_ticker)


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
        return "Win the tournament"
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


# Tokens stripped from a competition string to get a tournament-level label (gender/discipline are
# carried by player_key + tour, so they must not split one tournament's ladder).
_TOURNAMENT_STRIP = {"men", "mens", "men's", "women", "womens", "women's", "mixed",
                     "singles", "single", "doubles", "double"}
# Known tournament keywords (extend as the app generalizes), checked against event/series titles.
_TOURNAMENT_KEYWORDS = [
    ("French Open", ["french open", "roland garros", "roland-garros"]),
    ("Wimbledon", ["wimbledon"]),
    ("US Open", ["us open", "u.s. open"]),
    ("Australian Open", ["australian open"]),
]


def _clean_tournament(competition: Any) -> str:
    """Tournament-level label from a competition string, dropping gender/discipline tokens.

    "French Open Men Singles" / "French Open Women Singles" -> "French Open". Returns "" when there is
    no competition to clean (the caller then falls back to other signals)."""
    text = str(competition or "").strip()
    if not text:
        return ""
    kept = [w for w in re.split(r"\s+", text) if w.casefold() not in _TOURNAMENT_STRIP]
    cleaned = " ".join(kept).strip()
    return cleaned or text   # if everything was a strip-token, keep the original rather than ""


def _tournament_from_title(*texts: Any) -> str:
    blob = " ".join(str(t) for t in texts if t).casefold()
    for label, kws in _TOURNAMENT_KEYWORDS:
        if any(k in blob for k in kws):
            return label
    return ""


def tournament_of(competition: Any, series_ticker: Any, event_ticker: Any,
                  event_title: Any) -> tuple[str, str]:
    """Return ``(tournament_key, source)`` — the grouping key for containment ladders, plus where it
    came from (debug). The key is NEVER empty for a real row, and prefers tournament-level identifiers
    so a single tournament's rounds are never split:

      1. cleaned `competition`        -> source "competition"
      2. known winner ticker          -> "French Open" (winner events often lack competition)  "winner_ticker"
      3. tournament keyword in title  -> source "title_keyword"
      4. last-resort stable fallback  -> source "fallback"  (label "Unknown · <id>")

    The fallback can only *fail to form* a ladder (under-group), never MIX two unrelated ladders.
    """
    cleaned = _clean_tournament(competition)
    if cleaned:
        return cleaned, "competition"
    if str(series_ticker or "").upper() in FO_WINNER_TICKERS:
        return "French Open", "winner_ticker"
    kw = _tournament_from_title(event_title)
    if kw:
        return kw, "title_keyword"
    fallback = (str(competition or "").strip() or str(event_ticker or "").strip()
                or str(event_title or "").strip() or str(series_ticker or "").strip() or "unknown")
    return f"Unknown · {fallback}", "fallback"


def build_contracts(
    series_ticker: str, events: list[dict[str, Any]], series_title: Any = "",
    _diag: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Flatten one tennis series' events into per-player contract rows.

    Each row is one market from a single player's perspective. Players are keyed by their
    stable `tennis_competitor` UUID so the same player merges across every series/event.
    Opponent is derived (from sibling markets) ONLY for head-to-head match events; winner /
    advancement / set / score markets are single-sided and have no opponent.

    `series_title` (from /series/<ticker>) is used to build the slugged Kalshi deep link to each
    event's page; when absent, links fall back to the series page (see `kalshi_market_url`).
    """
    cfg = sports.sport_for_series(series_ticker)
    tour = cfg.division_of(series_ticker)

    rows: list[dict[str, Any]] = []
    for event in events or []:
        # NOTE: no French-Open gate here — all (tennis) events are included and stamped with a
        # `tournament` grouping key. The hardcoded FO restriction was removed to generalize; narrowing
        # to a tournament is now a client-side filter (is_french_open_event is kept as a helper).
        markets = event.get("markets") or []
        competition = (event.get("product_metadata") or {}).get("competition", "")
        event_ticker = event.get("event_ticker", "")
        tournament, tournament_source = tournament_of(
            competition, series_ticker, event_ticker, event.get("title", "")
        )
        names = [((m.get("yes_sub_title") or "").strip()) for m in markets]
        # Deep link to THIS event's page (lists the player markets) — built once per event.
        event_url = kalshi_market_url(series_ticker, series_title, event_ticker)

        for idx, market in enumerate(markets):
            name = names[idx]
            if not name:
                if _diag is not None:
                    _diag["skipped_no_name"] = _diag.get("skipped_no_name", 0) + 1
                continue  # need a display name for the participant selector

            # Structured, per-sport participant identity (UUID when available, else name fallback).
            ident = cfg.identity.resolve(market)
            player_key = ident.participant_key
            player_key_source = ident.source_field
            mapping_confidence = ident.confidence
            mapping_reason = ident.reason
            competitor = ident.raw_value if ident.confidence == "high" else ""
            # Clean, user-facing name via the single shared helper (alias > source > titleized
            # fallback). Internal identifiers are kept as separate fields for debug/export.
            display = display_player_name({"player_key": player_key, "player_name_raw": name})

            # Structured, per-sport market classification: family, stage, ladder node + eligibility.
            mc = cfg.classify(series_ticker, market)
            kind = mc.family
            category = cfg.category_labels.get(kind, "Other")
            stage = mc.stage

            # Opponent only for the head-to-head family (tennis: "match"; NBA: "series").
            if cfg.match_family and kind == cfg.match_family:
                opponents = [n for j, n in enumerate(names) if j != idx and n and n != name]
                opponent = " / ".join(opponents)
            else:
                opponent = ""

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

            # NO-side prices (Kalshi reports these directly). On Kalshi's unified book
            # no_ask == 1 - yes_bid exactly, but we read the real fields so the displayed "Buy NO"
            # price is literal. There are NO NO-side size fields: buying NO matches resting YES bids,
            # so the tradable size of a Buy-NO leg is `yes_bid_size`.
            no_bid = to_float(market.get("no_bid_dollars"))
            no_ask = to_float(market.get("no_ask_dollars"))
            no_bid_c = to_cents(market.get("no_bid_dollars"))
            no_ask_c = to_cents(market.get("no_ask_dollars"))

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
                    "stage_rank": mc.stage_rank,
                    "opponent": opponent,
                    "competition": competition,
                    "tournament": tournament,
                    "tournament_source": tournament_source,
                    # Structured classification: sport-agnostic ladder placement + eligibility.
                    # Ineligible/unsupported markets (per-game, props, …) never enter ladder checks
                    # and surface in the unmapped table with `classification_reason`.
                    "market_family": mc.family,
                    "ladder_node": mc.ladder_node,
                    "ladder_eligible": mc.eligible_for_ladder_checks,
                    "classification_confidence": mc.confidence,
                    "classification_reason": mc.reason,
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
                    # NO-side prices (real, from the API). No NO sizes exist on Kalshi.
                    "no_bid_pct": _pct(no_bid),
                    "no_ask_pct": _pct(no_ask),
                    "no_bid_c": no_bid_c,
                    "no_ask_c": no_ask_c,
                    "volume": to_float(market.get("volume_fp")),
                    "open_interest": to_float(market.get("open_interest_fp")),
                    "status": market.get("status", ""),
                    "time_value": time_value,
                    "time_kind": time_kind,
                    "kalshi_url": event_url,
                    # Identifiers + raw fields for the debug expander.
                    "series": series_ticker,
                    "event_ticker": event.get("event_ticker", ""),
                    "market_ticker": market.get("ticker", ""),
                    "event_title": event.get("title", ""),
                    "market_title": market.get("title", ""),
                    "raw_yes_bid": market.get("yes_bid_dollars"),
                    "raw_yes_ask": market.get("yes_ask_dollars"),
                    "raw_no_bid": market.get("no_bid_dollars"),
                    "raw_no_ask": market.get("no_ask_dollars"),
                    "raw_last": market.get("last_price_dollars"),
                    "rules_primary": market.get("rules_primary", ""),
                    # Raw metadata preserved for debugging / downloads (identity + settlement context).
                    "raw_custom_strike": market.get("custom_strike"),
                    "raw_product_metadata": event.get("product_metadata"),
                }
            )
    return rows


def series_for_families(series_tickers: list[str], families: Any) -> list[str]:
    """Subset of `series_tickers` whose contract family (CATEGORY of classify_kind) is enabled.

    This is what makes contract-family filters REDUCE FETCHING: only series for the selected families
    are requested from Kalshi. (Tournament / event / participant filters are client-side and do NOT
    change which series are fetched.)
    """
    fams = set(families or [])
    out: list[str] = []
    for s in series_tickers or []:
        cfg = sports.sport_for_series(s)
        if cfg.category_labels.get(cfg.family_of(s), "Other") in fams:
            out.append(s)
    return out
