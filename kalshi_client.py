"""Thin read-only HTTP client for the Kalshi public market-data API.

Only GET endpoints are used and no authentication is required for market data.
All network/pagination/retry/rate-limit concerns live here so the rest of the app stays clean.

Rate limiting: Kalshi's Basic (free) tier allows ~20 read requests/second. We cap issuance at
``config.MAX_RPS`` (~75% of that) with a process-wide min-interval limiter. The hard floor against a ban
is the exponential backoff on a 429 — it honours a ``Retry-After`` header WHEN the 429 carries one
(Kalshi may omit it), otherwise it backs off exponentially. The limiter is PROCESS-WIDE ONLY — it bounds
one Python process; multiple processes/containers/replicas each get their own limiter (aggregate =
MAX_RPS x process_count). See config.py.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter

import sports
from config import (
    BACKOFF_BASE,
    BACKOFF_MAX,
    BASE_URL,
    CONCURRENCY,
    MAX_PAGES,
    MAX_RETRIES,
    MAX_RPS,
    REQUEST_TIMEOUT,
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


# --- Process-wide request counter (PR 21a) -------------------------------------------
# Counts every HTTP ATTEMPT (each _session.get, so retries are counted) so a scan can report how many
# Kalshi requests it issued. Process-wide, like the throttle; read via request_count() and zeroed via
# reset_request_count(). Its own lock so it never contends with the rate limiter.
_req_lock = threading.Lock()
_request_count = 0


def _count_request() -> None:
    global _request_count
    with _req_lock:
        _request_count += 1


def request_count() -> int:
    """Total Kalshi HTTP attempts issued by this process since start / the last reset."""
    with _req_lock:
        return _request_count


def reset_request_count() -> None:
    global _request_count
    with _req_lock:
        _request_count = 0


# --- Process-wide retry/backoff counter (Phase 0 instrumentation) -----------------------
# Counts retry-backoffs (429 / 5xx / network) and the seconds slept on them, so a scan can report how much
# retrying it did — the signal for whether MAX_RPS is too aggressive (a rising count after raising MAX_RPS
# means revert). Process-wide, like the request counter; its own lock so it never contends with the others.
_retry_lock = threading.Lock()
_retry_count = 0
_backoff_seconds_total = 0.0


def _count_retry(seconds: float) -> None:
    global _retry_count, _backoff_seconds_total
    with _retry_lock:
        _retry_count += 1
        _backoff_seconds_total += max(0.0, seconds)


def retry_stats() -> tuple[int, float]:
    """(retry-backoffs, total backoff seconds) issued by this process since start / the last reset."""
    with _retry_lock:
        return _retry_count, round(_backoff_seconds_total, 2)


def reset_retry_stats() -> None:
    global _retry_count, _backoff_seconds_total
    with _retry_lock:
        _retry_count = 0
        _backoff_seconds_total = 0.0


# --- Process-wide request throttle ---------------------------------------------------
# Hand every caller a time "slot" spaced 1/MAX_RPS apart, so aggregate issuance across all threads
# in this process never exceeds MAX_RPS. NOTE: process-wide only (see module docstring).
_rl_lock = threading.Lock()
_rl_next = 0.0  # monotonic time at/after which the next request may go out


def _next_slot(now: float, last_next: float, min_interval: float) -> tuple[float, float]:
    """Pure scheduling step (no clock/sleep) so it is unit-testable.

    Returns (slot, new_last_next): the time this request may fire, and the updated floor. An idle gap
    does not let requests bunch up — the slot never precedes ``now``.
    """
    slot = max(now, last_next)
    return slot, slot + min_interval


def _throttle() -> None:
    """Block until this caller's rate-limit slot, capping issuance at MAX_RPS (process-wide)."""
    if MAX_RPS <= 0:
        return
    min_interval = 1.0 / MAX_RPS
    global _rl_next
    with _rl_lock:
        slot, _rl_next = _next_slot(time.monotonic(), _rl_next, min_interval)
    delay = slot - time.monotonic()
    if delay > 0:
        time.sleep(delay)  # sleep OUTSIDE the lock so concurrent callers still get spaced slots


def _backoff_seconds(resp: requests.Response | None, attempt: int) -> float:
    """How long to wait before the next retry: honour a Retry-After header, else exponential."""
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), BACKOFF_MAX)
            except ValueError:
                pass
    return min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET with process-wide rate limiting + retry/backoff on transient errors (429, 5xx, network)."""
    url = f"{BASE_URL}{path}"
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        _throttle()
        _count_request()   # per HTTP attempt (retries counted)
        try:
            resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc or KalshiError("network error")
            _delay = _backoff_seconds(None, attempt)
            _count_retry(_delay)
            time.sleep(_delay)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = KalshiError(f"HTTP {resp.status_code} from {url}")
            _delay = _backoff_seconds(resp, attempt)
            _count_retry(_delay)
            time.sleep(_delay)
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


def discover_series_for_sport(cfg: sports.SportConfig) -> list[str]:
    """Return the tickers of all series worth scanning for one sport.

    Lists every series whose ticker carries one of the sport's prefixes (plus its explicitly-named
    winner tickers, plus any exact-owned tickers) and lets the data layer stamp each event with its
    tournament. Sport-agnostic: the same scan works for tennis, NBA, or any registered sport.
    """
    # Exact-only sports (no prefixes / winner tickers) arrive as new EVENTS inside a fixed set of series,
    # never as new series — so the full set is known up front and we skip the /series scan entirely.
    if cfg.exact_series and not cfg.series_prefixes and not cfg.winner_tickers:
        return sorted(cfg.exact_series)
    series = get_paginated("/series", {"limit": 200}, list_key="series")
    tickers = [
        s["ticker"]
        for s in series
        if s.get("ticker")
        and (
            s["ticker"].startswith(cfg.series_prefixes)
            or s["ticker"] in cfg.winner_tickers
            or s["ticker"] in cfg.exact_series
        )
    ]
    return sorted(set(tickers))


def discover_tennis_series() -> list[str]:
    """Tennis series tickers (back-compat wrapper over `discover_series_for_sport`)."""
    return discover_series_for_sport(sports.TENNIS)


# --- Series-title cache (perf/parallel-sport-fetch) ----------------------------------
# Titles only build slugged web URLs and change rarely, so cache them to skip a /series GET on every
# scan. Thread-safe (read under the parallel per-sport fetch). Non-empty titles live ~24h; an empty
# result (miss/transient failure) lives only ~60s so it self-heals. Cache NEVER affects identity,
# pricing, or detection — only URL building. `reset_title_cache()` is the test/refresh hook.
TITLE_TTL_OK_SECONDS = 24 * 3600
TITLE_TTL_MISS_SECONDS = 60
_title_cache: dict[str, tuple[float, str]] = {}   # UPPER ticker -> (expiry_monotonic, title)
_title_lock = threading.Lock()


def reset_title_cache() -> None:
    """Drop all cached series titles (test hook / forced refresh)."""
    with _title_lock:
        _title_cache.clear()


def get_series_titles(tickers: list[str], max_workers: int = CONCURRENCY) -> dict[str, str]:
    """Fetch the human title for each series (used to build slugged Kalshi web URLs).

    Returns ``{ticker: title}``. A series whose metadata can't be fetched degrades to an empty
    string (the URL builder then falls back to the series page) — this never raises, because a
    missing title must not break the data load. Titles are cached with a TTL (see above) so repeat
    scans skip the /series round-trip.
    """
    titles: dict[str, str] = {}

    def _title(ticker: str) -> str:
        key = ticker.upper()
        now = time.monotonic()
        with _title_lock:
            hit = _title_cache.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]                       # fresh cache entry — skip the GET
        payload = _get(f"/series/{ticker}", {})
        series = payload.get("series") or payload
        title = str(series.get("title") or "")
        ttl = TITLE_TTL_OK_SECONDS if title else TITLE_TTL_MISS_SECONDS
        with _title_lock:
            _title_cache[key] = (now + ttl, title)
        return title

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
    tickers: list[str], status: str = "open", max_workers: int = CONCURRENCY
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

    # Retry the failures ONCE MORE, in PARALLEL (Phase 2). The old pass retried one-at-a-time, so under a
    # rate-limit each failed series could climb the full backoff ladder in series — N failures × ladder
    # serialized into minutes. A single capped parallel round bounds the retry to ~one more fan-out (the
    # process-wide throttle still paces issuance). Anything still failing is reported, never dropped.
    errors: list[tuple[str, str]] = []
    if failed:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            retry_futures = {pool.submit(get_events, t, status): t for t in failed}
            for future in as_completed(retry_futures):
                ticker = retry_futures[future]
                try:
                    results.append((ticker, future.result()))
                except Exception as exc:  # noqa: BLE001
                    errors.append((ticker, str(exc)))
    return results, errors
