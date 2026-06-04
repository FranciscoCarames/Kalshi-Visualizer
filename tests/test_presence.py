"""Unit tests for presence (PR 25b) — the best-effort live viewer counter (thread-safe, floored at 0)."""
from __future__ import annotations

import presence


def test_connect_disconnect_count_and_floor():
    presence.reset()
    assert presence.count() == 0
    presence.connect()
    presence.connect()
    assert presence.count() == 2
    presence.disconnect()
    assert presence.count() == 1
    presence.disconnect()
    presence.disconnect()      # extra disconnect must not drive it negative
    assert presence.count() == 0
    presence.reset()
