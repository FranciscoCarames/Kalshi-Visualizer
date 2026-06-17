---
session: 2026-06-03
milestone: m1.1-per-game-dutch-books
topic: full-tennis-coverage
slug: dutch-book-build
---

# Dutch-book detector — full build session (m1 + m1.1)

## Context

One long session that: re-scoped the project goal, created the `full-tennis-coverage` topic, shipped the
m1 dutch-book detector across 5 PRs, and built + verified the m1.1 per-game extension. This note is the
resume anchor — exact PR/merge state, the one bug found, and the remaining steps.

## PR / merge state (as of session end, 2026-06-03)

| PR | What | State |
|----|------|-------|
| #28 | `dutchbook.py` 2-outcome detector **+ WNBA landed on main** | ✅ merged |
| #29 | Dashboard section + `bucket_of` routing | ✅ merged |
| #30 | Cross-sport (NBA/WNBA) validation + "Dutch book" glossary | ✅ merged |
| #31 | Hardening tests (production NaN/`to_dict` path, 100¢ boundary, one-sided) | ✅ merged |
| #32 | CLAUDE.md m1 doc (dutch-book section) | ✅ merged |
| **#33** | **m1.1 per-game eligibility** (`_is_two_way_row`) + bug fix + breadth tests | 🔲 **OPEN, MERGEABLE/CLEAN — merge next** |

`main` head before #33 merges: includes #28–#32. Branch `feat/per-game-dutch-books` @ `63e21cd`.

## What the detector is

`dutchbook.py` — a check family SEPARATE from the containment ladder (`consistency.py`). Flags an
executable **dutch book** on a 2-outcome MECE event (exactly two distinct-participant markets): cover both
sides for < 100¢. **Underround** = Buy YES both (`yes_ask_A+yes_ask_B<100`); **overround** = Buy NO both
(`no_ask_A+no_ask_B<100`, `100−yes_bid` fallback). ≤1 finding/event (bid≤ask). Status
`EXECUTABLE_DUTCH_BOOK`, routed to actionable/blocked by a single `bucket_of` branch; dedicated dashboard
section (both legs same side → can't reuse the ladder's Buy-YES/Buy-NO table). True arbitrage → no rule
caveat. Sport-agnostic via `match_family`; m1.1 added per-game (`"game"` family).

## The bug found during m1.1 verification

The new per-game eligibility `_is_two_way_row` had `... or kind == "game"`, which **bypassed the
unknown-sport guard** — a `game`-kind row from an unrecognized series would be processed. Latent (only known
sports emit `kind="game"`) but wrong. **Fix:** return `False` for any series resolving to the UNKNOWN sport
*before* checking families. Regression test `test_unknown_series_with_game_kind_is_ignored` added.

## Outcome

- m1 **shipped** (SUMMARY written). m1.1 **code complete & verified** in PR #33: 31 detector tests, full
  suite **159 green**, ruff clean, headless 200. Live (all 3 sports, 407 rows): 26 eligible two-way markets
  (10 match + 16 game), **0 findings** — markets sum to ~101¢ (the vig), confirming the detector reads real
  contracts correctly; no live arb currently exists.
- Key fact: dutch books are rare live because Kalshi books carry a ~1¢ vig (sums sit 1–3¢ over 100). The
  value is being ready to catch them + the near-edge watchlist seed (S7).

## Followups (next session, in order)

1. **Merge PR #33.**
2. **m1.1 task #5** — one-line CLAUDE.md flip: dutch-book section currently says per-game is out-of-scope
   (S5); change to "per-game in scope." Branch off updated `main` (don't stack). Small PR.
3. **`complete-milestone`** for m1.1.
4. Then choose next: **diversify** (NHL/MLB/MMA — draw-free config drops that inherit the per-game detector)
   or **roadmap #2 discovery breadth** (51 missed tennis series). Recommended order from this session:
   per-game first (done) → then diversify. Avoid soccer (draws) until a draw-aware MECE extension.
   Seeds: S5 (done), S6 (n-outcome winner fields), S7 (near-edge dutch-book watchlist).
