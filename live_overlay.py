"""Real-time Stage 2C/2D: live-price overlay → re-run the engine → push a fresh feed over SSE.

The seam (`data.build_contracts` aside) is that everything the engine produces downstream of a contract row
is PRICE-dependent only through that row's price fields. So the live path is: take the latest REST scan's
per-sport **contracts frames** (already `build_contracts` output, keyed by `market_ticker`), patch each
row's price fields from the live book where a fresh book exists, re-run the UNCHANGED
`scanner.unified_opportunities` on the patched frames, and build a feed via
`webui.feed.build_feed_from_unified` — pushed **from memory**, never via the store.

Two safety layers keep this honest (the audit's load-bearing points):
- **Per-leg coverage gate.** Each opportunity's legs (`scanner.legs_of`) are checked against the live book;
  a row with a stale / desynced / uncovered leg can NOT be Actionable — it degrades to a labeled live
  review row, never silently.
- **2C vs 2D.** With `LIVE_ACTIONABILITY_ENABLED` False (default, Stage 2C) live prices are DISPLAYED but
  a NEW live-only edge (not Actionable on the last REST scan) is demoted — the Actionable set stays
  REST-confirmed. True (Stage 2D) lets a fully-live, fully-covered row rank Actionable.

Pure cores (`overlay_row_prices`, `leg_coverage`, `gate_record`, `parity_compare`) are unit-tested; the
orchestration (`build_live_feed`) is integration-tested against a seeded store + a stubbed live book.
"""
from __future__ import annotations

from typing import Any

import config
import live_feed

# --- pure: recompute a contract row's price fields from a live top-of-book -----------------------------

def overlay_row_prices(row: dict[str, Any], derived: dict[str, Any]) -> dict[str, Any]:
    """Return a COPY of a contracts-frame row with every price-derived field recomputed from the live
    `derived` top-of-book (the same dict `LiveBook.derived` returns). Reuses `data.py`'s pure pricing
    helpers verbatim, so display + executable fields stay mutually consistent (an empty side → 0.00/1.00,
    never a fabricated 50%). `last_c` (last trade) is kept from REST — the live book carries no last."""
    import data
    out = dict(row)
    yb_c = derived.get("yes_bid_c")
    ya_c = derived.get("yes_ask_c")
    nb_c = derived.get("no_bid_c")
    na_c = derived.get("no_ask_c")
    bid = (yb_c / 100.0) if yb_c is not None else None
    ask = (ya_c / 100.0) if ya_c is not None else None
    no_bid = (nb_c / 100.0) if nb_c is not None else None
    no_ask = (na_c / 100.0) if na_c is not None else None
    last_c = row.get("last_c")
    last = (last_c / 100.0) if last_c is not None else None
    out["yes_bid_c"], out["yes_ask_c"] = yb_c, ya_c
    out["no_bid_c"], out["no_ask_c"] = nb_c, na_c
    out["yes_bid_size"] = derived.get("yes_bid_size")
    out["yes_ask_size"] = derived.get("yes_ask_size")
    out["no_bid_size"] = derived.get("no_bid_size")
    out["no_ask_size"] = derived.get("no_ask_size")
    out["yes_bid_pct"] = data._pct(bid)
    out["yes_ask_pct"] = data._pct(ask)
    out["no_bid_pct"] = data._pct(no_bid)
    out["no_ask_pct"] = data._pct(no_ask)
    out["yes_mid_pct"] = data._pct(data.yes_mid(bid, ask))
    out["display_pct"] = data._pct(data.display_prob(bid, ask, last))
    out["display_c"] = data.display_cents(yb_c, ya_c, last_c)
    sp = data.spread(bid, ask)
    out["spread_cents"] = round(sp * 100, 1) if sp is not None else None
    out["quote_quality"] = data.quote_quality(bid, ask)
    out["price_source"] = "live"
    return out


# --- pure-ish: per-opportunity live coverage from its legs ---------------------------------------------

def leg_coverage(record: dict[str, Any], book: "live_feed.LiveBook") -> dict[str, Any]:
    """Live coverage for one opportunity, derived from its legs (`scanner.legs_of`). A leg is 'live' only if
    its book is fresh AND synced. Returns the per-row freshness/coverage metadata + the safety verdict."""
    import scanner
    tickers = [(leg.get("ticker") or "").strip() for leg in scanner.legs_of(record)]
    tickers = [t for t in tickers if t]
    n_total = len(tickers)
    n_live = 0
    ages: list[float] = []
    any_uncovered = any_desynced = any_stale = False
    for t in tickers:
        d = book.derived(t)
        if d is None:
            any_uncovered = True
            continue
        if not d.get("synced"):
            any_desynced = True
        if d.get("fresh"):
            n_live += 1
            if d.get("age_s") is not None:
                ages.append(d["age_s"])
        else:
            any_stale = True
    all_legs_live = n_total > 0 and n_live == n_total and not any_uncovered
    return {
        "live_legs": n_live, "legs_total": n_total, "all_legs_live": all_legs_live,
        "any_uncovered": any_uncovered, "any_desynced": any_desynced, "any_stale": any_stale,
        "price_age_s": (round(max(ages), 2) if ages else None),
        "live_coverage": all_legs_live,
        "price_source": "live" if all_legs_live else ("mixed" if n_live > 0 else "rest"),
    }


# --- pure: the Actionable gate ------------------------------------------------------------------------

def gate_record(record: dict[str, Any], cov: dict[str, Any], *, rest_bucket: str | None,
                allow_actionability: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decide whether a LIVE-derived row may stay Actionable, and stamp display-only live fields.

    Returns `(maybe_demoted_record, row_extra)`. A row is demoted out of Actionable (to `review_signal`,
    labeled) when a leg is stale/desynced/uncovered, OR — in Stage 2C (`allow_actionability` False) — when
    it's a NEW live-only edge that wasn't Actionable on the last REST scan (so a transient quote can't
    manufacture a false Actionable). `row_extra` carries the freshness/coverage badges for the feed row."""
    out = dict(record)
    row_extra = {
        "price_source": cov["price_source"], "live_coverage": cov["live_coverage"],
        "all_legs_live": cov["all_legs_live"], "live_legs": cov["live_legs"],
        "legs_total": cov["legs_total"], "price_age_s": cov["price_age_s"],
    }
    if out.get("bucket") == "actionable":
        reason = None
        if not cov["all_legs_live"]:
            reason = ("a leg is not covered by the live feed" if cov["any_uncovered"]
                      else "a leg's live book is desynced" if cov["any_desynced"]
                      else "a leg's live price is stale")
        elif not allow_actionability and rest_bucket != "actionable":
            reason = "new live-only edge — confirm on a REST scan (Stage 2C)"
        if reason:
            out["bucket"] = "review_signal"
            out["tradable_now"] = "Live — review"
            row_extra["live_demoted"] = True
            row_extra["live_block_reason"] = reason
    return out, row_extra


# --- orchestration: build the live feed (re-run the engine on patched prices) -------------------------

def _patched_frames(snap: dict[str, Any], book: "live_feed.LiveBook", db_path: str | None
                    ) -> tuple[dict[str, "Any"], int]:
    """Build per-sport patched contract DataFrames from the latest snapshot's contracts frames, overlaying
    live prices where a fresh book exists. Returns (sport_id -> DataFrame, n_rows_patched)."""
    import pandas as pd

    import store
    from sports import all_sports
    sid = snap.get("snapshot_id")
    out: dict[str, Any] = {}
    patched = 0
    for cfg in all_sports():
        rows: list[dict[str, Any]] = []
        for frame in store.load_frames(sid, sport=cfg.sport_id, frame_type="contracts", db_path=db_path):
            for row in frame.get("rows") or []:
                tk = (row.get("market_ticker") or "").strip()
                d = book.derived(tk) if tk else None
                if d is not None and d.get("fresh"):
                    rows.append(overlay_row_prices(row, d))
                    patched += 1
                else:
                    rows.append(row)
        if rows:
            out[cfg.sport_id] = pd.DataFrame(rows)
    return out, patched


def build_live_feed(db_path: str | None = None, *, live_seq: int = 0,
                    allow_actionability: bool | None = None,
                    book: "live_feed.LiveBook | None" = None) -> dict[str, Any] | None:
    """Re-run the UNCHANGED engine on live-patched contract prices and return a feed dict (or None when
    there's no snapshot to overlay). Pushed from memory by `LivePusher`; never writes the store."""
    import scanner
    import store
    from webui import feed as feedmod
    book = book if book is not None else live_feed.book
    allow = (config.LIVE_ACTIONABILITY_ENABLED if allow_actionability is None else allow_actionability)
    snap = store.latest(db_path=db_path)
    if not snap:
        return None
    frames_by_sport, _patched = _patched_frames(snap, book, db_path)
    if not frames_by_sport:
        return None
    unified, _errors = scanner.unified_opportunities(
        lambda sid: frames_by_sport.get(sid), fetched_at=snap.get("fetched_at"))
    records = unified.to_dict("records")
    rest_bucket_by_id = {o.get("opportunity_id"): o.get("bucket")
                         for o in (snap.get("opportunities") or [])}
    gated: list[dict[str, Any]] = []
    row_extra: dict[str, dict[str, Any]] = {}
    for rec in records:
        cov = leg_coverage(rec, book)
        rid = rec.get("opportunity_id")
        rec2, extra = gate_record(rec, cov, rest_bucket=rest_bucket_by_id.get(rid),
                                  allow_actionability=allow)
        gated.append(rec2)
        if rid is not None:
            row_extra[rid] = extra
    meta = dict(snap.get("meta") or {})
    cov_summary = live_feed.coverage(db_path=db_path)
    meta_extra = {
        "live_seq": live_seq, "price_source": "live", "live_actionability": bool(allow),
        "live_covered": cov_summary.get("live_covered"), "live_total": cov_summary.get("live_total"),
    }
    return feedmod.build_feed_from_unified(
        gated, meta, snapshot_id=snap.get("snapshot_id"), fetched_at=snap.get("fetched_at"),
        row_extra=row_extra, meta_extra=meta_extra)


# --- Stage 2B: REST/WS parity validation --------------------------------------------------------------

_PARITY_FIELDS = ("yes_bid_c", "yes_ask_c", "no_bid_c", "no_ask_c")


def parity_compare(live_by_ticker: dict[str, dict[str, Any]],
                   rest_by_ticker: dict[str, dict[str, Any]], *, tol_c: int = 0) -> dict[str, Any]:
    """Pure: compare live vs REST top-of-book over the shared tickers. A mismatch is any of the four
    executable cents fields differing by more than `tol_c`. Returns counts + a few samples — the evidence
    gate the owner reviews before trusting Stage 2C/2D (the audit's promotion gate)."""
    shared = sorted(set(live_by_ticker) & set(rest_by_ticker))
    mismatches: list[dict[str, Any]] = []
    for tk in shared:
        lv, rs = live_by_ticker[tk], rest_by_ticker[tk]
        diffs = {f: [lv.get(f), rs.get(f)] for f in _PARITY_FIELDS
                 if (lv.get(f) is not None and rs.get(f) is not None
                     and abs(int(lv[f]) - int(rs[f])) > tol_c)}
        if diffs:
            mismatches.append({"ticker": tk, "diffs": diffs})
    compared = len(shared)
    return {
        "compared": compared, "mismatched": len(mismatches),
        "mismatch_rate": (round(len(mismatches) / compared, 4) if compared else None),
        "samples": mismatches[:20],
    }


def parity_report(db_path: str | None = None, book: "live_feed.LiveBook | None" = None) -> dict[str, Any]:
    """Live-vs-REST parity over the latest snapshot's contracts (the REST side) and the live book cache."""
    import store
    from sports import all_sports
    book = book if book is not None else live_feed.book
    sid = store.latest_snapshot_id(db_path=db_path)
    if sid is None:
        return {"compared": 0, "mismatched": 0, "mismatch_rate": None, "samples": []}
    rest_by_ticker: dict[str, dict[str, Any]] = {}
    for cfg in all_sports():
        for frame in store.load_frames(sid, sport=cfg.sport_id, frame_type="contracts", db_path=db_path):
            for row in frame.get("rows") or []:
                tk = (row.get("market_ticker") or "").strip()
                if tk:
                    rest_by_ticker[tk] = {f: row.get(f) for f in _PARITY_FIELDS}
    live_by_ticker = {tk: book.derived(tk) for tk in book.tickers() if book.derived(tk)}
    return parity_compare(live_by_ticker, rest_by_ticker)


# --- debounced push: live book changed → rebuild the feed → SSE -----------------------------------------

class LivePusher:
    """Wired to `LiveFeed.on_book_change` (called on the event loop when a delta/snapshot moves a tracked
    book). Coalesces a burst of deltas with a single debounce timer, then rebuilds the live feed OFF the
    event loop (the engine pass is CPU work — never block the loop) and pushes it over Stage 1's SSE. A min
    interval floors recompute frequency under a fast market. From memory only; never writes the store."""

    def __init__(self, loop, db_path: str | None = None) -> None:
        self._loop = loop
        self._db_path = db_path
        self._timer = None
        self._seq = 0
        self._last_build = 0.0
        self._building = False

    def on_book_change(self, _ticker: str) -> None:
        # Runs on the loop thread (from the WS dispatch). Debounce: reset the single pending timer.
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._loop.call_later(config.LIVE_DEBOUNCE_SECONDS, self._fire)

    def _fire(self) -> None:
        self._timer = None
        import time as _t
        # Min-recompute floor: if we rebuilt very recently, defer one more debounce window instead of
        # hammering the engine under a fast market.
        if self._building or (_t.monotonic() - self._last_build) < config.LIVE_MIN_RECOMPUTE_SECONDS:
            self._timer = self._loop.call_later(config.LIVE_DEBOUNCE_SECONDS, self._fire)
            return
        self._building = True
        self._loop.run_in_executor(None, self._build_and_publish)

    def _build_and_publish(self) -> None:
        import json
        import time as _t

        import events
        try:
            self._seq += 1
            feed = build_live_feed(self._db_path, live_seq=self._seq)
            if feed is not None:
                events.publish(json.dumps(feed))
        except Exception:                              # noqa: BLE001 — a build/publish failure must not kill the feed
            pass
        finally:
            self._last_build = _t.monotonic()
            self._building = False
