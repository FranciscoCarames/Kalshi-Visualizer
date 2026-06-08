"""PR3 — the `qualifier_setup` dashboard bucket + opt-in section plumbing (no detectors yet).

Pins the routing surface the PR4/PR5 diagnostics will use: the bucket is registered everywhere, it is
threshold-spared but membership-filtered, and — critically — it is kept OUT of the strict
actionable/review/blocked sections and the durable backlog / recently-actionable paths.
"""

import config
import consistency
import lifecycle
import scanner
import store
from webui import viewmodel


def _qs(oid="qs1", *, sport="soccer", tournament="2026 World Cup", min_size=None, market_status=""):
    """A hand-built unified qualifier_setup diagnostic row (as PR4/PR5 detectors will emit)."""
    return {"opportunity_id": oid, "bucket": "qualifier_setup", "status": "EXACT_ORDER_DIAGNOSTIC",
            "sport": sport, "tournament": tournament, "tradable_now": "Diagnostic only",
            "exec_gap_c": None, "exec_min_size": min_size, "market_status": market_status,
            "setup_family": "wc_qualifier", "setup_type": "exact_order_top2_proxy"}


# --- registration / guards --------------------------------------------------------------------------
def test_bucket_registered_everywhere_and_priority_chain_intact():
    assert "qualifier_setup" in consistency.DASHBOARD_BUCKETS
    assert set(scanner.BUCKET_PRIORITY) == set(consistency.DASHBOARD_BUCKETS)
    bp = scanner.BUCKET_PRIORITY
    # The opt-in diagnostics rank below the strict edges and the bounded-loss watchlists.
    assert bp["blocked"] < bp["risk_budget"] < bp["near_miss"] < bp["qualifier_setup"] < bp["near_edge"]
    assert "qualifier_setup" in viewmodel._BUCKET_LABEL and "qualifier_setup" in viewmodel._BUCKET_ORDER


def test_status_group_and_bucket_of_route_the_diagnostic_statuses():
    for s in ("EXACT_ORDER_DIAGNOSTIC", "GAME_SUPPORT_SIGNAL"):
        assert consistency.STATUS_GROUP[s] == "Qualifier setup"
        assert consistency.bucket_of({"status": s}) == "qualifier_setup"


# --- threshold-spared but membership-filtered -------------------------------------------------------
def test_threshold_spared_by_min_size_and_active_only():
    # A diagnostic row carries no firm size / active status, but must NOT be hidden by the size / active
    # thresholds (it is spared like Actionable). Membership filters still apply (next test).
    rows = [_qs(min_size=None, market_status="")]
    assert viewmodel.filter_opps(rows, min_size=500) == rows
    assert viewmodel.filter_opps(rows, active_only=True) == rows
    assert viewmodel._spared(rows[0]) is True


def test_membership_filters_still_narrow_qualifier_rows():
    rows = [_qs(sport="soccer"), _qs(oid="qs2", sport="nfl")]
    assert {o["opportunity_id"] for o in viewmodel.filter_opps(rows, sports=["soccer"])} == {"qs1"}
    assert viewmodel.filter_opps(rows, tournaments=["nonexistent"]) == []


# --- kept OUT of the strict sections + backlog ------------------------------------------------------
def test_never_routed_into_actionable_review_or_blocked():
    row = _qs()
    for strict in ("actionable", "review_signal", "blocked"):
        assert row["bucket"] != strict


def test_excluded_from_lifecycle_actionable_paths():
    snap_prev = {"opportunities": [{"opportunity_id": "a", "bucket": "actionable", "market_status": "active"}]}
    snap_cur = {"opportunities": [_qs(), {"opportunity_id": "a", "bucket": "actionable", "market_status": "active"}]}
    # A qualifier_setup row is never an "actionable" id, so it cannot appear as new-actionable.
    assert lifecycle._actionable_ids(snap_cur) == {"a"}
    assert all(r.get("opportunity_id") != "qs1" for r in lifecycle.new_actionable(snap_prev, snap_cur))


def test_excluded_from_durable_backlog_category():
    # The bucket→category mapping is intentionally partial; an unmapped bucket → None → not tracked.
    assert "qualifier_setup" not in config.BACKLOG_CATEGORY_BY_BUCKET
    assert store._tracked_category(_qs()) is None


# --- counts line ------------------------------------------------------------------------------------
def test_counts_line_reports_qualifier_setup_section_toggle():
    counts = viewmodel.bucket_counts([_qs(), _qs(oid="qs2")], {})
    on = viewmodel.bucket_counts_line(counts, {"qualifier_setup": True})
    assert "Qualifier setups: 2 shown" in on
    off = viewmodel.bucket_counts_line(counts, {"qualifier_setup": False})
    assert "Qualifier setups: hidden by settings (2 in scope)" in off
