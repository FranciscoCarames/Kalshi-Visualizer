"""Manual verification: load a sport's LIVE Kalshi markets through the engine and print a report.

Usage (from the repo root):
    python scripts/verify_sport.py                  # NBA (default), open markets only
    python scripts/verify_sport.py tennis
    python scripts/verify_sport.py nba --status all # include SETTLED markets — needed at end-of-season
                                                    #   (e.g. NBA conferences already decided) to see the
                                                    #   full containment ladder, not just open markets
    python scripts/verify_sport.py nba --all        # scan ALL of the sport's series, not just the core ones

Read-only and keyless — Kalshi market data needs no API key. Requires live network. This is how you
manually validate the multi-sport engine (M1) before the NBA UI exists (M2): it proves the SAME engine
parses, classifies, and ladders any registered sport, and correctly excludes non-laddered markets.
"""
from __future__ import annotations

import os
import sys

# Make the repo root importable when run as `python scripts/verify_sport.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-console safe (labels use →/≤/·)

import pandas as pd  # noqa: E402

import consistency  # noqa: E402
import data  # noqa: E402
import sports  # noqa: E402
from kalshi_client import discover_series_for_sport, get_events_for_series  # noqa: E402


def _load_events(tickers: list[str], status: str):
    """Fetch (ticker, events) pairs. status='all' merges open+settled+closed (deduped by event)."""
    if status != "all":
        return get_events_for_series(tickers, status=status)
    merged: dict[str, dict] = {}
    errs: list = []
    for st in ("open", "settled", "closed"):
        res, e = get_events_for_series(tickers, status=st)
        errs.extend(e)
        for tk, events in res:
            for ev in events:
                merged[ev.get("event_ticker", id(ev))] = {"_t": tk, **ev}
    by_ticker: dict[str, list] = {}
    for ev in merged.values():
        by_ticker.setdefault(ev["_t"], []).append(ev)
    return list(by_ticker.items()), errs


def main(sport_id: str, scan_all: bool, status: str) -> None:
    cfg = sports.get_sport(sport_id)
    if cfg.sport_id == "unknown":
        print(f"Unknown sport '{sport_id}'. Registered: {[c.sport_id for c in sports.all_sports()]}")
        return

    tickers = discover_series_for_sport(cfg) if scan_all else list(cfg.default_series)
    print(f"== {cfg.emoji}  {cfg.label} ({cfg.sport_id}) — {len(tickers)} series, status={status} ==")
    print("series:", ", ".join(tickers[:12]) + (" …" if len(tickers) > 12 else ""))

    results, errors = _load_events(tickers, status)
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(data.build_contracts(ticker, events))
    if errors:
        print(f"\n⚠ {len(errors)} series failed to load:", [e[0] for e in errors][:8])
    df = pd.DataFrame(rows)
    if df.empty:
        print("\nNo contracts found (markets may be between seasons/rounds).")
        return

    print(f"\ncontracts: {len(df)}")
    print("by family:", df["market_family"].value_counts().to_dict())
    print("ladder-eligible:", int(df["ladder_eligible"].sum()),
          "| ineligible/unmapped:", int((~df["ladder_eligible"]).sum()))

    unm = (df[~df["ladder_eligible"]][["series", "market_family", "classification_reason"]]
           .drop_duplicates("series").head(10))
    if not unm.empty:
        print("\nunmapped/ineligible families (correctly excluded from ladder checks):")
        for _, r in unm.iterrows():
            print(f"  {r['series']:16s} {r['market_family']:7s} — {r['classification_reason']}")

    checks = consistency.build_checks(df)
    print(f"\nladder comparisons: {len(checks)}")
    print("by status:", checks["status"].value_counts().to_dict())

    flagged = checks[checks["status"].isin(["EXECUTABLE_VIOLATION", "DISPLAY_VIOLATION"])]
    print(f"\nflagged inconsistencies: {len(flagged)}")
    for _, c in flagged.head(10).iterrows():
        print(f"  {str(c['player'])[:18]:18s} | {c['chain']} | {c['status']} | gap {c.get('exec_gap_c')}")

    print("\nsample ladder rows (first 8, with live display prices):")
    for _, c in checks.head(8).iterrows():
        print(f"  {str(c['player'])[:16]:16s} | {c['chain']:34s} | "
              f"child={c['child_display_pct']} parent={c['parent_display_pct']} | {c['status']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_all = "--all" in args
    status = "open"
    if "--status" in args:
        i = args.index("--status")
        status = args[i + 1] if i + 1 < len(args) else "open"
    positional = [a for a in args if not a.startswith("-") and a != status]
    main(positional[0] if positional else "nba", scan_all, status)
