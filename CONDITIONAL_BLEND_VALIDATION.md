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
The CSV is the validation substrate (gitignored as a throwaway). Then score it against the predeclared
gate (Phase 0B):
```bash
python scripts/analyze_conditional_blend.py conditional_blend_samples.csv          # report + VERDICT
python scripts/analyze_conditional_blend.py conditional_blend_samples.csv --json   # machine-readable
```
The analyzer (pure `conditional_blend_analysis.py`, unit-tested) joins snapshots on `candidate_id` (stable
under B/C ordering) and computes persistence / signal half-life / realized convergence / gate-pass rate /
blend-vs-complement, then prints **PASS / FAIL / INSUFFICIENT SAMPLE** against the gate below.

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

## Phase 1 enablement (backend wiring built DEFAULT-OFF — do not flip until the gate is green)
The detector is now wired into `scanner.unified_opportunities` behind a flag, fully isolation-tested, but
**off by default** so production is unchanged:
- Flag: `config.CONDITIONAL_BLEND_DEFAULT_ENABLED = False`, or env `CONDITIONAL_BLEND_ENABLED=1` (read at
  the scanner boundary). When on, the scan emits `bucket="speculative_model"`, `status=MODEL_BLEND_CANDIDATE`,
  `exec_gap_c=None`, `tradable_now="Speculative — model validation only"` rows — display-only, **never
  ranked/Actionable** (routed via `consistency.bucket_of` → `speculative_model`, `STATUS_GROUP` →
  "Speculative model").
- Isolation suite (`tests/test_conditional_blend_wiring.py`): flag-off emits nothing; **enabling the
  detector leaves every executable row byte-identical**; blend rows never outrank an actionable edge; the
  `set(BUCKET_PRIORITY)==set(DASHBOARD_BUCKETS)` invariant holds.
- **Remaining for full Phase 1:** the React SPA section/Inspector that renders the `speculative_model`
  bucket (frontend), and the `CLAUDE.md` scope-guard update. Both gated on a green report before the flag
  is flipped on in production.

## Live test findings — 2026-06-19 (static structure probe; fire-path not yet live)
Ran the detector against live Kalshi data across sports and stress-tested payoffs/edge cases.

1. **No fire-able setup exists in ANY live competition right now.** World Cup is in the GROUP STAGE
   (0 teams locked into any knockout rung; 10–48 live contenders per rung); tennis is in early rounds
   (0 locked finalists); WNBA mid-season; basketball/hockey/baseball have 0 live rows. The detector
   correctly fired **0 candidates on 1400+ real rows, with 0 false positives.** → the live FIRE-path
   validation must wait for a knockout window (WC semifinals ~July, or a tennis SF).
2. **The setup is episodic/rare** — it only exists when one finalist is locked AND the other semifinal
   is live. Worth weighing against build cost: how often does the window even open?
3. **The lock requirement is essential (validated on real prices).** `win ÷ reach_final` is
   P(team beats a *generic* finalist), NOT P(beats A) — e.g. France 19/32 = 0.59 = "France beats
   whoever." It only becomes "beats A" once A is the locked, unique other finalist. The detector's
   lock gate enforces exactly this; without it the ratio is opponent-averaged and wrong for the blend.
4. **Sub-penny ratios at early stages:** most teams' reach-final is 1–2¢ in group stage → `win/reach`
   = 0/1 is noise. The ratio is only meaningful for high-reach-final favorites near the final →
   reinforces final-anchoring.
5. **Real winner fields are OVERROUND** (Σ 48 win-asks = 106¢) → `FIELD_UNDERROUND_DIAGNOSTIC` won't
   spam; underround is a transient-mispricing-only event.
6. **The closed-pair proof defeats the no-bracket-data false positives** (adversarially confirmed): two
   coincidentally-complementary teams in *different* semis are rejected because the other semifinalists
   show as extra live reach-final contenders (>2 live → SKIP). This is the key correctness result —
   the price-only proof is sound at the final.
7. **Real ladders are monotonic** (0 inversions in the top 10) and quotes are Tight — good data quality.
8. **Thin edges die on fees (sobering):** a realistic 6¢ MID gap shrank to a +1¢ CONSERVATIVE gap,
   below the 4¢ round-trip cost → `gate_pass=False`. The strategy needs FAT gaps (a big live lag) to
   clear; most apparent edges will not be tradable.
9. **BUG FOUND & FIXED** (commit f3e472a): the detector fired on a one-sided (ask-only) A target —
   buyable but no bid to exit a convergence trade. Now stamps `exit_liquidity` and blocks the gate
   without a firm A bid.
10. **Payoff branches verified** (buy A "win next" @ ask, 1 contract): {B advances, A beats B}=+,
    {B advances, B beats A}=−full, {C advances, A beats C}=+, {C advances, C beats A}=−full.
    EV(hold)=+gap gross but with full 0↔100 variance; convergence-exit captures ~gap − 2 fees, ONLY if
    it converges and an exit bid exists. **Convergence is the entire thesis and is unproven until the
    live forward-test measures it.**

## Validation report (fill in after the live KNOCKOUT run)
_Candidates observed: … · gate-pass %: … · median persistence: … · convergence realized: … ·
blend-vs-complement: … · adjacency finding: … · verdict: ship Phase 1 / iterate / drop._
