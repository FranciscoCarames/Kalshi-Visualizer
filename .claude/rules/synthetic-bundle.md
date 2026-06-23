---
paths:
  - "synthetic_bundle.py"
  - "scanner.py"
---

# Synthetic exact-score bundle — `synthetic_bundle.py` (do not regress)

A **separate N-leg family** (no UI/pandas). A player wins iff one of the MECE set scores occurs (bo5
{3-0,3-1,3-2} / bo3 {2-0,2-1}) — that bundle *replicates* "they win", priced against **TWO independent
hedges** (`hedge_kind ∈ {match, advance}`, distinct `opportunity_id`s): the match-winner market, and the
advance/win-tournament node the match implies (`ladder.match_stage_to_node`). Grouped by event + by
**`player_key` UUID** (not the display name).

- **NOT a dutch book / NOT true arbitrage.** A score ≠ the match-winner; on a retirement the score legs
  settle to Fair Market Price while the hedge settles cleanly → EVERY finding carries
  `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, `tradable_now="Review rules"`, routed **review/blocked, NEVER
  Actionable**. Gross / top-of-book; never "riskless"/"locked"/"true arbitrage".
- **Two directions** (exact cents): forward = Buy YES states + Buy NO hedge (`Σ yes_ask(states) + no_ask(hedge) < 100`); reverse = Buy NO states + Buy YES hedge (`Σ no_ask(states) + yes_ask(hedge) < N×100`). Best direction wins.
- **Gates (any fail → silent skip):** (1) **format proven** from `SportConfig.score_format_fn` (men's
  Grand Slam bo5, WTA + non-Slam ATP bo3 — NOT keyed off ATP/WTA alone), never from discovered markets;
  (2) **exhaustive** (found == expected); (3) **hedge present + round aligned** (match: same `stage`;
  advance: hedge node == `match_stage_to_node[score_stage]`); (4) **firm ask per leg** (else
  blocked/review, not dropped). Scoreline from `custom_strike["Set Score"]`, regex-fallback on the subtitle.
- **Two hedge kinds:** the match hedge keeps the 4-part `opportunity_id`; the advance hedge uses a 6-part
  recipe + an extra caveat (`BLOCKERS["synthetic_settlement_advance"]`: a walkover advances without a
  match win). `_advance_hedge_index` is tournament-keyed; the advance close-time gate checks score legs only.
- **Config + engine:** `SportConfig.state_bundles` + `score_format_fn`, both DEFAULTED (empty for
  non-tennis). `scanner.unified_opportunities` → `_to_unified_synthetic`; the N-leg plan lives in a
  `legs` list (`legs`/`n_legs` in `UNIFIED_COLUMNS` + the `api.Opportunity` model); `action_1/2_*`
  backfilled. Routing `STATUS_GROUP["EXECUTABLE_SYNTHETIC_BUNDLE"]="Warning"` + a `bucket_of` branch.
