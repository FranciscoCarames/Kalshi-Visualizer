"""Best-effort live viewer count for the NiceGUI dashboard (PR 25b).

A tiny process-local, thread-safe counter incremented on NiceGUI client connect and decremented on
disconnect (`webui/dashboard.py` registers `app.on_connect`/`app.on_disconnect`). Kept top-level and
dependency-free so `api.py` can read it for `/metrics` without importing the UI or the engine — and so it
stays trivially unit-testable. Best-effort by nature: it tracks websocket connections, not unique humans,
and (like the snapshot store + Kalshi throttle) is PER-PROCESS, so it is not aggregated across workers.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_count = 0


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


def reset() -> None:
    """Test hook: clear the counter between tests."""
    global _count
    with _lock:
        _count = 0
