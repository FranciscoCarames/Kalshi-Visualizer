"""Cross-sport opportunity scanner — Stage 2 engine.

One PURE function, `unified_opportunities`, that aggregates every opportunity across all wired sports
(tennis + NBA + WNBA) into a single best→worst-ranked frame: it runs the containment-ladder checker
(`consistency.build_checks`) and the dutch-book detector (`dutchbook.find_dutch_books`) per sport,
stamps each row with its `sport`, normalizes the two row shapes onto one schema, ranks them, and
optionally persists the scan to the Stage-1 snapshot store.

Kept Streamlit-free AND network-free: the per-sport contract fetch is dependency-INJECTED
(`fetch_fn(sport_id) -> contracts DataFrame`), so the app passes its cached `load_contracts` while unit
tests pass a stub — the scanner itself never imports `app`, `streamlit`, or `kalshi_client`. A single
sport's fetch/processing failure is recorded and skipped, never allowed to blank the whole frame.

`opportunity_id` / `relationship_type` / `bucket` / `blocked_reason` already live on every row (Stage 1);
this module only adds `sport` and the unified projection, then ranks.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

import consistency
import dutchbook
import sports

# Section priority for ranking (lower = surfaced first). Mirrors the dashboard's importance order;
# `bucket` is stamped on every row by Stage 1 (consistency.bucket_of / dutchbook).
BUCKET_PRIORITY = {
    "actionable": 0,
    "blocked": 1,
    "near_edge": 2,
    "display_signal": 3,
    "wide_signal": 4,
    "data_quality": 5,
    "clean": 6,
}

# The shared minimal schema both row shapes (containment checks + dutch-book findings) map onto. Stable
# column order so the interim table / CSV are coherent and the empty frame keeps its columns.
UNIFIED_COLUMNS = [
    "sport", "sport_label", "source",          # provenance
    "name", "detail", "tournament", "tour",    # what it is
    "action_1_text", "action_2_text",          # the two buys (same vocabulary across both shapes)
    "exec_gap_c", "exec_min_size", "exec_max_profit_dollars",  # gross edge / sizing
    "bucket", "status", "tradable_now", "blocked_reason",      # routing / state (Stage 1)
    "relationship_type", "opportunity_id",     # identity (Stage 1)
    "url",                                      # link
]


def _num(x: Any) -> Any:
    """None for None or float NaN (a None round-trips to NaN through DataFrame.to_dict)."""
    return None if x is None or (isinstance(x, float) and x != x) else x


def _to_unified_consistency(r: dict[str, Any], cfg) -> dict[str, Any]:
    return {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "containment",
        "name": r.get("player") or "", "detail": r.get("chain") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        "url": r.get("child_url") or r.get("parent_url") or "",
    }


def _to_unified_dutchbook(r: dict[str, Any], cfg) -> dict[str, Any]:
    return {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "dutch_book",
        "name": r.get("match") or "", "detail": r.get("direction") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        "url": r.get("url") or "",
    }


def _rank_key(row: dict[str, Any]) -> tuple:
    """Actionable first, then largest gross edge (¢), then a stable id tiebreak."""
    bp = BUCKET_PRIORITY.get(row.get("bucket"), 99)
    gap = row.get("exec_gap_c")
    gap = gap if isinstance(gap, (int, float)) and gap == gap else float("-inf")
    return (bp, -gap, row.get("opportunity_id") or "")


def unified_opportunities(
    fetch_fn: Callable[[str], "pd.DataFrame | None"],
    *,
    store_writer: Callable[[Any, "pd.DataFrame"], Any] | None = None,
    fetched_at: Any = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Aggregate opportunities across every registered sport into one ranked frame.

    `fetch_fn(sport_id)` returns that sport's per-player contract DataFrame (injected — the app passes
    its cached `load_contracts`, tests pass a stub). Each sport is processed independently; a fetch or
    processing error for one sport is recorded and skipped (never blanks the others). If `store_writer`
    is given, the scan is persisted once via `store_writer(fetched_at, frame)` (the app wires this to
    `store.write_snapshot`; tests inject a tmp-db writer or omit it).

    Returns `(unified_df, per_sport_errors)` where each error is `{"sport": id, "error": msg}`.
    """
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for cfg in sports.all_sports():
        try:
            contracts = fetch_fn(cfg.sport_id)
        except Exception as exc:  # a single sport's fetch must never blank the whole scan
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        if contracts is None or getattr(contracts, "empty", False):
            continue
        try:
            checks = consistency.build_checks(contracts)
            books = dutchbook.find_dutch_books(contracts.to_dict("records"))
        except Exception as exc:
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        rows.extend(_to_unified_consistency(r, cfg) for r in checks.to_dict("records"))
        rows.extend(_to_unified_dutchbook(r, cfg) for r in books)

    rows.sort(key=_rank_key)
    unified = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)

    if store_writer is not None:
        store_writer(fetched_at, unified)
    return unified, errors
