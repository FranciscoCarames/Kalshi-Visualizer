# Kalshi Structured Market Visualizer — Technical Documentation

**Audience:** Backend developer, technical collaborator, or future maintainer.
**Source of truth:** The live codebase as of 2026-06-02. Planned/unimplemented items are explicitly labelled.

---

## 1. Project Overview

The Kalshi Structured Market Visualizer is a read-only Streamlit web app that surfaces French Open tennis prediction-market data from the Kalshi exchange. It groups a player's contracts (match winner, stage advancement, tournament winner) into a logical progression ladder, detects when deeper outcomes are priced above broader prerequisites (a layer-consistency violation), and surfaces actionable entries as two-buy trade instructions.

**Current goal:** Give a trader a fast, accurate picture of which French Open contracts on Kalshi have price inconsistencies, whether those inconsistencies are executable, and exactly what to do (Buy YES on one leg, Buy NO on the other).

**Long-term goal:** Generalize beyond tennis and the French Open into a reusable structured prediction-market analysis tool applicable to any sport or event type with an ordered outcome hierarchy.

**Current supported market/event type:** French Open men's (ATP) and women's (WTA) tennis, 2026.

**Current development stage:** Feature-complete for the core French Open use-case. The tennis-specific logic is stable; generalization to other tournaments or sports is on the roadmap but not yet started.

**What the app is NOT trying to do yet:**
- Execute trades or place orders
- Model conditional probabilities or de-vig
- Provide portfolio management or position tracking
- Cover any sport other than tennis
- Cover any tournament other than the French Open (though the design allows expansion)

---

## 2. System Scope

### Current Scope

- Read-only market-data viewer; no authentication, no trading
- Loading and organizing Kalshi prediction-market contracts via public REST API
- Tennis-focused participant grouping keyed by stable competitor UUID
- Layer-consistency checking: containment violations + match-alignment equivalence checks
- Quote transparency: bid, ask, midpoint, last trade, spread quality
- Buy-only action instructions for executable inconsistencies
- Dashboard views: actionable now / blocked / near-edge watchlist / full diagnostics
- Raw and debug fields accessible via the Debug expander
- Per-player and full-dataset CSV/JSON export

### Out of Scope for Now

- Trade execution or order placement
- Automated trading or strategy execution
- Full arbitrage engine (settlement-rule compatibility is not auto-verified)
- Conditional-probability modeling or de-vig math
- Portfolio management
- Historical data storage or time-series analysis
- Alerts or notifications
- Full multi-sport generalization (structure exists for it; no concrete implementation)

---

## 3. Architecture Overview

```
Kalshi REST API (public, no auth)
  ↓
kalshi_client.py  — HTTP, pagination, throttle, retry, concurrency
  ↓
data.py           — Parse raw JSON → per-player contract rows (flat dicts)
  ↓
consistency.py    — Build per-player nodes → pairwise comparisons → edge classification
  ↓
filters.py        — Membership + threshold filtering on the comparison DataFrame
  ↓
app.py            — Streamlit UI: sidebar controls, summary cards, section tables, debug
  ↑
config.py         — All tunables (URLs, series lists, thresholds, rate limits, refresh cadence)
glossary.py       — All user-facing help text (tooltips, blocker reasons, watchlist notes)
```

### Per-layer details

| Layer | Responsibility | Input | Output | Files/Functions |
|---|---|---|---|---|
| **HTTP** | Rate-limited, paginated, retried GET requests to Kalshi | Series tickers | Raw event/market JSON | `kalshi_client._get`, `get_paginated`, `get_events`, `get_events_for_series` |
| **Parsing** | Flatten events → per-player contract rows; classify, price, link | Raw JSON dicts | List of contract dicts | `data.build_contracts` |
| **FO filtering** | Keep only French Open events | Event dict | bool | `data.is_french_open_event` |
| **Consistency** | Build player nodes, compare adjacent pairs, classify violations | Contract row list | Comparison DataFrame | `consistency.build_checks`, `_classify` |
| **Bucketing** | Route each comparison to a dashboard section | Single check row dict | Bucket name string | `consistency.bucket_of` |
| **Filtering** | Two-pass filter: membership (all sections) + thresholds (all except Actionable now) | Checks DataFrame | Filtered DataFrames | `filters.apply_membership`, `filters.apply_thresholds` |
| **UI** | Render tables, sidebar, summary cards, export buttons | Filtered DataFrames | Streamlit widgets | `app.py:render_dashboard` |

**Important assumptions:**
- `data.py` and `consistency.py` must never import Streamlit (independently testable).
- All comparison math uses exact integer cents (`to_cents` via `Decimal`); floats are display-only.
- An empty order book (`0.00/1.00`) is never treated as a real price.
- Pagination raises on truncation; partial data is never silently returned.

---

## 4. Data Model

### Core entities

**Series** — A Kalshi series groups semantically related events. Example: `KXWTAMATCH` (all WTA match-winner events). Identified by `series_ticker`.

**Event** — A single competition event, e.g. one match or one advancement milestone. Contains one or more markets. Identified by `event_ticker`.

**Market** — A single binary outcome. Identified by `market_ticker`. For match events there are two markets (one per player); for advancement/winner events there is one market per player.

**Participant (player)** — A competitor, identified by `player_key` (preferred: stable `tennis_competitor` UUID; fallback: normalized display name).

**Contract row** — The normalized per-player output of `data.build_contracts`. One row = one player's view of one market.

**Node** — A logical ladder position mapped from a contract: `Reach Semifinal`, `Reach Final`, or `Win Tournament`. Defined in `consistency.NODE_ORDER`.

**Comparison row** — Output of `consistency.build_checks`. One row = one pairwise comparison between a child (deeper) and a parent (broader) node, with a status, gap, and action plan.

### Contract row field dictionary

| Field | Source | Meaning | Used For | Notes |
|---|---|---|---|---|
| `player` | `data.display_player_name` | Clean, user-facing display name | Player selector, tables | Alias > source name > titleized fallback |
| `player_key` | `custom_strike.tennis_competitor` or `name.casefold()` | Stable grouping key | Grouping, dedup | UUID preferred; name-fallback may collide |
| `player_key_source` | derived | `"competitor_uuid"` or `"name_fallback"` | Debug, audit | |
| `player_name_raw` | `yes_sub_title` | Raw display name from Kalshi | Debug, display fallback | Preserved verbatim |
| `player_name_normalized` | `name.casefold()` | Lowercase normalized name | Debug | |
| `competitor_uuid` | `custom_strike.tennis_competitor` | Stable Kalshi competitor UUID | Primary grouping key | Empty string when absent |
| `mapping_confidence` | derived | `"high"`, `"low"`, or `"none"` | Audit, display | High = UUID present |
| `mapping_reason` | derived | Human-readable explanation of confidence level | Debug expander | |
| `tour` | `data.tour_of(series_ticker)` | `"ATP"` or `"WTA"` | Tour filter | |
| `kind` | `data.classify_kind(series_ticker)` | `"match"`, `"advance"`, `"winner"`, `"set_winner"`, `"exact_score"`, `"grand_slam"`, `"other"` | Contract type filter, node mapping | |
| `category` | `data.CATEGORY[kind]` | User-facing category label | Contract family filter | |
| `contract` | derived | Human-readable contract description | Tables | e.g. "Beat Andreeva — Quarterfinal" |
| `stage` | `data._extract_round(...)` | Ladder stage label | Node mapping, sort | e.g. "Semifinal", "Final", "Champion" |
| `stage_rank` | `data._STAGE_RANK[stage]` | Integer sort key (R128=1 … Champion=8) | Sort order | |
| `opponent` | sibling market `yes_sub_title` | Opponent name (match events only) | Display | Empty for non-match kinds |
| `competition` | `product_metadata.competition` | Tournament/competition label from Kalshi | FO filter, universe filter | e.g. "French Open Women Singles" |
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

- `/series` — list all series (used in full-scan mode to discover tennis series)
- `/events?series_ticker=X&with_nested_markets=true` — events with nested markets for a series
- `/series/<ticker>` — series metadata (title, used for URL slug generation)

### Discovery modes

**Default fast scan (`config.DEFAULT_SERIES`):** Fetches exactly 6 hardcoded series: `KXATPMATCH`, `KXWTAMATCH`, `KXATPADVANCE`, `KXWTAADVANCE`, `KXFOMEN`, `KXFOWOMEN`. This takes ~2 seconds and covers the core French Open contracts. (`kalshi_client.get_events_for_series`, `app.load_contracts`)

**Full dynamic scan (`kalshi_client.discover_tennis_series`):** Lists all Kalshi series, filters to those starting with `KXATP` or `KXWTA` (plus the explicitly listed `FO_WINNER_TICKERS`). Returns ~61 series. Triggered by the "Scan all tennis series" checkbox. Takes ~20 seconds.

### French Open filtering (`data.is_french_open_event`)

Each event is checked in priority order:

1. **Primary:** `product_metadata.competition` contains a French Open keyword (`"french open"`, `"roland garros"`, `"roland-garros"`, case-insensitive).
2. **Secondary:** FO keyword found in `event.title`, `event.sub_title`, or any market's `title` or `rules_primary`.
3. **Negative signal:** If a non-FO competition is named (e.g. `"Stuttgart Open"`), reject the event — do NOT fall back to dates.
4. **Last resort:** Only when no competition field is present at all, accept if any market's `occurrence_datetime` or `close_time` falls within the `config.FO_WINDOW` date range (currently `2026-05-18` to `2026-06-09`).

This order prevents concurrent non-French-Open tennis events from being mis-included.

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

### Preferred key: stable competitor UUID

`custom_strike.tennis_competitor` is a stable per-player UUID present on Kalshi tennis markets. When present, it is used directly as `player_key` (`player_key_source = "competitor_uuid"`, `mapping_confidence = "high"`). The same UUID links a player's contracts across all series and rounds.

### Name fallback

When the UUID is absent, `player_key = yes_sub_title.casefold()` (the normalized display name). This is `player_key_source = "name_fallback"`, `mapping_confidence = "low"`. Name-based keys can drift between markets or collide between same-named players.

### Display name resolution (`data.display_player_name`)

Priority order (implemented in `data.display_player_name`):

1. **Alias override:** `config.NAME_ALIASES.get(player_key)` — keyed by competitor UUID, currently empty but patchable for correcting drifted names.
2. **Clean source name:** `player_name_raw` (`yes_sub_title`) is shown verbatim if it contains any uppercase or a space — preserving accents, particles, and real casing (`"Stéphane de Robert"` stays `"Stéphane de Robert"`).
3. **Titleized fallback:** A bare lowercase token like `"aryna_sabalenka"` is title-cased to `"Aryna Sabalenka"` via `data._titleize_fallback`.

Internal identifiers (`player_key`, `player_name_raw`, `competitor_uuid`) are always preserved as separate fields for debug and export.

### Grouping in the consistency checker

`consistency.build_checks` groups by `player_key` (the stable UUID or name-fallback key), never by the display name. Two competitors with the same display name (e.g. `"Alex Smith"`) that have different keys are never merged. This is enforced by the test `test_build_checks_groups_by_player_key_not_display_name`.

### UI player selector disambiguation

When two players share the same display name but different keys, `app.py` appends a 6-character key suffix: `"Alex Smith [uuid-o]"` vs `"Alex Smith [uuid-t]"`.

### Known failure modes

- Name-fallback keys (`low` confidence) can collide across markets or drift if Kalshi changes name formatting.
- A player with only a name fallback key may appear as a duplicate if the same player's name is formatted differently in different series.
- `NAME_ALIASES` is currently empty (`config.py:65`). It exists as a patch point for correcting known drift without touching application code.

---

## 7. Contract Classification Logic

Classification assigns each contract a `kind` and `category`. Both are derived from the `series_ticker` string by `data.classify_kind`.

### Rules (evaluated in order — order matters)

```python
# data.py:293-312
if t in FO_WINNER_TICKERS:          -> "winner"    # explicit set check first
if "ADVANCE" in t:                   -> "advance"
if "EXACTMATCH" in t or "EXACTSCORE" in t: -> "exact_score"  # before "MATCH"
if "SETWINNER" in t:                 -> "set_winner"
if "GRANDSLAM" in t:                 -> "grand_slam"
if "MATCH" in t:                     -> "match"
else:                                -> "other"
```

Order matters: `KXATPEXACTMATCH` contains the substring `"MATCH"`, so `EXACTMATCH` must be checked first.

`FO_WINNER_TICKERS` is an explicit set in `config.py` covering all known tournament-winner series variants:
`KXFOMEN`, `KXFOWOMEN`, `KXFOMENSINGLES`, `KXFOWOMENSINGLES`, `KXFOPENMENSINGLE`, `KXFOPENWMENSINGLE`.

### Category labels (user-facing)

| kind | category | Notes |
|---|---|---|
| `match` | Match result | Head-to-head winner markets |
| `advance` | Stage advancement | Reach-a-round markets |
| `winner` | Tournament winner | Win-the-tournament markets |
| `set_winner` | Set winner | Per-set winner markets |
| `exact_score` | Exact score | Exact match score markets |
| `grand_slam` | Grand Slam (season) | Season-level Grand Slam markets |
| `other` | Other | Unrecognized series |

### Tour classification (`data.tour_of`)

Uses explicit sets for the winner-ticker variants where substring logic would misfire:
- `_WOMEN_WINNER_TICKERS = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}` → `"WTA"`
- `_MEN_WINNER_TICKERS = {"KXFOMEN", "KXFOMENSINGLES", "KXFOPENMENSINGLE"}` → `"ATP"`
- Then substring: `startswith("KXWTA")` or `"WOMEN" in t` → `"WTA"`; else `"ATP"`

The explicit set check catches `KXFOPENWMENSINGLE` which contains `"MEN"` as a substring of `"WOMEN"`.

### Stage extraction (`data._extract_round`)

Regex patterns applied most-specific first against the market `title` and `rules_primary` text:

```
Final, Semifinal, Quarterfinal, Round of 16, Round of 32, Round of 64, Round of 128
```

Word-boundary anchors (`\b`) prevent `"final"` matching inside `"quarterfinal"`. Returns `""` when no round is recognized.

Winner contracts are always stamped `stage = "Champion"`.

### Uncertain contracts

Contracts whose `kind == "other"` are included in the data but excluded from the consistency checker (no node mapping). Contracts whose round does not map to a tracked layer (`MATCH_STAGE_TO_NODE`) are emitted as `UNKNOWN_RELATIONSHIP` rows — never silently dropped, never treated as violations.

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

### Containment ladder

The consistency checker operates on the logical containment hierarchy:

```
Reach Semifinal ⊇ Reach Final ⊇ Win Tournament
```

A deeper outcome (e.g. Win Tournament) is contained in every broader prerequisite (e.g. Reach Semifinal). A deeper contract **must not** price higher than a broader one. Adjacent pairs checked: `(Win Tournament, Reach Final)` and `(Reach Final, Reach Semifinal)`.

### Match-alignment equivalence

When a player has both a market source (advance/winner) and a match source for the same node, the two are compared as equivalent. Example: "Quarterfinal win ≡ Reach Semifinal". This check runs in both directions (forward and reverse).

These comparisons always carry a `rule_flag` (`RULE_CHECK_REQUIRED` or `RULE_MISMATCH`) because settlement rules may differ between the two markets. The app never calls these "arbitrage" — they are "executable inconsistencies, rule-dependent."

### Classification logic (`consistency._classify`)

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

### Action plan (buy-only)

Every inconsistency of status `EXECUTABLE_VIOLATION`, `DISPLAY_VIOLATION`, or `QUOTE_SIZE_MISSING` is expressed as two BUYs:
- **Buy YES** on the broader (parent) leg at its YES ask price
- **Buy NO** on the deeper (child) leg at its NO ask price (`no_ask_c`, fallback `100 − yes_bid_c`)

The direction follows the winning firm cross for `EXECUTABLE_VIOLATION`; defaults to forward containment for display-only.

`WIDE_QUOTE` gets **no action** — it is watchlist-only.

### Tradability

`tradable_now` is set to `"Yes"` only when:
- Status is `EXECUTABLE_VIOLATION`
- Both legs have `status == "active"`
- No rule flag (or `"Yes — rule-dependent"` for equivalence pairs)

All other cases: `"No"`. Plain-English blockers from `glossary.BLOCKERS` explain why.

### Near-edge watchlist (`bucket_of`)

`CLEAN` rows whose firm executable gap (`child_bid_c − parent_ask_c`) is in `[NEAR_EDGE_MIN_C, 0]` (default `[-5, 0]`) cents, and whose worst quote quality is `"Tight"` or `"OK"`, appear in the near-edge watchlist. No buy instruction is shown.

### Profit calculation

For `EXECUTABLE_VIOLATION` only:
- `exec_gap_c` = gap in cents (child bid − parent ask for forward, or parent bid − child ask for reverse)
- `exec_min_size` = `min(long_leg_size, short_leg_size)`
- `exec_max_profit_dollars` = `exec_gap_c × exec_min_size / 100` (gross, before fees/slippage)

These fields are `None` for all other statuses.

---

## 10. Dashboard and UI Logic

### Main user workflow

1. Pick a tour (Women/Men/Both) and contract family in the sidebar.
2. The dashboard auto-refreshes on a timer (default 120s; `@st.fragment(run_every=...)`).
3. Six summary cards at the top: Actionable now, Gross quoted profit, Blocked, Near-edge, Data-quality issues, Last refreshed.
4. The first real table is **Actionable now** — always visible, not filtered by thresholds.
5. Below: Blocked / Near-edge watchlist (collapsed or toggleable).
6. Further below: Watchlist signals / Data-quality issues / Player detail / Full diagnostics / Debug — all collapsed.

### Section layout (top → bottom, `app.py`)

| Section | Description | Filtering applied |
|---|---|---|
| Header + metadata | Refresh time, contract count, comparison count | — |
| Summary cards | 6 `st.metric` widgets | Actionable = membership only |
| Export row | Dashboard/diagnostics/raw contract CSV downloads | — |
| ✅ Actionable now | Firm executable crosses that are tradable now | Membership only (thresholds do NOT apply) |
| ⛔ Blocked | Firm crosses blocked by no-size or inactive legs | Membership + thresholds |
| 📈 Near-edge watchlist | CLEAN rows within 5¢ of crossing on Tight/OK | Membership + thresholds |
| 👀 Watchlist signals | DISPLAY_VIOLATION + WIDE_QUOTE | Membership + thresholds |
| 🧹 Data-quality issues | MISSING_QUOTE/LAYER + UNKNOWN_RELATIONSHIP | Membership + thresholds |
| 🔍 Selected player detail | Chain + spreads + action cards + all contracts | Player-specific |
| 🧪 Full diagnostics | Complete comparison table | Membership + thresholds + outcome-status filter |
| 🔧 Debug | Failed series + per-player raw fields + link audit | Player-specific |

### Auto-refresh

`render_dashboard()` is decorated with `@st.fragment(run_every=run_every)`. Each tick calls `load_contracts` (TTL-cached at `REFRESH_TTL=30s`). Full-scan mode is clamped to a minimum of `FULL_SCAN_MIN_INTERVAL=120s`.

### Player detail section (`app.py:462–647`)

Contains: progression chain table, raw stage-ladder spreads table, per-player buy/no-buy action cards, mapping confidence, expected-vs-found layers, match contracts with confident stage mapping, all contracts with NO prices, JSON and CSV export buttons.

### Status display labels

Internal status strings map to user-facing labels in `app.py:STATUS_LABELS`. "Potential edge" is explicitly absent — "edge" is reserved for a positive executable gap.

---

## 11. Filters and Toggles

### Filter split (critical design invariant)

- **Membership filters** (`filters.apply_membership`): narrow all sections including Actionable now. These are "universe" filters — reducing which contracts are even considered.
- **Threshold filters** (`filters.apply_thresholds`): narrow everything *except* Actionable now. These are quality gates that should not hide real executable edges.

| Filter / Toggle | Purpose | Default | Notes |
|---|---|---|---|
| Tour (radio) | Women / Men / Both | Women | Filters `df` by `tour` before checks |
| Contract family (multiselect) | Tournament winner / Stage advancement / Match result | Winner + Advancement | Membership filter by `category`; "Match result" adds match-alignment rows |
| Auto-refresh (toggle) | Periodic re-fetch | On | Interval selectable: 60/120/300s |
| Refresh interval | Seconds between auto-refresh ticks | 120s | Clamped to 120s for full scan |
| Scan all tennis series | Fetch all ~61 tennis series | Off | Slows to ~20s+; adds set/score/grand-slam series |
| Show explanations | Show help captions in player detail | On | Informational only |
| Minimum volume (slider) | Drop contracts below traded volume | 0 | Membership filter |
| Competition (multiselect) | Filter by `product_metadata.competition` value | None | Membership; single-tournament in practice |
| Stage / layer (multiselect) | Filter by layer tokens (e.g. "Reach Final") | None | Membership; matches `layers` tuple field |
| Event / game search | Substring match on `child_event_ticker` or `parent_event_ticker` | "" | Membership |
| Player / participant search | Substring match on `player` display name | "" | Membership |
| Min gross edge (¢) | Threshold: drop comparisons below this executable gap | 0 | Threshold — does not affect Actionable now |
| Min tradable size | Threshold: drop comparisons with `exec_min_size < N` | 0 | Threshold |
| Quote quality (select) | All / Tight+OK only / Include wide | All | Threshold |
| Market status (select) | Any / Active only | Any | Threshold — checks both legs are active |
| Show blocked | Show/hide Blocked section | On | UI section toggle |
| Show near-edge | Show/hide Near-edge section | On | UI section toggle |
| Show watchlist signals | Show/hide Watchlist signals section | Off | UI section toggle |
| Show data-quality issues | Show/hide Data-quality issues section | Off | UI section toggle |
| Outcome status (select) | Filter Full diagnostics only by status group | All | Applies only to the Full diagnostics table |
| Player selector | Drive "Selected player detail" section | First alphabetically | Sidebar expander |

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
| Non-FO event in a tennis series | Filtered out by `is_french_open_event` | Not shown | Competition field takes precedence over date window |
| Series title missing (URL slug) | URL falls back to series page | Link still works; goes to series-level page | Non-fatal by design |
| NaN from pandas records path | `_isna` / `_num` normalize float NaN to None | Transparent to user | `None` becomes float NaN through `df.to_dict("records")` |
| Malformed market title | `_extract_round` returns `""`, stage stays empty | Contract label uses `_clean_title` fallback | |

---

## 13. Testing and Validation

Tests live in `tests/`. Run with `pytest -q`. No network access in tests (all HTTP is monkeypatched or synthetic).

Current test count: ~42 tests across 4 files (`test_data.py`, `test_consistency.py`, `test_glossary.py`, `test_client.py`).

### Contract Discovery Tests (`test_data.py`)

- `test_pagination_cap_raises_on_remaining_cursor` — paginator raises, never silently truncates
- `test_pagination_stops_cleanly_when_cursor_empties` — normal two-page case
- `test_non_fo_competition_in_window_is_rejected` — a named non-FO competition disqualifies even if in-window dates
- `test_fo_competition_is_accepted` — explicit FO competition accepted
- `test_date_window_fallback_only_when_no_competition` — fallback only when competition is absent
- `test_build_contracts_drops_non_french_open` — Wimbledon event with in-window dates is excluded

What to add: Tests for `discover_tennis_series` with a mocked `/series` response; tests for the series-title fetch degrading gracefully.

### Participant Grouping Tests (`test_data.py`)

- `test_build_contracts_typing_and_mapping` — UUID present → high confidence, correct opponent, tour, stage
- `test_display_name_prefers_source_verbatim` — accented names preserved
- `test_display_name_alias_overrides_source` — alias from `NAME_ALIASES` takes priority
- `test_display_name_titleizes_bare_key` — `"aryna_sabalenka"` → `"Aryna Sabalenka"`
- `test_build_contracts_exposes_internal_identifiers` — all key fields present and correct
- `test_build_checks_groups_by_player_key_not_display_name` — two same-named players not merged

What to add: Tests for the name-fallback collision case; tests for the `"name_fallback"` `player_key_source` path.

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

### UI / Filter Tests

No automated Streamlit UI tests currently exist. Manual validation steps:

1. Start the app (`streamlit run app.py`) and verify the six summary cards appear.
2. Confirm Actionable now is still populated when Threshold filters are tightened.
3. Confirm Tour filter correctly switches to WTA/ATP/both.
4. Confirm the player detail expander shows chain, spreads, and action cards.
5. Confirm the Debug expander shows failed series (test by temporarily breaking a series name).

### Regression Tests

Key invariants that must not regress:

- `EXECUTABLE_VIOLATION` is the **only** "Broken" status.
- `WIDE_QUOTE` rows get **no** action plan.
- Actionable now is **never** narrowed by threshold filters.
- `build_checks` groups by `player_key`, never display name.
- An empty `0.00/1.00` book is **never** treated as a price.
- Pagination truncation raises rather than silently returns partial data.

---

## 14. Extension Plan

### Staged expansion

1. **Improve tennis visualizer:** Extend `MATCH_STAGE_TO_NODE` to cover R16, R32, R64, R128 so early-round matches get consistency rows instead of `UNKNOWN_RELATIONSHIP`. Add more granular blocker reasons.

2. **Add simple spread/calendar-spread math:** The raw stage-ladder spreads (`consistency.layer_spreads`) are already implemented as percentage-point and cent differences. The next step is adding probability-adjusted calendar-spread views (today vs. final day of tournament).

3. **Clearer edge classification:** Add display labels for the "rule-dependent" vs "locked" spread certainty distinction already computed in `spread_certainty_label`. Surface it more prominently in the UI.

4. **Scenario and probability-chain modeling:** Model the probability of reaching each stage as a product of round-win probabilities. Display model-implied spreads vs. market spreads. This is the primary `"expand later"` item in the roadmap but is not committed scope.

5. **Generalize to other tennis tournaments:** Add `config.WO_WINDOW`, `config.USO_WINDOW`, etc. and make `is_french_open_event` accept a tournament parameter. The FO keyword list and date-window logic in `data.py` are already relatively generic.

6. **Generalize beyond tennis:** Introduce a `Sport` / `Tournament` abstraction layer above the tennis-specific series tickers and node names. The containment ladder concept (`NODE_ORDER`, `ADJACENT_PAIRS`) is already abstract enough to represent any sport with an ordered-outcome hierarchy.

### What abstractions should remain generic

These concepts are already expressed in a relatively abstract way and should not be made tennis-specific:

- **Participant identity:** `player_key` + `mapping_confidence` design is sport-agnostic.
- **Event structure:** Series → Event → Market hierarchy mirrors any prediction market.
- **Contract type classification:** `classify_kind` is a simple string-matching dispatcher — easy to extend.
- **Quote handling:** `to_cents`, `quote_quality`, `display_prob` are fully generic.
- **Outcome relationship logic:** `_classify`, `build_checks`, `ADJACENT_PAIRS` are abstract; the ladder labels are configuration.
- **Edge / spread calculation:** `exec_gap_c`, `exec_min_size`, `layer_spreads` are generic.
- **Display priorities:** `display_prob` waterfall and the `bucket_of` routing logic are generic.

What is tennis-specific and would need parameterization:

- `TENNIS_SERIES_PREFIXES`, `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW` in `config.py`
- `MATCH_STAGE_TO_NODE`, `ADVANCE_STAGE_TO_NODE`, `NODE_ORDER` in `consistency.py`
- `_ROUND_PATTERNS`, `_STAGE_RANK`, `tour_of` in `data.py`

---

## 15. Code / File Map

| File | Responsibility | Important Functions / Classes | Notes |
|---|---|---|---|
| `config.py` | All tunables and constants | `BASE_URL`, `DEFAULT_SERIES`, `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW`, `SPREAD_REASONABLE`, `DISPLAY_TOL_C`, `NEAR_EDGE_MIN_C`, `MAX_RPS`, `REFRESH_TTL` | Pure constants; no logic; no imports |
| `kalshi_client.py` | HTTP, pagination, throttle, retry, concurrency | `_get`, `get_paginated`, `get_events`, `discover_tennis_series`, `get_events_for_series`, `get_series_titles`, `_throttle`, `KalshiError` | No Streamlit; no data parsing; process-wide rate limiter |
| `data.py` | Parse raw JSON → contract rows; pricing; FO filter; identity | `build_contracts`, `is_french_open_event`, `to_cents`, `to_float`, `quote_quality`, `display_prob`, `yes_mid`, `classify_kind`, `tour_of`, `display_player_name`, `kalshi_market_url`, `link_audit`, `tournament_of`, `CATEGORY` | No Streamlit; no pandas; independently testable |
| `consistency.py` | Containment checking; action plan; dashboard bucketing | `build_checks`, `build_player_nodes`, `_classify`, `layer_spreads`, `expected_nodes`, `bucket_of`, `representative`, `duplicate_node_sources`, `spread_certainty_label`, `NODE_ORDER`, `ADJACENT_PAIRS` | No Streamlit; depends on pandas; depends on data, glossary |
| `filters.py` | Two-pass membership + threshold filtering | `apply_membership`, `apply_thresholds`, `QUOTE_MODES`, `STATUS_MODES` | No Streamlit; pure pandas; independently testable |
| `glossary.py` | All user-facing help text | `GLOSSARY`, `BLOCKERS`, `WATCHLIST_NOTE`, `COLUMN_HELP`, `help_for` | No imports; single source of truth for tooltips and blocker reasons |
| `app.py` | Streamlit UI; data load; cache; rendering | `load_contracts`, `discover`, `render_dashboard`, `_buy_disp` | Only file with Streamlit imports; delegates all math to other modules |
| `tests/test_data.py` | Unit tests for data layer | All `test_*` functions | No network; covers parsing, pricing, FO filter, build_contracts |
| `tests/test_consistency.py` | Unit tests for consistency layer | All `test_*` functions | No network; covers `_classify`, `build_checks`, `layer_spreads`, `bucket_of` |
| `tests/test_glossary.py` | Glossary integrity tests | `test_every_term_has_short_and_long`, `test_consistency_only_emits_known_blocker_text` | Guards against orphan jargon |
| `tests/test_client.py` | Unit tests for HTTP client | Rate-limiter, pagination, backoff | No real network; uses monkeypatching |
| `scripts/check_links.py` | Live link-reachability check | — | Runs from an unthrottled network; Kalshi throttles bots |
| `scripts/export_glossary.py` | Generate `docs/GLOSSARY.md` | — | Run locally; output committed to docs/ |
| `docs/GLOSSARY.md` | Generated glossary reference | — | Do not edit manually; regenerate from `glossary.py` |

### What each file should NOT own

- `data.py` and `consistency.py` must never import Streamlit.
- `data.py` must not import pandas (it uses plain dicts and lists).
- `kalshi_client.py` must not contain any parsing or business logic.
- `app.py` must not contain any math; delegate to `consistency.py` and `filters.py`.
- `config.py` must not contain any functions or imports.
- `glossary.py` must not contain any imports.

### Technical debt / refactoring notes

- `filters.py` is not yet referenced in `CLAUDE.md`'s architecture diagram (minor doc gap).
- `consistency.py` imports pandas while `data.py` does not; this asymmetry means `consistency.py` cannot be tested without pandas installed.
- `tournament_of` in `data.py` is defined but currently unused in `build_contracts` output; it exists as infrastructure for multi-tournament generalization.
- The `FULL_SCAN_MIN_INTERVAL` clamping warns the user but does not prevent them from setting a short interval on the first load before the warning appears.

---

## 16. Known Limitations

- **Tennis-first design:** All series tickers, stage labels, tour logic, and node names are tennis-specific. Generalizing to other sports requires parameterizing `classify_kind`, `tour_of`, `_extract_round`, `NODE_ORDER`, and `ADJACENT_PAIRS`.

- **French Open only:** The FO filter keywords and date window are hardcoded for French Open 2026. Each new tournament requires updating `config.FO_WINDOW` and potentially `config.FO_KEYWORDS`.

- **Metadata quality dependency:** The consistency checker relies on Kalshi's `product_metadata.competition`, `custom_strike.tennis_competitor`, and stage-keyword text in market titles. If Kalshi changes these fields or their format, filtering and grouping will degrade silently.

- **Missing quotes are common:** Between rounds or for illiquid players, most markets have empty or one-sided books. The app handles this gracefully but cannot compute edges where quotes are absent.

- **Imperfect classification:** Contracts whose series ticker has no recognized pattern become `kind = "other"` and are excluded from the consistency checker. New series types require updating `classify_kind`.

- **No trade execution:** The app is read-only. All "Buy YES / Buy NO" instructions are informational only.

- **No true arbitrage guarantee:** The app finds executable inconsistencies, not guaranteed arbitrage. Settlement-rule compatibility between match-alignment pairs is not auto-verified.

- **No probability modeling:** Display prices are market prices, not de-vigged probabilities. No implied probability calculations or Kelly sizing are implemented.

- **Process-wide rate limiter only:** Multiple processes or containers each have their own limiter. Aggregate rate is `MAX_RPS × process_count`. A large horizontal scale-out would need a shared/distributed limiter.

- **UI under active refinement:** Section visibility toggles, threshold filter defaults, and the near-edge window are tunable constants that may need adjustment as real data arrives.

- **Link audit is deterministic, not live:** `data.link_audit` verifies that each URL encodes the correct identifiers (series, event) but does not check live reachability (Kalshi throttles automated HTTP from this environment at 429).

---

## 17. Open Design Questions

- Should `NAME_ALIASES` be editable from the UI sidebar, or only from `config.py`? The current approach (config only) is safe but inflexible.

- What is the exact threshold defining a "near-edge" row? The current `NEAR_EDGE_MIN_C = -5` is a guess. A real threshold should be informed by typical bid/ask movement speed.

- Should `UNKNOWN_RELATIONSHIP` rows (early-round matches, R16 etc.) appear in the default view or only in Full diagnostics? Currently they appear only if "Show data-quality issues" is toggled on.

- Should the Outcome status filter (currently Full diagnostics only) also optionally narrow the Blocked and Watchlist sections? Or should those sections always show all statuses?

- How should the app handle a player who appears in both the ATP and WTA draws (e.g. a scheduling anomaly)? Currently `tour_of` is derived from the series ticker, so they would appear under the correct tour, but the player detail would merge them.

- How much raw debug data should be visible in the default player detail section vs. behind the Debug expander? The current design keeps raw price strings and internal identifiers in Debug only.

- What is the correct abstraction boundary for multi-tournament support? Should `config.py` hold a list of `Tournament` objects with their own keywords and date windows, or should tournament selection drive a separate config import?

- Should `RULE_MISMATCH` rows ever be shown in Actionable now with a stronger caveat, or always remain in Blocked? The current design puts all rule-flagged rows in "rule-dependent" which is shown in Actionable now — this is a deliberate but potentially confusing choice.

- At what scale of horizontal deployment should the rate limiter be redesigned? The current process-wide limiter is safe for a single-instance deployment but unsound for multiple replicas.

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
| Settlement rules / rule caveat | Match-alignment pairs may have different payout rules not auto-verified. |
| Executable inconsistency vs arbitrage | We say "executable inconsistency" — true arbitrage also requires settlement rules to match. |
| Containment ladder | Reach Semifinal ⊇ Reach Final ⊇ Win Tournament. A deeper outcome can't price higher than the broader one containing it. |
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

2. **Unexpected `UNKNOWN_RELATIONSHIP` rows:** The match's stage is not in `MATCH_STAGE_TO_NODE` (e.g. R16). Check `consistency.py:35`.

3. **Player appears under wrong tour:** `tour_of` may be using substring logic that misfires on a new ticker. Check `data.py:317-330` and update the explicit sets if needed.

4. **Duplicate player in the selector:** Two contracts with different `player_key`s but the same display name. The selector appends a 6-char key suffix. Check `mapping_confidence` in the Debug expander.

5. **All links going to series page instead of event page:** `series_title` was not fetched. Check the `get_series_titles` call in `app.load_contracts` and the `titles.get(ticker, "")` fallback.

6. **All contracts excluded as non-FO:** The `competition` field is present but named differently than expected. Check `data.FO_KEYWORDS` and `config.FO_KEYWORDS`. Add to `FO_KEYWORDS` if a new naming variant appears.

7. **Rate limit errors in production:** `MAX_RPS` is set to 5 (25% of the 20/s ceiling). If errors persist, lower `CONCURRENCY` or `MAX_RPS`. Note the limiter is process-wide only.

### F. Configuration knobs quick reference

| Constant | Location | Default | What changing it does |
|---|---|---|---|
| `DEFAULT_SERIES` | `config.py:20` | 6 series | The fast-scan series list |
| `SPREAD_REASONABLE` | `config.py:31` | 0.20 ($0.20) | Threshold for trusting midpoint as display price |
| `DISPLAY_TOL_C` | `config.py:34` | 1¢ | Ignore display gaps below this (noise filter) |
| `NEAR_EDGE_MIN_C` | `config.py:39` | -5¢ | Near-edge watchlist window lower bound |
| `FO_WINDOW` | `config.py:61` | 2026-05-18 to 2026-06-09 | Update per year |
| `MAX_RPS` | `config.py:80` | 5 req/s | Rate limiter ceiling |
| `REFRESH_TTL` | `config.py:90` | 30s | `load_contracts` cache TTL |
| `REFRESH_DEFAULT_SECONDS` | `config.py:88` | 120s | Default auto-refresh interval |

---

## 19. Planned evolution (roadmap)

> **STATUS: PLANNED — NOT YET IMPLEMENTED.** Everything in this section describes a finalized but
> unbuilt multi-stage roadmap. None of the modules, fields, or UI surfaces below exist in the codebase
> today; sections 1–18 above continue to describe the *current* (built) state and are unchanged.
> Where a current-state sentence elsewhere in this doc is about to be superseded, the change is noted
> here as planned rather than by rewriting the earlier text. The roadmap also introduces a deliberate
> **scope change** — a persisted on-disk store — which today's "Out of scope" list (§2) and `CLAUDE.md`
> still mark as a "don't add"; that scope line will be updated **only when Stage 1 actually lands**.

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
| **Stage 0 — Clarity quick wins (no new infra)** | Stop the dashboard misleading or burying info; immediate value with zero new infrastructure. | `app.py`, `config.py` (`STALE_AFTER_SECONDS`, TZ options), `data.py` (`fmt_time`, age/stale helpers), `viz.py` (delete `opportunity_ranking`) | TZ selectbox (**Lisbon default**) + `fmt_time()` on every timestamp; **remove the Altair ranking chart**; **"Show IDs & codes"** toggle (default OFF); always-visible **data-freshness & coverage strip** (exchange + local time, data age, refresh status, stale-data warning, coverage / fetch-failure counts); **Debug + Full-diagnostics moved behind a single Advanced toggle, default OFF** (the freshness strip stays out of Advanced). |
| **Stage 1 — Opportunity schema + SQLite snapshot store** | A stable identity + persisted history substrate that survives the React migration. | `consistency.py`, `dutchbook.py`, **new `store.py`**, `config.py` (`SNAPSHOT_DB_PATH`), `glossary.py` | `opportunity_id`; **`blocked_reason` as a required field**; `relationship_type`; **SQLite snapshot store** written once per refresh with the fields the change-classifier needs; `latest_two()` / `snapshots_since()`; retention cap + schema migration. **No multi-user/server.** |
| **Stage 2 — Cross-sport global scanner (always-on unified table)** | One always-visible table of actionable opps across **all wired sports simultaneously**, ranked best→worst, computed over the full loaded universe **independently of any selection**. | **new `scanner.py`**, `app.py`, `sports.py` (`ALL_SPORTS`), `filters.py` (sport filter), `config.py` (refresh clamp) | `scanner.unified_opportunities`; default **"All sports"** sortable `st.dataframe` (replaces the ranking graph) sortable by gross edge / size / age / status; header reads **"All loaded markets (<fetch mode>)"** — core-series vs full-scan labelled honestly, never "all Kalshi"; a simple unified-table CSV download; per-sport drill-down preserved; partial per-sport failure must not blank the table. |
| **Stage 3 — Lifecycle: alerts + recently-actionable backlog** | Make opportunity appearance/disappearance impossible to miss; keep a windowed record — all from pure diffs over the store. | **new `lifecycle.py`**, `app.py`, `config.py` (`BACKLOG_WINDOWS`, `ALERT_PERSISTENCE_OPTIONS`), `glossary.py`, reads/writes `store.py` | New-actionable alert (banner + `st.toast` + highlighted row + **"New" tag** + first-seen time + metric delta, with **configurable persistence**); blocked-change detection (changed-blocked marker + last-changed time + **"what changed"** label: blocker / price / liquidity / stale / missing-leg / **`rule_flag_changed`** / market-status); **Recently Actionable** section windowed over the store (`BACKLOG_WINDOWS = 15m / 1h / 4h / 24h / Session`, default 1h) with became/left times and "why it left". |
| **Stage 4 — Opportunity-first dashboard restructure** | The fuller restructure on top of Stage 2's minimal layout — replacing the player-detail + full-diagnostics sprawl. | `app.py` (primarily), `glossary.py` | Section order Actionable Now → Blocked-but-Interesting → Recently Actionable → main opportunity table → **explanation panel/drawer** → entity drill-down (sport → player/event → contract codes) → **Advanced** (diagnostics + debug, default OFF). Explanation panel is a display surface over already-present explainability fields — no new compute. |
| **Stage 5 — Export overhaul (dedicated)** | Make exports useful for analysis, debugging, reproducibility across the full data model. | `app.py`, optional **`export.py`**, reads `store.py` + `scanner.py` | An Export panel with **8 datasets** (current opportunities, actionable-only, blocked-only, recently-actionable backlog, raw contracts, normalized contracts, **relationship table**, **diagnostics bundle**); CSV per table + one JSON/ZIP bundle; every export embeds the active filters + `fetched_at` (TZ-aware). XLSX/Parquet explicitly deferred. |

### Planned config additions

`TIMEZONE_DEFAULT="Europe/Lisbon"`, `TIMEZONE_OPTIONS`, `STALE_AFTER_SECONDS`, `SNAPSHOT_DB_PATH`,
`BACKLOG_WINDOWS`, `ALERT_PERSISTENCE_OPTIONS`, and a cross-sport-mode refresh-clamp constant. `sports.py`
gains an `ALL_SPORTS` registry helper for iteration.

### How this supersedes current-state descriptions (planned, not yet done)

- **§2 "Out of Scope" / "Historical data storage"** — the planned SQLite snapshot store is a deliberate
  reversal of this line; it stays accurate until Stage 1 ships, then both this doc and `CLAUDE.md`'s
  scope are to be updated.
- **§2 "Alerts or notifications"** — Stage 3 adds in-page banners/toasts (still no out-of-browser
  notifications); the scope line is updated only on landing.
- **§10 / §11 ranking chart** — `viz.opportunity_ranking` and its Altair chart are planned for
  **deletion** (Stage 0) and replacement by the sortable unified table (Stage 2).
- **§10 section order & player-detail / full-diagnostics** — planned to be restructured (Stage 4) into
  an opportunity-first layout with diagnostics behind an Advanced toggle.

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
