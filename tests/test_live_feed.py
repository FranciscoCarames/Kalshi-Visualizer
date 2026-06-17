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
    # Under use_yes_price: yes_dollars_fp = YES BID ladder (best = highest = 59), no_dollars_fp = YES ASK
    # ladder (best = LOWEST = 61). NO side is the reciprocal (no_bid=100−yes_ask=39, no_ask=100−yes_bid=41).
    ob.apply_snapshot([["0.55", 10], ["0.59", 5]], [["0.65", 8], ["0.61", 4]], 100, now=1.0)
    d = ob.derived()
    assert (d["yes_bid_c"], d["yes_bid_size"]) == (59, 5)
    assert (d["yes_ask_c"], d["yes_ask_size"]) == (61, 4)     # MIN of the yes-ask ladder, its size
    assert (d["no_bid_c"], d["no_bid_size"]) == (39, 4)       # 100 − yes_ask
    assert (d["no_ask_c"], d["no_ask_size"]) == (41, 5)       # 100 − yes_bid
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


def test_delta_applied_leniently_across_global_seq_jump():
    # Kalshi's seq is connection-wide, so a per-market delta routinely jumps far ahead of this book's last
    # seq. That is NOT a per-book gap — the delta is still applied (a real missed message only makes the book
    # slightly stale, acceptable for display; the connection-level gap METRIC lives on LiveFeed).
    ob = live_feed.OrderBook()
    ob.apply_snapshot([["0.50", 10]], [], 5, now=1.0)
    assert ob.apply_delta("yes", "0.60", 1, 9999, now=1.0) is True  # seq 5→9999 (global) → still applied
    assert ob.synced is True and ob.derived()["yes_bid_c"] == 60
    # an unsnapshotted book still rejects deltas (must seed from a snapshot first)
    fresh = live_feed.OrderBook()
    assert fresh.apply_delta("yes", "0.60", 1, 1, now=1.0) is False


def test_rest_shape_matches_get_orderbook_ascending():
    ob = live_feed.OrderBook()
    # no_dollars_fp holds YES-ASK prices (0.62 = a yes ask at 62¢); rest_shape converts each to its NO-BID
    # price (100−62 = 38) so the depth ladder's `no` side matches REST (resting NO bids), ascending.
    ob.apply_snapshot([["0.60", 5], ["0.50", 10]], [["0.62", 4]], 1, now=1.0)
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
    # Real Kalshi WS field names: yes_dollars_fp/no_dollars_fp (snapshot), price_dollars/delta_fp (delta).
    lf = live_feed.LiveFeed("kid", b"pem", tickers=["KXT"])
    lf._dispatch({"type": "orderbook_snapshot", "seq": 1,
                  "msg": {"market_ticker": "KXT", "yes_dollars_fp": [["0.50", 5]], "no_dollars_fp": []}})
    lf._dispatch({"type": "orderbook_delta", "seq": 2,
                  "msg": {"market_ticker": "KXT", "side": "yes", "price_dollars": "0.55", "delta_fp": 3}})
    assert live_feed.book.derived("KXT")["yes_bid_c"] == 55
    assert live_feed.metrics.snapshot()["live_messages"] == 2


def test_dispatch_counts_connection_gap_but_keeps_book_live():
    # A connection-level seq jump is counted (a message was missed somewhere) but the book is NOT desynced —
    # the delta still applies and the book stays usable. Crucially: NO blocking network on the event loop.
    lf = live_feed.LiveFeed("kid", b"pem", tickers=["KXT"])
    lf._dispatch({"type": "orderbook_snapshot", "seq": 1,
                  "msg": {"market_ticker": "KXT", "yes_dollars_fp": [["0.50", 5]], "no_dollars_fp": []}})
    lf._dispatch({"type": "orderbook_delta", "seq": 50,        # seq 1 → 50 (global) → counted, applied
                  "msg": {"market_ticker": "KXT", "side": "yes", "price_dollars": "0.55", "delta_fp": 3}})
    assert live_feed.metrics.snapshot()["live_seq_gaps"] == 1
    assert live_feed.book.book("KXT").synced is True           # NOT desynced — book stays live
    assert live_feed.book.derived("KXT")["yes_bid_c"] == 55    # the delta was applied


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


# --- serve auto-detect: decide_live_feed (NEVER fatal — bad config just stays REST-only) ---------------

def test_decide_arms_when_valid_key_present():
    import serve
    arm, _ = serve.decide_live_feed(explicit_disabled=False, has_key_config=True, key_loadable=True,
                                    key_world_readable=False, web_concurrency=1)
    assert arm is True


def test_decide_quiet_rest_when_no_key():
    import serve
    arm, msg = serve.decide_live_feed(explicit_disabled=False, has_key_config=False, key_loadable=False,
                                      key_world_readable=False, web_concurrency=1)
    assert arm is False and msg == ""           # common default → silent REST-only


def test_decide_explicit_kill_switch():
    import serve
    arm, msg = serve.decide_live_feed(explicit_disabled=True, has_key_config=True, key_loadable=True,
                                      key_world_readable=False, web_concurrency=1)
    assert arm is False and "OFF" in msg


def test_decide_warns_but_stays_rest_on_bad_or_unsafe_key():
    import serve
    # configured but unloadable → warn, no arm (never crashes)
    arm, msg = serve.decide_live_feed(explicit_disabled=False, has_key_config=True, key_loadable=False,
                                      key_world_readable=False, web_concurrency=1)
    assert arm is False and "REST-only" in msg
    # world-readable key → refuse to arm
    arm, msg = serve.decide_live_feed(explicit_disabled=False, has_key_config=True, key_loadable=True,
                                      key_world_readable=True, web_concurrency=1)
    assert arm is False and "readable" in msg
    # multi-worker → refuse to arm
    arm, msg = serve.decide_live_feed(explicit_disabled=False, has_key_config=True, key_loadable=True,
                                      key_world_readable=False, web_concurrency=2)
    assert arm is False and "WEB_CONCURRENCY" in msg


def test_is_valid_rsa_key_roundtrip():
    import serve
    _key, pem = _gen_key()
    assert serve._is_valid_rsa_key(pem) is True
    assert serve._is_valid_rsa_key(b"-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----") is False
    assert serve._is_valid_rsa_key(b"not a key") is False


# --- serve.parse_dotenv (the .env loader) --------------------------------------------------------------

def test_parse_dotenv():
    import serve
    env = serve.parse_dotenv(
        "# comment\n"
        "KALSHI_API_KEY_ID=abc123\n"
        'KALSHI_PRIVATE_KEY_PATH="C:\\keys\\k.pem"\n'
        "\n"
        "EMPTY=\n"
        "WITH_EQUALS=a=b=c\n"
        "no_equals_line_ignored\n"
        "  SPACED  =  val  \n")
    assert env["KALSHI_API_KEY_ID"] == "abc123"
    assert env["KALSHI_PRIVATE_KEY_PATH"] == "C:\\keys\\k.pem"   # surrounding quotes stripped
    assert env["EMPTY"] == ""
    assert env["WITH_EQUALS"] == "a=b=c"                          # only the FIRST = splits
    assert env["SPACED"] == "val"                                # key + value trimmed
    assert "no_equals_line_ignored" not in env
