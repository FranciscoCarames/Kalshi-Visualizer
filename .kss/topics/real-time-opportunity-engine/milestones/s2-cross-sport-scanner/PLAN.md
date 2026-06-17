---
milestone: s2-cross-sport-scanner
topic: real-time-opportunity-engine
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: s2 — Cross-sport global scanner

> Stage 2 of the 6-stage roadmap (`~/.claude/plans/make-me-a-multi-atomic-tower.md`). Builds directly
> on s1 (every row already carries `opportunity_id` / `relationship_type` / `bucket` / `blocked_reason`)
> and is the **first caller of the s1 SQLite store**.

## Goal (one sentence)

One pure function that aggregates opportunities across **all wired sports** (tennis + NBA + WNBA) into a
single frame ranked best→worst — independent of any UI selection — stamping each row with its `sport`,
and persisting each scan to the s1 snapshot store.

## Success Criteria

What must be true to call this shipped:

- [ ] `scanner.unified_opportunities(...)` returns ONE ranked frame combining `build_checks` +
      `find_dutch_books` across every sport in `sports.all_sports()`; each row stamped with `sport`
      (sport_id) and a sport display label. Pure — **no Streamlit / network import in `scanner.py`**
      (the per-sport fetch is dependency-injected, so tests run offline).
- [ ] Deterministic ranking: actionable first, then by gross edge (`exec_gap_c` / locked ¢) descending,
      with a stable tiebreak — documented and unit-tested. (`opportunity_id` already stable from s1.)
- [ ] A **partial per-sport failure** (one sport errors/returns empty) never blanks the table — other
      sports still appear and the failure is surfaced (returned alongside the frame), not swallowed.
- [ ] Each scan **writes one snapshot** via `store.write_snapshot` (the s1 store's first real caller),
      gated so unit tests don't touch disk (inject store / a flag).
- [ ] Interim Streamlit surfacing: a single honest **"All loaded markets (core series | full scan)"**
      sortable table + CSV in `app.py` — header NEVER claims "all Kalshi markets". Kept minimal
      (replaced wholesale by NiceGUI at Stage 5).
- [ ] Suite green (new `test_scanner.py` + `test_filters` sport filter); ruff clean; headless boot 200.

## Out of Scope

- Net-of-fees / slippage (gross edge only — deferred to a later stage).
- WebSocket / async / incremental refetch (REST + the existing cache only).
- NiceGUI / FastAPI (Stages 4–5); the interim table is throwaway Streamlit.
- Lifecycle: new-actionable / blocked-change / recently-actionable diffing (that's Stage 3, which
  consumes the snapshots this stage starts writing).
- Any new detection logic or per-sport relationship changes.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `scanner.py` (NEW, pure): `unified_opportunities(fetch_fn, *, store_writer, fetched_at)` — loop `sports.all_sports()`, call injected `fetch_fn(sport_id) -> df`, run `build_checks` + `find_dutch_books`, stamp `sport`/`sport_label`, concat | ✓ |
| 2 | Unified ranked schema (`UNIFIED_COLUMNS`) both row shapes map onto + ranking `(bucket_priority, -gross_edge_c, opportunity_id)` | ✓ |
| 3 | Partial-failure handling: per-sport errors collected, never raise; returns `(frame, per_sport_errors)` | ✓ |
| 4 | Snapshot write via injected `store_writer` (default None → no disk in tests; app injects `store.write_snapshot`) | ✓ |
| 5 | `filters.py`: `sports` membership filter (no-ops when column absent); `test_filters` extended | ✓ |
| 6 | `app.py`: additive, toggle-gated "All loaded markets — cross-sport" table; cached `load_contracts` as fetch_fn; once-per-fetched_at snapshot; refresh clamp; errors surfaced | ✓ |
| 7 | `config.py`: no new knob needed (reused FULL_SCAN_MIN_INTERVAL + SNAPSHOT_*) | ✓ |
| 8 | Tests: new `test_scanner.py` + `test_filters` ext; 188 pass, ruff clean, headless 200, live cross-sport scan → **PR #38** | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

**SHIPPED 2026-06-03 via PR #38** (awaiting owner merge). 188 tests, ruff clean, headless 200; live
cross-sport scan returned 366 opps across 3 sports with a real actionable NBA dutch book + snapshot
round-trip. Open questions resolved (column union, exec_gap ranking, once-per-fetched_at cadence). UI
kept additive/minimal (single-sport dashboard untouched) per the owner's decision.

## Open Questions

(resolve as you go; promote stable answers to TOPIC.md Key Decisions at close)

- **Purity boundary:** `scanner.py` must stay Streamlit-free, but the only fetch path today
  (`app.load_contracts`) is `@st.cache_data` in `app.py`. Confirm dependency-injection: `fetch_fn`
  signature = `(sport_id) -> (contracts_df, fetch_meta)`; app passes its cached loader, tests pass a
  stub. (Avoids `scanner` importing `app`/`streamlit` and keeps tests offline.)
- **Unified ranking key:** proposed `(bucket_priority, -gross_edge_c, opportunity_id)` where
  bucket_priority = actionable < blocked < near_edge < signals < clean/data_quality. Confirm the exact
  edge field across the two row types (consistency `exec_gap_c` vs dutch-book locked `exec_gap_c` — both
  exist) and the tiebreak.
- **Snapshot cadence:** write a snapshot on EVERY scan (every refresh tick), or only when the
  actionable set changes? Roadmap says every refresh; confirm that's acceptable given retention
  (s1 retention = 30h; tick ≈ 120s → ~900 snapshots — within cap, but note row volume).
- **Column union:** consistency rows and dutch-book findings have different schemas. Define the shared
  minimal columns for the unified frame (so the table + CSV are coherent) without losing per-type
  detail needed later.

## Notes

(deep-dive session writeups go to sibling `note-YYYYMMDD-*.md` files)

- Live shape reference (from the s1 live smoke test, 2026-06-03): a single all-sports core-series scan
  returned ~405 contracts → ~367 consistency rows + ~1 dutch-book finding across tennis/NBA/WNBA. So the
  unified frame is a few-hundred rows per scan — fine for an in-memory concat + a sortable table.
- Stage 2 deliverables/risks/acceptance detail: `~/.claude/plans/make-me-a-multi-atomic-tower.md` §Stage 2.

---
*Planned via plan-milestone on 2026-06-03*
