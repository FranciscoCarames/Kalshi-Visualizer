"""CLI: analyze the conditional-blend dark-validation CSV against the predeclared go/no-go gate (Phase 0B).

    python scripts/analyze_conditional_blend.py conditional_blend_samples.csv
    python scripts/analyze_conditional_blend.py conditional_blend_samples.csv --json

Reads the append-only sampler output and prints the persistence / half-life / convergence / gate-pass /
blend-vs-complement report. Pure analysis lives in ``conditional_blend_analysis`` (unit-tested); this is a
thin reader so the harness is end-to-end ready the moment a live knockout produces candidates.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import conditional_blend_analysis as cba  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="sampler CSV (conditional_blend_samples.csv)")
    ap.add_argument("--json", action="store_true", help="emit the raw summary+gate as JSON")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"no such file: {args.csv}", file=sys.stderr)
        return 2
    with open(args.csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    result = cba.analyze_samples(rows)
    if args.json:
        print(json.dumps({"summary": result["summary"], "gate":
                          {k: {"pass": ok, "detail": d} for k, (ok, d) in result["gate"].items()}},
                         indent=2, default=str))
    else:
        print(cba.format_report(result))
    return 0 if result["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
