"""Unit tests for ratelimit.SlidingWindow (PR 26b) — deterministic via an injected clock."""
from __future__ import annotations

from ratelimit import SlidingWindow


def test_allows_up_to_cap_then_blocks_until_window_passes():
    w = SlidingWindow(max_events=2, window_s=10)
    assert w.allow(100.0) is True
    assert w.allow(101.0) is True
    assert w.allow(102.0) is False        # 3rd within the 10s window → blocked
    assert w.allow(109.0) is False        # still inside the window
    assert w.allow(112.0) is True         # the 100.0 event aged out (>10s) → room again


def test_reset_clears_events():
    w = SlidingWindow(max_events=1, window_s=60)
    assert w.allow(0.0) is True
    assert w.allow(1.0) is False
    w.reset()
    assert w.allow(2.0) is True
