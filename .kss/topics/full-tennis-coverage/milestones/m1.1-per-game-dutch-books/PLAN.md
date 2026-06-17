---
milestone: m1.1-per-game-dutch-books
topic: full-tennis-coverage
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: m1.1 — Per-game dutch books

> Extends the shipped **m1** dutch-book detector (seed S5). Versioned `m1.1` (a point release on m1, not a
> new roadmap position) so it doesn't collide with roadmap #2 (discovery).

## Goal (one sentence)

Extend the dutch-book detector's eligibility from match-family-only to also cover **per-game 2-outcome
markets** (NBA/WNBA `KX*GAME`, family `"game"`), where the live tradable liquidity actually is — a tiny,
sport-agnostic change that reuses the existing exactly-2-markets MECE guard.

## Why

m1 finds ~nothing live because head-to-head *series* are rare (NBA/WNBA returned 0). But per-game markets
are abundant and in-season (June: NBA Finals, WNBA regular season), 2-outcome and draw-free → exactly the
MECE shape the detector already handles. One eligibility tweak lights up the sport where edges live.

## Success Criteria

- [ ] The detector fires on NBA/WNBA per-game events (`KXNBAGAME`/`KXWNBAGAME`, kind `"game"`) when the two
      team books cross (under/overround), with the correct Buy-both action plan, profit, and tradability.
- [ ] Eligibility is generalized cleanly (match-family **and** game), not a per-sport hack; the
      **exactly-2-distinct-participant** MECE guard is unchanged and still rejects single/>2-outcome/field events.
- [ ] **No regression:** tennis matches still fire exactly as before; the m1 test suite stays green; the
      false-positive guards (No-quote/Crossed/non-eligible-family/unknown-series/3-market) still hold.
- [ ] Dashboard section copy updated to "match **& game** books" (the existing section now also shows game
      books); membership filtering + thresholds-spared behavior unchanged.
- [ ] New per-game firing tests (NBA + WNBA) + a **live NBA/WNBA validation** (games are in season) showing
      the detector reads real game contracts and produces sane output.
- [ ] `pytest -q` green, `ruff` clean, headless boot 200. CLAUDE.md dutch-book section updated (per-game now
      in scope; S5 done).

## Out of Scope

- Discovery breadth, deep ladder, n-outcome winner **fields** (S6), near-edge watchlist (S7).
- **Draw-prone sports** (soccer): a "game" there is 3-outcome — naturally excluded by the exactly-2 guard,
  and we do not add draw handling here.
- Reclassifying tennis `KXATPGAME`/`KXWTAGAME` (currently family `"other"`) — out of scope; note as a
  possible follow-up if those turn out to be real 2-outcome tennis match-winners we're missing.
- Per-game settlement nuance (postponement/OT) — a game still resolves to exactly one winner; no rule caveat.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | ✅ `dutchbook.py`: `_is_match_row`→`_is_two_way_row` (kind in {match_family, "game"}); module docstring updated | ✓ |
| 2 | ✅ Tests: NBA + WNBA per-game firing; props ignored; 3-outcome draw game rejected by exactly-2 guard; tennis unchanged (25→27) | ✓ |
| 3 | ✅ `app.py`: section copy → "match & game books" | ✓ |
| 4 | ✅ Live validation: detector now evaluates 4 NBA + 4 WNBA two-way game events (was 0); 0 findings (books sum 100–103¢ = vig) — reads real per-game contracts correctly | ✓ |
| 5 | `CLAUDE.md` per-game note — **DEFERRED**: the dutch-book section is in unmerged PR #32; flip "out of scope" → "in scope" once #32 lands (don't stack) | ○ |
| 6 | ✅ Verify (suite 155 green, ruff clean) → **PR #33** off `main` | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

1. **How to express "two-way eligible families" without coupling to literal strings?** Options: (a) literal
   set `{cfg.match_family, "game"}` in `dutchbook.py` (minimal; "game" is the consistent NBA/WNBA family,
   tennis has none so it's unaffected); (b) add a `SportConfig.two_way_families` field (cleaner, but touches
   sports.py for all sports). Lean **(a)** for a small change; revisit if a third family appears.
2. **Could a non-MECE 2-market event sneak in?** The exactly-2-distinct-participant guard + family gate
   (match/game only) should prevent it. Confirm no 2-market `game`/`match` event on Kalshi is non-exhaustive.

## Build progress

- **2026-06-03 — code done, PR #33** (`feat/per-game-dutch-books → main`). One-line eligibility
  generalization (`_is_two_way_row`); exactly-2 guard unchanged (rejects 3-outcome draw games). Tasks
  #1–#4, #6 ✓. **#5 (CLAUDE.md) deferred** until PR #32 merges.
- **2026-06-03 — verification pass (owner asked for wide testing before merge).** Added breadth +
  integration tests; **found & fixed a real gap**: the `kind == "game"` clause bypassed the unknown-sport
  guard (a game-kind row from an unrecognized series was processed). Fixed `_is_two_way_row` to exclude
  UNKNOWN-sport series first. Detector tests 27→**31**; suite **159 green**, ruff clean, headless 200. Live
  (all 3 sports, 407 rows): 26 eligible two-way markets (10 match + 16 game), 0 findings (vig), no crash;
  render path confirmed for a firing game finding. Pushed to #33 + PR comment.

## Notes

- Grounding: live probe (2026-06-03) showed NBA `KXNBAGAME` = 8 rows (4 games × 2 teams), WNBA likewise —
  exactly-2-markets per event, kind `"game"`, currently excluded by m1's `match_family` gate.
- The app already loads game rows into `df` and feeds `df.to_dict("records")` to the detector, so only the
  eligibility predicate changes; the NaN-safe production path (m1 hardening) covers game rows too.

---
*Planned via plan-milestone on 2026-06-03*
