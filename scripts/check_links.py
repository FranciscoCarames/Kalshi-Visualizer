"""Check that every contract link works AND points at the correct page.

Two independent checks:
  1. CORRECTNESS (always reliable): each unique URL is printed with the contract identifiers it
     encodes (series / event ticker), so you can confirm it targets the right market. This is also
     unit-tested (see tests/test_data.py::link_audit / kalshi_market_url).
  2. REACHABILITY (best-effort): each URL is fetched with a browser User-Agent and polite backoff.

IMPORTANT: kalshi.com rate-limits automated requests. From a server/CI you will usually get HTTP 429
("throttled — inconclusive"), which is NOT a broken link. Run this from your own machine/browser
network for a trustworthy reachability result. A real problem is a 404 (BROKEN).

Usage (from the repo root):
    python scripts/check_links.py            # core series (fast)
    python scripts/check_links.py --full     # full tennis-series scan
"""
from __future__ import annotations

import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEFAULT_SERIES  # noqa: E402
from data import build_contracts, link_audit  # noqa: E402
from kalshi_client import (  # noqa: E402
    discover_tennis_series,
    get_events_for_series,
    get_series_titles,
)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def collect_rows(full: bool) -> list[dict]:
    tickers = discover_tennis_series() if full else DEFAULT_SERIES
    results, errors = get_events_for_series(tickers)
    if errors:
        print(f"(note: {len(errors)} series failed to load: {[t for t, _ in errors]})")
    titles = get_series_titles([t for t, _ in results])
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events, series_title=titles.get(ticker, "")))
    return rows


def verdict(status_code: int | None) -> str:
    if status_code is None:
        return "NETWORK ERROR"
    if status_code == 200:
        return "OK"
    if status_code == 404:
        return "BROKEN (404)"
    if status_code == 429:
        return "throttled — inconclusive (429)"
    return f"check ({status_code})"


def main() -> None:
    full = "--full" in sys.argv
    rows = collect_rows(full)
    audit = link_audit(rows)
    print(f"\n{len(audit)} unique contract links from {len(rows)} contracts:\n")

    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "text/html"})

    broken = 0
    for entry in audit:
        url = entry["url"]
        code: int | None
        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            code = resp.status_code
        except requests.RequestException:
            code = None
        v = verdict(code)
        if v.startswith("BROKEN"):
            broken += 1
        print(f"  [{v:>28}]  {url}")
        print(f"  {'':>30}   ↳ series={entry['series']} event={entry['event_ticker']} "
              f"contracts={entry['contracts']}")
        time.sleep(1.0)  # be polite; reduce throttling

    print(f"\nDone. {broken} BROKEN (404). 429s are throttling, not broken links — "
          "rerun from your own network if you see many.")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
