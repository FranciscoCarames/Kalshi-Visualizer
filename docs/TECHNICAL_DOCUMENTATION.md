# Kalshi Structured Market Visualizer — Technical Documentation

**Audience:** Backend developer, technical collaborator, or future maintainer.
**Source of truth:** The live codebase as of 2026-06-04 (`main`, PR #35 merged). Items labelled
PLANNED are not yet built. Everything else is the current built state.

---

## 1. Project Overview

The Kalshi Structured Market Visualizer is a multi-entrypoint system built on top of the public Kalshi
prediction-market REST API. It surfaces price inconsistencies and Dutch-book arbitrage across tennis,
NBA, and WNBA contracts and expresses every opportunity as two-buy trade instructions.

**Two entrypoints exist and run simultaneously (one does not replace the other yet):**

- **`streamlit run app.py`** — the original per-sport Streamlit dashboard, kept fully operational. Full
  sidebar controls, per-player detail, all sections.
- **`python serve.py`** — the FastAPI engine API + NiceGUI cross-sport dashboard. REST endpoints at
  `/opportunities`, `/backlog`, `/coverage`, `/alerts`, `/healthz`, `/scan`; OpenAPI at `/docs`;
  NiceGUI opportunity-first UI at `/`.

**Supported sports:** Tennis (ATP + WTA, all tournaments), NBA (championship / conference / playoff-series
/ per-game), WNBA (championship / reach-stage / playoff-series / per-game). Each sport is registered as a
`SportConfig` in `sports.py`.

**Current state:** Stages 1–5 of the roadmap are built and tested (235 tests across 14 files). Stage 6
(export overhaul) and some deferred follow-up items remain planned. The Streamlit app is kept as-is;
Streamlit retirement is deferred.

**What the app is NOT doing:**
- Execute trades or place orders
- Model conditional probabilities or de-vig
- Provide portfolio management or position tracking
- Add sports beyond tennis / NBA / WNBA without explicit scope change
- Persist time-series historical data or multi-user server state

---

## 2. System Scope

### Current Scope

- Read-only market-data viewer; no authentication, no trading
- Loading and organizing Kalshi prediction-market contracts via public REST API across three sports
- Multi-sport participant grouping via a `SportConfig` abstraction (`sports.py`)
- Layer-consistency checking: containment violations + match-alignment equivalence checks, per sport ladder
- Dutch-book / MECE detector on 2-outcome head-to-head and per-game markets (`dutchbook.py`)
- Stable opportunity identity (`opportunity_id` — deterministic SHA-1 prefix) across refreshes
- **SQLite snapshot store** (`store.py`) — one persisted snapshot per scan; versioned schema (v2)
- **Cross-sport unified scanner** (`scanner.py`) — all sports aggregated and ranked in one frame
- **Lifecycle diffs** (`lifecycle.py`) — new-actionable alerts (§8), blocked-change detection (§9),
  recently-actionable backlog (§10); all derived from store snapshots, no extra tables
- **FastAPI REST API** (`api.py` + `serve.py`) — typed read-from-store endpoints + TTL-guarded scan
- **NiceGUI dashboard** (`webui/`) — in-process engine accessors, sortable tables, explanation panel,
  per-second freshness strip, alert polling
- **`fetch.py`** — Streamlit-free contract fetch, shared by both app.py and serve.py
- Quote transparency: bid, ask, midpoint, last trade, spread quality
- Buy-only action instructions for executable inconsistencies and Dutch-book arbitrage
- Dashboard views in both the Streamlit and NiceGUI surfaces
- Always-visible data-freshness & coverage strip
- Timezone-aware display with Lisbon default; comparison math always exact UTC cents
- Per-player and full-dataset CSV/JSON export (Streamlit app)

### Out of Scope

- Trade execution or order placement
- Automated trading or strategy execution
- Full arbitrage guarantee for match-alignment pairs (settlement-rule compatibility not auto-verified)
- Conditional-probability modeling or de-vig math
- Portfolio management
- Multi-user server state or shared rate limiter (store is single-writer local SQLite only)
- Sports beyond tennis / NBA / WNBA (requires explicit scope change)
- Out-of-browser notifications; sound alerts
- React migration (planned after Streamlit retirement, outside current stages)
- Export overhaul (Stage 6 — planned)

---

## 3. Architecture Overview

```
Kalshi REST API (public, no auth)
  ↓
kalshi_client.py  — HTTP, pagination, throttle, retry, concurrency; sport-aware series discovery
  ↓
sports.py         — SportConfig abstraction: one config per sport (tennis/NBA/WNBA), registry,
                    family/stage/node/division callables, LadderSpec, IdentityResolver
  ↓
fetch.py          — Streamlit-free fetch: fetch_contracts(families, scan_all, sport_id) → 7-tuple;
                    called by app.load_contracts (cached) and the FastAPI scanner
  ↓
data.py           — Parse raw JSON → per-participant contract rows (flat dicts); sport-agnostic
                    via sports.py; ALL tennis events (no FO gate); tournament stamping;
                    opportunity_id() deterministic hash helper
  ↓
consistency.py    — Build per-participant nodes → pairwise comparisons → edge classification;
                    sport-resolved ladder per row; stamps opportunity_id / relationship_type /
                    bucket / blocked_reason on every row
  ↓
dutchbook.py      — 2-outcome MECE detector: find_dutch_books() on match + game rows;
                    stamps opportunity_id / relationship_type / bucket / blocked_reason
  ↓
scanner.py        — Cross-sport aggregation: unified_opportunities() + run_scan();
                    normalizes both row shapes onto UNIFIED_COLUMNS; ranked best→worst;
                    partial-failure tolerant; store-write injected
  ↓
store.py          — SQLite snapshot store (local, single-writer, schema v2 with meta column);
                    write_snapshot / latest / latest_two / snapshots_since; NaN-safe; no pandas
  ↓
lifecycle.py      — Snapshot-diff engine: new_actionable / blocked_change / recently_actionable /
                    persisting_new_actionable / first_seen; pure functions, no store import
  ↓
┌─────────────────────┬──────────────────────────────────────────────────┐
│ app.py              │ api.py + serve.py + webui/                       │
│ (Streamlit app)     │ (FastAPI + NiceGUI engine)                       │
│ streamlit run app.py│ python serve.py                                  │
└─────────────────────┴──────────────────────────────────────────────────┘
  ↑
config.py         — All tunables (URLs, series lists, thresholds, rate limits, refresh cadence,
                    timezone options, staleness threshold, DB path, lifecycle windows, API host/port,
                    NiceGUI secret fallback)
glossary.py       — All user-facing help text (tooltips, blocker reasons, watchlist notes)
filters.py        — Two-pass membership + threshold filtering on comparison DataFrames
viz.py            — Chart data prep (payoff_chart_data, ladder_prices)
```

### Per-layer details

| Layer | Responsibility | Input | Output | Files/Functions |
|---|---|---|---|---|
| **Sport abstraction** | One `SportConfig` per sport; registry; family/stage/node/division resolution | Series ticker, market dict | `MarketClassification`, `IdentityResult` | `sports.SportConfig`, `sports.sport_for_series`, `sports.register`, `sports.TENNIS`, `sports.NBA`, `sports.WNBA` |
| **HTTP** | Rate-limited, paginated, retried GET requests to Kalshi | Series tickers | Raw event/market JSON | `kalshi_client._get`, `get_paginated`, `get_events`, `discover_series_for_sport`, `get_events_for_series` |
| **Fetch** | Streamlit-free data acquisition; wraps kalshi_client + data | (families, scan_all, sport_id) | 7-tuple (df, fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded) | `fetch.fetch_contracts` |
| **Parsing** | Flatten events → per-participant contract rows; classify, price, link; stamp tournament; opportunity_id | Raw JSON dicts | List of contract dicts | `data.build_contracts`, `data.opportunity_id` |
| **Tournament filtering** | Stamp each event with its tournament; `is_french_open_event` is a helper, not a gate | Event dict | tournament key string | `data.tournament_of`, `data.is_french_open_event` |
| **Consistency** | Build participant nodes using sport ladder, compare adjacent pairs, classify violations; stamp identity | Contract row list | Comparison DataFrame (incl. opportunity_id, relationship_type, bucket, blocked_reason) | `consistency.build_checks`, `consistency._classify` |
| **Dutch-book detection** | Find 2-outcome MECE arbitrage on match + game events; stamp identity | Contract row list (dicts) | List of finding dicts (incl. opportunity_id, relationship_type, bucket, blocked_reason) | `dutchbook.find_dutch_books`, `dutchbook._detect_pair` |
| **Scanner** | Aggregate all sports; normalize onto UNIFIED_COLUMNS; rank; optionally persist | (fetch_fn, store_writer) | (unified_df, per_sport_errors) | `scanner.unified_opportunities`, `scanner.run_scan` |
| **Snapshot store** | Persist one opportunity set per refresh; versioned schema; retention | (fetched_at, opps, meta) | snapshot_id; query functions | `store.write_snapshot`, `store.latest`, `store.latest_two`, `store.snapshots_since` |
| **Lifecycle** | Diff snapshots: new-actionable, blocked-change, recently-actionable | Snapshot dicts from store | Lists of diff/backlog rows | `lifecycle.new_actionable`, `lifecycle.blocked_change`, `lifecycle.recently_actionable` |
| **Bucketing** | Route each comparison or Dutch-book finding to a dashboard section | Single check row dict | Bucket name string | `consistency.bucket_of` |
| **Filtering** | Two-pass filter: membership (all sections) + thresholds (all except Actionable now) | Checks DataFrame | Filtered DataFrames | `filters.apply_membership`, `filters.apply_thresholds` |
| **FastAPI API** | Thin REST handlers; read-from-store; TTL-guarded POST /scan; Pydantic response models | HTTP request | JSON response | `api.app`, `api.get_opportunities`, `api.post_scan`, `api.get_coverage`, `api.get_alerts`, `api.get_backlog` |
| **NiceGUI engine** | In-process accessors wrapping store/lifecycle/scanner for the dashboard | — | Dicts/lists | `webui.engine.latest_opportunities`, `.coverage`, `.alerts`, `.backlog`, `.run_scan_now` |
| **NiceGUI dashboard** | Sortable tables, explanation panel, freshness strip, alert polling | Engine accessors | NiceGUI UI components | `webui.dashboard.dashboard` (registered as `@ui.page('/')`) |
| **Streamlit UI** | Per-sport sidebar controls, summary cards, section tables, Dutch-book section, export | Filtered DataFrames + Dutch-book findings | Streamlit widgets | `app.py:render_dashboard`, `app.py:render_freshness` |

**Architecture invariants:**
- `data.py`, `consistency.py`, `dutchbook.py`, `filters.py`, `viz.py`, `fetch.py`, `scanner.py`, `lifecycle.py`, and `store.py` must never import Streamlit.
- `data.py`, `dutchbook.py`, and `store.py` must not import pandas (plain dicts/lists only; DataFrames are duck-typed).
- `sports.py` imports only `config` and stdlib (no circular imports).
- `config.py` contains no functions or imports (pure constants).
- `glossary.py` contains no imports.
- All comparison math uses exact integer cents (`to_cents` via `Decimal`); floats are display-only.
- An empty order book (`0.00/1.00`) is never treated as a real price.
- Pagination raises on truncation; partial data is never silently returned.
- `api.py` handlers contain no detection logic — all computation is delegated to the engine.

---

## 4. Data Model

### Core entities

**Series** — A Kalshi series groups semantically related events. Example: `KXWTAMATCH` (all WTA
match-winner events). Identified by `series_ticker`.

**Event** — A single competition event, e.g. one match or one advancement milestone. Contains one or
more markets. Identified by `event_ticker`.

**Market** — A single binary outcome. Identified by `market_ticker`. For match events there are two
markets (one per player); for advancement/winner events there is one market per player.

**Participant (player/team)** — A competitor, identified by `player_key` (preferred: stable UUID from
`custom_strike.tennis_competitor` or `custom_strike.basketball_team`; fallback: normalized display name).
The identity path is sport-specific via `IdentityResolver`.

**Contract row** — The normalized per-participant output of `data.build_contracts`. One row = one
participant's view of one market.

**Node** — A logical ladder position mapped from a contract: e.g. `Reach Semifinal`, `Reach Final`,
`Win Tournament` (tennis); `Reach Playoffs`, `Win Conference`, `Win Championship` (NBA). Defined per
sport in `SportConfig.ladder.node_order`; back-compat alias `consistency.NODE_ORDER` references the
tennis ladder.

**Comparison row** — Output of `consistency.build_checks`. One row = one pairwise comparison between a
child (deeper) and a parent (broader) node, with a status, gap, action plan, and Stage-1 identity fields.

**Opportunity** — Any comparison row or Dutch-book finding; carries a stable `opportunity_id`,
`relationship_type`, `bucket`, and `blocked_reason`. The unit of persistence in the snapshot store and
the unit of tracking in the lifecycle engine.

**Snapshot** — One complete set of opportunity rows persisted together, keyed by `snapshot_id` and
`fetched_at`. Schema: `{snapshot_id, fetched_at, fetched_ts, meta, opportunities: [...]}`. The `meta`
field (schema v2) carries per-scan coverage JSON (scanned/loaded/failed/excluded counts + errors).

### Contract row field dictionary

| Field | Source | Meaning | Used For | Notes |
|---|---|---|---|---|
| `player` | `data.display_player_name` | Clean, user-facing display name | Player selector, tables | Alias > source name > titleized fallback |
| `player_key` | `IdentityResolver.resolve(market)` (sport-specific UUID or `name.casefold()`) | Stable grouping key | Grouping, dedup | UUID preferred; name-fallback may collide |
| `player_key_source` | derived | `"competitor_uuid"` or `"name_fallback"` | Debug, audit | |
| `player_name_raw` | `yes_sub_title` | Raw display name from Kalshi | Debug, display fallback | Preserved verbatim |
| `player_name_normalized` | `name.casefold()` | Lowercase normalized name | Debug | |
| `competitor_uuid` | `custom_strike.tennis_competitor` or `custom_strike.basketball_team` | Stable Kalshi identity UUID | Primary grouping key | Empty string when absent |
| `mapping_confidence` | derived | `"high"`, `"low"`, or `"none"` | Audit, display | High = UUID present |
| `mapping_reason` | derived | Human-readable explanation of confidence level | Debug panel | |
| `tour` | `cfg.division_of(series_ticker)` | `"ATP"` or `"WTA"` (tennis); `""` (NBA/WNBA) | Tour filter | |
| `kind` | `data.classify_kind(series_ticker)` (delegates to sport's `family_fn`) | e.g. `"match"`, `"advance"`, `"winner"`, `"game"`, `"other"` | Contract type filter, node mapping | Alias for `family` on `MarketClassification` |
| `category` | `cfg.category_labels[kind]` | User-facing category label | Contract family filter | Sport-specific |
| `contract` | derived | Human-readable contract description | Tables | e.g. "Beat Andreeva — Quarterfinal" |
| `stage` | `cfg.stage_of(family, market)` | Ladder stage label | Node mapping, sort | e.g. "Semifinal", "Final", "Champion", "Conference Finals" |
| `stage_rank` | `cfg.stage_rank[stage]` | Integer sort key | Sort order | Sport-specific rank map |
| `ladder_node` | `MarketClassification.ladder_node` | Containment node this market maps to, or None | Consistency checker | e.g. `"Reach Semifinal"`, `"Win Championship"` |
| `ladder_eligible` | `MarketClassification.eligible_for_ladder_checks` | Whether this market enters ladder comparisons | Consistency checker | False for `game`, props, `other` |
| `tournament` | `data.tournament_of(event)` | Never-empty tournament/season grouping key | Grouping, tournament filter | Resolution chain: competition → winner-ticker → title keyword → `"Unknown · ..."` |
| `tournament_source` | `data.tournament_of(event)` side-channel | Which resolution path produced the tournament key | Debug | `"competition"`, `"winner_ticker"`, `"title_keyword"`, or `"unknown"` |
| `opponent` | sibling market `yes_sub_title` | Opponent name (match events only) | Display | Empty for non-match kinds |
| `competition` | `product_metadata.competition` | Tournament/competition label from Kalshi | Universe filter, tournament stamping | e.g. `"French Open Women Singles"` |
| `display_pct` | `data.display_prob` | Best display price as a percentage | Tables, consistency | Midpoint if spread ≤ 20¢, else last, else None |
| `yes_mid_pct` | `data.yes_mid` | YES bid/ask midpoint % | Detail tables | None on empty/crossed book |
| `last_pct` | `last_price_dollars` | Last traded price % | Detail tables | |
| `yes_bid_pct` | `yes_bid_dollars` | YES bid price % | Tables | |
| `yes_ask_pct` | `yes_ask_dollars` | YES ask price % | Tables | |
| `spread_cents` | derived | YES bid/ask spread in cents | Quote quality | None on empty/crossed book |
| `quote_quality` | `data.quote_quality` | `"Tight"`, `"OK"`, `"Wide"`, `"Very wide"`, `"One-sided"`, `"No quote"`, `"Crossed"` | Filtering, consistency | |
| `yes_bid_c` | `data.to_cents(yes_bid_dollars)` | YES bid in exact integer cents | Consistency checker | `Decimal`-based, never float |
| `yes_ask_c` | `data.to_cents(yes_ask_dollars)` | YES ask in exact integer cents | Consistency checker | |
| `last_c` | `data.to_cents(last_price_dollars)` | Last price in cents | Consistency fallback | |
| `display_c` | `data.display_cents(...)` | Best display price in cents | Consistency display test | |
| `yes_bid_size` | `yes_bid_size_fp` | Order size at YES bid | Executable test, tradability | No NO-side size fields exist on Kalshi |
| `yes_ask_size` | `yes_ask_size_fp` | Order size at YES ask | Executable test | |
| `no_bid_pct` / `no_ask_pct` | `no_bid_dollars` / `no_ask_dollars` | NO-side prices as % | Detail tables, Buy NO price | Real API fields; `no_ask == 1 − yes_bid` by construction |
| `no_bid_c` / `no_ask_c` | `data.to_cents(no_bid/ask_dollars)` | NO-side prices in cents | Buy NO price in action plan | |
| `volume` | `volume_fp` | Total traded volume | Volume filter, representative selection | |
| `open_interest` | `open_interest_fp` | Open interest | Detail tables | |
| `status` | market `status` | `"active"`, `"finalized"`, `"settled"`, … | Tradability check | Only `"active"` markets are open |
| `time_value` | `occurrence_datetime` or `close_time` | Market time | Detail display | Match kind uses occurrence; others use close |
| `time_kind` | derived | `"Match time"`, `"Close time"`, or `"Expiration"` | Display label | |
| `kalshi_url` | `data.kalshi_market_url(...)` | Deep link to the event's Kalshi page | Link column in tables | `/<series_lower>/<slug>/<event_lower>` |
| `series` | `series_ticker` | Series identifier | Debug, grouping | |
| `event_ticker` | event `event_ticker` | Event identifier | Debug, link audit | |
| `market_ticker` | market `ticker` | Market identifier | Debug, dedup | |
| `event_title` / `market_title` | raw API fields | Original titles | Debug | |
| `raw_yes_bid` / `raw_yes_ask` / `raw_no_bid` / `raw_no_ask` / `raw_last` | market fields | Raw price strings | Debug expander | Preserved as strings |
| `rules_primary` | market `rules_primary` | Settlement rules text | Rule-flag comparison | Used to detect nuance token differences |

---

## 5. Contract Discovery Logic

### Data sources

All data comes from the Kalshi public market-data REST API (`https://external-api.kalshi.com/trade-api/v2`). No authentication is required. Three endpoints are used:

- `/series` — list all series (used in full-scan mode to discover series for the active sport)
- `/events?series_ticker=X&with_nested_markets=true` — events with nested markets for a series
- `/series/<ticker>` — series metadata (title, used for URL slug generation)

### Discovery modes

**Default fast scan (`cfg.default_series`):** Fetches the sport's configured default series from
`SportConfig.default_series`. For tennis: `KXATPMATCH`, `KXWTAMATCH`, `KXATPADVANCE`, `KXWTAADVANCE`,
`KXFOMEN`, `KXFOWOMEN` (6 series). For NBA: `KXNBA`, `KXNBAEAST`, `KXNBAWEST`, `KXNBAPLAYOFF`,
`KXNBASERIES`, `KXNBAGAME` (6 series). For WNBA: `KXWNBA`, `KXWNBAPLAYOFF`, `KXWNBASEMIFINAL`,
`KXWNBAFINAL`, `KXWNBASERIES`, `KXWNBAGAME` (6 series). (`kalshi_client.get_events_for_series`,
`fetch.fetch_contracts`). The NiceGUI dashboard's "Scan now" button and `api.fetch_dep` use core series
only (`scan_all=False`).

**Full dynamic scan (`kalshi_client.discover_series_for_sport(cfg)`):** Lists all Kalshi series, filters
to those starting with the sport's `series_prefixes` (or matching `winner_tickers`). For tennis: prefixes
`KXATP`, `KXWTA`. Returns ~61 series for tennis. Triggered by the "Scan all … series" checkbox in the
Streamlit app. Takes ~20 seconds. `discover_tennis_series()` is a back-compat wrapper over this generic
function.

### Tournament stamping (no French Open gate)

`build_contracts` includes **ALL events** for the active sport — there is no French Open gate. Every
event is stamped with a never-empty `tournament` grouping key via `data.tournament_of`, which resolves
in priority order:

1. **Primary:** Cleaned `product_metadata.competition` field.
2. **Winner-ticker fallback:** If competition is absent, infer from the series ticker.
3. **Title keyword:** If neither above, extract a keyword from the event title.
4. **Unknown:** `"Unknown · <competition|event_ticker|event_title|series_ticker>"` (never empty).

`tournament_source` records which path was taken. `build_checks` groups by `(player_key, tournament)` so
ladders never mix across tournaments and a fallback never collapses to `""`.

`is_french_open_event` still exists as a helper (uses `FO_KEYWORDS` + `FO_WINDOW` date fallback), but
it **no longer gates** `build_contracts`.

### Rate limiting and concurrency

- The client uses a process-wide min-interval limiter (`_throttle`) capped at `config.MAX_RPS` (5 req/s, ~25% of Kalshi's 20 req/s Basic tier limit).
- Fan-out to multiple series is concurrent via `ThreadPoolExecutor(max_workers=CONCURRENCY=4)`.
- A `Retry-After`-aware exponential backoff handles 429 and 5xx responses.
- Pagination is guarded: `get_paginated` raises `KalshiError` if `MAX_PAGES=100` is reached with a cursor still pending — partial data is never silently returned.

### Series titles for URL generation

`kalshi_client.get_series_titles(tickers)` fetches the human title for each series concurrently. Titles
are used to generate URL slugs (`data._slugify`). A missing title degrades gracefully to the series-level
URL rather than crashing.

### Raw data preservation

Every contract row preserves raw price strings (`raw_yes_bid`, `raw_yes_ask`, etc.), the original market
and event tickers, raw titles, and the full `rules_primary` text for debugging.

---

## 6. Participant Grouping Logic

### Preferred key: stable identity UUID (`IdentityResolver`)

Each sport defines an `IdentityResolver` in its `SportConfig.identity`. The resolver tries
`candidate_paths` in order for a stable UUID:
- **Tennis:** `custom_strike.tennis_competitor`
- **NBA / WNBA:** `custom_strike.basketball_team`

When a UUID is found, it is used directly as `player_key` (`player_key_source = "competitor_uuid"`,
`mapping_confidence = "high"`). The same UUID links a participant's contracts across all series and rounds.

### Name fallback

When no UUID is present across all candidate paths, `player_key = yes_sub_title.casefold()` (the
normalized display name). This is `player_key_source = "name_fallback"`, `mapping_confidence = "low"`.
Name-based keys can drift between markets or collide between same-named players.

### Display name resolution (`data.display_player_name`)

Priority order (implemented in `data.display_player_name`):

1. **Alias override:** `config.NAME_ALIASES.get(player_key)` — keyed by competitor UUID, currently empty but patchable for correcting drifted names.
2. **Clean source name:** `player_name_raw` (`yes_sub_title`) is shown verbatim if it contains any uppercase or a space.
3. **Titleized fallback:** A bare lowercase token is title-cased via `data._titleize_fallback`.

### Grouping in the consistency checker

`consistency.build_checks` groups by `(player_key, tournament)` — never by the display name and never
mixing tournaments. This is enforced by the test
`test_build_checks_groups_by_player_key_not_display_name`.

### UI player selector disambiguation

When two players share the same display name but different keys, `app.py` appends a 6-character key
suffix: `"Alex Smith [uuid-o]"` vs `"Alex Smith [uuid-t]"`.

### Known failure modes

- Name-fallback keys (`low` confidence) can collide across markets or drift if Kalshi changes name formatting.
- A player with only a name fallback key may appear as a duplicate if the same player's name is formatted differently in different series.
- `NAME_ALIASES` is currently empty (`config.py`). It exists as a patch point for correcting known drift without touching application code.

---

## 7. Sport Abstraction (`sports.py`) and Contract Classification

### The `SportConfig` abstraction

All sport-specific logic is encapsulated in `sports.SportConfig` — a frozen dataclass holding everything
the engine needs to handle one sport. The engine (`data.py`, `consistency.py`, `dutchbook.py`) calls
methods on the config; it never hardcodes a sport. Adding a sport means calling
`sports.register(SportConfig(...))`.

A `SportConfig` holds:
- `sport_id`, `label`, `emoji` — identity and display
- `series_prefixes`, `default_series`, `winner_tickers` — which series belong to this sport
- `identity: IdentityResolver` — resolves a stable participant key from a market dict (tries `candidate_paths` in order, then falls back to normalized display name)
- `ladder: LadderSpec` — the containment ladder: `node_order` (broad→deep tuple), `adjacent_pairs` (child/parent tuples), `match_stage_to_node`, `advance_stage_to_node`
- `category_labels: dict[str, str]` — user-facing category strings keyed by family
- `round_patterns: tuple[tuple[str, str], ...]` — ordered `(label, regex)` pairs for stage extraction (most-specific first)
- `stage_rank: dict[str, int]` — integer sort keys per stage label
- `ladder_families: frozenset[str]` — which families participate in ladder checks
- `match_family: str` — the head-to-head family name (`"match"` for all three sports)
- `divisions: dict[str, list[str]]`, `division_label: str` — UI split (tennis: `{"Women": ["WTA"], "Men": ["ATP"], "Both": ...}`; NBA/WNBA: empty)
- `family_fn`, `stage_fn`, `node_fn`, `division_fn` — small per-sport callables

The `SportConfig.classify(series_ticker, market_dict)` convenience method returns a `MarketClassification`
combining family, stage, stage_rank, ladder_node, eligible_for_ladder_checks, confidence, and reason.

The registry functions are: `sports.register(cfg)`, `sports.get_sport(sport_id)`, `sports.all_sports()`,
`sports.sport_for_series(series_ticker)`. Unknown series resolve to `sports.UNKNOWN` (an explicit
unsupported config) — **never silently to tennis**.

### Registered sports

**Tennis (`sports.TENNIS`, `sport_id="tennis"`):**
- Prefixes: `KXATP`, `KXWTA`. Winner tickers: `KXFOMEN`, `KXFOWOMEN`, `KXFOMENSINGLES`, `KXFOWOMENSINGLES`, `KXFOPENMENSINGLE`, `KXFOPENWMENSINGLE`.
- Identity: `custom_strike.tennis_competitor` (stable UUID).
- Ladder: `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`.
- Families: `match`, `advance`, `winner`, `set_winner`, `exact_score`, `grand_slam`, `other`.
- Division: `Tour` (ATP/WTA).

**NBA (`sports.NBA`, `sport_id="nba"`):**
- Prefix: `KXNBA`. Default series: `KXNBA`, `KXNBAEAST`, `KXNBAWEST`, `KXNBAPLAYOFF`, `KXNBASERIES`, `KXNBAGAME`.
- Identity: `custom_strike.basketball_team` (stable UUID).
- Ladder: `Reach Playoffs ⊇ Win Conference ⊇ Win Championship`.
- Families: `winner` (KXNBA), `advance` (KXNBAEAST/WEST/PLAYOFF), `match` (KXNBASERIES, playoff series head-to-head), `game` (KXNBAGAME — single game, **not laddered**), `other`.
- Division: none.

**WNBA (`sports.WNBA`, `sport_id="wnba"`):**
- Prefix: `KXWNBA`. Default series: `KXWNBA`, `KXWNBAPLAYOFF`, `KXWNBASEMIFINAL`, `KXWNBAFINAL`, `KXWNBASERIES`, `KXWNBAGAME`.
- Identity: `custom_strike.basketball_team` (same as NBA).
- Ladder (modern single-bracket format): `Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship`.
- Families: `winner`, `advance`, `match`, `game`, `other`.
- Division: none.

### Family classification (`SportConfig.family_of`)

The family (equivalent to the old `kind` field — `kind` is an alias for `family` on
`MarketClassification`) is derived from the series ticker by a sport-specific callable. Back-compat:
`data.classify_kind(ticker)` delegates to the sport's `family_fn` via the sport registry.

**Tennis family rules (evaluated in order):**
```
winner-tickers set → "winner"
"ADVANCE" in ticker → "advance"
"EXACTMATCH" or "EXACTSCORE" → "exact_score"   (before generic MATCH)
"SETWINNER" → "set_winner"
"GRANDSLAM" → "grand_slam"
"MATCH" → "match"
else → "other"
```

**NBA family rules:** Derived directly from the series ticker (not title-extracted stage): `KXNBA` → `winner`; `KXNBAEAST/WEST/PLAYOFF` → `advance`; `KXNBASERIES` → `match`; `KXNBAGAME` → `game`; else → `other`.

**WNBA family rules:** Same pattern as NBA: `KXWNBA` → `winner`; `KXWNBAPLAYOFF/SEMIFINAL/FINAL` → `advance`; `KXWNBASERIES` → `match`; `KXWNBAGAME` → `game`; else → `other`.

### Category labels (user-facing)

| family (kind) | Tennis category | NBA/WNBA category |
|---|---|---|
| `match` | Match result | Playoff series |
| `advance` | Stage advancement | Advancement (reach a stage) |
| `winner` | Tournament winner | Championship |
| `set_winner` | Set winner | — |
| `exact_score` | Exact score | — |
| `grand_slam` | Grand Slam (season) | — |
| `game` | — | Game (not laddered) |
| `other` | Other | Other |

### Division classification (`data.tour_of` / `SportConfig.division_of`)

Tennis uses explicit sets for winner-ticker variants where substring logic would misfire:
- `_WOMEN_WINNER_TICKERS = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}` → `"WTA"`
- `_MEN_WINNER_TICKERS = {"KXFOMEN", "KXFOMENSINGLES", "KXFOPENMENSINGLE"}` → `"ATP"`
- Then substring: `startswith("KXWTA")` or `"WOMEN" in t` → `"WTA"`; else `"ATP"`

The explicit set check catches `KXFOPENWMENSINGLE` which contains `"MEN"` as a substring of `"WOMEN"`. NBA/WNBA have no division — `division_of` returns `""`.

### Stage extraction (`sports.extract_round`, `SportConfig.stage_of`)

Each sport defines its own `round_patterns` (ordered `(label, regex)` pairs, most-specific first). The shared helper `sports.extract_round(round_patterns, *texts)` applies them to a joined blob of the market's `title` and `rules_primary`. Word-boundary anchors prevent partial matches. Winner contracts are always stamped `stage = "Champion"`.

Tennis patterns: `Final`, `Semifinal`, `Quarterfinal`, `Round of 16/32/64/128`.
NBA patterns: `Conference Finals` (before generic `Finals`), `Finals`, `Conference Semifinals`, `First Round`.
WNBA patterns: `Finals`, `Semifinals`, `First Round`.

### Uncertain contracts

Contracts whose `family == "other"` or `eligible_for_ladder_checks == False` are included in the data
but excluded from the consistency checker. Contracts whose stage does not map to a tracked ladder node
are emitted as `UNKNOWN_RELATIONSHIP` rows — never silently dropped, never treated as violations.

---

## 8. Quote and Pricing Logic

### Price field formats (live API, since March 2026)

Kalshi prices are fixed-point dollar strings: `"0.6500"` = 65¢. Size fields use `_fp` suffix (also strings). Volume and open interest similarly.

**Never cast a raw price to `float()` directly.** Use `data.to_float` (None-safe, empty→None) for display values or `data.to_cents` (Decimal-based, exact integer) for comparison logic.

### Quote quality labels (`data.quote_quality`)

| Label | Condition |
|---|---|
| `"No quote"` | Both sides None, or `bid == 0.0` and `ask == 1.0` (empty order book) |
| `"One-sided"` | Either bid or ask is None |
| `"Crossed"` | `ask < bid` (malformed book) |
| `"Tight"` | `spread ≤ 5¢` |
| `"OK"` | `spread ≤ 15¢` |
| `"Wide"` | `spread ≤ 30¢` |
| `"Very wide"` | `spread > 30¢` |

A `"Crossed"` book is never used for pricing or executable testing.

### Display price (`data.display_prob` / `data.display_cents`)

1. If YES bid/ask both present and spread ≤ `SPREAD_REASONABLE` (20¢): use midpoint.
2. Else if last trade > 0: use last trade.
3. Else: `None` (blank in the UI — never a fake 50%).

### NO-side prices

Kalshi reports `no_bid_dollars` and `no_ask_dollars` directly. On Kalshi's unified book, `no_ask == 1 − yes_bid` exactly. The app reads the real API fields; the fallback `100 − yes_bid_c` is used only when `no_ask_c` is absent. There are no NO-side size fields on Kalshi — buying NO matches resting YES bids, so the tradable size of a Buy-NO leg is `yes_bid_size`.

### Time labelling

- `kind == "match"` and `occurrence_datetime` present → `time_kind = "Match time"`, `time_value = occurrence_datetime`
- All other cases → `time_kind = "Close time"` or `"Expiration"`, `time_value = close_time or expiration_time`

---

## 9. Edge Detection Logic

### 9a. Opportunity identity schema (Stage 1)

Every opportunity row — both from `consistency.build_checks` and from `dutchbook.find_dutch_books` —
carries four Stage-1 schema fields:

| Field | Description | Values |
|---|---|---|
| `opportunity_id` | Deterministic 16-hex-character SHA-1 prefix; stable across runs and processes | `data.opportunity_id(*parts)` |
| `relationship_type` | Classification of the pair being compared | `"containment_adjacent"` \| `"match_alignment"` \| `"dutch_book"` |
| `bucket` | Dashboard routing | `"actionable"` \| `"blocked"` \| `"near_edge"` \| `"display_signal"` \| `"wide_signal"` \| `"data_quality"` \| `"clean"` |
| `blocked_reason` | REQUIRED field: non-empty **IFF** `bucket == "blocked"`; `""` otherwise | Plain-English blocker text; enforced by tests and the store integration test |

**`opportunity_id` recipe (`data.opportunity_id`):**

`sha1("|".join(parts))[:16]` where `None` normalizes to `""`. Both callers use positional, stable
recipes:

- **Containment adjacency:** `opportunity_id("containment_adjacent", player_key, tournament, child_node, parent_node)`
- **Match alignment:** `opportunity_id("match_alignment", player_key, tournament, node, node)` (or for unmapped: includes `event_ticker` + `stage` in a single part string)
- **Dutch book:** `opportunity_id(CHECK_TYPE, event_ticker, sorted_key_a, sorted_key_b)` — leg-order-independent (keys sorted before hashing)

**Invariant (test-enforced):** `bool(blocked_reason) == (bucket == "blocked")` for every row in every
persisted snapshot.

### 9b. Containment-ladder consistency checker (`consistency.py`)

#### Containment ladder

The consistency checker operates on the sport's containment hierarchy as defined in its `LadderSpec`. For tennis:

```
Reach Semifinal ⊇ Reach Final ⊇ Win Tournament
```

For NBA:
```
Reach Playoffs ⊇ Win Conference ⊇ Win Championship
```

For WNBA:
```
Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship
```

A deeper outcome must not price higher than a broader one. `build_checks` groups by
`(player_key, tournament)`, resolves the sport per group, and checks adjacent pairs from the group's
`LadderSpec`. Back-compat aliases `NODE_ORDER`, `ADJACENT_PAIRS`, `MATCH_STAGE_TO_NODE`,
`ADVANCE_STAGE_TO_NODE` at the module level reference the tennis ladder.

#### Match-alignment equivalence

When a participant has both a market source (advance/winner) and a match source for the same node, the
two are compared as equivalent. Example: "Quarterfinal win ≡ Reach Semifinal". This check runs in both
directions (forward and reverse).

These comparisons always carry a `rule_flag` (`RULE_CHECK_REQUIRED` or `RULE_MISMATCH`) because
settlement rules may differ between the two markets. The app never calls these "arbitrage" — they are
"executable inconsistencies, rule-dependent."

#### Classification logic (`consistency._classify`)

Two independent tests run on every pair:

**Executable test** (requires firm bid/ask + positive size on both legs):
- Forward: `child_bid_c > parent_ask_c` and both sizes > 0 → `EXECUTABLE_VIOLATION`
- Reverse (equivalence only): `parent_bid_c > child_ask_c` and both sizes > 0 → `EXECUTABLE_VIOLATION`
- The winning direction (higher gap) is selected; the reason quotes the actual legs.

**Display test** (requires `display_c` on both legs):
- `child_display_c > parent_display_c` by more than `DISPLAY_TOL_C` (1¢) → `DISPLAY_VIOLATION`

**Status precedence:**

| Condition | Status | Group |
|---|---|---|
| Firm cross + sizes > 0 | `EXECUTABLE_VIOLATION` | Broken |
| Firm cross + no size + display cross | `DISPLAY_VIOLATION` | Warning |
| Firm cross + no size + no display cross | `QUOTE_SIZE_MISSING` | Missing data |
| No firm cross + display cross | `DISPLAY_VIOLATION` | Warning |
| No firm bid/ask on a leg | `MISSING_QUOTE` | Missing data |
| Firm book, both wide/very wide | `WIDE_QUOTE` | Warning |
| Ordered, Tight/OK quotes | `CLEAN` | Clean |
| Either layer absent | `MISSING_LAYER` | Missing data |
| Round not tracked | `UNKNOWN_RELATIONSHIP` | Unknown relationship |

#### Action plan (buy-only)

Every inconsistency of status `EXECUTABLE_VIOLATION`, `DISPLAY_VIOLATION`, or `QUOTE_SIZE_MISSING` is expressed as two BUYs:
- **Buy YES** on the broader (parent) leg at its YES ask price
- **Buy NO** on the deeper (child) leg at its NO ask price (`no_ask_c`, fallback `100 − yes_bid_c`)

`WIDE_QUOTE` gets **no action** — it is watchlist-only.

#### Tradability

`tradable_now` is set to `"Yes"` only when:
- Status is `EXECUTABLE_VIOLATION`
- Both legs have `status == "active"`
- No rule flag (or `"Yes — rule-dependent"` for equivalence pairs)

All other cases: `"No"`. Plain-English blockers from `glossary.BLOCKERS` explain why.

#### Near-edge watchlist (`bucket_of`)

`CLEAN` rows whose firm executable gap (`child_bid_c − parent_ask_c`) is in `[NEAR_EDGE_MIN_C, 0]`
(default `[-5, 0]`) cents, and whose worst quote quality is `"Tight"` or `"OK"`, appear in the
near-edge watchlist. No buy instruction is shown.

#### Profit calculation

For `EXECUTABLE_VIOLATION` only:
- `exec_gap_c` = gap in cents (child bid − parent ask for forward, or parent bid − child ask for reverse)
- `exec_min_size` = `min(long_leg_size, short_leg_size)`
- `exec_max_profit_dollars` = `exec_gap_c × exec_min_size / 100` (gross, before fees/slippage)

These fields are `None` for all other statuses.

---

### 9c. Dutch-book / MECE detector (`dutchbook.py`)

A **separate check family** from the containment ladder, implemented in its own Streamlit-free module. A dutch book is an executable arbitrage (not merely an "inconsistency" — the legs are outcomes of the **same event** and settle together, so no rule caveat applies) on a mutually-exclusive-and-exhaustive set of binary markets.

#### What it detects

Currently the **2-outcome case only**: any event with **exactly two distinct-participant markets**
(head-to-head match/series OR a single per-game market for draw-free sports). The two markets are
mutually exclusive and exhaustive by construction for draw-free sports, so the pair is MECE.

**Two directions, each a pair of BUYS (never "sell"):**
- **Underround → Buy YES both:** `yes_ask_A + yes_ask_B < 100¢`. Locked profit per unit = `100 − cost`.
- **Overround → Buy NO both:** `no_ask_A + no_ask_B < 100¢` (with `100 − yes_bid` fallback). Locked profit per unit = `100 − cost`.

Because `bid ≤ ask`, the two directions are mutually exclusive — at most one fires per event.

**Eligible event families:** The sport's `match_family` (tennis `"match"`, NBA/WNBA `"match"` = playoff
series head-to-head) **plus** `"game"` (NBA/WNBA single per-game markets). Props, winner, advance
markets are NOT included. Unknown series (`sports.UNKNOWN`) are excluded. The exactly-2-distinct-participants guard in `_detect_pair` is the real MECE safety net.

#### API

`dutchbook.find_dutch_books(rows: list[dict]) -> list[dict]`
- Accepts the output of `df.to_dict("records")` — NaN-safe.
- Groups `match`/`game` rows by `event_ticker`.
- Returns ≤ 1 finding per event, sorted strongest-edge-first (`exec_gap_c` descending, tiebreak on `event_ticker`).
- Each finding has status `EXECUTABLE_DUTCH_BOOK`, `direction` (`"underround"` or `"overround"`), `tradable_now`, `blockers`, two-leg action plan (`action_1_*`, `action_2_*`), and the Stage-1 identity fields (`opportunity_id`, `relationship_type`, `bucket`, `blocked_reason`).

#### One status: `EXECUTABLE_DUTCH_BOOK`

Defined as `dutchbook.EXECUTABLE_DUTCH_BOOK = "EXECUTABLE_DUTCH_BOOK"`. This is distinct from
`EXECUTABLE_VIOLATION` so ladder semantics stay separate; `consistency.STATUS_GROUP` maps it to
`"Broken"`. `consistency.bucket_of` routes it: actionable if `tradable_now == "Yes"`, else blocked.
It is a true arbitrage (same event, both legs settle together) → no rule caveat.

#### Tradability

`tradable_now = "Yes"` when both legs have positive size **and** both markets are `"active"`. No rule caveat.

#### Sizes

Buy-YES leg size: `yes_ask_size`. Buy-NO leg size: `yes_bid_size` (buying NO matches resting YES bids on Kalshi's unified book). Tradable units = `min(leg_a_size, leg_b_size)`.

#### Profit fields

Same schema as containment rows: `exec_gap_c`, `exec_min_size`, `exec_max_profit_dollars` (gross, before fees/slippage). `cost_c` (combined cost of both legs) is added.

#### Engine integration

Detection lives entirely in `dutchbook.py`. The only `consistency.py` touches are: one `bucket_of`
branch and a `STATUS_GROUP` entry. The Streamlit UI renders a **dedicated "Dutch-book arbitrage — match
& game books" section**; the NiceGUI dashboard shows all Dutch-book findings in the unified Actionable/Blocked tables.

---

## 10. Snapshot Store (`store.py`) — Stage 1

`store.py` is a single-writer local SQLite store that persists one complete snapshot of opportunity rows
per scan. Pure standard library (`sqlite3` + `json`) — no Streamlit, no pandas import (DataFrames are
duck-typed via `.to_dict()`), independently unit-testable against a tmp file. No multi-user / shared
locking / server: designed for single-process local use.

### Schema (v2)

Two tables:

```sql
CREATE TABLE snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,    -- original timestamp text (display)
    fetched_ts REAL NOT NULL,    -- epoch seconds UTC (ordering / retention / windows)
    meta       TEXT             -- per-scan coverage metadata as JSON (v2; NULL for v1 rows)
);
CREATE TABLE opportunities (
    snapshot_id       INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    opportunity_id    TEXT NOT NULL,
    relationship_type TEXT,
    bucket            TEXT,
    status            TEXT,
    blocked_reason    TEXT,
    data              TEXT NOT NULL   -- full row as JSON (NaN→null, tuples→lists)
);
```

Promoted columns (`PROMOTED_COLUMNS = ("opportunity_id", "relationship_type", "bucket", "status", "blocked_reason")`) are indexed SQL columns for cheap lifecycle/backlog filtering; the full row always round-trips in the `data` JSON blob — no field is ever lost.

### Schema versioning and migration (`_migrate`)

`PRAGMA user_version` holds the schema version (currently **v2**). `_migrate` runs on every connection:

- **Fresh DB (version 0):** Creates the full current schema (including `meta`) and sets `user_version = 2`.
- **Existing v1 DB:** Upgrades via `ALTER TABLE snapshots ADD COLUMN meta TEXT` and sets `user_version = 2`.
- **v2 DB:** No-op.
- **Newer than supported:** Hard error — never downgrade-write.

### Public API

| Function | Signature | Description |
|---|---|---|
| `write_snapshot` | `(fetched_at, opps, *, meta=None, db_path=None) -> int` | Persist one snapshot; apply retention; return `snapshot_id`. `opps` may be a DataFrame or list of dicts. |
| `latest` | `(db_path=None) -> dict \| None` | The single newest snapshot, or `None` if empty. |
| `latest_two` | `(db_path=None) -> list[dict]` | Two most recent, ordered **oldest→newest** (`[prev, cur]` for diffing). Fewer than two → shorter list. |
| `snapshots_since` | `(window, db_path=None) -> list[dict]` | All snapshots within `window` (timedelta or seconds) of the **newest**, oldest→newest. Boundary is inclusive. |

**Snapshot dict schema:** `{snapshot_id, fetched_at, fetched_ts, meta, opportunities: [...]}`

**Retention:** Relative to the newest stored snapshot (not wall-clock `now`) — reproducible in tests.
Cap: `config.SNAPSHOT_RETENTION_SECONDS` (30 hours — covers the 24h backlog window plus margin).

**NaN-safety:** `_clean` converts float NaN → `None`, tuples → lists, numpy scalars → Python scalars before JSON serialization. Nothing exotic ever reaches the DB.

**Time handling:** `_to_epoch` accepts a datetime, ISO string, the `load_contracts` display string (`"YYYY-MM-DD HH:MM:SS UTC"`), or a raw epoch number. Raises `ValueError` on an unparseable input — never stores an unorderable timestamp.

**Config:** `config.SNAPSHOT_DB_PATH` (default `"snapshots.db"`, relative to process working dir); `config.SNAPSHOT_RETENTION_SECONDS` (30 hours). The `.db` file is gitignored.

---

## 11. Cross-Sport Scanner (`scanner.py`) — Stage 2

`scanner.py` provides two functions that aggregate the entire opportunity universe across all registered sports into one ranked frame.

### `UNIFIED_COLUMNS`

The 26-column schema both row shapes (containment checks + Dutch-book findings) are normalized onto:

```
"sport", "sport_label", "source",
"name", "detail", "tournament", "tour",
"action_1_text", "action_2_text",
"action_1_price_c", "action_2_price_c", "cost_c",
"exec_gap_c", "exec_min_size", "exec_max_profit_dollars",
"bucket", "status", "tradable_now", "blocked_reason",
"market_status", "rule_flag",
"relationship_type", "opportunity_id",
"ticker_1", "ticker_2", "url", "url_2"
```

`source` is `"containment"` or `"dutch_book"`. `market_status` (active/inactive) and `rule_flag` are lifecycle-diff inputs for Stage 3. `action_1_price_c` / `action_2_price_c` / `cost_c` / `ticker_1` / `ticker_2` / `url_2` are explanation-panel fields for the NiceGUI dashboard.

### `unified_opportunities(fetch_fn, *, store_writer=None, fetched_at=None)`

Loops `sports.all_sports()`, runs `consistency.build_checks` + `dutchbook.find_dutch_books` per sport,
normalizes both row shapes onto `UNIFIED_COLUMNS`, stamps `sport`, and sorts by
`(BUCKET_PRIORITY, -exec_gap_c, opportunity_id)`. Returns `(unified_df, per_sport_errors)`.

- **Dependency-injected fetch:** `fetch_fn(sport_id) -> DataFrame | None`. The app passes
  `load_contracts`; tests pass a stub; the scanner never imports `app`, `streamlit`, or
  `kalshi_client`.
- **Partial-failure tolerant:** A fetch or processing error for one sport is recorded in
  `per_sport_errors` and that sport is skipped — never blanks the rest.
- **Store write injected:** If `store_writer` is given, the result is persisted via
  `store_writer(fetched_at, frame)`.

### `run_scan(fetch_fn, *, fetched_at=None)`

The service entry point. `fetch_fn(sport_id)` returns `fetch.fetch_contracts`'s 7-tuple
`(df, _fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown)`. Aggregates
coverage across all sports and reuses `unified_opportunities` over the already-fetched frames. Returns
`(unified_df, coverage)` where `coverage` carries scan-wide counts + per-series / per-sport errors.

**`BUCKET_PRIORITY` ranking:** `actionable=0`, `blocked=1`, `near_edge=2`, `display_signal=3`,
`wide_signal=4`, `data_quality=5`, `clean=6`. Lower = surfaced first.

---

## 12. Lifecycle Engine (`lifecycle.py`) — Stage 3

Pure snapshot-diff functions with no imports of `store`, `streamlit`, or `kalshi_client`. The caller
reads snapshots from the store and passes them in — all functions are side-effect-free and independently
unit-testable. State is **derived** from the persisted snapshot history; there are no extra tables.

A snapshot dict is `{"fetched_at", "fetched_ts", "opportunities": [row, ...]}` as returned by the
store. All functions defensively sort snapshots oldest→newest before processing.

### §8 — New-actionable alerts

```python
new_actionable(prev, cur) -> list[dict]
```

Returns rows actionable in `cur` but absent from `prev`'s actionable set. **`prev is None` → `[]`** —
a fresh start never floods false-new alerts.

```python
first_seen(snapshots, opportunity_id, *, actionable_only=False) -> float | None
```

Numeric `fetched_ts` (epoch) of the earliest snapshot containing the id. `actionable_only=True` restricts to snapshots where the row is in the actionable bucket. Returns `None` if not found.

```python
persisting_new_actionable(history, window_s, *, now_ts=None) -> list[dict]
```

Rows actionable in the latest snapshot whose first-actionable time is within `window_s` of `now_ts` —
the banner-persistence set. `history` must be the full retained history (not pre-sliced) so a
still-actionable opportunity older than the window is correctly excluded rather than looking falsely
new. `window_s is None` → falls back to single-transition `new_actionable` over the last two snapshots.

### §9 — Blocked-change detection

```python
blocked_change(prev, cur) -> list[dict]
```

For ids present in both snapshots, emits when the row enters/leaves `blocked` OR changes while blocked.
Returns nothing when neither snapshot is blocked and nothing changed.

**`changes` dimensions** (the "what changed" set):
- `"blocker"` — `blocked_reason` text changed
- `"price"` — `exec_gap_c` changed (NaN-safe)
- `"liquidity"` — `exec_min_size` changed (NaN-safe)
- `"status"` — opportunity `status` string changed
- `"market_status"` — derived market status changed
- `"tradable_now"` — `tradable_now` string changed
- `"rule_flag_changed"` — `rule_flag` changed

`transitioned=True` when the row moved into or out of the blocked bucket.

### §10 — Recently-actionable backlog

```python
recently_actionable(snapshots, *, now_ts=None) -> list[dict]
```

Opportunities actionable in SOME snapshot in the window but **not** in the latest. `snapshots` is the
windowed history (`store.snapshots_since(window)`). Returns §10 fields with numeric `became_ts`,
`left_ts`, `duration_s`, and `reason_left`, ordered most-recently-left first.

**`reason_left` precedence:** `"disappeared"` (id gone from latest) → `"leg inactive"` (market_status
inactive) → `"went blocked"` (bucket == blocked) → `"went clean"`.

---

## 13. FastAPI Engine API (`api.py` + `serve.py`) — Stage 4

### FastAPI app (`api.py`)

`api.app = FastAPI(title="Kalshi opportunity engine", version="4.0")`. Handlers are **thin** — no
detection logic; all computation delegated to the engine (`store`, `lifecycle`, `scanner`).

**Dependencies (overridable via `app.dependency_overrides` in tests — no network required):**

| Dependency | Default | Test override |
|---|---|---|
| `db_path_dep()` | `None` (→ `config.SNAPSHOT_DB_PATH`) | tmp file path |
| `fetch_dep()` | Real network fetch (`fetch.fetch_contracts`, core series, `scan_all=False`) | Stub 7-tuple function |

### Pydantic response models

| Model | Fields |
|---|---|
| `Opportunity` | `opportunity_id`, `sport`, `sport_label`, `source`, `name`, `detail`, `tournament`, `tour`, `action_1_text`, `action_2_text`, `exec_gap_c`, `exec_min_size`, `exec_max_profit_dollars`, `bucket`, `status`, `tradable_now`, `blocked_reason`, `market_status`, `rule_flag`, `relationship_type`, `url` |
| `Coverage` | `meta_present`, `fetched_at`, `data_age_seconds`, `stale`, `scanned`, `loaded`, `failed`, `excluded`, `skipped_no_name`, `sport_errors`, `series_errors` |
| `BacklogItem` | `opportunity_id`, `sport`, `name`, `became_ts`, `left_ts`, `duration_s`, `reason_left`, `last_edge_c`, `last_action_1_text`, `last_action_2_text`, `current_status`, `current_bucket`, `url` |
| `BlockedChange` | `opportunity_id`, `prev_bucket`, `cur_bucket`, `transitioned`, `changes` |
| `Alerts` | `new_actionable: list[Opportunity]`, `blocked_changes: list[BlockedChange]` |
| `ScanResult` | `skipped`, `fetched_at`, `opportunities`, `scanned`, `loaded`, `failed`, `excluded`, `skipped_no_name`, `sport_errors`, `series_errors` |

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Returns `{"status": "ok"}`. Always fast — no DB read. |
| `GET` | `/opportunities` | Latest snapshot's opportunities; filter by `?sport=`, `?bucket=`, `?status=`. Returns `list[Opportunity]`. |
| `GET` | `/opportunities/{id}` | Single opportunity by `opportunity_id`; 404 if not in latest snapshot. |
| `GET` | `/backlog` | Recently-actionable backlog; `?window_s=` (default `config.BACKLOG_WINDOWS["1 hour"]`). Returns `list[BacklogItem]`. |
| `GET` | `/coverage` | Latest snapshot's coverage metadata + data age/stale; `meta_present=False` when store is empty or no meta. Returns `Coverage`. |
| `GET` | `/alerts` | New-actionable (§8) + blocked-change (§9) diffs; `?persistence_s=` for banner persistence (default = single-transition). Returns `Alerts`. |
| `POST` | `/scan` | Run a scan and persist; `?force=true` bypasses the TTL guard. Returns `ScanResult`. |

### POST /scan — TTL guard (store-backed, sane after restart)

The TTL guard reads the latest stored snapshot's `fetched_ts` against `config.SCAN_MIN_INTERVAL_SECONDS`
(30s). If the newest snapshot is younger than the minimum, the scan is skipped — `ScanResult.skipped=True`
is returned and **nothing is written** (no duplicate snapshot). `force=True` overrides the guard. The
guard reads the store (not process memory), so it works correctly after a restart.

### `serve.py`

`serve.py` mounts NiceGUI onto the FastAPI app and runs uvicorn:

```python
ui.run_with(api.app, mount_path="/", storage_secret=_storage_secret)
uvicorn.run(api.app, host=config.API_HOST, port=config.API_PORT)
```

The NiceGUI storage secret is read from `NICEGUI_STORAGE_SECRET` env var at serve-time (so `config.py`
stays import-free); the config value `NICEGUI_STORAGE_SECRET_FALLBACK` is a clearly-labeled dev
fallback only. Importing `webui.dashboard` registers the `@ui.page('/')` before `ui.run_with`.

**Config:** `config.API_HOST` (default `"127.0.0.1"`), `config.API_PORT` (default `8000`),
`config.SCAN_MIN_INTERVAL_SECONDS` (30s = `REFRESH_TTL`).

---

## 14. NiceGUI Dashboard (`webui/`) — Stage 5

### `webui/engine.py` — in-process accessors

Thin wrappers over `store`, `lifecycle`, and `scanner` so the dashboard stays declarative and the
accessors can be unit-tested without NiceGUI. The dashboard calls the engine **in-process** (not via
self-HTTP); the REST `api.py` is a sibling consumer for external clients.

| Function | Description |
|---|---|
| `latest_opportunities(db_path)` | All opportunities in the latest snapshot (ranked), or `[]`. |
| `opportunities_in_bucket(bucket, db_path)` | Filter latest by bucket. |
| `backlog(window_s, db_path)` | Recently-actionable backlog (§10). |
| `alerts(persistence_s, db_path)` | New-actionable (§8) + blocked-change (§9). |
| `coverage(db_path)` | Latest snapshot coverage + live age/stale; honest on empty or meta-less store. |
| `run_scan_now(db_path)` | Manual trigger: runs `scanner.run_scan` (core series, all sports), persists via `store.write_snapshot`, returns coverage. No TTL guard (that is the API's concern). |

Scan scope is **core series only** (`scan_all=False`) — honest label on the dashboard button: "Scan now (core series)". Full-scan toggle is deferred.

### `webui/dashboard.py` — NiceGUI page

Registered as `@ui.page('/')`. Layout:

- **Controls row:** timezone select, new-actionable banner persistence select, backlog window select, "Show IDs & codes" switch, "⟳ Scan now (core series)" button.
- **Per-second freshness label** (`ui.timer(1.0, tick_age)`): data time, data age (climbs live), stale warning, opportunity count, series scope.
- **New-actionable banner** (`ui.notify` toast on genuinely-new ids since last poll, suppressed on first load) + blocked-change label.
- **"✅ Actionable now"** — sortable `ui.table`, `pagination=15`, single-row selection → opens explanation panel.
- **"⛔ Blocked"** — sortable `ui.table`, `pagination=10`, single-row selection → opens explanation panel.
- **"📉 Recently actionable"** — collapsible `ui.expansion`, backlog `ui.table` with window selector.
- **Explanation panel** (`ui.dialog`) — opened on row click; shows sport, name, source/detail/tournament, leg 1 / leg 2 action text, cost / edge / max units / gross profit, tradable now / relationship type / market status, caveat (if blocked), leg links (clickable), optional IDs/tickers (Show IDs mode).

**Polling cadence:** `ui.timer(config.UI_REFRESH_SECONDS, refresh)` (120s). The "Scan now" button triggers an async `run.io_bound(engine.run_scan_now)` to keep network I/O off the NiceGUI event loop.

**Scan triggers the store-poll cycle:** `do_scan()` calls `engine.run_scan_now()` then `refresh()` to update the tables immediately after the scan completes.

**`explanation_lines(opp, *, show_ids=False)`** is a pure function (no NiceGUI runtime needed) — unit-testable separately.

---

## 15. Streamlit Dashboard and UI Logic (`app.py`)

### Main user workflow

1. Pick a **Sport** (radio, top of sidebar: Tennis / NBA / WNBA).
2. Pick **Contract family** (multiselect — all types default ON). This controls what is **fetched**.
3. The dashboard auto-refreshes on a timer (default 120s; `@st.fragment(run_every=...)`).
4. An always-visible **data-freshness & coverage strip** (`render_freshness()`, on its own 1s fast-tick fragment) shows data time, data age (climbs live), refresh status, and coverage counts.
5. Six summary cards: Actionable now, Gross quoted profit, Blocked, Near-edge, Data-quality issues, Last refreshed.
6. **Actionable now** — firm executable containment-ladder crosses, always visible, not filtered by thresholds.
7. **Dutch-book arbitrage** — 2-outcome match/game books, always visible, not filtered by thresholds.
8. Below: Blocked / Near-edge watchlist (show-toggleable).
9. Further below: Watchlist signals / Data-quality / Non-laddered contracts — all show-toggleable.
10. Player/team detail, Full diagnostics, and Debug are behind the "Advanced: diagnostics & debug" sidebar toggle (default OFF).

### Section layout (top → bottom, `app.py`)

| Section | Description | Filtering applied |
|---|---|---|
| Header caption | Refresh time, contract/comparison count, scan mode | — |
| Freshness strip | Data time · Data age · Refresh status · Coverage (own fragment, 1s tick) | — |
| Summary cards | 6 `st.metric` widgets | Actionable = membership only |
| Export row | Comparisons CSV + raw contracts CSV | — |
| ✅ Actionable now | Firm executable containment-ladder crosses, sorted by gross edge ↓ | Membership only (thresholds do NOT apply) |
| 🎯 Dutch-book arbitrage | 2-outcome match/game books: Buy YES both or Buy NO both | Membership (tournament/event/participant) only |
| ⛔ Blocked | Firm crosses blocked by no-size or inactive legs | Membership + thresholds |
| 📈 Near-edge watchlist | CLEAN rows within 5¢ of crossing on Tight/OK | Membership + thresholds |
| 👀 Watchlist signals | DISPLAY_VIOLATION + WIDE_QUOTE | Membership + thresholds |
| 🧹 Data-quality issues | MISSING_QUOTE/LAYER + UNKNOWN_RELATIONSHIP | Membership + thresholds |
| 🗺 Non-laddered contracts | Game/props/other — not part of ladder (off by default) | Membership + thresholds |
| 🔍 Selected player detail | Chain + spreads + payoff block + action cards + all contracts | Player-specific; behind Advanced toggle |
| 🧪 Full diagnostics | Complete comparison table | Membership + outcome-status filter; behind Advanced toggle |
| 🔧 Debug | Failed series + per-player raw fields + link audit | Player-specific; behind Advanced toggle |

**Note:** The gross-edge opportunity-ranking bar chart (Altair) has been **removed** (Stage 0). The Actionable-now table (sorted by gross edge) is the ranking surface.

### Auto-refresh and freshness

`render_dashboard()` is decorated with `@st.fragment(run_every=run_every)`. Each tick calls `load_contracts` (TTL-cached at `REFRESH_TTL=30s`). Full-scan mode is clamped to a minimum of `FULL_SCAN_MIN_INTERVAL=120s`.

`render_freshness()` is a **separate fragment** running at `FRESHNESS_TICK_SECONDS=1s`. It reads from `st.session_state["_freshness"]` (populated by the main fragment on each real fetch) and re-renders the data-freshness strip every second — so "Data age" climbs live and the stale warning appears without re-fetching.

`app.load_contracts` is now a thin cached wrapper around `fetch.fetch_contracts`; the fetch logic itself lives in `fetch.py` and is shared by the FastAPI API.

### Player detail section

Contains: progression chain table, raw stage-ladder spreads table, per-player buy/no-buy action cards with payoff-by-scenario block (`_payoff_block`, using `consistency.scenario_payoffs`), mapping confidence, expected-vs-found layers, match contracts with confident stage mapping, all contracts with NO prices, JSON and CSV export buttons.

### Status display labels

Internal status strings map to user-facing labels in `app.py:STATUS_LABELS`:
- `EXECUTABLE_VIOLATION` → `"Executable edge"`
- `DISPLAY_VIOLATION` → `"Theoretical inconsistency"`
- `WIDE_QUOTE` → `"Wide quote / watchlist"`
- `MISSING_QUOTE` → `"Missing firm quote"`
- `MISSING_LAYER` → `"Missing layer"`
- `QUOTE_SIZE_MISSING` → `"Blocked: no size"`
- `CLEAN` → `"Consistent"`
- `UNKNOWN_RELATIONSHIP` → `"Unverifiable"`

"Potential edge" is explicitly absent — "edge" is reserved for a positive executable gap.

---

## 16. Filters and Toggles (Streamlit app)

### Filter split (critical design invariant)

- **Membership filters** (`filters.apply_membership`): narrow all sections including Actionable now and the Dutch-book section.
- **Threshold filters** (`filters.apply_thresholds`): narrow everything *except* Actionable now and the Dutch-book section.

| Filter / Toggle | Purpose | Default | Notes |
|---|---|---|---|
| Sport (radio) | Tennis / NBA / WNBA | Tennis | Changes what is fetched; drives the whole dashboard |
| Contract family (multiselect) | All contract types for the sport | All ON | Controls what is FETCHED |
| Auto-refresh (toggle) | Periodic re-fetch | On | Interval selectable: 60/120/300s |
| Refresh interval | Seconds between auto-refresh ticks | 120s | Clamped to 120s for full scan |
| Scan all … series | Fetch all series for the active sport | On (default) | Slows to ~20s+; backed by session_state for read-ahead |
| Division / Tour (radio) | Women / Men / Both (tennis only) | Both | Pre-applied to `df`; NBA/WNBA have no division control |
| Tournament / season (multiselect) | Filter by `tournament` key | All | Membership filter |
| Participant (selectbox) | "All" = no filter; a name = filter dashboard + drive detail section | All | Appends 6-char key suffix on name collision |
| Event / game (multiselect) | Filter by event label | None | Membership |
| Stage / layer (multiselect) | Filter by ladder node or match stage | None | Membership |
| Min traded volume (slider) | Drop contracts below historical traded volume | 0 | Advanced → membership filter |
| Min available size | Threshold: drop comparisons with `exec_min_size < N` | 0 | Threshold |
| Quote quality (select) | All / Tight+OK only / Include wide | All | Threshold |
| Market status (select) | Any / Active only | Active only | Threshold — finalized markets remain visible in Full diagnostics |
| Show blocked opportunities | Show/hide Blocked section | On | Sections expander |
| Show near-edge watchlist | Show/hide Near-edge section | On | Sections expander |
| Show watchlist signals | Show/hide Watchlist signals section | Off | Sections expander |
| Show data-quality issues | Show/hide Data-quality issues section | Off | Sections expander |
| Show non-laddered / unmapped | Show/hide game/props/other contracts | Off | Sections expander |
| Time zone (selectbox) | Display zone for all timestamps | Europe/Lisbon | Display expander; never affects comparison math |
| Show IDs & codes | Reveal series/event/market tickers + participant IDs | Off | Display expander |
| Advanced: diagnostics & debug | Show Full diagnostics + Debug panel | Off | Display expander |
| Show explanations | Help captions in player detail | On | Advanced — data scope |
| Outcome status (select) | Filter Full diagnostics by status group | All | Applies only to the Full diagnostics table |

**Note:** "Min gross edge (¢)" has been **removed** — no minimum edge gate; any positive edge is shown.

---

## 17. Error Handling and Data Quality

| Problem | Current App Behavior | User-Visible Treatment | Notes |
|---|---|---|---|
| Network error on series load | `KalshiError` raised after `MAX_RETRIES` retries | `st.error(...)` + `st.stop()` — page stops | Retry with exponential backoff first |
| One series fails to load | Collected in `errors` list, never dropped | Shown in Debug expander as a warning | Sequential retry pass after concurrent load |
| Per-sport failure in scanner | Recorded in `per_sport_errors`; that sport contributes nothing | Coverage `sport_errors` list; `/coverage` honest | Never blanks other sports |
| Pagination truncated (cursor remaining at cap) | `KalshiError` raised | Same as network error | Silent partial data is never returned |
| Missing competitor UUID | Name-based key fallback | `mapping_confidence = "low"` visible in detail + debug | May drift/collide |
| Empty order book (0.00/1.00) | Treated as "No quote" | `quote_quality = "No quote"`, `display_pct = None` | Never shown as 50% |
| Crossed book (ask < bid) | Quote quality "Crossed"; excluded from executable test | `quote_quality = "Crossed"` in tables | Never produces a midpoint or executable finding |
| One-sided book | `quote_quality = "One-sided"` | Shown in detail; consistency gets `MISSING_QUOTE` | |
| Missing display price on a leg | Display test blocked for that pair | `MISSING_QUOTE` status | |
| Size = 0 on a leg | Executable test blocked; display test can still run | `QUOTE_SIZE_MISSING` or `DISPLAY_VIOLATION` | |
| Duplicate rows for same node/source | Deterministic representative chosen (`_representative_key`) | `duplicate_node_sources` shown in Debug | Higher volume preferred; then lexically smallest ticker |
| Round not in tracked layer map | `UNKNOWN_RELATIONSHIP` emitted | "Unverifiable" in full diagnostics | |
| Unknown series ticker (foreign sport) | `sports.sport_for_series` returns `UNKNOWN`; `build_contracts` skips the row | Counted in `n_excluded_unknown`; shown in Debug | Never silently mis-parsed as tennis |
| NaN from pandas records path | `_isna` / `_num` normalize float NaN to None | Transparent to user | `_clean` in `store.py` also handles NaN → null |
| Malformed market title | `_extract_round` returns `""`, stage stays empty | Contract label uses `_clean_title` fallback | |
| Store schema newer than supported | `RuntimeError` raised by `_migrate` | Propagates to caller | Never downgrade-write |
| Opportunity `blocked_reason` missing on blocked row | Fallback `"not executable now"` used | Invariant preserved | Enforced by test |

---

## 18. Testing and Validation

Tests live in `tests/`. Run with `pytest -q`. No network access in tests (all HTTP is monkeypatched or
synthetic; store tests use tmp files; API tests use FastAPI TestClient with dependency overrides).

**Current test count: 235 tests across 14 files** (`test_data.py`, `test_consistency.py`,
`test_glossary.py`, `test_client.py`, `test_filters.py`, `test_viz.py`, `test_sports.py`,
`test_dutchbook.py`, `test_app.py`, `test_store.py`, `test_scanner.py`, `test_lifecycle.py`,
`test_api.py`, `test_webui.py`).

### Contract Discovery Tests (`test_data.py`)

- `test_pagination_cap_raises_on_remaining_cursor` — paginator raises, never silently truncates
- `test_build_contracts_includes_all_tennis_and_stamps_tournament` — all tennis events included; verifies `tournament` key is always non-empty
- `test_tournament_of_sources_and_never_empty` — all four resolution paths produce a non-empty key

### Participant Grouping / Pricing / Classification Tests (`test_data.py`)

- `test_build_contracts_typing_and_mapping`, `test_display_name_*`, `test_classify_kind_*`, `test_tour_of`, `test_winner_ticker_tour_map_all_variants`
- `test_to_float_parses_and_guards`, `test_to_cents_is_exact_integer`, `test_quote_quality_buckets`
- `test_crossed_book_is_rejected`, `test_build_contracts_parses_no_side_prices_and_deep_link`
- `test_kalshi_market_url_deep_link_and_fallback`, `test_slugify_matches_kalshi_series_slug`

### Edge Logic Tests (`test_consistency.py`)

- `test_executable_violation_requires_cross_and_size`, `test_forward_violation_exposes_profit_and_long_broad_short_deep`
- `test_cross_without_size_downgrades_to_quote_size_missing`, `test_display_violation_is_warning_not_broken`
- `test_equivalence_checks_both_directions`, `test_equivalence_sets_rule_flag`
- `test_crossed_leg_is_not_executable`, `test_sizeless_cross_with_display_cross_stays_display_violation`
- `test_executable_containment_is_buy_yes_parent_buy_no_child`
- `test_tradable_now_no_when_a_leg_is_inactive`, `test_tradable_now_rule_dependent_for_equivalence_executable`
- `test_wide_quote_is_watchlist_only_no_action`
- `test_layer_spreads_full_chain`, `_missing_layer`, `_inverted`, `_missing_price`, `_via_dataframe_records`
- `test_build_player_nodes_duplicate_is_deterministic`
- `test_bucket_*` — all dashboard bucket classifications

### Dutch-book Tests (`test_dutchbook.py`)

- `test_underround_yes_sum_below_100_is_executable` — Buy YES both, direction, cost, gap, sizes
- `test_overround_no_sum_below_100_is_executable` — Buy NO both direction
- Blocked cases: `test_blocked_when_size_is_zero`, `test_blocked_when_one_market_inactive`
- False-positive guards: `test_no_dutch_book_when_sum_equals_100`, same player-key guard, >2 markets guard
- NBA/WNBA per-game eligibility: `test_nba_game_family_is_eligible`
- Sorting: `test_finds_sorted_by_gap_descending`

### Sport Abstraction Tests (`test_sports.py`)

- `test_unknown_series_resolves_to_unknown_not_tennis`, `test_registry_has_tennis_and_nba`
- `test_nba_ladder_families_map_to_nodes`, `test_nba_per_game_is_ineligible_and_excluded`

### Snapshot Store Tests (`test_store.py`)

- `test_write_and_latest_two_round_trip` — oldest→newest ordering
- `test_nan_and_tuple_are_json_safe` — NaN→None, tuple→list
- `test_snapshots_since_window_boundary_is_inclusive` — inclusive boundary; timedelta accepted
- `test_retention_drops_snapshots_older_than_window`
- `test_migration_sets_user_version_and_reopen_works`
- `test_schema_newer_than_supported_raises`
- `test_v1_db_upgrades_to_v2_via_alter` — live v1→v2 migration with old data intact
- `test_fresh_db_is_v2_with_meta_column`, `test_write_snapshot_meta_roundtrips_and_latest`
- `test_to_epoch_parses_display_format`, `test_to_epoch_rejects_unparseable`
- Integration: `test_real_build_checks_frame_round_trips` (NaN gaps + tuple layers + iff-invariant), `test_real_dutch_book_finding_round_trips`

### Scanner Tests (`test_scanner.py`)

- `test_aggregates_multiple_sports_and_stamps_sport` — both detectors, both sports in one frame
- `test_ranking_actionable_first_then_edge` — dutch-book (gap 7) before containment (gap 5) before data-quality
- `test_partial_failure_does_not_blank_other_sports`
- `test_snapshot_written_via_injected_store`
- `test_empty_when_all_sports_empty` — columns intact even when empty
- `test_unified_columns_include_lifecycle_fields`, `test_rows_carry_market_status_and_rule_flag`
- `test_market_status_derived_from_leg_statuses`
- `test_run_scan_aggregates_coverage_and_unifies`, `test_run_scan_records_sport_fetch_failure_without_blanking`
- `test_unified_columns_include_explanation_fields`, `test_explanation_fields_populated_per_source`

### Lifecycle Tests (`test_lifecycle.py`)

- `test_new_actionable_only_freshly_actionable`, `test_new_actionable_suppressed_without_prev`
- `test_first_seen_numeric_and_actionable_only`
- `test_persisting_new_actionable_uses_full_history_not_window_slice`
- `test_blocked_change_classifies_each_dimension` — all 6 change dimensions
- `test_blocked_change_enter_and_leave_are_flagged`
- `test_recently_actionable_went_blocked_with_fields` — became/left/duration/reason
- `test_recently_actionable_reason_precedence` — disappeared → leg inactive → went blocked → went clean
- `test_handles_unordered_snapshot_input` — defensive sort

### API Tests (`test_api.py`)

- `test_healthz_and_docs`, OpenAPI schema reachable
- `test_opportunities_and_filters` — sport/bucket/status query params
- `test_opportunity_by_id_and_404`
- `test_coverage_no_meta`, `test_coverage_with_meta`, `test_coverage_empty_store`
- `test_alerts_new_actionable_and_blocked_changes`
- `test_scan_writes_and_returns_result` — stub fetch, no network
- `test_scan_ttl_skip_and_force` — store-backed TTL guard; force overrides

### NiceGUI / Engine Tests (`test_webui.py`)

- `test_latest_and_bucket_split`, `test_coverage_empty_then_with_meta`, `test_backlog_and_alerts`
- `test_run_scan_now_offline` — monkeypatched fetch_dep, no network
- `test_dashboard_imports_and_registers_page` — smoke test
- `test_opp_row_new_marker_and_fields`, `test_opp_row_handles_none_numbers`
- `test_ts_disp_and_backlog_row`, `test_explanation_lines_content`

### Filter / Viz / App Tests

- `test_filters.py` — `apply_membership` + `apply_thresholds` edge cases
- `test_viz.py` — `payoff_chart_data`, `ladder_prices`
- `test_app.py` — Streamlit `AppTest` smoke test; full render pipeline with mocked network

### Regression invariants

- `EXECUTABLE_VIOLATION` is the only containment-ladder "Broken" status; `EXECUTABLE_DUTCH_BOOK` is the Dutch-book "Broken" status.
- `WIDE_QUOTE` rows get **no** action plan.
- Actionable now is **never** narrowed by threshold filters (Streamlit app).
- Dutch-book section is **never** narrowed by threshold filters (Streamlit app).
- `build_checks` groups by `(player_key, tournament)`, never display name.
- An empty `0.00/1.00` book is **never** treated as a price.
- Pagination truncation raises rather than silently returns partial data.
- Unknown series resolve to `UNKNOWN`, never silently to tennis.
- `bool(blocked_reason) == (bucket == "blocked")` for every opportunity row (store integration test enforces).
- `opportunity_id` is deterministic: identical inputs → identical hash across runs and processes.

---

## 19. Code / File Map

| File | Responsibility | Important Functions / Classes | Notes |
|---|---|---|---|
| `config.py` | All tunables and constants | `BASE_URL`, `DEFAULT_SERIES`, `TENNIS_SERIES_PREFIXES`, `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW`, `SPREAD_REASONABLE`, `DISPLAY_TOL_C`, `NEAR_EDGE_MIN_C`, `MAX_RPS`, `REFRESH_TTL`, `TIMEZONE_DEFAULT`, `TIMEZONE_OPTIONS`, `STALE_AFTER_SECONDS`, `FRESHNESS_TICK_SECONDS`, `SNAPSHOT_DB_PATH`, `SNAPSHOT_RETENTION_SECONDS`, `BACKLOG_WINDOWS`, `BACKLOG_DEFAULT`, `ALERT_PERSISTENCE_OPTIONS`, `API_HOST`, `API_PORT`, `SCAN_MIN_INTERVAL_SECONDS`, `NICEGUI_STORAGE_SECRET_FALLBACK`, `UI_REFRESH_SECONDS` | Pure constants; no logic; no imports |
| `sports.py` | Sport abstraction registry | `SportConfig`, `LadderSpec`, `IdentityResolver`, `IdentityResult`, `MarketClassification`, `sport_for_series`, `register`, `all_sports`, `get_sport`, `extract_round`, `TENNIS`, `NBA`, `WNBA`, `UNKNOWN` | Only imports `config` + stdlib; no pandas; no Streamlit; independently testable |
| `kalshi_client.py` | HTTP, pagination, throttle, retry, concurrency | `_get`, `get_paginated`, `get_events`, `discover_series_for_sport`, `discover_tennis_series`, `get_events_for_series`, `get_series_titles`, `_throttle`, `KalshiError` | No Streamlit; no data parsing; process-wide rate limiter |
| `fetch.py` | Streamlit-free contract fetch | `fetch_contracts(families, scan_all, sport_id) -> 7-tuple` | Shared by `app.load_contracts` (cached) and `api.fetch_dep`; no Streamlit |
| `data.py` | Parse raw JSON → contract rows; pricing; tournament stamping; identity | `build_contracts`, `opportunity_id`, `is_french_open_event`, `tournament_of`, `to_cents`, `to_float`, `quote_quality`, `display_prob`, `yes_mid`, `classify_kind`, `tour_of`, `display_player_name`, `kalshi_market_url`, `link_audit`, `fmt_time`, `data_age_seconds`, `is_stale`, `parse_fetched_at`, `CATEGORY` | No Streamlit; no pandas; independently testable |
| `consistency.py` | Containment checking; action plan; dashboard bucketing; scenario payoffs | `build_checks`, `build_player_nodes`, `_classify`, `layer_spreads`, `expected_nodes`, `bucket_of`, `representative`, `duplicate_node_sources`, `spread_certainty_label`, `scenario_payoffs`, `node_of`, `NODE_ORDER`, `ADJACENT_PAIRS`, `STATUS_GROUP` | No Streamlit; depends on pandas; depends on data, glossary, sports |
| `dutchbook.py` | 2-outcome Dutch-book / MECE detector | `find_dutch_books`, `_detect_pair`, `_direction_candidate`, `EXECUTABLE_DUTCH_BOOK`, `CHECK_TYPE` | No Streamlit; no pandas; depends on sports, glossary, data; independently testable |
| `scanner.py` | Cross-sport aggregation; unified ranked frame | `unified_opportunities`, `run_scan`, `UNIFIED_COLUMNS`, `BUCKET_PRIORITY` | No Streamlit; no network; fetch injected; independently testable |
| `store.py` | SQLite snapshot persistence | `write_snapshot`, `latest`, `latest_two`, `snapshots_since`, `SCHEMA_VERSION`, `PROMOTED_COLUMNS` | No Streamlit; no pandas; stdlib only; NaN-safe; versioned schema; independently testable |
| `lifecycle.py` | Snapshot-diff engine | `new_actionable`, `first_seen`, `persisting_new_actionable`, `blocked_change`, `recently_actionable` | No Streamlit; no network; no store import; pure functions; independently testable |
| `api.py` | FastAPI REST API; Pydantic models; thin handlers | `app`, `Opportunity`, `Coverage`, `BacklogItem`, `BlockedChange`, `Alerts`, `ScanResult`, `db_path_dep`, `fetch_dep`, `get_opportunities`, `get_opportunity`, `get_backlog`, `get_coverage`, `get_alerts`, `post_scan`, `healthz` | No detection logic; tests use `app.dependency_overrides`; no network in tests |
| `serve.py` | Entrypoint: FastAPI + NiceGUI via uvicorn | `ui.run_with(api.app, …)` | Reads `NICEGUI_STORAGE_SECRET` env; imports `webui.dashboard` to register the page |
| `webui/__init__.py` | Package marker | — | Empty |
| `webui/engine.py` | In-process engine accessors for NiceGUI dashboard | `latest_opportunities`, `opportunities_in_bucket`, `backlog`, `alerts`, `coverage`, `run_scan_now` | No NiceGUI; thin wrappers over store/lifecycle/scanner; independently testable |
| `webui/dashboard.py` | NiceGUI `@ui.page('/')` dashboard | `dashboard`, `explanation_lines`, `_opp_row`, `_backlog_row`, `_ts_disp` | Presentation only; detection in engine; `explanation_lines` is pure / unit-testable |
| `filters.py` | Two-pass membership + threshold filtering | `apply_membership`, `apply_thresholds`, `QUOTE_MODES`, `STATUS_MODES` | No Streamlit; pure pandas; independently testable |
| `viz.py` | Chart data preparation | `payoff_chart_data`, `ladder_prices` | No Streamlit; pure pandas; independently testable. `opportunity_ranking` removed (Stage 0) |
| `glossary.py` | All user-facing help text | `GLOSSARY`, `BLOCKERS`, `WATCHLIST_NOTE`, `COLUMN_HELP`, `help_for` | No imports; single source of truth for tooltips and blocker reasons |
| `app.py` | Streamlit UI; cached fetch; rendering | `load_contracts`, `discover`, `render_dashboard`, `render_freshness`, `_buy_disp`, `_payoff_block` | Only file with Streamlit imports; `load_contracts` is thin wrapper over `fetch.fetch_contracts` |
| `tests/test_data.py` | Unit tests for data layer | All `test_*` functions | No network |
| `tests/test_consistency.py` | Unit tests for consistency layer | All `test_*` functions | No network |
| `tests/test_dutchbook.py` | Unit tests for Dutch-book detector | All `test_*` functions | No network |
| `tests/test_sports.py` | Unit tests for sport abstraction | All `test_*` functions | No network |
| `tests/test_glossary.py` | Glossary integrity tests | `test_every_term_has_short_and_long`, `test_consistency_only_emits_known_blocker_text` | |
| `tests/test_client.py` | Unit tests for HTTP client | Rate-limiter, pagination, backoff | No real network |
| `tests/test_filters.py` | Unit tests for filter layer | `apply_membership`, `apply_thresholds` edge cases | No network |
| `tests/test_viz.py` | Unit tests for viz layer | `payoff_chart_data`, `ladder_prices` | No network |
| `tests/test_app.py` | Streamlit smoke test | `AppTest` end-to-end with mocked network | Tests full render pipeline; catches wiring bugs |
| `tests/test_store.py` | Unit + integration tests for snapshot store | Round-trip, latest_two, snapshots_since, retention, schema migration (v1→v2), NaN/tuple safety, real engine output | No network; tmp file DB |
| `tests/test_scanner.py` | Unit tests for cross-sport scanner | Aggregation, sport stamping, ranking, partial-failure, store write, lifecycle fields, explanation fields, run_scan coverage | No network; fetch stubbed |
| `tests/test_lifecycle.py` | Unit tests for lifecycle engine | §8 new-actionable, §9 blocked-change, §10 recently-actionable, first_seen, unordered-input robustness | No network or store; crafted snapshot dicts |
| `tests/test_api.py` | API endpoint tests | All endpoints; filtering; TTL guard; force; coverage meta/no-meta | TestClient; dependency_overrides; no network |
| `tests/test_webui.py` | NiceGUI engine + dashboard tests | Engine accessors, run_scan_now offline, dashboard imports + registers page, pure builder functions | No NiceGUI runtime for engine; monkeypatched fetch_dep |
| `scripts/check_links.py` | Live link-reachability check | — | Runs from an unthrottled network |
| `scripts/export_glossary.py` | Generate `docs/GLOSSARY.md` | — | Run locally; output committed |
| `docs/GLOSSARY.md` | Generated glossary reference | — | Do not edit manually |

### What each file should NOT own

- `data.py`, `consistency.py`, `dutchbook.py`, `filters.py`, `viz.py`, `fetch.py`, `scanner.py`, `lifecycle.py`, and `store.py` must never import Streamlit.
- `data.py`, `dutchbook.py`, and `store.py` must not import pandas (plain dicts/lists only).
- `sports.py` must not import any of the above modules (only `config` + stdlib) — no circular imports.
- `kalshi_client.py` must not contain any parsing or business logic.
- `app.py` must not contain any math; delegate to `consistency.py`, `dutchbook.py`, and `filters.py`.
- `config.py` must not contain any functions or imports.
- `glossary.py` must not contain any imports.
- `api.py` handlers must not contain detection logic (all computation delegated to engine modules).
- `webui/dashboard.py` must not contain detection logic (all computation via `webui/engine.py`).

### Technical debt / refactoring notes

- `consistency.py` imports pandas while `data.py` and `dutchbook.py` do not; this asymmetry means `consistency.py` cannot be tested without pandas installed.
- Back-compat aliases `NODE_ORDER`, `ADJACENT_PAIRS`, `MATCH_STAGE_TO_NODE`, `ADVANCE_STAGE_TO_NODE` in `consistency.py` reference the tennis ladder; multi-sport code resolves the ladder via `_sport_for_row`.
- Back-compat aliases `_ROUND_PATTERNS`, `_STAGE_RANK`, `CATEGORY` in `data.py` reference the tennis `SportConfig`; they exist so existing imports and tests continue to work without changes.
- `app.load_contracts` is now a thin cached wrapper — the fetch logic lives in `fetch.py`. Any future refactor of the Streamlit cache should touch only `app.py`.
- The NiceGUI "Scan now" button uses core series only; a full-scan toggle for the NiceGUI dashboard is deferred.
- Per-player detail + full diagnostics are not yet ported to the NiceGUI dashboard (Streamlit app retains them; Streamlit retirement deferred).

---

## 20. Known Limitations

- **Read-only, gross edge only:** The app is read-only. All "Buy YES / Buy NO" instructions are informational. Gross edge only — fees/slippage remain deferred.

- **No true arbitrage guarantee for match-alignment pairs:** Match-alignment pairs carry `RULE_CHECK_REQUIRED`/`RULE_MISMATCH`. Dutch-book findings do not have this caveat.

- **Dutch-book scope is 2-outcome only:** The detector handles exactly-2-outcome events. n-outcome winner fields (≥ 3 outcomes) are out of scope.

- **No Kalshi WebSocket feed:** All data is REST-polled (Kalshi does not currently expose a public WebSocket for market-data consumers). The freshness strip shows data age; the NiceGUI dashboard polls the store every 120s by default.

- **Streamlit retirement deferred:** The Streamlit app remains the per-sport detail surface. Per-player detail, full diagnostics, and the tour/tournament/stage sidebar filters are not yet ported to the NiceGUI dashboard.

- **Full-scan toggle not in NiceGUI dashboard:** The "Scan now" button uses core series only; the full-scan option lives in the Streamlit sidebar.

- **Process-wide rate limiter only:** Multiple processes each have their own limiter; aggregate rate = `MAX_RPS × process_count`. A shared limiter would be needed for horizontal scale-out.

- **Single-writer SQLite store:** `store.py` is designed for single-writer local use. Concurrent writers from multiple processes would corrupt the DB.

- **Metadata quality dependency:** The consistency checker relies on `product_metadata.competition`, `custom_strike.*`, and stage-keyword text. If Kalshi changes these fields, tournament stamping and grouping degrade silently (surfaced in `tournament_source` debug field).

- **Missing quotes are common:** Between rounds or for illiquid participants, most markets have empty or one-sided books.

- **FO date window is year-specific:** `config.FO_WINDOW` (`2026-05-18` to `2026-06-09`) is used only by the `is_french_open_event` helper (not a gate); update annually if the helper matters.

- **Link audit is deterministic, not live:** `data.link_audit` verifies URL correctness deterministically; live reachability checks require an unthrottled network.

---

## 21. Open Design Questions

- Should `NAME_ALIASES` be editable from the UI sidebar, or only from `config.py`?
- What is the exact threshold defining a "near-edge" row? The current `NEAR_EDGE_MIN_C = -5` is a guess.
- Should `UNKNOWN_RELATIONSHIP` rows appear in the default view or only in Full diagnostics?
- Should the Outcome status filter also optionally narrow the Blocked and Watchlist sections?
- How should NBA/WNBA per-game markets appear in the ladder view? Currently in "Non-laddered / unmapped" (off by default).
- Should the Dutch-book section ever be hidden by a section toggle, or always visible?
- At what scale of horizontal deployment should the rate limiter be redesigned?
- Should the NiceGUI dashboard surface a "Show IDs" toggle equivalent to the Streamlit one? (Currently implemented: `show_ids` switch in the controls row drives `explanation_lines(..., show_ids=...)` in the panel.)
- When should Streamlit be retired? The plan is deferred; the NiceGUI dashboard needs per-player detail and full diagnostics ported first.

---

## 22. Appendix

### A. Glossary (from `glossary.py`)

Key terms as defined in the app's single source of truth:

| Term | Short definition |
|---|---|
| Tradable now | Whether you could place both buys this second and lock the edge. ❌ means something blocks it. |
| Buy YES vs Buy NO | Buy YES = bet the outcome happens. Buy NO = bet it does NOT happen. Every opportunity is two buys. |
| Bid / Ask | Bid = best price someone will pay. Ask = best price someone will sell at. |
| Firm vs display price | Firm = real resting orders. Display = estimate (midpoint or last trade). |
| Quote size | How many contracts are available at a price. Size 0 means nothing to fill against. |
| Book width | Bid-ask gap. Tight ≤5¢ · OK ≤15¢ · Wide ≤30¢ · Very wide >30¢. |
| Settlement rules / rule caveat | Match-alignment pairs may have different payout rules not auto-verified. Dutch-book pairs have NO rule caveat — same event, settle together. |
| Executable inconsistency vs arbitrage | "Executable inconsistency" = containment-ladder cross (rule caveat may apply). "Dutch book" = true arbitrage (same event, no caveat). |
| Containment ladder | Broad ⊇ ... ⊇ Deep. A deeper outcome can't price higher than the broader one containing it. Per-sport ladder in `sports.py`. |
| Dutch book | A 2-outcome MECE market where both outcomes can be bought for < 100¢ — a locked profit regardless of which side wins. |
| Locked edge (¢) | The per-unit profit on a Dutch-book arbitrage (= 100 − combined cost). |
| Gross quoted profit | Gross edge × units, before fees, slippage, latency, and partial-fill risk. |

### B. Run instructions

**Streamlit app (original per-sport dashboard):**
```bash
pip install -r requirements.txt
streamlit run app.py
```

**FastAPI engine + NiceGUI cross-sport dashboard:**
```bash
pip install -r requirements.txt  # includes fastapi, uvicorn, pydantic, nicegui
python serve.py
# UI at http://localhost:8000/
# REST at http://localhost:8000/opportunities etc.
# OpenAPI at http://localhost:8000/docs
```

**Tests:**
```bash
pip install -r requirements-dev.txt  # adds pytest, ruff, httpx
pytest -q
ruff check .
```

**Headless boot verify (Streamlit):**
```bash
streamlit run app.py --server.headless true --server.port 8765
# check http://localhost:8765/_stcore/health → 200
```

### C. Sample opportunity row (unified schema, synthetic)

```json
{
  "sport": "tennis",
  "sport_label": "Tennis",
  "source": "dutch_book",
  "opportunity_id": "a3b2c1d4e5f6a7b8",
  "relationship_type": "dutch_book",
  "bucket": "actionable",
  "blocked_reason": "",
  "name": "Alcaraz vs Sinner",
  "detail": "underround",
  "tournament": "French Open Men Singles",
  "tour": "ATP",
  "action_1_text": "Buy YES — Alcaraz @ 45¢",
  "action_2_text": "Buy YES — Sinner @ 48¢",
  "action_1_price_c": 45,
  "action_2_price_c": 48,
  "cost_c": 93,
  "exec_gap_c": 7,
  "exec_min_size": 100,
  "exec_max_profit_dollars": 7.0,
  "status": "EXECUTABLE_DUTCH_BOOK",
  "tradable_now": "Yes",
  "market_status": "active",
  "rule_flag": "",
  "ticker_1": "KXATPMATCH-26JUN02ALCSINN-ALC",
  "ticker_2": "KXATPMATCH-26JUN02ALCSINN-SIN",
  "url": "https://kalshi.com/markets/kxatpmatch/...",
  "url_2": ""
}
```

### D. Example consistency check scenarios (live-verified)

| Player | Check | Expected status | Notes |
|---|---|---|---|
| Cirstea (WTA) | QF win ≡ Reach Semifinal | `EXECUTABLE_VIOLATION` + `RULE_MISMATCH` | ~2¢ cross, rules differ |
| Sabalenka (WTA) | Reach Final ≤ Reach Semifinal | `DISPLAY_VIOLATION` | Display prices cross, no firm executable cross |
| Gauff / Swiatek (WTA) | Any pair | `MISSING_QUOTE` | Empty books when inactive |

### E. Debugging checklist

1. **App shows stale data after a code edit:** Fully stop and restart `streamlit run app.py`. Clear `__pycache__` if a phantom `ImportError` persists.

2. **NiceGUI dashboard shows "No scan yet":** Press "Scan now (core series)". The store is empty on a fresh start — nothing is pre-populated.

3. **`/opportunities` returns empty:** The store is empty or the latest snapshot has no opportunities. Run `POST /scan` or press the scan button.

4. **`/coverage` returns `meta_present: false`:** The latest snapshot was written by the Streamlit app (which does not write coverage metadata), or the store is empty.

5. **Unexpected `UNKNOWN_RELATIONSHIP` rows:** The match's stage is not in the sport's `match_stage_to_node` map. Check `sports.py` for the sport's `match_stage_to_node`.

6. **Participant appears under wrong tour (tennis):** `tour_of` / `division_of` may be using substring logic that misfires on a new ticker. Check `sports.py:_tennis_division` and update the explicit winner-ticker sets if needed.

7. **All links going to series page instead of event page:** `series_title` was not fetched. Check the `get_series_titles` call in `fetch.fetch_contracts`.

8. **Contracts stamped `Unknown` tournament:** The `competition` field is absent and no keyword/ticker fallback matched. Check `data.tournament_of` and the `tournament_source` column in the Debug panel.

9. **Rate limit errors in production:** `MAX_RPS` is set to 5 (25% of the 20/s ceiling). If errors persist, lower `CONCURRENCY` or `MAX_RPS`. Note the limiter is process-wide only.

10. **Dutch-book detector fires on a non-MECE event:** Check that the event has exactly 2 distinct `player_key` markets. Events with more than 2 markets are excluded by the exactly-2 guard in `dutchbook._detect_pair`.

11. **Store schema error on startup:** If `RuntimeError` is raised mentioning "newer than supported", the DB was written by a newer version of the code. Either use the correct code version or delete the DB file to start fresh.

12. **`opportunity_id` collision across sports:** Each recipe includes the check type + participant/event key + (for containment) the tournament and node labels. Identical opportunities in different sports have different `player_key`s (UUIDs are sport-specific). Verify the `relationship_type` and `sport` fields to disambiguate.

### F. Configuration knobs quick reference

| Constant | Location | Default | What changing it does |
|---|---|---|---|
| `DEFAULT_SERIES` | `config.py` | 6 tennis series | The fast-scan tennis series list; per-sport defaults live in `sports.SportConfig.default_series` |
| `TENNIS_SERIES_PREFIXES` | `config.py` | `("KXATP", "KXWTA")` | Used by `discover_series_for_sport` for the full tennis scan |
| `SPREAD_REASONABLE` | `config.py` | 0.20 ($0.20) | Threshold for trusting midpoint as display price |
| `DISPLAY_TOL_C` | `config.py` | 1¢ | Ignore display gaps below this (noise filter) |
| `NEAR_EDGE_MIN_C` | `config.py` | -5¢ | Near-edge watchlist window lower bound |
| `FO_WINDOW` | `config.py` | 2026-05-18 to 2026-06-09 | FO date-window fallback for `is_french_open_event`; update per year |
| `MAX_RPS` | `config.py` | 5 req/s | Rate limiter ceiling |
| `REFRESH_TTL` | `config.py` | 30s | `load_contracts` cache TTL + `SCAN_MIN_INTERVAL_SECONDS` |
| `REFRESH_DEFAULT_SECONDS` | `config.py` | 120s | Default auto-refresh interval (Streamlit) + `UI_REFRESH_SECONDS` (NiceGUI) |
| `FRESHNESS_TICK_SECONDS` | `config.py` | 1s | How often the Streamlit freshness strip re-renders (no refetch) |
| `STALE_AFTER_SECONDS` | `config.py` | 300s | Data age threshold for the stale warning (both UIs) |
| `TIMEZONE_DEFAULT` | `config.py` | `"Europe/Lisbon"` | Default display timezone (comparison math unaffected) |
| `SNAPSHOT_DB_PATH` | `config.py` | `"snapshots.db"` | SQLite store file path; relative to process working dir; gitignored |
| `SNAPSHOT_RETENTION_SECONDS` | `config.py` | 108000s (30h) | How long snapshots are kept (relative to newest); covers 24h backlog window |
| `BACKLOG_WINDOWS` | `config.py` | 15m/1h/4h/24h/None | Recently-actionable window options; `None` = "This session" |
| `BACKLOG_DEFAULT` | `config.py` | `"1 hour"` | Default backlog window label |
| `ALERT_PERSISTENCE_OPTIONS` | `config.py` | None/5m/15m | New-actionable banner persistence options |
| `API_HOST` | `config.py` | `"127.0.0.1"` | FastAPI/uvicorn bind host |
| `API_PORT` | `config.py` | 8000 | FastAPI/uvicorn bind port |
| `SCAN_MIN_INTERVAL_SECONDS` | `config.py` | 30s (= `REFRESH_TTL`) | POST /scan TTL guard; overridable with `?force=true` |
| `NICEGUI_STORAGE_SECRET_FALLBACK` | `config.py` | dev-only string | Overridden by `NICEGUI_STORAGE_SECRET` env var in production |
| `UI_REFRESH_SECONDS` | `config.py` | 120s | NiceGUI dashboard poll cadence for re-reading the store |

---

## 23. Evolution — Stages built and remaining

### Locked decisions (apply across all stages)

- **Gross edge only** — fees/net-edge/slippage remain deferred; the existing "before fees/slippage" caveat stays.
- **Cross-sport unified scanner** = all wired sports scanned simultaneously; header reads "All loaded markets" (never "all Kalshi markets").
- **Timezone-aware display** with `Europe/Lisbon` default; TZ is display-only and never touches exact-integer-cents comparison math.
- **Data-freshness & coverage strip** is always visible in both UIs.
- Durable logic stays in pure, Streamlit-free engine modules + the store (migration-safe).
- No sound alerts; no out-of-browser notifications; no multi-user/server/auth; no new sports within these stages.

### Stage 0 — Clarity quick wins ✅ SHIPPED

Stage 0 (clarity quick wins) is fully shipped and described throughout §§1–22 above:
- Altair opportunity-ranking chart **removed**
- Always-visible data-freshness & coverage strip (its own 1s fragment)
- Timezone selectbox (Lisbon default) + `fmt_time()` on every timestamp
- "Show IDs & codes" toggle (default OFF)
- Debug + Full-diagnostics behind a single "Advanced" toggle (default OFF)

### Stage 1 — Opportunity schema + SQLite snapshot store ✅ BUILT

- **`opportunity_id`**: deterministic 16-char SHA-1 prefix via `data.opportunity_id(*parts)`; stable across runs and processes.
- **`blocked_reason`**: REQUIRED field on every opportunity row; non-empty IFF `bucket == "blocked"` (test-enforced).
- **`relationship_type`**: `containment_adjacent` | `match_alignment` | `dutch_book`.
- **SQLite snapshot store** (`store.py`): schema v2 with `meta` column; `write_snapshot` / `latest` / `latest_two` / `snapshots_since`; retention relative to newest snapshot; NaN-safe; versioned migration.
- New test suite: `tests/test_store.py`.

### Stage 2 — Cross-sport unified scanner ✅ BUILT

- **`scanner.py`**: `unified_opportunities(fetch_fn)` + `run_scan(fetch_fn)` — all sports, both detectors, normalized onto `UNIFIED_COLUMNS`, ranked by `(BUCKET_PRIORITY, -exec_gap_c, opportunity_id)`.
- Partial-failure tolerant; fetch dependency-injected; store write injected.
- `UNIFIED_COLUMNS` includes explanation-panel fields (`action_1_price_c`, `action_2_price_c`, `cost_c`, `ticker_1`, `ticker_2`, `url_2`) and lifecycle-diff fields (`market_status`, `rule_flag`).
- New test suite: `tests/test_scanner.py`.

### Stage 3 — Lifecycle: alerts + recently-actionable backlog ✅ BUILT

- **`lifecycle.py`**: pure snapshot-diff engine; `new_actionable` (§8), `persisting_new_actionable` (§8 banner persistence), `blocked_change` (§9, 7 dimensions), `recently_actionable` (§10), `first_seen`.
- `config.BACKLOG_WINDOWS`, `config.ALERT_PERSISTENCE_OPTIONS`.
- New test suite: `tests/test_lifecycle.py`.

### Stage 4 — FastAPI REST API ✅ BUILT

- **`api.py`**: FastAPI app; 6 Pydantic response models; 7 endpoints; thin handlers; dependency-injectable DB path + fetch function.
- **`serve.py`**: uvicorn entrypoint; mounts NiceGUI.
- **`fetch.py`**: Streamlit-free fetch shared by both app.py and serve.py.
- `config.API_HOST`, `config.API_PORT`, `config.SCAN_MIN_INTERVAL_SECONDS`.
- New test suite: `tests/test_api.py`.

### Stage 5 — NiceGUI cross-sport dashboard ✅ BUILT

- **`webui/engine.py`**: in-process accessors wrapping store/lifecycle/scanner.
- **`webui/dashboard.py`**: `@ui.page('/')` with sortable tables, per-second freshness strip, explanation panel, alerts (polling + toast), "Scan now" button (core series, async I/O-bound).
- **`serve.py`**: `ui.run_with(api.app, mount_path="/", storage_secret=...)` mounts NiceGUI onto FastAPI.
- `config.NICEGUI_STORAGE_SECRET_FALLBACK`, `config.UI_REFRESH_SECONDS`.
- New test suite: `tests/test_webui.py`.

### Stage 6 — Export overhaul ✅ PLANNED (not yet built)

A dedicated export panel with up to 8 datasets (current opportunities, actionable-only, blocked-only,
recently-actionable backlog, raw contracts, normalized contracts, relationship table, diagnostics bundle);
CSV per table + one JSON/ZIP bundle; every export embeds active filters + `fetched_at` (TZ-aware). XLSX/Parquet deferred. Optional `export.py` module. Reads `store.py` + `scanner.py`.

### Deferred follow-up (also planned)

- **Per-player detail + full diagnostics ported to NiceGUI** — currently only in the Streamlit app; required before Streamlit retirement.
- **Streamlit retirement** — deferred until NiceGUI surface is feature-complete for per-player detail.
- **Full-scan toggle in NiceGUI** — the dashboard's "Scan now" button uses core series; full-scan is Streamlit-only today.
- **n-outcome Dutch-book fields** (≥ 3 outcomes, seed S6) — needs field-completeness proof + multi-leg representation.
- **Per-game Dutch-book books on tennis** — tennis has no `game` family and no per-game series; out of scope.
