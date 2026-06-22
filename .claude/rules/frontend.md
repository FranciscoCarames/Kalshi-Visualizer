---
paths:
  - "frontend/**"
  - "webui/feed.py"
---

# React SPA — "Kalshi Structured Scanner" (`frontend/`) — do not regress

The SPA is the **default UI at `/`** (served from `frontend/dist` by `serve.py::mount_spa` when built;
the legacy NiceGUI dashboard is retained at `/dashboard`). Stack: **Vite + React + TypeScript**, **AG Grid
Community** (virtualized DOM grid), **Dockview** (docked/floating/pop-out panels), **cmdk** (Ctrl-K
palette), React context for state; the feed is polled (~4s) with an optional `/stream` SSE path.

## PRIME INVARIANT (do not break)

**The SPA is a faster VIEW of the engine, never a second engine.** It copies `bucket` / `status` /
`tradable_now` / `rule_flag` **verbatim**; client-side lenses are **SORT ONLY** (never re-bucket);
`ev` / `ripeness` / `cond_*` / net-of-fees are **display-only**, computed in **`webui/feed.py`** (NOT in
`scanner.py` / `consistency.py`), and proven isolated by `tests/test_feed.py` +
`tests/test_speculative_isolation.py`. Any new display-only number lives in `feed.py` and must never rank
or change a bucket. **Display-only / no de-vig in the SPA** is a scope guard — see CLAUDE.md "Scope guard"
(the field-de-vig panel lives only in the legacy NiceGUI `/dashboard`).

## Backend boundary

The SPA reads the engine **only** through `GET /api/terminal/feed` plus the thin read-only parity views in
`api.py`: `/api/terminal/detail|payoff|ladder|diagnostics|orderbook|stream|telemetry` and
`POST /api/terminal/export`. New parity endpoints must reuse `webui` engine/viewmodel/viz/export and stay
read-only. `detail`/`ladder` REQUIRE a `tournament` (the `(player_key, tournament)` grouping — no false
cross-tournament ladder).

## Source map (`frontend/src/`)

`feed.ts` (types + loader + taxonomy) · `context.tsx` (all state + poll + derived) · `App.tsx` (chrome +
surfaces) · `Workspace.tsx` + `panels.tsx` (Dockview) · `columns.ts` (per-bucket catalogs) · `lens.ts` ·
`filters.ts` (two-pass membership/threshold split, mirrors `filters.py`) · `Inspector.tsx` ·
`Ladder.tsx` · `Charts.tsx` · `Surfaces`/`SidePanels.tsx` · `Palette.tsx` + `Keys.tsx` · `stream.ts` ·
`alerts.ts` · `prefs.ts` · `AuthGate.tsx` · `csv.ts` · `main.tsx` (entry).

## Gotchas (do not regress)

- **AG-Grid module registration** is in `main.tsx` (`ModuleRegistry.registerModules`) — required once
  before any grid; do not drop it in refactors.
- A `cellRenderer` returning a **string is HTML-escaped** by `ag-grid-react` — return a React element
  (`createElement`), as the name column in `columns.ts` does.
- **Filter split:** `filters.ts` mirrors the engine two-pass — **membership** narrows all sections + counts;
  **thresholds** spare Actionable. Actionable count is membership-only (do not let a band/threshold reduce it).
- Net-of-fees toggle is **display-only, off by default**.

## Build & verify

```bash
cd frontend && npm install && npm run build   # → frontend/dist (gitignored); / is unmounted until built
npx vitest run                                 # frontend unit tests (*.test.ts)
npx tsc --noEmit                               # type check
```

Backend parity/isolation: `pytest -q` (incl. `test_feed`, `test_speculative_isolation`, `test_serve_spa`,
`test_terminal_endpoints`). Live-dev hot reload: `python serve.py` + `cd frontend && npm run dev` (Vite
proxies `/api` → backend; base path `/`).
