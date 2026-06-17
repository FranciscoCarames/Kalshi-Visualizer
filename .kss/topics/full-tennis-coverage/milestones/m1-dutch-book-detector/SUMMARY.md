---
milestone: m1-dutch-book-detector
topic: full-tennis-coverage
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: m1 — Dutch-book / MECE detector

## What Shipped

A new check family — `dutchbook.py` — independent of the containment ladder: it flags an executable
**dutch book** on a 2-outcome head-to-head event (exactly two mutually-exclusive, exhaustive player
markets) when both outcomes can be covered for under the guaranteed 100¢ payout. Both directions
(underround = Buy YES both; overround = Buy NO both), exact integer cents, ≤1 finding/event. Wired into the
dashboard as a dedicated "Dutch-book arbitrage" section, routed via `bucket_of`, with a glossary term. Pure
module; sport-agnostic (validated on tennis + NBA/WNBA series); NaN-safe on the real production data path.

## Success Criteria

- [x] Pure module (no Streamlit/pandas in the logic) — `dutchbook.py`. Passed.
- [x] 2-outcome both directions; EXECUTABLE only with firm quotes + positive sizes; degrades to **blocked**
      (no size / inactive leg). Passed. *Caveat:* a near-edge dutch-book watchlist (Open Q #4) was NOT built
      — deferred as a seed; "blocked" is the only degraded state.
- [x] Exhaustiveness explicit & safe — exactly-2-distinct-participant markets only; never a 2-leg
      YES-underround on a non-MECE/>2-outcome set. Passed.
- [x] No false positives — No-quote / Crossed / single-market / 3-market / non-match / unknown-series all
      guarded by tests. Passed.
- [x] Dashboard surfacing — dedicated section, Buy-YES/Buy-NO action text + per-unit profit, membership-
      filtered, thresholds spared. Passed (its own table, not the ladder's — see Decision D1).
- [x] Sport-agnostic — fires on NBA/WNBA playoff series, ignores per-game/props. Passed (firing via unit
      tests; live confirmed the exclusion half — no series events open to test firing live).
- [x] Tests + pytest green + ruff + headless 200 — 25 detector tests, full suite 153 green, ruff clean,
      headless 200. Passed.

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| D1 — sibling module `dutchbook.py` + one status `EXECUTABLE_DUTCH_BOOK` routed by a single `bucket_of` branch; detection never in consistency.py | Keep containment logic focused; dutch-book is a distinct generic check family | Clean separation; consistency.py only gained routing + a STATUS_GROUP entry |
| Dedicated UI section (not the ladder's Actionable table) | A dutch book is two *same-side* buys; the ladder table's "Buy YES"/"Buy NO" columns would mislabel a leg | Refined D1's "same section"; still routed by bucket_of + spared thresholds like Actionable now |
| It IS true arbitrage (no rule caveat) | Both legs settle on the SAME event together — unlike match-alignment equivalence | Worded as a locked edge; "Dutch book" glossary term added |

(D1 promoted to TOPIC.md Key Decisions.)

## Deferred

Captured as seeds (in SEEDS.md):

- **S5** — extend the detector to per-game 2-outcome markets (`KX*GAME`). Trigger: dutch-book follow-up /
  NBA-WNBA coverage matters. **This is the planned next milestone.**
- **S6** — n-outcome winner-**field** dutch book (needs completeness proof + multi-leg representation).
- **S7** — near-edge dutch-book watchlist (sum within a few cents of 100¢), mirroring the containment
  near-edge bucket. Trigger: when adding watchlist polish to the dutch-book section.

## Files Touched

- `dutchbook.py` — new detector (find_dutch_books, 2-outcome MECE, both directions).
- `tests/test_dutchbook.py` — 25 tests (logic, blocked, false-positive guards, cross-sport, NaN path).
- `consistency.py` — `bucket_of` branch + `STATUS_GROUP` entry for `EXECUTABLE_DUTCH_BOOK` (routing only).
- `app.py` — dedicated "Dutch-book arbitrage" section + membership filtering.
- `glossary.py` + `docs/GLOSSARY.md` — "Dutch book" term, wired to the "Locked edge (¢)" column.
- `CLAUDE.md` — architecture map + do-not-regress section (PR #32, docs).

PRs: #28 (detector + WNBA→main), #29 (dashboard), #30 (cross-sport + glossary), #31 (hardening tests),
#32 (CLAUDE.md — open at close).

## Sessions

1 working session (2026-06-03) logged in topic LOG.md.

---
*Closed via complete-milestone on 2026-06-03*
