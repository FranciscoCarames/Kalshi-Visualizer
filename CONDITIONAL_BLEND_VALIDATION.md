# Conditional-blend detector — Phase 0 (dark) handoff & validation protocol

**Branch:** `feat/conditional-blend-detector` (off `origin/main`). **Status:** Phase 0A built + tested
(1309 pytest, ruff clean, no existing engine files touched). Phases 1–2 are **gated on the live
forward-test report below** and are NOT implemented. Plan: `.claude/plans/warm-coalescing-eclipse.md`.

## What this is
Detects the owner's opponent-resolution strategy: A is through to round R and waiting; B and C compete
**this round** to decide A's R opponent. A's price to **win the next round (R)** should be a
market-implied blend:

```
A_winNext_fair = P(B wins this round)·P(A beats B) + P(C wins this round)·P(A beats C)
P(A beats B)   = 1 − B_winNext / B_winThis      (= 1 − B_deeper/B_broader on the ladder)
```

It is a **market-implied, model-based CONVERGENCE candidate — not arbitrage, not fair value, can lose
money.** Every finding is `exec_gap_c=None`, display-only, never ranked. Nothing is wired into the
scanner/SPA/lifecycle.

## Files
- `conditional_blend.py` — pure detector (`find_conditional_blends(records, *, snapshot_ts, fee_rates,
  diag)`), fail-closed linkage proof, conservative interval gate, honest labels.
- `roundtrip_cost.py` — pure fee/round-trip cost (real per-series `fee_multiplier`; `fee_known=False`
  blocks the cost gate).
- `scripts/validate_conditional_blend.py` — dark sampler → append-only throwaway CSV (logs cadence +
  latency).
- `tests/test_conditional_blend.py`, `tests/test_roundtrip_cost.py`.

## How to collect data (owner runs during live World Cup matches)
```bash
# single snapshot:
python scripts/validate_conditional_blend.py --sport soccer --out conditional_blend_samples.csv
# loop every 60s through a live knockout match (needs network — Bash sandbox disabled):
python scripts/validate_conditional_blend.py --sport soccer --interval 60
```
The CSV is the validation substrate (gitignored as a throwaway). Persistence / half-life / re-convergence
are computed offline by joining snapshots on `candidate_id` (stable under B/C ordering).

## Adjacency audit (Phase-0 task #1) — current finding
The blend math is clean at every round (next-round target), but it still requires proof that **the B/C
winner actually becomes A's opponent**. The detector proves this purely from prices via the closed-pair
shape: at the `broader` rung there must be exactly **1 locked (A) + 2 complementary live (B,C)** with
everyone else eliminated.
- **Final pair** (`deeper = Win the World Cup`): this shape is provable from prices today → fires
  (`adjacency_proof="closed_pair_final"`). Verified in tests; live-confirm during a WC semifinal→final.
- **Earlier rounds**: the same price shape only narrows to 3 once the local field has collapsed — globally
  there are >2 live contenders at an early `broader` rung, so the proof (correctly) fails and the detector
  SKIPS. Unlocking earlier rounds needs **explicit bracket-slot metadata** (which seed feeds A's slot).
  **OPEN QUESTION for the live run:** confirm whether Kalshi's WC contracts expose a usable pairing signal
  (a next-round match/`opponent` field, or a `KXWC*` bracket token) tying the B/C event's winner to A. If
  yes, an earlier-round path can be added; if no, the detector stays final-anchored. Record the answer in
  the report below.

## Predeclared go/no-go gate (set BEFORE looking at results — do not move the goalposts)
Promote to Phase 1 (SPA) only if, on the collected CSV:
1. **≥ 20 independent `candidate_id`s** observed (else mark "sample too small").
2. **Every fired linkage manually audited** — false-positive list attached.
3. Conservative `model_gap_to_ask_lower_c` **positive after the applicable fee path** in **≥ 50%** of
   candidate-snapshots (`gate_pass=True`).
4. **Median persistence ≥ 2 scan intervals** (the manual-fill proxy — a gap that vanishes in one snapshot
   is untradeable by hand).
5. **A's mid actually drifts toward the blend** after detection (convergence realized, not just a static
   discrepancy) in a clear majority of cases.
6. The matchup blend **beats the model-free `complement_gap_c` baseline** after fees/spread.
7. Top-of-book `A_target_ask_size` supports a **standardized $100 notional** in a usable share, else rows
   are flagged "size-limited".

A green report unlocks Phase 1 (SPA surfacing, feature-flagged, never Actionable, with the isolation test
suite). It also changes a checked-in `CLAUDE.md` invariant (cond-prob enters the SPA) — call that out in
the Phase-1 PR.

## Validation report (fill in after the live run)
_Candidates observed: … · gate-pass %: … · median persistence: … · convergence: … · blend-vs-complement:
… · adjacency finding: … · verdict: ship Phase 1 / iterate / drop._
