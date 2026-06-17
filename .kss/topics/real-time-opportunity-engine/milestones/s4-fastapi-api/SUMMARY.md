---
milestone: s4-fastapi-api
topic: real-time-opportunity-engine
shipped: 2026-06-04
status: shipped
---

# Milestone Summary: s4 — FastAPI engine API (the boundary)

## What Shipped

`api.py` — a typed FastAPI service exposing the engine: read endpoints (`/opportunities` +sport/bucket/
status filters, `/opportunities/{id}`, `/backlog`, `/coverage`, `/alerts`, `/healthz`) serve the latest
persisted snapshot; `POST /scan` runs a Streamlit-free scan on demand behind a **store-backed TTL guard**
(skip → `skipped:true` + no duplicate write; `force` overrides) and persists results **with coverage
metadata**. Supporting changes: `fetch.py` (extracted the pure fetch from `app.load_contracts`, now a thin
cached wrapper), `scanner.run_scan` (coverage aggregation), `store.py` **schema v2** (`meta` column;
staged migration — fresh→full v2, existing v1→`ALTER`), `serve.py` (uvicorn entrypoint). Merged via
**PR #40** (`main`).

## Success Criteria

- [x] `fetch.py` extracted; `app.load_contracts` a thin wrapper (app unchanged; headless 200) — passed.
- [x] `store.py` schema v2 with `meta`; fresh→v2 has `meta`, v1→`ALTER` (both unit-tested); `write_snapshot(meta=)`, `latest()` — passed.
- [x] `scanner.run_scan` aggregates coverage (scanned/loaded/failed/excluded + per-sport/series errors), pure + partial-failure tolerant — passed.
- [x] `api.py` thin handlers; all endpoints + filters + 404 + store-backed `POST /scan` (skip/force) + `/docs` — passed.
- [x] `serve.py` uvicorn; `config` API_HOST/PORT/SCAN_MIN_INTERVAL_SECONDS; deps added — passed.
- [x] `test_api.py` (TestClient + overrides, no network) + suite + ruff + live boot — passed (224 tests).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| The API SERVES the persisted store snapshot (read endpoints are read-only); `POST /scan` is the only fetch trigger, guarded by a STORE-backed TTL (not process memory) | Fast/deterministic reads, sane after restart, decoupled from any single writer; skip returns the latest result + writes nothing | `store.latest()` powers reads; `/scan` skip/force semantics; coverage persisted in snapshot `meta` |
| Coverage is persisted WITH the snapshot (`meta`), and `/coverage` reports `meta_present:false` rather than faking counts when a snapshot lacks meta (e.g. Streamlit-written) | Honest coverage across mixed writers + restarts; no fabricated numbers | store schema v2 + the `meta_present` flag |
| The store evolves via real VERSIONED migrations (base CREATE = current schema for fresh DBs; incremental `ALTER` steps for older versions) | A naive `SCHEMA_VERSION` bump would mark a fresh DB current without the new column — both paths must be tested | staged `_migrate`; fresh + v1 migration tests |

## Deferred

No new seeds. NiceGUI consuming these endpoints is s5; full-scan scan-scope in the API/UI is a later toggle.

## Files Touched

`api.py` (NEW), `serve.py` (NEW), `fetch.py` (NEW), `store.py` (schema v2 + `latest`), `scanner.py`
(`run_scan`), `app.py` (`load_contracts` → wrapper), `config.py` (API_*), `requirements*.txt`,
`tests/test_api.py` (NEW) + `test_store`/`test_scanner` extensions.

## Sessions

Built 2026-06-03 (2 plan-review rounds); merged + extensively re-verified pre-merge 2026-06-04 (224 tests,
ruff, both store migrations, full live `uvicorn` boot — empty-store + 367-opp scan + filters + TTL guard,
Streamlit regression 200, + an empty-store endpoint test added).

---
*Closed via complete-milestone on 2026-06-04*
