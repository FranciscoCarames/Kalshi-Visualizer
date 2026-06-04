"""Unit tests for webui.diagnostics (PR 25a) — pure observability builders (metrics / failures / category
honesty). No store, no scan_manager, no network — inputs are plain dicts/lists."""
from __future__ import annotations

from webui import diagnostics as dg


def _snapshot(**meta):
    return {"snapshot_id": 7, "fetched_at": 1000,
            "opportunities": [{"bucket": "actionable"}, {"bucket": "blocked"}, {"bucket": "actionable"}],
            "meta": {"scanned": 10, "loaded": 9, "failed": 1, "excluded": 2, "skipped_no_name": 3,
                     "contracts_scanned": 120, "checks_tested": 40, "kalshi_requests": 25,
                     "sport_errors": [{"sport": "nba", "error": "boom"}],
                     "series_errors": [{"sport": "tennis", "series": "KXX", "error": "x"}], **meta}}


# --- build_metrics --------------------------------------------------------------------
def test_build_metrics_shape_and_low_cardinality():
    m = dg.build_metrics(snapshot=_snapshot(), scan_status={"status": "done", "since": 1.0,
                                                            "last_result": {}}, now_age=12.0, stale=False)
    assert m["snapshot_id"] == 7 and m["snapshot_age_seconds"] == 12.0 and m["stale"] is False
    assert m["opportunities"] == 3 and m["actionable"] == 2
    assert m["contracts_scanned"] == 120 and m["checks_tested"] == 40 and m["kalshi_requests"] == 25
    assert m["scanned_series"] == 10 and m["failed_series"] == 1
    assert m["sport_error_count"] == 1                       # COUNT, not the list
    assert m["scan_status"] == "done" and m["last_scan_error"] is None and m["viewer_count"] is None
    # Low-cardinality: no value is an unbounded list (everything is scalar / None).
    assert not any(isinstance(v, (list, dict)) for v in m.values())


def test_build_metrics_honest_when_empty():
    m = dg.build_metrics(snapshot=None, scan_status=None)
    assert m["snapshot_id"] is None and m["opportunities"] == 0 and m["actionable"] == 0
    assert m["scan_status"] == "idle" and m["kalshi_requests"] == 0 and m["sport_error_count"] == 0


def test_build_metrics_in_progress_elapsed_and_last_error():
    running = dg.build_metrics(snapshot=_snapshot(), scan_status={"status": "in_progress", "since": 100.0},
                               now_age=0.0, now=130.0)
    assert running["scan_in_progress_seconds"] == 30.0
    # Not in progress → elapsed is None even if `now` is given.
    idle = dg.build_metrics(snapshot=_snapshot(), scan_status={"status": "done", "since": 100.0}, now=130.0)
    assert idle["scan_in_progress_seconds"] is None
    failed = dg.build_metrics(snapshot=_snapshot(), scan_status={"status": "error",
                                                                 "last_result": {"error": "kaboom"}})
    assert failed["last_scan_error"] == "kaboom"


# --- build_failures -------------------------------------------------------------------
def test_build_failures_surfaces_meta_lists():
    f = dg.build_failures(_snapshot())
    assert f["sport_errors"] == [{"sport": "nba", "error": "boom"}]
    assert f["series_errors"][0]["series"] == "KXX"
    assert f["skipped_no_name"] == 3 and f["excluded"] == 2 and f["failed"] == 1
    empty = dg.build_failures(None)
    assert empty["sport_errors"] == [] and empty["series_errors"] == [] and empty["failed"] == 0


# --- build_category_breakdown (honesty axes never lumped) ------------------------------
def _c(*, eligible, conf="high", series="KXATPADVANCE", family="advance"):
    return {"ladder_eligible": eligible, "mapping_confidence": conf, "series": series, "market_family": family}


def test_category_breakdown_separates_each_axis():
    rows = [
        _c(eligible=True),                                          # laddered, high-conf, supported
        _c(eligible=True, conf="low"),                             # laddered AND low-confidence (both axes)
        _c(eligible=False, family="game"),                         # non-laddered (per-game)
        _c(eligible=False, series="KXZZUNKNOWN", family="props"),  # non-laddered AND unsupported
    ]
    b = dg.build_category_breakdown(rows)
    assert b["total"] == 4
    assert b["laddered"] == 2 and b["non_laddered"] == 2
    assert b["low_confidence"] == 1                 # only the low-conf row
    assert b["unsupported"] == 1                    # the unknown-series row
    assert b["by_family"] == {"advance": 2, "game": 1, "props": 1}
    # A laddered low-confidence row is counted under BOTH laddered and low_confidence (never lumped away).
    assert b["laddered"] + b["non_laddered"] == b["total"]


def test_category_breakdown_empty():
    b = dg.build_category_breakdown(None)
    assert b == {"total": 0, "laddered": 0, "non_laddered": 0, "low_confidence": 0,
                 "unsupported": 0, "by_family": {}}
