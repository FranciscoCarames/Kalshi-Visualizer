---
milestone: m1.1-per-game-dutch-books
topic: full-tennis-coverage
shipped: 2026-06-03
status: shipped-with-gaps
---

# Milestone Summary: m1.1 — Per-game dutch books

## What Shipped

Generalized the dutch-book detector's eligibility from match-family-only to also cover **per-game
2-outcome markets** (NBA/WNBA `KX*GAME`, family `"game"`) via `_is_two_way_row`, reusing the
exactly-2-distinct-participant MECE guard. A verification pass found & fixed a real bug (the `game`
clause bypassed the unknown-sport guard). Landed on `main` inside the integration PR **#35** — which
superseded the original standalone PR #33 — alongside the full dutch-book detector, the NBA 3-rung
ladder, WNBA, and the Stage 0 dashboard-clarity work.

## Success Criteria

- [x] Detector fires on NBA/WNBA per-game events with correct Buy-both action plan / profit /
      tradability — passed.
- [x] Eligibility generalized cleanly (match-family **and** game); exactly-2 MECE guard unchanged —
      passed.
- [x] No regression; tennis fires as before; false-positive guards (No-quote/Crossed/non-eligible/
      unknown-series/3-market) hold — passed (suite green).
- [x] Dashboard section copy → "match **& game** books" — passed.
- [x] Per-game firing tests (NBA + WNBA) + live validation — passed (31 detector tests; live: 26
      eligible two-way markets across 3 sports, 0 findings = vig, no crash, render path confirmed).
- [partial] `pytest`/`ruff`/headless green — passed; **CLAUDE.md per-game scope flip (task #5) NOT
      done** — see Gaps.

## Gaps

- **Task #5 (CLAUDE.md per-game scope note)** — deferred pending a merge that has now happened (#35).
  The dutch-book "out of scope → in scope (per-game)" flip in CLAUDE.md is still pending. Small doc
  follow-up; fold into the doc-reconciliation pass.

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Ship via integration PR **#35**, not standalone #33 | Owner wanted ONE feature-complete branch (NBA-depth + WNBA + dutch-book + per-game + Stage 0) before the next stage | #35 merged to `main`; #33 superseded |
| Eligibility = literal `{cfg.match_family, "game"}` (Open Q1 → option a) | Minimal change; "game" is the consistent NBA/WNBA family; tennis unaffected | Shipped; revisit if a 3rd two-way family appears |

## Deferred

Captured as seeds:

- **CLAUDE.md per-game scope note** — trigger: next doc-reconciliation pass / next time CLAUDE.md is edited.

## Files Touched

- `dutchbook.py` — `_is_two_way_row` (match + game; unknown-sport guard fix)
- `app.py` — dutch-book section copy → "match & game books"
- `tests/test_dutchbook.py`, `tests/test_sports.py` — per-game firing + guard tests (→ 31 detector tests)

## Sessions

Built and verified 2026-06-03. Detail: `note-20260603-dutch-book-build.md`.

---
*Closed via complete-milestone on 2026-06-03*
