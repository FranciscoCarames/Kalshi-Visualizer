# Terminal Pro — framework bake-off (5 real prototypes)

Five real Vite/TypeScript SPAs of the **Terminal Pro Opportunity surface**, built to pick a no-lag UI stack
for the Kalshi workstation. Same dataset, same synthetic stress stream, same standardized grid engine, same
perf overlay — so the comparison is fair. Throwaway evaluation prototypes on branch `feat/ui-prototype-bakeoff`
(never `main`). They consume the FastAPI API **read-only** via the Vite `/api` proxy; the engine is untouched.

## Run

```bash
cd ui-prototypes
npm install                 # one workspace install
npm run dev:react           # :5173   React + AG Grid
npm run dev:solid           # :5174   SolidJS + AG Grid
npm run dev:svelte          # :5175   Svelte 5 + AG Grid
npm run dev:vue             # :5176   Vue 3 + AG Grid
npm run dev:canvas          # :5177   React + Glide (canvas)
```

Open `launcher.html` for links + instructions. In each app, the **PERF overlay** (bottom-right) has stress
presets: **ROWS** (100 / 1k / 10k) × **UPDATES/SEC** (1 / 10 / 60 / 240), plus a synthetic↔real(poll) source
toggle (real needs a separate `serve.py` on :8000).

## The five

| Port | App | Reactivity | Grid | Notes |
|---|---|---|---|---|
| 5173 | **React + AG Grid** | virtual DOM | AG Grid (official `ag-grid-react`) | ecosystem benchmark |
| 5174 | **SolidJS + AG Grid** | fine-grained signals, no VDOM | AG Grid (vanilla `createGrid`) | grid init deferred 1 tick (Solid runs `onMount` during render) |
| 5175 | **Svelte 5 + AG Grid** | compiled runes | AG Grid (vanilla) | leanest bundle |
| 5176 | **Vue 3 + AG Grid** | proxy reactivity | AG Grid (vanilla) | closest to the current Quasar/NiceGUI stack |
| 5177 | **React + Glide (canvas)** | virtual DOM | **Glide Data Grid (canvas)** | the no-lag ceiling; same React, swapped grid |

## Benchmark — apply-latency at 10k rows × 240 updates/sec

**Captured headless (Playwright).** ⚠️ Headless background tabs throttle `requestAnimationFrame` and timers,
so **FPS and batches/sec are NOT reliable here** and the four DOM apps land in a noisy band (they share the
same AG Grid engine, so in a *focused* tab expect them to be roughly equal — judge them on DX + feel, not
these numbers). The one robust, structural result is Glide.

| App | apply p50 | apply p95 | batches/s | reading |
|---|---|---|---|---|
| React + AG Grid | 15.9 ms | 19.2 ms | 57 | DOM grid (run before other servers loaded the CPU) |
| Solid + AG Grid | 52.2 ms | 96.7 ms | 16 | DOM grid (noisy/throttled) |
| Svelte + AG Grid | 44.6 ms | 67.6 ms | 20 | DOM grid (noisy/throttled) |
| Vue + AG Grid | 46.1 ms | 89.8 ms | 17 | DOM grid (noisy/throttled) |
| **React + Glide (canvas)** | **0.5 ms** | **1 ms** | **200** | **canvas — ~50–100× cheaper apply; kept up with the stream** |

**Findings**
1. **The grid, not the framework, decides lag.** All four DOM apps use the identical AG Grid engine and
   virtualize 10k rows to ~25–35 DOM nodes; their apply cost is the same order and differences above are
   headless noise. **Canvas (Glide) is the structural winner** — it repaints only changed cells with no DOM
   churn, holding ~1ms apply at 10k×240.
2. So the **framework choice should be made on developer experience, ecosystem, and the *surrounding*
   reactivity** (tiles/ladder/card/lens), then **pick the grid by scale**: AG Grid (DOM) is plenty for your
   real volume (hundreds of rows, second-scale scans); Glide (canvas) is the insurance if you ever push to
   thousands of streaming rows.
3. **Solid gotcha (fixed):** Solid runs `onMount` synchronously during render, so creating AG Grid there
   blocked first paint — deferring grid init by one macrotask fixes it. Vue/Svelte/React mount after paint and
   didn't need it (deferred anyway for consistency).

## How to judge it yourself (the real test)

Open each in a **focused, foreground** browser tab (not headless), set **10k × 240**, then:
- watch the PERF **fps** (green ≥55) and **apply p95**,
- scroll the blotter and select rows under load — does it stay smooth?,
- compare the four DOM apps for *feel* + how pleasant the code was, and feel the Glide canvas ceiling.

## Architecture (the fairness layer)

`shared/` is imported by all five: `tokens.css` (identical Terminal Pro amber look), `data.ts` (dataset +
`api.Opportunity` type + `loadReal()`), `stream.ts` (pluggable `UpdateSource`: synthetic / poll / **sse-stub**
ready for the backend plan's Phase-4 `GET /stream`), `perf.ts` (the overlay). Each app only writes its view +
reactivity wiring + grid integration. AG Grid is standardized for 1–4 (React via the official wrapper, others
via vanilla `createGrid` — same engine); Glide for #5; charts are inline SVG sparklines (no chart dep).

## Invariants kept (visual)

Read-only, `READ-ONLY DEPTH VIEW — NO ORDERS` ladder with no order controls, the
`GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS` disclaimer,
Actionable/Review/Blocked/Research separation, $1 basis. The `api.Opportunity` contract is unchanged, so the
parallel backend-perf plan and these prototypes don't collide.
