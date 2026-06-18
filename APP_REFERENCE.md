# APP_REFERENCE.md — Kalshi Visualizer (comprehensive reference)

> A single, self-contained reference to the **Kalshi Visualizer** app: what it is, how it is
> structured, every module and endpoint, the detection engine, the React SPA, the legacy NiceGUI
> dashboard, authentication, deployment, configuration, and tests. Written to be handed to an
> external assistant (e.g. a ChatGPT project) as ground truth.
>
> **Snapshot:** branch `feat/scanner-bugfixes`, commit `4e3d285`, 2026-06-18. Where this document
> and the code disagree, the code wins — verify against the repo. Config numbers below are quoted
> directly from `config.py` (authoritative); some prose docs (`README.md`, `docs/STATUS.md`) predate
> the auth feature and still say "no authentication" — that is stale (auth is now in scope and shipped).

---

## 1. What the app is

A small, **read-only** trader dashboard over **live [Kalshi](https://kalshi.com) prediction-market
data**. It does not place orders, hold positions, or model probabilities. It surfaces two classes of
**gross, top-of-book pricing opportunity** across a participant's related contracts and ranks them
best-first into **Actionable / Review / Blocked**.

It covers **10 sports**: tennis (ATP/WTA), NBA, WNBA, golf, soccer (World Cup), MLB, NHL, motorsport
(F1/NASCAR/IndyCar/MotoGP), NFL, and esports (CS2/LoL/Valorant/Dota2/CoD/R6/…).

### The two primary detectors

1. **Layer-consistency violations (containment ladder).** A *deeper* outcome must never price above a
   *broader* prerequisite that contains it. Example tennis ladder (broad → deep): *Reach Semifinal ⊇
   Reach Final ⊇ Win Tournament*. If a child's firm YES bid exceeds the parent's firm YES ask (with
   size behind both), that is an **executable inconsistency**. Framed buy-only: **Buy YES** on the
   broader leg, **Buy NO** on the deeper leg.
2. **Dutch-book / MECE edges.** A mutually-exclusive-and-exhaustive set of binary markets whose every
   outcome can be bought for less than the guaranteed payout floor. Two directions, both buys:
   **underround** (Buy YES all, `Σ yes_ask < 100¢`), **overround** (Buy NO all,
   `Σ no_ask < (n−1)·100¢`).

A third, **review-only** family: the **synthetic exact-score bundle** (`synthetic_bundle.py`) —
replicates "this player wins their match" from the MECE set of set-scores, priced against two
independent hedges. Because an exact score settles differently from a match winner on a retirement,
every finding is settlement-caveated and never routed Actionable.

### Hard product rules (do not regress — from `CLAUDE.md`)

- **Read-only**: no trading, no order placement, no conditional-probability/de-vig model in the SPA
  (the legacy NiceGUI `/dashboard` has an owner-approved de-vig panel; the **SPA stays display-only**).
- **Conservative wording**: findings are "executable inconsistencies" / "gross pricing discrepancies",
  **never** "arbitrage", "riskless", "locked", or "true arbitrage".
- **Gross & top-of-book**: every edge is an upper bound. Three costs are **documented but not
  modeled** — fees, position limits/collateral, full-depth execution. Fees have a **display-only**
  estimate that **never** drives ranking, bucketing, or actionability.
- **Exact integer cents** for all comparison logic (`data.to_cents`, `Decimal`); floats are
  display-only.
- **Per-sport `SportConfig` drop-in** is the only sanctioned way to add a sport. Adding non-sport
  features needs explicit owner approval.

---

## 2. Two UIs, one engine

Both UIs are read-only views of the same engine and the same SQLite snapshot.

| Surface | Path | Tech | Status |
|---|---|---|---|
| **Kalshi Structured Scanner (React SPA)** | `/` (also `/terminal`) | React 18 + Vite + TypeScript | **Default UI** |
| Legacy dashboard | `/dashboard` | NiceGUI on FastAPI | Retained read-only fallback |
| REST API | `/healthz`, `/readyz`, `/opportunities`, `/api/terminal/*`, … | FastAPI | Serves both UIs |

The SPA reads the engine **solely** through `GET /api/terminal/feed` (+ thin `/api/terminal/*` parity
views). `frontend/dist` is a **gitignored build artifact**: until it is built, `/` is simply unmounted
and boot never breaks. The legacy Streamlit `app.py` was retired.

---

## 3. Architecture & data flow

```
                         Browser
        ┌───────────────────┴───────────────────┐
   React SPA (frontend/dist at /)        NiceGUI dashboard (/dashboard)
        │  GET /api/terminal/*                   │  in-process (webui.engine)
        └───────────────────┬───────────────────┘
                            ▼
              FastAPI app  (serve.py mounts api.py + NiceGUI + SPA on ONE app)
                            │
   auth gate (auth.py)  ·  middleware (TrustedHost, GZip)  ·  scan_manager / scheduler / presence
                            │
            ┌───────────────┼───────────────────────────┐
            ▼               ▼                           ▼
      store.py         scanner.py                  kalshi_client.py
   (SQLite snapshots)  unified_opportunities()     (read-only paginated GET,
            │           │   ├ consistency.build_checks   process-wide throttle,
            │           │   ├ dutchbook.find_dutch_books  429 backoff)
            │           │   ├ synthetic_bundle / no_structures / …
            │           │   └ fetch.fetch_contracts → data.build_contracts
            ▼           ▼
   lifecycle.py    sports.py  (SportConfig registry; sport_for_series)
   (snapshot diffs)
```

**One scan, end to end:**
1. `scan_scheduler` (background timer) or `POST /scan` or the dashboard button triggers
   `scan_manager.ScanManager` (a process-local **singleflight** with TTL/budget/cooldown guards).
2. `scanner.unified_opportunities(fetch_fn, store_writer=…)` runs per sport:
   `fetch.fetch_contracts` → `data.build_contracts` (flatten events→markets→per-participant rows) →
   `consistency.build_checks` (ladder) + `dutchbook.find_dutch_books` + synthetic / NO-structure /
   group-basket / qualifier detectors.
3. Rows are normalized onto `scanner.UNIFIED_COLUMNS`, stamped with `sport`, ranked by
   `BUCKET_PRIORITY` → gap size → `opportunity_id`, and written to the SQLite store via
   `store.write_snapshot`.
4. `lifecycle.py` diffs the new snapshot against the previous (new-actionable, blocked-change,
   recently-actionable).
5. On completion, `scan_manager.on_complete(snapshot_id)` publishes an SSE event (`events.py`) to all
   open `/api/terminal/stream` subscribers; the SPA repaints instantly. NiceGUI polls
   `store.latest_snapshot_id()` (~1s) and re-renders when a new id lands.

**Process-local invariant:** the Kalshi throttle, the snapshot store, the scan manager, presence, and
the rate limiters are all **per process**. Run **one** worker; `WEB_CONCURRENCY>1` is warned (and
fatal under auth). Aggregate Kalshi rate = `MAX_RPS × process count`.

---

## 4. Backend module map (top-level Python)

UI-free, independently testable pure-logic modules (no `nicegui`/`streamlit` import): `sports.py`,
`data.py`, `consistency.py`, `dutchbook.py`, `synthetic_bundle.py`, `glossary.py`, `filters.py`,
`viz.py`, and the other detectors.

### Core configuration & sport abstraction

- **`config.py`** — all tuning constants (read-only, import-free by convention; env overrides are read
  at the boundaries that consume them, never here). See §11 for the full value table.
- **`sports.py`** — the multi-sport abstraction. Imports only `config` + stdlib.
  - `IdentityResult` (dataclass): `participant_key`, `display_name`, `confidence`
    (`high`/`low`/`none`), `source_field`, `raw_value`, `reason`.
  - `IdentityResolver`: tries dotted `candidate_paths` (e.g. `custom_strike.tennis_competitor`) for a
    stable UUID; falls back to normalized display name (low confidence). Optional `id_validator` marks
    a present-but-non-id value low (e.g. motorsport constructor *name*).
  - `MarketClassification`: `family`, `stage`, `stage_rank`, `ladder_node`,
    `eligible_for_ladder_checks`, `confidence`, `reason`.
  - `LadderSpec`: `node_order` (broad→deep rungs), `adjacent_pairs` (child,parent), `match_stage_to_node`,
    `advance_stage_to_node`, `simultaneous` (finishing-position vs sequential), `node_survivors`.
  - `SportConfig` (dataclass): `sport_id`, `label`, `emoji`, `series_prefixes`, `default_series`,
    `winner_tickers`, `identity`, `ladder`, `family_fn`, `stage_fn`, `node_fn`, `state_bundles`
    (exact-score), `score_format_fn`, `winner_label`, etc. Most callbacks are **defaulted** (empty for
    non-tennis).
  - Registry functions: `register(cfg)`, `all_sports()`, `get_sport(sport_id)`,
    `sport_for_series(ticker)` (exact → prefix → winner-ticker priority; unknown → explicit `UNKNOWN`,
    **never** a silent tennis default), `extract_round(patterns, *texts)`.

### Data acquisition & parsing

- **`kalshi_client.py`** — thin read-only HTTP client. `KalshiError`. Functions: `get_paginated(path,
  params, list_key)` (loops `cursor`, raises at `MAX_PAGES` with cursor pending), `get_events(series,
  status="open")`, `get_orderbook(ticker, depth=10)`, `discover_series_for_sport(cfg)`,
  `discover_tennis_series()`, `get_series_meta(tickers)` (`{ticker:{title,fee_type,fee_multiplier}}`),
  `get_events_for_series(tickers)` (parallel fan-out with retry), `get_event_fee_overrides()`.
  Process-wide counters: `request_count()`, `reset_request_count()`, `retry_stats()`. A process-wide
  `_throttle` caps issuance at `MAX_RPS`; `_get` backs off on 429/5xx (honors `Retry-After` when
  present) via `MAX_RETRIES`/`BACKOFF_*`.
- **`fetch.py`** — `fetch_contracts(families, scan_all, sport_id) -> (df, fetched_at, errors,
  n_scanned, n_loaded, skipped_no_name, n_excluded_unknown, fee_rates)`. **Fetch by family**: only the
  series whose contract family is enabled are fetched (`data.non_other_families` / `series_for_families`)
  — family toggles are the only control that changes what is fetched. Hosted scan path uses each
  sport's core series (`scan_all=False`).
- **`data.py`** — pure parsing & the per-participant contract index.
  - `to_float(v)` (None-safe; `""`→None), `to_cents(v)` (exact `Decimal`→int; e.g. `"0.37"`→37) —
    **never `float()` a raw price field**.
  - `display_prob` / `display_cents` (mid if spread reasonable, else last, else blank);
    `quote_quality(bid,ask)` → Tight/OK/Wide/Very wide/One-sided/No quote/Crossed.
  - `build_contracts(series_ticker, events, series_title="")` — the **core flattener** → per-participant
    rows with identity (`player`, `player_key`, `player_key_source`, `mapping_confidence`,
    `mapping_reason`), classification (`tour`, `kind`, `category`, `contract`, `stage`, `stage_rank`,
    `opponent`, `tournament`, `tournament_source`), pricing (`*_pct`, `*_c` cents, `*_size`,
    `spread_cents`, `quote_quality`, `subpenny`), `volume`, `open_interest`, `status`, time fields,
    links (`kalshi_url`, `series`, `*_ticker`, `*_title`), `raw_*`, `rules_primary`.
  - `classify_kind`, `tour_of`, `display_player_name`, `tournament_of(competition, series, event,
    title) -> (tournament_key, source)` (**never-empty** key, season-scoped), `opportunity_id(*parts)`
    (deterministic 16-char sha1 prefix), `gate_stale_tradability(opps, age, stale_after)`.
  - `RULE_TOKENS` = ("ball has been played", "walkover", "retire", "withdraw", "forfeit", "cancel").

### Detectors

- **`consistency.py`** — the containment-ladder + match-alignment classifier.
  - `build_checks(df, risk_budget_max_loss_c=0)` — the **core consistency detector** (groups by
    `(player_key, tournament)`), emitting per-pair statuses and the buy-only plan
    (`action_1_side/leg/price_c`, `action_2_*`, `tradable_now`, `blockers`, `watchlist_note`).
  - `bucket_of(row)` (routing), `node_of`, `build_player_nodes`, `layer_spreads` (raw adjacent-pair
    pp/cents gaps), `expected_nodes` (expected-vs-found ladder), `devig_field_by_node`,
    `scenario_payoffs`, `duplicate_node_sources`.
  - `STATUS_GROUP`, `ACTION_STATUSES`, tennis back-compat aliases (`NODE_ORDER`, `ADJACENT_PAIRS`, …).
  - **Statuses:** `CLEAN`, `EXECUTABLE_VIOLATION` (the only "Broken"), `DISPLAY_VIOLATION` (Warning),
    `WIDE_QUOTE`, `MISSING_QUOTE`, `MISSING_LAYER`, `QUOTE_SIZE_MISSING`, `UNKNOWN_RELATIONSHIP`.
- **`dutchbook.py`** — MECE detector. `FixedSumProof`, `MeceProof`. `prove_mece` (soccer 3-way),
  `prove_field_mece` (winner field). Dispatch in `find_dutch_books(rows)`: soccer → `_detect_n_way`,
  winner fields → `_detect_field` (overround-only on priceable subset), else 2-way `_detect_pair`
  (`_is_two_way_row`: match family + `"game"` family; same-series guard). `find_group_baskets(rows)`
  for World Cup group qualifiers. Tie-capable games (NFL) gated on `_proves_fixed_sum`. Statuses:
  `EXECUTABLE_DUTCH_BOOK`, `EXECUTABLE_GROUP_BASKET`, `NEAR_MISS_DUTCH_BOOK`.
- **`synthetic_bundle.py`** — N-leg exact-score bundle vs 2 hedges (match + advance). Gates: format
  proven via `score_format_fn`, exhaustive, hedge present + round aligned, firm ask per leg. Every
  finding `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, `tradable_now="Review rules"`, review/blocked only.
  Status `EXECUTABLE_SYNTHETIC_BUNDLE`.
- **`no_structures.py`** — "Cheap bounded-loss NO fades" (speculative, opt-in, never actionable): BAND
  (Buy NO deeper + Buy YES broader, bounded max-loss) and OUTRIGHT (single cheap Buy NO) tiers.
- **`numeric_ladder.py`** — S2 numeric-strike ladders (Over/Under N). `parse_numeric_strike(row)` →
  `(direction "ge"/"le", strike)` from structured fields only (never subtitle). `build_numeric_ladders`.
  **Diagnostic-only — NOT wired to Actionable** (owner-gated behind an evidence gate).
- **`game_support.py`** — World Cup ask-implied support score (diagnostic flag; not a probability).
- **`exact_order.py`** — World Cup exact-order top-two bundle (diagnostic → review-only speculative when
  genuinely attractive).
- **`stage_elim.py`** — `KXWCSTAGEOFELIM` 7-bucket stage-of-elimination book (Review-only tail-sum).
- **`wc_groups.py`** — fail-closed World Cup group helpers (qualify/win-group/cardinality baskets).
- **`probability.py`** — pure de-vig transforms (used by the NiceGUI cond-prob panel, not the SPA).

### Cross-sport orchestration, storage, lifecycle

- **`scanner.py`** — `unified_opportunities(fetch_fn, store_writer=None, fetched_at=None,
  frames_out=None) -> (unified_df, per_sport_errors)`. Runs all detectors per sport, normalizes onto
  `UNIFIED_COLUMNS`, ranks by `BUCKET_PRIORITY` (`actionable`=0, `review_signal`=1, `blocked`=2, …),
  optionally persists. Helpers: `gross_roi_pct(gap, cost)`, `legs_of(row)`.
- **`store.py`** — SQLite snapshot store, `SCHEMA_VERSION = 4` (v4 adds the durable `backlog_intervals`
  7-day table). `write_snapshot(fetched_at, opportunities, frames=None, db_path=None) ->
  (snapshot_id, housekeeping_stats)`, `latest()`, `latest_snapshot_id()`, `latest_rows_by_id(ids)`,
  `snapshots_since(seconds)`, `actionable_history_since(seconds)`, `footprint_stats()`,
  `db_writable()`. WAL mode, `auto_vacuum=INCREMENTAL`, throttled incremental vacuum + WAL truncate in
  post-commit housekeeping; opportunity/frame tiering keeps history bounded.
- **`lifecycle.py`** — snapshot diffs: `new_actionable(prev, cur)`, `first_seen`,
  `persisting_new_actionable(history, window_s)`, `blocked_change(prev, cur)`,
  `recently_actionable(snapshots)`, `recently_actionable_from_actionable_history(...)`.

### Runtime, scan control, presence, rate limiting, SSE

- **`serve.py`** — the entrypoint (`python serve.py`). Mounts FastAPI API + NiceGUI dashboard + the
  built SPA on **one** app. Applies secure defaults (auth on), seeds first admin from env, enforces
  `bind_safety`, starts the auto-scan scheduler behind a presence gate, runs uvicorn.
- **`scan_manager.py`** — `ScanManager` singleflight. `trigger(run_fn, write_fn, force, wait_timeout,
  db_path)`. Guards (all `force`-overridable): singleflight, budget cooldown, TTL. Status ∈
  {idle, in_progress, done, skipped, error} with `reason`, `last_snapshot_id`, `cooldown_seconds_left`.
  `on_complete` hook publishes SSE.
- **`scan_scheduler.py`** — process-wide background loop. `start(scan_fn, gate=None)`,
  `set_interval`, `set_enabled`. The gate is the presence/idle predicate.
- **`presence.py`** — viewer presence. `connect`/`disconnect` (NiceGUI), `count()`, `touch()` (SPA
  feed poll heartbeat), `recently_active(window_s)`, `reset()`.
- **`ratelimit.py`** — `SlidingWindow(max_events, window_s)`: `allow(now)`, `is_stale(now)`, `reset()`.
  Used for HTTP `/scan`, login, per-user actions, and the orderbook fetch.
- **`events.py`** — process-local SSE pub/sub broker. `set_loop(loop)`, `subscribe()` (bounded
  `asyncio.Queue`), `publish(payload)` (thread→loop bridge, coalesce-to-latest backpressure),
  `unsubscribe(q)`, `subscriber_count()`, `dropped_count()`, `reset()`.

### Glossary / filters / viz

- **`glossary.py`** — single source of truth for plain-English help. `GLOSSARY{short,long}`,
  `BLOCKERS` (templated why-not-tradable), `KNOWN_LIMIT_*`, `DUTCH_BOOK_BASIS`, `COLUMN_HELP`,
  `help_for(column_label)`.
- **`filters.py`** — the two-pass split. `apply_membership(df, …, min_volume=0)` narrows **every**
  section; `apply_thresholds(df, min_edge_c, min_size, quote_mode, status_mode)` spares **Actionable**
  but gates the rest. `QUOTE_MODES`, `STATUS_MODES`.
- **`viz.py`** — pure tidy chart frames: `payoff_chart_data(pay)`, `ladder_prices(chain_rows)`.

---

## 5. Sports configuration matrix

Identity is `custom_strike.<key>`; classification is an **allow-list** (`family_fn`), not a bare
prefix. Grouping is by `(player_key, tournament)`; the tournament key is season-scoped so co-loaded
seasons never form a false cross-season ladder. Tournament is a **client-side filter**, not a fetch
gate — all events for a sport are loaded and the user narrows in the UI.

| Sport | Series ownership | Identity UUID | match_family | Ladder (broad → deep) / dutch-book shape |
|---|---|---|---|---|
| **Tennis** 🎾 | `KXATP*`, `KXWTA*`, `KXITF*` | `tennis_competitor` | `match` | Reach SF ⊇ Reach Final ⊇ Win Tournament; head-to-head matches + synthetic exact-score bundles |
| **NBA** 🏀 | `KXNBA*` | `basketball_team` | `match` (series) | Reach Playoffs ⊇ Win Conference ⊇ Win Championship; `KX*GAME` games |
| **WNBA** 🏀 | `KXWNBA*` | `basketball_team` | `match` (series) | Reach Playoffs ⊇ Reach SF ⊇ Reach Finals ⊇ Win Championship; games |
| **Golf** ⛳ | exact (`KXPGATOP5/10/20`, `KXPGATOUR`) | `golf_competitor` | `""` | Top20 ⊇ Top10 ⊇ Top5 ⊇ Win; **winner-field overround only** (no dutch books) |
| **Soccer** ⚽ | exact (`KXWCGAME`, `KXWCROUND`, `KXWCGROUPQUAL`, dormant `KXWC*` outright) | `soccer_team` | `""` (3-way) | RO32(=group qualifier) ⊇ RO16 ⊇ QF ⊇ SF ⊇ Final ⊇ Win the World Cup; 3-way Home/Away/Tie games + group baskets + stage-of-elim + exact-order diagnostics |
| **MLB** ⚾ | `KXMLB*` allow-list | `baseball_team` | `""` | Reach Playoffs ⊇ Win League ⊇ Win World Series; `KXMLBGAME` games. `KXMLBSERIES` excluded (non-MECE: can tie 2-2) |
| **NHL** 🏒 | `KXNHL*` allow-list | `hockey_team` | `match` | Reach Playoffs ⊇ Win Conference ⊇ Win Stanley Cup; `KXNHLSERIES` (clean bo7) + `KXNHLGAME` |
| **NFL** 🏈 | `KXNFL*` allow-list + `KXSB` | `football_team` | `""` | Reach Playoffs ⊇ Win Conference ⊇ Win Super Bowl; `KXSB` winner-field overround; `KXNFLGAME` games **tie-gated** (`game_mece_by_shape=False` + `_proves_fixed_sum`) |
| **Motorsport** 🏁 | `KXF1`/`KXNASCAR`/`KXINDY`/`KXMOTOGP` | driver/team UUID or constructor **name** | `""` | field sport like golf; one-winner FIELDS → overround; Top-N/Podium → finishing-position ladder; grouped per race instance; `player_key` role-namespaced |
| **Esports** 🎮 | exact allow-list (CS2/LoL/Valorant/Dota2/CoD/R6/…) | `esports_competitor` | `""` | **no ladder (v1)**; `KX*GAME`+`KX*MAP` draw-free → ungated 2-way dutch books; per-title winner series → overround. Total-maps/qualifiers/props/legacy/majors → `other` |

`UNKNOWN` sport is excluded from detection and never fetched.

---

## 6. Pricing model & quote quality

- **Display %** = YES midpoint when the bid/ask spread is reasonable (`SPREAD_REASONABLE = 0.20`),
  else last trade, else blank. A `0.00/1.00` book is **"No quote"**, never a fake 50%.
- Components always surfaced: YES mid / Last / YES bid / YES ask / Spread ¢.
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote / Crossed.
- **NO-side** read directly (`no_bid_dollars`/`no_ask_dollars`); `no_ask == 1 − yes_bid` on the unified
  book. **No NO-side size fields** — a Buy-NO leg's tradable size is `yes_bid_size`; fallback Buy-NO
  cents = `100 − yes_bid_c` when `no_ask_c` is absent.
- **Executable vs display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
  positive sizes**; a missing display blocks only the display test.

---

## 7. Kalshi API facts (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`); keys only matter for trading (out of
  scope). Hierarchy: **Series → Event → Market(outcome)**. Paginate via `cursor` until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `*_size_fp`; `volume_fp`, `open_interest_fp`. An empty
  book is `0.00/1.00`.
- **Market `status`** (`active`/`finalized`/`settled`/…): only `active` is tradable → drives
  `tradable_now`. `get_events` passes `status="open"`, so fully closed events are excluded.
- **Web URL:** `https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`, `slug =
  data._slugify(series.title)`.
- **Identity:** the stable `custom_strike.*` UUID is the per-sport join key; `yes_sub_title` is the
  display name.

### Tennis series quick map

| Series | Meaning | kind |
|---|---|---|
| `KXATPMATCH` / `KXWTAMATCH` | match winner (head-to-head) | `match` |
| `KXITFMATCH` / `KXITFWMATCH` | ITF lower-tour match winner | `match` |
| `KXATPADVANCE` / `KXWTAADVANCE` | reach a stage | `advance` |
| `KXFOMEN` / `KXFOWOMEN` | win the tournament | `winner` |
| `KXATPEXACTMATCH` | exact match score | `exact_score` |
| `KXATPSETWINNER` / `KXWTASETWINNER` | set winner | `set_winner` |

---

## 8. REST API (`api.py` / `serve.py`)

All non-public routes are gated by `auth.gate_and_harden` (deny-by-default when `AUTH_ENABLED=1`);
`TrustedHostMiddleware` validates Host; `GZipMiddleware` is optional (`FEED_GZIP_ENABLED`). Routes are
registered before the SPA catch-all so explicit routes win.

### Liveness / readiness / monitoring

| Method | Path | Auth | Returns | Notes |
|---|---|---|---|---|
| GET | `/healthz` | — | `{"status":"ok"}` | liveness |
| GET | `/readyz` | public (detail redacted for anon) | `ReadyZ` | 200 ready/degraded, 503 not_ready (DB writable + fresh snapshot) |
| GET | `/metrics` | ✓ | `Metrics` | low-cardinality monitoring (scan health, SSE subscribers, DB footprint, viewer count) |
| GET | `/coverage` | ✓ | `Coverage` | latest snapshot scan counts/errors/metadata |

### Opportunities / lifecycle / alerts

| Method | Path | Query | Auth | Returns |
|---|---|---|---|---|
| GET | `/opportunities` | `sport`, `bucket`, `status` | ✓ | `list[Opportunity]` |
| GET | `/opportunities/{id}` | — | ✓ | `Opportunity` (404 if not in latest) |
| GET | `/backlog` | `window_s` (default 3600) | ✓ | `list[BacklogItem]` (short live view) |
| GET | `/backlog/events` | `days` (7), `category`, `include_open` (true) | ✓ | `list[BacklogInterval]` (durable 7-day) |
| GET | `/alerts` | `persistence_s` | ✓ | `Alerts` (new-actionable + blocked transitions) |

### Scan control

| Method | Path | Query / headers | Auth | Returns | Status |
|---|---|---|---|---|---|
| POST | `/scan` | `force`, `wait`; `X-Scan-Token` if `SCAN_TOKEN` env set | token/✓ | `ScanStatus` | **202** |
| GET | `/scan/status` | — | ✓ | `ScanStatus` | 200 |

HTTP-layer rate limit: `SCAN_HTTP_MAX_PER_WINDOW` (10) per `SCAN_HTTP_WINDOW_SECONDS` (60) → 429. The
dashboard "Scan now" calls the engine in-process and bypasses this.

### Terminal SPA feeds (`/api/terminal/*`)

| Method | Path | Query / body | Returns |
|---|---|---|---|
| GET | `/api/terminal/feed` | — | denormalized snapshot view (`{meta, opps}`); touches presence |
| GET | `/api/terminal/stream` | — | SSE push of the feed on scan completion + keepalives |
| GET | `/api/terminal/detail` | `sport`, `player_key`, `tournament` | `TerminalDetail` (chain, indicators, spreads, contracts, raw fields, rules) |
| GET | `/api/terminal/payoff` | `opportunity_id` | `TerminalPayoff` (per-state scenarios + cost) |
| GET | `/api/terminal/ladder` | `sport`, `player_key`, `tournament` | `TerminalLadder` |
| GET | `/api/terminal/diagnostics` | — | `TerminalDiagnostics` (OPS grids, ≤2000 rows + truncation count) |
| GET | `/api/terminal/telemetry` | — | `TerminalTelemetry` (liquidity/volatility; cached per snapshot) |
| GET | `/api/terminal/orderbook` | `ticker`, `depth` (1–100, default 10) | `TerminalOrderbook` (live book; 2s cache; rate-limited `ORDERBOOK_HTTP_*`) |
| POST | `/api/terminal/export` | body `ExportRequest` (`opportunity_ids`, `snapshot_id`) | ZIP (409 if no snapshot) |

### Auth (`/auth/*`)

| Method | Path | Body | Auth | Purpose |
|---|---|---|---|---|
| POST | `/auth/login` | username, password, remember | — | session login + optional remember-me |
| POST | `/auth/register` | username, password, remember | — | self-register if `AUTH_ALLOW_SIGNUP=1` (else 403) |
| POST | `/auth/logout` | — | session | clear session + revoke this device |
| POST | `/auth/password` | current, new | session | change password; bumps `session_epoch` (logs out other devices) |
| GET | `/auth/me` | — | session/token | current identity |
| GET | `/auth/config` | — | — | `{auth_enabled, remember_available, signup_enabled}` |
| GET | `/auth/devices` | — | session | trusted devices (remember-me tokens) |
| POST | `/auth/devices/{token_id}/revoke` | — | session | sign out one device |
| GET | `/auth/preferences` | — | session | stored prefs envelope |
| PUT | `/auth/preferences` | prefs | session | update (server-sanitized + size-capped) |

### `Opportunity` model (key fields — denormalized 2-leg/N-leg plan + display-only fields)

Identity/meta: `opportunity_id`, `sport`, `sport_label`, `source`, `name`, `detail`, `tournament`,
`tour`. Plan/economics: `action_1_text`, `action_2_text`, `action_1_price_c`, `action_2_price_c`,
`cost_c`, `exec_gap_c`, `exec_min_size`, `exec_max_profit_dollars`, `payout_floor_c`, `roi_pct`.
Edge class: `edge_class` (`strict`/`risk_budget`/`near_miss`), `worst_case_profit_c`,
`best_case_profit_c`. Display pricing (risk-budget, not executable): `parent_display_c`,
`child_display_c`, `display_spread_c`, `spread_over_parent`, `spread_over_child`. Firm quotes:
`parent_yes_bid_c`, `child_yes_ask_c`. Ladder labels: `child_node`, `parent_node`,
`comp_quote_quality`. Bucketing/status: `bucket`, `status`, `tradable_now`, `blocked_reason`,
`market_status`, `rule_flag`, `settlement_caveat`, `relationship_type`, `resolution_mode`
(`simultaneous`/`calendar`). NO-fade: `no_structure_scope`, `no_structure_close_time`,
`no_structure_faded_node`, `no_structure_faded_display_c`. Ladder triage: `ladder_steps`,
`ladder_bottom_c`, `ladder_step_ratio`. Links: `ticker_1`, `ticker_2`, `url`, `url_2`. N-leg:
`legs[]`, `n_legs`, `participant_keys[]`, `participant_labels[]`. World Cup qualifier / exact-order:
`setup_family`, `setup_type`, `qualifier_vs_top2_premium_c`, `synthetic_top_two_cost_c`,
`qualifier_yes_ask_c`, `ask_support_score_total_c`, `ask_support_score_per_game_c`, `join_confidence`,
`opportunity_class`, `top2_*`, `worst_bundle_quote_quality`, `wide_bundle_leg_count`,
`comparator_quote_quality`.

Other models: `Coverage`, `Metrics`, `BacklogItem`, `BacklogInterval`, `BlockedChange`, `Alerts`,
`ScanStatus`, `ReadyZ`, `TerminalDetail/Payoff/Ladder/Diagnostics/Telemetry/Orderbook`, `ExportRequest`.

---

## 9. React SPA (`frontend/`)

### Build tooling

- Vite 5.4 + React 18.3 + TypeScript 5.6; tests via Vitest 2.1; plugin `@vitejs/plugin-react`.
- Scripts: `npm run dev` (Vite on **:5180**, proxies `/api` → `127.0.0.1:8000`), `npm run build`
  (→ `frontend/dist`), `npm run preview`, `npm run test` (`npx vitest run`).
- `vite.config.ts`: base path `/terminal/`; `__APP_VERSION__` injected at build (git short SHA +
  date); strict port 5180. **Prod**: `npm ci && npm run build`, then `serve.py` serves `dist` itself.

### Source layout (`frontend/src/`)

- **Shell/state:** `main.tsx` (root), `App.tsx` (chrome: F-key surface bar, status line, tab bar,
  filter panel, tile grid, footer), `context.tsx` (`TerminalProvider` global state, no reducer),
  `AuthGate.tsx` (login/register/force-password-change wrapper + global 401 handler), `tokens.css`
  (design tokens; amber + high-contrast themes).
- **Workspace/panels:** `Workspace.tsx` (3-column drag-resize, 6 panel types, pop-outs, presets),
  `Blotter.tsx` (scanner table — plain HTML, capped 500 rows, zone/section tabs, column chooser,
  change badges, display-only sort), `Inspector.tsx` (trade card / participant detail / formulas
  tabs; economics, legs, conditional prob, fee scenarios), `Ladder.tsx` (live order book, ~5s poll;
  YES bids verbatim, YES asks = 100 − NO bids; leg & rung pickers), `SidePanels.tsx`
  (Watch + Alerts), `panels.tsx` (Compare / Don't-take-both overlap / multi-ladder), `Charts.tsx`.
- **UI:** `Keys.tsx` (Ctrl-K/`/`, 1-6 lenses, J/K nav), `Palette.tsx` (command palette),
  `MultiSelect.tsx`.
- **Data/API:** `http.ts` (`apiFetch` + global 401), `feed.ts` (feed types/loader; zone/section
  taxonomy), `stream.ts` (SSE + polling fallback after 3 errors), `scan.ts` (POST /scan + poll),
  `detail.ts` (detail/ladder/payoff/orderbook/diagnostics/backlog), `auth.ts`.
- **View logic:** `filters.ts` (membership vs threshold), `columns.ts` (6 catalogs: opp/risk/nm/no/qs/diag),
  `lens.ts` (sort lenses), `sort.ts`, `layout.ts` (presets + serialization), `prefs.ts`
  (hydrate/save per-user prefs).
- **Utilities:** `url.ts` (shareable filter URLs — NOT persisted as defaults), `csv.ts`, `diff.ts`
  (snapshot diff → new/up/down/returned), `alerts.ts`.
- **Tests:** `*.test.ts` for alerts, auth, columns, diff, filters, inspector, ladder, layout, prefs,
  sort, stream, url.

### UI features

- **Zones × sections:** EXECUTABLE (actionable/review/blocked), SPECULATIVE
  (risk_budget/near_miss/qualifier_setup/no_structure), DIAGNOSTIC (data_quality/display/wide/near_edge/clean).
- **Tiles:** ACTIONABLE, REVIEW, BLOCKED, BOUNDED-LOSS, CHEAP-NO, QUALIFIER, NEAR-MISS, DATA-QUALITY.
- **Cheap-NO scope subtabs:** All / Event / Tournament / Championship.
- **Lenses (sort only, never re-rank engine truth):** Blended (0.35·edge + 0.45·ROI + 0.2·spread),
  Edge¢, Spread, Outright+Spread, Implied EV, Ripeness, Setup quality.
- **5 layout presets:** default / triage / inspect / research / blotterfull.
- **Pop-outs:** independent OS window sharing the parent feed (single live-data source) but its own
  view state.
- **Text size:** page-wide selector (compact/normal/large/xlarge) + per-panel override; every
  `font-size` derives from `--fs` via `calc()`.
- **Two themes:** amber (default) + high-contrast.
- **Exports:** CSV (selected / view) client-side; ZIP via `POST /api/terminal/export` (filtered
  opportunity ids → `opportunities.csv` + per-sport frames + `manifest.json`).
- **Footer disclaimer:** "GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS ·
  fees est. only" + version string.
- **Persistence:** `GET /auth/preferences` on mount, debounced `PUT` (~600ms). Persisted: theme,
  settings (`longShort`, `showIds`, `resolutionCriteria`, `hideNetNegExec`, `textSize`, tz,
  autorefresh), showNet, columns per zone/section, bands, split, layoutPreset, layout. **Filters are
  NOT persisted** (shared/debug URLs must never become defaults).

---

## 10. Legacy NiceGUI dashboard (`webui/`)

The retained read-only fallback at `/dashboard`, mounted on FastAPI via `serve.py`. Pure cores
(`viewmodel.py`, `diagnostics.py`, `export.py`, `engine.py`, `feed.py`) are NiceGUI-free and
unit-tested.

- **`dashboard.py`** — the `@ui.page` shell: scope banner (freshness + scan metadata), membership
  filters (Sport/Tournament/Participant), threshold controls (min exec size, Active-only, Net-of-fees),
  Scan-now button, Export, per-table column menus; the ranked **Actionable** table (best→worst), then
  **Review**/**Blocked** (toggle-gated), opt-in Risk-budget / Near-miss, a recently-actionable backlog,
  a click-to-open explanation dialog + participant detail panel, and a collapsed Diagnostics & debug
  expander.
- **`viewmodel.py`** — pure presentation: `classify_changes`, `severity_badges`, `opp_display_row`,
  `risk_display_row`, `filter_by_membership` / `filter_by_threshold` (reuse the `filters.py` two-pass
  split), `filter_options`, URL-state roundtrip. **Status display labels:** `EXECUTABLE_VIOLATION`→
  "Actionable gross edge", `DISPLAY_VIOLATION`→"Display inconsistency", `WIDE_QUOTE`→"Wide quote /
  watchlist", `MISSING_QUOTE`→"Missing firm quote", `QUOTE_SIZE_MISSING`→"Blocked: no size",
  `CLEAN`→"Consistent".
- **`engine.py`** — in-process engine accessors (no self-HTTP): cached `latest_opportunities`,
  `opportunities_in_bucket`, `backlog`, `backlog_events`, `alerts`, `coverage`, `frames`,
  `participant_contracts`, `diagnostics`, `metrics`, `scan_status`, `payoff_for_opp`,
  `run_scan_now(force)`.
- **`diagnostics.py`** — pure observability builders: `build_readiness`, `build_metrics`,
  `build_failures`, `build_category_breakdown`.
- **`export.py`** — pure ZIP/CSV builder with **CSV formula-injection defense** (guards cells starting
  with `= + - @`, tab, CR): `build_export_zip(...)`, `build_basket_csv(opps)`.
- **`feed.py`** — `build_terminal_feed(db_path) -> {meta, opps}`: the SPA's only backend surface.
  Re-presents `store.latest()` through `viewmodel` builders; **never** re-derives
  bucket/status/tradable_now/rule_flag (copied verbatim), never feeds the scanner. Maps buckets → zones.

---

## 11. Configuration (`config.py`) — authoritative values

| Constant | Value | Meaning |
|---|---|---|
| `BASE_URL` | `https://external-api.kalshi.com/trade-api/v2` | Kalshi market-data base |
| `SPREAD_REASONABLE` | `0.20` | trust midpoint when spread ≤ this (dollars) |
| `DISPLAY_TOL_C` | `1` | ignore display gaps < this many cents |
| `NEAR_EDGE_MIN_C` | `-5` | near-edge watchlist band `[-5, 0]` |
| `RISK_BUDGET_MAX_LOSS_C` | `25` | widest bounded worst-case loss persisted |
| `NEAR_MISS_MAX_OVER_C` | `5` | widest dutch-book overpay persisted |
| `NO_STRUCTURE_BAND_MAX_LOSS_C` / `_OUTRIGHT_MAX_C` | `40` / `25` | cheap-NO fade caps |
| `MAX_RPS` | `15` | per-process Kalshi issuance cap (~75% of ~20/s Basic) |
| `CONCURRENCY` / `SPORT_FETCH_CONCURRENCY` | `4` / `4` | per-series fan-out / per-sport fan-out (4×4=16 = pool max) |
| `MAX_RETRIES` | `3` | attempts per request |
| `BACKOFF_BASE` / `BACKOFF_MAX` | `1.0` / `8.0` | exponential backoff seconds |
| `MAX_PAGES` | `100` | pagination safety cap (raises if hit with cursor pending) |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout seconds |
| `FEE_TAKER_BASE_COEFF` / `FEE_MAKER_BASE_COEFF` | `0.07` / `0.0175` | display-only fee coefficients |
| `STALE_AFTER_SECONDS` | `300` | snapshot staleness; downgrades `tradable_now` |
| `SNAPSHOT_DB_PATH` / `AUTH_DB_PATH` | `snapshots.db` / `auth.db` | separate SQLite files |
| `SNAPSHOT_RETENTION_SECONDS` | `6*60*60` (6h) | heavy snapshot retention |
| `BACKLOG_RETENTION_SECONDS` | `7*24*60*60` (7d) | durable interval backlog |
| `SNAPSHOT_FRAME_RETENTION_N` / `_DB_BUDGET_BYTES` | `12` / `~500 MB` | heavy-frame retention |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | bind defaults (loopback) |
| `SCAN_MIN_INTERVAL_SECONDS` | `8` | store-backed TTL guard |
| `SCAN_WAIT_TIMEOUT_SECONDS` | `60` | `?wait=true` join bound |
| `SCAN_BUDGET_MAX_SECONDS` / `_MAX_REQUESTS` / `_MAX_FAILED_SERIES` | `150` / `2000` / `20` | scan cooldown triggers |
| `SCAN_BUDGET_COOLDOWN_SECONDS` | `300` | cooldown after a blown budget |
| `SCAN_HTTP_MAX_PER_WINDOW` / `_WINDOW_SECONDS` | `10` / `60` | HTTP `/scan` rate limit |
| `ORDERBOOK_HTTP_MAX_PER_WINDOW` / `_WINDOW_SECONDS` | `30` / `10` | live orderbook rate limit |
| `AUTO_SCAN_INTERVAL_OPTIONS` | `[10,15,30,60,120]` | selectable cadences (s) |
| `AUTO_SCAN_DEFAULT_SECONDS` | `60` | server-safe default cadence |
| `AUTO_SCAN_DEFAULT_ENABLED` | `True` | auto-scan on by default |
| `AUTO_SCAN_PAUSE_WHEN_IDLE` | `True` | pause when no viewer (env `AUTO_SCAN_PAUSE_WHEN_IDLE=0` → 24/7) |
| `TERMINAL_PRESENCE_WINDOW_S` | `30` | SPA feed-poll = presence window |
| `SSE_KEEPALIVE_SECONDS` | `15` | SSE keepalive (< presence window) |
| `AUTH_SESSION_IDLE_SECONDS` / `_ABSOLUTE_SECONDS` | `2h` / `12h` | sliding idle / hard cap |
| `AUTH_LOGIN_MAX_PER_WINDOW` / `_WINDOW_SECONDS` | `5` / `60` | login rate limit per (ip,username) |
| `AUTH_LOCKOUT_THRESHOLD` / `_SECONDS` | `10` / `15min` | brute-force lockout |
| `AUTH_REMEMBER_MAX_AGE` | `30d` | remember-me token lifetime |
| `AUTH_MAX_CRED_LEN` | `256` | reject longer username/password before hashing |
| `AUTH_ARGON2_TIME_COST` / `_MEMORY_COST` / `_PARALLELISM` | `2` / `19456 KiB` / `1` | argon2id params (OWASP 2024) |
| `AUTH_PREFS_MAX_BYTES` / `_VERSION` | `32768` / `1` | prefs blob cap / envelope version |
| `AUTH_COOKIE_NAME` / `AUTH_REMEMBER_COOKIE_NAME` | `kss_session` / `kss_remember` | signed cookies (itsdangerous) |
| `TIMEZONE_DEFAULT` | `Europe/Lisbon` | display tz (never affects cents logic) |
| `FO_WINDOW` | `(2026-05-18, 2026-06-09)` | French Open fallback date window (**year-specific — update**) |

**Env overrides** are read at boundaries (never in `config.py`): `API_HOST`, `API_PORT`,
`SNAPSHOT_DB_PATH`, `AUTH_DB_PATH`, `NICEGUI_STORAGE_SECRET`, `APP_SESSION_SECRET`,
`ALLOW_DEV_STORAGE_SECRET_ON_LAN`, `AUTH_ENABLED`, `AUTH_ALLOW_SIGNUP`, `APP_ADMIN_USER`,
`APP_ADMIN_PASSWORD`, `APP_ALLOWED_HOSTS`, `ALLOW_ANY_HOST_ON_LAN`, `APP_TLS`, `TRUST_PROXY`,
`SCAN_TOKEN`, `FEED_GZIP_ENABLED`, `WEB_CONCURRENCY`, `AUTO_SCAN_PAUSE_WHEN_IDLE`,
`AUTO_SCAN_DEFAULT_SECONDS`, `SNAPSHOT_RETENTION_SECONDS`, and the store housekeeping flags.

---

## 12. Authentication (`auth.py`, `auth_store.py`, `manage_users.py`)

Per-user app-level login over the read-only surface, gated by `AUTH_ENABLED` (in scope since 2026-06;
must **never** alter engine logic). See `docs/AUTH.md`.

- **Separate SQLite** (`AUTH_DB_PATH`, default `auth.db`) so a snapshot-store reset can never touch
  credentials. Migration **fails hard** (corrupt/newer auth.db raises — credentials never silently
  dropped). argon2id hashing with pinned params + `needs_rehash` upgrade path.
- **Sessions:** signed cookie (`kss_session`, itsdangerous), sliding idle (`AUTH_SESSION_IDLE_SECONDS`)
  under an absolute cap; `SameSite=Strict`, httponly, Secure when TLS/proxy.
- **Remember-me:** rotating single-use device tokens (`selector:validator`), theft-detection revokes
  the family; "trusted devices" panel + per-device / global revoke.
- **Brute force:** per-(ip,username) login limiter → 429; lockout after `AUTH_LOCKOUT_THRESHOLD`
  failures for `AUTH_LOCKOUT_SECONDS` (CLI `unlock` clears early).
- **Preferences:** versioned envelope, **server-sanitized** (not trusted from client), size-capped;
  allowed-value sets single-sourced in `config.py` (`PREFS_THEMES`, `PREFS_LAYOUT_PRESETS`,
  `PREFS_COL_KEYS`, `PREFS_PANEL_IDS`, `PREFS_TEXT_SIZES`, …).
- **CLI:** `python -m manage_users {add|passwd|list|disable|enable|unlock} <username>`; first admin can
  be seeded from `APP_ADMIN_USER`/`APP_ADMIN_PASSWORD` (one-shot, forces password change on first login).
- **Bind safety** (`serve.bind_safety`): a non-loopback bind requires `NICEGUI_STORAGE_SECRET` (fatal
  otherwise, escape `ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`); auth-on non-loopback additionally requires a
  session secret, at least one user, TLS or proxy, and `APP_ALLOWED_HOSTS` (escape
  `ALLOW_ANY_HOST_ON_LAN=1`). `DASHBOARD_PUBLIC=1` leaves the NiceGUI `/dashboard` un-gated while the
  SPA stays gated.

---

## 13. Real-time live feed (experimental, default-off)

An approved, pushed-but-unmerged experiment (`docs/REALTIME_LIVE_FEED_PLAN.md`): Stage 1 SSE (shipped,
`events.py` + `/api/terminal/stream`) plus Stage 2 live WebSocket collector (`live_feed.py`) and
overlay (`live_overlay.py`). **Default-OFF** — armed via `KALSHI_LIVE_ENABLED=1` + an RSA key
(`KALSHI_LIVE_ACTIONABILITY=1` for the 2D actionability overlay). The merged/default app uses only the
SSE push of completed snapshots; the live WS layer is not in the default path.

---

## 14. Run, verify, deploy

```bash
pip install -r requirements.txt                          # requests, pandas, fastapi, nicegui, uvicorn, pydantic, argon2-cffi
cd frontend && npm ci && npm run build && cd ..          # build the default SPA → frontend/dist (gitignored)
python serve.py                                          # SPA (/) + NiceGUI (/dashboard) + REST API, one app
pip install -r requirements-dev.txt                      # pytest, pytest-asyncio, ruff, httpx, pip-audit, bandit
pytest -q                                                # pure layers + in-process engine/API + headless NiceGUI smoke
ruff check .                                             # lint
cd frontend && npx vitest run                            # frontend unit tests
```

- **Dev frontend:** `cd frontend && npm run dev` (Vite :5180, proxies `/api` → :8000) needs
  `python serve.py` running alongside, or every fetch fails. Not how prod runs.
- **Verify without a browser:** `pytest -q`; `python -c "import serve, api, webui.dashboard"`; a
  `serve.py` boot — `GET /` (SPA), `/dashboard/`, `/healthz`, `/metrics` → 200; `/readyz` →
  ready/degraded/not_ready. Live Kalshi calls, `pip`, and `git push` need the Bash tool with the
  sandbox disabled (network otherwise blocked).
- **LAN hosting / deploy:** `serve.py` serves API + dashboard + SPA on one app (default loopback).
  Full runbook + clean deploy artifact (`scripts/build_deploy_repo.py`, `deploy/` systemd templates):
  `docs/DEPLOYMENT.md`. **Server caches imported modules** — fully restart after editing a module (no
  auto-reload); for a phantom `ImportError`, clear bytecode (`rm -rf __pycache__ tests/__pycache__`).

### Scripts (`scripts/`)

`audit_series_coverage.py` (live catalog vs owned series), `benchmark_scan.py` (full scan-all
benchmark), `build_deploy_repo.py` (clean runtime-only artifact), `check_links.py` (deep-link
correctness + reachability), `compact_store.py` (one-time VACUUM + enable incremental auto_vacuum),
`export_glossary.py` (→ `docs/GLOSSARY.md` on demand), `probe_wc_qualifier_setups.py` /
`probe_wc_stage_of_elim.py` (offline fixture capture), `verify_e2e.py` (boots a throwaway server,
drives the full journey over real HTTP), `verify_fees.py` (fee cross-check), `verify_sport.py`
(load one sport live and report).

---

## 15. Tests (`tests/`, ~58 files)

Pure-first, deterministic (no network/clock by default; stubbed fetches, injected clocks, tmp stores,
offline JSON fixtures under `tests/fixtures/`). Areas: core layers (`test_store`, `test_scanner`,
`test_lifecycle`, `test_api`, `test_webui`), dashboard/UI (`test_viewmodel`, `test_browser` —
headless NiceGUI via `nicegui.testing`, no selenium — `test_export`, `test_diagnostics`,
`test_filters`, `test_serve`, `test_serve_spa`), auth/security (`test_auth`, `test_auth_store`,
`test_manage_users`, `test_security_regression`, `test_device_tokens`,
`test_routes_deny_by_default`), per-sport (`test_sports`, `test_nfl`, `test_mlb`, `test_nhl`,
`test_motorsport`, `test_esports`, plus World Cup `test_wc_groups`, `test_stage_elim`,
`test_wc_qualifier_tag`, `test_exact_order`, `test_game_support`), detectors (`test_consistency`,
`test_dutchbook`, `test_synthetic_bundle`, `test_beyond_strict_rule`, `test_bounded_loss_kind`,
`test_no_structures`, `test_ladder_closure`, `test_numeric_ladder`, `test_speculative_isolation`),
data/infra (`test_data`, `test_client`, `test_probability`, `test_ratelimit`, `test_scan_manager`,
`test_scan_scheduler`, `test_presence`, `test_readyz`, `test_stream`, `test_read_path_opt`,
`test_glossary`, `test_adapter_hooks`, `test_terminal_endpoints`), build (`test_build_deploy_repo`,
`test_audit_coverage`). Advisory security sweep: `pip-audit` (network) + `bandit` (offline), run in
verification, not a hard gate.

---

## 16. Docs index (`docs/`)

| File | Focus |
|---|---|
| `STATUS.md` | Shipped state, deliberately-not-modeled limits, approved next work |
| `AUTH.md` | Per-user auth: store schema, argon2, cookies, bind safety, security regression |
| `DEPLOYMENT.md` | Office-LAN hosting: systemd, scan timer, TLS proxy, deploy artifact, env vars |
| `DASHBOARD_COLUMN_GUIDE.md` | Every table/column meaning in the UI |
| `TERMINAL_SPA.md` | The React trader workstation (Terminal Pro) design + handoff |
| `REALTIME_LIVE_FEED_PLAN.md` | SSE + live WS/overlay plan (default-off) |
| `REVIEW_PROTOCOL.md` | Shared review protocol (plans, diffs, risk classes, verdicts) |
| `PR_CHECKLIST.md` | Required pre-merge checklist |
| `AGENT_WORKFLOW.md` | Day-to-day workflow for Claude Code / Codex / worktrees |

Repo-root reference docs: `CLAUDE.md` (authoritative code-structure + invariants), `README.md`
(overview), `AGENTS.md` (Codex guide). Build history lives in `.kss/`.

---

## 17. Glossary of key terms

- **Containment ladder** — broad→deep chain where a deeper outcome must price ≤ its broader prerequisite.
- **Executable inconsistency** — firm child YES bid > parent YES ask with positive sizes
  (`EXECUTABLE_VIOLATION`); the only "Broken" status. Never called "arbitrage".
- **Dutch book / MECE** — buy every outcome of a mutually-exclusive-exhaustive set under the payout
  floor (underround Buy-YES-all / overround Buy-NO-all).
- **Synthetic bundle** — replicate "player wins" from MECE set-scores vs two hedges; review-only,
  settlement-caveated.
- **Buckets** — `actionable`, `review_signal`, `blocked`, `risk_budget`, `near_miss`,
  `qualifier_setup`, `no_structure`, `data_quality`, `display_signal`, `wide_signal`, `near_edge`,
  `clean`.
- **Zones (SPA)** — EXECUTABLE / SPECULATIVE / DIAGNOSTIC groupings of the buckets.
- **Gross & top-of-book** — every edge is an upper bound; fees, position limits, and full-depth
  execution are documented but not modeled.
- **Mapping confidence** — `high` (stable competitor UUID) vs `low` (name fallback); stamped on every
  contract with a `mapping_reason`.
- **`tradable_now`** — "Yes" only for `EXECUTABLE_VIOLATION` with both legs `active`, no rule flag, and
  a fresh snapshot; downgraded to "No — stale snapshot" past `STALE_AFTER_SECONDS`.
