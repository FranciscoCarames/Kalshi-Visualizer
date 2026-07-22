"""Live Kalshi probe (read-only): discover NUMERIC strike families inside our existing sports.

Goal: find an in-season series whose markets carry machine-readable numeric strikes
(strike_type in {greater,greater_or_equal,less,less_or_equal,between}, floor_strike/cap_strike,
market_type) so S2 can be scoped to ONE proven family. Prints evidence, fetches NOTHING to trade.
"""
from __future__ import annotations

import json
import sys

import requests

import config

BASE = config.BASE_URL
S = requests.Session()
S.headers.update({"Accept": "application/json"})


def get(path, **params):
    r = S.get(f"{BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def list_series():
    """Paginate /series; return list of {ticker,title,category}."""
    out, cursor = [], None
    for _ in range(60):
        j = get("/series", limit=200, **({"cursor": cursor} if cursor else {}))
        out.extend(j.get("series", []))
        cursor = j.get("cursor")
        if not cursor:
            break
    return out


NUM_HINTS = ("TOTAL", "POINTS", "REBOUND", "ASSIST", "SPREAD", "MARGIN", "SCORE",
             "RUNS", "GOALS", "OVER", "UNDER", "PROP", "STRIKEOUT", "THREE")
SPORT_HINTS = ("NBA", "WNBA", "MLB", "NHL", "NFL", "ATP", "WTA", "PGA", "GOLF",
               "WC", "SOCCER", "F1", "NASCAR", "CS2", "LOL", "VAL")


def main():
    try:
        series = list_series()
    except Exception as e:  # noqa: BLE001
        print("SERIES_FETCH_ERROR", repr(e))
        sys.exit(1)
    print(f"total series: {len(series)}")
    cand = []
    for s in series:
        tk = (s.get("ticker") or "").upper()
        ti = (s.get("title") or "")
        if any(h in tk for h in SPORT_HINTS) and any(h in tk or h in ti.upper() for h in NUM_HINTS):
            cand.append((tk, ti, s.get("category")))
    print(f"\ncandidate numeric-in-sport series: {len(cand)}")
    for tk, ti, cat in sorted(cand)[:40]:
        print(f"  {tk:30s} | {cat or '':12s} | {ti}")

    # For up to 6 candidates, fetch open events + a sample market's strike fields.
    print("\n=== market-shape evidence (open events only) ===")
    shown = 0
    for tk, ti, _cat in sorted(cand):
        if shown >= 6:
            break
        try:
            ev = get("/events", series_ticker=tk, status="open", limit=5)
        except Exception as e:  # noqa: BLE001
            print(f"  {tk}: events error {e!r}")
            continue
        events = ev.get("events", [])
        if not events:
            continue
        try:
            mk = get("/markets", series_ticker=tk, status="open", limit=8)
        except Exception as e:  # noqa: BLE001
            print(f"  {tk}: markets error {e!r}")
            continue
        markets = mk.get("markets", [])
        if not markets:
            continue
        shown += 1
        print(f"\n* {tk}  ({len(events)} open events shown, {len(markets)} sample markets)  — {ti}")
        for m in markets[:6]:
            print("   ", json.dumps({
                "ticker": m.get("ticker"),
                "market_type": m.get("market_type"),
                "strike_type": m.get("strike_type"),
                "floor_strike": m.get("floor_strike"),
                "cap_strike": m.get("cap_strike"),
                "yes_sub_title": m.get("yes_sub_title"),
                "status": m.get("status"),
            }))


if __name__ == "__main__":
    main()
