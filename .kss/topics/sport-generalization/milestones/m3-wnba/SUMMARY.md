---
milestone: m3-wnba
topic: sport-generalization
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: m3 — WNBA (third sport)

## What Shipped

WNBA registered as the third sport — a pure `SportConfig` drop in `sports.py`, **zero engine changes**,
tennis + NBA preserved. Confirms the abstraction's whole thesis. Shipped as PR #27 (stacked on #26).

Ladder (verified from live settlement rules — WNBA is a single bracket, conferences defunct):
**Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship** (4 rungs). Identity
`custom_strike.basketball_team` (same as NBA); prefix `KXWNBA` (no collision with NBA's `KXNBA`); advance
"stage" derived from the qualifier series ticker; `KXWNBASERIES` match-alignment; per-game/props/conference
ineligible.

## Success Criteria

- [x] `wnba` SportConfig registered; NBA/WNBA cleanly separated (prefix test).
- [x] Ladder verified against live format (single bracket → reach-stage chain, no conference rung).
- [x] Tennis + NBA tests still green, zero edits; +6 WNBA tests.
- [x] WNBA in the Sport selector; headless boot 200 with 3 sports.
- [x] `pytest` 128 / ruff / headless; **live `verify_sport wnba` shows an active 4-rung ladder**.
- [x] Branch → PR #27.

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| WNBA ladder is reach-stage, NOT conference | Modern WNBA is a single bracket; `KXWNBAEAST/WEST` are defunct/empty; qualifier rules say "qualifies for X" | 4-rung reach-stage ladder; conference markets → ineligible |
| WNBA is its own sport (not a "basketball" division of NBA) | Separate leagues, separate series/seasons | Clean separate `wnba` SportConfig |

## Validation highlight

WNBA is **in-season**, so this was the first live **active** multi-rung ladder: 228 contracts, 168
per-game excluded, 45 comparisons, and **4 real theoretical inconsistencies flagged on live data** (e.g.
NY "Win Championship ≤ Reach Finals").

## Files Touched

- `sports.py` (WNBA block), `tests/test_sports.py` (+6 WNBA tests).

## Sessions

Completed 2026-06-03 (continued session). Discovery: `note-20260603-wnba-discovery.md`.

---
*Closed via complete-milestone on 2026-06-03*
