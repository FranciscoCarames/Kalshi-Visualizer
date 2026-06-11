"""Probe + fixture capture for KXWCSTAGEOFELIM ("World Cup Stage of Elimination").

Read-only, keyless, requires live network (run with the Bash sandbox disabled). Captures trimmed,
sanitized event JSON to tests/fixtures/wc_stage_elim/ so the stage-elim detector tests run fully offline,
and prints a per-event shape summary (7 MECE buckets, the constant soccer_team UUID, whole-cent prices).

Usage:
    python scripts/probe_wc_stage_of_elim.py                  # summary only
    python scripts/probe_wc_stage_of_elim.py --save USA UZB    # also capture those teams' fixtures
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SERIES = "KXWCSTAGEOFELIM"
FIX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tests", "fixtures", "wc_stage_elim")
# The market fields the engine (data.build_contracts) + the detector actually read.
_KEEP_M = ("ticker", "yes_sub_title", "status", "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars",
           "no_ask_dollars", "last_price_dollars", "yes_bid_size_fp", "yes_ask_size_fp", "volume_fp",
           "open_interest_fp", "custom_strike", "mutually_exclusive", "title")


def _trim(ev: dict) -> dict:
    return {
        "event_ticker": ev.get("event_ticker"),
        "series_ticker": ev.get("series_ticker"),
        "title": ev.get("title"),
        "mutually_exclusive": ev.get("mutually_exclusive"),
        "product_metadata": ev.get("product_metadata"),
        "markets": [{k: m.get(k) for k in _KEEP_M if k in m} for m in (ev.get("markets") or [])],
    }


def main(save_teams: list[str]) -> None:
    from kalshi_client import get_events

    evs = get_events(SERIES, status="open")
    print(f"{SERIES}: {len(evs)} open events")
    os.makedirs(FIX_DIR, exist_ok=True)
    for ev in evs:
        et = ev.get("event_ticker") or ""
        team_suffix = et.split("-", 1)[1] if "-" in et else et   # e.g. 26USA
        mkts = ev.get("markets") or []
        uuids = {(m.get("custom_strike") or {}).get("soccer_team") for m in mkts}
        suffixes = [str(m.get("ticker") or "").rsplit("-", 1)[-1] for m in mkts]
        if any(t in team_suffix for t in save_teams):
            with open(os.path.join(FIX_DIR, f"{et}.json"), "w", encoding="utf-8") as fh:
                json.dump(_trim(ev), fh, indent=2, ensure_ascii=False)
            print(f"  saved {et}: {len(mkts)} markets, buckets={suffixes}, distinct_uuids={len(uuids)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    save = args[args.index("--save") + 1:] if "--save" in args else []
    main([s.upper() for s in save])
