"""A tiny process-local sliding-window rate limiter (PR 26b).

Used to cap how often the HTTP `POST /scan` endpoint can be triggered, independent of the scan-manager's
own TTL/singleflight (which dedups the *actual* scan). Kept top-level and dependency-free so `api.py`
imports it with no cycle, and PURE in the sense that the clock is INJECTED (`allow(now)`) — there is no
internal `time.time()` call — so it unit-tests deterministically. Thread-safe via a lock. Process-local
only (like the snapshot store + Kalshi throttle): each worker has its own window.
"""
from __future__ import annotations

import threading


class SlidingWindow:
    """Allow at most `max_events` calls per `window_s` seconds. `allow(now)` records the call and returns
    True when under the cap, else False (without recording). `now` is caller-supplied epoch seconds."""

    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._events: list[float] = []
        self._lock = threading.Lock()

    def allow(self, now: float) -> bool:
        with self._lock:
            cutoff = now - self.window_s
            self._events = [t for t in self._events if t > cutoff]
            if len(self._events) >= self.max_events:
                return False
            self._events.append(now)
            return True

    def reset(self) -> None:
        """Test hook: clear the recorded events."""
        with self._lock:
            self._events = []
