"""Unit tests for the in-process auto-scan scheduler (scan_scheduler.py) and the related config knobs.

Deterministic: the injected scan_fn signals via threading.Events, so tests wait on a condition with a
timeout rather than sleeping a fixed duration. No network, no NiceGUI, no real scan.
"""
from __future__ import annotations

import threading
import time

import config
import scan_scheduler
from scan_scheduler import Scheduler


def _wait(cond, timeout=2.0, interval=0.005):
    """Poll `cond()` until true or timeout; returns the final truthiness."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(interval)
    return cond()


def test_module_singleton_not_started_on_import():
    # Importing the module must NOT spawn a thread or trigger a scan.
    assert isinstance(scan_scheduler.scheduler, Scheduler)
    assert scan_scheduler.scheduler.running is False


def test_enabled_scans_repeatedly():
    calls = []
    fired = threading.Event()

    def scan_fn():
        calls.append(1)
        fired.set()

    s = Scheduler(interval_s=1, enabled=True)
    # Tiny cadence for the test; the first tick fires immediately (loop scans at the top).
    s.interval_s = 0.02
    try:
        s.start(scan_fn)
        assert fired.wait(2.0), "scan_fn was never called while enabled"
        assert _wait(lambda: len(calls) >= 3), f"expected repeated ticks, got {len(calls)}"
    finally:
        s.stop()


def test_disabled_never_scans():
    calls = []
    s = Scheduler(interval_s=0.02, enabled=False)
    try:
        s.start(lambda: calls.append(1))
        # Give the loop ample chances to (wrongly) fire; it must stay at zero.
        assert _wait(lambda: len(calls) > 0, timeout=0.3) is False
        assert calls == []
    finally:
        s.stop()


def test_gate_false_skips_scans():
    # P4: a gate returning False (e.g. presence.count()==0) pauses ticks even while enabled.
    calls = []
    s = Scheduler(interval_s=0.02, enabled=True)
    try:
        s.start(lambda: calls.append(1), gate=lambda: False)
        assert _wait(lambda: len(calls) > 0, timeout=0.3) is False
        assert calls == []
    finally:
        s.stop()


def test_gate_resumes_when_it_turns_true():
    # P4: when the gate opens (a viewer connects) the loop resumes on the next tick — no restart.
    calls = []
    fired = threading.Event()
    watching = {"on": False}

    def scan_fn():
        calls.append(1)
        fired.set()

    s = Scheduler(interval_s=0.02, enabled=True)
    try:
        s.start(scan_fn, gate=lambda: watching["on"])
        assert _wait(lambda: len(calls) > 0, timeout=0.2) is False   # gated off -> no scan
        watching["on"] = True                                        # viewer connects
        assert fired.wait(2.0), "scan_fn never ran after the gate opened"
    finally:
        s.stop()


def test_presence_gate_flag_default_on():
    assert config.AUTO_SCAN_PAUSE_WHEN_IDLE is True


def test_set_enabled_toggles_live():
    calls = []
    fired = threading.Event()

    def scan_fn():
        calls.append(1)
        fired.set()

    s = Scheduler(interval_s=0.02, enabled=False)
    try:
        s.start(scan_fn)
        assert _wait(lambda: len(calls) > 0, timeout=0.2) is False  # disabled → idle
        s.set_enabled(True)
        assert fired.wait(2.0), "enabling did not wake the loop into scanning"
        n = len(calls)
        s.set_enabled(False)
        # After disabling, the count must plateau (allow one in-flight tick).
        time.sleep(0.15)
        assert len(calls) <= n + 1
    finally:
        s.stop()


def test_set_interval_wakes_without_stopping():
    calls = []
    s = Scheduler(interval_s=100, enabled=True)  # huge interval: only the immediate first tick, then waits
    try:
        s.start(scan_fn=lambda: calls.append(1))
        assert _wait(lambda: len(calls) >= 1), "expected the immediate first tick"
        n = len(calls)
        s.set_interval(0.02)  # should wake the loop (not stop it) → more ticks soon
        assert _wait(lambda: len(calls) > n), "set_interval did not wake the loop"
        assert s.running is True
    finally:
        s.stop()


def test_double_start_is_idempotent():
    s = Scheduler(interval_s=0.05, enabled=True)
    try:
        s.start(lambda: None)
        t1 = s._thread
        s.start(lambda: None)  # second call while alive → no-op
        assert s._thread is t1
    finally:
        s.stop()


def test_scan_fn_exception_does_not_kill_loop():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("transient fetch error")

    s = Scheduler(interval_s=0.02, enabled=True)
    try:
        s.start(boom)
        # The loop must keep calling despite every tick raising.
        assert _wait(lambda: len(calls) >= 3, timeout=2.0), f"loop died after {len(calls)} ticks"
        assert s.running is True
    finally:
        s.stop()


def test_stop_terminates_loop():
    s = Scheduler(interval_s=0.02, enabled=True)
    s.start(lambda: None)
    assert s.running is True
    s.stop()
    assert s.running is False


# --- config knobs stay coherent with the scheduler / TTL contract -----------------------
def test_config_rate_and_scheduler_knobs():
    assert config.MAX_RPS == 15
    opts = config.AUTO_SCAN_INTERVAL_OPTIONS
    assert opts == sorted(opts) and len(opts) == len(set(opts))
    # The fastest selectable interval must not be TTL-skipped.
    assert config.SCAN_MIN_INTERVAL_SECONDS <= min(opts)
    assert config.AUTO_SCAN_DEFAULT_SECONDS in opts
    assert isinstance(config.AUTO_SCAN_DEFAULT_ENABLED, bool)
