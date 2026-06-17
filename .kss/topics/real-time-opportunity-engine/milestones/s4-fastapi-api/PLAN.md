---
milestone: s4-fastapi-api
topic: real-time-opportunity-engine
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: s4 — FastAPI engine API (the boundary)

> Stage 4 of the roadmap. Full design + verification: `~/.claude/plans/immutable-gathering-valiant.md`.
> Builds on s1–s3 (scanner + store + lifecycle, all pure/in-process). The seam the s5 NiceGUI UI consumes.

## Goal (one sentence)

Expose the engine (scanner + store + lifecycle) as a typed REST API — read endpoints serve the latest
persisted snapshot; a store-backed `POST /scan` runs a Streamlit-free scan and persists results with
coverage metadata — with thin handlers, a `serve.py` uvicorn entrypoint, and OpenAPI docs.

## Success Criteria

- [ ] `fetch.py` (pure) extracted from `app.load_contracts`; `app.load_contracts` is a thin `@st.cache_data`
      wrapper (app behavior unchanged — headless boot still 200).
- [ ] `store.py` schema **v2** with a `meta` column: a FRESH DB is created with `snapshots.meta`; an
      existing **v1** DB upgrades via `ALTER` (both unit-tested); `write_snapshot(meta=...)` round-trips;
      `latest()` added.
- [ ] `scanner.run_scan(fetch_fn, *, fetched_at)` aggregates coverage (scanned/loaded/failed/excluded +
      per-sport/series errors) and returns `(unified_df, coverage)`; pure, partial-failure tolerant.
- [ ] `api.py` FastAPI app + Pydantic models + thin handlers: `GET /opportunities` (sport/bucket/status
      filter), `GET /opportunities/{id}` (404 if absent), `GET /backlog`, `GET /coverage`, `GET /alerts`,
      `POST /scan` (store-backed TTL guard; skip → `skipped:true` + no duplicate write; `force` overrides),
      `GET /healthz`; `/docs` renders. No detection logic in `api.py`.
- [ ] `serve.py` uvicorn entrypoint; `config.py` API_HOST/API_PORT/SCAN_MIN_INTERVAL_SECONDS; deps added.
- [ ] `test_api.py` (TestClient, dependency_overrides → tmp store + stub fetch, NO network) green; full
      suite + ruff; service boot serves `/docs`+`/healthz` 200 and a live `POST /scan` populates the store.

## Out of Scope

- No auth / multi-user / websockets / scheduler / background worker (POST /scan is on-demand).
- No NiceGUI / UI (Stage 5); no net-of-fees; no new detection logic.
- No "until acknowledged" alert state (Stage 5).

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `fetch.py`: extract `fetch_contracts(...)`; `app.load_contracts` → thin cached wrapper | ✓ |
| 2 | `store.py`: schema v2 (`meta` in base CREATE + staged `_migrate` fresh/v1), `write_snapshot(meta=)`, `latest()` | ✓ |
| 3 | `scanner.run_scan(fetch_fn, *, fetched_at)` — coverage aggregation + unified frame | ✓ |
| 4 | `api.py`: Pydantic models + thin endpoints (read-from-store + POST /scan + /healthz); overridable deps | ✓ |
| 5 | `serve.py` uvicorn entrypoint; `config.py` API_HOST/API_PORT/SCAN_MIN_INTERVAL_SECONDS | ✓ |
| 6 | `requirements.txt` (fastapi/uvicorn[standard]/pydantic) + `requirements-dev.txt` (httpx) | ✓ |
| 7 | Tests: `test_api.py` + `test_store` (both migration paths + meta + latest) + `test_scanner` (run_scan) | ✓ |
| 8 | Verify: pip install, pytest + ruff, live serve boot, streamlit regression → **PR #40** | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

**SHIPPED 2026-06-03 via PR #40** (awaiting owner merge). 223 tests, ruff clean, streamlit headless 200;
live `uvicorn` boot served /docs+/healthz 200, `POST /scan` → 367 opps / 18 series / 0 failed, /coverage
honest, second /scan skipped by the store-backed TTL guard. Migration verified both ways (fresh v2 has
`meta`; v1 upgrades via ALTER). Open questions resolved (raw-seconds window params; honest no-meta
coverage; api.py owns scan-level fetched_at).

## Open Questions

- `/backlog` & `/alerts` window params: raw seconds (`window_s`/`persistence_s`) + sane defaults; label-mapping stays in the UI.
- `/coverage` when the serving snapshot has no meta (written by Streamlit): age/stale + counts null + `meta_present:false` (never fake numbers).
- `run_scan` fetched_at: one scan-level stamp from api.py (deterministic), not per-sport fetch values.

## Notes

- Stage 4 spec + §endpoint detail: `~/.claude/plans/make-me-a-multi-atomic-tower.md` (Stage 4).
- FastAPI is NOT installed in this env → verification must `pip install` (sandbox off).

---
*Planned via plan-milestone on 2026-06-03*
