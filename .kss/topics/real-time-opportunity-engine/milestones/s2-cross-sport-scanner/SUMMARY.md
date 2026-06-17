---
milestone: s2-cross-sport-scanner
topic: real-time-opportunity-engine
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: s2 — Cross-sport global scanner

## What Shipped

`scanner.py` — one PURE function (`unified_opportunities`, Streamlit-free + network-free via an injected
`fetch_fn`) that aggregates `build_checks` + `find_dutch_books` across all wired sports (tennis + NBA +
WNBA) into a single best→worst-ranked frame, stamps each row with its `sport`, normalizes the two row
shapes onto one `UNIFIED_COLUMNS` schema, ranks by `(bucket_priority, −gross_edge_c, opportunity_id)`,
tolerates a per-sport fetch failure (recorded, never blanks the rest), and is the FIRST real caller of
the Stage-1 snapshot store. `filters.apply_membership` gained a `sports` filter. `app.py` got a minimal,
additive, **toggle-gated** "All loaded markets — cross-sport" table (default off; single-sport dashboard
untouched) that writes one snapshot per distinct `fetched_at`. Merged via **PR #38**.

## Success Criteria

- [x] Unified ranked frame across all sports, `sport` stamped, pure (injected fetch) — passed.
- [x] Deterministic ranking (actionable first, then gross edge, id tiebreak) — passed; verified live (monotonic).
- [x] Partial per-sport failure never blanks the frame — passed (unit-tested).
- [x] Each scan writes one snapshot via the injected store_writer — passed; once-per-`fetched_at` de-dup verified via AppTest.
- [x] Minimal honest interim Streamlit table ("All loaded markets", not "all Kalshi") — passed.
- [x] Suite green + ruff + headless 200 — passed (188 tests; live scan of 366–368 opps across 3 sports; real-app AppTest).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Interim UI is ADDITIVE + toggle-gated (single-sport dashboard untouched), not a multi-sport rebuild | Stage 5 replaces the UI with NiceGUI; don't polish throwaway Streamlit. Avoids the ~3× all-sports fetch unless asked | One cross-sport table behind a toggle; the pure `scanner.py` + tests are the real deliverable |
| Scanner is pure via an INJECTED `fetch_fn(sport_id) -> df` (app passes cached `load_contracts`, tests pass a stub) | Keeps `scanner.py` Streamlit-free + network-free + offline-testable; no import of `app`/`streamlit`/`kalshi_client` | `unified_opportunities(fetch_fn, *, store_writer, fetched_at)` |
| Snapshots written once per distinct `fetched_at` (session-state de-dup) | Streamlit reruns (widget clicks) must not write duplicate snapshots; only a genuinely fresh fetch persists | Verified: 3 renders within the cache window → 1 snapshot |

## Deferred

No new seeds. `sport`-narrowing of the per-sport dashboard sections and net-of-fees remain later/out of
scope; lifecycle (consuming these snapshots) is the next milestone (s3).

## Files Touched

- `scanner.py` (NEW) — cross-sport aggregator.
- `filters.py` — `sports` membership filter.
- `app.py` — additive toggle-gated cross-sport table + snapshot writer.
- `tests/test_scanner.py` (NEW) + `tests/test_filters.py` extension.

## Sessions

1 build session on 2026-06-03 (topic LOG.md). Verified offline (188 tests, ruff, headless 200), via a
real-`app.py` `AppTest` run (toggle on/off, default-path snapshot, de-dup), and against live Kalshi data
(366–368 opps across 3 sports, real actionable NBA dutch book, snapshot round-trip).

---
*Closed via complete-milestone on 2026-06-03*
