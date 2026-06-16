# Terminal Pro SPA — status & continuation handoff

The redesigned trader workstation (mockup `ui-mockup-final-spa.html`), built as a dedicated
client-side SPA on the owner's bake-off-proven stack and served at **`/terminal`**. The legacy NiceGUI
dashboard is untouched at **`/`**. This doc is the pick-up point for a fresh session.

---

## ✅ 5 inspector/links/ladder/defaults fixes — DONE (2026-06-15, uncommitted, awaiting owner test+merge)

Branch **`feat/terminal-spa-parity`**. All 5 owner-requested polish/correctness fixes are implemented +
verified in the working tree (NOT committed — owner merges manually). Plan (audit-hardened):
`~/.claude/plans/show-me-the-full-eager-wreath.md`.

1. **Charts too big** — SUPERSEDED by the table redesign below; `Charts.tsx` SVGs were first shrunk, then
   replaced entirely with numeric tables (owner preferred numbers over bars).
2. **Conditional probs discoverable** — `Inspector.tsx` Trade-Card now shows a one-line conditional pointer
   for containment rows; Participant-Detail leads with a plain-English explainer + full row labels.
3. **Per-participant + per-side deep links** — `webui/feed.py` `_leg_deep_link` builds
   `<event_url>?op_market_ticker=<TK>&op_order_side=<yes|no>` into each `legs[].u`; `data.kalshi_url` (event
   url) left intact for link_audit. Engine is BUY-ONLY → side is the buy's yes/no.
4. **Real Kalshi order book** (synthetic dropped) — `kalshi_client.get_orderbook()` (Decimal cents via
   `data.to_cents`, tolerates malformed rungs) + read-only `GET /api/terminal/orderbook` (depth clamp
   1..100, light ticker validation, ~2s per-ticker TTL cache, sliding-window limiter, honest-degrade on
   4xx/5xx/empty). `Ladder.tsx` rewritten: deleted `book()`; YES bids verbatim, YES asks = `100 − no_price`
   (best ask from the HIGHEST no-bid), ~5s refetch while selected + AbortController, "LIVE · refreshed Ns
   ago", empty → "no resting orders". Live-verified unauthenticated against Kalshi.
5. **Band defaults = old UI** — `feed.meta.defaults` (config 5/3/15/15); `filters.ts` `defaultBand(section,
   meta.defaults)` seeds PER-SECTION (bounded max-loss 5¢ vs cheap-NO 15¢ collide → per-section band map in
   `context.tsx`); SecBar (`App.tsx`) shows a defaults hint + "reset band".

Verified: `pytest -q` 981 green, `vitest` 31 green, `tsc` + `npm run build` clean, `ruff` clean (only the
untracked `_export_mockup_data.py` is dirty), serve.py boot smoke, live Kalshi orderbook probe. New/updated
tests: `tests/test_feed.py`, `tests/test_client.py`, `tests/test_terminal_endpoints.py`,
`frontend/src/filters.test.ts`, `frontend/src/ladder.test.ts`. Remaining owner step: visual `/terminal`
check + merge.

## ✅ Follow-on polish — DONE same session (2026-06-15)

- **Participant-Detail charts → numeric tables** (`Charts.tsx`): owner disliked the inline-SVG bars (too
  small, imprecise, preferred numbers). Both rebuilt as `.condtbl` tables, no SVG. `LadderChart` = Layer /
  Disp % / Δ-vs-parent / step verdict (inversion → red "↑ INVERTED"); `PayoffChart` = Scenario / Role /
  Payout / signed P&L (green/red), `Cost N¢ · per contract · gross` header. Dead `.chart` CSS removed.
  Mockup used to choose the design: `chart-redesign-mockup.html` (untracked scratch, safe to delete).
- **Count-badge fixes** (`context.tsx`, `Blotter.tsx`): (1) tab/tile counts for the speculative band
  sections (bounded/nearmiss/cheapno) now apply the SecBar band, so the BOUNDED-LOSS badge tracks the
  Max-loss control (Actionable stays membership-only — invariant preserved). (2) new `zoneCount(z)` = Σ of
  the zone's section counts, so the SPECULATIVE badge is the true total instead of mirroring the first
  (bounded) sub-tab. `filteredCount` import dropped (now inlined band-aware).

## ⏭️ PENDING for next session — terminology rename (agreed, NOT yet applied)

Owner approved a desk-standard-but-honest label pass (display text only — keep internal keys/buckets/CSS
`data-tab`/tests/engine fields/the `ripeness` lens name). Final agreed set (audit-reconciled):
- **Sections:** `BOUNDED-LOSS`→**BOUNDED RISK**, `CHEAP-NO`→**CHEAP NO FADES**, spec tagline→
  `bounded-risk · speculative · can lose money`; RES/OPS `BOUNDED-LOSS MIX`→**BOUNDED RISK MIX**,
  `CHEAP-NO SCOPE`→**CHEAP NO SCOPE**. Keep **NEAR-MISS**.
- **Columns (`columns.ts`):** `Participant / market`→**Participant / Market**, `Max units`→**Max contracts**,
  `Upside:risk`→**Reward / risk**, `Quote health`→**Quote quality**, `Market gap (pp)`→**Parent − child gap
  (pp)**, `Success given reached %`→**P(win │ parent) %**, `Deeper given reached %`→**P(deeper │ parent) %**,
  `Parent ÷ max loss`→**Parent coverage / ¢ risk**, `Kind`→**Structure**, `Caveat`→**Risk note**. (Keep
  `Max gross profit`.)
- **Inspector:** `BUY-ONLY PLAN`→**BUY PLAN** (NOT "Order plan" — read-only posture), `ECONOMICS (PER UNIT)`→
  **P&L — PER CONTRACT**, `Worst case`/`Best case`→**Max loss**/**Max gross profit**, `Max units`→**Max
  contracts**, `Ripeness (parent÷loss)`→**Parent coverage / ¢ risk**, `WHY RANKED HERE`→**RANKING
  RATIONALE**, `EVIDENCEPACK`→**EVIDENCE / CHECKS**, `Opp id`→**Opportunity ID**, `PER-UNIT PAYOFF BY
  SCENARIO`→**SCENARIO PAYOFF — PER CONTRACT**, Formulas heading→**PARENT COVERAGE / ¢ RISK**.
- **Charts tables:** payoff `· per unit ·`→`· per contract ·`, cols `Settles`/`Profit`→**Role**/**P&L**
  (keep `Payout` distinct); ladder `Disp %`/`Δ parent`/`Step`→**Implied %**/**Δ vs parent**/**Check**.
- **3 deviations from the audit (intentional):** keep **P&L** (not "Payoff") for the economics block AND
  the payoff table's profit column (a `Payout`+`Payoff` pair would collide); harmonize BOTH conditional
  columns to **parent** (audit was internally inconsistent). Rejected: `Market`, `ITM per ¢ risk`,
  `ORDER PLAN`, `Notes`, `NO FADES`-without-"cheap".

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
