---
topic: sport-generalization
created: 2026-06-03
---

# Milestone Log: sport-generalization

Newest at top. Append-only summary of shipped milestones.

## m3 — WNBA, third sport (shipped 2026-06-03)

WNBA registered as a pure `SportConfig` drop (zero engine changes); tennis + NBA preserved. 4-rung
reach-stage ladder (single bracket — no conference): Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇
Win Championship. Identity `basketball_team`; no KXWNBA/KXNBA prefix collision. 128 tests (+6), ruff clean,
headless 200; live in-season ladder flagged 4 real inconsistencies. PR #27 (stacked on #26). Also this
session: NBA deepened to 3 rungs (#26).

Archive: `milestones/m3-wnba/`

## m2 — NBA in the UI + validation (shipped 2026-06-03)

NBA selectable in the dashboard, driven by `SportConfig`: sport selector, conditional division control
(Tour hidden for NBA), non-laddered/unmapped table + family filter, "theoretical" vs "executable" relabel.
Tennis unchanged. 121 tests (NBA AppTest + 3 engine edge-cases), ruff clean, headless 200, live smoke both
sports. PR #24 (→ M1 branch) + #25 (→ main).

Archive: `milestones/m2-nba-ui-and-validation/`

## m1 — Sport abstraction + NBA engine (shipped 2026-06-03)

Multi-sport engine via `sports.py` (SportConfig/LadderSpec/IdentityResolver/MarketClassification/registry);
tennis preserved (107 green, zero signature changes); NBA registered from live discovery (identity
`basketball_team`, ladder Win Conference ⊇ Win Championship, per-game excluded). 117 tests, ruff clean,
headless 200, live NBA load validated. PR #23. UI is M2.

Archive: `milestones/m1-sport-abstraction-and-nba-engine/`
