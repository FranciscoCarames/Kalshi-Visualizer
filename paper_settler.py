"""Background settlement for the forward-test harness: poll the markets behind open paper positions,
cache their settlement outcomes, and re-score. Read-only against Kalshi (``get_market`` only — no orders).

Runs on a LOW cadence with a per-run request cap so it never competes with the scanner for the rate
budget (settlement is a slow, once-per-market event). Default-OFF — armed only when the paper flag is on.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import config
import data
import kalshi_client
import paper_recorder
import paper_store

logger = logging.getLogger(__name__)


def _num(x: Any) -> Any:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _parse_settlement(market: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the harness's settlement fields out of a raw Kalshi market record, or None if it has no ticker.
    ``settlement_value_dollars`` is a per-contract dollar payout → cents via ``data.to_cents`` (binary: 100
    for yes, 0 for no). The engine scores from the binary ``result``; the value is a stored cross-check."""
    ticker = str(market.get("ticker") or "").strip()
    if not ticker:
        return None
    sv = market.get("settlement_value_dollars")
    sv_c = data.to_cents(sv) if sv not in (None, "") else None
    return {
        "ticker": ticker,
        "result": market.get("result") or "",
        "status_raw": str(market.get("status") or "").strip().lower(),
        "settlement_value_c": None if sv_c is None else int(sv_c),
        "settled_ts": _num(market.get("settlement_ts")),
    }


def settle_once(db_path: str | None = None, *,
                max_requests: int | None = None, now_ts: float | None = None) -> dict[str, Any]:
    """One settlement sweep: look up each open ticker (capped at ``max_requests``), cache outcomes, rescore.
    Returns a summary ``{checked, deferred, cached, newly_settled}``. Network errors per ticker are skipped
    (logged), never fatal."""
    cap = config.PAPER_SETTLE_MAX_REQUESTS_PER_RUN if max_requests is None else max_requests
    now_ts = time.time() if now_ts is None else now_ts
    tickers = paper_store.open_tickers(db_path=db_path)
    deferred = max(0, len(tickers) - cap)
    if deferred:
        # No silent truncation: surface that this sweep left some tickers for the next tick.
        logger.info("paper-settler: %d open tickers > cap %d; deferring %d to next sweep",
                    len(tickers), cap, deferred)
    batch = tickers[:cap]
    settlements: list[dict[str, Any]] = []
    for tk in batch:
        try:
            market = kalshi_client.get_market(tk)
        except Exception:  # noqa: BLE001 - one unreachable market must not abort the sweep
            logger.exception("paper-settler: get_market failed for %s", tk)
            continue
        parsed = _parse_settlement(market)
        if parsed is not None:
            settlements.append(parsed)
    cached = paper_store.cache_settlements(settlements, now_ts, db_path=db_path) if settlements else 0
    newly_settled = paper_store.rescore(db_path=db_path) if settlements else 0
    return {"checked": len(batch), "deferred": deferred, "cached": cached, "newly_settled": newly_settled}


class PaperSettler:
    """A low-frequency background thread that runs :func:`settle_once` while the paper flag is enabled.
    Mirrors ``scan_scheduler``: a stop event + an early-wake event, an optional viewer gate."""

    def __init__(self, db_path: str | None = None, interval_s: float | None = None):
        self.db_path = db_path
        self.interval_s = config.PAPER_SETTLE_INTERVAL_SECONDS if interval_s is None else interval_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._gate = None

    def start(self, gate=None) -> None:
        if self._thread is not None:
            return
        self._gate = gate
        self._thread = threading.Thread(target=self._run, name="paper-settler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if paper_recorder.paper_enabled() and (self._gate is None or self._gate()):
                try:
                    settle_once(self.db_path)
                except Exception:  # noqa: BLE001 - a transient error must never kill the loop
                    logger.exception("paper-settler tick failed")
            self._wake.wait(timeout=self.interval_s)
            self._wake.clear()


# Process-wide singleton, started by serve.py when the paper flag is on (mirrors scan_scheduler.scheduler).
settler = PaperSettler()
