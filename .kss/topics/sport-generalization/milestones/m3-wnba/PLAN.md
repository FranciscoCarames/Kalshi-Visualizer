---
milestone: m3-wnba
topic: sport-generalization
created: 2026-06-03
last_updated: 2026-06-03
status: shipped
---

# Milestone Plan: m3 — Add WNBA (third sport)

Proves "adding a sport = a `SportConfig` drop." WNBA is structurally close to NBA (same
`basketball_team` identity, same family pattern) and **in-season/live now** → real active-ladder
validation. Discovery facts: `note-20260603-wnba-discovery.md`. **Prereq: merge PR #25 first**, then work
on a fresh branch off `main` (do NOT stack a 4th deep).

## Goal (one sentence)

Register a `wnba` `SportConfig` so WNBA is selectable and ladders correctly, with **no engine changes** and
tennis + NBA fully preserved.

## Success Criteria

- [ ] `wnba` SportConfig registered (prefix `KXWNBA`, identity `basketball_team`, families + ladder).
- [ ] `sport_for_series` cleanly separates NBA vs WNBA (no prefix collision).
- [ ] WNBA ladder maps correctly per the **verified** format (likely **Reach Finals ⊇ Win Championship**, NOT
      conference — see open question); per-game/props ineligible.
- [ ] Tennis (107) + NBA (13) tests still green, zero edits to either; **new WNBA tests** mirror them.
- [ ] App: WNBA appears in the Sport selector and renders (AppTest); unmapped table shows per-game.
- [ ] `pytest`/ruff/headless 200; live `verify_sport.py wnba` shows a real **active** ladder.
- [ ] Branch off main → PR.

## Out of Scope

- Reworking the engine (none needed). Real-time/backend (parked). Conference-division UI filter (seed).

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | **Verify WNBA playoff format** — single bracket confirmed (KXWNBAEAST/WEST empty); ladder = reach-stage chain | ✓ |
| 2 | Register `wnba` SportConfig in `sports.py` (basketball_team identity; 4-rung reach-stage ladder) | ✓ |
| 3 | `tests/test_sports.py`: WNBA classification, ladder, per-game ineligible, identity, sport separation (+6) | ✓ |
| 4 | App: WNBA in selector; headless 200 with 3 sports | ✓ |
| 5 | Verify (pytest 128/ruff/headless) + live `verify_sport.py wnba` (active ladder, 4 inconsistencies) → PR #27 | ✓ |

## Open Questions

- **WNBA ladder structure** (the one real unknown): single-bracket vs conference. Resolve in task 1 by
  reading `KXWNBAEAST/WEST` + `KXWNBAFINAL` rules_primary / settlement. Default to Reach Finals ⊇ Win
  Championship if conferences don't gate the title.
- Whether to add broader layers (Reach Semifinals `KXWNBASEMIFINAL`, Reach Playoffs `KXWNBAPLAYOFF`).

## Precedent: NBA now has a 3-rung ladder (PR #26)

NBA was deepened to **Reach Playoffs ⊇ Win Conference ⊇ Win Championship** via the same mechanism we'll
reuse for WNBA: multiple advance series mapped to distinct rungs by deriving the advance "stage" from the
series ticker (`advance_stage_to_node`). WNBA has richer reach-stage series than NBA (`KXWNBAPLAYOFF`,
`KXWNBASEMIFINAL`, `KXWNBAFINAL`), so once the format is verified the WNBA ladder can be:
**Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship** (4 rungs) — copy the NBA pattern.

---
*Planned via plan-milestone on 2026-06-03*
