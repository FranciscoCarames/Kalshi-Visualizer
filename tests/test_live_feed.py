"""Real-time Stage 2A — live Kalshi WebSocket collector (SHADOW mode), fixture-tested (no live socket).

Covers the pieces that must be right BEFORE any live price can touch the UI: the RSA-PSS handshake
signature, the order-book BUILDER (snapshot + single-level deltas + seq-gap desync + resync), the
reciprocal top-of-book derivation (empty side → 0.00/1.00, never a fake 50%), the price cache, the
message dispatch routing, the default-OFF contract, and the read-only guarantee (no trading endpoints).
"""
from __future__ import annotations

import pytest

import config
import live_feed


@pytest.fixture(autouse=True)
def _clean():
    live_feed.reset()
    yield
    live_feed.reset()


# --- RSA-PSS handshake signature ----------------------------------------------------------------------

def _gen_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    return key, pem


def test_sign_is_deterministic_path_and_verifies():
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key, pem = _gen_key()
    sig_b64 = live_feed._sign(pem, "1700000000000", "GET", "/trade-api/ws/v2")
    # The signature verifies against the public key for the exact signed string.
    key.public_key().verify(
        base64.b64decode(sig_b64),
        b"1700000000000GET/trade-api/ws/v2",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())


def test_auth_headers_shape():
    _key, pem = _gen_key()
    h = live_feed.auth_headers("kid-123", pem, now_ms=1700000000000)
    assert h["KALSHI-ACCESS-KEY"] == "kid-123"
    assert h["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    assert h["KALSHI-ACCESS-SIGNATURE"]            # non-empty base64
    assert "kid-123" not in h["KALSHI-ACCESS-SIGNATURE"]


# --- the order-book builder ---------------------------------------------------------------------------

def test_snapshot_builds_reciprocal_top_of_book():
    ob = live_feed.OrderBook()
    # YES bids up to 60¢, NO bids up to 38¢ → yes_ask = 100-38 = 62, no_ask = 100-60 = 40.
    ob.apply_snapshot([["0.55", 10], ["0.60", 5]], [["0.30", 8], ["0.38", 4]], 100, now=1.0)
    d = ob.derived()
    assert (d["yes_bid_c"], d["yes_bid_size"]) == (60, 5)
    assert (d["no_bid_c"], d["no_bid_size"]) == (38, 4)
    assert (d["yes_ask_c"], d["yes_ask_size"]) == (62, 4)     # 100 − best no bid, size@that no bid
    assert (d["no_ask_c"], d["no_ask_size"]) == (40, 5)       # 100 − best yes bid, size@that yes bid
    assert d["synced"] is True and d["seq"] == 100


def test_empty_side_is_zero_one_never_fake_fifty():
    ob = live_feed.OrderBook()
    ob.apply_snapshot([], [], 1, now=1.0)
    d = ob.derived()
    assert d["yes_bid_c"] == 0 and d["yes_ask_c"] == 100        # 0.00 / 1.00 sentinel, not 50
    assert d["no_bid_c"] == 0 and d["no_ask_c"] == 100


def test_delta_add_update_remove_moves_top_of_book():
    ob = live_feed.OrderBook()
    ob.apply_snapshot([["0.50", 10]], [], 5, now=1.0)
    assert ob.apply_delta("yes", "0.55", 7, 6, now=1.0) is True    # add a better bid
    assert ob.derived()["yes_bid_c"] == 55
    assert ob.apply_delta("yes", "0.55", -7, 7, now=1.0) is True   # remove it → back to 50
    assert ob.derived()["yes_bid_c"] == 50
    assert ob.apply_delta("yes", "0.50", 3, 8, now=1.0) is True    # update size 10→13
    assert ob.derived()["yes_bid_size"] == 13


def test_seq_gap_desyncs_and_blocks_until_reseed():
    ob = live_feed.OrderBook()
    ob.apply_snapshot([["0.50", 10]], [], 5, now=1.0)
    assert ob.apply_delta("yes", "0.60", 1, 99, now=1.0) is False  # seq jumped 5→99 → gap
    assert ob.synced is False
    # a delta on a desynced book is ignored (returns False) until a fresh snapshot reseeds it
    assert ob.apply_delta("yes", "0.60", 1, 100, now=1.0) is False
    ob.apply_snapshot([["0.60", 2]], [], 200, now=2.0)
    assert ob.synced is True and ob.derived()["yes_bid_c"] == 60


def test_rest_shape_matches_get_orderbook_ascending():
    ob = live_feed.OrderBook()
    ob.apply_snapshot([["0.60", 5], ["0.50", 10]], [["0.38", 4]], 1, now=1.0)
    shape = ob.rest_shape()
    assert shape["yes"] == [[50, 10], [60, 5]]                  # ascending — best bid LAST (REST parity)
    assert shape["no"] == [[38, 4]]


# --- the price cache ----------------------------------------------------------------------------------

def test_livebook_freshness_and_stats():
    import time as _t
    lb = live_feed.LiveBook()
    lb.book("KXT").apply_snapshot([["0.50", 5]], [], 1, now=_t.monotonic())
    d = lb.derived("KXT")
    assert d["fresh"] is True and d["age_s"] is not None
    assert lb.derived("UNKNOWN") is None
    assert lb.stats() == {"books": 1, "synced": 1, "desynced": 0}


# --- message dispatch -----------------------------------------------------------------------------------

def test_dispatch_routes_snapshot_then_delta_by_ticker():
    lf = live_feed.LiveFeed("kid", b"pem", tickers=["KXT"])
    lf._dispatch({"type": "orderbook_snapshot", "seq": 1,
                  "msg": {"market_ticker": "KXT", "yes": [["0.50", 5]], "no": []}})
    lf._dispatch({"type": "orderbook_delta", "seq": 2,
                  "msg": {"market_ticker": "KXT", "side": "yes", "price": "0.55", "delta": 3}})
    assert live_feed.book.derived("KXT")["yes_bid_c"] == 55
    assert live_feed.metrics.snapshot()["live_messages"] == 2


def test_dispatch_seq_gap_counts_and_resyncs(monkeypatch):
    import kalshi_client
    monkeypatch.setattr(kalshi_client, "get_orderbook",
                        lambda tk, depth=10: {"ticker": tk, "yes": [["0.70", 9]], "no": []})
    lf = live_feed.LiveFeed("kid", b"pem", tickers=["KXT"])
    lf._dispatch({"type": "orderbook_snapshot", "seq": 1,
                  "msg": {"market_ticker": "KXT", "yes": [["0.50", 5]], "no": []}})
    lf._dispatch({"type": "orderbook_delta", "seq": 50,        # gap → desync → REST resync
                  "msg": {"market_ticker": "KXT", "side": "yes", "price": "0.55", "delta": 3}})
    assert live_feed.metrics.snapshot()["live_seq_gaps"] == 1
    assert live_feed.book.derived("KXT")["yes_bid_c"] == 70    # reseeded from the REST snapshot


def test_subscribe_cmd_uses_yes_price():
    lf = live_feed.LiveFeed("kid", b"pem", tickers=["A", "B"])
    cmd = lf._subscribe_cmd(["A", "B"])
    assert cmd["cmd"] == "subscribe"
    assert cmd["params"]["use_yes_price"] is True             # required — else NO-side fake crosses
    assert cmd["params"]["market_tickers"] == ["A", "B"]
    assert cmd["params"]["channels"] == ["orderbook_delta"]


# --- safety contracts ---------------------------------------------------------------------------------

def test_default_off():
    assert config.LIVE_FEED_ENABLED is False
    assert live_feed.is_enabled() is False


def test_no_trading_surface():
    """Read-only guarantee: the live module never references an order/portfolio/trading endpoint or verb.
    Scans CODE only (comment lines stripped) so prose in docstrings can't trip it."""
    import pathlib
    lines = pathlib.Path(live_feed.__file__).read_text(encoding="utf-8").splitlines()
    code = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#")).lower()
    for forbidden in ("/orders", "/portfolio", "create_order", "place_order", "cancel_order",
                      "createorder", "amend_order", "self._ws.send(_json.dumps(_order"):
        assert forbidden not in code, f"live_feed.py must not reference {forbidden!r}"


# --- serve.live_feed_safety (fail-hard credential guard) -----------------------------------------------

def test_safety_noop_when_disabled():
    import serve
    assert serve.live_feed_safety(False, key_id=None, key_path=None, key_readable=False,
                                  key_world_readable=False, web_concurrency=8) == []


def test_safety_fatal_on_missing_key_or_unreadable_or_world_readable_or_multiworker():
    import serve
    # missing id + path
    iss = serve.live_feed_safety(True, key_id=None, key_path=None, key_readable=False,
                                 key_world_readable=False)
    assert sum(1 for lvl, _ in iss if lvl == "fatal") >= 2
    # unreadable key
    iss = serve.live_feed_safety(True, key_id="k", key_path="/no/such.pem", key_readable=False,
                                 key_world_readable=False)
    assert any(lvl == "fatal" for lvl, _ in iss)
    # world-readable key
    iss = serve.live_feed_safety(True, key_id="k", key_path="/k.pem", key_readable=True,
                                 key_world_readable=True)
    assert any(lvl == "fatal" and "readable" in msg for lvl, msg in iss)
    # multi-worker
    iss = serve.live_feed_safety(True, key_id="k", key_path="/k.pem", key_readable=True,
                                 key_world_readable=False, web_concurrency=2)
    assert any(lvl == "fatal" and "WEB_CONCURRENCY" in msg for lvl, msg in iss)


def test_safety_clean_when_armed_correctly():
    import serve
    assert serve.live_feed_safety(True, key_id="k", key_path="/k.pem", key_readable=True,
                                  key_world_readable=False, web_concurrency=1) == []
