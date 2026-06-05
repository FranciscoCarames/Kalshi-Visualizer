"""Cross-sport opportunity scanner — Stage 2 engine.

One PURE function, `unified_opportunities`, that aggregates every opportunity across all wired sports
(tennis, NBA, WNBA, golf, soccer, MLB, NHL) into a single best→worst-ranked frame: it runs the containment-ladder checker
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

import config
import consistency
import dutchbook
import sports
import synthetic_bundle

# Section priority for ranking (lower = surfaced first). Mirrors the dashboard's importance order;
# `bucket` is stamped on every row by Stage 1 (consistency.bucket_of / dutchbook). Its key set MUST equal
# consistency.DASHBOARD_BUCKETS (a test guards this). risk_budget / near_miss are "beyond the strict rule"
# (opt-in, past the actionable line), so they rank just below blocked and above the near_edge watchlist.
BUCKET_PRIORITY = {
    "actionable": 0,
    "review_signal": 1,   # settlement-caveated discrepancies (synthetic bundles) — review, just below actionable
    "blocked": 2,
    "risk_budget": 3,     # containment near-miss: bounded loss, convex upside (opt-in)
    "near_miss": 4,       # dutch-book near-miss: flat-payout watchlist (opt-in)
    "near_edge": 5,
    "display_signal": 6,
    "wide_signal": 7,
    "data_quality": 8,
    "clean": 9,
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
    "settlement_caveat",                       # non-blocking per-game settlement caveat (dutch-book PR 6)
    "relationship_type", "opportunity_id",     # identity (Stage 1)
    "ticker_1", "ticker_2", "url", "url_2",    # per-leg tickers + links (panel, Stage 5 §0)
    "legs", "n_legs",                          # N-leg plan (synthetic bundles); synthesized 2-leg otherwise
    "payout_floor_c", "roi_pct",               # guaranteed payout floor + gross ROI on cost (PR 13)
    "snapshot_id",                             # stamped by store.write_snapshot at write time (PR 21a)
    "participant_key",                         # the participant's stable key, for the detail panel (PR 24)
    # "Beyond the strict rule" (PR 29): edge_class tags risk-budget / near-miss rows; worst/best per-unit
    # profit drives the convex risk-budget columns (max loss / max profit / upside:risk). roi_pct (above)
    # doubles as the worst-case ROC for risk-budget rows (worst_case_profit_c == exec_gap_c).
    "edge_class", "worst_case_profit_c", "best_case_profit_c",
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


def gross_roi_pct(gap: Any, cost: Any) -> Any:
    """Gross ROI % on top-of-book cost (gap / cost × 100, 1 dp), or None when cost is missing/non-positive.
    GROSS — before fees / slippage / partial fill (same caveat as exec_max_profit_dollars). Shared by the
    unified mappers and the Streamlit dutch-book / synthetic tables so the number is defined once."""
    gap, cost = _num(gap), _num(cost)
    if gap is None or cost is None or cost <= 0:
        return None
    return round(gap / cost * 100, 1)


def legs_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Every opportunity as a uniform list of leg dicts. Returns the row's own ``legs`` when it is a
    non-empty list (N-leg dutch books / synthetic bundles); otherwise SYNTHESIZES a 2-leg list from the
    positional ``action_1/2_*`` + ``ticker_1/2`` + ``url``/``url_2`` fields. This gives every row — the
    2-leg containment / dutch shapes AND old snapshots written before ``legs`` existed — a single render
    path. A leg with no action text is dropped, so a single-sided row yields a shorter list, not a blank
    leg."""
    legs = row.get("legs")
    if isinstance(legs, list) and legs:
        return legs
    out: list[dict[str, Any]] = []
    for i, (tk, url) in enumerate(((row.get("ticker_1"), row.get("url")),
                                   (row.get("ticker_2"), row.get("url_2"))), start=1):
        text = row.get(f"action_{i}_text")
        if not text:
            continue
        out.append({
            "side": row.get(f"action_{i}_side") or "",
            "contract": row.get(f"action_{i}_contract") or "",
            "price_c": _num(row.get(f"action_{i}_price_c")),
            "size": None,
            "ticker": tk or "",
            "url": url or "",
            "text": text,
        })
    return out


def _finalize_unified(d: dict[str, Any], *, payout_floor_c: Any) -> dict[str, Any]:
    """Stamp the derived schema fields (PR 13) onto a built unified row: the guaranteed payout floor, the
    gross ROI on cost, and a uniform ``legs`` list (synthesized for 2-leg shapes). ``n_legs`` follows the
    leg list. Idempotent over the existing ``legs`` so N-leg findings keep their real list."""
    d["payout_floor_c"] = _num(payout_floor_c)
    d["roi_pct"] = gross_roi_pct(d.get("exec_gap_c"), d.get("cost_c"))
    legs = legs_of(d)
    d["legs"] = legs or None
    d["n_legs"] = _num(d.get("n_legs")) or (len(legs) if legs else None)
    return d


def _to_unified_consistency(r: dict[str, Any], cfg) -> dict[str, Any]:
    d = {
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
        "settlement_caveat": "",  # containment ladders aren't per-game books
        "participant_key": r.get("player_key") or "",   # for the detail panel (PR 24)
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        # Leg 1 = broader/parent (Buy YES), leg 2 = deeper/child (Buy NO). Links must follow the legs:
        # url -> parent (leg 1), url_2 -> child (leg 2). (Was reversed: url pointed at the child.)
        "ticker_1": r.get("parent_ticker") or "", "ticker_2": r.get("child_ticker") or "",
        "url": r.get("parent_url") or r.get("child_url") or "", "url_2": r.get("child_url") or r.get("parent_url") or "",
        "legs": None, "n_legs": None,  # synthesized into a 2-leg list by _finalize_unified (parity)
        # Risk-budget tag + convex payoff (PR 29) — populated only for RISK_BUDGET_CANDIDATE / executable rows.
        "edge_class": r.get("edge_class") or "",
        "worst_case_profit_c": _num(r.get("worst_case_profit_c")),
        "best_case_profit_c": _num(r.get("best_case_profit_c")),
    }
    # broader-YES + deeper-NO guarantees ≥100¢ in every settled state, so the floor is 100 when there's a
    # buy-plan (a firm cost), else None (CLEAN / display-only rows have no executable position).
    return _finalize_unified(d, payout_floor_c=(100 if d["cost_c"] is not None else None))


def _to_unified_dutchbook(r: dict[str, Any], cfg) -> dict[str, Any]:
    d = {
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
        "market_status": r.get("market_status") or "active", "rule_flag": "",  # dutch books carry no rule flag
        "settlement_caveat": r.get("settlement_caveat") or "",  # non-blocking per-game caveat (PR 6)
        # The primary participant (player A); both legs' links stay in the action summary (PR 24).
        "participant_key": r.get("player_key_a") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        # Two legs of the same event; one event link (no second link).
        "ticker_1": r.get("ticker_a") or "", "ticker_2": r.get("ticker_b") or "",
        "url": r.get("url") or "", "url_2": "",
        # 2-leg books carry legs=None (synthesized below); the n-outcome (soccer 3-way) path sets a full
        # `legs` list. _finalize_unified normalizes both into a uniform list + n_legs.
        "legs": r.get("legs"), "n_legs": _num(r.get("n_legs")),
        # Near-miss tag + flat per-unit profit (worst == best == gap_c, negative on a near-miss).
        "edge_class": r.get("edge_class") or "",
        "worst_case_profit_c": _num(r.get("worst_case_profit_c")),
        "best_case_profit_c": _num(r.get("best_case_profit_c")),
    }
    # 2-way floor is 100¢; the n-way path already carries (n−1)·100 (overround) / 100 (underround).
    return _finalize_unified(d, payout_floor_c=(_num(r.get("payout_floor_c")) or 100))


def _to_unified_synthetic(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a synthetic-bundle finding (N legs) onto the unified schema. The full plan lives in `legs`;
    `action_1/2_*` are backfilled (by the detector) from the first two legs so 2-leg consumers still work."""
    legs = r.get("legs") or []
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "synthetic_bundle",
        "name": r.get("player") or r.get("match") or "",
        "detail": (f"score bundle vs "
                   f"{'reach-next-round' if r.get('hedge_kind') == 'advance' else 'match-winner'} "
                   f"({r.get('direction') or ''})").strip(),
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": r.get("market_status") or "active", "rule_flag": r.get("rule_flag") or "",
        "settlement_caveat": "",  # synthetic bundles carry their caveat in blocked_reason (always review-only)
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": (legs[0].get("ticker") if len(legs) > 0 else "") or "",
        "ticker_2": (legs[1].get("ticker") if len(legs) > 1 else "") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": legs, "n_legs": _num(r.get("n_legs")),
        # Synthetic bundles aren't risk-budget/near-miss rows (always review-only) — no edge_class / convex split.
        "edge_class": "", "worst_case_profit_c": None, "best_case_profit_c": None,
    }
    # synthetic forward floor = 100¢, reverse = N×100¢ (carried as payout_floor_c by _build_finding).
    return _finalize_unified(d, payout_floor_c=_num(r.get("payout_floor_c")))


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
    frames_out: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Aggregate opportunities across every registered sport into one ranked frame.

    `fetch_fn(sport_id)` returns that sport's per-player contract DataFrame (injected — the app passes
    its cached `load_contracts`, tests pass a stub). Each sport is processed independently; a fetch or
    processing error for one sport is recorded and skipped (never blanks the others). If `store_writer`
    is given, the scan is persisted once via `store_writer(fetched_at, frame)` (the app wires this to
    `store.write_snapshot`; tests inject a tmp-db writer or omit it).

    When `frames_out` (a list) is given, the per-sport EVIDENCE frames behind the opportunities are
    appended to it as `{sport, frame_type, schema_version, rows}` for `frame_type` ∈
    {contracts, checks, dutchbook} (empties skipped) — the caller persists them via the v3
    `store.write_snapshot(frames=…)` (PR 21a). Out-param (not a return value) so the 2-tuple return and
    every existing caller stay unchanged.

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
            # "Beyond the strict rule" (PR 29): always compute the FULL opt-in bands so every scan persists
            # risk-budget + near-miss candidates; the NiceGUI UI filters them live (no rescan on a control move).
            checks = consistency.build_checks(contracts, risk_budget_max_loss_c=config.RISK_BUDGET_MAX_LOSS_C)
            checks_records = checks.to_dict("records")
            books = dutchbook.find_dutch_books(records, near_miss_max_over_c=config.NEAR_MISS_MAX_OVER_C)
            bundles = synthetic_bundle.find_synthetic_bundles(records)
        except Exception as exc:
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        rows.extend(_to_unified_consistency(r, cfg) for r in checks_records)
        rows.extend(_to_unified_dutchbook(r, cfg) for r in books)
        rows.extend(_to_unified_synthetic(r, cfg) for r in bundles)
        if frames_out is not None:
            for frame_type, frame_rows in (("contracts", records), ("checks", checks_records),
                                           ("dutchbook", books)):
                if frame_rows:
                    frames_out.append({"sport": cfg.sport_id, "frame_type": frame_type,
                                       "schema_version": 1, "rows": frame_rows})

    rows.sort(key=_rank_key)
    unified = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)

    if store_writer is not None:
        store_writer(fetched_at, unified)
    return unified, errors


def run_scan(fetch_fn: Callable[[str], tuple], *, fetched_at: Any = None,
             request_count: Callable[[], int] | None = None
             ) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    """Fetch every sport, aggregate coverage, and produce the unified ranked frame — the service entry.

    `fetch_fn(sport_id)` returns the `fetch.fetch_contracts` 7-tuple
    `(df, _fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown)`. Returns
    `(unified_df, coverage, frames)` where `coverage` carries the scan-wide counts + per-series /
    per-sport errors (so `/coverage` is honest), and `frames` is the per-sport evidence to persist via
    `store.write_snapshot(frames=…)`. `request_count` is an injected no-arg counter (e.g.
    `kalshi_client.request_count`) read before/after so coverage carries the Kalshi `kalshi_requests`
    issued this scan — injected (not imported) so the scanner stays network-free. Pure: fetch injected,
    no store, no network. A per-sport fetch failure is recorded and that sport contributes nothing.
    """
    before = request_count() if request_count else None
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
    frames: list[dict[str, Any]] = []
    unified, processing_errors = unified_opportunities(
        lambda sid: dfs.get(sid), fetched_at=fetched_at, frames_out=frames)

    # Two named volume counters, kept DISTINCT from the opportunity count (§ PR 19/21 meta).
    contracts_scanned = sum(len(f["rows"]) for f in frames if f["frame_type"] == "contracts")
    checks_tested = sum(len(f["rows"]) for f in frames if f["frame_type"] == "checks")
    coverage = {
        "fetched_at": fetched_at,
        "scanned": scanned, "loaded": loaded, "failed": len(series_errors), "excluded": excluded,
        "skipped_no_name": skipped,
        "contracts_scanned": contracts_scanned, "checks_tested": checks_tested,
        "sport_errors": fetch_errors + processing_errors,   # fetch-level + processing-level
        "series_errors": series_errors,
    }
    if before is not None:
        coverage["kalshi_requests"] = request_count() - before
    return unified, coverage, frames
