---
paths:
  - "webui/**"
---

# UI — NiceGUI dashboard (`webui/dashboard.py`) — do not regress

The legacy NiceGUI dashboard is **retained at `/dashboard`** as a read-only fallback (the React SPA in
`frontend/` is the default UI at `/`). Mounted on FastAPI via `serve.py`. Layout: display + scan controls,
a filter row (Sport / Tournament / Participant / Min size / Active-only / Review / Blocked), the ranked
**Actionable** table, **Review** + **Blocked** (toggle-gated), opt-in **Risk-budget** / **Near-miss**
sections, a recently-actionable backlog, a click-to-open explanation dialog + participant detail panel,
and a collapsed Diagnostics & debug expander. `viewmodel.py` + `diagnostics.py` are the pure cores.

- **Filter split (critical — do not regress):** `consistency.bucket_of(row)` routes each comparison;
  `webui/viewmodel.filter_opps` reuses the two-pass `filters.py` split — **membership**
  (sport/tournament/participant/min-volume) narrows **every section**; **thresholds** (min size, quote,
  market status) spare **Actionable** but gate the others. Full diagnostics is built from the
  membership-filtered set (NOT the thresholded set) so **finalized markets stay visible** there. (Fully
  closed events are excluded at the API level — `get_events` passes `status="open"`.)
- **Section order:** Actionable is always visible, **ranked best→worst**; Review/Blocked + opt-in
  sections follow; detail/diagnostics/debug collapsed below.
- **Status display labels** (no "Potential edge"; "edge" only for a positive executable gap):
  `EXECUTABLE_VIOLATION`→"Actionable gross edge", `DISPLAY_VIOLATION`→"Display inconsistency",
  `WIDE_QUOTE`→"Wide quote / watchlist", `MISSING_QUOTE`→"Missing firm quote",
  `QUOTE_SIZE_MISSING`→"Blocked: no size", `CLEAN`→"Consistent". Internal status strings are unchanged.
