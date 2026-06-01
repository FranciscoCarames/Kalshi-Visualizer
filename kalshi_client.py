"""Thin read-only HTTP client for the Kalshi public market-data API.

Only GET endpoints are used and no authentication is required for market data.
All network/pagination/retry concerns live here so the rest of the app stays clean.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from config import BASE_URL, MAX_PAGES, REQUEST_TIMEOUT, USER_AGENT


class KalshiError(RuntimeError):
    """Raised when the Kalshi API cannot be reached or returns an error response."""


_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Perform a single GET with light retry/backoff on 429 and 5xx responses."""
    url = f"{BASE_URL}{path}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = KalshiError(f"HTTP {resp.status_code} from {url}")
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise KalshiError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        return resp.json()

    raise KalshiError(f"Failed to GET {url} after retries: {last_error}")


def get_paginated(path: str, params: dict[str, Any], list_key: str) -> list[dict[str, Any]]:
    """Follow Kalshi's `cursor` pagination until exhausted, returning all items.

    `list_key` is the response field holding each page's items ("events" or "markets").
    Capped at MAX_PAGES to guard against a malformed/looping cursor.
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
            break
    return items


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
