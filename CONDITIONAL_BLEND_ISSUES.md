# Conditional-blend detector — issues log

Every issue discovered while implementing `.claude/plans/warm-coalescing-eclipse.md` (the
opponent-resolution dynamic detector). Branch `feat/conditional-blend-detector`. Severity:
**H** = correctness/economic-viability, **M** = soundness/robustness, **L** = minor, **Info** = finding.
Status: **Resolved** / **Fixed (commit)** / **Open** / **Inherent** / **Not-a-bug**.

## A. Design & math issues (surfaced by the critical pre-build audit)

| ID | Sev | Status | Issue → resolution |
|----|-----|--------|--------------------|
| A1 | H | Resolved | **Blend was overgeneralized to earlier rounds** — `A_fair = ΣP·P(A beats)` with target "win tournament" silently drops A's remaining-path probability past the next match. → Owner's reframing: target = **"win the NEXT round"** (a single immediate match), which makes the conditional ratio clean at the decided stage; the detector is anchored to the final-decider and self-gates elsewhere. |
| A2 | M | Resolved | **"Market-implied = no model" was misleading** — it IS a model (assumes prices≈probabilities, vig cancels, legs fresh, convergence occurs). → Honest labels throughout: `market_implied_blend_*` (never "fair"), `model_gap_to_ask_*` (never "edge"), status `MODEL_BLEND_CANDIDATE`; every row carries a "not fair value / not arbitrage / can lose money" note. |
| A3 | H | Resolved | **Raw point conditional ratios are unsafe** (spread, stale quotes, one-sided books, thin size). → Conservative **bid/ask interval** is the firing gate; the midpoint is diagnostic-only. |
| A4 | M | Resolved | **`pB_ask + pC_ask ≈ 100` sanity check was wrong** — within a 2-way book two asks sum to 100 + spread (double-counts vig). → Normalized **mid** weights remove the double-count; explicit quote-side semantics; complementarity tolerance on mids. |
| A5 | M | Resolved | **Fee multiplier wrongly called "UI-tainted"** — it is per-series market metadata (`fetch_contracts` `fee_rates`). → `roundtrip_cost.effective_coeffs` resolves the real `fee_type`/`fee_multiplier`; `fee_known=False` (unknown/assumed) **blocks** the cost gate instead of defaulting to a base coefficient. |
| A6 | L | Resolved | **Single round-trip cost too coarse** (hold vs convergence-exit vs maker differ). → Three logged cost paths: `cost_hold_c`, `cost_roundtrip_taker_c`, `cost_maker_entry_taker_exit_c`. |
| A7 | M | Resolved | **Validation gate was vague** (post-hoc overfitting risk). → **Predeclared** go/no-go thresholds written before data collection (`CONDITIONAL_BLEND_VALIDATION.md`). |
| A8 | M | Resolved | **Persistence join keys fragile** (B/C order flips, missing event_ticker). → Canonical `candidate_id = sha1(sport, tournament, deeper, broader, A, sorted(B,C))`; `schema_version` stamped. |
| A9 | L | Resolved | **Field-underround row conceptually muddled** ("closer to arb" but not exhaustiveness-proven). → Single `FIELD_UNDERROUND_DIAGNOSTIC`, logging-only, no arb language. |
| A10 | H | Partially resolved / **Open** | **Adjacency** — proving the B/C winner actually becomes A's opponent — is NOT removed by the next-round reframing. → Provable from prices at the **final-decider** (closed-pair guard); **earlier rounds need bracket-slot metadata that Kalshi does not expose** (confirmed, see C7). Detector fails closed off the final. |

## B. Code bugs

| ID | Sev | Status | Issue → resolution |
|----|-----|--------|--------------------|
| B1 | H | **Fixed (f3e472a)** | **Fired on a one-sided (ask-only) A target** — buyable but no bid to sell into, so a convergence exit is impossible. → Stamp `exit_liquidity`; block `gate_pass` unless A's "win next round" market has a firm bid (still surfaced as a real mispricing). Found by live adversarial testing. |
| B2 | L | Fixed (47002ed) | ruff `F841` unused `a_br`. → Removed. |
| B4 | M | **Fixed** | **`FIELD_UNDERROUND_DIAGNOSTIC` leaked into the SPA.** The live end-to-end test (real server, flag ON, injected demo final-decider) showed the scanner mapped *all* `find_conditional_blends` outputs through `_to_unified_conditional_blend` — so the logging-only field-underround diagnostic surfaced in the SPEC-MODEL section as a malformed row (`name=""`, "None vs None decides 's opponent…"). → Scanner now maps **only `MODEL_BLEND_CANDIDATE`** findings to unified rows; the diagnostic stays CSV-only. Regression test added. Found by the browser/API live test. |
| B3 | H | **Fixed** | **Field-sport false positive** — the detector fired a garbage candidate on golf's "Top 5" rung (`survivors_of=5`), where there is no head-to-head "this round" decider and the blend `P(A beats B)` is meaningless. The original price-only closed-pair proof did not exclude field rungs. → Require `cfg.survivors_of(broader) == 2` (a genuine 2-survivor head-to-head slot); excludes golf/motorsport/field rungs and earlier non-2-way bracket rungs while admitting every bracket sport's final pair. Found by the round-2 cross-sport probe; regression test added. |

## C. Live-data findings & inherent strategy limitations (2026-06-19 live probe)

| ID | Sev | Status | Finding |
|----|-----|--------|---------|
| C1 | Info/H | **Open** | **No fire-able setup exists in any live market right now** — WC is in the group stage (0 teams locked into any knockout rung), tennis is early-round, WNBA mid-season; basketball/hockey/baseball have 0 live rows. Detector fired **0 candidates on 1400+ real rows, 0 false positives**. Live FIRE-path validation must wait for a knockout window (WC SF ~July, or a tennis SF). |
| C2 | M | Inherent | **The setup is rare/episodic** — it only exists when one finalist is locked AND the other semifinal is live. Weigh against build cost. |
| C3 | M | Mitigated | **Sub-penny ratios at early stages** — group-stage reach-final is 1–2¢ for most teams, so `win/reach = 0/1` is noise. The lock gate restricts firing to high-reach-final favorites near the final. |
| C4 | H | **Open / Inherent** | **Thin edges die on fees** — a realistic 6¢ MID gap shrank to a +1¢ CONSERVATIVE gap, below the 4¢ round-trip cost → no gate pass. The strategy needs FAT gaps; most apparent edges are untradeable. |
| C5 | H | **Open** | **Convergence is the entire thesis and is unproven** — payoffs check out, but whether A's lagging price actually re-converges (vs. drifts/reverses) can only be measured by the live forward-test. The Phase-0B analyzer is built to measure it. |
| C6 | — | Resolved (validated) | **The lock requirement is essential** — `win/reach_final` is P(team beats a *generic* finalist) (France 19/32 = 0.59), NOT P(beats A), until A is the locked unique other finalist. The lock gate enforces this; live prices confirm why it's needed. |
| C7 | M | Open | **No bracket/group membership in the contract rows** to localize earlier-round fields (a group with 1 clinched + 2 fighting for 2nd is the structure, but it's invisible to a global price proof; and group "deciding" is 3-way, not head-to-head, so the ratio wouldn't be valid anyway). Confirms A10. |
| C8 | — | Resolved (validated) | **Closed-pair guard defeats the no-bracket false positive** — two coincidentally-complementary teams in *different* semis are correctly SKIPPED (their other semifinalists show as extra live contenders → >2 live). Adversarially confirmed. |
| C10 | — | Resolved (validated) | **Full live end-to-end test (2026-06-19):** booted the real server with the detector ON, injected a realistic final-decider into the soccer fetch so the REAL scan fired a candidate; verified scan→store→feed→API→SPA. The feed served exactly **one clean `MODEL_BLEND_CANDIDATE`** (after B4); the SPA rendered the **SPEC-MODEL** tile/section/row with edge "—", "Speculative — model validation only", and the full honesty caveat; the **Inspector** showed the "market-implied, NOT fair value/NOT arbitrage/can lose money/never Actionable" caveat + `Status: MODEL_BLEND_CANDIDATE`. Console errors were only harmless 401s from auth-disabled prefs. |
| C9 | — | Resolved (validated) | **Round-2 hardening (2026-06-19):** all-10-sport live sweep = **3760 rows, 0 candidates, 0 crashes** (golf no longer fires after B3); a biased fuzz fired **5,951 candidates with 0 invariant violations** (exec_gap_c always None, blend & probs in range, blend_lower ≤ blend_mid, gate_pass ⇒ fee_known + exit bid + conservative gap > cost); detector is **order-independent/deterministic** (identical candidate_ids across shuffles); analyzer survives malformed/hostile CSV rows without crashing. |

## D. Process / tooling

| ID | Sev | Status | Note |
|----|-----|--------|------|
| D1 | L | Resolved | **Original plan file was lost** (lived under gitignored `.claude/`, never tracked, deleted from disk). → Reconstructed from the memory pointer + predecessor strategy docs. |
| D2 | L | Fixed | **Windows console (cp1252) can't print Unicode** (`·`, `→`, `≥`) → `UnicodeEncodeError`. Surfaced first in diagnostics, then in *shipped* code: the Phase-0B analyzer's report used `≥` and crashed under a default Windows console/pipe. → Analyzer report made ASCII-only (`>=`); diagnostics use `PYTHONIOENCODING=utf-8`. cp1252 console smoke now passes. |
| D8 | — | Resolved (audit) | **Phase 2 (SPA↔NiceGUI parity) audit done** → `SPA_NICEGUI_PARITY_AUDIT.md`. SPA is ~79% feature-complete (142 FULL / 27 PARTIAL / 11 MISSING). Top gap = the field-de-vig conditional-probability estimate (PARTIAL — raw ratios shown, no de-vig; the detector does NOT depend on it). Porting is a **separate owner-prioritized workstream** (own branch per item), deliberately NOT bundled onto the detector branch. |
| D7 | L | Open (display follow-up) | **Blend summary placement.** The feed sets `sub = tournament`, and both the Blotter name-cell and the Inspector subtitle prefer `sub` over `detail` — so the model-blend summary (carried in `detail`) shows in the Blotter's `detail` COLUMN + the Inspector caveat, but not the subtitle. Fine for the flag-off/validation-pending state; when the feature goes live, add a dedicated `specmodel` columns catalog (blend / gap / cost columns) for a cleaner display. |
| D6 | M | Resolved | **Phase-1 FRONTEND rendering (behind the flag).** Added the `SPEC-MODEL` section to the SPA: backend `webui/feed.py` `_SEC` maps `speculative_model → (spec, specmodel)`; frontend `feed.ts` adds it to `SUBTABS.spec` / `TILES` / `SECTION_BUCKET`; `Inspector.tsx` shows a display-only "market-implied, NOT fair value / NOT arbitrage / can lose money" caveat. Verified end-to-end (backend `_build_row` → `spec/specmodel`; 113 vitest incl. new `feed.test.ts`; `npm run build` OK). Inert until the flag is enabled (no rows otherwise). `CLAUDE.md` scope guard updated for the owner-approved, flag-gated SPA exception. |
| D5 | M | Resolved | **Phase-1 backend wiring (DEFAULT-OFF).** Wired the detector into `scanner.unified_opportunities` behind `config.CONDITIONAL_BLEND_DEFAULT_ENABLED` / env `CONDITIONAL_BLEND_ENABLED`; new `speculative_model` bucket (+ `BUCKET_PRIORITY`/`DASHBOARD_BUCKETS`/`STATUS_GROUP`/`bucket_of`). Isolation suite proves flag-off emits nothing and **enabling leaves executable rows byte-identical**, blend rows never outrank actionable, routing invariant preserved. Avoided a circular import (consistency keeps the status as a string literal) and schema bloat (no new UNIFIED columns — blend summary rides `detail`). **Remaining Phase 1:** React SPA rendering + `CLAUDE.md` scope-guard update, gated on a green report before the flag is flipped. |
| D4 | L | Resolved | **Phase-0B analyzer added** (`conditional_blend_analysis.py` + `scripts/analyze_conditional_blend.py` + tests): scores the sampler CSV against the predeclared gate (persistence / half-life / convergence / gate-pass / blend-vs-complement → PASS/FAIL/INSUFFICIENT SAMPLE). Completes the validation harness so the go/no-go is mechanical the moment a live knockout produces candidates. |
| D3 | — | Not-a-bug | **Tournament-key split** ('World Cup · 26' vs a 96-row 'World Cup') investigated → the second group is `KXWCGROUPORDER` exact-order markets (`ladder_node=None`) that never enter the blend; the main group holds both reach-final and win. No fix needed. |

---
_Open items that gate Phase 1: A10/C7 (earlier-round adjacency needs bracket data), C1/C5 (fire-path +
convergence unvalidated until a live knockout), C4 (economic viability under fees). Resolve via the live
forward-test + the Phase-0B analyzer before any SPA wiring._
