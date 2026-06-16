# Real-time live updates for the Terminal Pro SPA — saved plan

> **Status:** APPROVED-FOR-IMPLEMENTATION plan, not yet started. Saved 2026-06-15 for a future session.
> Branch to build on: the newest scanner branch — **`feat/scanner-fee-display`** as of 2026-06-16
> (re-verify; see below). Owner wants the SPA to do exactly what it does today but update **live** (push,
> not 4–10 s poll), with a Kalshi **RSA exchange API key** they will supply. Working copy of this plan
> also at `~/.claude/plans/cozy-spinning-blum.md`.

## How to resume (read first)
1. Re-verify the code state — this plan was rewritten three times because the branch kept advancing
   (`feat/terminal-spa` → `feat/terminal-spa-parity` → `feat/spa-default-ui` → `feat/scanner-fee-display`,
   and counting). **Confirm the current branch and that the line refs below still hold before editing;**
   if not, re-grep and update. Note: `frontend/src/context.tsx` may carry unrelated uncommitted changes.
2. Ship **Stage 1 first** (SSE push, no key) — it is independently valuable and de-risks the transport.
3. Do **Stage 2** as the phased 2A→2B→2C→2D rollout. Do NOT collapse it; the gates exist because turning
   WS deltas into *safe actionable rows* is the hard, false-positive-prone part.
4. Honor the repo's branch-only delivery (no commits/merges to `main`; owner merges manually).

## Session decision log (why the plan looks like this)
- **Two layers separated.** "Real-time" = (1) browser push (NiceGUI already has a WS; the SPA polls) and
  (2) upstream live data (Kalshi WS). Layer 1 is cheap/in-scope; Layer 2 needs the key.
- **Kalshi WS requires auth even for public market data** (RSA-PSS handshake) — verified against
  `docs.kalshi.com`. The owner explicitly asked + supplies the key, so this is sanctioned.
- **An adversarial audit reshaped Stage 2.** Its two load-bearing protocol claims were **verified true**
  against Kalshi docs:
  - `orderbook_delta` is a **single price-level** update (`price_dollars`/`delta_fp`/`side`), preceded by
    an `orderbook_snapshot` (`yes_dollars_fp`/`no_dollars_fp` arrays), with a `seq`. ⇒ a real **order-book
    builder** is required; you cannot track top-of-book from deltas alone.
    (https://docs.kalshi.com/websockets/orderbook-updates)
  - NO-side levels default to **no-leg pricing**; pass **`use_yes_price: true`** or fake crosses appear.
    (https://docs.kalshi.com/getting_started/order_direction)
  - The SSE `event: feed` + `onmessage` mismatch is real (named SSE events need `addEventListener`).
- **Two audit points down-scoped on purpose:** (a) the live engine pushes the SPA **from memory** and
  persists only throttled checkpoints — this *dissolves* the DB-churn + REST/live write-race surface
  rather than patching it with generation IDs/locks (kept only as a backstop); (b) no dual ranking system
  in v1 — a per-row `live_coverage` flag + mixed-stale blocking suffices.
- **Code-state corrections discovered while planning (already folded in):**
  - SPA is now the **default UI at `/`** ("Kalshi Structured Scanner"); NiceGUI moved to `/dashboard`.
  - `GET /api/terminal/feed` is the **only** terminal-presence toucher (`presence.touch()`, `api.py:352`)
    and the scan idle-gate pauses with no viewer ⇒ **SSE must touch presence** or the scanner stops.
  - The SPA's NEW/up/down flash diffs only when `meta.snapshot_id` advances ⇒ live pushes need a
    **monotonic id**.
  - The repo **already has full per-user auth** (`docs/AUTH.md`) — so this is the first *upstream-exchange*
    credential, not the first auth. The new SSE route **auto-gates** under `auth.gate_and_harden`;
    `tests/test_routes_deny_by_default.py` enforces it. `EventSource` carries the same-origin cookie;
    machine-token (header) clients keep polling.
  - A **live order-book REST path already exists**: `kalshi_client.get_orderbook()` → gated
    `GET /api/terminal/orderbook` (TTL cache + limiter) → `Ladder.tsx`, normalized to
    `{yes/no: [[price_c, size]]}` bids-only. The WS builder **emits that same shape** and can **back that
    endpoint** from the live cache when on.
  - This **un-defers an explicit `MASTER_BACKLOG.md` item** ("WebSocket/SSE channel when streaming is
    approved") and advances `docs/STATUS.md`'s stated long-term "real-time engine" direction.

---

## Correctness invariants (do not regress)
- **Single-process only.** Live WS connection + book state + SSE registry are process-local like the
  store/throttle/`scan_manager`. With the live feed enabled, **`WEB_CONCURRENCY>1` must FAIL-HARD** (a 2nd
  worker = a 2nd authenticated WS session, doubled subscriptions, snapshot races).
- **Never fake 50%.** Empty YES/NO arrays ⇒ `yes_bid_dollars="0.00"`/`yes_ask_dollars="1.00"`, never a
  midpoint (`data.py:682-706`).
- **Integer-cents / no `float()` of raw prices.** Parse WS `price_dollars`/`delta_fp` with `Decimal`; keep
  sizes fixed-point; write the same `*_dollars` **strings** into raw market dicts and let `data.to_cents`
  round once at the existing boundary.
- **Detectors need firm bid/ask AND sizes** ⇒ consume the **`orderbook` channel** (snapshot+delta), not
  `ticker` alone.
- **Conservative labeling preserved.** Synthetic exact-score bundles stay review-only (never promoted to
  Actionable because prices are live). Edges stay "gross, top-of-book" — label live rows accordingly.

---

## Stage 1 — browser push of existing snapshots (no key, ship first)

**New `events.py`** (process-local pub/sub, peer of `presence.py`):
- set of **bounded** `asyncio.Queue` subscribers (coalesce: keep only the latest payload per subscriber so
  a slow tab can't accumulate unbounded JSON); `subscribe()`/`unsubscribe(q)`/`publish(payload)`.
- **Cross-thread bridge:** scans run on a daemon thread (`scan_manager.py:81-83`); SSE queues live on the
  uvicorn loop. Capture the loop at startup; `publish()` uses `loop.call_soon_threadsafe`.

**Notify hook:** inject optional `on_complete: Callable[[int], None] | None` into `scan_manager.ScanManager`
(default `None` ⇒ tests stay decoupled); call it in the success branch of `_run()` (`scan_manager.py:96-110`)
— the single choke point all snapshot writes flow through. Wire it in `api.py`/`serve.py`.

**SSE endpoint `GET /api/terminal/stream`** in `api.py` (`StreamingResponse`,
`media_type="text/event-stream"`; register BEFORE the catch-all SPA mount — API routes already precede it
at `serve.py:63`):
- **Build the feed ONCE per publish** (not per subscriber) — `webui.feed.build_feed(db_path=...)` → fan out
  the same JSON to all queues.
- Emit a **named** event: `event: feed\ndata: <json>\n\n`; the client uses `addEventListener("feed", …)`
  (NOT `onmessage`).
- On connect, send the current feed immediately (instant paint).
- **Touch presence on connect AND on every keepalive tick** (`presence.touch()`) — the SSE connection is
  now the viewer, replacing the feed-poll heartbeat so the idle-gate keeps scanning.
- `: keepalive` comment every ~15 s; set `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- **Auth gating (do not regress):** `/api/terminal/stream` auto-**gated** by `auth.gate_and_harden`
  (session or machine token). Do NOT add it to `is_public()`; `tests/test_routes_deny_by_default.py` must
  still pass. Browser `EventSource` carries the same-origin session cookie (works); a raw `EventSource`
  cannot send `X-API-Token`, so machine-token clients keep using polling `/api/terminal/feed`. SSE is a GET
  ⇒ no Origin/CSRF check needed.

**Client (`frontend/src/context.tsx:138-145`):** replace the `setInterval(pull, …)` feed poll with an
`EventSource("/api/terminal/stream")` + `addEventListener("feed", e => setFeed(JSON.parse(e.data)))`. Keep
`loadFeed()` (`frontend/src/feed.ts:47`) for the initial paint AND as a **polling fallback** if the stream
errors repeatedly ⇒ Stage 1 is a strict superset of today. Keep the manual scan path (`runScan`/`scan.ts`,
`context.tsx:108-133`) + its `/scan/status` poll unchanged. Respect `settings.autoRefresh` (SSE when on;
"off" = manual-only). Keep the 1 s clock tick (`context.tsx:137`). The change-signal diff
(`context.tsx:158-169`) is unchanged because each pushed feed carries an advancing `meta.snapshot_id`.

**Stage 1 tests:** connect→first event is current feed; `publish`→second event arrives; named-event
dispatch; bounded-queue drops/coalesces under a slow client; disconnect cleans up; **SSE connect/keepalive
touches presence** (`presence.count()` reflects an open stream); **stream route is gated** (anon→401,
session/token→200, `tests/test_routes_deny_by_default.py` passes); repeated stream error → polling fallback;
`build_feed` called once per publish. Add a frontend **vitest** for the EventSource→`setFeed` + fallback.

**Stage 1 is independently shippable and solves "SPA doesn't update after scans" with no credentials.**

---

## Stage 2 — live Kalshi feed (key; phased, each sub-stage verifiable)

Separation seam: `data.build_contracts` (`data.py:587`) reads prices from a few `market` keys and joins on
`market.get("ticker")` (→ `market_ticker`, `data.py:778`) — the WS subscription key. Everything else
`build_contracts` produces is price-independent. **Structure** (which markets exist, identity,
classification, ladders, **status**) stays REST-sourced + periodic; only **prices** come live.

### Stage 2A — live collector in SHADOW mode (no UI/ranking effect)
New `live_feed.py` (process-local singleton, started via FastAPI **lifespan**; clean shutdown: cancel task,
close socket, mark stale — no dangling tasks in tests):
- **Auth:** RSA-PSS sign of `timestamp + "GET" + "/trade-api/ws/v2"` on the handshake. New explicit deps:
  **`websockets`** + **`cryptography`** in `requirements.txt` (don't rely on uvicorn transitives).
- **Order-book builder (the core):** subscribe to `orderbook` with **`use_yes_price: true`**. Consume
  `orderbook_snapshot` → seed full YES/NO ladders (`Decimal` prices, fixed-point sizes); apply each
  `orderbook_delta` by `side`+`price_dollars` (`delta_fp`); drop zero-size levels; recompute top-of-book.
  **Emit the existing normalized shape** `{yes/no: [[price_c, size]]}` (matching
  `kalshi_client.get_orderbook` / `TerminalOrderbook`) so `Ladder.tsx` is reused.
- **Sequence safety:** track `sid`/`seq` per subscription; on gap/desync, re-request a fresh REST snapshot
  via **`kalshi_client.get_orderbook`** (`kalshi_client.py:221`) and **mark the book desynced** until resynced.
- **Synergy:** when live, back the gated `GET /api/terminal/orderbook` (`api.py:559`) from the live cache;
  keep `_orderbook_cache`/`_orderbook_limiter` as the off/fallback path.
- **Derived fields (matches the app's reciprocal NO-side model):** `yes_bid`=best YES bid;
  `yes_bid_size`=size@best YES bid; `yes_ask`=`1−best NO bid`, `yes_ask_size`=size@best NO bid;
  `no_bid`/`no_bid_size` symmetric; `no_ask`=`1−best YES bid`, `no_ask_size`=size@best YES bid. Empty side
  ⇒ `0.00`/`1.00`.
- **Output:** in-memory cache `market_ticker → {*_dollars strings, *_size_fp, seq, price_as_of, synced}`.
- **Shadow:** expose `/metrics` live fields (connected, reconnect count, last-msg age, sub count, seq gaps,
  desynced-book count) + a diagnostics dump. **No** snapshot writes, feed changes, or ranking effect.

### Stage 2B — REST/WS parity validation
Compare live top-of-book vs the latest REST snapshot for the same tickers; track mismatch rate; validate
side normalization, ask derivation + sizes, empty-book `0.00/1.00`, subpenny. Gate advancing to 2C on low
mismatch — book-builder bugs surface here before they can mislead a trader.

### Stage 2C — live prices in DISPLAY only (NOT actionability)
Refactor `webui.feed.build_feed` into `build_feed_from_unified(unified, meta)` + the existing store-loading
wrapper. Add a **price-overlay** path: copy the last REST scan's raw events (captured via an out-param on
`fetch.fetch_contracts`, `fetch.py:34-39`, mirroring `frames_out`), patch each nested market's
`*_dollars`/`*_size_fp` from the live cache, re-run the **unchanged** `build_contracts` +
`scanner.unified_opportunities(fetch_fn=lambda sid: dfs[sid])`, build a feed via `build_feed_from_unified`,
and push over Stage 1's SSE — **from memory, not via the store**.
- **Monotonic id for the flash diff:** stamp each live push's `meta.snapshot_id` (or a new `meta.live_seq`
  the SPA diff also accepts) strictly increasing; set `meta.fetched_at`/`prices_as_of` to the price time.
- **Richer feed shape flows through unchanged:** still emits `FeedRow` incl. the `probability.py`-derived
  `cond_*`/`ev`/`breakeven` columns (uncalibrated · gross · never rank).
- **Per-leg freshness metadata (additive):** `price_source` (live|rest), `price_as_of`, `book_seq_ok`, plus
  row-level `all_legs_live`, `all_legs_active_confirmed`, `live_coverage`, `row_age_ms`, `min_top_book_size`.
- **Actionability stays REST-derived in 2C.** Live prices update displayed numbers + a "live" badge; the
  Actionable/Review/Blocked bucketing is not yet live-driven. UI label: "Live gross top-of-book — not an
  executable guarantee."

### Stage 2D — live actionability (only after 2A–2C pass)
Allow live-derived rows into ranking, gated by **pre-detector data-quality blocks** (freshness/quality
fields consumed *before* the unchanged detectors):
- **Block from Actionable** any row with a **mixed-stale** leg, a **desynced** book, a leg whose **status is
  not live-confirmed active**, an **unsubscribed/uncovered** leg, or **stale structure**. Degrade to a
  labeled `review-only`/`stale-price candidate`, never silent.
- **Market status freshness:** subscribe to the **lifecycle/ticker status** channel; a row is Actionable
  only if every leg is `active` per a live-confirmed (or very recent) status.
- **Structure staleness:** track `structure_as_of`/`structure_source_snapshot_id`/`structure_age`; block
  live actionability when structure is stale/failed.
- **Market disappearance:** on each REST generation, diff old vs new ticker universe → unsubscribe removed
  tickers, delete cache entries, invalidate rows using them, push the removal.

### Persistence, races, lifecycle (solved by the memory-push design)
- Live feed pushes the SPA **from memory**; it does **not** persist every tick. The store keeps getting
  periodic **REST** snapshots, plus throttled **live checkpoints** (every N s or on a **material state
  transition** only). Min-persistence-before-"new actionable", `source=live` interval tagging, alert-storm
  suppression are part of the policy.
- **One store writer:** serialize REST + live-checkpoint writes through a single lock; bind every live
  checkpoint to its `structure_generation_id`; **drop** a live checkpoint if a newer REST snapshot landed.
- **Debounce:** dirty-flag + single `LIVE_DEBOUNCE_SECONDS` (~0.4 s) timer + a `LIVE_MIN_RECOMPUTE_SECONDS`
  floor. **Benchmark first** (`scripts/benchmark_scan.py`): recompute/feed-build/write duration, DB growth,
  backlog churn, browser render — tune from data, don't assume 1.5 s.

### Subscription planning / coverage honesty
Universe = `market_ticker`s in the latest snapshot's `contracts` frame (`scanner.py:590-593`). **Tier 1
(always):** every leg of any Actionable/Review/risk_budget/near_miss row **plus its ladder/MECE peers**.
**Tier 2 (capped):** the rest up to `LIVE_MAX_SUBSCRIPTIONS`; beyond the cap, REST-only. Surface coverage
(`/coverage` + label "Live mode covers X/Y markets; others update on REST scan only") + a per-row
`live_coverage` flag — uncovered rows are **not** ranked as if live.

### Config + credential safety (default OFF, fail-hard)
- `config.py`: `LIVE_FEED_ENABLED=False`, `LIVE_WS_URL="wss://external-api-ws.kalshi.com/trade-api/ws/v2"`,
  `LIVE_DEBOUNCE_SECONDS`, `LIVE_MIN_RECOMPUTE_SECONDS`, `LIVE_MAX_SUBSCRIPTIONS`, `LIVE_STALE_AFTER_SECONDS`,
  `LIVE_CHECKPOINT_SECONDS`.
- Env (read in `serve.py`): `KALSHI_LIVE_ENABLED=1`, `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`.
- `live_feed_safety()` — **fail-hard `SystemExit`**, extending the existing startup guards (bind guard +
  auth-mode `WEB_CONCURRENCY>1` fatal, `docs/AUTH.md:129`) — if live is enabled and: key id/file
  missing/unreadable; key file world-readable; or `WEB_CONCURRENCY>1` (covers the AUTH-disabled-but-live
  case). Banner: "app now holds Kalshi **exchange** credentials."
- **Credential hygiene:** never log/echo the key; `*.pem`/`.env` gitignored; commented placeholders in
  `deploy/.env.example`; restrict key-file perms like `auth.db`. **Read-only guarantee:** the live module
  imports/calls **no** order/portfolio/trading endpoints — enforced by a test; prefer a least-privilege key;
  document rotation/revocation.

## Files
| Action | Files |
|---|---|
| **New modules** | `events.py` (bounded pub/sub + cross-thread bridge); `live_feed.py` (WS auth, order-book builder, seq/resync, status, price cache, overlay, debounce, checkpoints) |
| **Additive edits** | `scan_manager.py` (`on_complete` hook); `api.py` (SSE endpoint w/ `presence.touch`, lifespan loop-capture, `/metrics`+`/coverage` live fields, back `/orderbook` from live cache); `serve.py` (env reads, `live_feed_safety`, lifespan start/stop of `live_feed`); `fetch.py` (capture raw events); `webui/feed.py` (`build_feed_from_unified` split + monotonic-id stamp + freshness fields); `config.py` (`LIVE_*`); `frontend/src/context.tsx` (EventSource + fallback + freshness/coverage badges) + a new `*.test.ts`; `requirements.txt` (`websockets`, `cryptography`); `deploy/.env.example` |
| **Reused unchanged** | `data.build_contracts`, `scanner.unified_opportunities` + `_to_unified_*`, `consistency`/`dutchbook`/`synthetic_bundle`, `store.write_snapshot`, `kalshi_client.get_orderbook` + `TerminalOrderbook` + `Ladder.tsx`, `auth.gate_and_harden`, `scan_scheduler` (REST fallback) |

## Verification
- **Stage 1 tests:** SSE named-event, bounded/slow client, fallback, build-once, presence-touch, route-gated.
- **Stage 2 unit (no live socket — fixture WS messages):** `orderbook_snapshot` builds full book; delta
  add/update/remove changes top-of-book; missing `seq` blocks actionability + triggers resync; default
  NO-leg pricing cannot invert, `use_yes_price:true` normalizes; YES/NO ask + sizes derived from opposite
  bids; empty book ⇒ `0.00/1.00`; **parity** (REST vs live overlay ⇒ identical `unified_opportunities`);
  RSA `_sign()` deterministic vs a known test key+timestamp; cross-thread `publish` reaches a queue.
- **Stage 2 safety tests:** mixed live+stale leg ⇒ not Actionable; closed/inactive market ⇒ blocked;
  over-cap market labeled + not live-ranked; older live checkpoint cannot overwrite newer REST snapshot;
  cadence doesn't blow up DB/backlog; reconnect resubscribes + rebuilds + blocks until synced;
  market-disappearance invalidates rows; **default-off ⇒ no WS connect, app byte-for-byte as today**;
  **credential safety ⇒ no trading endpoints imported/called**.
- **Existing detector suite passes with zero edits** (`test_scanner`/`test_dutchbook`/`test_consistency`/
  `test_synthetic_bundle`/`test_feed`).
- **End-to-end:** `pytest -q`; `ruff check .`; `cd frontend && npm run build && npx vitest run`; boot
  `serve.py` with `KALSHI_LIVE_ENABLED=1`+key → `/healthz`/`/readyz` 200, open `/`, confirm rows update +
  live badges on a real price move, and an open SSE stream keeps the idle-gated scanner alive; boot OFF →
  today's polling unchanged. Branch-only delivery off the current scanner branch (re-verify, see top).

## Out of scope (seeds)
- WS-driven market **discovery** (REST stays discovery authority; new markets appear on next REST scan).
- Per-sport/per-group **incremental** recompute (v1 = full pass, bounded by debounce+floor+benchmark).
- Modeling fees/depth/queue (still gross top-of-book — labeled, not modeled).
