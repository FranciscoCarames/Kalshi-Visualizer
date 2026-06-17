---
topic: full-tennis-coverage
created: 2026-06-03
---

# Session Log: full-tennis-coverage

Newest sessions at top. One entry per session, terse.

## 2026-06-04 — Concurrent session: 55-issue detection-correctness register + actionable plan (analysis only, NO code)

**Milestone:** —
**Did:**
- On branch `feat/s5-nicegui-dashboard` (predates merged m5), turned the synthetic exact-score bundle idea
  into a **55-issue conceptual/correctness register** (each grounded in code or live Kalshi API 2026-06-04),
  then a phased actionable plan. Saved in-repo: `Concurrent Plans/synthetic-bundle-and-correctness-plan.md`
  (Phases 0–5 + Appendix A = the 55 issues). Mirror: `~/.claude/plans/imperative-zooming-thimble.md`.
- **Overlap flag:** much of the bundle *feature* is ALREADY shipped on `main` as m5 (`synthetic_bundle.py`,
  PRs #42–#47) — this branch lacked it, so the plan re-derives it. Durable value = the **expanded
  detection-correctness register**, which supersedes the paused 5-PR audit brief: adds transitive
  containment (#4), N-of-M / title-fractional / WNBA qualify-vs-compete (#5/#17/#18), exchange-metadata
  capture (#19/#34/#35), normalized ranking + capital (#45/#46), lifecycle churn + metadata versioning
  (#49/#55), plus the synthetic-bundle safety gates.
- Verified LIVE: `extract_round("Quarter-finals")`→`"Finals"` still mis-fires for NBA/WNBA (no QF pattern;
  tennis fixed by #42); exact-score & match-winner are distinct events (same-match cross-event).
- **User instruction: do NOT implement.** Analysis + saved plan only.
**Tasks moved:** —
**Notes:** `Concurrent Plans/synthetic-bundle-and-correctness-plan.md` (in-repo deliverable)

## 2026-06-04 — Started m5 synthetic-bundle detector: Task 1.5 + spike + Task 2

**Milestone:** m5-synthetic-bundle-detector (executing)
**Did:**
- **Planned m5** (synthetic exact-score / state-bundle discrepancy detector — score bundle ≡ player
  wins/advances, hedged vs match-winner/advance; both directions; format-verified + MECE/exhaustive/rule
  gates; conservative gross labels). Full plan: `~/.claude/plans/binary-jumping-fern.md`. The paused 5-PR
  detection-correctness hardening (note in real-time-opportunity-engine topic) follows m5.
- **Task 1.5 — round-parser bugfix, MERGED PR #42 (f258922).** Cross-sport (Tennis/NBA/WNBA): a generic
  `\bfinal(s)\b` ordered before a more-specific hyphenated round swallowed "semi-final"/"quarter-final"/
  "conference semi-finals" → mis-labelled Final/Finals (hyphen = word boundary). Reordered patterns + NBA
  Conference-Semifinals hyphen support. Full battery: 238 pass, ruff, headless Streamlit 200, engine 200
  (/scan 367 opps 0 fail), 31-case edge sweep, live smoke.
- **Task 1 — live-data spike DONE** (`.kss/spikes/exact-score-bundle-feasibility/`): scoreline =
  `custom_strike["Set Score"]` (structured, no regex); format = Grand-Slam + gender (bo5/bo3), independent
  of discovered markets; hedge = match-winner (same-event UUID join, reliable) first, advance = 3b;
  **retirement caveat CONFIRMED required** (exact-score legs → Fair Market Price on retirement while the
  hedge settles).
- **Task 2 — parser + format config, PR #43 open.** `synthetic_bundle.py` (`parse_scoreline`,
  `expected_states`) + `SportConfig.state_bundles`/`score_format_fn` (tennis bo5/bo3; men's Slam=bo5,
  WTA/non-Slam=bo3, unprovable=None). 247 pass, ruff clean, live-verified completeness.
- **Task 3a — detector, PR #44 open.** `find_synthetic_bundles`: match-winner hedge (ticker-agnostic
  player_key join), forward `<100¢` / reverse `<N×100¢`, gates (format / exhaustive-by-UUID / same-round /
  firm-ask), always settlement-caveated (`SETTLEMENT_CHECK_REQUIRED` + `tradable_now="Review rules"`,
  blocked/review never Actionable), N-leg `legs` + action_1/2 backfill, new single-sourced
  `glossary.BLOCKERS["synthetic_settlement"]`. 259 pass, ruff clean; live 4/4 hedges joined, 0 findings.
- **Task 4 — scanner + API plumbing, PR #45 open.** `find_synthetic_bundles` wired into `scanner.py`
  (`_to_unified_synthetic`, `legs`/`n_legs` in `UNIFIED_COLUMNS`); api.py `Opportunity` declares
  `legs`/`n_legs`; `STATUS_GROUP`/`bucket_of` entries (Warning / review-blocked). 262 pass, ruff clean;
  live scanner 116 rows/0 err, API 200. (#42/#43/#44 all merged.)
- **Task 5 — UI surfaces, PR #46 open.** NiceGUI `explanation_lines`/links iterate `legs` (N-leg; 2-leg
  fallback kept); Streamlit dedicated "Synthetic-bundle discrepancies" section (wires
  `find_synthetic_bundles`, full-bundle text, review caveat, `TRADABLE_DISP["Review rules"]`); glossary
  "Synthetic bundle" term + COLUMN_HELP. 263 pass, ruff clean; Streamlit boot 200.
- **Task 6 — docs, PR #47 open.** CLAUDE.md synthetic-bundle section + architecture tree; dutchbook docstring
  points at the built module; GLOSSARY.md regenerated. 263 pass, ruff clean.
**Concurrency:** a second Claude session is editing the shared tree (serve.py LAN WIP). Did Tasks 2/3a/4/5/6 in
isolated **git worktrees** (`-st2`…`-st6`, removed after push) — shared tree never touched. Each PR verified
with the full battery (pytest+ruff+headless+in-process API on a temp DB+live smoke) before the owner merged.
**m5 CLOSED 2026-06-04** — all of 1.5/2/3a/4/5/6 shipped via **PRs #42–#47 (merged)**; 263 tests green.
SUMMARY.md written, MILESTONES.md updated, TOPIC Key Decisions appended (settlement-caveat principle).
**Task 3b (advance hedge) deferred → seed S8.** Topic now **between-milestones**. Highest-priority queued
work: the paused 5-PR detection-correctness hardening (note in real-time-opportunity-engine topic).

## 2026-06-03 — Shipped m1 (dutch-book), built + verified m1.1 (per-game)

**Milestone:** m1-dutch-book-detector (shipped) → m1.1-per-game-dutch-books (in PR)
**Did:**
- Built the **m1 dutch-book / MECE detector** end-to-end across 5 PRs: `dutchbook.py` (2-outcome
  under/overround, exact cents) #28; dashboard section + `bucket_of` routing #29; cross-sport validation +
  "Dutch book" glossary #30; production-NaN-path hardening tests #31; CLAUDE.md doc #32. All merged.
  **`complete-milestone` ran** — m1 SUMMARY written, status shipped.
- Also via #28: **landed WNBA on `main`** (it had been merged into `feat/nba-ladder-depth`, not main).
- Planned + built **m1.1 (per-game)**: generalized eligibility `_is_match_row`→`_is_two_way_row`
  ({match_family, "game"}); per-game `KX*GAME` now in scope. PR #33.
- **Verification pass on #33 found & fixed a real bug:** the `"game"` clause bypassed the unknown-sport
  guard. Fixed; added breadth/integration tests. Suite **159 green**, ruff clean, headless 200, #33
  MERGEABLE/CLEAN. Live (all 3 sports, 407 rows): 26 eligible two-way markets, 0 findings (vig).
**Tasks moved (m1.1):** 1 ✓, 2 ✓, 3 ✓, 4 ✓, 6 ✓; 5 (CLAUDE.md flip) ○ deferred until #33 merges.
**Notes:** `note-20260603-dutch-book-build.md`

## 2026-06-03 — Topic created from a goal re-scope

- Started planning a *deep per-round tennis ladder* (m4) under sport-generalization; owner clarified the real
  goal is **every contract in the tennis category, at any point in time**.
- Live-probed Kalshi: ~80–90 real tennis series, **51 missed** by prefix-only discovery, ~15 unmodeled
  families, category is just "Sports" (noisy — chess/golf/table-tennis/movie false positives).
- Concluded m4 alone meets ~5–10% of the goal. Re-scoped into this topic with a 6-milestone roadmap;
  chose the **MECE/dutch-book detector** as milestone 1. m4 deep-ladder relocated here as a later milestone.
- No code yet — planning only.
