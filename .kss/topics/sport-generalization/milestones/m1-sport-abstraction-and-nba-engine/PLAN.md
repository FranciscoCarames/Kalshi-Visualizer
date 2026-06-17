---
milestone: m1-sport-abstraction-and-nba-engine
topic: sport-generalization
created: 2026-06-03
last_updated: 2026-06-03
status: executing
---

# Milestone Plan: m1 — Sport abstraction + NBA engine support

Full design: `~/.claude/plans/rosy-percolating-frost.md`. This milestone is the **engine** (no UI yet).

## Goal (one sentence)

Make the engine sport-agnostic and add NBA support at the data/detection layer — NBA markets parse,
classify, and ladder-check correctly — while preserving tennis behavior exactly (107 tests green).

## Success Criteria

- [ ] `sports.py` exists: `SportConfig` + `LadderSpec` + `IdentityResolver`/`IdentityResult` +
      `MarketClassification` + registry + `sport_for_series(ticker) -> SportConfig | UNKNOWN`.
- [ ] Tennis registered from current constants verbatim; back-compat aliases (`NODE_ORDER`, `CATEGORY`, …)
      reference the tennis config. **All 107 existing tests green, no test edits, no public-signature changes.**
- [ ] `data.py` resolves sport from the ticker internally; identity via `IdentityResolver`; `build_contracts`
      emits `market_family, ladder_node, ladder_eligible, classification_reason` and preserves raw metadata.
- [ ] `consistency.py` resolves `LadderSpec` from `row["series"]`; ladder checks **gated on `ladder_eligible`**;
      ineligible/unsupported markets routed to the unmapped set with a reason.
- [ ] NBA `SportConfig` registered from the live-discovered schema; per-game/props classify **ineligible**.
- [ ] Engine tests: unknown sport ≠ tennis; per-game NBA excluded from ladder; unsupported surfaced with
      reason; low-confidence identity marked low; NBA `build_contracts`/`node_of`/`build_checks` ladder correct.
- [ ] `pytest -q` green; `ruff` clean; `python -c "import app"`; headless boot 200; an NBA script-load shows real contracts.

## Out of Scope (this milestone)

- All UI work (sport selector, unmapped table, new filters, "theoretical" relabel) → **M2**.
- Live-smoke checklist → **M2**.

## Task Breakdown

| # | Task | Stage | Status |
|---|------|-------|--------|
| 1 | Live keyless NBA discovery → structured schema inventory | 0 | ✓ |
| 2 | `sports.py`: dataclasses, registry, `sport_for_series`, tennis registration (verbatim) | A | ✓ |
| 3 | Repoint `data.py` (classify/identity/round/tournament/build_contracts + raw fields) | A | ✓ |
| 4 | Repoint `consistency.py` (ladder from row series; gate on `ladder_eligible`) | A | ✓ |
| 5 | `discover_tennis_series` → `discover_series_for_sport(TENNIS)` wrapper | A | ✓ |
| 6 | **GATE:** 107 green, ruff, import, headless 200 (Stage A done) | A | ✓ |
| 7 | NBA `SportConfig` from discovery (eligible ladder markets; per-game→unsupported) | B | ✓ |
| 8 | `tests/test_sports.py` + NBA fixtures (5 cases + NBA ladder) | B | ✓ |
| 9 | Verify (pytest 117/ruff/headless 200 + live NBA load) → PR #23 | — | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

- NBA team-identity field — resolved by Stage 0 discovery (IdentityResolver candidate-path list + fallback).
- NBA stage taxonomy & which market types exist — resolved by Stage 0.

---
*Planned via plan-milestone on 2026-06-03*
