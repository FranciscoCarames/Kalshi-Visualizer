# Kalshi Opportunity Engine — Development Roadmap

> Strategy and architecture document. Revised **2026-06-03**. Decisions captured: **audience = small
> private group**, **latency target = a few seconds**, **execution = read-only now, fully-automated
> trading only in the very long term**, **opportunity scope = all sports + all Kalshi categories**
> (today: **all tennis** is shipped; other sports/categories are the next frontier).
>
> **Status of the codebase (verified 2026-06-03):** `main` is generalized beyond the French Open —
> `build_contracts` ingests **all tennis events**, each stamped with a never-empty `tournament` key, and
> containment ladders group by `(player_key, tournament)`. The pure modules the rearchitecture depends on
> already exist and are tested: `data.py`, `consistency.py`, `filters.py`, `glossary.py`, `viz.py` (all
> Streamlit-free), plus a `tests/` suite and an opportunity-ranking chart. **The Streamlit app is further
> along than this doc's Phase 2/3 framing assumes — tennis generalization is done, not pending.**

---

## Current roadmap — Opportunity-first, cross-sport scanner (Stages 0–5)

> **This is the finalized, active roadmap** (locked this session). It supersedes the longer-horizon
> "real-time engine roadmap" framing below for near-term planning. The §3–§6 material that follows is
> **preserved as a parked strategy backlog** — it still informs where things go after these six stages,
> but the six stages here are what we build next. Everything in this section is **planned / upcoming
> work**, not yet built, unless a stage explicitly says otherwise.

The app today is a mature read-only Streamlit dashboard over Kalshi sports markets (Tennis / NBA / WNBA),
with a clean engine/UI split and ~150 tests. An audit confirmed much of the broad backlog is **already
built**. These six stages target only the genuine remaining gaps the owner called out, in order, on the
current Streamlit stack — while keeping the durable logic migration-ready.

### Locked decisions (read these first)

- **SQLite snapshot store on disk** is in scope (a deliberate change to the old "no persisted storage"
  guard). But **do NOT build multi-user / server / auth architecture yet** — the store is merely designed
  so it does not *preclude* future sharing.
- **Gross edge only for now.** Fees / net-edge / slippage are explicitly deferred to a separate later
  stage; the "before fees/slippage" caveat stays loud.
- **Frontend will migrate to React / FastAPI within months.** So: keep durable logic in the pure engine
  modules + a SQLite store + clean surfaces; treat all Streamlit work as pragmatic and throwaway.
- **Timezone selector with Lisbon default** (`Europe/Lisbon`), UTC still selectable; TZ work is
  display-only and never touches the exact-cents comparison math.
- **Honest scope labels** — the scanner header says **"All loaded markets"** (with a `(core series)` or
  `(full scan — all discoverable series)` qualifier), never "all Kalshi markets".
- **Replace the ranking graph with a sortable table** — the Altair `opportunity_ranking` chart is
  removed; the unified cross-sport opportunity table is the sortable surface that replaces it.

### The six stages, in order

- **Stage 0 — Clarity quick wins (no new infrastructure).** *Shipped — PR #34.* Immediate daily value with
  zero new infra: a timezone selector (Lisbon default) applied to every displayed time; **remove** the
  misleading ranking graph; a "Show IDs & codes" toggle (default OFF) exposing series/event/market codes
  and participant IDs; an always-visible **data-freshness & coverage strip** on the main dashboard (local
  time, data age, refresh status, stale-data warning, coverage/fetch-failure counts); and **debug + full
  diagnostics moved behind a single Advanced toggle, default OFF**.
  *Implementation note:* the freshness strip is rendered by a dedicated lightweight `st.fragment`
  (`FRESHNESS_TICK_SECONDS`, default 10s) that recomputes age from the cached fetch, so **Data age climbs
  live and the stale warning fires even when auto-refresh is off** — without any extra network fetch.

- **Stage 1 — Opportunity schema + SQLite snapshot store (durable backbone).** *Upcoming.* Give every
  opportunity a stable, deterministic `opportunity_id`; make `blocked_reason` a **required** schema field
  (non-empty iff the opportunity is blocked); add a `relationship_type`; and stand up `store.py`, a local
  **SQLite snapshot store** written once per refresh, with read APIs for the latest two snapshots and a
  time window. This is the backbone that survives the React migration and unblocks alerts and backlog. No
  multi-user, no locking, no server.

- **Stage 2 — Cross-sport global scanner (always-on unified table).** *Upcoming.* One unified,
  always-visible **sortable table** of actionable opportunities scanned over the **full loaded market
  universe across all wired sports simultaneously**, ranked best→worst — computed *independently of* any
  player/event/series selection (those are views layered on top). New `scanner.py` aggregates per-sport
  results. Header uses the honest "All loaded markets (\<fetch mode\>)" label; ships a simple unified-table
  CSV download and a minimal opportunity-first layout (fuller restructure deferred to Stage 4). Selecting a
  sport drops into today's focused per-sport view.

- **Stage 3 — Lifecycle: alerts + recently-actionable backlog.** *Upcoming.* Make opportunities appearing
  and disappearing impossible to miss, all derived from the SQLite store via pure diffs (`lifecycle.py`):
  a **new-actionable alert** (banner + toast + highlighted row + "New" tag + first-seen time + metric
  delta, with configurable persistence); a **blocked-change alert** (changed marker + last-changed time +
  a classified "what changed" label — blocker / price / liquidity / stale / missing-leg / `rule_flag_changed`
  / market-status); and a **Recently Actionable** section sourced from the store over a user-selected window
  (15m / 1h / 4h / 24h / session) showing became/left times and why each opportunity left.

- **Stage 4 — Opportunity-first dashboard restructure.** *Upcoming.* Build the *fuller* restructure on top
  of Stage 2's minimal layout: a clear section order (Actionable Now → Blocked-but-Interesting → Recently
  Actionable → main opportunity table → explanation panel → entity drill-down → Advanced), a row-click
  **explanation panel** surfacing the already-present explainability fields, and demotion of the old
  "selected player detail" + "full diagnostics" sprawl into drill-down / Advanced. No information lost —
  it moves, not deleted. Kept lean (Streamlit is throwaway pre-migration).

- **Stage 5 — Export overhaul (dedicated).** *Upcoming.* A dedicated export panel with **eight datasets**
  (current opportunities, actionable-only, blocked-only, recently-actionable backlog, raw contracts,
  normalized contracts, a **relationship table**, and a **diagnostics bundle**), as CSV per table plus one
  JSON/ZIP bundle. Every export embeds the active filters + `fetched_at` (TZ-aware) for reproducibility.
  XLSX/Parquet and scheduled/auto-export are explicitly deferred.

### Stage-level non-goals (carried across all six)

No fees / net-edge / slippage yet; no multi-user / server / auth / shared rate limiter; no React/FastAPI
migration *within these stages* (kept migration-ready); no new sports; no sound alerts; no historical
analytics beyond the snapshot store + backlog window. Comparison/edge math stays exact-integer-cents.

> **Doc-sync note:** the SQLite store is a scope change to CLAUDE.md's "don't-add" list. When Stage 1
> lands, `CLAUDE.md` and the two Google Drive docs (Project Brief + Technical Documentation) must be
> updated to match — see "Documentation follow-through" in the source plan.

---

## Next steps (committed — 2026-06-03)

This is the decision layer on top of the brainstorm below. Order is deliberate; each item is small and
ships on the **current Streamlit stack** (no rearchitecture yet).

1. **NS-1 — Fee-aware net edge (was P0.1). The single highest-value, lowest-effort change.** Implement the
   verified Kalshi fee formula and re-rank every opportunity by **net-of-fees** edge; relabel "gross edge"
   → "net edge". Pure work in `consistency.py` + a fee helper; fully unit-testable offline. **Verified
   inputs (see §0):** taker `= ceil(0.07·P·(1−P)·100)/100` per contract, **per side**, peaks 1.75¢ at 50¢;
   maker = 25% of taker; **fee rate varies by market — do NOT hardcode `0.07`**, read a per-series rate with
   the general formula as default. Both legs of a human-crossed structural trade pay **taker** fees, so a
   2¢ gross gap is routinely net-negative — that's the credibility bug this fixes.
2. **NS-2 — Dutch-book / sum-to-one detector (was P0.2). The keystone for category generalization.**
   Generalize the containment ladder into the MECE primitive over any `mutually_exclusive` group: `Σ YES
   asks ≥ $1` and `Σ YES bids ≤ $1`; buying every outcome's YES for net `< $1` is a true (rule-free) arb.
   Subsumes tennis ladders and is the one detector that ports to politics/econ/weather unchanged. Pure
   module, property-testable on the Σ invariants. Must consume NS-1's net-of-fees numbers.
3. **NS-3 — Live validation while tennis markets are open (time-boxed, opportunistic).** Capture a few
   real live-book examples through NS-1/NS-2 and pin them as regression fixtures. **Caveat (do not let this
   reorder the plan):** the French Open ends **2026-06-09**; after it, live FO tournament-winner fields go
   quiet, though other live tennis (ATP/WTA tour events) and eventually other categories keep the detectors
   exercised. If the window closes before NS-1/NS-2 land, fall back to **synthetic fixtures** — correctness
   does not depend on live data, only fresh real-world examples do.
4. **NS-4 — Resolve the two genuinely-open infra facts before committing to Phase 1.** The fee question is
   now answered (§0). Still undocumented and **blocking the funnel design**: (a) WS **max subscriptions per
   connection**, (b) whether **WS is metered separately from the REST token buckets**. Kalshi's docs are
   silent — these need a **small live spike** with a read-only API key (or a support question), not more
   doc-reading. Do this before, not during, the backend decouple.

Everything past NS-4 (backend decouple, push frontend, non-tennis categories, history, execution) stays as
the staged plan in §3–§4 below. **Recommended sequence: NS-1 → NS-2 → NS-3 (opportunistic, in parallel) →
NS-4 → reassess Phase 1.**

---

## 0. Verified facts that drive the architecture (current as of June 2026)

| Fact | Source | Consequence |
|---|---|---|
| Kalshi has a **WebSocket feed**: `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (demo: `…ws.demo.kalshi.co/…`). **Public** channels: `ticker`, `orderbook_delta`, `trade`, `market_lifecycle_v2`, `multivariate_market_lifecycle`, `cfbenchmarks_value`. **Authenticated/account-scoped** channels: `fill`, `market_positions`, order/order-group updates, `communications`. *(Verified via docs index + WS channel page, 2026-06-03.)* | [WS channels index](https://docs.kalshi.com/llms.txt) · [Orderbook Updates](https://docs.kalshi.com/websockets/orderbook-updates) | Real-time at scale must be **push (WS)**, not REST polling. **`orderbook_delta` is PUBLIC market data** (snapshot-then-delta, fields `price_dollars`/`delta_fp`/`side`) — a **read-only key reaches full depth**; only the *connection* needs auth. (Corrects an earlier "private" mis-note.) Resolves the depth-access open question. |
| **Every WS connection requires API-key auth during the handshake** — confirmed, including for public market-data channels. REST market data stays keyless. *(Verified live 2026-06-03.)* | [WS quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) | The "no auth" simplicity ends the moment we stream. We need a Kalshi API key pair (read-only scope; **no** trading scope). |
| REST rate limits (token bucket, **10 tokens/standard GET**): Basic 200 read / 100 write tok/s (~20 GET/s read), Advanced 300/300, Premier 1000/1000, Paragon 2000/2000, Prime 4000/4000. Some ops (cancels, single-order reads, quote create/cancel) cost <10; batch items are billed individually, not discounted. *(Verified live 2026-06-03.)* | [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) | Polling the whole universe is impossible; ~10.5k series alone is ~53 paginated GETs just to enumerate. |
| **Fee formula (verified, Kalshi schedule Feb 2026):** taker `fee = ceil(0.07 · P · (1−P) · 100)/100` **per contract**, **per side**, rounded up to the next cent — peaks **1.75¢ at P=0.50**, → 0 at the extremes. **Maker = 25% of taker** (frequently rounds to **$0.00**). **The coefficient varies by market** — special events (elections, championships, awards) differ from the `0.07` default. *(Verified live 2026-06-03.)* | [Fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) · [Help: fees](https://help.kalshi.com/trading/fees) | Net edge must subtract **taker fees on both legs** (a human crossing to capture a structural edge is a taker twice). The per-market coefficient means the engine reads a **fee rate per series**, defaulting to `0.07`, never hardcoding it. |
| **WS max subscriptions/connection and WS-vs-REST metering are NOT documented** — Kalshi's WS and rate-limit pages are both silent. *(Confirmed undocumented 2026-06-03.)* | [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) · [WS quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) | These bound how wide "stream-narrow" can go and whether the funnel is comfortable. **Resolve by live spike / support question (NS-4), not by reading docs** — the docs don't contain the answer. |
| The Kalshi book is **unified**: `no_ask == 1 − yes_bid` exactly. The REST orderbook endpoint returns **yes bids and no bids only (no asks)** — an "ask" is the opposite side's bid. | CLAUDE.md (verified live) · [docs index](https://docs.kalshi.com/llms.txt) | There is **no within-market YES/NO arb** by construction. All real edge is **cross-market**. Depth, when needed, is read as yes/no bid levels (REST `GetMarketOrderbook` / batch `GetMultipleMarketOrderbooks`, or WS `orderbook_delta`). |
| **Useful primitives for later phases** (from the docs index, not yet used): **candlesticks** at 1/60/1440-min via `GetMarket/EventCandlesticks` (history *without* our own tick storage); **per-series/-event fee overrides** via `GetSeriesFeeChanges`/`GetEventFeeChanges` (the concrete source for NS-1's per-series fee-rate table); `GetExchangeSchedule`/`GetExchangeStatus` (open/closed + maintenance windows). | [docs index](https://docs.kalshi.com/llms.txt) | Candlesticks could power price context/sparklines with no storage; fee-change endpoints turn "coefficient varies by market" from a caveat into a lookup; schedule endpoints sharpen the time-to-resolution signal. All **deferred** — referenced so we don't re-discover them. |
| `~10,500` series across all categories; tens of thousands of active markets. | repo `config.py:71` | "Stream everything at once" is not a thing. Architecture must scan-wide-slow + stream-narrow-fast. |

**The one design insight everything hangs on:** you cannot hold the entire exchange live. The correct
shape is a **two-tier funnel** — a cheap, slow REST *scan* over the whole universe to find *where a
structural edge could exist* (candidate set), then a fast WS *stream* on only the hot subset to confirm
and act. "General across all Kalshi" means general **detection**, not streaming every market.

---

## 1. Trader's critique of the current product (read this before planning features)

Taking the seat of a multi-year Kalshi trader looking at the app as it stands:

1. **"Gross edge" is a trap — there are no fees in your math.** *(Fee schedule now verified — see §0.)*
   Kalshi's **taker** fee is `ceil(0.07 · P · (1−P) · 100)/100` per contract, per side, peaking at 1.75¢
   at 50¢. A human capturing a structural edge **crosses on both legs → pays taker fees twice**, so a 2¢
   gross gap is usually **net-negative**. Ranking by *gross* edge surfaces opportunities that lose money.
   Two refinements the live schedule forces: (a) the coefficient **varies by market** (special events
   differ from `0.07`) → read a per-series rate, never hardcode; (b) **maker fees are only 25% of taker**
   and often round to $0 — irrelevant while we cross to capture, but the lever if execution (P4.4) ever
   posts resting orders. **Net-of-fees edge is non-negotiable** and is NS-1, the highest-value fix here.

2. **Your niche is actually the right one — name it.** Within a single unified book there's no arb
   (no_ask = 1 − yes_bid). Pure cross-market arbs that *don't* carry settlement-rule risk get vacuumed
   by bots in milliseconds. What persists for a **human** is exactly what you flag: cross-market
   structural mispricings that bots avoid **because the settlement rules might not match**
   (`RULE_CHECK_REQUIRED`). So the product's real value proposition is a **rule-risk-aware structural
   scanner where the human supplies the settlement-rule judgment.** Lean into that; it's defensible and
   not bot-contested.

3. **The containment ladder is a special case of a far more general edge.** The general, category-agnostic
   structural edge is the **mutually-exclusive / sum-to-one (dutch book)** test: for any MECE outcome set
   (tournament winner across all players, an economic range market's buckets, an election field), `Σ YES
   asks` should be ≥ $1 and `Σ YES bids` ≤ $1; if you can buy every outcome's YES for < $1 (or every NO
   appropriately) for a guaranteed $1, that's a true arb. This **subsumes** tennis ladders and instantly
   generalizes to politics/econ/weather. It should be the engine's core primitive.

4. **Top-of-book size is not executable size.** You read best bid/ask + top size only. A real edge needs
   depth: an edge on 3 contracts at the touch evaporates after fees. `orderbook_delta` gives true depth;
   until then, every "edge" should be sized and discounted honestly.

5. **Stale-quote risk.** Half of apparent edges are resting orders about to be pulled. By the time a
   human crosses, they're gone. This is the real argument for the few-second-latency / WS move you chose:
   not to *race bots*, but so the signal you're looking at is *live*, not 30–120s stale.

6. **The UI is built for explanation, not for scanning.** Plain-English "Buy YES / Buy NO + blockers" is
   excellent for trust and onboarding, but a working trader scanning hundreds of markets wants a **dense,
   sortable, flash-on-change blotter** ranked by net edge, with color-coded severity and one-click
   drill-down — not prose cards. Keep the prose in a detail panel; make the main surface terse and dense.

---

## 2. Why the current stack hits a wall on *your* three choices

Your answers (small group / few-second / all categories) each independently break the Streamlit monolith,
and together they're decisive:

- **All categories → can't poll.** REST at 20 GET/s can't refresh tens of thousands of markets in
  seconds. Forces WS + the scan-wide/stream-narrow funnel.
- **Few-second + "important updates visually obvious" → push, not rerun.** Streamlit's full-script rerun
  reserializes whole dataframes over its internal socket; there's no clean "flash these 3 changed cells"
  path. `st.fragment(run_every)` is a timer-poll, not push.
- **Small private group → the process-wide throttle becomes a bug.** Each Streamlit session reruns its
  own script with its **own** limiter (see `config.py:77`). Five users = 5× the Kalshi load and no shared
  rate budget. Multi-user *requires* one shared backend holding the data, not N independent app processes.

**Conclusion:** decouple. One **shared backend** (auth + WS ingestion + order-book state + detection
engine + shared rate limiter) and a **thin client per user**. The good news: your pure modules
(`data.py`, `consistency.py`, `filters.py`, `viz.py`) are already Streamlit-free — that discipline is
exactly what makes this migration cheap. They become the backend's compute core almost unchanged.

---

## 3. Target architecture (end-state, build toward incrementally)

```
            Kalshi REST (keyless)            Kalshi WS (API-key signed)
          enumerate series/events           ticker · trade · orderbook_delta
                    │                                    │
                    ▼                                    ▼
        ┌─────────────────────────── Ingestion service (async: FastAPI + httpx + websockets) ──┐
        │  • slow REST scan → universe of markets + MECE/ladder candidate groups               │
        │  • WS subscribe ONLY the hot subset → maintain in-memory order books (depth)          │
        │  • run detection engine on tick (dutch-book / ladder / equivalence), NET of fees      │
        │  • SHARED token-bucket rate limiter (fixes the per-process limiter)                   │
        └───────────────┬───────────────────────────────────────────────────────────────────┘
                        │  latest state + signal deltas
                        ▼
              ┌──────── Redis (only once >1 backend proc / for pub-sub fan-out) ───────┐
                        │
                        ▼
        ┌──────── API / push tier (FastAPI) ────────┐
        │  REST: snapshot + config                  │
        │  WS:   snapshot-then-stream deltas,        │
        │        per-client watchlist filtering      │
        └───────────────┬───────────────────────────┘
                        │  WebSocket (delta messages)
                        ▼
        ┌──────── Frontend (per user) ──────────────┐
        │  dense blotter (AG Grid: applyTransaction, │
        │  flash-on-change, virtualized, sort by net │
        │  edge), book-depth drill-down, detail panel│
        │  (existing blockers/glossary prose)        │
        └────────────────────────────────────────────┘
```

**Frontend decision (deferred but framed):**
- **Pragmatic middle — recommended first move:** **NiceGUI** (pure Python, FastAPI-native, websocket
  push, ships AG Grid + ECharts as components). Lets you reuse the Python core, get a real
  flash-on-change blotter, and run one shared server — without a separate JS build. Best effort/payoff
  for a small group. (Dash + `dash-extensions` + `dash-ag-grid` is the equivalent alternative.)
- **Best-in-class end-state:** decoupled **SolidJS/React + AG Grid + TradingView Lightweight Charts**
  over the FastAPI WS. Reserve this for when the group grows, you want pro charting/in-grid interaction,
  or you head toward execution. 5–10× the effort; don't pay it yet.
- **Streamlit's role:** it can survive as a *thin read-only client* of the backend during transition, or
  be retired. It should **stop being the thing that fetches and computes.**

---

## 4. Staged plan

### Phase 0 — Correctness & generalization on the *existing* stack (fast, high-value, no rearchitecture)
Goal: fix the trader-credibility gaps and prove the general engine before touching infrastructure.
*(P0.1/P0.2 are the committed NS-1/NS-2 above — detail here, decision there.)*

- **P0.1 Fee-aware net edge → NS-1.** Implement the Kalshi fee formula (verified §0); compute **net edge
  after taker fees on both legs**; re-rank Actionable by net, not gross. Relabel "gross edge" → "net edge".
  Use a **per-series fee rate** (default `0.07`), never a hardcoded constant. *(Biggest credibility win;
  small, pure-`consistency.py` change.)*
- **P0.2 Dutch-book / sum-to-one detector → NS-2.** Generalize from containment ladders to the MECE
  primitive over any `mutually_exclusive` group. Tennis ladders become one strategy among several. Pure
  module work, fully unit-testable offline. This is the keystone for category generalization.
- **P0.3 Honest sizing.** Surface executable size and a fee-and-size-adjusted edge; stop implying a 3-lot
  touch edge is a real opportunity.
- **P0.4 API-key client (read scope).** Stand up RSA-signed request signing + WS auth as a *library*
  (no trading scope). Doesn't change the UI yet; unblocks Phase 1. Secrets via env / `.env` (already
  gitignored).

### Phase 1 — Real-time data core (decouple the backend)
Goal: one shared, push-based, fee-aware engine — the thing the group connects to.

- **P1.1 Async ingestion service** (FastAPI + `httpx` async + `websockets`): slow REST universe scan +
  candidate detection; WS-subscribe the hot subset; maintain in-memory order books (depth from
  `orderbook_delta`); run the detection engine on tick.
- **P1.2 Scan-wide / stream-narrow funnel** as the explicit core loop (see §0 insight).
- **P1.3 Shared rate limiter** (token bucket; in-process now, Redis-backed when >1 process) — retires the
  per-process-throttle caveat.
- **P1.4 Push API**: FastAPI WS endpoint, snapshot-then-stream, per-client watchlist filtering.

### Phase 2 — Trader-grade frontend
Goal: scanning speed + "important updates are visually unmissable."

- **P2.1 Pick the view tier** (recommend NiceGUI first; React end-state documented). Decision gate.
- **P2.2 Dense blotter**: virtualized, sortable by net edge, **flash-on-change**, severity color,
  keyboard-navigable. The main surface.
- **P2.3 Drill-down**: order-book depth view + the existing blockers/glossary prose in a side panel
  (preserve the explainability that's already a strength).
- **P2.4 "Unmissable update" treatment**: when a *new actionable net edge* appears or crosses a
  threshold, make it loud (row flash + sticky toast + optional sound), distinct from routine reprice.

### Phase 3 — Category breadth (the generalization payoff)
Goal: all sports + all Kalshi categories via a strategy/adapter model.
*(Partially shipped: tennis is already generalized beyond the French Open — all tennis events, grouped by
`(player_key, tournament)`. Phase 3 is now about **non-tennis** categories, not tennis tournaments.)*

- **P3.1 Detector-as-strategy plugin model**: each opportunity type (ladder, dutch-book, cross-market
  equivalence, …) is a strategy over a normalized market graph. New categories = new adapters, not engine
  rewrites.
- **P3.2 Category adapters**: sports ladders (NBA/NFL/soccer) → reuse containment; politics/econ →
  MECE/range buckets; weather → range buckets. Driven by `mutually_exclusive` + market metadata.
- **P3.3 Settlement-rule equivalence hardening** (the genuinely dangerous part — go slow, stay
  conservative): keep `RULE_CHECK_REQUIRED` as the default; consider an *offline, human-gated*
  LLM-assisted rule-text comparison to upgrade confidence, never auto-trusting it.

### Phase 4 — Long-term extensions
- **P4.1 History (DuckDB)**: persist ticks/signals to measure how long edges actually persisted and which
  signals were genuinely actionable — turns the app into its own backtest. (Currently out of CLAUDE.md
  scope; gate explicitly.)
- **P4.2 Alerting / push notifications** for high-value net edges (mobile/desktop/Slack).
- **P4.3 Cross-platform** (Polymarket / others): same-event identity matching → cross-venue arb. Big data
  + entity-resolution problem; high payoff, high effort.
- **P4.4 (Very long term) Execution**: semi-automated one-click staging → risk-controlled full automation.
  Separate trading-scoped keys, hard risk limits, kill switch, audit log. A different risk universe — its
  own design doc when the time comes.

---

## 5. Cross-cutting concerns (don't let these rot)

- **Fees everywhere**: once P0.1 lands, no edge is ever shown gross again.
- **Secrets**: API keys in env / secret store, never in repo (`.env` already gitignored). Read-only scope
  until P4.4.
- **Testing discipline**: keep the pure modules Streamlit-free and offline-unit-tested (the current
  strength). Add property tests for the dutch-book detector (Σ invariants).
- **Observability**: structured logs + a health/metrics endpoint on the backend (WS connection state,
  scan lag, detection latency, rate-budget headroom).
- **Failed series still surfaced, never silently dropped** (existing hard requirement — carry forward).
- **Scope guard update**: this roadmap *intentionally* expands the old guard (auth for WS read; multi-leg
  arbs; all categories; eventual execution). Update CLAUDE.md's scope guard when each phase is approved so
  the guard and the plan don't contradict.

---

## 6. Open questions to resolve as we go

1. ~~**Fee schedule**~~ — **RESOLVED (2026-06-03).** Taker `= ceil(0.07·P·(1−P)·100)/100` per contract,
   per side; maker = 25% of taker; **coefficient varies by market** (special events differ). Folded into
   §0 and NS-1. Remaining sub-item: enumerate which series carry a non-`0.07` rate (read from the fee-
   schedule PDF when building the per-series rate table).
2. **WS subscription limits** — **confirmed undocumented (2026-06-03).** Kalshi's WS page states no
   max-subscriptions/connection cap. Bounds how wide "stream-narrow" can be and may force multiple
   connections. **→ NS-4 live spike**, not resolvable from docs.
3. **WS vs REST metering** — **confirmed undocumented (2026-06-03).** Neither the rate-limit page nor the
   WS page says whether WS counts against the REST token buckets. If WS is unmetered the funnel is very
   comfortable; if metered, the slow scan and the stream share Basic's 200 read tok/s. **→ NS-4 live
   spike.** (Basic = 200 read / 100 write tok/s, confirmed; fine for the slow scan regardless.)
4. ~~**`orderbook_delta` access scope**~~ — **RESOLVED (2026-06-03).** `orderbook_delta` is a **public**
   market-data channel ([Orderbook Updates](https://docs.kalshi.com/websockets/orderbook-updates)); only the
   connection needs auth, so a **read-only key reaches full depth** (snapshot-then-delta, yes/no bid levels).
   The earlier "private" note was a mis-summary. No spike needed for this.
5. **Frontend**: NiceGUI vs Dash vs full React — decide at the P2.1 gate with a small spike of each on the
   real blotter. *(Note: a Streamlit opportunity-ranking chart already exists in `viz.py`; the dense
   flash-on-change blotter is the gap this gate fills.)*
6. **Candidate-set sizing**: how many markets do we stream concurrently per user/group, and how is the hot
   subset chosen (watchlist + auto-promoted candidates)? Directly downstream of Q2/Q3 (NS-4).
