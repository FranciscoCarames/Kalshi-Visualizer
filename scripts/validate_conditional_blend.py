"""Dark validation sampler for the conditional-blend detector (Phase 0).

Fetches one sport's live contracts, runs ``conditional_blend.find_conditional_blends``, and APPENDS every
candidate to a throwaway CSV (one row per detection per snapshot). Run it repeatedly during live matches
(e.g. a cron/loop every minute) to build the time series the offline go/no-go report needs — persistence,
re-convergence, gap-vs-cost, and signal half-life are computed later by joining snapshots on
``candidate_id``. This script writes NO database and is not wired into the app.

    python scripts/validate_conditional_blend.py --sport soccer --out conditional_blend_samples.csv
    python scripts/validate_conditional_blend.py --sport soccer --interval 60      # loop every 60s

Live Kalshi fetches need the Bash tool with the sandbox disabled (network is otherwise blocked).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import conditional_blend  # noqa: E402
import fetch  # noqa: E402
import sports  # noqa: E402

# Stable leading columns; any extra keys a finding carries are appended by the writer.
_COLUMNS = [
    "schema_version", "check_type", "status", "candidate_id", "snapshot_ts", "scan_cadence_s",
    "detect_latency_ms", "adjacency_proof", "sport", "tournament", "round_broader", "round_deeper",
    "A_name", "B_name", "C_name", "A_winNext_ask_c", "B_winThis_mid_c", "C_winThis_mid_c",
    "B_winNext_mid_c", "C_winNext_mid_c", "A_beats_B_mid", "A_beats_C_mid",
    "market_implied_blend_mid_c", "market_implied_blend_lower_c", "model_gap_to_ask_mid_c",
    "model_gap_to_ask_lower_c", "complement_gap_c", "cost_hold_c", "cost_roundtrip_taker_c",
    "cost_maker_entry_taker_exit_c", "fee_known", "fee_status", "gate_pass", "A_target_ask_size",
    "field_ask_sum_c", "field_underround_c", "exec_gap_c", "A_key", "B_key", "C_key",
    "settlement_note", "linkage_reason", "legs",
]


def _cell(v):
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, default=str)
    return v


def _families(cfg) -> tuple:
    return tuple(sorted(set(cfg.category_labels.values())))


def sample_once(sport_id: str, out_path: str, cadence_s: int | None) -> int:
    cfg = sports.get_sport(sport_id)
    (df, fetched_at, errors, *_rest, fee_rates) = fetch.fetch_contracts(_families(cfg), False, sport_id)
    records = df.to_dict("records") if not df.empty else []
    diag: list[dict] = []
    t0 = time.time()
    findings = conditional_blend.find_conditional_blends(
        records, snapshot_ts=fetched_at, fee_rates=fee_rates, diag=diag)
    latency_ms = round((time.time() - t0) * 1000, 1)
    for f in findings:
        f.setdefault("scan_cadence_s", cadence_s)
        f.setdefault("detect_latency_ms", latency_ms)

    new_file = not os.path.exists(out_path) or os.path.getsize(out_path) == 0
    extra = [k for f in findings for k in f if k not in _COLUMNS]
    columns = _COLUMNS + sorted(set(extra))
    with open(out_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for f in findings:
            writer.writerow({c: _cell(f.get(c)) for c in columns})

    n_cand = sum(1 for f in findings if f.get("status") == conditional_blend.MODEL_BLEND_CANDIDATE)
    n_pass = sum(1 for f in findings if f.get("gate_pass"))
    print(f"[{fetched_at}] {sport_id}: {len(records)} rows · {n_cand} candidates "
          f"({n_pass} gate-pass) · {len(diag)} near-miss shapes · {latency_ms}ms → {out_path}"
          + (f"  ({len(errors)} fetch errors)" if errors else ""))
    return len(findings)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="soccer", help="sport id (default: soccer / World Cup)")
    ap.add_argument("--out", default="conditional_blend_samples.csv", help="append-only CSV path")
    ap.add_argument("--interval", type=int, default=0,
                    help="loop forever sampling every N seconds (0 = run once)")
    args = ap.parse_args()
    if args.interval and args.interval > 0:
        print(f"sampling {args.sport} every {args.interval}s → {args.out} (Ctrl-C to stop)")
        while True:
            try:
                sample_once(args.sport, args.out, args.interval)
            except Exception as e:                                  # keep the loop alive across transient errors
                print(f"  sample error: {e}")
            time.sleep(args.interval)
    sample_once(args.sport, args.out, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
