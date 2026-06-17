---
milestone: s3-lifecycle
topic: real-time-opportunity-engine
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: s3 — Lifecycle: alerts + recently-actionable (engine)

> Stage 3 of the 6-stage roadmap. Full design + verification: the approved plan
> `~/.claude/plans/immutable-gathering-valiant.md`. Builds on s2 (PR #38): the engine now writes a
> cross-sport opportunity snapshot to SQLite each scan; this stage DIFFS those snapshots over time.

## Goal (one sentence)

Add `lifecycle.py` — pure snapshot-diff functions (new-actionable §8, blocked-change "what changed" §9,
recently-actionable backlog §10) derived entirely from the snapshot history Stage 2 already persists —
so a trader sees what's newly actionable, what changed while blocked, and what was actionable recently.

## Success Criteria

- [ ] `lifecycle.py` (pure; no Streamlit/network/store import — snapshots passed in): `new_actionable`,
      `persisting_new_actionable`, `blocked_change`, `recently_actionable`, `first_seen` — unit-tested on
      crafted prev→cur / history fixtures.
- [ ] Banner persistence is correct: `persisting_new_actionable` uses **full retained history** (not a
      window slice) for first-actionable, so a row actionable LONGER than the window is not falsely "new";
      a still-actionable recent row persists for the window. `new_actionable` suppresses with no prev.
- [ ] `blocked_change` classifies the §9 dimensions (blocker / price / liquidity / status /
      `market_status` active→inactive / tradable_now / `rule_flag_changed`); no change → not emitted.
- [ ] `recently_actionable` returns §10 fields with numeric `became_ts`/`left_ts`, `duration_s`, and a
      correct `reason_left` (disappeared → leg inactive → went blocked → went clean).
- [ ] Snapshot rows carry the fields the diff needs: `scanner.UNIFIED_COLUMNS` gains `rule_flag` +
      normalized `market_status` (+ a `market_status` field on dutch-book findings) — additive, NO DB migration.
- [ ] Interim Streamlit (cross-sport section, toggle-gated): persistent new-actionable banner +
      recently-actionable table + minimal blocked-change table; safe `latest_two()` normalization.
- [ ] Suite green (`test_lifecycle.py` + scanner/dutchbook/glossary extensions) + ruff + headless 200;
      app-level AppTest (run twice → real prev/cur) renders all three surfaces; live smoke on 2 snapshots.

## Out of Scope

- No new store schema / migration (derive from history); "until acknowledged" persistence → Stage 5 ack.
- No NiceGUI / FastAPI (Stages 4–5); the interim tables are throwaway Streamlit.
- Snapshot-level `stale` per row; graded relationship confidence (only the binary `rule_flag_changed`).
- No net-of-fees, no notifications outside the page.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `scanner.py` + `dutchbook.py`: add `rule_flag` + normalized `market_status` to the unified row (additive) | ✓ |
| 2 | `lifecycle.py`: `new_actionable` + `first_seen(actionable_only)` + `persisting_new_actionable` (full-history, window filter) | ✓ |
| 3 | `lifecycle.py`: `blocked_change` (§9 dimension diff) | ✓ |
| 4 | `lifecycle.py`: `recently_actionable` (§10 fields + `reason_left` precedence) | ✓ |
| 5 | `config.py`: `BACKLOG_WINDOWS`/`BACKLOG_DEFAULT` + `ALERT_PERSISTENCE_OPTIONS`; `glossary.py`: 3 terms | ✓ |
| 6 | `app.py`: persistent banner + "New" flag + recently-actionable table + minimal blocked-change table (safe `latest_two`) | ✓ |
| 7 | Tests: `test_lifecycle.py` (+ scanner/dutchbook ext); 203 pass + ruff clean | ✓ |
| 8 | Verify: AppTest (cross-sport + lifecycle UI renders), headless `python -m streamlit` 200, live prev/cur smoke → **PR #39** | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

**SHIPPED 2026-06-03 via PR #39** (awaiting owner merge). 203 tests, ruff clean, headless 200; AppTest
renders the lifecycle UI; live smoke diffed two real snapshots (`blocked_change` caught an
actionable→blocked flip with `market_status`+`tradable_now`; `recently_actionable` → `leg inactive`).
Open questions resolved: `reason_left` precedence (disappeared→leg inactive→blocked→clean); full-history
persistence avoids the windowed-slice false-"new"; no store migration (derive from history).

## Open Questions

- `reason_left` precedence: disappeared → leg inactive (`market_status`) → went blocked → went clean — confirm on live transitions.
- "This session" window = app/process start time (app passes `now_ts`/session-start); confirm interim is acceptable.
- Snapshot-history dependency: lifecycle only has data when the cross-sport scanner runs (it writes the snapshots) — noted.

## Notes

(deep-dive writeups → sibling `note-YYYYMMDD-*.md` files)

- §8/§9/§10 definitions + Stage 3 spec: `~/.claude/plans/make-me-a-multi-atomic-tower.md`.

---
*Planned via plan-milestone on 2026-06-03*
