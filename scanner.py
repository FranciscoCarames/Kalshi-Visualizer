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
import synthetic_bundle

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
    "action_1_price_c", "action_2_price_c", "cost_c",   # numeric leg prices + combined cost (panel, Stage 5 §0)
    "exec_gap_c", "exec_min_size", "exec_max_profit_dollars",  # gross edge / sizing
    "bucket", "status", "tradable_now", "blocked_reason",      # routing / state (Stage 1)
    "market_status", "rule_flag",              # lifecycle-diff inputs (Stage 3 §9/§10)
    "relationship_type", "opportunity_id",     # identity (Stage 1)
    "ticker_1", "ticker_2", "url", "url_2",    # per-leg tickers + links (panel, Stage 5 §0)
    "legs", "n_legs",                          # N-leg plan (synthetic bundles); None for 2-leg shapes
]


def _cost(a: Any, b: Any) -> Any:
    """Combined cost of the two legs in cents, or None if either price is missing."""
    a, b = _num(a), _num(b)
    return (a + b) if (a is not None and b is not None) else None


def _market_status_consistency(r: dict[str, Any]) -> str:
    """Normalized leg status for a consistency row: 'inactive' if any present leg is non-active,
    else 'active' (a blank/absent leg status — e.g. a single-sided row — does not mark inactive)."""
    for s in (r.get("child_status"), r.get("parent_status")):
        s = str(s or "")
        if s and s != "active":
            return "inactive"
    return "active"


def _num(x: Any) -> Any:
    """None for None or float NaN (a None round-trips to NaN through DataFrame.to_dict)."""
    return None if x is None or (isinstance(x, float) and x != x) else x


def _to_unified_consistency(r: dict[str, Any], cfg) -> dict[str, Any]:
    return {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "containment",
        "name": r.get("player") or "", "detail": r.get("chain") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _cost(r.get("action_1_price_c"), r.get("action_2_price_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": _market_status_consistency(r), "rule_flag": r.get("rule_flag") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        # Leg 1 = broader/parent (Buy YES), leg 2 = deeper/child (Buy NO).
        "ticker_1": r.get("parent_ticker") or "", "ticker_2": r.get("child_ticker") or "",
        "url": r.get("child_url") or r.get("parent_url") or "", "url_2": r.get("parent_url") or "",
        "legs": None, "n_legs": None,  # 2-leg shape — the positional action_1/2 fields carry it
    }


def _to_unified_dutchbook(r: dict[str, Any], cfg) -> dict[str, Any]:
    return {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "dutch_book",
        "name": r.get("match") or "", "detail": r.get("direction") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": r.get("market_status") or "active", "rule_flag": "",  # dutch books carry no rule caveat
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        # Two legs of the same event; one event link (no second link).
        "ticker_1": r.get("ticker_a") or "", "ticker_2": r.get("ticker_b") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": None, "n_legs": None,  # 2-leg shape
    }


def _to_unified_synthetic(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a synthetic-bundle finding (N legs) onto the unified schema. The full plan lives in `legs`;
    `action_1/2_*` are backfilled (by the detector) from the first two legs so 2-leg consumers still work."""
    legs = r.get("legs") or []
    return {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "synthetic_bundle",
        "name": r.get("player") or r.get("match") or "",
        "detail": f"score bundle vs match-winner ({r.get('direction') or ''})".strip(),
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": r.get("market_status") or "active", "rule_flag": r.get("rule_flag") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": (legs[0].get("ticker") if len(legs) > 0 else "") or "",
        "ticker_2": (legs[1].get("ticker") if len(legs) > 1 else "") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": legs, "n_legs": _num(r.get("n_legs")),
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
            records = contracts.to_dict("records")
            checks = consistency.build_checks(contracts)
            books = dutchbook.find_dutch_books(records)
            bundles = synthetic_bundle.find_synthetic_bundles(records)
        except Exception as exc:
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        rows.extend(_to_unified_consistency(r, cfg) for r in checks.to_dict("records"))
        rows.extend(_to_unified_dutchbook(r, cfg) for r in books)
        rows.extend(_to_unified_synthetic(r, cfg) for r in bundles)

    rows.sort(key=_rank_key)
    unified = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)

    if store_writer is not None:
        store_writer(fetched_at, unified)
    return unified, errors


def run_scan(fetch_fn: Callable[[str], tuple], *, fetched_at: Any = None
             ) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch every sport, aggregate coverage, and produce the unified ranked frame — the service entry.

    `fetch_fn(sport_id)` returns the `fetch.fetch_contracts` 7-tuple
    `(df, _fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown)`. Returns
    `(unified_df, coverage)` where `coverage` carries the scan-wide counts + per-series / per-sport
    errors (so `/coverage` is honest). Pure: fetch injected, no store, no network. A per-sport fetch
    failure is recorded and that sport contributes nothing — never blanks the rest.
    """
    dfs: dict[str, Any] = {}
    scanned = loaded = skipped = excluded = 0
    series_errors: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []
    for cfg in sports.all_sports():
        sid = cfg.sport_id
        try:
            df, _fa, errors, n_scanned, n_loaded, skipped_no_name, n_excluded = fetch_fn(sid)
        except Exception as exc:   # a single sport's fetch failure must not blank the scan
            fetch_errors.append({"sport": sid, "error": str(exc)})
            continue
        dfs[sid] = df
        scanned += n_scanned
        loaded += n_loaded
        skipped += skipped_no_name
        excluded += n_excluded
        for s, msg in (errors or []):
            series_errors.append({"sport": sid, "series": s, "error": str(msg)})

    # Reuse the pure aggregator over the already-fetched per-sport frames (it adds its own
    # per-sport PROCESSING errors — build_checks/find_dutch_books failures — to the set).
    unified, processing_errors = unified_opportunities(lambda sid: dfs.get(sid), fetched_at=fetched_at)

    coverage = {
        "fetched_at": fetched_at,
        "scanned": scanned, "loaded": loaded, "failed": len(series_errors), "excluded": excluded,
        "skipped_no_name": skipped,
        "sport_errors": fetch_errors + processing_errors,   # fetch-level + processing-level
        "series_errors": series_errors,
    }
    return unified, coverage
