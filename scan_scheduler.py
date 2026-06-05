"""In-process periodic auto-scan loop (NO streamlit, NO webui/api/kalshi imports).

One process-wide daemon thread that triggers the **non-force** scan on a timer, so `python serve.py`
auto-refreshes data without any external scheduler (systemd timer / cron). A SINGLE loop runs per
process regardless of how many browser tabs/viewers are connected — strictly safer than a per-client
timer — and every tick still passes through the ScanManager's TTL / budget / singleflight guards
(the scan function the app injects is `webui.engine.run_scan_now(force=False)`).

The scan function is dependency-INJECTED via `start(scan_fn)` so this module never imports the web/engine
layers; unit tests pass a stub. The module-level `scheduler` singleton is CONSTRUCTED but NOT started at
import time — `start()` is called only from the real `serve.py` runtime, so importing this module (as the
test suite does) never spawns a thread or triggers a scan.

Wake-up uses two separate primitives: `_stop` (terminate the loop) and `_wake` (re-evaluate without
stopping). `set_interval` / `set_enabled` only set `_wake`, so a live config change takes effect promptly
without ever killing the loop.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import config

logger = logging.getLogger(__name__)

ScanFn = Callable[[], object]


class Scheduler:
    """A restartable, reconfigurable periodic trigger for a single injected scan function."""

    def __init__(self, *, interval_s: int, enabled: bool) -> None:
        self.interval_s = int(interval_s)
        self.enabled = bool(enabled)
        self._scan_fn: ScanFn | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()

    # --- lifecycle -------------------------------------------------------------------
    def start(self, scan_fn: ScanFn) -> None:
        """Launch the daemon loop. Idempotent: a second call while running is a no-op."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._scan_fn = scan_fn
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, name="scan-scheduler", daemon=True)
            self._thread.start()

    def stop(self, *, join_timeout: float | None = 2.0) -> None:
        """Signal the loop to terminate and (optionally) join it. Safe to call when not running."""
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and join_timeout is not None:
            t.join(timeout=join_timeout)

    # --- live reconfiguration (wake the loop, never stop it) -------------------------
    def set_interval(self, interval_s: int) -> None:
        self.interval_s = max(1, int(interval_s))
        self._wake.set()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- the loop --------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if self.enabled and self._scan_fn is not None:
                try:
                    self._scan_fn()
                except Exception:  # a transient fetch/scan error must never kill the loop
                    logger.exception("auto-scan tick failed")
            # Wait the current interval, but wake early on stop() / set_interval() / set_enabled().
            self._wake.wait(timeout=self.interval_s)
            self._wake.clear()


# Process-wide singleton — CONSTRUCTED here, but NOT started (no thread, no scan on import).
scheduler = Scheduler(interval_s=config.AUTO_SCAN_DEFAULT_SECONDS,
                      enabled=config.AUTO_SCAN_DEFAULT_ENABLED)
