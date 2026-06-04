# CLAUDE.md

Guidance for **Claude Code** working in this repository. Self-contained — read top to bottom.

## Project

A **read-only** multi-sport (tennis/NBA/WNBA) **opportunity engine** over live [Kalshi](https://kalshi.com)
prediction-market data. It surfaces **executable inconsistencies** across a participant's related
contracts (a deeper outcome must not price above a prerequisite that contains it) and **dutch-book
arbitrage** on 2-outcome MECE events, framed as buy-only opportunities (**Buy YES / Buy NO**).

Two surfaces, both kept:

- **`app.py`** — the original per-sport **Streamlit** trader dashboard: sidebar controls, Actionable /
  Blocked / Near-edge sections, per-player detail, auto-refresh, full diagnostics. Streamlit-only.
- **`serve.py`** — the **FastAPI engine API + NiceGUI cross-sport dashboard**: REST API at
  `/opportunities`, `/backlog`, `/coverage`, `/alerts`, `POST /scan`, OpenAPI at `/docs`; cross-sport
  opportunity-first NiceGUI UI at `/`. Run with `python serve.py`.

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer` (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Multi-sport (shipped):** `sports.py` defines a `SportConfig` abstraction; tennis, NBA, and WNBA
  are registered sports. Adding a new sport = one `register(SportConfig(...))` call. `build_contracts`
  includes **all events for all registered sports**; containment ladders group by **(player_key,
  tournament)** per sport. Tournament is a client-side filter.
- **Scope guard — do NOT add unless explicitly asked:** trading, authentication, order placement,
  net-of-fees analysis (gross only), live Kalshi WebSocket feed (REST polling used), Streamlit retirement
  (deferred — `app.py` kept for now), conditional-probability/de-vig models. Adding a **new sport**
  is in scope via a `SportConfig` drop-in. The engine (SQLite store, scanner, lifecycle, FastAPI API,
  NiceGUI dashboard) is **built** — do not re-add or duplicate it.

## Run & verify

```bash
pip install -r requirements.txt          # runtime: streamlit, requests, pandas, fastapi, uvicorn, nicegui, pydantic
streamlit run app.py                     # original Streamlit per-sport dashboard
python serve.py                          # FastAPI engine API + NiceGUI cross-sport dashboard
pip install -r requirements-dev.txt      # adds pytest + ruff + httpx (for API tests)
pytest -q                                # unit tests for the pure layers (no network); ~235 tests
ruff check .                             # lint
```

To verify without a browser:
- `pytest -q` — full unit suite.
- `python -c "import app"` — Streamlit import check.
- Headless Streamlit: `streamlit run app.py --server.headless true --server.port 8765` → check `http://localhost:8765/_stcore/health` returns `200`.
- Headless engine: `python serve.py` → check `GET /healthz` returns `{"status":"ok"}`, `GET /` renders the NiceGUI dashboard, `POST /scan` triggers a scan.

Live Kalshi calls, `pip`, and `git push` in this environment require running the Bash tool with the sandbox disabled (network is otherwise blocked).

## Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Pagination via a `cursor` param — loop until it's empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `yes_bid_size_fp`/`yes_ask_size_fp`; volume `volume_fp`,
  `open_interest_fp`. An **empty order book is `0.00/1.00`** — never a real 50%.
- **NO-side prices exist** (`no_bid_dollars`, `no_ask_dollars`) and are read directly (the "Buy NO"
  price). On Kalshi's unified book `no_ask == 1 − yes_bid` exactly (verified live). There are **no
  NO-side size fields** — buying NO matches resting YES bids, so a Buy-NO leg's tradable size is
  `yes_bid_size`. `data._buy_no_c`-equivalent fallback is `100 − yes_bid_c` when `no_ask_c` is absent.
- **Market `status`** (`active`, `finalized`, `settled`, …) is the "tradable right now" signal — only
  `active` markets are open for trading; consistency uses it to set `tradable_now`.
- **Web URL format (verified live):** `https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`
  where `slug = data._slugify(series.title)` (e.g. `KXFOWOMEN` + "French Open Women's" →
  `…/kxfowomen/french-open-womens/kxfowomen-26`). Series titles come from `/series/<ticker>`
  (`kalshi_client.get_series_titles`); when a title is missing the link falls back to the series page.
- **Player identity:** `custom_strike.tennis_competitor` (stable UUID) is the join key across all series;
  `yes_sub_title` is the display name.
- **Tournament (not a filter gate anymore):** all tennis events are included; each is stamped with a
  never-empty `tournament` key via `data.tournament_of` (cleaned `competition` → winner-ticker → title
  keyword → `Unknown · <id>`). `is_french_open_event` still exists as a helper but no longer gates
  `build_contracts`. Match events are head-to-head (2 markets, `mutually_exclusive`); winner/advancement/
  set/score markets are single-sided (no opponent).

### Relevant per-player series (tennis)
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH` / `KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXATPADVANCE` / `KXWTAADVANCE` | reach a stage (`…-26FOSF`, `…-26FOFIN`) | `advance` | Stage advancement |
| `KXFOMEN` / `KXFOWOMEN` | win the tournament (1 market/player) | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER` / `KXWTASETWINNER` | set winner | `set_winner` | Set winner |

The women's winner title is the ugly "win the KXFOWOMEN-26?" → synthesize "Win the French Open".

**NBA/WNBA series** are fully configured in `sports.py` (`NBA` and `WNBA` `SportConfig` objects).
Tennis identity: `custom_strike.tennis_competitor` UUID. Basketball identity: `custom_strike.basketball_team` UUID.
Key NBA series: `KXNBA` (championship winner), `KXNBAEAST`/`KXNBAWEST`/`KXNBAPLAYOFF` (advance), `KXNBASERIES` (playoff series match), `KXNBAGAME` (per-game).
Key WNBA series: `KXWNBA` (championship), `KXWNBAPLAYOFF`/`KXWNBASEMIFINAL`/`KXWNBAFINAL` (advance), `KXWNBASERIES` (playoff series), `KXWNBAGAME` (per-game).

## Architecture

```
config.py          # All tunables: BASE_URL, DEFAULT_SERIES, thresholds, rate-limit (MAX_RPS/CONCURRENCY/
                   #   BACKOFF_*), refresh (REFRESH_TTL/OPTIONS/NEAR_EDGE_MIN_C), + engine knobs (SNAPSHOT_DB_PATH/
                   #   RETENTION, SCAN_MIN_INTERVAL, API_HOST/PORT, NICEGUI_STORAGE_SECRET_FALLBACK,
                   #   UI_REFRESH_SECONDS, BACKLOG_WINDOWS, ALERT_PERSISTENCE_OPTIONS). IMPORT-FREE (see Conventions).
sports.py          # NO streamlit: SportConfig registry (Tennis/NBA/WNBA); sport_for_series() → SportConfig
                   #   (UNKNOWN, never a silent tennis default); IdentityResolver/MarketClassification/LadderSpec;
                   #   add a sport = register(SportConfig(...)).
kalshi_client.py   # read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide throttle
                   #   (MAX_RPS), discover_tennis_series(), get_series_titles(), get_events_for_series().
data.py            # NO streamlit/pandas: parsing, to_cents(), classify_kind/tour_of, pricing helpers,
                   #   tournament_of(), series_for_families(), kalshi_market_url(), opportunity_id() (sha1),
                   #   build_contracts() (ALL events, all sports), fmt_time/data_age_seconds/is_stale.
consistency.py     # NO streamlit: build_checks (groups by [player_key, tournament]) + node/spread helpers;
                   #   buy-only action plan + tradable_now + blockers; bucket_of (dashboard routing).
dutchbook.py       # NO streamlit: find_dutch_books() — 2-outcome MECE arbitrage (match/series + per-game
                   #   "game" family); status EXECUTABLE_DUTCH_BOOK (see Dutch-book section).
glossary.py        # NO streamlit: GLOSSARY{term:{short,long}}, BLOCKERS, WATCHLIST_NOTE, help_for.
filters.py         # NO streamlit: apply_membership (tournament/family/layer/event/participant/volume) +
                   #   apply_thresholds (size/quote/market-status) — the two-pass filter split.
viz.py             # NO streamlit: payoff_chart_data + ladder_prices (tidy chart frames).
fetch.py           # NO streamlit: fetch_contracts(families, scan_all, sport_id) → 7-tuple. Extracted from
                   #   app.load_contracts so the engine fetches without Streamlit (app wraps it in a cache shim).
store.py           # NO streamlit/pandas: SQLite snapshot store — write_snapshot(…, meta, db_path), latest(),
                   #   latest_two(), snapshots_since(window). Versioned (PRAGMA user_version v2 + _migrate);
                   #   retention vs newest; NaN-safe; .db gitignored.
scanner.py         # NO streamlit: cross-sport aggregator — unified_opportunities(fetch_fn, *, store_writer,
                   #   fetched_at) ranks build_checks + find_dutch_books across all_sports() onto
                   #   UNIFIED_COLUMNS; run_scan(...) adds coverage. Fetch injected; no network import.
lifecycle.py       # NO streamlit, NO store import: pure snapshot-diff — new_actionable, persisting_new_actionable,
                   #   blocked_change (§9), recently_actionable (§10 backlog), first_seen.
api.py             # FastAPI app + Pydantic models + THIN handlers: GET /opportunities (+sport/bucket/status),
                   #   /opportunities/{id}, /backlog, /coverage, /alerts, /healthz; POST /scan. Db-path + fetch
                   #   are injectable deps (offline tests).
serve.py           # Uvicorn entrypoint: imports webui.dashboard, then ui.run_with(api.app, mount_path='/').
                   #   Run: python serve.py.
webui/             # NiceGUI dashboard (Streamlit-free): dashboard.py = @ui.page('/') opportunity-first
                   #   cross-sport view (tables + explanation panel, backlog, alerts, freshness, Scan now);
                   #   engine.py = in-process store/lifecycle/scanner accessors (db_path=None → live store).
app.py             # Streamlit ONLY: per-sport dashboard; load_contracts wraps fetch.fetch_contracts. Kept.
scripts/           # check_links.py, export_glossary.py (→ docs/GLOSSARY.md).
docs/GLOSSARY.md   # generated glossary (also a Google Doc).
tests/             # pytest (~235): test_{data,consistency,dutchbook,glossary,client,filters,viz,sports,app}
                   #   + test_{store,scanner,lifecycle,api,webui} (engine layer).
```

`sports.py`, `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py`, `fetch.py`,
`store.py`, `scanner.py`, `lifecycle.py`, `api.py`, and `webui/` MUST stay free of Streamlit imports.
`config.py` MUST stay import-free at the top level (so `serve.py` can safely read env vars before any
engine import).

- **Fetch by family (do not regress):** `load_contracts(families, scan_all)` fetches ONLY the series
  whose contract family is enabled (`data.series_for_families`) — **family toggles are the only control
  that changes what's fetched**. `scan_all` (default ON) widens candidates to all tennis via
  `discover_tennis_series()`; else `DEFAULT_SERIES`. Tournament/event/participant filters are
  client-side. Series list cached ttl 3600; contracts cached ttl `config.REFRESH_TTL` (30s).
- **Auto-refresh (do not regress):** the dashboard renders inside `@st.fragment(run_every=...)` so it
  re-fetches on a timer (on by default; interval picker, default `REFRESH_DEFAULT_SECONDS`=120s). The
  fragment re-calls the cache-gated `load_contracts`. Full scan is heavier (~120+ GETs/tick): a warning
  is shown and the interval is clamped to ≥ `FULL_SCAN_MIN_INTERVAL` (120s).
- **Rate limiting (free tier):** Kalshi Basic read ≈ 20 req/s (200 tokens/s ÷ 10/GET; verified at
  docs.kalshi.com/getting_started/rate_limits). `kalshi_client._throttle` caps issuance at
  `config.MAX_RPS` (5, ~25%) via a min-interval limiter; `_get` retries with `Retry-After`/exponential
  backoff (`MAX_RETRIES`/`BACKOFF_*`); fan-out concurrency is `CONCURRENCY` (4). **The throttle is
  PROCESS-WIDE ONLY** — multiple processes/containers/replicas each have their own limiter (aggregate =
  `MAX_RPS × process count`); a large scale-out would need a shared limiter.
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source,
  mapping_confidence, mapping_reason, tour, kind, category, contract, stage, stage_rank, opponent,
  tournament, tournament_source, display_pct, yes_mid_pct, last_pct, yes_bid_pct, yes_ask_pct,
  spread_cents, quote_quality, yes_bid_c,
  yes_ask_c, last_c, display_c, yes_bid_size, yes_ask_size, no_bid_pct, no_ask_pct, no_bid_c, no_ask_c,
  volume, open_interest, status, time_value, time_kind, kalshi_url, series, event_ticker, market_ticker,
  event_title, market_title, raw_yes_bid, raw_yes_ask, raw_no_bid, raw_no_ask, raw_last, rules_primary`.

## Opportunity engine (built — per-module detail in the Architecture tree above)

The engine turns per-sport contracts into one persistent, ranked, queryable opportunity feed:
`fetch → consistency/dutchbook → scanner → store → lifecycle → api/webui`.

**Opportunity invariants (do not regress)** — every row (consistency check or dutch-book finding) carries:
- `opportunity_id` — deterministic sha1 (`data.opportunity_id`), stable across scans for the same pair.
- `relationship_type` — `containment_adjacent` | `match_alignment` | `dutch_book`.
- `bucket` — `actionable` | `blocked` | `near_edge` | `display_signal` | `wide_signal` | `data_quality` | `clean`.
- `blocked_reason` — non-empty **IFF** `bucket == "blocked"` (a test guards it).

**Cross-cutting engine rules (do not regress):**
- The **store is the source of truth** — the API and NiceGUI read the latest snapshot; the only
  writer-trigger is a scan, which is **store-backed TTL-guarded** (skip if too soon, never write a
  duplicate; `force` overrides).
- Coverage (scanned/loaded/failed/excluded/skipped) is persisted in the snapshot `meta` column;
  `/coverage` reports `meta_present` honestly (never fakes counts).
- `lifecycle` is derived **purely from snapshot history** — no extra state/tables (§8 new-actionable,
  §9 blocked-change "what changed", §10 recently-actionable backlog).
- `api.py` handlers are **thin** (no detection logic); db-path + fetch are injectable dependencies so
  tests run offline. Pydantic models are stable (Stage-6 export reuses them).
- NiceGUI calls the engine **in-process** (not self-HTTP); its scan is **core series only**, labelled honestly.

## Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last
  trade, else blank. A `0.00/1.00` book is "No quote" (never a fake 50%).
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote.
- Surface every component (mid / last / bid / ask / spread) so a price is never opaque.

## Layer Consistency Checker — hard rules (do not regress)

Containment ladder, broad → deep: `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`; a child (deeper)
price must be ≤ its parent (broader). Adjacent containment pairs use market contracts; **match-alignment**
pairs (`Quarterfinal win ≡ Reach Semifinal`, etc.) are included only when the round maps confidently.
Anything unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

- **Call findings "executable inconsistencies", NEVER "arbitrage."** True arbitrage also needs the two
  markets' settlement rules to match, which we don't auto-verify → match-alignment rows always carry
  `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` if a light `rules_primary` token compare differs).
- **Buy-only action language (do not regress):** the UI must express every opportunity as two BUYS —
  **Buy YES** on the broader/parent leg, **Buy NO** on the deeper/child leg — never "sell"/"long"/
  "short". `_classify` emits `action_1_*`/`action_2_*` (+ `tradable_now`, `blockers`, `watchlist_note`)
  for `EXECUTABLE_VIOLATION`/`DISPLAY_VIOLATION`/`QUOTE_SIZE_MISSING`; the Buy-NO price is the real
  `no_ask_c` (fallback `100 − yes_bid_c`). `tradable_now` is "Yes" only when `EXECUTABLE_VIOLATION` +
  both legs `active` + no rule flag ("Yes — rule-dependent" for equivalence). **`WIDE_QUOTE` gets no
  action (watchlist-only).** `blockers`/glossary text is single-sourced from `glossary.py`. The
  executable-gap/profit math is unchanged.
- **All comparison logic in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.
- **Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
  positive sizes**; a missing display blocks only the display test.
- **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, sizes > 0) is the ONLY "Broken" status.**
  `DISPLAY_VIOLATION` is "Warning"; a sizeless price-cross → `QUOTE_SIZE_MISSING`, **unless the display
  prices also cross** (then `DISPLAY_VIOLATION` — AUDIT-002 product decision: the display cross is the
  more informative signal when size is absent; see `consistency.py` for the inline comment). Crossed books
  (`ask < bid`) → "Crossed" quality, never executable.
- Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
  QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
  WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown relationship=UNKNOWN_RELATIONSHIP.

**Historical illustration (French Open 2026 women's draw — captured live then; not reproducible now the
draw has settled):** Cirstea `Quarterfinal win ≡ Reach Semifinal` → `EXECUTABLE_VIOLATION` (~2¢) flagged
`RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display → `DISPLAY_VIOLATION`; Gauff/Swiatek
empty books → `MISSING_QUOTE`. (For repeatable assertions use the unit tests, not live data.)

## Dutch-book / MECE detector — `dutchbook.py` (do not regress)

A **separate check family** from the containment ladder, in its own module (`dutchbook.py`, NO streamlit).
A dutch book is an executable arbitrage on a **mutually-exclusive-and-exhaustive** set of binary markets:
cover EVERY outcome for under the guaranteed 100¢ payout. Currently the **2-outcome case only** — a
head-to-head event with **exactly two** distinct-participant markets (one wins, no draw → MECE by
construction). `find_dutch_books(rows)` groups match-family rows by `event_ticker` and emits ≤1 finding/event.

- **Two directions, both pairs of BUYS** (never "sell"): **underround** → Buy YES both (`yes_ask_A +
  yes_ask_B < 100`); **overround** → Buy NO both (`no_ask_A + no_ask_B < 100`, with the `100 − yes_bid`
  fallback). They're mutually exclusive (`bid ≤ ask`) so only one can fire. Exact integer cents only.
- **Sport-agnostic via `_is_two_way_row`:** eligible families are the sport's head-to-head family
  (`cfg.match_family`) **and** the `"game"` family (NBA/WNBA per-game `KX*GAME` markets). This covers
  tennis matches, NBA/WNBA playoff series, and NBA/WNBA single games. Props, winner, advance are NOT
  two-way → ignored. Unknown/unrecognized series (`UNKNOWN` sport) are always excluded.
- **One status `EXECUTABLE_DUTCH_BOOK`** carrying `tradable_now` + `blockers` (covers actionable AND
  blocked). **Routing is the only consistency.py touch:** `bucket_of` has one branch (actionable if
  tradable, else blocked) + a `STATUS_GROUP` entry — detection stays entirely in `dutchbook.py`. The status
  string is held as a literal in `consistency.py` (a test guards the contract). **It is a true arbitrage**
  (same event, both legs settle together) → no rule caveat, unlike match-alignment.
- **UI:** `app.py` renders a **dedicated "Dutch-book arbitrage — match books" section** (both legs are the
  *same* side, so it can't reuse the ladder's Buy-YES-broader/Buy-NO-deeper table). Membership-filtered like
  the rest; thresholds spare it (like Actionable now). Glossary term "Dutch book" → "Locked edge (¢)" column.
- **In scope (built):** per-game 2-outcome books (NBA/WNBA `KX*GAME`) — milestone m1.1, shipped. **Out of
  scope (seeds):** n-outcome winner **fields** (≥3 outcomes; need completeness proof + multi-leg). `find_dutch_books` consumes `df.to_dict("records")` so it is **NaN-safe**.

## Mapping audit & raw ladder spreads

- **Mapping confidence:** `build_contracts` stamps `mapping_confidence` ("high" = stable
  `tennis_competitor` UUID; "low" = name fallback) + `mapping_reason`. No downstream row without `kind` + confidence.
- **Expected-vs-found:** `consistency.expected_nodes(player_rows)` makes a missing ladder layer explicit.
- **Per-player export:** the detail view exports a JSON snapshot + CSV (contracts + consistency comparisons).
- **Raw stage-ladder spreads (v1, shipped):** `consistency.layer_spreads(player_rows)` returns, per
  adjacent pair, `spread_pct` (percentage **points**) and `spread_cents` (broader − deeper). **Raw spreads,
  not a probability model.** Reuse `consistency.representative(node_entry)` (market else match) — the single
  price-row selector shared by the chain and the spreads. Distinguish `missing_layer` from `missing_price`
  (both **NaN-safe** — `None` round-trips to NaN via `to_dict`); a `quote` field (worst leg) drives a Quote
  column since most legs are illiquid; `inverted` is None-safe; pp gap labelled **"pp"**; the spread table
  sits **directly beneath** the ladder (don't replace it).

## Correctness & robustness invariants (audit hardening — do not regress)

- **Group/select by `player_key`, not display name** (`build_checks` groups on `(player_key, tournament)`;
  the Participant selector maps labels→keys, disambiguating `"Name [key6]"` only on collision) — two
  same-named players never merge, and one player's tournaments never merge.
- **Truthful evidence:** the `EXECUTABLE_VIOLATION` reason quotes the *winning* cross direction (equivalence
  checks forward and reverse).
- **Crossed books** (`ask < bid`) → `quote_quality == "Crossed"`: never Tight, never a midpoint, never fed to
  the executable test.
- **`tour_of`** classifies every `FO_WINNER_TICKERS` variant explicitly (`KXFOPENWMENSINGLE` → WTA).
- **No silent truncation:** `get_paginated` raises if `MAX_PAGES` (100) is hit with a cursor pending. *(PR #13)*
- **Deterministic duplicates:** `build_player_nodes` picks the representative by a stable rule; `duplicate_node_sources` surfaces it. *(PR #13)*
- **Tournament grouping (generalized; replaces the old FO gate):** `build_contracts` no longer gates on
  French Open — all tennis events are included. `data.tournament_of` returns a **never-empty** grouping
  key (cleaned `competition` → winner-ticker → title keyword → `Unknown · <competition|event_ticker|
  event_title|series_ticker>`, with `tournament_source` recording which). `build_checks` groups by
  `(player_key, tournament)`, so ladders never mix across tournaments and a fallback never collapses to
  "". `is_french_open_event` survives as a helper, not a gate.

## UI — trader-first dashboard (do not regress the section order)

**Controls live in `st.sidebar`; main page full width.** Order: Refresh, **Contract family**
(**default ALL**, read **before** the fetch — *only this control changes what's fetched*), then after
the fetch: **Tour** (default **Both**), **Tournament** (multiselect, default all), Auto-refresh +
interval, **Market universe** (one merged **Participant** selectbox — *All* = no filter; a name filters
the dashboard AND drives the detail section; **Event/game** + **Stage/layer** multiselects),
**Thresholds** (Min available size, Quote quality, **Market status = Active only by default**),
**Sections** toggles, and **Advanced — data scope LAST** (Scan-all **default ON** via a session-state
read-ahead; **Min traded volume**; Show explanations).

**Filter split (critical — do not regress):** `consistency.bucket_of(row)` routes each comparison
(actionable / blocked / near_edge / display_signal / wide_signal / data_quality / clean). Two passes via
`filters.py`: `universe = apply_membership(dash_base, …)` (Tour pre-applied to `df`;
tournament/contract-family/stage-layer/event/participant/min-volume are membership) feeds **Actionable
now and every section**; `thresholded = apply_thresholds(universe, …)` (min size, quote, **market
status**) feeds **every section EXCEPT Actionable now**. **Full diagnostics is built from `universe`
(NOT `thresholded`) + the Outcome-status select**, so **finalized markets stay visible there** even with
Active-only as the default elsewhere. (Scope: "finalized" here means markets with `status=finalized`
within events the API still returns as `status=open`. Fully closed events are excluded at the API
level — `kalshi_client.get_events` passes `status="open"` to Kalshi, so settled past events are not
in the universe.) Membership runs on comparison rows so it never breaks pairing.

**Main area:** (1) header; (2) six `st.metric` cards + **⬇ Export** expander (Comparisons `universe`
CSV, Raw contracts CSV); (3) **Actionable now** — always visible, **sorted by gross edge ↓** (no
min-edge gate; any edge is good); (4) **Dutch-book arbitrage** section (dedicated, separate from the
ladder); (5) **Blocked** / (6) **Near-edge** (Show-toggled); collapsed: (7) **Watchlist signals** +
(7b) **Data-quality** (off by default), (8) **Selected player detail**, (9) **Full diagnostics**
(Outcome-status + own CSV), (10) **Debug** (incl. `tournament_source`). The opportunity-ranking bar
chart was **removed** (Stage 0 — misleading; Actionable table is the ranking surface). Use
`width="stretch"` on dataframes and `st.altair_chart` if adding charts.

**Status display labels (no "Potential edge"; "edge" only for a positive executable gap):**
`EXECUTABLE_VIOLATION`→"Actionable gross edge", `DISPLAY_VIOLATION`→"Display inconsistency",
`WIDE_QUOTE`→"Wide quote / watchlist", `MISSING_QUOTE`→"Missing firm quote",
`QUOTE_SIZE_MISSING`→"Blocked: no size", `CLEAN`→"Consistent". Internal status strings are unchanged.

## Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`.
- Use `data.to_cents` (Decimal, exact) for any comparison logic — no float drift.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Empty results are valid (between rounds → no open events), not errors — handle gracefully.
- Always loop the `cursor` for pagination; the client raises if the `MAX_PAGES` cap is hit with a cursor
  still pending (no silent partial data).
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- **Restart the running server after editing imported modules** — both `streamlit run app.py` and
  `python serve.py` (uvicorn) cache modules, so a browser "Rerun" / refresh won't pick up edits. Fully
  stop and restart; for a phantom `ImportError` clear stale bytecode too (`rm -rf __pycache__
  tests/__pycache__`). (This already cost time once.)
- **Engine vs Streamlit separation:** `store`/`scanner`/`lifecycle`/`fetch`/`api.py`/`webui/` are
  engine modules — they must not import `streamlit`; `app.py` is Streamlit-only and must not be imported
  by the engine (`webui/engine.py` imports `api.fetch_dep`, NOT `app`). **`config.py` must stay
  import-free** at the top level (so `serve.py` can read env vars before any engine import). The snapshot
  **`.db` is gitignored** (`config.SNAPSHOT_DB_PATH`) — never commit it.
- The FO date window in `config.py` is year-specific — update for future tournaments.
- The Kalshi **web** site (`kalshi.com`) is bot-throttled (HTTP 429), so automated link-reachability
  checks from this environment are unreliable (everything 429s — not a broken link). Links point at
  the specific market via the verified deep-link format (see API section); `data.link_audit` proves
  link *correctness* (URL ↔ contract identifiers) deterministically, and `scripts/check_links.py` does a
  best-effort live reachability check meant to be run from your own (unthrottled) network.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` here-doc for multi-line commit/PR text. The PowerShell
  `@'...'@` here-string syntax **corrupts** messages when invoked through the Bash tool (it bit us twice —
  stray `@` characters). Reference code as `path:line`.
- Verify changes with `pytest -q` plus a headless Streamlit boot and/or `python serve.py` → `GET /healthz` (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, and `.claude/` (local settings — keep out of the repo).

## Git workflow (strict — owner confirmed)

- **Never commit or push to `main`.** The owner merges manually; you push branches and open PRs.
- Branch off the current `main` (now canonical). **Do not stack on unmerged branches** — a past stack
  caused a merge mess; one PR per change, based on `main`. Verify (`pytest -q`, headless) before pushing.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR bodies end with the Claude Code footer.

## Repository status

`main` is **feature-complete through Stage 4** (PRs #35–#40 merged): all-tennis generalization,
multi-sport (`sports.py`), dutch-book detector, Stage-0 clarity, and engine Stages 1–4 (opportunity
schema + SQLite store, cross-sport scanner, lifecycle, FastAPI API). **Stage 5 (#41 — `serve.py` +
`webui/` NiceGUI dashboard) is open** — owner merges manually. ~235 tests (file list: the `tests/` entry
in the Architecture tree). See the Iteration history below for what each stage delivered.

**Remaining / deferred:** Stage 6 export overhaul; per-player deep-dive port → Streamlit retirement;
full-scan toggle in the NiceGUI dashboard.

## Iteration history (intent)
1. Per-player French Open match viewer.
2. All per-player FO contracts via dynamic series discovery.
3. Transparent pricing (Display % + components + quote quality), default core series, richer debug.
4. Layer Consistency Checker: containment + match-alignment, executable-vs-display, conservative rule flags.
5. Mapping-audit hardening (confidence + reasons, expected-vs-found, per-player export) + first tests.
6. v1 raw stage-ladder spreads beneath the ladder; NaN-safe + Quote column.
7. Audit hardening — Tier-1 (key-based grouping, truthful reasons, tour map, crossed-book guard, JSON
   safety) merged; Tier-2 (pagination/duplicate/date-window) in PR #13.
8. Buy-only action plan: real Kalshi NO prices, verified deep links, `tradable_now` + plain-English
   blockers, single-sourced glossary (`glossary.py` + Google Doc).
9. Trader-first dashboard: sidebar controls, full-width summary cards + Actionable now / Blocked /
   Near-edge on top, diagnostics + player detail + debug collapsed below; `consistency.bucket_of`
   routes rows; "Potential edge" wording removed.
10. Auto-refresh (native `st.fragment(run_every)`, on by default, 120s; full-scan clamp/warn) with a
    process-wide request throttle + `Retry-After`/exponential backoff, kept safely under the free-tier
    read limit.
11. Market-universe sidebar filters (`filters.py`): membership (tour/tournament/contract-family/
    stage-layer/event/participant/min-volume) narrows all sections; thresholds (min size, quote, market
    status) spare Actionable now; Show-section toggles; Data-quality section; exports.
12. **Generalized to all tennis** (`tournament_of`, grouping by player+tournament, fetch-by-family),
    sidebar cleanup (merged participant control, Active-only default with finalized still visible in
    diagnostics, Advanced last, scan-all + all-families default), **Actionable ranked by edge**, and an
    **opportunity-ranking chart** (`viz.opportunity_ranking` + Altair). Min-gross-edge control removed.
13. **Multi-sport** (`sports.py`): `SportConfig` registry (Tennis/NBA/WNBA) with `IdentityResolver`/`LadderSpec`/`MarketClassification`; `sport_for_series` resolves any ticker (explicit `UNKNOWN`, no silent tennis default); the engine reads sport config off the registry (no hardcoded sport).
14. **Dutch-book detector** (`dutchbook.py`): 2-outcome MECE arbitrage on matches/series + per-game (`KX*GAME`, m1.1); under/overround; dedicated section; `EXECUTABLE_DUTCH_BOOK`; sport-agnostic via the `"game"` family.
15. **Stage 0 clarity**: Lisbon-default TZ + per-second freshness/coverage strip, "Show IDs & codes" toggle, ranking chart removed, debug/diagnostics behind Advanced.
16. **Stage 1 — opportunity schema + SQLite store** (`fetch.py`, `store.py`): stable `opportunity_id`/`relationship_type`/`bucket`/`blocked_reason`; `fetch_contracts` extracted from `app.load_contracts`; versioned store (v2 + `_migrate`), retention, NaN-safe.
17. **Stage 2 — cross-sport scanner** (`scanner.py`): `unified_opportunities`/`run_scan` aggregate + rank across sports (bucket priority → edge → id); per-sport failures isolated; coverage persisted in `meta`.
18. **Stage 3 — lifecycle** (`lifecycle.py`): pure snapshot-diff — new-actionable (§8), blocked-change (§9), recently-actionable (§10), first-seen, persisting-new-actionable.
19. **Stage 4 — FastAPI engine API** (`api.py`): thin read endpoints serving the latest snapshot + store-backed-TTL `POST /scan`; injectable deps (offline tests); stable Pydantic models.
20. **Stage 5 — NiceGUI cross-sport dashboard** (`serve.py`, `webui/`): mounted on `api.app` at `/`; in-process reads; sortable tables + explanation panel, backlog, alerts, freshness strip, honest core-series "Scan now".
