# Kalshi Visualizer — Multi-Sport Executable-Inconsistency Dashboard

A read-only tool that pulls live [Kalshi](https://kalshi.com/) prediction-market data for
**tennis (ATP/WTA), NBA, and WNBA** and surfaces two classes of opportunity:

1. **Layer-consistency violations** — a deeper outcome must not price above a prerequisite that
   contains it (e.g. *Win Tournament ≤ Reach Final ≤ Reach Semifinal*). Framed as buy-only
   opportunities: **Buy YES** on the broader leg, **Buy NO** on the deeper leg.
2. **Dutch-book arbitrage** — a mutually-exclusive-and-exhaustive pair of 2-outcome markets where
   covering both outcomes costs under 100¢. True arbitrage: both legs are outcomes of the *same*
   event and settle together, so no settlement-rule caveat applies.

---

## Two ways to run

| Mode | Command | What you get |
|---|---|---|
| Per-sport Streamlit dashboard | `streamlit run app.py` | Single-sport view: per-player detail, progression ladder, raw spreads, diagnostics, auto-refresh |
| Cross-sport engine + NiceGUI + REST API | `python serve.py` | Opportunity-first unified view across all sports; NiceGUI dashboard at `/`; REST API at `/opportunities` etc.; OpenAPI at `/docs` |

Both modes read the same engine layers (`consistency.py`, `dutchbook.py`, `fetch.py`, `scanner.py`)
and the same live Kalshi data. No API key is required for either.

---

## Opportunity Engine & API

### Overview

`python serve.py` launches a single [uvicorn](https://www.uvicorn.org/) server that mounts both the
[NiceGUI](https://nicegui.io/) dashboard and the [FastAPI](https://fastapi.tiangolo.com/) REST API
on one process. The engine pipeline is:

```
fetch.py          →  scanner.py         →  store.py         →  api.py / webui/
(per-sport fetch)    (cross-sport scan)    (SQLite snapshot)    (REST + NiceGUI)
```

### SQLite snapshot store (`store.py`)

A standalone SQLite store, pure stdlib (no Streamlit, no pandas). On every scan it persists:

- The full unified opportunity frame (all sports, all findings), keyed by a stable `opportunity_id`
  (deterministic sha1 via `data.opportunity_id`).
- Per-scan coverage metadata (series scanned/loaded/failed, per-sport errors).
- Versioned schema (`PRAGMA user_version`, currently v2). Staged migrations bring older files forward.
- Retention cap (`config.SNAPSHOT_RETENTION_SECONDS`): old snapshots are pruned relative to the
  newest stored snapshot, so retention is reproducible in tests.

Key accessors: `write_snapshot`, `latest`, `latest_two`, `snapshots_since`.

### Cross-sport scanner (`scanner.py`)

`unified_opportunities(fetch_fn, ...)` aggregates `build_checks` (containment ladder) and
`find_dutch_books` (MECE detector) across **all registered sports** into one ranked frame
(`UNIFIED_COLUMNS`). Each row carries `sport`, `opportunity_id`, `relationship_type`, `bucket`,
and `blocked_reason`. A single sport's fetch or processing failure is recorded and skipped — it
never blanks the whole frame.

`run_scan(fetch_fn, ...)` adds coverage aggregation on top and is the entry point for `POST /scan`.
Fetch is dependency-injected so unit tests pass a stub; the scanner never imports `streamlit` or
`kalshi_client` directly.

Ranking: actionable first → largest gross edge (¢) → stable id tiebreak.

### Opportunity lifecycle (`lifecycle.py`)

Pure snapshot-diff functions — no extra persisted state, no network:

- **§8 New-actionable** (`new_actionable`, `persisting_new_actionable`): rows actionable in the
  current snapshot but not in the previous one. No-prev on first load suppresses false alerts.
  Persistence window configurable (`config.ALERT_PERSISTENCE_OPTIONS`).
- **§9 Blocked-change** (`blocked_change`): rows that enter/leave `blocked` or change while blocked
  between two snapshots. Reports what changed (blocker, price, liquidity, status, rule flag).
- **§10 Recently-actionable backlog** (`recently_actionable`): rows actionable in some snapshot
  within a history window but not in the latest; includes why they left (`disappeared` / `leg
  inactive` / `went blocked` / `went clean`) and how long they were actionable.

### REST API (`api.py`)

FastAPI app; thin handlers that only call engine functions. All read endpoints serve the **latest
persisted snapshot** (fast, deterministic). `POST /scan` runs a live scan behind a store-backed
TTL guard. DB path and scan fetch are FastAPI dependencies, overridable in tests.

| Endpoint | Description |
|---|---|
| `GET /opportunities` | All opportunities in the latest snapshot; filterable by `?sport=`, `?bucket=`, `?status=` |
| `GET /opportunities/{id}` | Single opportunity by `opportunity_id`; 404 if not in the latest snapshot |
| `GET /backlog` | Recently-actionable backlog; `?window_s=` configures history window |
| `GET /coverage` | Scan coverage metadata (series scanned/loaded/failed, data age, stale flag) |
| `GET /alerts` | New-actionable + blocked-change diff; `?persistence_s=` for banner window |
| `GET /healthz` | Service health check |
| `POST /scan` | Run a fresh cross-sport scan (core series); `?force=true` bypasses TTL guard |

OpenAPI (Swagger) docs at `/docs`.

### NiceGUI dashboard (`webui/`)

`webui/dashboard.py` registers a `@ui.page('/')` that reads the engine **in-process** via
`webui/engine.py` (no self-HTTP):

- **Per-second freshness strip** — data age, stale warning, coverage counts (series/failed).
- **Sortable Actionable / Blocked tables** — all sports, ranked by gross edge; clicking a row opens
  an explanation panel with action texts, leg prices, links, and IDs.
- **New-actionable alert banner + toast** — configurable persistence window; suppressed on first
  load to avoid false alerts.
- **Blocked-change indicator** — shows how many opportunities changed while blocked.
- **Recently-actionable backlog** — collapsible; configurable history window; shows when each
  opportunity became/left actionable, why it left, and last edge.
- **"Scan now (core series)"** button — honest label (scan scope is core series only; full-scan
  toggle is deferred). Runs network I/O off the NiceGUI event loop.
- **Timezone selector** and **"Show IDs & codes"** toggle.

Scan scope is **core series only** (full-scan toggle deferred). The `webui/engine.py` wrappers
are independently unit-testable without NiceGUI.

---

## Layer Consistency Checker

The main table compares contracts that have a provable logical **containment** relationship and flags
**executable inconsistencies** (a firm bid/ask cross with order size behind it). It is deliberately
conservative:

- **Executable test** uses firm YES bid/ask **and positive order sizes**, compared in exact integer
  cents. A child YES bid above the parent YES ask is `EXECUTABLE_VIOLATION` (the only *Broken*
  status).
- **Display test** compares the display %; a breach is `DISPLAY_VIOLATION` (a *Warning*, since it
  may not be tradable).
- Wide/empty books, missing sizes, missing layers, and unprovable relationships are surfaced as
  `WIDE_QUOTE` / `MISSING_QUOTE` / `QUOTE_SIZE_MISSING` / `MISSING_LAYER` / `UNKNOWN_RELATIONSHIP`
  — **never** mislabelled as violations.
- **Match-alignment** rows (winning your current match ⇔ reaching the next stage) are included only
  when the round maps confidently, and always carry a `RULE_CHECK_REQUIRED` / `RULE_MISMATCH` flag:
  findings are called *executable inconsistencies*, **not arbitrage**, because the two markets'
  settlement rules are not auto-verified.

### Containment ladders by sport

| Sport | Ladder (broad → deep) |
|---|---|
| Tennis | Reach Semifinal ⊇ Reach Final ⊇ Win Tournament |
| NBA | Reach Playoffs ⊇ Win Conference ⊇ Win Championship |
| WNBA | Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship |

---

## Dutch-Book Detector (`dutchbook.py`)

A **separate check family** from the containment ladder, in its own Streamlit-free module. Handles the
**2-outcome case**: any event with exactly two distinct-participant binary markets (a head-to-head
match/series, or a single game). Those two markets are mutually exclusive and, for the draw-free sports
supported, exhaustive — MECE by construction.

Two directions, both expressed as pairs of BUYS (never "sell"):

- **Underround → Buy YES on both.** `yes_ask_A + yes_ask_B < 100¢` — one side wins and pays 100¢,
  so the locked profit per unit is `100 − cost`.
- **Overround → Buy NO on both.** `no_ask_A + no_ask_B < 100¢` — the loser's NO pays 100¢, same
  locked profit math.

The two directions are mutually exclusive (`bid ≤ ask` always), so at most one fires per event. All
comparisons are exact integer cents. Status `EXECUTABLE_DUTCH_BOOK`; its own dashboard section.

**Sport coverage:** tennis matches + NBA/WNBA playoff series + NBA/WNBA per-game (`KX*GAME`) books.
Props, winner fields, and advancement markets are not 2-outcome MECE → excluded. Unknown series are
always excluded.

---

## Multi-Sport Engine (`sports.py`)

One detection engine, swappable data per sport. Each sport is a `SportConfig` holding the series
prefixes, a structured identity resolver (stable competitor UUID → normalized name fallback), market
classification (family + ladder node + eligibility), the containment ladder, and labels. Adding a
sport is a matter of dropping in a new `SportConfig` and calling `register()`. Unknown series resolve
to the explicit `UNKNOWN` sport — never silently to tennis.

Registered sports:

| Sport | Series prefixes | Identity key | Match family |
|---|---|---|---|
| Tennis | `KXATP*`, `KXWTA*` | `custom_strike.tennis_competitor` UUID | `match` |
| NBA | `KXNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |
| WNBA | `KXWNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |

---

## How it works

Kalshi organizes contracts as **Series → Event → Market (outcome)**. The engine:

1. **Fetches** the selected sport's series via `fetch.py`. An optional **"Scan all"** mode
   dynamically discovers every series matching the sport's prefixes for extra contract types. Series
   list is cached 3600 s; contracts are cached for `REFRESH_TTL` (30 s) in the Streamlit app.
2. **Classifies** each market by type (family + stage + ladder node) using the sport's `SportConfig`.
3. **Indexes** contracts by the participant's stable identity key (competitor/team UUID, or name
   fallback) so the same participant merges across all series.
4. **Stamps** each contract with a never-empty `tournament` grouping key (`data.tournament_of`).
   Containment ladders group by `(participant_key, tournament)` — ladders never mix across
   tournaments, and a fallback key never collapses to an empty string.
5. **Tournament is a client-side filter**, not a fetch gate — all events for a sport are included,
   and the user narrows by tournament in the Streamlit sidebar. The French Open is one of several
   tennis tournaments, not a special case.

### Discovery modes

- **Default (fast):** fetch only the sport's `default_series` — typically 6 well-known series.
- **Scan all (default ON in Streamlit):** dynamically discover every series matching the sport's
  prefixes; widens coverage to set-winner, exact-score, per-game, and other contract types. The
  engine API's `POST /scan` uses core series only (full-scan toggle deferred).

### Pricing columns

Rather than a single implied probability, each row exposes:

- **Display %** — YES midpoint when the bid/ask spread is reasonable (≤ 20¢), otherwise last trade,
  otherwise blank. An empty `0.00/1.00` order book is never disguised as a fake 50%.
- **YES mid % / Last % / YES bid % / YES ask % / Spread ¢** — the raw components.
- **Quote** — quality flag (Tight / OK / Wide / Very wide / One-sided / No quote) so an unreliable
  price is immediately visible.

---

## Project layout

| File / directory | Responsibility |
|---|---|
| `config.py` | Base URL, series tickers, thresholds, rate-limit + refresh knobs, timezone options, engine config (`SNAPSHOT_DB_PATH`, `SCAN_MIN_INTERVAL_SECONDS`, `BACKLOG_WINDOWS`, etc.) |
| `kalshi_client.py` | Read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide throttle |
| `sports.py` | Sport abstraction — `SportConfig`, registry, `sport_for_series`; imports only `config` + stdlib |
| `data.py` | Parsing, `tournament_of`, `build_contracts` (all events, all sports), cent-exact pricing helpers, `opportunity_id` (deterministic sha1) (no Streamlit) |
| `fetch.py` | Streamlit-free contract fetch — `fetch_contracts(families, scan_all, sport_id)`. `app.load_contracts` is a thin `@st.cache_data` wrapper over this |
| `consistency.py` | Containment ladder + match-alignment classifier, `build_checks`, `bucket_of`, buy-only action plans; every row carries `opportunity_id`, `relationship_type`, `bucket`, `blocked_reason` (no Streamlit) |
| `dutchbook.py` | Dutch-book / MECE arbitrage detector — 2-outcome events (no Streamlit) |
| `scanner.py` | `unified_opportunities` — cross-sport aggregator (containment + dutch-book) into one ranked frame; `run_scan` adds coverage; fetch injected (no network, no Streamlit) |
| `store.py` | SQLite snapshot store — `write_snapshot` / `latest` / `latest_two` / `snapshots_since`; versioned schema (v2); retention cap; pure stdlib, NaN-safe (no Streamlit, no pandas) |
| `lifecycle.py` | Snapshot-diff: new-actionable (§8), blocked-change (§9), recently-actionable backlog (§10); pure functions, no store import (no Streamlit, no network) |
| `api.py` | FastAPI app — thin REST handlers over the engine; Pydantic models; endpoints: `/opportunities`, `/backlog`, `/coverage`, `/alerts`, `/healthz`, `/scan` |
| `serve.py` | Uvicorn entrypoint — mounts NiceGUI dashboard onto `api.app` via `ui.run_with` |
| `webui/dashboard.py` | NiceGUI `@ui.page('/')` — opportunity-first cross-sport dashboard (freshness strip, sortable tables, backlog, alerts, explanation panel, scan button) |
| `webui/engine.py` | In-process accessors for the NiceGUI dashboard (thin wrappers over `store` / `lifecycle` / `scanner`; no self-HTTP) |
| `glossary.py` | `GLOSSARY`, `BLOCKERS`, `WATCHLIST_NOTE`, `help_for` — single-sourced terminology (no Streamlit) |
| `filters.py` | `apply_membership` (tournament/family/layer/event/participant/volume) + `apply_thresholds` (size/quote/status) — Streamlit app filters (no Streamlit) |
| `viz.py` | `payoff_chart_data` + `ladder_prices` — tidy chart frames (no Streamlit) |
| `app.py` | Streamlit UI: sidebar controls, auto-refresh fragment, dashboard sections, charts |
| `tests/` | ~235 pytest unit tests covering all pure-logic layers (no network required) |

`data.py`, `fetch.py`, `consistency.py`, `dutchbook.py`, `sports.py`, `glossary.py`, `filters.py`,
`viz.py`, `scanner.py`, `store.py`, `lifecycle.py`, and `webui/engine.py` are **Streamlit-free** and
independently testable.

---

## Setup & run

```bash
pip install -r requirements.txt          # streamlit, requests, pandas, altair, fastapi, uvicorn, pydantic, nicegui
```

### Streamlit per-sport dashboard

```bash
streamlit run app.py
```

Opens in your browser. Auto-refresh is on by default (120 s interval; configurable in the sidebar).

### Cross-sport engine API + NiceGUI dashboard

```bash
python serve.py
```

- NiceGUI dashboard: `http://localhost:8000/`
- REST API: `http://localhost:8000/opportunities` (and other endpoints listed above)
- OpenAPI docs: `http://localhost:8000/docs`

The first view is empty until you press **"Scan now (core series)"** or `POST /scan` — the store
starts empty and scans are on-demand (no background scheduler).

Data is public — no API key required for either mode.

## Tests

Pure logic is covered by unit tests (no network):

```bash
pip install -r requirements-dev.txt      # adds pytest, ruff, httpx (FastAPI test client)
pytest -q                                # ~235 tests
ruff check .                             # lint
```

---

## Mapping audit

Each contract carries a `mapping_confidence` (high when keyed to the stable competitor UUID; low for a
name-only fallback) and a `mapping_reason`. The per-participant detail view (Streamlit) shows an
explicit **expected-vs-found** progression ladder (a missing layer is surfaced explicitly, not implied),
and offers a **per-participant export** (JSON snapshot + CSV) of contracts and consistency comparisons.

Directly beneath the progression ladder, the detail view shows **raw stage-ladder spreads** — the
percentage-point and cents gaps between adjacent layers. These are raw price differences only (not a
probability model); an inverted spread is the same inconsistency the consistency table flags. Each row
shows the worse of the two layers' **Quote** quality; a `missing_price` row is shown blank rather than
as a misleading number.

---

## Notes

- Read-only / on-demand snapshot. No trading, no authentication required.
- The snapshot store persists opportunity history locally (`.db` file, gitignored) within the
  retention window (`config.SNAPSHOT_RETENTION_SECONDS`). No remote storage.
- The rate throttle is **process-wide only** — multiple processes/containers each have their own
  limiter; aggregate rate = `MAX_RPS × process count`.
- Between rounds (no open events for a sport), the app shows an informational message rather than an
  empty table — empty results are valid, not errors.
- Failed series are reported in the in-app **Debug** expander (Streamlit) and in `GET /coverage`
  (engine API) — never silently dropped.
- The Kalshi **web** site is bot-throttled (HTTP 429), so automated link-reachability checks from this
  environment are unreliable. Links point at the specific market via the verified deep-link format;
  `scripts/check_links.py` does a best-effort live check meant to run from an unthrottled network.
- **Remaining deferred work:** export overhaul (Stage 6); Streamlit app retirement (follow-up after
  the NiceGUI dashboard stabilizes). Full-scan toggle in the engine UI is also deferred.
