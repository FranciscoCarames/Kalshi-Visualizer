"""Unit tests for the process-local scan singleflight (PR 21b). Fast stubs — no network, no real engine.

run_fn / write_fn are injected, so these exercise the manager's concurrency + guards (singleflight, TTL,
budget cooldown, bounded wait) directly. Threads are real but fast and deterministically gated with Events
/ short sleeps."""
from __future__ import annotations

import threading
import time

import config
import store
from scan_manager import ScanManager, _over_budget

_OPP = {"opportunity_id": "a", "bucket": "clean"}


def _run_fn(calls, *, coverage=None):
    def run_fn(fetched_at):
        calls.append(fetched_at)
        return ("UNIFIED", coverage or {"scanned": 3, "failed": 0, "kalshi_requests": 5}, ["FRAMES"])
    return run_fn


def _write_fn(writes):
    def write_fn(fetched_at, unified, coverage, frames, db_path):
        writes.append(coverage)
        return len(writes)        # a fake snapshot id
    return write_fn


def _wait_done(m, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if m.status()["status"] in ("done", "error", "skipped"):
            return
        time.sleep(0.01)


def test_singleflight_two_triggers_run_once(tmp_path):
    m = ScanManager()
    db = str(tmp_path / "s.db")
    calls, writes = [], []
    started, release = threading.Event(), threading.Event()

    def blocking_run(fetched_at):
        calls.append(fetched_at)
        started.set()
        release.wait(3)
        return ("U", {"scanned": 1}, [])

    st1 = m.trigger(run_fn=blocking_run, write_fn=_write_fn(writes), db_path=db)
    assert st1["status"] == "in_progress"
    assert started.wait(3)
    # Second trigger WHILE the first is in flight -> singleflight: no second run started.
    st2 = m.trigger(run_fn=blocking_run, write_fn=_write_fn(writes), db_path=db)
    assert st2["status"] == "in_progress"
    release.set()
    _wait_done(m)
    assert m.status()["status"] == "done"
    assert len(calls) == 1 and len(writes) == 1          # one upstream fetch despite two triggers


def test_ttl_skip_and_force_override(tmp_path):
    m = ScanManager()
    db = str(tmp_path / "s.db")
    store.write_snapshot(time.time(), [_OPP], db_path=db)   # a very recent snapshot
    calls = []
    st = m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), db_path=db)
    assert st["status"] == "skipped" and st["reason"] == "ttl" and calls == []   # TTL: wrote/ran nothing
    st2 = m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), force=True, wait_timeout=3, db_path=db)
    assert st2["status"] == "done" and len(calls) == 1                           # force overrode the TTL


def test_wait_timeout_returns_in_progress_then_completes(tmp_path):
    m = ScanManager()
    db = str(tmp_path / "s.db")

    def slow(fetched_at):
        time.sleep(0.4)
        return ("U", {}, [])

    st = m.trigger(run_fn=slow, write_fn=_write_fn([]), wait_timeout=0.05, db_path=db)
    assert st["status"] == "in_progress"        # didn't finish within the bound -> still 202/in_progress
    _wait_done(m)
    assert m.status()["status"] == "done"


def test_budget_cooldown_skips_next_until_force(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCAN_BUDGET_MAX_REQUESTS", 1)   # the stub reports 5 -> blows the budget
    m = ScanManager()
    db = str(tmp_path / "s.db")
    calls = []
    m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), wait_timeout=3, db_path=db)
    assert m.status()["status"] == "done" and m.status()["reason"] == "budget exceeded; cooling down"
    # The stub write_fn never touched the store, so there's no TTL skip — the COOLDOWN is what skips this.
    st = m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), db_path=db)
    assert st["status"] == "skipped" and st["reason"] == "budget cooldown" and len(calls) == 1
    st2 = m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), force=True, wait_timeout=3, db_path=db)
    assert st2["status"] == "done" and len(calls) == 2          # force overrides the cooldown


def test_run_failure_does_not_wedge_manager(tmp_path):
    m = ScanManager()
    db = str(tmp_path / "s.db")

    def boom(fetched_at):
        raise RuntimeError("scan blew up")

    m.trigger(run_fn=boom, write_fn=_write_fn([]), wait_timeout=3, db_path=db)
    assert m.status()["status"] == "error" and "blew up" in m.status()["last_result"]["error"]
    # A subsequent trigger can still run (the failed thread was cleared).
    calls = []
    st = m.trigger(run_fn=_run_fn(calls), write_fn=_write_fn([]), force=True, wait_timeout=3, db_path=db)
    assert st["status"] == "done" and len(calls) == 1


def test_over_budget_helper():
    assert _over_budget({"kalshi_requests": config.SCAN_BUDGET_MAX_REQUESTS + 1}, 0.0) is True
    assert _over_budget({}, config.SCAN_BUDGET_MAX_SECONDS + 1) is True
    assert _over_budget({"failed": config.SCAN_BUDGET_MAX_FAILED_SERIES + 1}, 0.0) is True
    assert _over_budget({"kalshi_requests": 1, "failed": 0}, 1.0) is False
