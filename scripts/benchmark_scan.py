"""Forced scan-all benchmark (PR 21b) — MANUAL, sandbox-disabled (it hits live Kalshi).

Measures a full scan's duration / Kalshi requests / failure rate / row counts WITHOUT changing the
production default scan scope. Use it to sanity-check the scan-budget caps (config.SCAN_BUDGET_*) and to
pick a scheduled-scan interval that's comfortably longer than a real scan (UNIFIED-PLAN §7 Q6). Scope is
injectable; nothing here alters what `POST /scan` fetches by default.

Run from the repo root:
    python scripts/benchmark_scan.py            # scan-all (every discovered series), all sports
    python scripts/benchmark_scan.py --core     # core series only (the production default) for comparison
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch  # noqa: E402
import kalshi_client  # noqa: E402
import scanner  # noqa: E402
import sports  # noqa: E402


def main() -> None:
    scan_all = "--core" not in sys.argv
    scope = "scan-all" if scan_all else "core"

    def fetch_fn(sport_id: str):
        cfg = sports.get_sport(sport_id)
        families = tuple(sorted(set(cfg.category_labels.values())))
        return fetch.fetch_contracts(families, scan_all, sport_id)

    kalshi_client.reset_request_count()
    t0 = time.time()
    unified, cov, frames = scanner.run_scan(
        fetch_fn, fetched_at="benchmark", request_count=kalshi_client.request_count)
    duration = time.time() - t0
    fail_rate = cov["failed"] / max(cov["scanned"], 1)

    print(f"scope            : {scope}")
    print(f"duration         : {duration:.1f}s")
    print(f"kalshi_requests  : {cov.get('kalshi_requests')}")
    print(f"scanned/loaded   : {cov['scanned']} / {cov['loaded']}")
    print(f"failed/excluded  : {cov['failed']} / {cov['excluded']}  (failure_rate {fail_rate:.1%})")
    print(f"opportunities    : {len(unified)}")
    print(f"contracts_scanned: {cov['contracts_scanned']}")
    print(f"checks_tested    : {cov['checks_tested']}")
    print(f"frames           : {len(frames)} {sorted({f['frame_type'] for f in frames})}")
    print(f"budget verdict   : over-budget={scan_manager_over_budget(cov, duration)}")


def scan_manager_over_budget(cov: dict, duration: float) -> bool:
    import scan_manager  # local import: this is a measurement helper, not part of the scan path
    return scan_manager._over_budget(cov, duration)


if __name__ == "__main__":
    main()
