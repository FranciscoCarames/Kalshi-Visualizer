"""Process-local scan singleflight + non-blocking trigger (Stage 5 / PR 21b).

ONE entry point for "run a scan" shared by `POST /scan` (REST) AND the NiceGUI "Scan now" button
(`webui.engine.run_scan_now`), so two concurrent triggers collapse to a SINGLE upstream fetch instead of
hammering Kalshi twice. A trigger is **non-blocking by default**: it starts the scan in a background thread
and returns the current status immediately; `wait_timeout>0` joins the in-flight scan up to a bound (then
returns whatever state it's in).

Guards, in order (all overridable by `force=True`):
  - **singleflight** — if a scan is already running, return its status; never start a second.
  - **budget cooldown** — if the previous scan blew a budget cap (time / Kalshi requests / failed series),
    a cooldown window is active and a non-forced trigger is skipped (a pathological scan can't re-fire
    every tick).
  - **TTL** — if the newest STORED snapshot is younger than `SCAN_MIN_INTERVAL_SECONDS`, skip (write
    nothing). Store-backed, so it's sane across a restart.

NO network and NO detection logic here — the scan (`run_fn`) and the persist (`write_fn`) are INJECTED, so
this is unit-testable with fast stubs. Process-local only (single uvicorn worker — see `serve.py`).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import config
import store


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class ScanManager:
    """Singleflight scan runner. `run_fn(fetched_at) -> (unified, coverage, frames)` and
    `write_fn(fetched_at, unified, coverage, frames, db_path) -> snapshot_id` are injected so the manager
    owns the concurrency/guards, not the engine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cooldown_until = 0.0
        self._status: dict[str, Any] = {
            "status": "idle", "since": None, "last_snapshot_id": None, "last_result": None, "reason": None,
        }

    def reset(self) -> None:
        """Test hook: clear in-flight state, cooldown, and status (call between tests)."""
        with self._lock:
            self._thread = None
            self._cooldown_until = 0.0
            self._status = {"status": "idle", "since": None, "last_snapshot_id": None,
                            "last_result": None, "reason": None}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def trigger(self, *, run_fn: Callable[[str], tuple], write_fn: Callable[..., Any],
                force: bool = False, wait_timeout: float = 0.0, db_path: str | None = None
                ) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            thread = self._thread
            if not running:
                now = time.time()
                if not force and self._cooldown_until > now:
                    self._status = {**self._status, "status": "skipped", "reason": "budget cooldown"}
                    return dict(self._status)
                latest = store.latest(db_path=db_path)
                if not force and latest is not None:
                    age = now - (latest.get("fetched_ts") or 0.0)
                    if age < config.SCAN_MIN_INTERVAL_SECONDS:
                        self._status = {**self._status, "status": "skipped", "reason": "ttl"}
                        return dict(self._status)
                fetched_at = _utc_stamp()
                self._status = {"status": "in_progress", "since": now,
                                "last_snapshot_id": (latest or {}).get("snapshot_id"),
                                "last_result": None, "reason": None}
                self._thread = threading.Thread(
                    target=self._run, args=(run_fn, write_fn, db_path, fetched_at), daemon=True)
                self._thread.start()
                thread = self._thread
        # Outside the lock: optionally wait for the (this or already-running) scan, bounded.
        if thread is not None and wait_timeout and wait_timeout > 0:
            thread.join(wait_timeout)
        return self.status()

    def _run(self, run_fn: Callable[[str], tuple], write_fn: Callable[..., Any],
             db_path: str | None, fetched_at: str) -> None:
        start = time.time()
        try:
            unified, coverage, frames = run_fn(fetched_at)
            sid = write_fn(fetched_at, unified, coverage, frames, db_path)
            ok, result = True, dict(coverage or {})
        except Exception as exc:                       # a scan failure must not wedge the manager
            sid, ok, result = None, False, {"error": str(exc)}
        duration = time.time() - start
        with self._lock:
            self._status = {"status": "done" if ok else "error", "since": self._status.get("since"),
                            "last_snapshot_id": sid, "last_result": result, "reason": None}
            if ok and _over_budget(result, duration):
                self._cooldown_until = time.time() + config.SCAN_BUDGET_COOLDOWN_SECONDS
                self._status["reason"] = "budget exceeded; cooling down"
            self._thread = None


def _over_budget(coverage: dict[str, Any], duration: float) -> bool:
    return (duration > config.SCAN_BUDGET_MAX_SECONDS
            or (coverage.get("kalshi_requests") or 0) > config.SCAN_BUDGET_MAX_REQUESTS
            or (coverage.get("failed") or 0) > config.SCAN_BUDGET_MAX_FAILED_SERIES)


# The single process-wide instance shared by POST /scan and webui.run_scan_now.
manager = ScanManager()
