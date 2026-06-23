"""Manually run one forward-test settlement sweep + print the paper report.

Read-only against Kalshi (``get_market`` only — no orders). Useful when running without the background
settler (e.g. ad-hoc reconcile). Honors ``SNAPSHOT_DB_PATH`` / ``PAPER_SETTLE_MAX_REQUESTS_PER_RUN``.

    python scripts/settle_paper.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paper_settler  # noqa: E402
import paper_store  # noqa: E402


def main() -> None:
    db_path = os.getenv("SNAPSHOT_DB_PATH")
    summary = paper_settler.settle_once(db_path=db_path)
    print("Settlement sweep:", json.dumps(summary, indent=2))
    print("\nForward-test report:")
    print(json.dumps(paper_store.report(db_path=db_path), indent=2))


if __name__ == "__main__":
    main()
