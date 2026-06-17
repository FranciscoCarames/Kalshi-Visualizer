---
milestone: m2-nba-ui-and-validation
topic: sport-generalization
created: 2026-06-03
last_updated: 2026-06-03
status: executing
---

# Milestone Plan: m2 — NBA in the UI + validation

Builds on M1 (engine). Goal: make NBA selectable and usable in the Streamlit app, surface the
non-laddered markets, and validate live. Single-owner (app.py is one file with overlapping regions).

## Goal (one sentence)

Pick a sport in the sidebar and drive the whole dashboard off its `SportConfig` — NBA renders with its
ladder, its non-laddered markets shown in a dedicated unmapped table, and tennis still works exactly as before.

## Success Criteria

- [ ] **Sport selector** (sidebar) drives fetch + title/emoji + division control + families + layers off `cfg`.
- [ ] **Division control** is conditional: tennis shows the "Tour" radio (Women/Men/Both); NBA hides it and skips the tour filter (`cfg.divisions == {}`).
- [ ] Selecting **NBA loads real NBA contracts and the Win Conference ⊇ Win Championship ladder**; selecting Tennis is byte-identical to today.
- [ ] **Unmapped / non-laddered contracts table** (market_family, ladder_node, eligibility, reason, volume) — so per-game/props are visible, not silently dropped.
- [ ] **Ladder-only toggle** (default on) + **market-family filter** for the unmapped view (NBA has ~420 per-game markets).
- [ ] Display-only inconsistencies relabeled **"theoretical"** vs **"executable"** (firm bid/ask + size).
- [ ] `pytest` green; ruff clean; `import app`; headless boot 200 with BOTH tennis and NBA selected; AppTest smoke both sports.
- [ ] **Live-smoke checklist** (below) run by owner.

## Out of Scope (seeds)

- Max-spread / classification-confidence filters (lower value) → SEEDS.
- Conference (East/West) division filter for NBA → SEEDS.
- Per-sport contract-label polish ("Win Championship" wording) → minor follow-up.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | Sport selector + session_state; `set_page_config`/title/emoji from `cfg` | ✓ |
| 2 | `load_contracts`/`discover` sport-parameterized (cfg.default_series / discover_series_for_sport) | ✓ |
| 3 | Conditional division control (Tour → hidden for NBA); family multiselect + layers from `cfg` | ✓ |
| 4 | Unmapped/non-laddered contracts table + show toggle + market-family filter | ✓ |
| 5 | "Theoretical" vs "executable" relabel (STATUS_LABELS + group labels) | ✓ |
| 6 | Tests: NBA AppTest (ladder + unmapped table); test_app mock updated | ✓ |
| 7 | Verify (pytest 118/ruff/headless 200) → PR #24. **Live-smoke = owner-run (pending).** | ◆ |

## Live-smoke checklist (owner-run before close)

1. Launch app; **Sport = Tennis** → dashboard identical to before (FO contracts, payoff scenarios, charts).
2. Switch **Sport = NBA** → title/emoji change; "Tour" control gone; real NBA contracts load.
3. NBA **Win Championship ⊆ Win Conference** rows appear; a known team's chain renders.
4. **Unmapped table** lists per-game/props with reasons; **ladder-only** toggle hides them.
5. Display-only rows read **"theoretical"**; executable rows read **"executable"**.
6. Switch back to **Tennis** → still works (no state bleed).

---
*Planned via plan-milestone on 2026-06-03*
