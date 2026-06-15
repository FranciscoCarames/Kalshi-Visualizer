"""Unit tests for the rate-limit throttle and retry/backoff in kalshi_client (no network)."""
from __future__ import annotations

import dataclasses
import time

import pytest

import config
import kalshi_client as kc
import sports


# --- throttle scheduling (pure) ------------------------------------------------------
def test_next_slot_spaces_back_to_back_callers():
    mi = 0.2
    slot1, nxt1 = kc._next_slot(now=100.0, last_next=0.0, min_interval=mi)
    assert slot1 == 100.0          # idle: may fire immediately
    assert nxt1 == pytest.approx(100.2)
    slot2, nxt2 = kc._next_slot(now=100.0, last_next=nxt1, min_interval=mi)
    assert slot2 == pytest.approx(100.2)   # spaced by min_interval
    assert nxt2 == pytest.approx(100.4)


def test_next_slot_does_not_bunch_after_idle():
    # A long idle gap (last_next far in the past) must not let a burst fire before `now`.
    slot, nxt = kc._next_slot(now=500.0, last_next=100.0, min_interval=0.2)
    assert slot == 500.0
    assert nxt == pytest.approx(500.2)


# --- backoff -------------------------------------------------------------------------
class _Resp:
    def __init__(self, status, headers=None, json_data=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def test_backoff_honors_retry_after_and_caps():
    assert kc._backoff_seconds(_Resp(429, {"Retry-After": "2"}), attempt=0) == 2.0
    assert kc._backoff_seconds(_Resp(429, {"Retry-After": "99999"}), attempt=0) == config.BACKOFF_MAX


# --- series-title TTL cache (perf/parallel-sport-fetch) ------------------------------
def test_series_title_cache_hits_and_resets(monkeypatch):
    kc.reset_title_cache()
    calls = {"n": 0}

    def fake_get(path, _params):
        calls["n"] += 1
        return {"series": {"title": "French Open"}}

    monkeypatch.setattr(kc, "_get", fake_get)
    assert kc.get_series_titles(["KXFOWOMEN"]) == {"KXFOWOMEN": "French Open"}
    assert kc.get_series_titles(["KXFOWOMEN"]) == {"KXFOWOMEN": "French Open"}
    assert calls["n"] == 1                          # second call served from cache, no GET
    kc.reset_title_cache()
    assert kc.get_series_titles(["KXFOWOMEN"]) == {"KXFOWOMEN": "French Open"}
    assert calls["n"] == 2                          # reset forces a fresh GET


def test_series_title_cache_short_ttl_for_misses(monkeypatch):
    kc.reset_title_cache()
    monkeypatch.setattr(kc, "_get", lambda *_a: {"series": {}})    # no title -> empty
    now = time.monotonic()
    assert kc.get_series_titles(["KXEMPTY"]) == {"KXEMPTY": ""}
    expiry, title = kc._title_cache["KXEMPTY"]
    assert title == ""
    # an empty/miss result lives only the short TTL (~60s), not the 24h success TTL
    assert expiry - now <= kc.TITLE_TTL_MISS_SECONDS + 1 < kc.TITLE_TTL_OK_SECONDS


def test_backoff_exponential_without_header():
    r = _Resp(500, {})
    assert kc._backoff_seconds(r, 0) == config.BACKOFF_BASE * 1
    assert kc._backoff_seconds(r, 1) == config.BACKOFF_BASE * 2
    assert kc._backoff_seconds(r, 2) == config.BACKOFF_BASE * 4
    assert kc._backoff_seconds(None, 0) == config.BACKOFF_BASE   # network error path


# --- _get retry behaviour (monkeypatched session + no real sleeping) -----------------
def _patch(monkeypatch, responses):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(kc._session, "get", fake_get)
    monkeypatch.setattr(kc.time, "sleep", lambda *_: None)  # no real waiting
    monkeypatch.setattr(kc, "_throttle", lambda: None)      # skip the rate-limit sleep
    return calls


def test_get_retries_on_429_then_succeeds(monkeypatch):
    calls = _patch(monkeypatch, [
        _Resp(429, {"Retry-After": "0"}),
        _Resp(200, json_data={"ok": True}),
    ])
    assert kc._get("/x", {}) == {"ok": True}
    assert len(calls) == 2   # retried once


def test_request_counter_counts_every_attempt_including_retries(monkeypatch):
    # PR 21a: the process-wide request counter ticks PER HTTP attempt, so a retried 429 counts twice.
    _patch(monkeypatch, [_Resp(429, {"Retry-After": "0"}), _Resp(200, json_data={"ok": True})])
    kc.reset_request_count()
    assert kc.request_count() == 0
    kc._get("/x", {})
    assert kc.request_count() == 2   # the 429 attempt + the 200 attempt
    kc.reset_request_count()
    assert kc.request_count() == 0


def test_get_raises_after_max_retries(monkeypatch):
    _patch(monkeypatch, [_Resp(503) for _ in range(config.MAX_RETRIES)])
    with pytest.raises(kc.KalshiError):
        kc._get("/x", {})


def test_get_4xx_raises_without_retry(monkeypatch):
    calls = _patch(monkeypatch, [_Resp(404, text="nope"), _Resp(200, json_data={"ok": True})])
    with pytest.raises(kc.KalshiError):
        kc._get("/x", {})
    assert len(calls) == 1   # a non-429 4xx is fatal immediately (no retry)


# --- discover_series_for_sport: exact_series support (PR 2) ---------------------------
def test_discover_exact_only_short_circuits(monkeypatch):
    """An exact-only sport (no prefixes/winners) returns its exact tickers sorted, WITHOUT scanning
    /series (golf's 4 tickers don't need ~53 pages of GETs)."""
    def boom(*a, **k):
        raise AssertionError("get_paginated must not be called for an exact-only sport")
    monkeypatch.setattr(kc, "get_paginated", boom)
    cfg = dataclasses.replace(sports.TENNIS, sport_id="golfish", series_prefixes=(),
                              winner_tickers=frozenset(), exact_series=frozenset({"KXB", "KXA", "KXC"}))
    assert kc.discover_series_for_sport(cfg) == ["KXA", "KXB", "KXC"]


def test_discover_includes_exact_alongside_prefix(monkeypatch):
    """A sport with both a prefix and exact tickers discovers both; unrelated series are excluded."""
    monkeypatch.setattr(kc, "get_paginated",
                        lambda *a, **k: [{"ticker": "KXNBA"}, {"ticker": "KXEXTRA"}, {"ticker": "KXFOO"}])
    cfg = dataclasses.replace(sports.NBA, exact_series=frozenset({"KXEXTRA"}))
    got = kc.discover_series_for_sport(cfg)
    assert "KXNBA" in got and "KXEXTRA" in got and "KXFOO" not in got


def test_golf_discover_short_circuits_to_four_tickers(monkeypatch):
    """GOLF is exact-only -> discovery returns its 4 tickers sorted WITHOUT scanning /series."""
    def boom(*a, **k):
        raise AssertionError("get_paginated must not be called for golf (exact-only)")
    monkeypatch.setattr(kc, "get_paginated", boom)
    assert kc.discover_series_for_sport(sports.GOLF) == [
        "KXPGATOP10", "KXPGATOP20", "KXPGATOP5", "KXPGATOUR"]


# --- get_orderbook: fixed-point dollar strings -> integer cents (NEVER float) ---------
def test_get_orderbook_parses_fp_dollars_to_cents(monkeypatch):
    monkeypatch.setattr(kc, "_get", lambda *_a: {"orderbook_fp": {
        "yes_dollars": [["0.6000", 100], ["0.6100", 40]],
        "no_dollars": [["0.3700", 80]]}})
    ob = kc.get_orderbook("KXNBA-27-BOS", depth=10)
    assert ob == {"ticker": "KXNBA-27-BOS", "yes": [[60, 100], [61, 40]], "no": [[37, 80]]}
    # cents are exact ints (Decimal-parsed), never floats
    assert all(isinstance(p, int) and isinstance(s, int) for p, s in ob["yes"])


def test_get_orderbook_empty_and_missing_arrays(monkeypatch):
    monkeypatch.setattr(kc, "_get", lambda *_a: {"orderbook_fp": {"yes_dollars": []}})
    assert kc.get_orderbook("TK") == {"ticker": "TK", "yes": [], "no": []}
    monkeypatch.setattr(kc, "_get", lambda *_a: {})        # no orderbook_fp at all (closed market)
    assert kc.get_orderbook("TK") == {"ticker": "TK", "yes": [], "no": []}


def test_get_orderbook_skips_malformed_rungs(monkeypatch):
    monkeypatch.setattr(kc, "_get", lambda *_a: {"orderbook_fp": {"yes_dollars": [
        ["0.5000", 10],          # good
        ["notanumber", 5],       # bad price -> skipped (to_cents returns None)
        ["0.4000", "x"],         # bad size -> skipped
        ["0.3000", 0],           # non-positive size -> skipped
        [42],                    # wrong shape -> skipped
    ], "no_dollars": None}})     # None side -> []
    ob = kc.get_orderbook("TK")
    assert ob["yes"] == [[50, 10]] and ob["no"] == []
