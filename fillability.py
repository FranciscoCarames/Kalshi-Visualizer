"""Visible-depth gross-edge curve for a buy-only opportunity (Feature #1).

A **pure, display-only** layer: given an opportunity's legs and each leg's live order book, walk the
book to show how the gross edge decays as size is added, and the size at which it dies. It is NOT a
pricing engine and changes NOTHING about detection — it never feeds ranking, bucketing, filtering, or
``tradable_now``. Conservative wording throughout: a **visible-depth gross edge estimate**, never
"fillable", "executable", "locked", "riskless", or "arbitrage". Gross and top-of-the-book-walk only —
fees, collateral, position limits, and partial-fill / legging risk are NOT modelled here.

This module has NO network / UI / store / scanner-ranking imports, so it is pure-testable. The API
layer fetches the books (reusing the existing ``/api/terminal/orderbook`` cache + limiter) and passes
them in; the SPA renders the result verbatim.

## Inputs

- ``legs``: ``[{"side": "buy_yes"|"buy_no", "ticker": str, "contract": str}, ...]`` — the uniform leg
  list from ``scanner.legs_of`` (``side`` vocabulary verified against ``dutchbook``/``synthetic_bundle``).
- ``books``: ``{ticker: {"yes": [[price_c, size], ...], "no": [[price_c, size], ...], "ok": bool,
  "fetched_ms": int}}`` — each side is resting **BIDS** in integer cents (as returned by
  ``kalshi_client.get_orderbook``).
- ``payout_floor_c``: the opportunity's **structural** guaranteed payout floor (``scanner.payout_floor_c``)
  — time-invariant, so the live books are scored against it. ``None`` ⇒ no guaranteed floor ⇒ refused.

## Book-side mapping (a taker BUY crosses to the implied ask on the OPPOSITE side)

| leg side  | consume book side | effective ask | size |
|-----------|-------------------|---------------|------|
| ``buy_yes`` | ``no`` (NO bids)  | ``100 − p_no``  | NO bid size  |
| ``buy_no``  | ``yes`` (YES bids)| ``100 − p_yes`` | YES bid size |

(Matches Kalshi's unified book ``no_ask == 1 − yes_bid`` and the dutch-book size rule.) Levels are sorted
**defensively** by best bid first (we never trust returned order); an empty consumed side means the leg
has no visible ask → the whole curve fails closed (we never synthesize a 100¢ ask).

## Water-fill (N-leg)

One bundle unit = **one contract on every leg**. At the current level on each leg the fillable block is
the ``min`` remaining size across legs; we advance by that block, consume it from every leg, recompute,
and repeat until a leg's visible depth is exhausted. ``marginal_edge_c(Q) = payout_floor_c −
Σ_legs(effective ask of that leg's Q-th contract)``; cumulative gross profit sums the marginal edge over
the units filled. A leg that runs out stops the walk — remaining units are NOT shown as usable edge.
"""

from __future__ import annotations

from typing import Any

# Curve points beyond this are not generated (a runaway-depth backstop; real books are far shallower).
_MAX_SEGMENTS = 500


def _num(x: Any) -> Any:
    """None for None or float NaN (a None round-trips to NaN through a DataFrame)."""
    return None if x is None or (isinstance(x, float) and x != x) else x


def _to_int(x: Any) -> int | None:
    v = _num(x)
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def effective_levels(side: str, book: dict[str, Any]) -> list[list[int]]:
    """One leg's taker-buy ladder as ``[[ask_c, size], ...]`` ascending by ask (cheapest/best first).

    ``buy_yes`` consumes the ``no`` bids (ask = ``100 − p_no``); ``buy_no`` consumes the ``yes`` bids
    (ask = ``100 − p_yes``). Defensive: sort the consumed bids by price DESCENDING (best bid first) no
    matter how they arrived, drop malformed / non-positive-size / out-of-range rungs, and clamp asks to
    ``[0, 100]``. An unknown side or empty consumed side yields ``[]`` (caller fails closed)."""
    consumed_key = "no" if side == "buy_yes" else ("yes" if side == "buy_no" else None)
    if consumed_key is None:
        return []
    raw = book.get(consumed_key) or []
    bids: list[tuple[int, int]] = []
    for lvl in raw:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        price_c, size = _to_int(lvl[0]), _to_int(lvl[1])
        if price_c is None or size is None or size <= 0 or not (0 <= price_c <= 100):
            continue
        bids.append((price_c, size))
    bids.sort(key=lambda t: t[0], reverse=True)          # best (highest) bid first → cheapest ask first
    return [[100 - p, s] for p, s in bids]


def _leg_label(leg: dict[str, Any]) -> str:
    return str(leg.get("contract") or leg.get("ticker") or leg.get("side") or "leg")


def fill_curve(legs: list[dict[str, Any]], books: dict[str, Any], payout_floor_c: Any,
               *, depth_limit: int = 100) -> dict[str, Any]:
    """Walk every leg's book in lockstep and return the visible-depth gross-edge curve + summary.

    Returns ``{"ok": bool, "reason": str, "curve": [...], "summary": {...}, "leg_summaries": [...],
    "warnings": [...]}``. ``ok=False`` (with a reason and no curve) when: there is no structural floor
    (``payout_floor_c is None``); fewer than two priceable legs; any leg's consumed book side is empty
    (no visible ask); or a leg book is missing / not ``ok``. All math is exact integer cents."""
    warnings: list[str] = []
    floor = _to_int(payout_floor_c)
    if floor is None:
        return {"ok": False, "reason": "no guaranteed payout floor for this opportunity shape",
                "curve": [], "summary": {}, "leg_summaries": [], "warnings": warnings}
    legs = [lg for lg in (legs or []) if lg.get("side") in ("buy_yes", "buy_no") and lg.get("ticker")]
    if len(legs) < 2:
        return {"ok": False, "reason": "need at least two priceable legs", "curve": [],
                "summary": {}, "leg_summaries": [], "warnings": warnings}

    # Build each leg's ascending taker-buy ladder; fail closed on any missing / empty book.
    ladders: list[list[list[int]]] = []
    leg_summaries: list[dict[str, Any]] = []
    for lg in legs:
        tk = str(lg.get("ticker"))
        book = books.get(tk)
        if not isinstance(book, dict) or book.get("ok") is False:
            return {"ok": False, "reason": f"order book unavailable for {tk}", "curve": [],
                    "summary": {}, "leg_summaries": [], "warnings": warnings, "truncation_reason": "missing_book"}
        levels = effective_levels(str(lg.get("side")), book)
        if not levels:
            return {"ok": False, "reason": f"no visible ask for {_leg_label(lg)} ({tk})", "curve": [],
                    "summary": {}, "leg_summaries": [], "warnings": warnings, "truncation_reason": "no_liquidity"}
        ladders.append(levels)
        visible_units = sum(s for _, s in levels)
        leg_summaries.append({"ticker": tk, "side": lg.get("side"), "contract": _leg_label(lg),
                              "visible_units": visible_units, "first_ask_c": levels[0][0],
                              "worst_ask_c": levels[-1][0]})

    current_top_edge_c = floor - sum(lev[0][0] for lev in ladders)   # marginal edge on the 1st bundle unit
    if any(lev[0][0] <= 0 for lev in ladders):                       # a 0¢/crossed ask is suspicious, not fatal
        warnings.append("a leg shows a 0¢ ask (possibly crossed/stale book) — treat the curve cautiously")

    # Lockstep water-fill. idx/rem track the current level + remaining size on each leg.
    idx = [0] * len(ladders)
    rem = [lev[0][1] for lev in ladders]
    curve: list[dict[str, Any]] = []
    filled = 0
    cumulative_profit_c = 0
    max_cumulative_profit_c = 0
    last_positive_marginal_unit = 0
    positive_visible_units = 0
    break_even_found = False
    truncated = False
    truncation_reason = ""

    for _ in range(_MAX_SEGMENTS):
        if any(rem[i] <= 0 and idx[i] >= len(ladders[i]) for i in range(len(ladders))):
            truncated = True                                          # a leg ran out of visible depth
            truncation_reason = "depth_limit"
            break
        bundle_cost_c = sum(ladders[i][idx[i]][0] for i in range(len(ladders)))
        marginal_edge_c = floor - bundle_cost_c
        block = min(rem)
        if block <= 0:
            break
        seg_profit = marginal_edge_c * block
        cumulative_profit_c += seg_profit
        from_units, filled = filled, filled + block
        avg_edge_c = round(cumulative_profit_c / filled) if filled else 0
        curve.append({"from_units": from_units, "to_units": filled, "bundle_cost_c": bundle_cost_c,
                      "marginal_edge_c": marginal_edge_c, "avg_edge_c": avg_edge_c,
                      "cumulative_profit_c": cumulative_profit_c})
        if marginal_edge_c > 0:
            last_positive_marginal_unit = filled
            positive_visible_units = filled
            max_cumulative_profit_c = max(max_cumulative_profit_c, cumulative_profit_c)
        else:
            break_even_found = True                                   # we saw the edge die within visible depth
        # Consume `block` from every leg; advance any leg whose level is now exhausted.
        for i in range(len(ladders)):
            rem[i] -= block
            if rem[i] <= 0:
                idx[i] += 1
                rem[i] = ladders[i][idx[i]][1] if idx[i] < len(ladders[i]) else 0

    if not break_even_found and curve:                                # edge stayed positive through visible depth
        truncated = True
        if not truncation_reason:
            truncation_reason = "depth_limit"

    # The weakest leg = the shallowest visible depth (first to stop a deeper bundle fill).
    weakest = min(leg_summaries, key=lambda s: s["visible_units"]) if leg_summaries else None
    summary = {
        "payout_floor_c": floor,
        "current_top_edge_c": current_top_edge_c,
        "positive_visible_units": positive_visible_units,
        "last_positive_marginal_unit": last_positive_marginal_unit,
        "max_cumulative_profit_c": max_cumulative_profit_c,
        "break_even_found": break_even_found,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "weakest_leg": (weakest["contract"] if weakest else None),
        "weakest_leg_ticker": (weakest["ticker"] if weakest else None),
        "n_legs": len(legs),
    }
    return {"ok": True, "reason": "", "curve": curve, "summary": summary,
            "leg_summaries": leg_summaries, "warnings": warnings}
