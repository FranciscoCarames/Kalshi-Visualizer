"""Offline analysis of the conditional-blend dark-validation CSV (Phase 0B) — PURE, stdlib only.

Turns the append-only sampler output (``scripts/validate_conditional_blend.py`` → one row per candidate
per snapshot) into the predeclared go/no-go metrics from ``CONDITIONAL_BLEND_VALIDATION.md``: candidate
count, gate-pass rate, persistence, signal half-life, realized convergence, and matchup-blend vs the
model-free complement baseline. No I/O here — the CLI wrapper reads the CSV and hands rows in; this stays
unit-testable on synthetic rows.
"""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

MODEL_BLEND_CANDIDATE = "MODEL_BLEND_CANDIDATE"

# Predeclared go/no-go gate (must match CONDITIONAL_BLEND_VALIDATION.md — set BEFORE looking at results).
GATE = {
    "min_candidates": 20,
    "min_gatepass_rate": 0.50,          # fraction of candidate-snapshots with gate_pass True
    "min_median_persistence_snaps": 2,  # a gap that vanishes in one snapshot is untradeable by hand
    "min_convergence_rate": 0.50,       # fraction of candidates whose A-mid drifts toward the blend
    "blend_must_beat_complement": True,
}


def _num(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _bool(x: Any) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


def _parse_ts(s: Any) -> datetime | None:
    t = str(s or "").replace(" UTC", "").strip()
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _a_mid(row: dict[str, Any]) -> float | None:
    ask, bid = _num(row.get("A_winNext_ask_c")), _num(row.get("A_winNext_bid_c"))
    if ask is not None and bid is not None:
        return (ask + bid) / 2.0
    return ask if ask is not None else bid


def _analyze_one(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics for a single candidate_id's snapshots (already sorted by time)."""
    gaps = [_num(s.get("model_gap_to_ask_mid_c")) for s in snaps]
    gaps = [g for g in gaps if g is not None]
    t0 = _parse_ts(snaps[0].get("snapshot_ts"))
    tn = _parse_ts(snaps[-1].get("snapshot_ts"))
    lifetime_min = round((tn - t0).total_seconds() / 60, 1) if (t0 and tn) else None

    # half-life: first snapshot whose mid gap <= half the initial gap
    half_life_min = half_life_snaps = None
    if gaps and gaps[0] > 0:
        for i, g in enumerate(gaps):
            if g <= gaps[0] / 2:
                half_life_snaps = i
                ti = _parse_ts(snaps[i].get("snapshot_ts"))
                half_life_min = round((ti - t0).total_seconds() / 60, 1) if (t0 and ti) else None
                break

    # convergence: did A's mid drift toward the blend over the candidate's life?
    a0, an = _a_mid(snaps[0]), _a_mid(snaps[-1])
    blend0 = _num(snaps[0].get("market_implied_blend_mid_c"))
    conv_frac = None
    if None not in (a0, an, blend0):
        toward = blend0 - a0
        conv_frac = ((an - a0) / toward) if toward != 0 else None

    return {
        "candidate_id": snaps[0].get("candidate_id"),
        "n_snapshots": len(snaps),
        "lifetime_min": lifetime_min,
        "initial_gap_mid_c": gaps[0] if gaps else None,
        "peak_gap_mid_c": max(gaps) if gaps else None,
        "half_life_snaps": half_life_snaps,
        "half_life_min": half_life_min,
        "halved": half_life_snaps is not None,
        "convergence_frac": conv_frac,
        "converged": conv_frac is not None and conv_frac > 0,
        "gate_pass_ever": any(_bool(s.get("gate_pass")) for s in snaps),
    }


def analyze_samples(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate go/no-go metrics over all sampler rows. Returns a summary dict plus per-candidate detail
    and a ``gate`` block of pass/fail checks against the predeclared thresholds."""
    cand_rows = [r for r in (rows or []) if str(r.get("status")) == MODEL_BLEND_CANDIDATE]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in cand_rows:
        by_id.setdefault(str(r.get("candidate_id") or ""), []).append(r)
    for snaps in by_id.values():
        snaps.sort(key=lambda s: str(s.get("snapshot_ts") or ""))

    per = [_analyze_one(snaps) for snaps in by_id.values() if snaps]
    n = len(per)

    gatepass_rate = (sum(1 for r in cand_rows if _bool(r.get("gate_pass"))) / len(cand_rows)
                     if cand_rows else 0.0)
    persists = [p["n_snapshots"] for p in per]
    halflives = [p["half_life_min"] for p in per if p["halved"] and p["half_life_min"] is not None]
    conv_rate = (sum(1 for p in per if p["converged"]) / n) if n else 0.0

    blend_mag = [abs(g) for g in (_num(r.get("model_gap_to_ask_mid_c")) for r in cand_rows) if g is not None]
    comp_mag = [abs(g) for g in (_num(r.get("complement_gap_c")) for r in cand_rows) if g is not None]
    blend_mean = statistics.mean(blend_mag) if blend_mag else 0.0
    comp_mean = statistics.mean(comp_mag) if comp_mag else 0.0

    summary = {
        "distinct_candidates": n,
        "candidate_snapshots": len(cand_rows),
        "gatepass_rate": round(gatepass_rate, 3),
        "candidates_ever_gatepass": sum(1 for p in per if p["gate_pass_ever"]),
        "median_persistence_snaps": (statistics.median(persists) if persists else 0),
        "median_half_life_min": (round(statistics.median(halflives), 1) if halflives else None),
        "half_life_censored": sum(1 for p in per if p["initial_gap_mid_c"] and not p["halved"]),
        "convergence_rate": round(conv_rate, 3),
        "blend_mean_abs_c": round(blend_mean, 2),
        "complement_mean_abs_c": round(comp_mean, 2),
        "blend_beats_complement": blend_mean > comp_mean,
    }

    gate = {
        "candidates": (n >= GATE["min_candidates"], f"{n} >= {GATE['min_candidates']}"),
        "gatepass_rate": (gatepass_rate >= GATE["min_gatepass_rate"],
                          f"{gatepass_rate:.0%} >= {GATE['min_gatepass_rate']:.0%}"),
        "persistence": (summary["median_persistence_snaps"] >= GATE["min_median_persistence_snaps"],
                        f"median {summary['median_persistence_snaps']} >= {GATE['min_median_persistence_snaps']} snaps"),
        "convergence": (conv_rate >= GATE["min_convergence_rate"],
                        f"{conv_rate:.0%} >= {GATE['min_convergence_rate']:.0%}"),
        "blend_vs_complement": (summary["blend_beats_complement"] or not GATE["blend_must_beat_complement"],
                                f"blend {blend_mean:.1f}c vs complement {comp_mean:.1f}c"),
    }
    summary["verdict"] = "PASS" if all(ok for ok, _ in gate.values()) else (
        "INSUFFICIENT SAMPLE" if n < GATE["min_candidates"] else "FAIL")
    return {"summary": summary, "gate": gate, "per_candidate": per}


def format_report(result: dict[str, Any]) -> str:
    s, g = result["summary"], result["gate"]
    lines = ["=== conditional-blend validation report ===",
             f"distinct candidates      : {s['distinct_candidates']}  ({s['candidate_snapshots']} candidate-snapshots)",
             f"gate-pass rate (post-fee): {s['gatepass_rate']:.0%}  ({s['candidates_ever_gatepass']} candidates ever passed)",
             f"median persistence       : {s['median_persistence_snaps']} snapshots",
             f"median signal half-life  : {s['median_half_life_min']} min  ({s['half_life_censored']} never halved)",
             f"convergence rate         : {s['convergence_rate']:.0%}  (A-mid drifts toward the blend)",
             f"blend vs complement      : {s['blend_mean_abs_c']}c vs {s['complement_mean_abs_c']}c"
             f"  ({'blend wins' if s['blend_beats_complement'] else 'complement wins'})",
             "--- predeclared gate ---"]
    for name, (ok, detail) in g.items():
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    lines.append(f"VERDICT: {s['verdict']}")
    return "\n".join(lines)
