---
milestone: phase-f-followons
topic: unified-plan-build
shipped: 2026-06-05
status: shipped
---

# Milestone Summary: Phase F — follow-on detectors + known-limits docs

## What Shipped

The final phase of `Concurrent Plans/UNIFIED-PLAN.md`, completing the plan's core (Phases A–F). Three
PRs, each branched off a freshly-merged `origin/main`, verified (pytest + ruff + import smoke + headless
boots + live smoke), and opened for owner merge:

- **PR 27a — advancement-hedge synthetic bundle detector** (`#75`, MERGED). The synthetic exact-score
  bundle is now hedged a second way — against the advance / win-tournament market the match *implies*
  (winning a quarterfinal ≡ Reach Semifinal; the Final ≡ Win Tournament) — emitted independently of the
  match-winner hedge, review-only, with its own walkover settlement caveat.
- **PR 27b — tournament-winner FIELD dutch book** (`#76`, MERGED). An overround-only dutch book over a
  mutually-exclusive winner field (≥3 "win the tournament" markets), trading the priceable subset
  (`gap = Σ yes_bid(subset) − 100`). Underround is never emitted (a field is not provably exhaustive).
- **PR 28 — known-limits documentation** (`#77`, open, awaiting owner merge). Single-sourced glossary
  term + README/tech-doc/CLAUDE sections documenting the three execution-realism limits the engine
  deliberately does not model (net-of-fees, position limits/collateral, full-depth execution).

Both detectors were preceded by a **live discovery gate** (raw Kalshi `/events`) that drove the design —
notably the winner field's `mutually_exclusive=True` + non-exhaustiveness, which *forced* overround-only.

## Success Criteria

(No formal PLAN.md existed for this milestone; criteria are the plan's Phase F deliverables.)

- [x] Advancement-hedge detector built, both directions, review-only, distinct opportunity_id — `#75`.
- [x] N-outcome winner-FIELD detector built, overround-only, safe on the priceable subset — `#76`.
- [x] Known-limits (fees / position-limits / full-depth) documented, single-sourced — `#77` (open).
- [x] Each PR: full battery green (441 pytest by PR 28, ruff clean, headless 200, live-smoke verified).
- [x] No regression to the 2-way / soccer-3-way dutch-book paths (byte-identical, regression-tested).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Advance hedge emits independently of the match-winner hedge | Genuinely different priced opportunities; owner chose "emit both" | Distinct 6-part opportunity_id for advance; match keeps the legacy 4-part (lifecycle continuity) |
| Winner field is OVERROUND-ONLY | Live data: fields are `mutually_exclusive=True` but list fewer markets than the draw → not exhaustive → underround unsafe | `prove_field_mece` sets `exhaustive=False`; underround never emitted |
| Trade the priceable SUBSET of a field | Overround is safe on any subset of a ME set; longshots have empty books that would block the whole field | `_field_overround_subset`; floor `(k−1)·100`; event-keyed stable id |
| Advance close-time gate scoped to score legs | An advance market's scheduled close is the later stage's date but it settles on THIS match | Prevents the close-time gate from wrongly suppressing every advance hedge |
| `synthetic_bundle.py` stays pandas-free | Module isolation invariant | Local `_node_of` mirrors `consistency.node_of` instead of importing it |

## Deferred

Captured as seeds (see SEEDS.md):

- Advancement-FIELD detector (n-outcome reach-a-stage 1-of-N) — needs an exhaustiveness proof.
- Field **underround** — needs an exhaustiveness proof we cannot derive from current data.
- K-of-N qualifier fields.
- **PR 11** — soccer tournament-scope missing-layer suppression (owner decision §7 Q9; default = skip).
- **GDrive docs refresh** (standing rule) — Project Brief + Technical Documentation pending across
  27a / 27b / 28; do once the PRs are merged.

## Files Touched

- `synthetic_bundle.py`, `glossary.py`, `scanner.py`, `app.py` — advance hedge (PR 27a).
- `dutchbook.py`, `glossary.py`, `scanner.py`, `app.py`, `webui/viewmodel.py` — winner field (PR 27b).
- `glossary.py`, `README.md`, `docs/TECHNICAL_DOCUMENTATION.md`, `CLAUDE.md` — known-limits (PR 28).
- `tests/test_synthetic_bundle.py`, `tests/test_dutchbook.py` — +26 tests across the three PRs.
- `docs/GLOSSARY.md` regenerated.

## Sessions

Topic LOG.md spans 2026-06-04 (topic creation, m1 foundation, golf, soccer, synthetic stack) through
2026-06-05 (Phase F: PRs 27a / 27b / 28).

---
*Closed via complete-milestone on 2026-06-05*
