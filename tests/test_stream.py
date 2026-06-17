"""Real-time Stage 1 — SSE push of completed snapshots.

Covers the three new pieces: the `events` pub/sub broker (coalesce-to-latest + cross-thread bridge), the
`ScanManager.on_complete` notify hook (fires on success, swallowed on failure, never wedges the manager),
and the `GET /api/terminal/stream` endpoint (instant-paint on connect, named `feed` event, presence touch,
auth-gated). No network, no real Kalshi.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import api
import events
import presence
import scan_manager
import store


def _op(oid="a", *, bucket="actionable"):
    return {
        "opportunity_id": oid, "sport": "tennis", "sport_label": "Tennis", "source": "dutch_book",
        "name": "A vs B", "detail": "underround", "tournament": "T1", "tour": "ATP",
        "action_1_text": "Buy YES", "action_2_text": "Buy NO", "exec_gap_c": 5, "exec_min_size": 10,
        "exec_max_profit_dollars": 0.5, "bucket": bucket, "status": "OK", "tradable_now": "Yes",
        "blocked_reason": "", "market_status": "active", "rule_flag": "", "relationship_type": "dutch_book",
        "url": "", "participant_key": "p1",
    }


# --- events broker -------------------------------------------------------------------------------------

def test_offer_coalesces_to_latest():
    events.reset()
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    events._offer(q, "a")
    events._offer(q, "b")                       # drops the stale "a", keeps the newest "b"
    assert q.get_nowait() == "b"
    assert events.dropped_count() == 1
    events.reset()


def test_publish_is_noop_without_a_captured_loop():
    events.reset()
    q = events.subscribe()
    events.publish("x")                         # no loop captured → safe no-op (import/test-client-less path)
    assert q.empty()
    assert events.subscriber_count() == 1
    events.reset()


async def test_publish_bridges_to_all_subscribers():
    events.reset()
    events.set_loop(asyncio.get_running_loop())
    q1, q2 = events.subscribe(), events.subscribe()
    events.publish("hello")
    await asyncio.sleep(0)                       # let call_soon_threadsafe run the fan-out
    assert q1.get_nowait() == "hello"
    assert q2.get_nowait() == "hello"
    events.unsubscribe(q1)
    assert events.subscriber_count() == 1
    events.reset()


# --- ScanManager.on_complete hook ----------------------------------------------------------------------

def _drain(mgr):
    t = mgr._thread
    if t is not None:
        t.join(5)


def test_on_complete_fires_with_snapshot_id_on_success():
    mgr = scan_manager.ScanManager()
    seen: list[int] = []
    mgr.on_complete = seen.append
    mgr.trigger(run_fn=lambda fa: ([], {}, []), write_fn=lambda *a, **k: 42, force=True, wait_timeout=5)
    _drain(mgr)
    assert seen == [42]


def test_on_complete_not_called_on_scan_failure():
    mgr = scan_manager.ScanManager()
    seen: list[int] = []
    mgr.on_complete = seen.append

    def boom(_fa):
        raise RuntimeError("scan blew up")

    mgr.trigger(run_fn=boom, write_fn=lambda *a, **k: 1, force=True, wait_timeout=5)
    _drain(mgr)
    assert seen == []
    assert mgr.status()["status"] == "error"


def test_on_complete_exception_never_wedges_the_manager():
    mgr = scan_manager.ScanManager()

    def explode(_sid):
        raise RuntimeError("notify failed")

    mgr.on_complete = explode
    mgr.trigger(run_fn=lambda fa: ([], {}, []), write_fn=lambda *a, **k: 7, force=True, wait_timeout=5)
    _drain(mgr)
    assert mgr.status()["status"] == "done"           # the scan still succeeded despite the bad hook


# --- GET /api/terminal/stream --------------------------------------------------------------------------
# NOTE: the SSE generator is infinite by design, and FastAPI's TestClient BUFFERS the whole response body
# before returning — so it can never read an endless stream lazily. We therefore exercise the route handler
# and its async body generator DIRECTLY (fast + deterministic), and use TestClient only for the gate check
# (the auth middleware rejects before the handler ever streams).

def _fake_request():
    """A minimal connected Starlette Request: receive() returns a normal request message, so the handler's
    `is_disconnected()` poll reads 'not disconnected' (we only consume a couple of frames, then aclose)."""
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({"type": "http", "method": "GET", "path": "/api/terminal/stream",
                    "headers": [], "query_string": b""}, receive)


async def test_stream_sends_current_feed_on_connect_and_touches_presence(tmp_path):
    db = str(tmp_path / "stream.db")
    presence.reset()
    events.reset()
    store.write_snapshot("2026-06-03 12:00:00 UTC", [_op("a")], frames=[], db_path=db)

    resp = await api.get_terminal_stream(_fake_request(), db_path=db)
    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert presence.recently_active(30) is True              # connect heartbeat fired (synchronously)
    assert events.subscriber_count() == 1                    # the open stream registered a subscriber

    gen = resp.body_iterator
    first = await gen.__anext__()                            # instant paint = the current feed
    assert first.startswith("event: feed\n")
    assert '"snapshot_id"' in first
    await gen.aclose()                                       # tears down → unsubscribe in the finally
    assert events.subscriber_count() == 0
    presence.reset()
    events.reset()


async def test_stream_pushes_a_published_payload(tmp_path):
    events.reset()
    presence.reset()
    events.set_loop(asyncio.get_running_loop())
    resp = await api.get_terminal_stream(_fake_request(), db_path=str(tmp_path / "empty.db"))
    gen = resp.body_iterator
    await gen.__anext__()                                    # consume the instant-paint frame first
    events.publish('{"meta":{"snapshot_id":123},"opps":[]}')   # a scan-completion push
    pushed = await asyncio.wait_for(gen.__anext__(), timeout=5)
    assert pushed.startswith("event: feed\n")
    assert '"snapshot_id":123' in pushed
    await gen.aclose()
    events.reset()


def test_stream_route_is_auth_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    client = TestClient(api.app)
    # No session / token → the deny-by-default gate rejects BEFORE the handler ever streams (so this GET,
    # unlike a real stream read, returns immediately).
    assert client.get("/api/terminal/stream").status_code == 401
