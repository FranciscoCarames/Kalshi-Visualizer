"""Best-effort live viewer presence (PR 25b + terminal-feed heartbeat).

Two process-local, thread-safe signals the scan scheduler's idle gate reads:
- `count()` — NiceGUI websocket viewers (`webui/dashboard.py` registers `app.on_connect`/`on_disconnect`).
- `recently_active()` — the Terminal Pro SPA at `/terminal` is NOT a NiceGUI client, so it can't bump the
  counter; instead its feed poll (`GET /api/terminal/feed`) calls `touch()`, and the gate treats a recent
  touch as presence so the background scan refreshes the snapshot while the SPA is open.

Kept top-level and dependency-free so `api.py`/`serve.py` read it without importing the UI or engine, and so
it stays trivially unit-testable. Best-effort + PER-PROCESS (not aggregated across workers). The heartbeat
uses `time.monotonic()` (NOT wall-clock) so a system clock change can never wedge the gate active/expired.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_count = 0
_last_touch: float | None = None   # monotonic seconds of the last terminal-feed poll, or None if never


def connect() -> None:
    """Register a newly-connected viewer."""
    global _count
    with _lock:
        _count += 1


def disconnect() -> None:
    """Register a viewer leaving; floored at 0 so a stray disconnect never drives it negative."""
    global _count
    with _lock:
        _count = max(0, _count - 1)


def count() -> int:
    """The current best-effort viewer count."""
    with _lock:
        return _count


def touch() -> None:
    """Record terminal-feed activity (called only by `GET /api/terminal/feed`). Monotonic timestamp."""
    global _last_touch
    with _lock:
        _last_touch = time.monotonic()


def recently_active(window_s: float) -> bool:
    """Whether the terminal feed was polled within the last `window_s` seconds (monotonic). False if never
    touched. Read by `serve.py`'s scan-gate so an open SPA keeps the scheduler scanning; idle re-pauses."""
    with _lock:
        if _last_touch is None:
            return False
        return (time.monotonic() - _last_touch) < window_s


def reset() -> None:
    """Test hook: clear BOTH the NiceGUI counter and the terminal heartbeat between tests."""
    global _count, _last_touch
    with _lock:
        _count = 0
        _last_touch = None
