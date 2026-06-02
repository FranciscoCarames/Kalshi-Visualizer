"""Thin read-only HTTP client for the Kalshi public market-data API.

Only GET endpoints are used and no authentication is required for market data.
All network/pagination/retry concerns live here so the rest of the app stays clean.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from config import (
    BASE_URL,
    FO_WINNER_TICKERS,
    MAX_PAGES,
    REQUEST_TIMEOUT,
    TENNIS_SERIES_PREFIXES,
    USER_AGENT,
)


class KalshiError(RuntimeError):
    """Raised when the Kalshi API cannot be reached or returns an error response."""


_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
# Size the connection pool for our concurrent fan-out so workers don't starve/drop.
_adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Perform a single GET with retry/backoff on transient errors (429, 5xx, network)."""
    url = f"{BASE_URL}{path}"
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc or KalshiError("network error")
            time.sleep(0.8 * (attempt + 1))
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = KalshiError(f"HTTP {resp.status_code} from {url}")
            time.sleep(0.8 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise KalshiError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:  # non-JSON 200 body — surface as KalshiError, not a raw decode error
            raise KalshiError(f"Invalid JSON from {url}: {exc}") from exc

    raise KalshiError(f"Failed to GET {url} after retries: {last_error!r}")


def get_paginated(path: str, params: dict[str, Any], list_key: str) -> list[dict[str, Any]]:
    """Follow Kalshi's `cursor` pagination until exhausted, returning all items.

    `list_key` is the response field holding each page's items ("events" or "markets").
    Capped at MAX_PAGES to guard against a malformed/looping cursor. If the cap is reached
    while a cursor still remains, raise rather than silently return partial data — in an app
    whose job is to surface missing/failed data accurately, silent truncation is dangerous.
    """
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        payload = _get(path, page_params)
        items.extend(payload.get(list_key, []) or [])
        cursor = payload.get("cursor") or None
        if not cursor:
            return items
    raise KalshiError(
        f"Pagination cap MAX_PAGES={MAX_PAGES} reached for {path} with a cursor still remaining; "
        f"returning partial data would be silent truncation."
    )


def get_events(series_ticker: str, status: str = "open") -> list[dict[str, Any]]:
    """Fetch all events for a series WITH their nested markets in one paginated stream.

    Using `with_nested_markets=true` avoids an N+1 fan-out to /markets/{ticker}.
    """
    return get_paginated(
        "/events",
        {
            "series_ticker": series_ticker,
            "with_nested_markets": "true",
            "status": status,
            "limit": 200,
        },
        list_key="events",
    )


def discover_tennis_series() -> list[str]:
    """Return the tickers of all tennis series worth scanning for French Open contracts.

    The French Open universe spans match/advancement/winner/set/score series; rather than
    hardcode them we list every series with a tennis prefix (plus the explicitly-named
    tournament-winner tickers) and let the data layer narrow events to the French Open.
    """
    series = get_paginated("/series", {"limit": 200}, list_key="series")
    tickers = [
        s["ticker"]
        for s in series
        if s.get("ticker")
        and (
            s["ticker"].startswith(TENNIS_SERIES_PREFIXES)
            or s["ticker"] in FO_WINNER_TICKERS
        )
    ]
    return sorted(set(tickers))


def get_series_titles(tickers: list[str], max_workers: int = 8) -> dict[str, str]:
    """Fetch the human title for each series (used to build slugged Kalshi web URLs).

    Returns ``{ticker: title}``. A series whose metadata can't be fetched degrades to an empty
    string (the URL builder then falls back to the series page) — this never raises, because a
    missing title must not break the data load.
    """
    titles: dict[str, str] = {}

    def _title(ticker: str) -> str:
        payload = _get(f"/series/{ticker}", {})
        series = payload.get("series") or payload
        return str(series.get("title") or "")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_title, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                titles[ticker] = future.result()
            except Exception:  # noqa: BLE001 - a missing title is non-fatal (URL falls back)
                titles[ticker] = ""
    return titles


def get_events_for_series(
    tickers: list[str], status: str = "open", max_workers: int = 8
) -> tuple[list[tuple[str, list[dict[str, Any]]]], list[tuple[str, str]]]:
    """Fetch open events for many series concurrently.

    Returns ``(results, errors)`` where ``results`` is a list of ``(ticker, events)`` for
    series that loaded, and ``errors`` is a list of ``(ticker, message)`` for series that
    failed. Failures are returned (never silently dropped) so the UI can surface them.
    """
    results: list[tuple[str, list[dict[str, Any]]]] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(get_events, t, status): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results.append((ticker, future.result()))
            except Exception:  # noqa: BLE001 - retry sequentially below before reporting
                failed.append(ticker)

    # Sequential retry pass: most failures are transient (rate limit / dropped connection
    # under load). Anything still failing here is reported to the caller, never dropped.
    errors: list[tuple[str, str]] = []
    for ticker in failed:
        try:
            results.append((ticker, get_events(ticker, status)))
        except Exception as exc:  # noqa: BLE001
            errors.append((ticker, str(exc)))
    return results, errors
