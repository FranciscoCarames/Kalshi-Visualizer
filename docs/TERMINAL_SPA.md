# Terminal Pro SPA — status & continuation handoff

The redesigned trader workstation (mockup `ui-mockup-final-spa.html`), built as a dedicated
client-side SPA on the owner's bake-off-proven stack and served at **`/terminal`**. The legacy NiceGUI
dashboard is untouched at **`/`**. This doc is the pick-up point for a fresh session.

## Where it lives
- **Branch:** `feat/terminal-spa` (based off `feat/ui-prototype-bakeoff`, which has the Vite scaffold +
  `ui-prototypes/shared`). `main` is frozen — owner merges manually (branch-only delivery).
- **Frontend:** `frontend/` — a standalone Vite + React + TypeScript app (`node_modules/` + `dist/` are
  gitignored — run `npm install` / `npm run build` after a fresh clone).
- **Backend:** `webui/feed.py` (the read-only terminal-feed adapter) + `GET /api/terminal/feed` in
  `api.py`; `serve.py::mount_spa` serves the built `frontend/dist` at `/terminal` when present.
- **Full plan:** `~/.claude/plans/graceful-strolling-acorn.md` (audit-revised, gated A→D).

## Stack (from the recorded bake-off — `ui-prototypes/README.md`)
Vite + **React + TypeScript** · **AG Grid Community** (DOM, virtualized) · **Dockview** (docked / floating /
pop-out panels) · **cmdk** (Ctrl-K palette) · React context for state · feed polled every 4s. Glide-canvas
remains the documented no-lag swap behind the grid, **unbuilt** until a measured need.

## PRIME INVARIANT (do not break)
**The SPA is a faster VIEW of the engine, never a second engine.** It copies `bucket` / `status` /
`tradable_now` / `rule_flag` verbatim; lenses are **client-side SORT ONLY** (never re-bucket); `ev` /
`ripeness` / `cond_*` / fees are **display-only**, computed in `webui/feed.py` (not in scanner/consistency),
and proven isolated by `tests/test_feed.py` + `tests/test_speculative_isolation.py`.

## What's done (all committed, all verified live with 0 console errors)
- **Phase A** — `webui/feed.py` + `/api/terminal/feed` (contract/parity/isolation tests in
  `tests/test_feed.py`); React parity blotter; `mount_spa` + `tests/test_serve_spa.py`.
- **Phase B** — Dockview docked workspace (drag/resize/pop-out + presets) · 6 lenses · full per-bucket
  column catalogs + custom chooser · inspector trade-card + MD ladder · Ctrl-K palette · keyboard
  (1-6 / J/K / `/`) · amber + high-contrast themes · multi-select → Compare / Don't-take-both / CSV export.
- **Phase C** — OPP/RES/OPS surfaces · inspector Participant-detail + Formulas tabs · net-of-fees toggle
  (display-only, off by default).

## Run / build / verify
```bash
# backend tests (unchanged engine): from repo root
pytest -q                 # 953 pass, incl. test_feed / test_speculative_isolation / test_serve_spa
ruff check .              # (the only warnings are in the untracked _export_mockup_data.py, now superseded)

# production: build the SPA, then boot — /terminal serves the built bundle, / is the legacy dashboard
cd frontend && npm install && npm run build
cd .. && python serve.py                       # http://127.0.0.1:8000/terminal

# live dev (hot reload): serve.py on :8000 + Vite proxying /api → :8000
python serve.py                                # terminal 1
cd frontend && npm run dev                     # terminal 2 → http://localhost:5180/terminal/
```
Frontend source map: `frontend/src/` — `feed.ts` (types + loader + taxonomy), `context.tsx` (all state +
poll + derived), `App.tsx` (chrome + surfaces), `Workspace.tsx` + `panels.tsx` (Dockview), `columns.ts`
(per-bucket catalogs), `lens.ts`, `Inspector.tsx` (card/detail/formulas), `Ladder.tsx`, `SidePanels.tsx`,
`Surfaces.tsx` (RES/OPS), `Palette.tsx` + `Keys.tsx`, `csv.ts`, `tokens.css`.

## Remaining work (pick up here)

### Phase D — retire the old NiceGUI `/terminal`
**Already moot on this branch:** `feat/terminal-spa` never contained `webui/terminal.py` (that lived on the
separate `feat/terminal-pro-ui` branch). On this branch the React SPA already owns `/terminal` and the
NiceGUI dashboard owns `/`. If `feat/terminal-pro-ui` is ever merged first, Phase D = delete
`webui/terminal.py`, its `serve.py` import, `tests/test_terminal.py`, the `/terminal` cases in
`tests/test_browser.py`, and the `webui.terminal` line in `tests/nicegui_main.py`.

### Optional follow-ups
1. **Real field-de-vig** — build `GET /api/terminal/detail?sport=&player_key=` reusing
   `consistency.devig_field_by_node` + `webui.engine.participant_contracts` / `tournament_field`; have the
   inspector **Participant Detail** tab fetch it to fill the "field-impl. est." column (currently a
   labelled placeholder pointing here). Add a parity/isolation test (must stay display-only).
2. **Ship the build in deploy** — add a `cd frontend && npm ci && npm run build` step to
   `scripts/build_deploy_repo.py` so `frontend/dist` is included in the deploy artifact (see
   `docs/DEPLOYMENT.md`).
3. **Promote to `/`** — once validated, optionally make the SPA the default surface (replacing or
   redirecting the NiceGUI dashboard). Keep `/` serving NiceGUI until the owner approves the swap.

## Notes / gotchas
- AG-Grid module registration is in `frontend/src/main.tsx` (`ModuleRegistry.registerModules`) — required
  once before any grid; don't drop it in refactors.
- A function `cellRenderer` returning a string is escaped by `ag-grid-react` — return a React element
  (`createElement`), see the name column in `columns.ts`.
- Vite proxy does **not** strip `/api` (so `/api/terminal/feed` reaches the backend); base is `/terminal/`.
- `_export_mockup_data.py` (untracked, root) is the one-off that produced the static `tp-final-data.js`;
  `webui/feed.py` supersedes it as the live feed.
