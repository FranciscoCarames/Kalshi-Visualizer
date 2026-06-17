---
topic: dashboard-usability
created: 2026-06-03
---

# Session Log: dashboard-usability

Newest sessions at top. One entry per session, terse.

## 2026-06-11 — Bounded-loss trader likelihood/comparability metrics, Phase 1 (current branch)
**Milestone:** —
**Did:** Shipped **Phase 1** of trader likelihood/comparability metrics on
`feat/bounded-loss-likelihood-metrics` (`36c4ca2`, **off `feat/ui-trust-fixes` 197bf07** — the
owner-preferred tip, NOT the parked ui-table-clarity). Committed, **NOT pushed/merged** (owner tests
in-branch). All **display-only, fail-closed**, never touch `bucket_of`/`_rank_key`/peer-cheapness.
- New Bounded-Loss columns: **"Chance if reached %"** (conditional P(success|reached)=spread÷parent,
  vig-aware), **"Firm success gap ¢"** (conservative parent-bid − child-ask; a ¢ gap not a tradable %),
  **Midpoint-only / Wide-basis badges** (the audit #1 phantom-positive fix), **"Cost per implied pp"**.
- Firm-quote passthrough `parent_yes_bid_c`/`child_yes_ask_c`: `consistency._row` → `build_checks` →
  `scanner` UNIFIED_COLUMNS/`_to_unified_consistency` → `api.Opportunity` (REST parity); round-trips in the
  store JSON blob → **no migration**. New pure **`probability.py`** (`devig_proportional`/`devig_field` —
  Phase 2a MATH ONLY, no UI yet).
- Owner directives (AskUserQuestion): **phased**; **experimental** (do NOT touch the CLAUDE.md scope guard
  — de-vig stays out-of-scope on paper, this is display-only); open to reorganizing the table around a
  win/loss/likelihood trio **but only via a previewable mockup** (not done).
- **922 pytest** (new `test_probability.py` + extended `test_speculative_isolation.py`), ruff clean,
  `serve.py` boot green, 0 console errors, live Midpoint-only badge renders. Resolves
  `bounded-loss-ev-discussion` #1/#2 + `bounded-loss-implied-audit` #1/#2. **Phase 2** (field-implied
  de-vig: scanner pre-pass `build_fair_prob_table` + `SportConfig.survivors_for_node` + `FieldStatus`
  gating) = SEPARATE later branch, gated on a field-completeness audit.
**Tasks moved:** —
**Notes:** memory `bounded-loss-likelihood-metrics.md`, `bounded-loss-ev-discussion.md`; plan
`~/.claude/plans/make-me-a-plan-imperative-eich.md`

## 2026-06-10 — Bounded-loss EV discussion (OPEN) + table-clarity branch REJECTED
**Milestone:** —
**Did:** Owner asked why bounded-loss EV maxes at 0 / why negatives are hidden. Answered live-verified
(294 rb rows): **EV ≤ 0 by construction** (a market-positive firm edge would be Actionable, not a
>100¢-cost near-miss); 58 EV=0 rows ALL Tight; the lone +18¢ (Bryson, Wide book) is a **mid-vs-ask
quote artifact**, not a free lunch (cost uses asks, chance uses mids — the audit's #1 basis mismatch).
Proposed **6 improvements** (interpretation copy → dual-basis EV → trader-probability input → EV
tie-breaks → soft de-emphasis → time-to-resolution); offer pending = start #1+#2 + preview #4/#5 — owner
had NOT chosen (now superseded by the 06-11 Phase 1 metrics work).
- **`feat/ui-table-clarity` (ad6e024) PARKED** — owner viewed the 8-change clarity pass live and prefers
  the ORIGINAL. **Merge tip stays `feat/ui-trust-fixes` (197bf07).** Branch preserved/pushed, not for merge.
  Standing rule reinforced: preview default-view changes with owner BEFORE branching.
**Tasks moved:** —
**Notes:** memory `bounded-loss-ev-discussion.md`, `bounded-loss-clarity-rejected.md`

## 2026-06-09 — Bounded-loss comparability suite (A–D) + Phase 1/2 + speculative roadmap approved
**Milestone:** —
**Did:** Made the **Bounded-Loss Bets** section the primary cross-sport comparison surface.
- **Suite A→C→B→D** (plan `~/.claude/plans/bounded-loss-comparability-suite.md`): **A** promote+default-open
  (#143 merged), **C** Implied-chance + Implied-EV col + rank mode (#144 merged), **B** Vertical-vs-Calendar
  split via `LadderSpec.simultaneous`+derived `resolution_mode` (#145 merged), **D** golf make-cut implied
  FLOOR via `SportConfig.derived_indicators_fn` (#146, merged later). Suite v1 complete.
- **Implied audit** (13 issues, analysis-only): top two = basis mismatch (chance from mids, cost from asks)
  + negative chance shown as a probability. Feeds the extensions plan.
- **Extensions** `~/.claude/plans/sorted-rolling-zephyr.md`: **Phase 1** (`feat/bounded-loss-phase1`) PR R
  rerender-debounce lag fix + PR M implied metric decomposed (Market gap / Breakeven / Gap-vs-breakeven +
  signal class). **Phase 2** (`feat/bounded-loss-phase2`, tip `9d7b977`) B+E+F+G: glossary basis +
  isolation-test template, combined "All" table + trader cols + $100 sizing, peer-cheapness badge,
  generalized `derived_indicators`. 863 tests, NOT merged.
- **Scope expanded** (owner): approved the **Speculative Decision-Support Layer** roadmap
  (`~/.claude/plans/turn-this-into-a-drifting-anchor.md`) — 3 product zones; **hard invariant** = every
  prob/EV/de-vig metric is display + opt-in sort ONLY, never feeds classify/bucket/rank (isolation test per
  PR). PR 0 = scope-guard rewrite in AGENTS.md+CLAUDE.md is a hard predecessor. Planning-only.
- **Workflow changed → branch-only delivery** (main frozen, full scope in branch(es), owner merges; NO
  per-step PRs).
**Tasks moved:** —
**Notes:** memory `bounded-loss-comparability-suite.md`, `bounded-loss-implied-audit.md`,
`speculative-decision-support-roadmap.md`, `pr-after-every-change.md`

## 2026-06-07 — Probability-context ranking + filters for risk-budget candidates (PR #107 OPEN)
**Milestone:** —
**Did:** Extended the PR #100 ranking modes (this topic) with a probability-context view for risk-budget
containment near-misses, so meaningful-probability outrights surface ahead of tiny longshots. Plan
`~/.claude/plans/frolicking-prancing-spring.md`. Branched off main (docs branch already merged), committed,
pushed, opened **PR #107** (`feat/risk-budget-spread-outright-ranking`), awaiting owner merge.
- **Key insight (decided with owner):** `spread ÷ outright` is **scale-invariant** (3/2 and 30/20 both =
  0.50), so no ratio of spread+outright can separate them. New rank mode **"Outright + spread"** is
  therefore **probability-LED**: deeper (child) `display_c` outright magnitude DESC first, ratio second.
  The **min-child-outright** filter (not max-ratio) is what actually removes longshots.
- Metric uses the **display outright** (`display_c`, NOT executable action prices — caught in owner audit).
  5 fields plumbed `consistency._row` → `scanner.UNIFIED_COLUMNS`/`_to_unified_consistency` →
  `api.Opportunity` (`extra="ignore"` would drop them). Two opt-in filters on `vm.risk_budget_view`
  (`min_outright_c`, `max_spread_ratio_hundredths`, both 0=off) + config defaults. Older snapshots missing
  fields sort last, hidden only when a filter is active. Existing Max loss / Upside:risk + default mode
  unchanged.
- **Verified:** 599 pytest (+8 new incl. 30/20-before-3/2 + min-outright filter), ruff clean, API/unified
  round-trips confirmed. Memory: `risk-budget-spread-outright-pr107.md`.
**Tasks moved:** —
**Notes:** —

## 2026-06-05 — 15-feature dashboard batch + Streamlit retirement + near-real-time perf (ALL MERGED)
Designed + built the owner's 15-feature request as 15 PRs off `main`, isolated worktrees, ALL MERGED to
`origin/main` `c2f2d4b`. Plan `~/.claude/plans/peppy-bubbling-neumann.md` (~8 review rounds before build).
- **PR0 #89** retire Streamlit (`app.py`/`test_app.py` deleted, dep dropped, NiceGUI is sole UI; docs banner +
  GDrive-sync deferred for TECHNICAL_DOC/ROADMAP prose).
- **Perf:** P1 #90 `store.latest_snapshot_id()` + engine latest-snapshot cache; P2 #91 split
  `refresh()`→`reload_data`/`rerender`/`poll` (1s poll, snapshot-id guard, in-memory filters,
  `UI_POLL_SECONDS=1`); P3 #92 `AUTO_SCAN_DEFAULT_SECONDS` 30→10; P4 #93 presence-gated auto-scan
  (`Scheduler.start(gate=…)`, `AUTO_SCAN_PAUSE_WHEN_IDLE`).
- **Features:** PR1 #94 selected-row highlight; PR2 #95 risk section after Actionable; PR3 #96 `.env`/rate
  doc note (#8 keys-don't-help); PR4 #97 resolution-criteria toggle (`engine.contract_by_ticker`); PR5 #98
  accessibility (ARIA/focus/larger-text); PR6 #99 participant multi-select (`participant_keys/labels`,
  per-leg keys, key URL state); PR7 #100 ranking modes from **payoff geometry, no prob/EV** (`vm.rank_opps`);
  PR8 #101 change-color (`vm.classify_changes` + colored slot); PR9 #102 liquidity (`vm.liquidity_leader`);
  PR10 #103 volatility (`store.contract_frames_since` + `vm.volatility_leader`).
- Verified per PR: pytest (532→**557**) + ruff + compileall + serve.py boot (`/healthz`/`/readyz`/`/metrics`/`/`).
- **NEXT:** manual browser checks (both themes — headless can't drive row-select/cell render) + GDrive doc
  sync (now behind Streamlit retirement + all new surfaces; finish TECHNICAL_DOC prose, drop the banner).
