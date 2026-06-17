---
milestone: m2-nba-ui-and-validation
topic: sport-generalization
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: m2 — NBA in the UI + validation

## What Shipped

NBA is selectable and usable in the dashboard, driven entirely by the selected sport's `SportConfig`.
Tennis is unchanged. Sport selector, conditional division control (Tour hidden for NBA), non-laddered /
unmapped contracts table + market-family filter, and a "theoretical" vs "executable" relabel. Shipped as
PR #24 (→ M1 branch) then PR #25 (→ main, since #24 merged into the M1 branch).

## Success Criteria

- [x] Sport selector drives fetch + title/emoji + division control + families + layers off `cfg`.
- [x] Conditional division control — tennis shows Tour (Women/Men/Both); NBA hides it (`divisions == {}`).
- [x] NBA loads real contracts + the Win Conference ⊇ Win Championship ladder; tennis identical.
- [x] Non-laddered / unmapped contracts table (per-game/props with reasons).
- [x] Show-non-laddered toggle + market-family filter (sport-scoped widget keys avoid stale state).
- [x] "Theoretical" (display) vs "executable" (firm + size) relabel.
- [x] `pytest` 121 green; ruff clean; `import app`; headless boot 200; AppTest both sports.
- [x] Live-smoke — validated via AppTest (both sports) + live `verify_sport.py` (tennis 353 / NBA 504
      contracts through the engine). *(Programmatic + live-data equivalent of the browser checklist; a
      visual glance in the browser is optional confirmation.)*

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Sport-scoped widget keys (`families_{sport}`, etc.) | Switching sports changes a widget's options; a shared key throws "default not in options" | Each sport keeps independent control state |
| "Theoretical" vs "Executable" wording | Display-price findings aren't actionable; firm+sized ones are | DISPLAY_VIOLATION → "Theoretical inconsistency"; EXECUTABLE → "Executable edge" |
| M2 single-owner (no Workflow) | app.py is one file with overlapping edit regions → parallel agents would conflict | Done sequentially; reserved Workflows for genuinely independent work |

## Deferred (seeds)

- Max-spread / classification-confidence filters.
- NBA East/West conference division filter (would mirror tennis ATP/WTA divisions).

## Files Touched

- `app.py` (sport selector, sport-aware controls, unmapped table, relabel), `tests/test_app.py` (NBA AppTest),
  `tests/test_sports.py` (3 added engine edge-cases).

## Sessions

Completed 2026-06-03 (single session, continued from M1).

---
*Closed via complete-milestone on 2026-06-03*
