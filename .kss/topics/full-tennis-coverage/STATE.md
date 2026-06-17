---
topic: full-tennis-coverage
status: between-milestones
active_milestone: null
last_session: 2026-06-04
last_updated: 2026-06-04
---

# Topic State: full-tennis-coverage

## Current Position

**Last shipped: m5-synthetic-bundle-detector on 2026-06-04** (PRs #42–#47 merged). New
`synthetic_bundle.py` family — a player's MECE exact-score set vs their match-winner hedge, both
directions, format-proven + exhaustive + same-round gated, ALWAYS settlement-caveated (review/blocked,
never Actionable). End-to-end: detection → scanner (N-leg `legs`) → store → FastAPI → both dashboards →
docs. Cross-sport round-parser bugfix landed alongside (#42). See
`milestones/m5-synthetic-bundle-detector/SUMMARY.md`.

Shipped milestones: **m1** (dutch-book detector), **m1.1** (per-game dutch books), **m5**
(synthetic-bundle detector). All on `main`.

Run `plan-milestone` to scope the next.

## Blockers

None.

## Next Action (candidates — pick when resuming)

- **Paused: 5-PR detection-correctness hardening** (the highest-priority queued work) — spec in
  `../real-time-opportunity-engine/note-20260604-detection-correctness-audit.md` (the dutch-book
  "true arbitrage" contradiction fix + transitive containment + `mutually_exclusive` inputs + honest labels).
  **NOW SUPERSEDED/EXPANDED** by a concurrent session into a 55-issue register + phased plan:
  `Concurrent Plans/synthetic-bundle-and-correctness-plan.md` (in-repo) — start at Phase 0 (round parser #25
  for NBA/WNBA still mis-fires; transitive containment #4). Analysis only, not yet implemented.
- Roadmap #2 — robust tennis **discovery** (the ~51 missed series) + sport tagging.
- Roadmap #4 — **deep per-round containment ladder** (`m4-deep-tennis-ladder`).
- **Open seeds (SEEDS.md):** S8 (synthetic-bundle advance hedge — Task 3b deferred), S6 (n-outcome winner
  fields), S7 (near-edge dutch-book watchlist), S1–S5 (discovery/identity/classifier).

Per owner: open a PR after every significant change; owner merges manually ([[pr-after-every-change]]).
All m5 work was done in isolated git worktrees (a 2nd Claude session was editing the shared tree —
serve.py LAN WIP — which was never touched).
