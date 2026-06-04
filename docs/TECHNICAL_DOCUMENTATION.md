# Kalshi Structured Market Visualizer — Technical Documentation

**Audience:** Backend developer, technical collaborator, or future maintainer.
**Source of truth:** The live codebase as of 2026-06-03 (`main`, PR #35 merged). Planned/unimplemented items are explicitly labelled.

---

## 1. Project Overview

The Kalshi Structured Market Visualizer is a read-only Streamlit web app that surfaces prediction-market data from the Kalshi exchange across multiple sports. It groups a participant's contracts into a logical progression ladder, detects when deeper outcomes are priced above broader prerequisites (a layer-consistency violation), and surfaces actionable entries as two-buy trade instructions. It also runs a separate Dutch-book / MECE detector on head-to-head match and per-game markets.

**Current goal:** Give a trader a fast, accurate picture of which contracts on Kalshi have price inconsistencies or Dutch-book arbitrage across supported sports (tennis, NBA, WNBA), whether those opportunities are executable, and exactly what to do (Buy YES on one leg, Buy NO on the other).

**Current supported sports:** Tennis (ATP + WTA, all tournaments), NBA (championship / conference / playoff-series / per-game), WNBA (championship / reach-stage / playoff-series / per-game). Each sport is registered as a `SportConfig` in `sports.py`.

**Current development stage:** Multi-sport engine operational; Stage 0 clarity wins shipped (live freshness strip, timezone selector, Show IDs toggle, diagnostics behind Advanced toggle); opportunity-ranking bar chart removed. Stages 1–6 of the forward roadmap are planned but not yet built.

**What the app is NOT trying to do yet:**
- Execute trades or place orders
- Model conditional probabilities or de-vig
- Provide portfolio management or position tracking
- Add sports beyond tennis / NBA / WNBA without explicit scope change
- Persist historical data, run lifecycle alerts, or expose a REST API (all planned in future stages)

---

## 2. System Scope

### Current Scope

- Read-only market-data viewer; no authentication, no trading
- Loading and organizing Kalshi prediction-market contracts via public REST API across three sports (tennis, NBA, WNBA)
- Multi-sport participant grouping via a `SportConfig` abstraction (`sports.py`); participant key is a stable competitor/team UUID (or normalized name fallback)
- Layer-consistency checking: containment violations + match-alignment equivalence checks, per sport ladder
- Dutch-book / MECE detector on 2-outcome head-to-head and per-game markets (`dutchbook.py`)
- Quote transparency: bid, ask, midpoint, last trade, spread quality
- Buy-only action instructions for executable inconsistencies and Dutch-book arbitrage
- Dashboard views: actionable now / Dutch-book arbitrage / blocked / near-edge watchlist / full diagnostics
- Always-visible data-freshness & coverage strip (data age, stale warning, coverage counts, refresh status)
- Timezone-aware display with Lisbon default; comparison math always exact UTC cents
- "Show IDs & codes" toggle; diagnostics and debug behind an Advanced toggle (default OFF)
- Raw and debug fields accessible via the Advanced → Debug section
- Per-player and full-dataset CSV/JSON export

### Out of Scope for Now

- Trade execution or order placement
- Automated trading or strategy execution
- Full arbitrage engine (settlement-rule compatibility is not auto-verified for match-alignment pairs)
- Conditional-probability modeling or de-vig math
- Portfolio management
- Historical data storage or time-series analysis (planned as Stage 1 SQLite snapshot store)
- Alerts or out-of-browser notifications (planned as Stage 3)
- Sports beyond tennis / NBA / WNBA (scope requires an explicit change)
- REST API or NiceGUI frontend (planned as Stages 4–5)

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
data.py           — Parse raw JSON → per-participant contract rows (flat dicts); sport-agnostic
                    via sports.py; ALL tennis events (no FO gate); tournament stamping
  ↓
consistency.py    — Build per-participant nodes → pairwise comparisons → edge classification;
                    sport-resolved ladder per row
  ↓
dutchbook.py      — 2-outcome MECE detector: find_dutch_books() on match + game rows
  ↓
filters.py        — Membership + threshold filtering on the comparison DataFrame
  ↓
app.py            — Streamlit UI: sport selector, sidebar controls, freshness strip,
                    summary cards, section tables, Dutch-book section, debug
  ↑
config.py         — All tunables (URLs, series lists, thresholds, rate limits, refresh cadence,
                    timezone options, staleness threshold)
glossary.py       — All user-facing help text (tooltips, blocker reasons, watchlist notes)
```

### Per-layer details

| Layer | Responsibility | Input | Output | Files/Functions |
|---|---|---|---|---|
| **Sport abstraction** | One `SportConfig` per sport; registry; family/stage/node/division resolution | Series ticker, market dict | `MarketClassification`, `IdentityResult` | `sports.SportConfig`, `sports.sport_for_series`, `sports.register`, `sports.TENNIS`, `sports.NBA`, `sports.WNBA` |
| **HTTP** | Rate-limited, paginated, retried GET requests to Kalshi | Series tickers | Raw event/market JSON | `kalshi_client._get`, `get_paginated`, `get_events`, `discover_series_for_sport`, `get_events_for_series` |
| **Parsing** | Flatten events → per-participant contract rows; classify, price, link; stamp tournament | Raw JSON dicts | List of contract dicts | `data.build_contracts` |
| **Tournament filtering** | Stamp each event with its tournament; `is_french_open_event` is a helper, not a gate | Event dict | tournament key string | `data.tournament_of`, `data.is_french_open_event` |
| **Consistency** | Build participant nodes using sport ladder, compare adjacent pairs, classify violations | Contract row list | Comparison DataFrame | `consistency.build_checks`, `consistency._classify` |
| **Dutch-book detection** | Find 2-outcome MECE arbitrage on match + game events | Contract row list (dicts) | List of finding dicts | `dutchbook.find_dutch_books`, `dutchbook._detect_pair` |
| **Bucketing** | Route each comparison or Dutch-book finding to a dashboard section | Single check row dict | Bucket name string | `consistency.bucket_of` |
| **Filtering** | Two-pass filter: membership (all sections) + thresholds (all except Actionable now) | Checks DataFrame | Filtered DataFrames | `filters.apply_membership`, `filters.apply_thresholds` |
| **UI** | Render tables, sidebar, freshness strip, summary cards, Dutch-book section, export | Filtered DataFrames + Dutch-book findings | Streamlit widgets | `app.py:render_dashboard`, `app.py:render_freshness` |

**Important assumptions:**
- `data.py`, `consistency.py`, `dutchbook.py`, `filters.py`, and `viz.py` must never import Streamlit (independently testable).
- `data.py` and `dutchbook.py` must not import pandas (plain dicts/lists only).
- `sports.py` imports only `config` and stdlib (no circular imports).
- All comparison math uses exact integer cents (`to_cents` via `Decimal`); floats are display-only.
- An empty order book (`0.00/1.00`) is never treated as a real price.
- Pagination raises on truncation; partial data is never silently returned.

---

## 4. Data Model

### Core entities

**Series** — A Kalshi series groups semantically related events. Example: `KXWTAMATCH` (all WTA match-winner events). Identified by `series_ticker`.

**Event** — A single competition event, e.g. one match or one advancement milestone. Contains one or more markets. Identified by `event_ticker`.

**Market** — A single binary outcome. Identified by `market_ticker`. For match events there are two markets (one per player); for advancement/winner events there is one market per player.

**Participant (player/team)** — A competitor, identified by `player_key` (preferred: stable UUID from `custom_strike.tennis_competitor` or `custom_strike.basketball_team`; fallback: normalized display name). The identity path is sport-specific via `IdentityResolver`.

**Contract row** — The normalized per-participant output of `data.build_contracts`. One row = one participant's view of one market.

**Node** — A logical ladder position mapped from a contract: e.g. `Reach Semifinal`, `Reach Final`, `Win Tournament` (tennis); `Reach Playoffs`, `Win Conference`, `Win Championship` (NBA). Defined per sport in `SportConfig.ladder.node_order`; back-compat alias `consistency.NODE_ORDER` references the tennis ladder.

**Comparison row** — Output of `consistency.build_checks`. One row = one pairwise comparison between a child (deeper) and a parent (broader) node, with a status, gap, and action plan.

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

**Default fast scan (`cfg.default_series`):** Fetches the sport's configured default series from `SportConfig.default_series`. For tennis: `KXATPMATCH`, `KXWTAMATCH`, `KXATPADVANCE`, `KXWTAADVANCE`, `KXFOMEN`, `KXFOWOMEN` (6 series). For NBA: `KXNBA`, `KXNBAEAST`, `KXNBAWEST`, `KXNBAPLAYOFF`, `KXNBASERIES`, `KXNBAGAME` (6 series). For WNBA: `KXWNBA`, `KXWNBAPLAYOFF`, `KXWNBASEMIFINAL`, `KXWNBAFINAL`, `KXWNBASERIES`, `KXWNBAGAME` (6 series). (`kalshi_client.get_events_for_series`, `app.load_contracts`)

**Full dynamic scan (`kalshi_client.discover_series_for_sport(cfg)`):** Lists all Kalshi series, filters to those starting with the sport's `series_prefixes` (or matching `winner_tickers`). For tennis: prefixes `KXATP`, `KXWTA`. Returns ~61 series for tennis. Triggered by the "Scan all … series" checkbox. Takes ~20 seconds. `discover_tennis_series()` is a back-compat wrapper over this generic function.

### Tournament stamping (no French Open gate)

`build_contracts` includes **ALL events** for the active sport — there is no French Open gate. Every event is stamped with a never-empty `tournament` grouping key via `data.tournament_of`, which resolves in priority order:

1. **Primary:** Cleaned `product_metadata.competition` field (e.g. `"French Open Men Singles"` → `"French Open Men Singles"`).
2. **Winner-ticker fallback:** If competition is absent, infer from the series ticker (e.g. `KXFOWOMEN` → `"French Open Women"`).
3. **Title keyword:** If neither above, extract a keyword from the event title.
4. **Unknown:** `"Unknown · <competition|event_ticker|event_title|series_ticker>"` (never empty).

`tournament_source` records which path was taken. `build_checks` groups by `(player_key, tournament)` so ladders never mix across tournaments and a fallback never collapses to `""`.

`is_french_open_event` still exists as a helper for debugging/display, using the priority-order keyword + date-window check described below, but it **no longer gates** `build_contracts`:

1. **Primary:** `product_metadata.competition` contains a French Open keyword (`"french open"`, `"roland garros"`, `"roland-garros"`, case-insensitive).
2. **Secondary:** FO keyword found in `event.title`, `event.sub_title`, or any market's `title` or `rules_primary`.
3. **Negative signal:** If a non-FO competition is named (e.g. `"Stuttgart Open"`), reject — do NOT fall back to dates.
4. **Last resort:** Only when no competition field is present at all, accept if any market's `occurrence_datetime` or `close_time` falls within `config.FO_WINDOW` (currently `2026-05-18` to `2026-06-09`, year-specific — update annually).

### Rate limiting and concurrency

- The client uses a process-wide min-interval limiter (`_throttle`) capped at `config.MAX_RPS` (5 req/s, ~25% of Kalshi's 20 req/s Basic tier limit).
- Fan-out to multiple series is concurrent via `ThreadPoolExecutor(max_workers=CONCURRENCY=4)`.
- A `Retry-After`-aware exponential backoff handles 429 and 5xx responses.
- Pagination is guarded: `get_paginated` raises `KalshiError` if `MAX_PAGES=100` is reached with a cursor still pending — partial data is never silently returned.

### Series titles for URL generation

`kalshi_client.get_series_titles(tickers)` fetches the human title for each series concurrently. Titles are used to generate URL slugs (`data._slugify`). A missing title degrades gracefully to the series-level URL rather than crashing.

### Raw data preservation

Every contract row preserves raw price strings (`raw_yes_bid`, `raw_yes_ask`, etc.), the original market and event tickers, raw titles, and the full `rules_primary` text for debugging.

---

## 6. Participant Grouping Logic

### Preferred key: stable identity UUID (`IdentityResolver`)

Each sport defines an `IdentityResolver` in its `SportConfig.identity`. The resolver tries `candidate_paths` in order for a stable UUID:
- **Tennis:** `custom_strike.tennis_competitor`
- **NBA / WNBA:** `custom_strike.basketball_team`

When a UUID is found, it is used directly as `player_key` (`player_key_source = "competitor_uuid"`, `mapping_confidence = "high"`). The same UUID links a participant's contracts across all series and rounds.

### Name fallback

When no UUID is present across all candidate paths, `player_key = yes_sub_title.casefold()` (the normalized display name). This is `player_key_source = "name_fallback"`, `mapping_confidence = "low"`. Name-based keys can drift between markets or collide between same-named players.

### Display name resolution (`data.display_player_name`)

Priority order (implemented in `data.display_player_name`):

1. **Alias override:** `config.NAME_ALIASES.get(player_key)` — keyed by competitor UUID, currently empty but patchable for correcting drifted names.
2. **Clean source name:** `player_name_raw` (`yes_sub_title`) is shown verbatim if it contains any uppercase or a space — preserving accents, particles, and real casing (`"Stéphane de Robert"` stays `"Stéphane de Robert"`).
3. **Titleized fallback:** A bare lowercase token like `"aryna_sabalenka"` is title-cased to `"Aryna Sabalenka"` via `data._titleize_fallback`.

Internal identifiers (`player_key`, `player_name_raw`, `competitor_uuid`) are always preserved as separate fields for debug and export.

### Grouping in the consistency checker

`consistency.build_checks` groups by `(player_key, tournament)` — never by the display name and never mixing tournaments. Two competitors with the same display name (e.g. `"Alex Smith"`) that have different keys are never merged. A player appearing in two tournaments gets separate ladders per tournament. This is enforced by the test `test_build_checks_groups_by_player_key_not_display_name`.

### UI player selector disambiguation

When two players share the same display name but different keys, `app.py` appends a 6-character key suffix: `"Alex Smith [uuid-o]"` vs `"Alex Smith [uuid-t]"`.

### Known failure modes

- Name-fallback keys (`low` confidence) can collide across markets or drift if Kalshi changes name formatting.
- A player with only a name fallback key may appear as a duplicate if the same player's name is formatted differently in different series.
- `NAME_ALIASES` is currently empty (`config.py:65`). It exists as a patch point for correcting known drift without touching application code.

---

## 7. Sport Abstraction (`sports.py`) and Contract Classification

### The `SportConfig` abstraction

All sport-specific logic is encapsulated in `sports.SportConfig` — a frozen dataclass holding everything the engine needs to handle one sport. The engine (`data.py`, `consistency.py`, `dutchbook.py`) calls methods on the config; it never hardcodes a sport. Adding a sport means calling `sports.register(SportConfig(...))`.

A `SportConfig` holds:
- `sport_id`, `label`, `emoji` — identity and display
- `series_prefixes`, `default_series`, `winner_tickers` — which series belong to this sport
- `identity: IdentityResolver` — resolves a stable participant key from a market dict (tries `candidate_paths` in order, then falls back to normalized display name)
- `ladder: LadderSpec` — the containment ladder: `node_order` (broad→deep tuple), `adjacent_pairs` (child/parent tuples), `match_stage_to_node`, `advance_stage_to_node`
- `category_labels: dict[str, str]` — user-facing category strings keyed by family
- `round_patterns: tuple[tuple[str, str], ...]` — ordered `(label, regex)` pairs for stage extraction (most-specific first)
- `stage_rank: dict[str, int]` — integer sort keys per stage label
- `ladder_families: frozenset[str]` — which families participate in ladder checks
- `match_family: str` — the head-to-head family name (`"match"` for tennis/NBA/WNBA; `""` for golf, which has no head-to-head and so produces no dutch books)
- `divisions: dict[str, list[str]]`, `division_label: str` — UI split (tennis: `{"Women": ["WTA"], "Men": ["ATP"], "Both": ...}`; NBA/WNBA/golf: empty)
- `family_fn`, `stage_fn`, `node_fn`, `division_fn` — small per-sport callables
- `exact_series: frozenset[str]` (defaulted empty) — exact ticker ownership. When non-empty, these tickers resolve to this sport **before** any prefix/winner match (most specific wins regardless of registry order), and `discover_series_for_sport` short-circuits the `/series` scan for exact-only sports. Golf uses this to own exactly its 4 finishing-position series (`KXPGATOP5/10/20`, `KXPGATOUR`) without a broad prefix that would swallow round-finishers/H2H/props (which resolve to `UNKNOWN`).

The `SportConfig.classify(series_ticker, market_dict)` convenience method returns a `MarketClassification` combining family, stage, stage_rank, ladder_node, eligible_for_ladder_checks, confidence, and reason.

The registry functions are: `sports.register(cfg)`, `sports.get_sport(sport_id)`, `sports.all_sports()`, `sports.sport_for_series(series_ticker)`. Unknown series resolve to `sports.UNKNOWN` (an explicit unsupported config) — **never silently to tennis**.

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
- Division: none (no ATP/WTA equivalent).

**WNBA (`sports.WNBA`, `sport_id="wnba"`):**
- Prefix: `KXWNBA`. Default series: `KXWNBA`, `KXWNBAPLAYOFF`, `KXWNBASEMIFINAL`, `KXWNBAFINAL`, `KXWNBASERIES`, `KXWNBAGAME`.
- Identity: `custom_strike.basketball_team` (same as NBA).
- Ladder (modern single-bracket format): `Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship`.
- Families: `winner`, `advance`, `match`, `game`, `other`.
- Division: none.

### Family classification (`SportConfig.family_of`)

The family (equivalent to the old `kind` field — `kind` is an alias for `family` on `MarketClassification`) is derived from the series ticker by a sport-specific callable. Back-compat: `data.classify_kind(ticker)` delegates to the sport's `family_fn` via the sport registry.

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

Contracts whose `family == "other"` or `eligible_for_ladder_checks == False` are included in the data but excluded from the consistency checker (no node mapping). Contracts whose stage does not map to a tracked ladder node are emitted as `UNKNOWN_RELATIONSHIP` rows — never silently dropped, never treated as violations.

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

### 9a. Containment-ladder consistency checker (`consistency.py`)

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

A deeper outcome must not price higher than a broader one. `build_checks` groups by `(player_key, tournament)`, resolves the sport per group, and checks adjacent pairs from the group's `LadderSpec`. Back-compat aliases `NODE_ORDER`, `ADJACENT_PAIRS`, `MATCH_STAGE_TO_NODE`, `ADVANCE_STAGE_TO_NODE` at the module level reference the tennis ladder and are used by tennis-only code and tests.

#### Match-alignment equivalence

When a participant has both a market source (advance/winner) and a match source for the same node, the two are compared as equivalent. Example: "Quarterfinal win ≡ Reach Semifinal". This check runs in both directions (forward and reverse).

These comparisons always carry a `rule_flag` (`RULE_CHECK_REQUIRED` or `RULE_MISMATCH`) because settlement rules may differ between the two markets. The app never calls these "arbitrage" — they are "executable inconsistencies, rule-dependent."

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

The direction follows the winning firm cross for `EXECUTABLE_VIOLATION`; defaults to forward containment for display-only.

`WIDE_QUOTE` gets **no action** — it is watchlist-only.

#### Tradability

`tradable_now` is set to `"Yes"` only when:
- Status is `EXECUTABLE_VIOLATION`
- Both legs have `status == "active"`
- No rule flag (or `"Yes — rule-dependent"` for equivalence pairs)

All other cases: `"No"`. Plain-English blockers from `glossary.BLOCKERS` explain why.

#### Near-edge watchlist (`bucket_of`)

`CLEAN` rows whose firm executable gap (`child_bid_c − parent_ask_c`) is in `[NEAR_EDGE_MIN_C, 0]` (default `[-5, 0]`) cents, and whose worst quote quality is `"Tight"` or `"OK"`, appear in the near-edge watchlist. No buy instruction is shown.

#### Profit calculation

For `EXECUTABLE_VIOLATION` only:
- `exec_gap_c` = gap in cents (child bid − parent ask for forward, or parent bid − child ask for reverse)
- `exec_min_size` = `min(long_leg_size, short_leg_size)`
- `exec_max_profit_dollars` = `exec_gap_c × exec_min_size / 100` (gross, before fees/slippage)

These fields are `None` for all other statuses.

---

### 9b. Dutch-book / MECE detector (`dutchbook.py`)

A **separate check family** from the containment ladder, implemented in its own Streamlit-free module. A dutch book is an executable arbitrage (not merely an "inconsistency" — the legs are outcomes of the **same event** and settle together, so no rule caveat applies) on a mutually-exclusive-and-exhaustive set of binary markets: covering every outcome costs less than the guaranteed 100¢ payout.

#### What it detects

Currently the **2-outcome case only**: any event with **exactly two distinct-participant markets** (head-to-head match/series OR a single per-game market for draw-free sports). The two markets are mutually exclusive and exhaustive by construction for draw-free sports, so the pair is MECE.

**Two directions, each a pair of BUYS (never "sell"):**
- **Underround → Buy YES both:** `yes_ask_A + yes_ask_B < 100¢`. Locked profit per unit = `100 − cost`.
- **Overround → Buy NO both:** `no_ask_A + no_ask_B < 100¢` (with `100 − yes_bid` fallback). Locked profit per unit = `100 − cost`.

Because `bid ≤ ask`, the two directions are mutually exclusive — at most one fires per event.

**Eligible event families:** The sport's `match_family` (tennis `"match"`, NBA/WNBA `"match"` = playoff series head-to-head) **plus** `"game"` (NBA/WNBA single per-game markets). Props, winner, advance markets are NOT included. Unknown series (`sports.UNKNOWN`) are excluded. The exactly-2-distinct-participants guard in `_detect_pair` is the real MECE safety net.

#### API

`dutchbook.find_dutch_books(rows: list[dict]) -> list[dict]`
- Accepts the output of `df.to_dict("records")` — NaN-safe.
- Groups `match`/`game` rows by `event_ticker`.
- Returns ≤ 1 finding per event, sorted strongest-edge-first (`exec_gap_c` descending, tiebreak on `event_ticker`).
- Each finding has status `EXECUTABLE_DUTCH_BOOK`, `direction` (`"underround"` or `"overround"`), `tradable_now`, `blockers`, two-leg action plan (`action_1_*`, `action_2_*`), and profit fields mirroring the consistency row schema.

#### One status: `EXECUTABLE_DUTCH_BOOK`

Defined as `dutchbook.EXECUTABLE_DUTCH_BOOK = "EXECUTABLE_DUTCH_BOOK"`. This is distinct from `EXECUTABLE_VIOLATION` so ladder semantics stay separate; `consistency.STATUS_GROUP` maps it to `"Broken"` (same high-priority group). `consistency.bucket_of` routes it: actionable if `tradable_now == "Yes"`, else blocked.

#### Tradability

`tradable_now = "Yes"` when both legs have positive size **and** both markets are `"active"`. No rule caveat — same event, both legs settle together.

#### Sizes

Buy-YES leg size: `yes_ask_size`. Buy-NO leg size: `yes_bid_size` (buying NO matches resting YES bids on Kalshi's unified book). Tradable units = `min(leg_a_size, leg_b_size)`.

#### Profit fields

Same schema as containment rows: `exec_gap_c`, `exec_min_size`, `exec_max_profit_dollars` (gross, before fees/slippage). `cost_c` (combined cost of both legs) is added.

#### Engine integration

Detection lives entirely in `dutchbook.py`. The only `consistency.py` touches are: one `bucket_of` branch and a `STATUS_GROUP` entry (the status string `"EXECUTABLE_DUTCH_BOOK"` is held as a literal to avoid an import cycle). The UI renders a **dedicated "Dutch-book arbitrage — match & game books" section** immediately after "Actionable now"; it cannot reuse the ladder table because both legs are the same side.

#### Out of scope

- n-outcome winner fields (≥ 3 outcomes): need a field-completeness proof + multi-leg representation (planned as future stage).
- Per-game books on tennis (tennis has no `game` family and no per-game series, so it is unaffected).

---

## 10. Dashboard and UI Logic

### Main user workflow

1. Pick a **Sport** (radio, top of sidebar: Tennis / NBA / WNBA). The whole dashboard — series, ladder, division controls, contract families — is driven by that sport's `SportConfig`.
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

**Note:** The gross-edge opportunity-ranking bar chart (Altair) has been **removed** (Stage 0). The Actionable-now table (sorted by gross edge) is the ranking surface. Stage 2 will replace it with a unified cross-sport sortable table.

### Auto-refresh and freshness

`render_dashboard()` is decorated with `@st.fragment(run_every=run_every)`. Each tick calls `load_contracts` (TTL-cached at `REFRESH_TTL=30s`). Full-scan mode is clamped to a minimum of `FULL_SCAN_MIN_INTERVAL=120s`.

`render_freshness()` is a **separate fragment** running at `FRESHNESS_TICK_SECONDS=1s`. It reads from `st.session_state["_freshness"]` (populated by the main fragment on each real fetch) and re-renders the data-freshness strip every second — so "Data age" climbs live and the stale warning appears without re-fetching.

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

## 11. Filters and Toggles

### Filter split (critical design invariant)

- **Membership filters** (`filters.apply_membership`): narrow all sections including Actionable now and the Dutch-book section. These are "universe" filters — reducing which contracts are even considered.
- **Threshold filters** (`filters.apply_thresholds`): narrow everything *except* Actionable now and the Dutch-book section. These are quality gates that should not hide real executable edges.

| Filter / Toggle | Purpose | Default | Notes |
|---|---|---|---|
| Sport (radio) | Tennis / NBA / WNBA | Tennis | Changes what is fetched; drives the whole dashboard |
| Contract family (multiselect) | All contract types for the sport | All ON | Controls what is FETCHED; family toggles are the only control that changes API requests |
| Auto-refresh (toggle) | Periodic re-fetch | On | Interval selectable: 60/120/300s |
| Refresh interval | Seconds between auto-refresh ticks | 120s | Clamped to 120s for full scan |
| Scan all … series | Fetch all series for the active sport | On (default) | Slows to ~20s+; backed by session_state for read-ahead |
| Division / Tour (radio) | Women / Men / Both (tennis only) | Both | Pre-applied to `df`; NBA/WNBA have no division control |
| Tournament / season (multiselect) | Filter by `tournament` key | All | Membership filter; default = all loaded tournaments |
| Participant (selectbox) | "All" = no filter; a name = filter dashboard + drive detail section | All | One unified control; appends 6-char key suffix on name collision |
| Event / game (multiselect) | Filter by event label | None | Membership; maps to `event_ticker` set |
| Stage / layer (multiselect) | Filter by ladder node or match stage | None | Membership; matches `layers` tuple field |
| Min traded volume (slider) | Drop contracts below historical traded volume | 0 | Advanced → membership filter |
| Min available size | Threshold: drop comparisons with `exec_min_size < N` | 0 | Threshold (Thresholds expander) |
| Quote quality (select) | All / Tight+OK only / Include wide | All | Threshold |
| Market status (select) | Any / Active only | Active only | Threshold — checks both legs; finalized markets remain visible in Full diagnostics |
| Show blocked opportunities | Show/hide Blocked section | On | Sections expander |
| Show near-edge watchlist | Show/hide Near-edge section | On | Sections expander |
| Show watchlist signals | Show/hide Watchlist signals section | Off | Sections expander |
| Show data-quality issues | Show/hide Data-quality issues section | Off | Sections expander |
| Show non-laddered / unmapped | Show/hide game/props/other contracts | Off | Sections expander |
| Time zone (selectbox) | Display zone for all timestamps | Europe/Lisbon | Display expander; never affects comparison math |
| Show IDs & codes | Reveal series/event/market tickers + participant IDs | Off | Display expander |
| Advanced: diagnostics & debug | Show Full diagnostics + Debug panel | Off | Display expander; hides per-player detail + diagnostics by default |
| Show explanations | Help captions in player detail | On | Advanced — data scope |
| Outcome status (select) | Filter Full diagnostics by status group | All | Applies only to the Full diagnostics table |

**Note:** "Min gross edge (¢)" has been **removed** from the UI — no minimum edge gate; any positive edge is shown in Actionable now.

---

## 12. Error Handling and Data Quality

| Problem | Current App Behavior | User-Visible Treatment | Notes |
|---|---|---|---|
| Network error on series load | `KalshiError` raised after `MAX_RETRIES` retries | `st.error(...)` + `st.stop()` — page stops | Retry with exponential backoff first |
| One series fails to load | Collected in `errors` list, never dropped | Shown in Debug expander as a warning | Sequential retry pass after concurrent load |
| Pagination truncated (cursor remaining at cap) | `KalshiError` raised | Same as network error | Silent partial data is never returned |
| Missing competitor UUID | Name-based key fallback | `mapping_confidence = "low"` visible in detail + debug | May drift/collide |
| Empty order book (0.00/1.00) | Treated as "No quote" | `quote_quality = "No quote"`, `display_pct = None` | Never shown as 50% |
| Crossed book (ask < bid) | Quote quality "Crossed"; excluded from executable test | `quote_quality = "Crossed"` in tables | Never produces a midpoint or executable finding |
| One-sided book | `quote_quality = "One-sided"` | Shown in detail; consistency gets `MISSING_QUOTE` | |
| Missing display price on a leg | Display test blocked for that pair | `MISSING_QUOTE` status | Executable test can still run if firm bid/ask present |
| Size = 0 on a leg | Executable test blocked; display test can still run | `QUOTE_SIZE_MISSING` or `DISPLAY_VIOLATION` depending on display cross | |
| Duplicate rows for same node/source | Deterministic representative chosen (`_representative_key`) | `duplicate_node_sources` shown in Debug | Higher volume → preferred; then lexically smallest ticker |
| Round not in tracked layer map | `UNKNOWN_RELATIONSHIP` emitted | "Unverifiable" in full diagnostics | R16, R32, R64, R128 currently not in `MATCH_STAGE_TO_NODE` |
| Unknown series ticker (foreign sport) | `sports.sport_for_series` returns `UNKNOWN`; `build_contracts` skips the row | Counted in `n_excluded_unknown`; shown in Debug | Never silently mis-parsed as tennis |
| Non-FO tennis event in a tennis series | Included (no FO gate); stamped with its own `tournament` key | Visible in dashboard; filterable by Tournament selector | `is_french_open_event` is a helper, not a gate |
| Series title missing (URL slug) | URL falls back to series page | Link still works; goes to series-level page | Non-fatal by design |
| NaN from pandas records path | `_isna` / `_num` normalize float NaN to None | Transparent to user | `None` becomes float NaN through `df.to_dict("records")` |
| Malformed market title | `_extract_round` returns `""`, stage stays empty | Contract label uses `_clean_title` fallback | |

---

## 13. Testing and Validation

Tests live in `tests/`. Run with `pytest -q`. No network access in tests (all HTTP is monkeypatched or synthetic).

**Current test count: 158 tests across 9 files** (`test_data.py`, `test_consistency.py`, `test_glossary.py`, `test_client.py`, `test_filters.py`, `test_viz.py`, `test_sports.py`, `test_dutchbook.py`, `test_app.py`).

### Contract Discovery Tests (`test_data.py`)

- `test_pagination_cap_raises_on_remaining_cursor` — paginator raises, never silently truncates
- `test_pagination_stops_cleanly_when_cursor_empties` — normal two-page case
- `test_non_fo_competition_in_window_is_rejected` — a named non-FO competition disqualifies even if in-window dates
- `test_fo_competition_is_accepted` — explicit FO competition accepted
- `test_date_window_fallback_only_when_no_competition` — fallback only when competition is absent
- `test_build_contracts_includes_all_tennis_and_stamps_tournament` — all tennis events included; verifies `tournament` key is always non-empty
- `test_tournament_of_sources_and_never_empty` — all four resolution paths produce a non-empty key; `tournament_source` is set

### Participant Grouping Tests (`test_data.py`)

- `test_build_contracts_typing_and_mapping` — UUID present → high confidence, correct opponent, tour, stage
- `test_display_name_prefers_source_verbatim` — accented names preserved
- `test_display_name_alias_overrides_source` — alias from `NAME_ALIASES` takes priority
- `test_display_name_titleizes_bare_key` — `"aryna_sabalenka"` → `"Aryna Sabalenka"`
- `test_build_contracts_exposes_internal_identifiers` — all key fields present and correct
- `test_build_checks_groups_by_player_key_not_display_name` — two same-named players not merged

### Contract Classification Tests (`test_data.py`)

- `test_classify_kind_order_and_values` — covers all kinds including EXACTMATCH-before-MATCH ordering
- `test_tour_of` — ATP/WTA for standard series
- `test_winner_ticker_tour_map_all_variants` — all FO winner ticker variants including `KXFOPENWMENSINGLE`
- `test_extract_round_word_boundaries` — regex patterns and boundary conditions

### Quote and Pricing Tests (`test_data.py`)

- `test_to_float_parses_and_guards`, `test_to_cents_is_exact_integer` — parsing edge cases
- `test_quote_quality_buckets` — all quality labels
- `test_yes_mid_and_spread_handle_empty_book` — empty book returns None
- `test_display_prob_midpoint_else_last_else_blank`
- `test_display_cents_matches_prob_logic`
- `test_crossed_book_is_rejected` — crossed book never produces midpoint, never "Tight"
- `test_build_contracts_parses_no_side_prices_and_deep_link` — NO prices and URL
- `test_kalshi_market_url_deep_link_and_fallback` — URL format and fallback logic
- `test_slugify_matches_kalshi_series_slug`

### Edge Logic Tests (`test_consistency.py`)

- `test_executable_violation_requires_cross_and_size`
- `test_forward_violation_exposes_profit_and_long_broad_short_deep`
- `test_reverse_equivalence_violation_is_long_deep_short_broad`
- `test_profit_fields_blank_for_clean_row`
- `test_cross_without_size_downgrades_to_quote_size_missing`
- `test_display_violation_is_warning_not_broken`
- `test_missing_quote_when_no_firm_book` / `test_missing_quote_when_no_display`
- `test_wide_quote_when_ordered_but_wide`
- `test_clean_when_ordered_and_tight`
- `test_equivalence_checks_both_directions`
- `test_equivalence_sets_rule_flag`
- `test_equivalence_reverse_cross_reason_names_correct_legs`
- `test_crossed_leg_is_not_executable`
- `test_sizeless_cross_with_display_cross_stays_display_violation`
- `test_executable_containment_is_buy_yes_parent_buy_no_child`
- `test_buy_no_price_falls_back_to_100_minus_child_bid`
- `test_tradable_now_no_when_a_leg_is_inactive`
- `test_tradable_now_no_when_size_missing`
- `test_tradable_now_no_for_display_only_violation`
- `test_tradable_now_rule_dependent_for_equivalence_executable`
- `test_wide_quote_is_watchlist_only_no_action`
- `test_layer_spreads_full_chain` / `_missing_layer` / `_inverted` / `_missing_price` / `_via_dataframe_records`
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

- `test_unknown_series_resolves_to_unknown_not_tennis` — foreign ticker → `UNKNOWN`, not tennis
- `test_registry_has_tennis_and_nba` — registry contains expected sports
- `test_nba_ladder_families_map_to_nodes` — NBA classification end-to-end
- `test_nba_per_game_is_ineligible_and_excluded` — `game` family skipped by ladder
- `test_unsupported_markets_carry_reason` — unsupported classification has a reason string
- `test_low_confidence_identity_is_flagged` — name-fallback confidence marked `"low"`
- Tennis-preserved tests verifying back-compat aliases

### Filter Tests (`test_filters.py`)

- `apply_membership` edge cases: empty selection = no filter; NaN-safe volume; layer tuple matching
- `apply_thresholds` edge cases: min_edge_c, min_size, quote_mode, status_mode

### Viz Tests (`test_viz.py`)

- `test_payoff_chart_data_*` — tidy frame shape, role labels, empty input
- `test_ladder_prices_*` — inversion detection, missing-price handling, empty input

### App Tests (`test_app.py`)

- Streamlit `AppTest` smoke test: full UI render pipeline with mocked network, no real HTTP
- Exercises the Participant selector path → per-player detail and `expected_nodes` ladder path
- Catches app.py wiring bugs (tuple unpacking, column references, widget config)

### Regression Tests

Key invariants that must not regress:

- `EXECUTABLE_VIOLATION` is the only containment-ladder "Broken" status; `EXECUTABLE_DUTCH_BOOK` is the Dutch-book "Broken" status.
- `WIDE_QUOTE` rows get **no** action plan.
- Actionable now is **never** narrowed by threshold filters.
- Dutch-book section is **never** narrowed by threshold filters.
- `build_checks` groups by `(player_key, tournament)`, never display name.
- An empty `0.00/1.00` book is **never** treated as a price.
- Pagination truncation raises rather than silently returns partial data.
- Unknown series resolve to `UNKNOWN`, never silently to tennis.

---

## 14. Extension Plan (Roadmap)

> **STATUS: PLANNED — NOT YET IMPLEMENTED.** The six-stage forward roadmap is detailed in `docs/ROADMAP.md` and summarized in §19 of this document. Everything in that section is planned, not built. §1–13 above describe the *current* (built) state. This section notes the direction and what is already generic vs. what remains to be done.

### What is already generic (no further parameterization needed)

The multi-sport engine is live. The following are already sport-agnostic:

- **Sport abstraction:** `sports.SportConfig` / `sports.register` / `sports.sport_for_series` — adding a new sport is a `register(SportConfig(...))` call in `sports.py`.
- **Participant identity:** `IdentityResolver` with `candidate_paths` handles any stable-UUID scheme.
- **Containment ladder:** `LadderSpec` (`node_order`, `adjacent_pairs`, `match_stage_to_node`, `advance_stage_to_node`) is pure data — any ordered hierarchy works.
- **Family/stage/node callables:** sport-specific functions in `sports.py` hold the pattern-matching logic; the engine calls them through the config.
- **Dutch-book detector:** `dutchbook.find_dutch_books` is sport-agnostic via `sports.sport_for_series`.
- **Quote handling:** `to_cents`, `quote_quality`, `display_prob` are fully generic.
- **Outcome relationship logic:** `_classify`, `build_checks`, `bucket_of` are abstract; ladder labels come from config.
- **Edge / spread calculation:** `exec_gap_c`, `exec_min_size`, `layer_spreads` are generic.
- **Tournament stamping:** `data.tournament_of` is generic — works for any sport's competition/event metadata.

### What is still tennis-specific (French Open helpers)

- `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW` in `config.py` — French Open–specific; `is_french_open_event` uses them but is no longer a gate.
- The FO date window in `config.py` is year-specific — update annually.

### Planned roadmap (Stages 1–6)

See §19 for the full staged plan. In brief:

1. **Stage 1:** Opportunity schema (`opportunity_id`, required `blocked_reason`, `relationship_type`) + SQLite snapshot store (`store.py`).
2. **Stage 2:** Cross-sport unified scanner (`scanner.py`) — one always-on table ranked best→worst across all wired sports.
3. **Stage 3:** Lifecycle diffs (`lifecycle.py`) — new-actionable alerts, blocked-change detection, recently-actionable backlog.
4. **Stage 4:** FastAPI REST layer (`api.py`) exposing `/opportunities`, `/backlog`, `/coverage`.
5. **Stage 5:** NiceGUI dashboard (Streamlit cutover/retirement).
6. **Stage 6:** Export overhaul (`export.py`).

None of these modules exist yet. Do not claim `store.py`, `scanner.py`, `lifecycle.py`, `api.py`, or NiceGUI exist.

---

## 15. Code / File Map

| File | Responsibility | Important Functions / Classes | Notes |
|---|---|---|---|
| `config.py` | All tunables and constants | `BASE_URL`, `DEFAULT_SERIES`, `TENNIS_SERIES_PREFIXES`, `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW`, `SPREAD_REASONABLE`, `DISPLAY_TOL_C`, `NEAR_EDGE_MIN_C`, `MAX_RPS`, `REFRESH_TTL`, `TIMEZONE_DEFAULT`, `TIMEZONE_OPTIONS`, `STALE_AFTER_SECONDS`, `FRESHNESS_TICK_SECONDS` | Pure constants; no logic; no imports |
| `sports.py` | Sport abstraction registry | `SportConfig`, `LadderSpec`, `IdentityResolver`, `IdentityResult`, `MarketClassification`, `sport_for_series`, `register`, `all_sports`, `get_sport`, `extract_round`, `TENNIS`, `NBA`, `WNBA`, `UNKNOWN` | Only imports `config` + stdlib; no pandas; no Streamlit; independently testable |
| `kalshi_client.py` | HTTP, pagination, throttle, retry, concurrency | `_get`, `get_paginated`, `get_events`, `discover_series_for_sport`, `discover_tennis_series`, `get_events_for_series`, `get_series_titles`, `_throttle`, `KalshiError` | No Streamlit; no data parsing; process-wide rate limiter |
| `data.py` | Parse raw JSON → contract rows; pricing; tournament stamping; identity | `build_contracts`, `is_french_open_event`, `tournament_of`, `to_cents`, `to_float`, `quote_quality`, `display_prob`, `yes_mid`, `classify_kind`, `tour_of`, `display_player_name`, `kalshi_market_url`, `link_audit`, `fmt_time`, `data_age_seconds`, `is_stale`, `parse_fetched_at`, `CATEGORY` | No Streamlit; no pandas; independently testable |
| `consistency.py` | Containment checking; action plan; dashboard bucketing; scenario payoffs | `build_checks`, `build_player_nodes`, `_classify`, `layer_spreads`, `expected_nodes`, `bucket_of`, `representative`, `duplicate_node_sources`, `spread_certainty_label`, `scenario_payoffs`, `node_of`, `NODE_ORDER`, `ADJACENT_PAIRS`, `STATUS_GROUP` | No Streamlit; depends on pandas; depends on data, glossary, sports |
| `dutchbook.py` | 2-outcome Dutch-book / MECE detector | `find_dutch_books`, `_detect_pair`, `_direction_candidate`, `EXECUTABLE_DUTCH_BOOK`, `CHECK_TYPE` | No Streamlit; no pandas; depends on sports, glossary; independently testable |
| `filters.py` | Two-pass membership + threshold filtering | `apply_membership`, `apply_thresholds`, `QUOTE_MODES`, `STATUS_MODES` | No Streamlit; pure pandas; independently testable |
| `viz.py` | Chart data preparation | `payoff_chart_data`, `ladder_prices` | No Streamlit; pure pandas; independently testable. Note: `opportunity_ranking` was removed (Stage 0) |
| `glossary.py` | All user-facing help text | `GLOSSARY`, `BLOCKERS`, `WATCHLIST_NOTE`, `COLUMN_HELP`, `help_for` | No imports; single source of truth for tooltips and blocker reasons |
| `app.py` | Streamlit UI; data load; cache; rendering | `load_contracts`, `discover`, `render_dashboard`, `render_freshness`, `_buy_disp`, `_payoff_block` | Only file with Streamlit imports; delegates all math to other modules |
| `tests/test_data.py` | Unit tests for data layer | All `test_*` functions | No network; covers parsing, pricing, tournament stamping, build_contracts |
| `tests/test_consistency.py` | Unit tests for consistency layer | All `test_*` functions | No network; covers `_classify`, `build_checks`, `layer_spreads`, `bucket_of` |
| `tests/test_dutchbook.py` | Unit tests for Dutch-book detector | All `test_*` functions | No network; covers underround/overround, blocked, false-positive guards, NBA/WNBA per-game |
| `tests/test_sports.py` | Unit tests for sport abstraction | All `test_*` functions | No network; covers registry, classification, NBA ladder, unknown-sport guard |
| `tests/test_glossary.py` | Glossary integrity tests | `test_every_term_has_short_and_long`, `test_consistency_only_emits_known_blocker_text` | Guards against orphan jargon |
| `tests/test_client.py` | Unit tests for HTTP client | Rate-limiter, pagination, backoff | No real network; uses monkeypatching |
| `tests/test_filters.py` | Unit tests for filter layer | `apply_membership`, `apply_thresholds` edge cases | No network; pure pandas |
| `tests/test_viz.py` | Unit tests for viz layer | `payoff_chart_data`, `ladder_prices` | No network |
| `tests/test_app.py` | Streamlit smoke test | `AppTest` end-to-end with mocked network | Tests full render pipeline; catches wiring bugs |
| `scripts/check_links.py` | Live link-reachability check | — | Runs from an unthrottled network; Kalshi throttles bots |
| `scripts/export_glossary.py` | Generate `docs/GLOSSARY.md` | — | Run locally; output committed to docs/ |
| `docs/GLOSSARY.md` | Generated glossary reference | — | Do not edit manually; regenerate from `glossary.py` |

### What each file should NOT own

- `data.py`, `consistency.py`, `dutchbook.py`, `filters.py`, and `viz.py` must never import Streamlit.
- `data.py` and `dutchbook.py` must not import pandas (plain dicts/lists only).
- `sports.py` must not import any of the above modules (only `config` + stdlib) — no circular imports.
- `kalshi_client.py` must not contain any parsing or business logic.
- `app.py` must not contain any math; delegate to `consistency.py`, `dutchbook.py`, and `filters.py`.
- `config.py` must not contain any functions or imports.
- `glossary.py` must not contain any imports.

### Technical debt / refactoring notes

- `consistency.py` imports pandas while `data.py` and `dutchbook.py` do not; this asymmetry means `consistency.py` cannot be tested without pandas installed.
- The `FULL_SCAN_MIN_INTERVAL` clamping warns the user but does not prevent them from setting a short interval on the first load before the warning appears.
- Back-compat aliases `NODE_ORDER`, `ADJACENT_PAIRS`, `MATCH_STAGE_TO_NODE`, `ADVANCE_STAGE_TO_NODE` in `consistency.py` reference the tennis ladder and are used by tennis-only tests; multi-sport code resolves the ladder via `_sport_for_row`.
- Back-compat aliases `_ROUND_PATTERNS`, `_STAGE_RANK`, `CATEGORY` in `data.py` reference the tennis `SportConfig`; they exist so existing imports and tests continue to work without changes.

---

## 16. Known Limitations

- **Finite sport set:** The engine supports tennis, NBA, and WNBA. Adding a new sport requires a `register(SportConfig(...))` call in `sports.py` and vetting live series. The architecture is designed for this but the work has not been done for other sports.

- **Tennis all-tournament, not French-Open-only:** The FO gate has been removed — all tennis events are included. However, the `is_french_open_event` helper and `FO_WINDOW` date window in `config.py` are still French Open 2026–specific; update `FO_WINDOW` annually for future tournaments.

- **Metadata quality dependency:** The consistency checker relies on Kalshi's `product_metadata.competition`, `custom_strike.tennis_competitor` / `custom_strike.basketball_team`, and stage-keyword text in market titles and rules. If Kalshi changes these fields or their format, tournament stamping and grouping will degrade silently (surfaced in `tournament_source` debug field).

- **Missing quotes are common:** Between rounds or for illiquid participants, most markets have empty or one-sided books. The app handles this gracefully but cannot compute edges where quotes are absent.

- **Imperfect classification:** Contracts whose series ticker has no recognized pattern become `family = "other"` and are excluded from the consistency checker. New series types require adding a family rule to the sport's `family_fn` in `sports.py`.

- **No trade execution:** The app is read-only. All "Buy YES / Buy NO" instructions are informational only.

- **No true arbitrage guarantee for match-alignment pairs:** Match-alignment pairs carry `RULE_CHECK_REQUIRED`/`RULE_MISMATCH` because settlement-rule compatibility is not auto-verified. Dutch-book findings **do not** have this caveat — both legs are outcomes of the same event and settle together.

- **Dutch-book scope is 2-outcome only:** The detector handles exactly-2-outcome events. n-outcome winner fields (≥ 3 outcomes) are out of scope — they need a field-completeness proof and multi-leg representation.

- **No probability modeling:** Display prices are market prices, not de-vigged probabilities. No implied probability calculations or Kelly sizing are implemented.

- **Process-wide rate limiter only:** Multiple processes or containers each have their own limiter. Aggregate rate is `MAX_RPS × process_count`. A large horizontal scale-out would need a shared/distributed limiter.

- **No persistent history:** Each refresh is a stateless snapshot. The planned SQLite snapshot store (`store.py`) is not yet built.

- **UI under active refinement:** Section visibility toggles, threshold filter defaults, and the near-edge window are tunable constants that may need adjustment as real data arrives.

- **Link audit is deterministic, not live:** `data.link_audit` verifies that each URL encodes the correct identifiers (series, event) but does not check live reachability (Kalshi throttles automated HTTP from this environment at 429).

---

## 17. Open Design Questions

- Should `NAME_ALIASES` be editable from the UI sidebar, or only from `config.py`? The current approach (config only) is safe but inflexible.

- What is the exact threshold defining a "near-edge" row? The current `NEAR_EDGE_MIN_C = -5` is a guess. A real threshold should be informed by typical bid/ask movement speed.

- Should `UNKNOWN_RELATIONSHIP` rows (early-round matches, R16 etc.) appear in the default view or only in Full diagnostics? Currently they appear only if "Show data-quality issues" is toggled on.

- Should the Outcome status filter (currently Full diagnostics only) also optionally narrow the Blocked and Watchlist sections? Or should those sections always show all statuses?

- How should the app handle a participant who appears in both ATP and WTA series (scheduling anomaly)? Currently `division_of`/`tour_of` is derived from the series ticker, so they appear under the correct tour, but the player detail is filtered by participant key (not tour).

- How much raw debug data should be visible in the default player detail section vs. behind the Debug/Advanced panel? The current design keeps raw price strings and internal identifiers behind the Advanced toggle by default.

- Should `RULE_MISMATCH` rows ever be shown in Actionable now with a stronger caveat, or always remain in Blocked? The current design puts all rule-flagged rows in "rule-dependent" which is shown in Actionable now — this is a deliberate but potentially confusing choice.

- At what scale of horizontal deployment should the rate limiter be redesigned? The current process-wide limiter is safe for a single-instance deployment but unsound for multiple replicas.

- How should NBA/WNBA per-game markets (`game` family) be surfaced in the ladder view? Currently they appear in the "Non-laddered / unmapped contracts" section (off by default). A dedicated per-game section may be clearer.

- Should the Dutch-book section ever be hidden by a section toggle, or should it always be visible alongside Actionable now? Currently it is always visible (same as Actionable now).

---

## 18. Appendix

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

### B. Sample contract row (synthetic)

```json
{
  "player": "Sorana Cirstea",
  "player_key": "uuid-cir",
  "player_key_source": "competitor_uuid",
  "mapping_confidence": "high",
  "tour": "WTA",
  "kind": "match",
  "category": "Match result",
  "contract": "Beat Mirra Andreeva — Quarterfinal",
  "stage": "Quarterfinal",
  "stage_rank": 5,
  "opponent": "Mirra Andreeva",
  "display_pct": 37.5,
  "yes_bid_pct": 37.0,
  "yes_ask_pct": 38.0,
  "spread_cents": 1.0,
  "quote_quality": "Tight",
  "yes_bid_c": 37,
  "yes_ask_c": 38,
  "no_bid_c": 62,
  "no_ask_c": 63,
  "yes_bid_size": 100,
  "yes_ask_size": 100,
  "volume": 1000,
  "status": "active",
  "kalshi_url": "https://kalshi.com/markets/kxwtamatch/wta-match-winner/kxwtamatch-26jun02andcir",
  "series": "KXWTAMATCH",
  "event_ticker": "KXWTAMATCH-26JUN02ANDCIR",
  "market_ticker": "KXWTAMATCH-26JUN02ANDCIR-CIR"
}
```

### C. Example participant grouping cases

| Scenario | `player_key` | `mapping_confidence` | Notes |
|---|---|---|---|
| UUID present | `"a3b2c1-uuid"` (raw UUID) | `"high"` | Preferred; stable across rounds |
| UUID absent, name present | `"sorana cirstea"` (lowercase) | `"low"` | Can collide; may drift |
| UUID absent, name empty | skipped — `build_contracts` drops rows with no name | — | No display name → no row emitted |

### D. Example consistency check scenarios (live-verified)

| Player | Check | Expected status | Notes |
|---|---|---|---|
| Cirstea (WTA) | QF win ≡ Reach Semifinal | `EXECUTABLE_VIOLATION` + `RULE_MISMATCH` | ~2¢ cross, rules differ |
| Sabalenka (WTA) | Reach Final ≤ Reach Semifinal | `DISPLAY_VIOLATION` | Display prices cross, no firm executable cross |
| Gauff / Swiatek (WTA) | Any pair | `MISSING_QUOTE` | Empty books when inactive |

### E. Debugging checklist

1. **App shows stale data after a code edit:** Fully stop and restart `streamlit run app.py`. A browser "Rerun" does not reload edited modules. Clear `__pycache__` if a phantom `ImportError` persists.

2. **Unexpected `UNKNOWN_RELATIONSHIP` rows:** The match's stage is not in the sport's `match_stage_to_node` map (e.g. NBA First Round may not map to a ladder node). Check `sports.py` for the sport's `_nba_ladder` / `_tennis_ladder` `match_stage_to_node`.

3. **Participant appears under wrong tour (tennis):** `tour_of` / `division_of` may be using substring logic that misfires on a new ticker. Check `sports.py:_tennis_division` and update the explicit winner-ticker sets if needed.

4. **Duplicate participant in the selector:** Two contracts with different `player_key`s but the same display name. The selector appends a 6-char key suffix. Check `mapping_confidence` in the Debug panel (Advanced toggle).

5. **All links going to series page instead of event page:** `series_title` was not fetched. Check the `get_series_titles` call in `app.load_contracts` and the `titles.get(ticker, "")` fallback.

6. **Contracts stamped `Unknown` tournament:** The `competition` field is absent and no keyword/ticker fallback matched. Check `data.tournament_of` and the `tournament_source` column in the Debug panel.

7. **Rate limit errors in production:** `MAX_RPS` is set to 5 (25% of the 20/s ceiling). If errors persist, lower `CONCURRENCY` or `MAX_RPS`. Note the limiter is process-wide only.

8. **Dutch-book detector fires on a non-MECE event:** Check that the event has exactly 2 distinct `player_key` markets. Events with more than 2 markets are excluded by the exactly-2 guard in `dutchbook._detect_pair`.

9. **A sport's per-game markets appear in the containment-ladder sections:** `game` family has `eligible_for_ladder_checks = False`; `build_player_nodes` should skip them. Check that `ladder_eligible` is correctly set in the contract row (`data.build_contracts` stamps it from `MarketClassification.eligible_for_ladder_checks`).

### F. Configuration knobs quick reference

| Constant | Location | Default | What changing it does |
|---|---|---|---|
| `DEFAULT_SERIES` | `config.py` | 6 tennis series | The fast-scan tennis series list; per-sport defaults live in `sports.SportConfig.default_series` |
| `TENNIS_SERIES_PREFIXES` | `config.py` | `("KXATP", "KXWTA")` | Used by `discover_series_for_sport` for the full tennis scan |
| `SPREAD_REASONABLE` | `config.py` | 0.20 ($0.20) | Threshold for trusting midpoint as display price |
| `DISPLAY_TOL_C` | `config.py` | 1¢ | Ignore display gaps below this (noise filter) |
| `NEAR_EDGE_MIN_C` | `config.py` | -5¢ | Near-edge watchlist window lower bound |
| `FO_WINDOW` | `config.py` | 2026-05-18 to 2026-06-09 | FO date-window fallback; update per year |
| `MAX_RPS` | `config.py` | 5 req/s | Rate limiter ceiling |
| `REFRESH_TTL` | `config.py` | 30s | `load_contracts` cache TTL |
| `REFRESH_DEFAULT_SECONDS` | `config.py` | 120s | Default auto-refresh interval |
| `FRESHNESS_TICK_SECONDS` | `config.py` | 1s | How often the freshness strip re-renders (no refetch) |
| `STALE_AFTER_SECONDS` | `config.py` | 300s | Data age threshold for the stale warning |
| `TIMEZONE_DEFAULT` | `config.py` | `"Europe/Lisbon"` | Default display timezone (comparison math unaffected) |
| `TIMEZONE_OPTIONS` | `config.py` | 7 IANA zones | Choices in the timezone selectbox |

---

## 19. Planned evolution (roadmap)

> **STATUS: Stage 0 SHIPPED; Stages 1–6 PLANNED — NOT YET IMPLEMENTED.** Stage 0 (clarity quick
> wins) is now part of the current codebase and described throughout §§1–18 above. The remaining
> stages (1–6) are finalized plans: none of the modules, fields, or UI surfaces described under
> those stages exist in the codebase today. The roadmap introduces a deliberate **scope change**
> — a persisted on-disk store (Stage 1) — which `CLAUDE.md` and §2 "Out of scope" still mark as
> a "don't add"; those scope lines will be updated **only when Stage 1 actually lands**.

The roadmap reframes the app from a tennis/per-sport dashboard into an **opportunity-first, cross-sport
scanner** while keeping the engine/UI split intact. It is sequenced as six stages (Stage 0–5).

### Locked decisions (apply across all planned stages)

- **Persisted SQLite snapshot store** on local disk — but **NO multi-user / server / auth / shared
  rate-limiter build-out** yet (the store is merely *designed* not to preclude that later).
- **Gross edge only** for now — fees / net-edge / slippage remain deferred to a separate later stage;
  the existing "before fees/slippage" caveat stays loud.
- **Cross-sport unified scanner** = all wired sports scanned *simultaneously* over the full loaded
  universe, surfaced as one always-on table ranked best→worst; the header is labelled honestly as
  **"All loaded markets"** (never "all Kalshi markets").
- The **Altair opportunity-ranking graph is replaced by a sortable table** (the unified cross-sport
  table is that surface).
- **Timezone-aware display** with a **`Europe/Lisbon` default** (UTC still selectable); TZ work is
  display-only and never touches the exact-integer-cents comparison math.
- A **data-freshness & coverage strip** is lifted to the main dashboard (not behind Advanced/Debug).
- Streamlit is treated as **throwaway** ahead of a planned React/FastAPI migration, so durable logic
  stays in pure, Streamlit-free engine modules + the store.

### Planned new pure modules (Streamlit-free, unit-testable, migration-safe)

| Module (planned) | Responsibility | Key planned functions |
|---|---|---|
| `store.py` | SQLite snapshot persistence at `config.SNAPSHOT_DB_PATH`; tolerant of concurrent readers; retention cap; schema-version migration. **No sharing/locking/server logic.** | `write_snapshot(fetched_at, opps_df)`, `latest_two()`, `snapshots_since(window)` |
| `lifecycle.py` | Pure diffs/derivations over stored snapshots (no fetching) | `new_actionable(prev, cur)`, `blocked_change(prev, cur)`, `recently_actionable(snapshots, window)` |
| `scanner.py` | Cross-sport aggregation over the full loaded universe; reuses `consistency.build_checks` + `dutchbook.find_dutch_books` per sport, concats with `sport` stamped, ranked | `unified_opportunities(per_sport_frames)` |
| `export.py` *(optional)* | Diagnostics-bundle assembly for the export overhaul | bundle helpers |

### Planned schema additions (engine layer)

- **`opportunity_id`** — a deterministic short hash (`hashlib`, no randomness/timestamps) over a stable
  key (consistency: `sport|player_key|tournament|child_node|parent_node|check_type`; dutch-book:
  `sport|event_ticker|sorted(player_keys)|dutch_book`). Stamped on every `consistency` and `dutchbook`
  row. Same inputs → identical id across runs.
- **`blocked_reason`** — promoted to a **REQUIRED** schema field on every opportunity row: non-empty
  **iff** the row routes to the `blocked` bucket, `""` otherwise (test-enforced). The existing
  human-readable `blockers` string is kept; an optional `unblock_condition` is added.
- **`relationship_type`** — `containment_adjacent` | `match_alignment` | `dutch_book`, for the planned
  relationship export.

### The six stages

| Stage | Goal | New / touched files (planned) | Notable deliverables |
|---|---|---|---|
| **Stage 0 — Clarity quick wins (no new infra)** ✅ SHIPPED | Stop the dashboard misleading or burying info; immediate value with zero new infrastructure. | `app.py`, `config.py` (`STALE_AFTER_SECONDS`, TZ options), `data.py` (`fmt_time`, age/stale helpers), `viz.py` (delete `opportunity_ranking`) | TZ selectbox (**Lisbon default**) + `fmt_time()` on every timestamp; **Altair ranking chart removed**; **"Show IDs & codes"** toggle (default OFF); always-visible **data-freshness & coverage strip** (data time, data age, refresh status, stale-data warning, coverage / fetch-failure counts via its own 1s fragment); **Debug + Full-diagnostics moved behind a single "Advanced: diagnostics & debug" toggle, default OFF** (the freshness strip stays out of Advanced). All shipped in `main`. |
| **Stage 1 — Opportunity schema + SQLite snapshot store** | A stable identity + persisted history substrate that survives the React migration. | `consistency.py`, `dutchbook.py`, **new `store.py`**, `config.py` (`SNAPSHOT_DB_PATH`), `glossary.py` | `opportunity_id`; **`blocked_reason` as a required field**; `relationship_type`; **SQLite snapshot store** written once per refresh with the fields the change-classifier needs; `latest_two()` / `snapshots_since()`; retention cap + schema migration. **No multi-user/server.** |
| **Stage 2 — Cross-sport global scanner (always-on unified table)** | One always-visible table of actionable opps across **all wired sports simultaneously**, ranked best→worst, computed over the full loaded universe **independently of any selection**. | **new `scanner.py`**, `app.py`, `sports.py` (`ALL_SPORTS`), `filters.py` (sport filter), `config.py` (refresh clamp) | `scanner.unified_opportunities`; default **"All sports"** sortable `st.dataframe` (replaces the ranking graph) sortable by gross edge / size / age / status; header reads **"All loaded markets (<fetch mode>)"** — core-series vs full-scan labelled honestly, never "all Kalshi"; a simple unified-table CSV download; per-sport drill-down preserved; partial per-sport failure must not blank the table. |
| **Stage 3 — Lifecycle: alerts + recently-actionable backlog** | Make opportunity appearance/disappearance impossible to miss; keep a windowed record — all from pure diffs over the store. | **new `lifecycle.py`**, `app.py`, `config.py` (`BACKLOG_WINDOWS`, `ALERT_PERSISTENCE_OPTIONS`), `glossary.py`, reads/writes `store.py` | New-actionable alert (banner + `st.toast` + highlighted row + **"New" tag** + first-seen time + metric delta, with **configurable persistence**); blocked-change detection (changed-blocked marker + last-changed time + **"what changed"** label: blocker / price / liquidity / stale / missing-leg / **`rule_flag_changed`** / market-status); **Recently Actionable** section windowed over the store (`BACKLOG_WINDOWS = 15m / 1h / 4h / 24h / Session`, default 1h) with became/left times and "why it left". |
| **Stage 4 — Opportunity-first dashboard restructure** | The fuller restructure on top of Stage 2's minimal layout — replacing the player-detail + full-diagnostics sprawl. | `app.py` (primarily), `glossary.py` | Section order Actionable Now → Blocked-but-Interesting → Recently Actionable → main opportunity table → **explanation panel/drawer** → entity drill-down (sport → player/event → contract codes) → **Advanced** (diagnostics + debug, default OFF). Explanation panel is a display surface over already-present explainability fields — no new compute. |
| **Stage 5 — Export overhaul (dedicated)** | Make exports useful for analysis, debugging, reproducibility across the full data model. | `app.py`, optional **`export.py`**, reads `store.py` + `scanner.py` | An Export panel with **8 datasets** (current opportunities, actionable-only, blocked-only, recently-actionable backlog, raw contracts, normalized contracts, **relationship table**, **diagnostics bundle**); CSV per table + one JSON/ZIP bundle; every export embeds the active filters + `fetched_at` (TZ-aware). XLSX/Parquet explicitly deferred. |

### Planned config additions

`TIMEZONE_DEFAULT="Europe/Lisbon"`, `TIMEZONE_OPTIONS`, `STALE_AFTER_SECONDS`, `SNAPSHOT_DB_PATH`,
`BACKLOG_WINDOWS`, `ALERT_PERSISTENCE_OPTIONS`, and a cross-sport-mode refresh-clamp constant. `sports.py`
gains an `ALL_SPORTS` registry helper for iteration.

### How this supersedes current-state descriptions

- **Stage 0 (SHIPPED):** The Altair opportunity-ranking chart has been removed; the freshness strip, timezone selector, "Show IDs & codes" toggle, and Advanced toggle are all live — §10 and §11 now describe the current state.
- **§2 "Out of Scope" / "Historical data storage"** — the planned SQLite snapshot store (Stage 1) is a deliberate reversal of this line; it stays accurate until Stage 1 ships, then both this doc and `CLAUDE.md`'s scope are to be updated.
- **§2 "Alerts or notifications"** — Stage 3 adds in-page banners/toasts (still no out-of-browser notifications); the scope line is updated only on landing.
- **§10 section order & player-detail / full-diagnostics** — planned to be further restructured (Stage 4) into an opportunity-first layout. The Advanced toggle is already live (Stage 0).

### Global non-goals (all planned stages)

No fees/net-edge/slippage modeling; no multi-user/server/auth or shared rate limiter; no React/FastAPI
migration within these stages (engine + store kept migration-ready); no new sports; no sound alerts; no
historical analytics beyond the snapshot store + backlog window; comparison/edge math stays
exact-integer-cents and TZ work never touches it.

### Planned verification

New test suites `test_store.py`, `test_lifecycle.py`, `test_scanner.py`, `test_export.py`, plus
extensions to `test_consistency` / `test_dutchbook` / `test_data` / `test_viz` / `test_filters` /
`test_app`. Guarded invariants: `opportunity_id` determinism, `blocked_reason` required-iff-blocked,
export schema stability, and no-silent-missing (failed/excluded series surfaced, not dropped).
