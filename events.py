"""Process-local SSE pub/sub broker + cross-thread bridge (real-time Stage 1).

A tiny peer of `presence.py`: a set of bounded `asyncio.Queue` subscribers (one per open
`GET /api/terminal/stream` connection) and a thread-safe `publish()` that fans a single pre-built payload
out to all of them. Scans run on a daemon thread (`scan_manager._run`), while the SSE queues live on the
uvicorn event loop — so `publish()` captures the loop at startup (`set_loop`) and hops onto it with
`loop.call_soon_threadsafe`. Until the loop is captured (e.g. `import api` with no server running, or a
`TestClient` used without its context manager), `publish()` is a safe no-op.

**Backpressure = coalesce-to-latest.** Each subscriber queue is `maxsize=1`; a publish to a full queue
drops the stale queued payload and keeps the newest (a slow tab never accumulates unbounded JSON, and only
ever misses INTERMEDIATE snapshots — the next one it reads is always current). `dropped_count()` surfaces
how often that happened for `/metrics`.

Process-local, single-worker only (like the store / throttle / scan_manager). Dependency-free so
`api.py`/`serve.py` import it without pulling in the UI or engine, and it stays trivially unit-testable.
"""
from __future__ import annotations

import asyncio
import threading

_lock = threading.Lock()
_subscribers: set[asyncio.Queue[str]] = set()
_loop: asyncio.AbstractEventLoop | None = None
_dropped = 0   # coalesce/backpressure counter (a slow client made us drop a stale payload)


def set_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Capture the uvicorn event loop at startup so `publish()` (called from the scan thread) can bridge
    onto it. Passing ``None`` (or never calling this) makes `publish()` a no-op — safe for import/tests."""
    global _loop
    with _lock:
        _loop = loop


def subscribe() -> asyncio.Queue[str]:
    """Register a new subscriber and return its bounded (maxsize=1) queue. Call from the event-loop thread
    (the SSE request handler) — `asyncio.Queue` binds to the running loop."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    """Drop a subscriber (on disconnect). Idempotent."""
    with _lock:
        _subscribers.discard(q)


def subscriber_count() -> int:
    """Open SSE subscribers right now (best-effort; per-process)."""
    with _lock:
        return len(_subscribers)


def dropped_count() -> int:
    """How many payloads were coalesced away because a subscriber was still draining the previous one."""
    with _lock:
        return _dropped


def _offer(q: asyncio.Queue[str], payload: str) -> None:
    """Coalesce-to-latest enqueue, RUN ON THE EVENT LOOP THREAD only (so the non-thread-safe queue ops are
    safe). If the consumer hasn't drained the previous payload, drop it and keep the newest."""
    global _dropped
    if q.full():
        try:
            q.get_nowait()
            _dropped += 1
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:                       # racing consumer refilled it; count the drop, never block
        _dropped += 1


def publish(payload: str) -> None:
    """Fan one pre-serialized SSE payload out to every subscriber. Thread-safe: callable from the scan
    daemon thread. No-op until `set_loop` has captured the loop, or once it's closed (shutdown)."""
    with _lock:
        loop = _loop
        subs = list(_subscribers)
    if loop is None or not subs:
        return

    def _fan_out() -> None:                          # runs on the loop thread
        for q in subs:
            _offer(q, payload)

    try:
        loop.call_soon_threadsafe(_fan_out)
    except RuntimeError:                              # loop already closed during shutdown — drop silently
        pass


def reset() -> None:
    """Test hook: clear subscribers, the captured loop, and the drop counter between tests."""
    global _subscribers, _loop, _dropped
    with _lock:
        _subscribers = set()
        _loop = None
        _dropped = 0
