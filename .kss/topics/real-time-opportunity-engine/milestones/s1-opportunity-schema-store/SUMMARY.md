---
milestone: s1-opportunity-schema-store
topic: real-time-opportunity-engine
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: s1 — Opportunity schema + SQLite snapshot store

## What Shipped

Every opportunity (containment-ladder consistency rows + dutch-book findings) now carries a stable,
deterministic `opportunity_id`, a `relationship_type`, a dashboard `bucket`, and a REQUIRED
`blocked_reason` (non-empty iff blocked) — stamped via one shared `data.opportunity_id` helper. A new
standalone `store.py` persists one opportunity snapshot per refresh to local SQLite (versioned schema +
forward migration + deterministic retention), readable via `latest_two` / `snapshots_since`. Pure
engine, no on-screen change. Shipped as **PR #37** (awaiting the owner's manual merge per the standing
workflow); verified by 182 unit tests, an offline real-engine integration test, and a live Kalshi
smoke test.

## Success Criteria

- [x] Deterministic, stable `opportunity_id` for consistency AND dutch-book rows via one shared `data.py` sha1 helper — passed cleanly.
- [x] `relationship_type` stamped on every row (`containment_adjacent` | `match_alignment` | `dutch_book`) — passed cleanly.
- [x] `blocked_reason` on every row, non-empty IFF the row's bucket is `blocked` — passed; verified across synthetic + real + live frames.
- [x] `store.py` write/`latest_two`/`snapshots_since`, version pragma + migration, retention cap, unit-tested standalone — passed cleanly.
- [x] No on-screen change; suite green (158 → 182); ruff clean — passed (headless boot 200, app imports clean).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| `opportunity_id` recipe is node/stage-based (NOT market-ticker based), with event-ticker disambiguation for unmapped-match rows | Node-based id survives a representative-market flip between refreshes → tracks the same *logical* opportunity across snapshots (Stage 3); ticker-based would churn. Unmapped matches have no node, so they need the ticker token to stay unique | One shared `data.opportunity_id(*parts)`; uniqueness + determinism covered by tests; resolves the PLAN's open uniqueness question |
| `store.py` is pandas-free (DataFrame duck-typed) with deterministic time (retention/window measured from the NEWEST stored snapshot, not wall-clock) | Keeps the store standalone/unit-testable and its behaviour reproducible regardless of when a query runs | Full-row JSON blob (NaN→null, tuples→arrays) + promoted indexed columns; round-trips real engine output |

## Deferred

No new seeds. Stamping `sport` on each row and the first real `store.write_snapshot` caller are already
scoped to Stage 2 (SEED S2 / the roadmap); `unblock_condition` text and net-of-fees remain later-stage.

## Files Touched

- `data.py` — `opportunity_id()` shared helper (+ `hashlib` import).
- `consistency.py` — `build_checks`/`_row` stamp `relationship_type` / `opportunity_id` / `bucket` / `blocked_reason`; new columns.
- `dutchbook.py` — `_detect_pair` stamps the same four (+ `import data`).
- `store.py` — NEW standalone SQLite snapshot store.
- `config.py` — `SNAPSHOT_DB_PATH` + `SNAPSHOT_RETENTION_SECONDS`.
- `.gitignore` — ignore local `*.db`.
- `tests/test_store.py` (new) + `test_data` / `test_consistency` / `test_dutchbook` extensions.

## Sessions

1 build session on 2026-06-03 (topic LOG.md). Verified offline (182 tests, ruff, headless 200), via a
real-engine→store integration test, and against live Kalshi data (405 contracts across tennis/NBA/WNBA).

---
*Closed via complete-milestone on 2026-06-03*
