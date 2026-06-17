---
session: 2026-06-04
milestone: "—"
topic: real-time-opportunity-engine
slug: detection-correctness-audit
---

# Detection-logic correctness audit + implementation brief (response to external audit)

## Context

An external audit ("you have a strong scanner, not an arb certifier; the word 'riskless' should
disappear") was put to Claude as a critical brainstorming exercise, then turned into a scoped
implementation brief. No code was changed this session — this is the design output to drive a future
**detection-correctness / hardening** milestone (candidate; thematically also fits the paused
`audit-hardening` topic). All recommendations stay inside the scope guard: read-only, gross-only, no
execution, no fee engine, no de-vig.

## Details

### What the audit got wrong (so we don't over-correct)
- **"riskless" is a strawman** — the word is NOT in the codebase. `consistency.py:9` + `glossary.py:98`
  already say "executable inconsistency, NEVER arbitrage"; match-alignment rows are *always*
  `RULE_CHECK_REQUIRED`/`RULE_MISMATCH`; strongest label is `"Locked gross spread"` (gross, explicit).
- **Execution-grade critiques don't apply** — order groups, $25k accountability, resting-order-cancel,
  full-depth fills, batch submission are for a system that places orders. This app is read-only.
- **"Active = tradable" is already conservative** — `_is_active` treats only `status=="active"` as
  tradable; finalized/closed/disputed → `tradable_now="No"` → blocked. Finalized children already kept
  to diagnostics only.
- Fee modeling + full-depth sizing contradict the scope guard → label the limitation, don't build engines.

### The one real bug (highest value)
**Dutch book contradicts the ladder on the SAME tennis match markets.** Ladder flags walkover/no-ball/
retire as equivalence-breaking (`consistency.py:58`); dutch book asserts "NO rule caveat / true
arbitrage" (`dutchbook.py:180`, `scanner.py:107` hardcodes `rule_flag=""`, `glossary.py:131`). A tennis
match that never starts voids/fair-prices both legs → MECE-by-construction fails. Team series/games are
cleaner but not bulletproof. Fix = make settlement-rule risk a per-sport/per-family property.

### Confirmed code facts (grounding the brief)
- `mutually_exclusive` is captured NOWHERE; `rules_secondary` dropped (only `rules_primary` used in
  `_rule_flag`). Both trivially addable at `data.py:629` — `event` and `market` dicts are in scope there
  (already grabs `event.get("product_metadata")` two lines down).
- `build_checks` walks `ladder.adjacent_pairs` ONLY → missing middle rung kills the signal (transitive
  containment still holds, currently un-checked → false negative).
- `scenario_payoffs` (`consistency.py:688`) already enumerates terminal states incl. an equivalence
  "rules diverge / payout unknown" risk row → extend it for abnormal states; dutch books have NO payoff
  table yet.
- `bucket_of` routes `EXECUTABLE_DUTCH_BOOK` to actionable when `tradable_now` starts "Yes" → a
  rule-dependent-but-tradable book stays actionable WITH the caveat (no routing change needed).

## Outcome — the brief (priority order, one PR each off `main`)

1. **PR A — dutch-book settlement caveat (SMALL, do first).** Add `SportConfig` field (caveat per
   two-way family). Tennis `match` → settlement caveat; set `rule_flag="SETTLEMENT_CHECK_REQUIRED"`,
   downgrade `tradable_now`→`"Yes — rule-dependent"`, append caveat to blockers. `scanner.py:107` carry
   real flag. Rewrite `glossary.py:131`. `spread_certainty_label` auto-flips to "Rule-dependent" for free.
2. **PR B — sport-specific blockers (SMALL).** New `BLOCKERS`: `tennis_void`, `wnba_qualify_vs_compete`
   (WNBA "qualifies ≠ competes" — its `match_stage_to_node` First-Round≡Reach-Semis is the exposed case),
   `title_fractional` (TITLE co-champion/no-contest). Map (sport,node/family)→keys as DATA in SportConfig,
   not `if sport==` branches.
3. **PR C — `mutually_exclusive` + `rules_secondary` first-class (SMALL-MED).** Capture both at
   `data.py:629`. Dutch book: `ME==False` → suppress/demote; `True` → proceed (still caveated);
   absent → infer + note "ME flag absent". Fold `rules_secondary` into `_rule_flag`.
4. **PR D — transitive containment checks (MEDIUM, budget time).** Derive non-adjacent `(deeper,broader)`
   pairs; emit ONLY when an intermediate rung is missing/illiquid (else redundant noise).
   `relationship_type="containment_transitive"`, node-pair `opportunity_id`. Pure transitivity, no new
   settlement assumptions. Closes the audit's real false-negative.
5. **PR E — honest labels + small-edge advisory (SMALL).** Label size/profit "top-of-book; full-depth
   fill not modeled, gross of fees". Optional `config.SMALL_EDGE_WARN_C=2` → non-blocking "≤2¢ gross —
   fees likely erase" (a CAVEAT, not a filter — min-edge filter was deliberately removed in iter 12).

**Rejected:** rename `EXECUTABLE_VIOLATION`→`EXECUTABLE_GROSS_CROSS` (conflates the real ordering fact
with net-exploitability; the caveat layer already carries the uncertainty).
**Deferred:** full payoff-state engine (extend `scenario_payoffs` incrementally instead), n-outcome
dutch books (documented seed), fee modeling + full-depth (scope), inventory/source-agency convergence
(audit admits not riskless).

## Followups (open decisions before coding)
- PR A: how conservative on NBA/WNBA series/games? Lean: series genuinely-clean, `game` gets a mild
  reschedule/no-contest caveat.
- PR C: `mutually_exclusive` absent → keep-and-note (lean) vs suppress.
