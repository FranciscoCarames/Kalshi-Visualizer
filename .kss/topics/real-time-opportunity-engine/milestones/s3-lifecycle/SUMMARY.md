---
milestone: s3-lifecycle
topic: real-time-opportunity-engine
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: s3 — Lifecycle: alerts + recently-actionable

## What Shipped

`lifecycle.py` — pure snapshot-diff functions over the snapshots Stage 2 persists: `new_actionable` (§8),
`persisting_new_actionable` (banner persistence over full retained history), `blocked_change` (§9 "what
changed"), `recently_actionable` (§10 backlog with `reason_left` precedence), `first_seen` (numeric ts).
State is derived from snapshot history — **no store schema change**. The unified row gained `rule_flag` +
a normalized `market_status` (scanner + a tiny `dutchbook` field) so the diff has what it needs. Interim
Streamlit surfacing (toggle-gated cross-sport section): a persistent new-actionable banner + "New" flag,
a windowed recently-actionable table, and a minimal changed-while-blocked table — all with safe
`latest_two()` normalization. Merged via **PR #39**.

## Success Criteria

- [x] `lifecycle.py` pure functions, unit-tested on crafted fixtures — passed.
- [x] Banner persistence uses full retained history (long-actionable row not falsely "new") — passed (test).
- [x] `blocked_change` classifies the §9 dimensions; silent when nothing changed — passed.
- [x] `recently_actionable` §10 fields + numeric became/left + `reason_left` precedence — passed.
- [x] Snapshot rows carry `rule_flag` + `market_status` (additive, no migration) — passed.
- [x] Interim banner + recently-actionable + minimal blocked-change UI (safe normalization) — passed.
- [x] 203→209 tests green + ruff + headless 200; AppTest renders the UI; live prev/cur smoke — passed.

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Lifecycle state DERIVED from snapshot history, not a new store table | first-seen / new / recently-actionable are all computable from persisted snapshots; avoids a schema/migration and mutable state | Pure diff functions; "until acknowledged" persistence deferred to Stage 5 (NiceGUI ack) |
| Banner persistence computed over FULL retained history, not a window slice | a window-clipped history makes a long-actionable row look falsely "new" once early snapshots drop off | `persisting_new_actionable(history, window_s, now_ts)` + a clip-safety test |
| `reason_left` precedence: disappeared → leg inactive → went blocked → went clean | deterministic, intuitive ordering for "why an edge left" | unit-tested; drives the §10 backlog label |

## Deferred

No new seeds. "Until acknowledged" alert persistence and the rich alert/backlog treatment are Stage 5
(NiceGUI); snapshot-level `stale` and graded relationship confidence remain out of scope.

## Files Touched

- `lifecycle.py` (NEW) + `tests/test_lifecycle.py` (NEW).
- `scanner.py` / `dutchbook.py` — `rule_flag` + `market_status` enrichment.
- `config.py` (BACKLOG_WINDOWS/ALERT_PERSISTENCE_OPTIONS), `glossary.py` (3 terms), `app.py` (interim UI).

## Sessions

1 build session on 2026-06-03 (3 plan-review rounds). Verified offline (209 tests, ruff, headless 200),
real-app `AppTest` (empty + seeded-populated rendering), and a live prev/cur diff on the real persisted schema.

---
*Closed via complete-milestone on 2026-06-03*
