---
topic: full-tennis-coverage
created: 2026-06-03
---

# Milestone Log: full-tennis-coverage

Newest at top. Append-only summary of shipped milestones.

## m5 — Synthetic exact-score / state-bundle detector (shipped 2026-06-04)

New `synthetic_bundle.py` check family: a player's MECE exact-set-score set (bo5 {3-0,3-1,3-2} / bo3
{2-0,2-1}) replicates "they win", priced vs their match-winner hedge → a gross pricing discrepancy in two
directions (`<100¢` / `<N×100¢`, exact cents). Format-proven + exhaustive + same-round gated; ALWAYS
settlement-caveated (review/blocked, never Actionable — the retirement hole is real). Shipped end-to-end:
detection → scanner (N-leg `legs` plumbing) → store → FastAPI → both dashboards → docs. Round-parser
cross-sport bugfix landed alongside (PR #42). 263 tests green. PRs **#42–#47**. Deferred: advance hedge (S8).

Archive: `milestones/m5-synthetic-bundle-detector/`

## m1.1 — Per-game dutch books (shipped-with-gaps 2026-06-03)

Generalized the dutch-book detector to per-game 2-outcome markets (NBA/WNBA `KX*GAME`, family `"game"`)
via `_is_two_way_row`, reusing the exactly-2 MECE guard; a verification pass fixed an unknown-sport-guard
bug. 31 detector tests. Landed on `main` via integration PR **#35** (superseded #33). Gap: CLAUDE.md
per-game scope note (task #5) still pending — folded into the doc-reconciliation pass.

Archive: `milestones/m1.1-per-game-dutch-books/`

## m1 — Dutch-book / MECE detector (shipped 2026-06-03)

New `dutchbook.py` check family (separate from the containment ladder): flags an executable dutch book on a
2-outcome head-to-head when both outcomes can be covered for < 100¢ — underround (Buy YES both) / overround
(Buy NO both), exact cents, ≤1/event. Dedicated dashboard section routed via `bucket_of`; sport-agnostic
(tennis + NBA/WNBA series); NaN-safe. 25 detector tests, suite 153 green. PRs #28–#32. Deferred: per-game
(S5, next), winner fields (S6), near-edge watchlist (S7).

Archive: `milestones/m1-dutch-book-detector/`
