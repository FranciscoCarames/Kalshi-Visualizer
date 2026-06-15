# Terminal Pro SPA — status & continuation handoff

The redesigned trader workstation (mockup `ui-mockup-final-spa.html`), built as a dedicated
client-side SPA on the owner's bake-off-proven stack and served at **`/terminal`**. The legacy NiceGUI
dashboard is untouched at **`/`**. This doc is the pick-up point for a fresh session.

---

## ⏭️ NEXT SESSION — START HERE (5 inspector/links/ladder/defaults fixes)

Branch **`feat/terminal-spa-parity`** (full parity DONE + pushed to origin, HEAD `032c9e1`). The full
mockup-exact port + NiceGUI parity is complete; these are 5 owner-requested polish/correctness fixes.
**Full plan:** `~/.claude/plans/delightful-hopping-aurora.md`. Order: 1 → 2 → 5 (quick FE) → 3 → 4.

1. **Charts too big** (Participant-Detail) — `tokens.css .chart` is `width:100%`. Cap `max-width:300px;
   max-height:160px`, shrink viewBoxes (payoff `W240 H96`, ladder `rowH14`, cap ~8 layers).
2. **Conditional probs hard to find** — they're in the **PARTICIPANT DETAIL** tab, ladder rows only
   (`Inspector.tsx` `Detail`, `hasCond`). Add a Trade-Card pointer + plain-English explainer.
3. **Per-participant + per-side deep links** — CONFIRMED format (owner examples):
   `<event_url>?op_market_ticker=<FULL_TICKER>&op_order_side=<yes|no>`. All parts already in each feed leg
   (`u`=event url, `tk`=`KXNBA-27-BOS`, `side`=`buy_yes/buy_no`). Build in `webui/feed.py` `_trim_legs`
   (`legs[].u`); keep `data.kalshi_url` (event url) intact for link_audit. Engine is BUY-ONLY → side is
   always the buy's yes/no (no sell). + a feed test.
4. **Depth ladder — DROP synthetic, show ACTUAL Kalshi order book** (owner: "I want the actual depth").
   Snapshot has only top-of-book → fetch live. CONFIRMED endpoint:
   `GET /trade-api/v2/markets/{ticker}/orderbook?depth=N` → `{orderbook_fp:{yes_dollars:[[price$,size]…],
   no_dollars:[[price$,size]…]}}` (resting bids/side; dollar strings → cents). Add
   `kalshi_client.get_orderbook()` + read-only `GET /api/terminal/orderbook?ticker=` (throttled/rate-
   limited). Rewrite `Ladder.tsx`: delete the fabricated `book()`; render YES bids from `yes_dollars`,
   YES asks = `100 − no_price` (invert `no_dollars`), sizes verbatim; re-fetch ~5s while a row is selected;
   footer "LIVE · refreshed Ns ago"; empty book → honest "no resting orders".
5. **Band defaults ≠ old UI (bug)** — SPA SecBar defaults all to 0 (off); old UI uses
   `config.RISK_BUDGET_DEFAULT_MAX_LOSS_C=5`, `NEAR_MISS_DEFAULT_OVER_C=3`,
   `NO_STRUCTURE_DEFAULT_MAX_LOSS_C=15`, `NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C=15`. Expose via
   `feed.meta.defaults`; seed `filters.emptyBand()` from it; add a defaults hint + "reset band". The
   SecBar (thin bar under the filter row, shown for Bounded-loss/Near-miss/Cheap-NO) is where they live.

Verify: `tsc`+`vitest`+`npm run build`; `pytest -q`+`ruff`; Playwright `/terminal` (compact charts; leg ↗
opens the exact market+side; ladder shows real bid/ask sizes; bounded-loss opens with max-loss 5¢).

---

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

## Full-parity + mockup-exact effort (branch `feat/terminal-spa-parity`, off `feat/terminal-spa`)

Goal: zero gaps vs the old NiceGUI dashboard AND match `ui-mockup-final-spa.html` exactly. Plan +
audit-amendments: `~/.claude/plans/delightful-hopping-aurora.md`. PRIME INVARIANT preserved throughout
(read-only view; new endpoints reuse engine/viewmodel/viz/export; display-only numbers never rank).

**Done + verified (committed):**
- **Stage 1 — backend** (`56033af`): 5 read-only endpoints — `GET /api/terminal/detail|payoff|ladder|
  diagnostics`, `POST /api/terminal/export` (ZIP from posted opportunity_ids). `detail`/`ladder` REQUIRE
  `tournament` (the `(player_key, tournament)` grouping — no false cross-tournament ladder). feed.py adds
  display-only `sport_key`/`player_key`/`tournament` routing keys. `tests/test_terminal_endpoints.py`
  (8 tests: tournament-scoping, 400/404/409, export parity, read-only). Full suite 961 green, ruff clean.
- **Stage 2a — filters** (`2c435d5`): mockup filter bar — Sport + Tournament MULTI-selects (cascading),
  Min-size, Tradable-only, ⬇CSV, clear. New pure `filters.ts` two-pass (membership narrows all; thresholds
  spare Actionable + Diagnostics) drives rows AND counts → Actionable count is membership-only (audit §4,
  verified live: min-size=100k drops other buckets, Actionable holds).
- **Stage 2e — participant detail + charts** (`3889b16`): real data-driven drill-down (chain / derived
  indicators / spreads / expected-vs-found / contracts / rules / raw-fields) from `/detail`, plus inline-SVG
  `LadderChart` + `PayoffChart` (no charting lib). Every derived number caveated uncalibrated/gross/not-fair-
  value. Verified live on a soccer ladder row, 0 console errors.

**Remaining for full parity (not yet built):** scan button + ⚡force + `.scanbar` + `/scan/status` wiring;
⚙ settings menu (long/short wording, show-IDs gate, timezone, auto-refresh, larger-text); per-section
`SecBar` band controls (bounded-loss / near-miss / cheap-no); blotter name-cell sparkline; OPS deep-
diagnostics grids from `/api/terminal/diagnostics`; durable-backlog panel (`/backlog/events`); ZIP export
button wired to `POST /api/terminal/export`; palette Surface/Zone/Split/Toggle/Help groups; cosmetic
clock `KALSHI<POLL>` + footer/keyboard-hints + `--orange/--bid/--ask/--fs` tokens. See the plan file for
the file-by-file map.

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
