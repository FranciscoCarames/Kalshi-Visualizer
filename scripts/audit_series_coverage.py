"""Coverage audit: diff Kalshi's LIVE `/series` catalog against what the app actually owns.

Exact-owned sports (golf, soccer/World Cup, esports) miss every NEW series until it is manually added to
their `exact_series` allow-list — a safety choice that avoids false positives but is a *coverage* blind
spot. This script makes the blind spot visible on demand: it lists every live series and buckets it by what
`sports.sport_for_series()` + `cfg.family_of()` would do with it, so a human can spot a current series the
app silently drops.

Usage (from the repo root):
    python scripts/audit_series_coverage.py                     # all live series
    python scripts/audit_series_coverage.py --category Sports    # only the Sports category
    python scripts/audit_series_coverage.py --out audit.txt      # also write the report to a file

Read-only and keyless. Requires live network (run from an unthrottled connection; the Bash sandbox must be
disabled). The bucketing itself (`classify_coverage`) is PURE — no network — so it is unit-tested offline.

Buckets:
  recognized+supported   resolves to a sport AND a non-"other" family (fetched + detector-eligible)
  recognized+other       resolves to a sport but family == "other" (owned, never fetched/detected)
  unknown+sports-cand.    resolves to the UNKNOWN sport but the series' own category looks sports-y
  unknown+out-of-scope   resolves to UNKNOWN and is not sports-y (correctly ignored)
"""
from __future__ import annotations

import os
import sys

# Make the repo root importable when run as `python scripts/audit_series_coverage.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-console safe
except Exception:
    pass

import sports  # noqa: E402

# Bucket constants (stable strings so tests can assert on them).
SUPPORTED = "recognized+supported"
OTHER = "recognized+other"
SPORTS_CANDIDATE = "unknown+sports-candidate"
OUT_OF_SCOPE = "unknown+out-of-scope"

BUCKET_ORDER = (SUPPORTED, OTHER, SPORTS_CANDIDATE, OUT_OF_SCOPE)


def _looks_sporty(category: str, title: str) -> bool:
    """Heuristic for an UNKNOWN-sport series that is probably a sports market worth a closer look."""
    blob = f"{category} {title}".lower()
    return "sport" in blob or any(
        kw in blob for kw in ("soccer", "football", "tennis", "golf", "basketball", "hockey",
                              "baseball", "world cup", "esports", "racing", "nascar", "formula")
    )


def classify_series(ticker: str, *, category: str = "", title: str = "") -> dict[str, str]:
    """Classify ONE series ticker into a coverage bucket. Pure (no network) — testable offline.

    Returns {ticker, sport_id, family, bucket}.
    """
    cfg = sports.sport_for_series(ticker)
    if cfg.sport_id != "unknown":
        family = cfg.family_of(ticker)
        bucket = OTHER if family == "other" else SUPPORTED
        return {"ticker": ticker, "sport_id": cfg.sport_id, "family": family, "bucket": bucket}
    bucket = SPORTS_CANDIDATE if _looks_sporty(category, title) else OUT_OF_SCOPE
    return {"ticker": ticker, "sport_id": "unknown", "family": "other", "bucket": bucket}


def classify_coverage(series_items: list[dict]) -> list[dict[str, str]]:
    """Classify a list of /series items (each a dict with at least a 'ticker'). Pure (no network)."""
    out: list[dict[str, str]] = []
    for s in series_items or []:
        ticker = str(s.get("ticker") or "").strip()
        if not ticker:
            continue
        out.append(classify_series(
            ticker, category=str(s.get("category") or ""), title=str(s.get("title") or "")))
    return out


def _render_report(rows: list[dict[str, str]]) -> str:
    """Human-readable coverage report from classified rows."""
    lines: list[str] = []
    counts = {b: 0 for b in BUCKET_ORDER}
    for r in rows:
        counts[r["bucket"]] = counts.get(r["bucket"], 0) + 1
    lines.append(f"== Series coverage audit — {len(rows)} live series ==")
    for b in BUCKET_ORDER:
        lines.append(f"  {b:26s} {counts.get(b, 0)}")

    # The actionable section: current series the app silently drops.
    candidates = sorted(r["ticker"] for r in rows if r["bucket"] == SPORTS_CANDIDATE)
    if candidates:
        lines.append(f"\n-- {len(candidates)} unknown+sports-candidate (review for ownership) --")
        for t in candidates:
            lines.append(f"  {t}")

    # Per-sport supported/other counts + flag the brittle exact-only sports.
    lines.append("\n-- per-sport recognized counts --")
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        if r["sport_id"] == "unknown":
            continue
        d = per.setdefault(r["sport_id"], {SUPPORTED: 0, OTHER: 0})
        d[r["bucket"]] = d.get(r["bucket"], 0) + 1
    for cfg in sports.all_sports():
        d = per.get(cfg.sport_id, {SUPPORTED: 0, OTHER: 0})
        exact_only = bool(cfg.exact_series) and not cfg.series_prefixes and not cfg.winner_tickers
        flag = "  [EXACT-ONLY → brittle: misses new series until added]" if exact_only else ""
        lines.append(f"  {cfg.sport_id:11s} supported={d.get(SUPPORTED, 0):3d} "
                     f"other={d.get(OTHER, 0):3d}{flag}")
    return "\n".join(lines)


def main(category: str | None, out_path: str | None) -> None:
    from kalshi_client import get_paginated  # local import: only the live path needs the client

    params: dict[str, object] = {"limit": 200}
    if category:
        params["category"] = category
    series = get_paginated("/series", params, list_key="series")
    rows = classify_coverage(series)
    report = _render_report(rows)
    print(report)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"\n(report written to {out_path})")


if __name__ == "__main__":
    args = sys.argv[1:]
    cat = None
    out = None
    if "--category" in args:
        i = args.index("--category")
        cat = args[i + 1] if i + 1 < len(args) else None
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1] if i + 1 < len(args) else "series_coverage_audit.txt"
    main(cat, out)
