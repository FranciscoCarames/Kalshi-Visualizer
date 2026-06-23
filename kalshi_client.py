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

import data
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


def _scrub_body(text: str) -> str:
    """Sanitize an upstream error body before it lands in an exception / `last_scan_error` surface. Control
    chars + newlines are collapsed to single spaces (so an HTML/Cloudflare page can't inject multi-line
    structure into logs or the OPS view) and the result is capped short. Defense-in-depth: the endpoints
    that expose `last_scan_error` (`/metrics`, `/coverage`, `/readyz`, `/scan/status`) are auth-gated too."""
    collapsed = " ".join((text or "").split())
    return collapsed[:120]


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
            if attempt < MAX_RETRIES - 1:                  # don't sleep after the FINAL attempt — we raise next
                _delay = _backoff_seconds(None, attempt)
                _count_retry(_delay)                       # main: retry/backoff instrumentation
                time.sleep(_delay)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = KalshiError(f"HTTP {resp.status_code} from {url}")
            if attempt < MAX_RETRIES - 1:                  # ditto: a final 429/5xx raises, no point sleeping
                _delay = _backoff_seconds(resp, attempt)
                _count_retry(_delay)                       # main: retry/backoff instrumentation
                time.sleep(_delay)
            continue
        if resp.status_code >= 400:
            raise KalshiError(f"HTTP {resp.status_code} from {url}: {_scrub_body(resp.text)}")
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


def _parse_book_side(levels: Any) -> list[list[int]]:
    """Parse one side of the ``orderbook_fp`` book ([[price$, size], …]) into ``[[price_c, size], …]`` —
    fixed-point dollar STRINGS → exact integer cents via ``data.to_cents`` (NEVER float). A malformed rung
    (bad price, non-numeric size, non-positive size) is SKIPPED, not raised; a non-list yields []. Kalshi
    returns levels ascending (best bid last); order is preserved verbatim for the caller to interpret."""
    out: list[list[int]] = []
    if not isinstance(levels, list):
        return out
    for lvl in levels:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        price_c = data.to_cents(lvl[0])
        try:
            size = int(round(float(lvl[1])))
        except (TypeError, ValueError):
            continue
        if price_c is None or size <= 0:
            continue
        out.append([price_c, size])
    return out


def get_orderbook(ticker: str, depth: int = 10) -> dict[str, Any]:
    """Fetch one market's resting order book (read-only market data; no auth required, like /events).

    Endpoint: ``GET /markets/{ticker}/orderbook?depth=N`` → ``{"orderbook_fp": {"yes_dollars":
    [[price$,size]…], "no_dollars": [[price$,size]…]}}`` — resting BIDS on each side, prices as fixed-point
    dollar strings, ascending (best bid last). Returns ``{"ticker", "yes": [[price_c,size]…],
    "no": [[price_c,size]…]}`` with prices in integer cents. An empty/closed book yields empty sides
    (honest empty — never fabricated). Network/4xx/5xx surface as ``KalshiError`` (the caller degrades)."""
    payload = _get(f"/markets/{ticker}/orderbook", {"depth": depth})
    ob = (payload or {}).get("orderbook_fp") or {}
    return {
        "ticker": ticker,
        "yes": _parse_book_side(ob.get("yes_dollars")),
        "no": _parse_book_side(ob.get("no_dollars")),
    }


def get_market(ticker: str) -> dict[str, Any]:
    """Fetch one market's full record (read-only market data; no auth required, like /events).

    Endpoint: ``GET /markets/{ticker}`` → ``{"market": {...}}``. Returns the raw ``market`` dict, which
    after determination/settlement carries the settlement fields the forward-test harness scores from:
    ``status`` (``active``/``closed``/``determined``/``finalized``/``settled``/…), ``result`` (``"yes"``/
    ``"no"`` for a settled binary market, ``""`` while still active), and — when finalized —
    ``settlement_value_dollars`` / ``settlement_ts``. Used ONLY to read settlement outcomes (no trading).
    An absent ``market`` yields ``{}``. Network/4xx/5xx surface as ``KalshiError`` (the caller degrades)."""
    payload = _get(f"/markets/{ticker}", {})
    return (payload or {}).get("market") or {}


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


# --- Series-meta cache (titles + DISPLAY-ONLY fee metadata) --------------------------
# The /series/{ticker} GET (made to build slugged web URLs) also returns `fee_type` + `fee_multiplier`
# (live-confirmed 2026-06-16), so we cache the whole small meta dict and serve both titles and fee rates
# from one fetch — zero extra requests for fee data. Thread-safe (read under the parallel per-sport
# fetch). A successful fetch lives ~24h; an empty/failed one lives ~60s so it self-heals. The cache NEVER
# affects identity, pricing, or detection — titles build URLs and fees are display-only.
# `reset_title_cache()` is the test/refresh hook.
TITLE_TTL_OK_SECONDS = 24 * 3600
TITLE_TTL_MISS_SECONDS = 60
# UPPER ticker -> (expiry_monotonic, {title, fee_type, fee_multiplier}). fee_type/fee_multiplier are None
# when the series payload omits them (the fee resolver then marks the estimate incomplete — never assumes).
_title_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_title_lock = threading.Lock()


def reset_title_cache() -> None:
    """Drop all cached series meta (test hook / forced refresh)."""
    with _title_lock:
        _title_cache.clear()


def get_series_meta(tickers: list[str], max_workers: int = CONCURRENCY) -> dict[str, dict[str, Any]]:
    """Fetch ``{UPPER_ticker: {"title", "fee_type", "fee_multiplier"}}`` for each series in ONE GET each.

    `title` builds slugged web URLs; `fee_type`/`fee_multiplier` drive the DISPLAY-ONLY fee estimate. A
    series whose metadata can't be fetched degrades to an empty dict (title "", fees None) — this never
    raises, because a missing title/fee must not break the data load. Cached with a TTL so repeat scans
    skip the round-trip.
    """
    out: dict[str, dict[str, Any]] = {}

    def _meta(ticker: str) -> dict[str, Any]:
        key = ticker.upper()
        now = time.monotonic()
        with _title_lock:
            hit = _title_cache.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]                       # fresh cache entry — skip the GET
        payload = _get(f"/series/{ticker}", {})
        series = payload.get("series") or payload
        title = str(series.get("title") or "")
        meta = {
            "title": title,
            "fee_type": series.get("fee_type"),            # None when absent -> resolver marks incomplete
            "fee_multiplier": series.get("fee_multiplier"),
        }
        ttl = TITLE_TTL_OK_SECONDS if title else TITLE_TTL_MISS_SECONDS
        with _title_lock:
            _title_cache[key] = (now + ttl, meta)
        return meta

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_meta, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                out[ticker] = future.result()
            except Exception:  # noqa: BLE001 - missing meta is non-fatal (URL + fee fall back)
                out[ticker] = {"title": "", "fee_type": None, "fee_multiplier": None}
    return out


def get_series_titles(tickers: list[str], max_workers: int = CONCURRENCY) -> dict[str, str]:
    """Back-compat wrapper over :func:`get_series_meta` returning just ``{ticker: title}``."""
    return {t: m.get("title", "") for t, m in get_series_meta(tickers, max_workers).items()}


# --- Event-level fee overrides (DISPLAY-ONLY) ----------------------------------------
# Event fees override the parent series fee. The event OBJECT does NOT expose the override fields
# (live-confirmed: absent even with with_nested_markets); the only source is GET /events/fee_changes
# (currently returns []). ONE unfiltered, page-capped sweep builds {event_ticker: latest override} and is
# fail-closed: any error/cap -> {} so a scan never breaks and the UI falls back to series-level + a label.
_fee_override_cache: dict[str, Any] = {}          # {"expiry": monotonic, "map": {...}, "status": str}
_fee_override_lock = threading.Lock()


def reset_fee_override_cache() -> None:
    """Drop the cached event-fee-override sweep (test hook / forced refresh)."""
    with _fee_override_lock:
        _fee_override_cache.clear()


def _pick_active_override(changes: list[dict[str, Any]], now_iso: str) -> dict[str, Any]:
    """From a single event's fee-change records, pick the one with the latest scheduled_ts <= now."""
    active = [c for c in changes if str(c.get("scheduled_ts") or "") <= now_iso]
    if not active:
        return {}
    latest = max(active, key=lambda c: str(c.get("scheduled_ts") or ""))
    return {
        "fee_type_override": latest.get("fee_type_override"),
        "fee_multiplier_override": latest.get("fee_multiplier_override"),
        "scheduled_ts": latest.get("scheduled_ts"),
    }


def get_event_fee_overrides(max_pages: int | None = None) -> tuple[dict[str, dict[str, Any]], str]:
    """Sweep ``GET /events/fee_changes`` and return ``({UPPER_event_ticker: active_override}, status)``.

    ONE unfiltered paginated sweep, page-capped (``config.FEE_EVENT_OVERRIDE_MAX_PAGES``); per event keeps
    the latest change with ``scheduled_ts <= now``. ``status`` ∈ {"ok", "capped", "failed", "disabled"}.
    Fail-closed: on any error or cap-hit the map is ``{}`` and the caller uses series-level fees + a label.
    TTL-cached like series meta.
    """
    import config as _cfg
    if not getattr(_cfg, "FEE_EVENT_OVERRIDE_FETCH_ENABLED", True):
        return {}, "disabled"
    cap = max_pages if max_pages is not None else getattr(_cfg, "FEE_EVENT_OVERRIDE_MAX_PAGES", 10)
    now = time.monotonic()
    with _fee_override_lock:
        cached = _fee_override_cache.get("map")
        if cached is not None and _fee_override_cache.get("expiry", 0) > now:
            return cached, _fee_override_cache.get("status", "ok")

    by_event: dict[str, list[dict[str, Any]]] = {}
    status = "ok"
    try:
        cursor: str | None = None
        for _ in range(cap):
            params: dict[str, Any] = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            payload = _get("/events/fee_changes", params)
            for rec in payload.get("event_fee_changes", []) or []:
                et = str(rec.get("event_ticker") or "").upper()
                if et:
                    by_event.setdefault(et, []).append(rec)
            cursor = payload.get("cursor") or None
            if not cursor:
                break
        else:
            if cursor:                              # cap hit with a cursor still pending -> fail closed
                status = "capped"
                by_event = {}
    except Exception:  # noqa: BLE001 - an override fetch failure must never break a scan
        status = "failed"
        by_event = {}

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = {et: _pick_active_override(recs, now_iso) for et, recs in by_event.items()}
    result = {et: ov for et, ov in result.items() if ov}      # drop events with no active change
    ttl = TITLE_TTL_OK_SECONDS if status == "ok" else TITLE_TTL_MISS_SECONDS
    with _fee_override_lock:
        _fee_override_cache.update({"expiry": now + ttl, "map": result, "status": status})
    return result, status


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
