"""Unit tests for the lifecycle snapshot-diff engine (Stage 3). Pure — crafted snapshot dicts, no
network/store. Covers new-actionable (§8) + banner persistence, blocked-change (§9), recently-actionable
(§10), and first_seen."""
from __future__ import annotations

import lifecycle


def op(oid, bucket="actionable", **kw):
    """A minimal persisted unified opportunity row."""
    return {
        "opportunity_id": oid, "bucket": bucket,
        "status": kw.get("status", ""), "blocked_reason": kw.get("blocked_reason", ""),
        "exec_gap_c": kw.get("exec_gap_c"), "exec_min_size": kw.get("exec_min_size"),
        "tradable_now": kw.get("tradable_now", ""), "market_status": kw.get("market_status", "active"),
        "rule_flag": kw.get("rule_flag", ""), "sport": kw.get("sport", "tennis"),
        "name": kw.get("name", "X"), "url": kw.get("url", ""),
        "action_1_text": kw.get("a1", ""), "action_2_text": kw.get("a2", ""),
        "legs": kw.get("legs"), "payout_floor_c": kw.get("payout_floor_c"), "roi_pct": kw.get("roi_pct"),
    }


def snap(ts, *rows):
    return {"fetched_at": f"t{ts}", "fetched_ts": float(ts), "opportunities": list(rows)}


# --- §8 new-actionable -----------------------------------------------------------------
def test_new_actionable_only_freshly_actionable():
    prev = snap(1, op("a", "actionable"), op("b", "blocked"))
    cur = snap(2, op("a", "actionable"), op("c", "actionable"))
    assert {r["opportunity_id"] for r in lifecycle.new_actionable(prev, cur)} == {"c"}


def test_new_actionable_suppressed_without_prev():
    assert lifecycle.new_actionable(None, snap(1, op("a"))) == []
    assert lifecycle.new_actionable(snap(1, op("a")), None) == []


def test_first_seen_numeric_and_actionable_only():
    hist = [snap(5, op("a", "blocked")), snap(7, op("a", "actionable"))]
    assert lifecycle.first_seen(hist, "a") == 5.0
    assert lifecycle.first_seen(hist, "a", actionable_only=True) == 7.0
    assert lifecycle.first_seen(hist, "missing") is None


def test_persisting_new_actionable_uses_full_history_not_window_slice():
    # `a` became actionable at ts=100 and is STILL actionable at ts=160.
    hist = [snap(100, op("a", "actionable")), snap(160, op("a", "actionable"))]
    # window 30s from now=160 -> first-actionable (100) is 60s ago > 30 -> NOT new (the clip-safety case).
    assert lifecycle.persisting_new_actionable(hist, 30, now_ts=160) == []
    # window 100s -> 60 <= 100 -> still flagged new (persists across refreshes).
    assert {r["opportunity_id"] for r in lifecycle.persisting_new_actionable(hist, 100, now_ts=160)} == {"a"}


def test_persisting_new_actionable_none_window_falls_back_to_single_transition():
    hist = [snap(1, op("a", "actionable")), snap(2, op("a", "actionable"), op("b", "actionable"))]
    assert {r["opportunity_id"] for r in lifecycle.persisting_new_actionable(hist, None, now_ts=2)} == {"b"}


# --- §9 blocked-change -----------------------------------------------------------------
def test_blocked_change_classifies_each_dimension():
    prev = snap(1, op("a", "blocked", blocked_reason="no size", exec_gap_c=3, exec_min_size=0,
                      status="S1", market_status="active", tradable_now="No", rule_flag=""))
    cur = snap(2, op("a", "blocked", blocked_reason="leg inactive", exec_gap_c=5, exec_min_size=10,
                     status="S2", market_status="inactive", tradable_now="No", rule_flag="RULE_MISMATCH"))
    res = lifecycle.blocked_change(prev, cur)
    assert len(res) == 1
    assert set(res[0]["changes"]) == {"blocker", "price", "liquidity", "status", "market_status",
                                      "rule_flag_changed"}   # tradable_now unchanged -> absent


def test_blocked_change_enter_and_leave_are_flagged():
    enter = lifecycle.blocked_change(snap(1, op("a", "actionable", tradable_now="Yes")),
                                     snap(2, op("a", "blocked", tradable_now="No")))
    assert enter and enter[0]["transitioned"] and enter[0]["cur_bucket"] == "blocked"
    leave = lifecycle.blocked_change(snap(1, op("a", "blocked", tradable_now="No")),
                                     snap(2, op("a", "actionable", tradable_now="Yes")))
    assert leave and leave[0]["transitioned"] and leave[0]["cur_bucket"] == "actionable"


def test_blocked_change_no_change_and_neither_blocked_are_silent():
    same = op("a", "blocked", blocked_reason="x", exec_gap_c=3, status="S")
    assert lifecycle.blocked_change(snap(1, same), snap(2, dict(same))) == []        # identical -> silent
    assert lifecycle.blocked_change(snap(1, op("a", "clean")), snap(2, op("a", "near_edge"))) == []  # neither blocked


# --- §10 recently-actionable -----------------------------------------------------------
def test_recently_actionable_went_blocked_with_fields():
    snaps = [snap(1, op("a", "actionable", exec_gap_c=5, sport="nba", name="A vs B", url="u")),
             snap(2, op("a", "actionable", exec_gap_c=4, sport="nba", name="A vs B", url="u")),
             snap(3, op("a", "blocked", market_status="active", sport="nba", name="A vs B"))]
    res = lifecycle.recently_actionable(snaps)
    assert len(res) == 1
    r = res[0]
    assert r["opportunity_id"] == "a"
    assert r["became_ts"] == 1.0 and r["left_ts"] == 3.0 and r["duration_s"] == 1.0
    assert r["reason_left"] == "went blocked"
    assert r["last_edge_c"] == 4 and r["sport"] == "nba"   # last actionable snapshot (ts2)


def test_recently_actionable_carries_last_legs_and_floor_roi():
    # PR 13: the backlog carries the full N-leg plan + floor/ROI as the opp last looked actionable.
    legs = [{"text": "Buy YES — Reach Final @ 40¢"}, {"text": "Buy NO — Win @ 38¢"}]
    snaps = [snap(1, op("a", "actionable", legs=legs, payout_floor_c=100, roi_pct=9.0)),
             snap(2, op("a", "blocked", market_status="active"))]
    r = lifecycle.recently_actionable(snaps)[0]
    assert r["last_legs"] == legs and r["payout_floor_c"] == 100 and r["roi_pct"] == 9.0


def test_recently_actionable_excludes_still_actionable():
    assert lifecycle.recently_actionable([snap(1, op("a", "actionable")),
                                          snap(2, op("a", "actionable"))]) == []


def test_recently_actionable_reason_precedence():
    leg = lifecycle.recently_actionable([snap(1, op("a", "actionable")),
                                         snap(2, op("a", "blocked", market_status="inactive"))])
    assert leg[0]["reason_left"] == "leg inactive"          # inactive beats "went blocked"
    gone = lifecycle.recently_actionable([snap(1, op("a", "actionable")), snap(2, op("b", "clean"))])
    assert gone[0]["reason_left"] == "disappeared"
    clean = lifecycle.recently_actionable([snap(1, op("a", "actionable")), snap(2, op("a", "clean"))])
    assert clean[0]["reason_left"] == "went clean"


def test_recently_actionable_empty_history():
    assert lifecycle.recently_actionable([]) == []


# --- Edge cases / robustness (extensive) ----------------------------------------------
def test_handles_unordered_snapshot_input():
    # Newest-first input must be sorted internally (store returns ascending, but be defensive).
    snaps = [snap(3, op("a", "blocked", market_status="active")),
             snap(1, op("a", "actionable", exec_gap_c=5)),
             snap(2, op("a", "actionable", exec_gap_c=4))]
    r = lifecycle.recently_actionable(snaps)[0]
    assert r["became_ts"] == 1.0 and r["left_ts"] == 3.0
    assert lifecycle.first_seen(snaps, "a", actionable_only=True) == 1.0


def test_blocked_change_nan_gap_is_not_a_phantom_change():
    nan = float("nan")
    prev = snap(1, op("a", "blocked", exec_gap_c=nan, blocked_reason="x", status="S"))
    cur = snap(2, op("a", "blocked", exec_gap_c=nan, blocked_reason="x", status="S"))
    assert lifecycle.blocked_change(prev, cur) == []          # NaN != NaN must NOT register as 'price'


def test_persisting_now_ts_defaults_to_latest_snapshot_ts():
    hist = [snap(100, op("a", "actionable")), snap(160, op("a", "actionable"))]
    assert {r["opportunity_id"] for r in lifecycle.persisting_new_actionable(hist, 100, now_ts=None)} == {"a"}
    assert lifecycle.persisting_new_actionable(hist, 30, now_ts=None) == []   # ref = latest ts (160)


def test_recently_actionable_multiple_actionable_intervals():
    snaps = [snap(1, op("a", "actionable")), snap(2, op("a", "clean")),
             snap(3, op("a", "actionable")), snap(4, op("a", "blocked"))]
    r = lifecycle.recently_actionable(snaps)[0]
    assert r["became_ts"] == 1.0          # FIRST time actionable
    assert r["left_ts"] == 4.0            # snapshot after the LAST actionable (ts3)
    assert r["duration_s"] == 2.0         # first-actionable (ts1) -> last-actionable (ts3) span
    assert r["reason_left"] == "went blocked"


def test_lifecycle_on_store_roundtripped_snapshots(tmp_path):
    """The real path: lifecycle consumes rows that went through store JSON (None -> null -> None,
    not NaN). Must not phantom-change or crash."""
    import store
    db = str(tmp_path / "lc.db")
    store.write_snapshot(1, [op("a", "actionable", exec_gap_c=5),
                             op("b", "actionable", exec_gap_c=None)], db_path=db)   # b: missing gap
    store.write_snapshot(2, [op("a", "blocked", market_status="inactive", exec_gap_c=5),
                             op("b", "actionable", exec_gap_c=None)], db_path=db)
    prev, cur = store.latest_two(db_path=db)
    ch = lifecycle.blocked_change(prev, cur)
    assert {c["opportunity_id"] for c in ch} == {"a"}        # a went blocked; b unchanged & never blocked
    rec = lifecycle.recently_actionable(store.snapshots_since(10 ** 9, db_path=db))
    assert any(r["opportunity_id"] == "a" and r["reason_left"] == "leg inactive" for r in rec)
