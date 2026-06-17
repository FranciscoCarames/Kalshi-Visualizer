---
topic: real-time-opportunity-engine
created: 2026-06-02
---

# Milestone Log: real-time-opportunity-engine

Newest at top. Append-only summary of shipped milestones.

## s4 — FastAPI engine API (shipped 2026-06-04)

`api.py` typed FastAPI service over the engine: read endpoints serve the latest store snapshot;
store-backed `POST /scan` (TTL guard, skip/force) persists results + coverage `meta`. Plus `fetch.py`
(Streamlit-free fetch), `scanner.run_scan` (coverage), `store` schema v2 (`meta` + staged migration),
`serve.py`. PR #40 (merged); 224 tests, verified offline + live uvicorn boot.

Archive: `milestones/s4-fastapi-api/`

## s3 — Lifecycle: alerts + recently-actionable (shipped 2026-06-03)

`lifecycle.py` — pure snapshot-diff (new-actionable §8, blocked-change §9, recently-actionable §10)
derived from the Stage-2 snapshots (no store migration); unified row enriched with `rule_flag` +
`market_status`; interim banner/backlog/blocked-change UI. PR #39; 209 tests, verified offline + AppTest
+ live prev/cur smoke.

Archive: `milestones/s3-lifecycle/`

## s2 — Cross-sport global scanner (shipped 2026-06-03)

`scanner.py` — pure (injected-fetch) aggregator running `build_checks` + `find_dutch_books` across all
sports into one ranked frame, stamping `sport`, partial-failure-tolerant, and the first real caller of
the Stage-1 store. `filters` gained a `sports` filter; `app.py` got a minimal additive toggle-gated
cross-sport table (once-per-`fetched_at` snapshot). PR #38; 188 tests, verified offline + live + AppTest.

Archive: `milestones/s2-cross-sport-scanner/`

## s1 — Opportunity schema + SQLite snapshot store (shipped 2026-06-03)

Stable deterministic `opportunity_id` + `relationship_type` + `bucket` + required `blocked_reason`
stamped on consistency and dutch-book rows (one shared `data.opportunity_id` helper), plus a standalone
pandas-free SQLite `store.py` (write/latest_two/snapshots_since + versioned schema/migration +
retention). Pure engine, no on-screen change. PR #37; 182 tests, verified offline + live.

Archive: `milestones/s1-opportunity-schema-store/`
