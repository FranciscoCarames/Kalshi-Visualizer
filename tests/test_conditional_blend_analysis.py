"""Unit tests for the Phase-0B offline analyzer (pure, no I/O)."""
from __future__ import annotations

import conditional_blend_analysis as cba


def _snap(cid, ts, *, gap_mid, a_ask, a_bid, blend, gate=False, complement=2):
    return {
        "status": cba.MODEL_BLEND_CANDIDATE, "candidate_id": cid, "snapshot_ts": ts,
        "model_gap_to_ask_mid_c": gap_mid, "market_implied_blend_mid_c": blend,
        "A_winNext_ask_c": a_ask, "A_winNext_bid_c": a_bid,
        "complement_gap_c": complement, "gate_pass": gate,
    }


def test_persistence_halflife_and_convergence():
    # one candidate over 3 snapshots: gap decays 12 → 6 → 3 (halves by snap 1) and A converges up to blend
    rows = [
        _snap("x", "2026-07-19 12:00:00 UTC", gap_mid=12, a_ask=68, a_bid=66, blend=80, gate=True),
        _snap("x", "2026-07-19 12:05:00 UTC", gap_mid=6, a_ask=74, a_bid=72, blend=80, gate=True),
        _snap("x", "2026-07-19 12:10:00 UTC", gap_mid=3, a_ask=78, a_bid=76, blend=80),
    ]
    r = cba.analyze_samples(rows)
    s = r["summary"]
    assert s["distinct_candidates"] == 1 and s["candidate_snapshots"] == 3
    assert s["median_persistence_snaps"] == 3
    p = r["per_candidate"][0]
    assert p["halved"] and p["half_life_min"] == 5.0          # gap ≤ 6 first at the 12:05 snapshot
    assert p["converged"] and p["convergence_frac"] > 0.5     # A-mid 67 → 77, toward blend 80
    assert s["gatepass_rate"] == round(2 / 3, 3)


def test_candidate_id_groups_and_blend_vs_complement():
    rows = [
        _snap("a", "2026-07-19 12:00:00 UTC", gap_mid=10, a_ask=60, a_bid=58, blend=70, complement=3),
        _snap("b", "2026-07-19 12:00:00 UTC", gap_mid=8, a_ask=50, a_bid=48, blend=58, complement=2),
    ]
    r = cba.analyze_samples(rows)
    assert r["summary"]["distinct_candidates"] == 2
    assert r["summary"]["blend_beats_complement"] is True     # mean|gap| 9 > mean|complement| 2.5


def test_insufficient_sample_verdict():
    rows = [_snap("only", "2026-07-19 12:00:00 UTC", gap_mid=10, a_ask=60, a_bid=58, blend=70, gate=True)]
    r = cba.analyze_samples(rows)
    assert r["summary"]["verdict"] == "INSUFFICIENT SAMPLE"   # < 20 candidates
    assert r["gate"]["candidates"][0] is False


def test_empty_input_is_safe():
    r = cba.analyze_samples([])
    assert r["summary"]["distinct_candidates"] == 0
    assert r["summary"]["verdict"] in ("INSUFFICIENT SAMPLE", "FAIL")
    assert "conditional-blend validation report" in cba.format_report(r)


def test_pass_verdict_when_all_gates_clear():
    rows = []
    for i in range(20):                                       # 20 candidates, each persists 2 snaps,
        cid = f"c{i}"                                         # halves, converges, and gate-passes
        rows.append(_snap(cid, "2026-07-19 12:00:00 UTC", gap_mid=10, a_ask=60, a_bid=58, blend=70, gate=True))
        rows.append(_snap(cid, "2026-07-19 12:05:00 UTC", gap_mid=4, a_ask=66, a_bid=64, blend=70, gate=True))
    r = cba.analyze_samples(rows)
    assert r["summary"]["verdict"] == "PASS"
    assert all(ok for ok, _ in r["gate"].values())
