# PR 29 — "Beyond the strict rule": risk-budget candidates + near-miss books (NiceGUI)

**Date:** 2026-06-05 · **PR #78 MERGED** to origin/main (commit `efbfb19`, merge `2853040`) · NiceGUI-only
follow-on built AFTER the full UNIFIED-PLAN (#48–#77). Branched from a fresh `origin/main` in an isolated
worktree (`kv-p29`, removed after merge).

## What it does
A trader can look *just past* the strict `<100¢` opportunity rule, via TWO opt-in toggles → TWO sections,
kept **economically distinct** (the central correction from two design-audit rounds — see the plan file
`~/.claude/plans/lazy-launching-robin.md`):

- **🟡 Risk-budget candidates** (containment near-miss): cost slightly OVER 100¢ for a **bounded loss +
  convex upside** (broader-but-not-deeper state pays +$1). e.g. cost 102¢ → max loss 2¢, max profit 98¢.
- **🔭 Near-miss books** (dutch over-cost): a 2-/n-way MECE book overpriced by a few ¢ — **FLAT** payout, a
  guaranteed gross loss as a bundle → **watchlist only**, never an edge.

## How it's built (key decisions)
- **New statuses, default-off bands = pure no-op.** `consistency.RISK_BUDGET_CANDIDATE` (joins
  `ACTION_STATUSES`, reuses the Buy-YES-parent/Buy-NO-child plan + `scenario_payoffs`); `dutchbook.NEAR_MISS_DUTCH_BOOK`.
  `build_checks(df, risk_budget_max_loss_c=0)` / `find_dutch_books(rows, near_miss_max_over_c=0)` default 0
  ⇒ Streamlit/api/all existing tests byte-for-byte unchanged.
- **Risk-budget is CONTAINMENT-ONLY** — equivalence/match-alignment excluded (its `scenario_payoffs` has no
  convex upside + a rule-risk state). Audit fix #1.
- **`tradable_now` stays honest** for risk-budget ("Yes" when legs active+sized) — routing is bucket-driven
  (`bucket_of` → `"risk_budget"`), so it never leaks into actionable. Audit fix #2/#7.
- **Payoff plumbing explicit:** `_row` calls `scenario_payoffs` and copies `worst_case_profit_c` /
  `best_case_profit_c` / `roc_pct` / `edge_class` onto the row. Audit fix #3.
- **Strict XOR near-miss per event** (`dutchbook._select_edge` — strict always wins), generalized via
  `payout_floor_c` (2-way + n-way). NOT applied to `_detect_field` (winner-field overround is convex on a
  subset, not flat). Audit fix #5.
- **Store-everything-per-scan:** scanner always computes the full bands
  (`config.RISK_BUDGET_MAX_LOSS_C=25` / `NEAR_MISS_MAX_OVER_C=5`); NiceGUI controls (`webui/viewmodel.py`
  `risk_budget_view`/`near_miss_view`) filter live, no rescan.
- **Exact integer cents** — min upside:risk compared as integer tenths (no float ratio). `roi_pct` doubles
  as worst-case ROC (labelled secondary; Upside:risk is the headline). Audit fix #4/#10.
- **Strict-pipeline isolation:** new buckets never named actionable/blocked → bucket-keyed
  `lifecycle`/alerts/backlog auto-exclude them (test-guarded). Audit fix #6.
- `edge_class` / `worst_case_profit_c` / `best_case_profit_c` added to `scanner.UNIFIED_COLUMNS` AND
  `api.Opportunity`. New bucket set kept in sync: `consistency.DASHBOARD_BUCKETS` == `scanner.BUCKET_PRIORITY`.

## Files
`config.py`, `consistency.py`, `dutchbook.py`, `scanner.py`, `glossary.py` (`BLOCKERS["near_miss_flat"]`),
`webui/viewmodel.py`, `webui/dashboard.py` (two control clusters + two sections), `api.py`,
`tests/test_beyond_strict_rule.py` (14 new tests).

## Verification (pre-merge battery)
455 tests pass (14 new) · ruff clean · headless `serve.py` boot (`/healthz` 200, dashboard renders) ·
**live scan**: 378 risk-budget + 64 near-miss surfaced (incl. a soccer 3-way at floor 200¢/cost 201¢);
convex (worst −2/best 98) & flat (worst==best==−1) fields round-trip through store v3 and the REST API;
strict Actionable unaffected (`edge_class: strict`).

## Follow-ups (not done)
- GDrive Project Brief + Technical Documentation refresh (standing rule after significant changes) — also
  pending for #77; bundle them.
- Streamlit `app.py` deliberately untouched (NiceGUI-only feature, per owner decision).
