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


def test_terminal_heartbeat_window_is_monotonic(monkeypatch):
    """recently_active() is true within the window, false after, and uses monotonic time (clock-jump safe)."""
    presence.reset()
    assert presence.recently_active(30) is False                 # never touched
    clock = [1000.0]
    monkeypatch.setattr(presence.time, "monotonic", lambda: clock[0])
    presence.touch()
    assert presence.recently_active(30) is True
    clock[0] += 29
    assert presence.recently_active(30) is True                  # still inside the window
    clock[0] += 2                                                # 31s since touch
    assert presence.recently_active(30) is False                 # expired
    presence.reset()
    assert presence.recently_active(30) is False                 # reset clears the heartbeat


def test_reset_clears_both_signals():
    presence.reset()
    presence.connect()
    presence.touch()
    assert presence.count() == 1 and presence.recently_active(30) is True
    presence.reset()
    assert presence.count() == 0 and presence.recently_active(30) is False


def test_idle_gate_composition():
    """The serve.py gate: scan when a NiceGUI viewer is connected OR the terminal polled recently."""
    presence.reset()
    gate = lambda: presence.count() > 0 or presence.recently_active(30)   # noqa: E731 (mirrors serve.py)
    assert gate() is False                                       # nobody → paused
    presence.connect()
    assert gate() is True                                        # NiceGUI viewer → scan
    presence.disconnect()
    assert gate() is False
    presence.touch()
    assert gate() is True                                        # terminal recent → scan
    presence.reset()
