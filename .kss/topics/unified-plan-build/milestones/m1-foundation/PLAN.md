---
milestone: m1-foundation
topic: unified-plan-build
created: 2026-06-04
last_updated: 2026-06-04
status: planned
---

# Milestone Plan: m1 — Foundation (collision core)

## Goal (one sentence)

Land the shared "collision core" that golf, soccer, and NiceGUI all independently depend on — done once,
off `origin/main` #47 — so the downstream sport/detector/UI PRs never conflict on it.

## Success Criteria

What must be true to call this shipped (each PR merged to `main`, one PR per item, never stacked):

- [ ] **PR 1** — scanner leg↔URL fix: `scanner.py:93` `_to_unified_consistency` uses `url = parent_url or
      child_url`, `url_2 = child_url or parent_url`; regression test asserts leg↔ticker↔url alignment for
      **both** consistency and dutch-book row shapes.
- [ ] **PR 2** — `exact_series: frozenset[str] = frozenset()` is the LAST `SportConfig` field; `sport_for_series`
      resolves **exact-first across all sports** (two-pass); `discover_series_for_sport` includes
      `exact_series` and **short-circuits** (no pagination) when prefixes+winners are empty. Tests: exact
      precedence wins regardless of registry order; no false prefix match; discovery includes exact + short-circuits.
- [ ] **PR 3** — `consistency._row` category dispatch is per-sport via `_sport_for_row(...).category_labels.get(kind, "Other")`
      (no more tennis-only `data.CATEGORY`). Test: NBA `kind="game"` → correct category, never a tennis label or blank.
- [ ] Full suite stays green (**≥263 tests**) + `ruff check .` clean after each PR; `python -m streamlit run
      app.py --headless` → `/_stcore/health`=200 and `python serve.py` → `/healthz` ok.
- [ ] No regression to tennis/NBA/WNBA detection or to legacy 2-leg dutch-book IDs.

## Out of Scope

- Any sport registration (golf/soccer) — those are Phase C, and depend on this milestone.
- The n-outcome detector / leg-schema changes (Phase D) and NiceGUI parity (Phase E).
- The independent defects PR 4/5/6 (Phase B) — separately tracked; parallelizable after this lands.
- PR 0 is the baseline **sync** (already done during setup: local `main` FF'd to `origin/main` #47, impl
  worktree created); it requires no code.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 0 | PR 0 — baseline sync to `origin/main` #47 + impl worktree (DONE in setup) | ✓ |
| 1 | PR 1 — scanner leg/URL fix + leg↔ticker↔url regression tests | ○ |
| 2 | PR 2 — `exact_series` field + exact-first `sport_for_series` + discovery update/short-circuit | ○ |
| 3 | PR 3 — per-sport category dispatch in `consistency._row` | ○ |

Status legend: ○ pending · ◆ in-progress · ✓ done

Per-PR loop: branch off `origin/main` in the worktree → re-verify the PR's anchors on #47 (S3) → implement
→ `pytest -q` + `ruff` + headless boot → open PR → owner merges → next. Use a verification workflow per PR
(adversarial + the false-positive/negative actionability checks) per the "verify each stage" rule.

## Open Questions

(resolve as you go; promote stable answers to TOPIC.md "Key Decisions" at milestone close)

- PR 2: confirm golf's two-pass `sport_for_series` shape is exactly what soccer needs too (it is, per the
  plan) — verify when wiring PR 2 so soccer's later registration is a pure data add.
- None blocking; the §7 owner questions (Q1/Q2/Q3/Q9) gate Phase C/D/E, not this milestone.

## Notes

(deep-dive session writeups go to sibling `note-YYYYMMDD-*.md` files, not here)

Detailed acceptance criteria + file:line anchors live in `Concurrent Plans/UNIFIED-PLAN.md` §2A (F1/F4/F5),
§2B (C1/C2), §4 (foundation table), and §5 Phase A. This milestone tracks execution, not re-spec.

---
*Planned via plan-milestone on 2026-06-04*
