"""Real-time Stage 2: authenticated Kalshi WebSocket live order-book feed (DEFAULT OFF).

This is the ONLY module in the app that holds Kalshi **exchange** credentials (an RSA key). It is OFF
unless `KALSHI_LIVE_ENABLED=1` and a readable key are supplied; `serve.live_feed_safety()` fail-hards
otherwise. It is **read-only by construction** — it never references an order-placement, portfolio, or
trading endpoint (enforced by `tests/test_live_feed.py::test_no_trading_surface`). Single-process only: the
WS connection,
book state, and price cache are process-local like the store/throttle, so `WEB_CONCURRENCY>1` is fatal.

Architecture (each piece is pure + fixture-testable; the live socket is the only impure edge):
- `_sign` — RSA-PSS signature of the handshake (timestamp+GET+path), the same scheme as Kalshi REST auth.
- `OrderBook` — a real book BUILDER. Kalshi sends an `orderbook_snapshot` (full YES/NO bid ladders) then
  incremental single-level `orderbook_delta`s carrying a monotonic `seq`; you cannot track top-of-book
  from deltas alone. On a seq gap the book is marked DESYNCED until a fresh snapshot reseeds it.
- `LiveBook` — the process-local cache `market_ticker -> derived top-of-book` (the same normalized
  `{yes,no:[[price_c,size]]}` shape `kalshi_client.get_orderbook` emits, plus reciprocal ask derivation),
  so `Ladder.tsx` and the overlay reuse one shape. NO fabricated 50% — an empty side is 0.00/1.00.
- `LiveFeed` — the async singleton: connect, subscribe (`use_yes_price: true` — else NO-side levels
  default to no-leg pricing and fake crosses appear), dispatch snapshot/delta, reconnect w/ backoff,
  resync on desync. Shadow mode in 2A: it maintains state + metrics but changes NOTHING the user sees.

NaN-safe, integer-cents only (Decimal at the parse boundary; never `float()` a raw price for logic).
"""
from __future__ import annotations

import base64
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import config

# --- price parsing (exact cents; never float for logic) -----------------------------------------------

def _price_to_cents(value: Any) -> int | None:
    """Kalshi WS price (a fixed-point dollar string like "0.6500", or a number) → exact integer cents.
    Mirrors `data.to_cents` but kept local so this module imports no UI/engine code. None on garbage."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def _to_int_size(value: Any) -> int | None:
    """A fixed-point size → int. None on garbage (so a bad rung is skipped, never crashes the book)."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


# --- RSA-PSS handshake signature ----------------------------------------------------------------------

def _sign(private_key_pem: bytes, timestamp_ms: str, method: str, path: str) -> str:
    """Sign the Kalshi auth string `timestamp + METHOD + PATH` with RSA-PSS (MGF1-SHA256, salt=digest len),
    base64-encoded — the same scheme Kalshi REST uses, required on the WS handshake even for public market
    data. `cryptography` is imported LAZILY so a default-OFF deploy needn't install it."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    message = f"{timestamp_ms}{method}{path}".encode()
    signature = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def auth_headers(key_id: str, private_key_pem: bytes, *, now_ms: int, method: str = "GET",
                 path: str | None = None) -> dict[str, str]:
    """Build the three Kalshi auth headers for the WS handshake. `now_ms` is injected (no `Date.now()` in
    pure code) so the signature is deterministic in tests. The key is never logged."""
    ts = str(int(now_ms))
    sig = _sign(private_key_pem, ts, method, path or config.LIVE_WS_PATH)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


# --- the order-book builder ---------------------------------------------------------------------------

class OrderBook:
    """One market's resting book, built from a snapshot + incremental deltas. Each side maps price_c→size
    (size>0). Tracks `seq` for gap detection; a gap marks the book DESYNCED (its derived top-of-book is
    untrustworthy and its legs are blocked from Actionable in Stage 2D) until a fresh snapshot reseeds it.

    Side semantics match `kalshi_client.get_orderbook`: `yes`/`no` are each that side's resting BIDS in
    that side's own price. Deltas/snapshots are subscribed with `use_yes_price:true` so the NO ladder is
    consistently priced (no fake crosses). Derived asks are reciprocal: `yes_ask = 100 − best_no_bid`."""

    def __init__(self) -> None:
        self.yes: dict[int, int] = {}
        self.no: dict[int, int] = {}
        self.seq: int | None = None
        self.synced: bool = False
        self.last_update_ts: float | None = None      # monotonic; None until first message

    # --- mutation -------------------------------------------------------------------------------------
    @staticmethod
    def _seed_side(levels: Any) -> dict[int, int]:
        out: dict[int, int] = {}
        if not isinstance(levels, list):
            return out
        for lvl in levels:
            if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
                continue
            price_c = _price_to_cents(lvl[0])
            size = _to_int_size(lvl[1])
            # A Kalshi book price is always 1..99¢; reject anything out of range (a malformed/garbage level
            # must never poison best-bid/ask, which are min/max over the price keys).
            if price_c is None or not 0 < price_c < 100 or size is None or size <= 0:
                continue
            out[price_c] = size
        return out

    def apply_snapshot(self, yes_levels: Any, no_levels: Any, seq: int | None, *, now: float) -> None:
        """Seed (or reseed, after a desync) the full book from an `orderbook_snapshot`."""
        self.yes = self._seed_side(yes_levels)
        self.no = self._seed_side(no_levels)
        self.seq = seq
        self.synced = True
        self.last_update_ts = now

    def apply_delta(self, side: str, price: Any, delta: Any, seq: int | None, *, now: float) -> bool:
        """Apply one single-level `orderbook_delta`. Returns True if applied, False if it forced a desync
        (a seq gap — the caller must re-request a snapshot). A delta on an unsynced book is ignored."""
        # Sequence gap → the book is no longer trustworthy. Mark desynced; the caller resyncs via snapshot.
        if seq is not None and self.seq is not None and seq != self.seq + 1:
            self.synced = False
            return False
        if not self.synced:
            return False
        book = self.yes if side == "yes" else self.no if side == "no" else None
        price_c = _price_to_cents(price)
        d = _to_int_size(delta)
        if book is None or price_c is None or not 0 < price_c < 100 or d is None:
            return False
        new_size = book.get(price_c, 0) + d
        if new_size > 0:
            book[price_c] = new_size
        else:
            book.pop(price_c, None)                    # rung emptied → drop it (never a 0-size rung)
        if seq is not None:
            self.seq = seq
        self.last_update_ts = now
        return True

    def mark_desynced(self) -> None:
        self.synced = False

    # --- reads ----------------------------------------------------------------------------------------
    # IMPORTANT (verified live 2026-06-17): with `use_yes_price:true`, BOTH ladders are in YES price.
    # `yes` = the YES-BID ladder (best bid = HIGHEST price). `no` = the YES-ASK ladder (best ask = LOWEST
    # price) — it is NOT a NO-bid ladder, so the reciprocal is `yes_ask = min(no)`, NOT `100 − max(no)`.
    @staticmethod
    def _best_bid(book: dict[int, int]) -> tuple[int | None, int]:
        """(highest price_c, its size) — best bid; (None, 0) for an empty side."""
        if not book:
            return None, 0
        best = max(book)
        return best, book[best]

    @staticmethod
    def _best_ask(book: dict[int, int]) -> tuple[int | None, int]:
        """(lowest price_c, its size) — best ask of the yes-ask ladder; (None, 0) for an empty side."""
        if not book:
            return None, 0
        best = min(book)
        return best, book[best]

    def rest_shape(self) -> dict[str, list[list[int]]]:
        """The `{yes,no:[[price_c,size]]}` ascending (best bid last) shape `get_orderbook` emits, so the depth
        ladder + `/api/terminal/orderbook` reuse one shape. The `no` book holds YES-ASK prices, so convert
        each to its NO-BID price (`100 − p`) to match the REST 'no' side (resting NO bids)."""
        return {
            "yes": [[p, self.yes[p]] for p in sorted(self.yes)],
            "no": [[100 - p, self.no[p]] for p in sorted(self.no, reverse=True)],
        }

    def derived(self) -> dict[str, Any]:
        """Top-of-book (matches `build_contracts`): best YES bid = max(yes); best YES ask = MIN(no) (the no
        book is the yes-ask ladder under use_yes_price); the NO side is the reciprocal (`no_bid = 100 −
        yes_ask`, `no_ask = 100 − yes_bid`). An empty side → 0.00/1.00, never a fabricated 50%."""
        yb, yb_sz = self._best_bid(self.yes)        # best YES bid
        ya, ya_sz = self._best_ask(self.no)         # best YES ask (lowest price in the yes-ask ladder)
        return {
            "yes_bid_c": yb if yb is not None else 0,
            "yes_bid_size": yb_sz,
            "yes_ask_c": ya if ya is not None else 100,
            "yes_ask_size": ya_sz,
            "no_bid_c": (100 - ya) if ya is not None else 0,
            "no_bid_size": ya_sz,
            "no_ask_c": (100 - yb) if yb is not None else 100,
            "no_ask_size": yb_sz,
            "synced": self.synced,
            "seq": self.seq,
        }


# --- the process-local price cache --------------------------------------------------------------------

class LiveBook:
    """Thread-safe `market_ticker -> OrderBook` cache + derived-snapshot reads. The WS task mutates it on
    the event loop; the overlay / `/api/terminal/orderbook` / `/metrics` read it from request/other threads,
    so every access takes the lock and reads are point-in-time copies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._books: dict[str, OrderBook] = {}

    def book(self, ticker: str) -> OrderBook:
        with self._lock:
            ob = self._books.get(ticker)
            if ob is None:
                ob = self._books[ticker] = OrderBook()
            return ob

    def derived(self, ticker: str) -> dict[str, Any] | None:
        """Derived top-of-book for one ticker + freshness, or None if never seen."""
        with self._lock:
            ob = self._books.get(ticker)
            if ob is None:
                return None
            d = ob.derived()
        age = None if ob.last_update_ts is None else (time.monotonic() - ob.last_update_ts)
        d["age_s"] = age
        d["fresh"] = (age is not None and age <= config.LIVE_STALE_AFTER_SECONDS and ob.synced)
        return d

    def rest_shape(self, ticker: str) -> dict[str, list[list[int]]] | None:
        with self._lock:
            ob = self._books.get(ticker)
            return ob.rest_shape() if ob is not None else None

    def tickers(self) -> list[str]:
        with self._lock:
            return list(self._books)

    def stats(self) -> dict[str, int]:
        """Shadow/observability counters over the whole cache."""
        with self._lock:
            books = list(self._books.values())
        return {
            "books": len(books),
            "synced": sum(1 for b in books if b.synced),
            "desynced": sum(1 for b in books if not b.synced),
        }

    def reset(self) -> None:
        with self._lock:
            self._books = {}


# --- live-feed health metrics (shadow mode surfaces these; no UI/ranking effect) ----------------------

class _Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.connected = False
        self.reconnects = 0
        self.seq_gaps = 0
        self.messages = 0
        self.subscriptions = 0
        self.last_msg_ts: float | None = None
        self.last_error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            age = None if self.last_msg_ts is None else round(time.monotonic() - self.last_msg_ts, 2)
            return {
                "live_connected": self.connected,
                "live_reconnects": self.reconnects,
                "live_seq_gaps": self.seq_gaps,
                "live_messages": self.messages,
                "live_subscriptions": self.subscriptions,
                "live_last_msg_age_s": age,
                "live_last_error": self.last_error,
            }

    def reset(self) -> None:
        with self.lock:
            self.connected = False
            self.reconnects = self.seq_gaps = self.messages = self.subscriptions = 0
            self.last_msg_ts = None
            self.last_error = None


metrics = _Metrics()
book = LiveBook()


def is_enabled() -> bool:
    """Master switch (config default OFF; serve.py flips `config.LIVE_FEED_ENABLED` from the env at boot)."""
    return bool(getattr(config, "LIVE_FEED_ENABLED", False))


def live_metrics() -> dict[str, Any]:
    """Combined health + book-coverage counters for `/metrics` (safe to call when OFF → all-zero/false)."""
    out = metrics.snapshot()
    out.update({f"live_{k}": v for k, v in book.stats().items()})
    return out


def plan_subscriptions(db_path: str | None = None, cap: int | None = None) -> list[str]:
    """Which markets to subscribe to from the latest snapshot's contracts frames. v1 = the distinct
    `market_ticker`s in the newest snapshot, capped at `cap` (`LIVE_MAX_SUBSCRIPTIONS`); beyond the cap a
    market stays REST-only and is labeled uncovered. (Tier-1-first prioritization — Actionable/Review legs
    and their MECE peers ahead of the rest — is the Stage 2D refinement; this keeps the universe honest and
    bounded for shadow + display.) Imports store/sports LAZILY so a default-OFF deploy needn't load them."""
    import store
    from sports import all_sports
    cap = cap if cap is not None else config.LIVE_MAX_SUBSCRIPTIONS
    sid = store.latest_snapshot_id(db_path=db_path)
    if sid is None:
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for cfg in all_sports():
        for frame in store.load_frames(sid, sport=cfg.sport_id, frame_type="contracts", db_path=db_path):
            for row in frame.get("rows") or []:
                tk = (row.get("market_ticker") or "").strip()
                if tk and tk not in seen_set:
                    seen_set.add(tk)
                    seen.append(tk)
    return seen[:cap]


def coverage(db_path: str | None = None) -> dict[str, Any]:
    """Honest live coverage: how many of the snapshot's markets have a (fresh, synced) live book vs the
    total universe. Drives the "Live mode covers X/Y markets" label + per-row `live_coverage`."""
    universe = plan_subscriptions(db_path)
    total = len(universe)
    covered = sum(1 for tk in universe if (book.derived(tk) or {}).get("fresh"))
    return {"live_total": total, "live_covered": covered,
            "live_uncovered": max(0, total - covered)}


def reset() -> None:
    """Test hook: clear the shared book cache + metrics between tests."""
    book.reset()
    metrics.reset()


# --- the async WebSocket manager (the only impure edge) -----------------------------------------------

class LiveFeed:
    """Process-local singleton owning the authenticated WS connection + book state. Started from FastAPI
    lifespan when enabled; clean shutdown cancels the task and closes the socket (no dangling tasks in
    tests). The message dispatch (`_dispatch`) is a pure-ish state mutation over the shared `book`/`metrics`
    and is fixture-tested without a real socket; only `_run` (connect/subscribe/reconnect) touches the net.

    `on_book_change` is an optional callback invoked (debounced by the caller) when a delta/snapshot moved
    a tracked book — Stage 2C wires it to the overlay+SSE push. Default None = pure shadow mode (2A)."""

    def __init__(self, key_id: str, private_key_pem: bytes, tickers: list[str] | None = None,
                 *, on_book_change=None) -> None:
        self._key_id = key_id
        self._pem = private_key_pem                    # held in memory only; never logged/echoed
        self._tickers = list(tickers or [])
        self._on_book_change = on_book_change
        self._task = None
        self._ws = None
        self._stop = False
        self._sid_to_ticker: dict[int, str] = {}       # subscription id → market_ticker (for delta routing)
        self._next_id = 1

    # --- message dispatch (pure over shared state; no socket) ------------------------------------------
    def _dispatch(self, msg: dict[str, Any]) -> None:
        """Update book + metrics from one parsed server message. Tolerant of shape drift (a malformed
        message is counted + ignored, never raised — the connection must survive bad input)."""
        now = time.monotonic()
        with metrics.lock:
            metrics.messages += 1
            metrics.last_msg_ts = now
        mtype = msg.get("type")
        body = msg.get("msg") or {}
        if mtype == "subscribed":
            sid = body.get("sid")
            # The subscribe ack may carry the market_ticker; otherwise routing falls back to body fields.
            tk = body.get("market_ticker")
            if isinstance(sid, int) and isinstance(tk, str):
                self._sid_to_ticker[sid] = tk
            with metrics.lock:
                metrics.subscriptions = len(self._sid_to_ticker) or metrics.subscriptions
            return
        if mtype == "orderbook_snapshot":
            tk = body.get("market_ticker") or self._sid_to_ticker.get(msg.get("sid"))
            if not tk:
                return
            # Kalshi WS snapshot carries `yes_dollars_fp`/`no_dollars_fp` — each a [[price$, size], …] bid
            # ladder (verified live 2026-06-17), NOT `yes`/`no`. seq is top-level + per-market.
            self.book.book(tk).apply_snapshot(
                body.get("yes_dollars_fp"), body.get("no_dollars_fp"), msg.get("seq"), now=now)
            self._notify(tk)
            return
        if mtype == "orderbook_delta":
            tk = body.get("market_ticker") or self._sid_to_ticker.get(msg.get("sid"))
            if not tk:
                return
            ob = self.book.book(tk)
            # Delta fields are `price_dollars`/`delta_fp`/`side` (verified live 2026-06-17).
            applied = ob.apply_delta(body.get("side"), body.get("price_dollars"), body.get("delta_fp"),
                                     msg.get("seq"), now=now)
            if not applied and not ob.synced:
                with metrics.lock:
                    metrics.seq_gaps += 1
                self._schedule_resync(tk)
            else:
                self._notify(tk)
            return
        if mtype == "error":
            with metrics.lock:
                metrics.last_error = str(body)[:200]
            return

    @property
    def book(self) -> LiveBook:
        return book                                    # the module singleton (shared with reads/metrics)

    def _notify(self, ticker: str) -> None:
        if self._on_book_change is not None:
            try:
                self._on_book_change(ticker)
            except Exception:                          # noqa: BLE001 — a consumer error must not kill the feed
                pass

    def _schedule_resync(self, ticker: str) -> None:
        """A desynced book is reseeded from a fresh REST snapshot (best-effort; the WS `get_snapshot`
        request is the preferred path when the socket is healthy — see `_request_ws_snapshot`)."""
        try:
            import kalshi_client
            ob_rest = kalshi_client.get_orderbook(ticker)
            self.book.book(ticker).apply_snapshot(
                ob_rest.get("yes"), ob_rest.get("no"), None, now=time.monotonic())
            self._notify(ticker)
        except Exception:                              # noqa: BLE001 — leave it desynced; 2D blocks it
            pass

    # --- subscription command -------------------------------------------------------------------------
    def _subscribe_cmd(self, tickers: list[str]) -> dict[str, Any]:
        """The subscribe command. `use_yes_price:true` is REQUIRED (else NO-side levels default to no-leg
        pricing and produce fake crosses)."""
        cmd_id = self._next_id
        self._next_id += 1
        return {
            "id": cmd_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
                "use_yes_price": True,
            },
        }

    # --- the connect/reconnect loop (impure; needs the key + network) ----------------------------------
    async def _run(self) -> None:
        import json as _json

        from websockets.asyncio.client import connect as ws_connect

        backoff = config.LIVE_RECONNECT_BASE_SECONDS
        attempt = 0
        while not self._stop:
            try:
                import time as _time
                headers = auth_headers(self._key_id, self._pem, now_ms=int(_time.time() * 1000))
                async with ws_connect(config.LIVE_WS_URL, additional_headers=headers,
                                      open_timeout=config.LIVE_WS_OPEN_TIMEOUT_SECONDS) as ws:
                    self._ws = ws
                    with metrics.lock:
                        metrics.connected = True
                        metrics.last_error = None
                    backoff = config.LIVE_RECONNECT_BASE_SECONDS         # reset on a clean connect
                    attempt = 0
                    if self._tickers:
                        await ws.send(_json.dumps(self._subscribe_cmd(self._tickers)))
                    async for raw in ws:
                        if self._stop:
                            break
                        try:
                            self._dispatch(_json.loads(raw))
                        except Exception:                                # noqa: BLE001 — bad frame, keep going
                            continue
            except Exception as exc:                                     # noqa: BLE001 — any drop → reconnect
                with metrics.lock:
                    metrics.last_error = f"{type(exc).__name__}: {exc}"[:200]
            finally:
                self._ws = None
                with metrics.lock:
                    metrics.connected = False
            if self._stop:
                break
            with metrics.lock:
                metrics.reconnects += 1
            # Exponential backoff with deterministic jitter (no Math.random in resumable code): vary by attempt.
            attempt += 1
            jitter = (attempt % 5) * 0.1
            await _async_sleep(min(backoff + jitter, config.LIVE_RECONNECT_MAX_SECONDS))
            backoff = min(backoff * 2, config.LIVE_RECONNECT_MAX_SECONDS)

    def start(self, loop) -> None:
        """Schedule the WS task on the captured event loop (idempotent)."""
        if self._task is not None:
            return
        self._stop = False
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the task + close the socket cleanly (no dangling tasks)."""
        self._stop = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:                          # noqa: BLE001
                pass
        if self._task is not None:
            import asyncio
            self._task.cancel()
            try:
                await self._task
            # CancelledError is a BaseException (NOT Exception) in 3.8+, so it MUST be caught explicitly —
            # otherwise it propagates out of the lifespan shutdown ("Application shutdown failed").
            except (asyncio.CancelledError, Exception):   # noqa: BLE001 — teardown is best-effort
                pass
            self._task = None


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


# The process-wide singleton (created by serve.py at boot when enabled; None when OFF).
feed_singleton: LiveFeed | None = None
