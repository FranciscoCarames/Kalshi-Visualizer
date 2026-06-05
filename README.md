# Kalshi Visualizer — Multi-Sport Executable-Inconsistency Dashboard

A small, read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for **tennis (ATP/WTA), NBA, WNBA, golf, soccer, MLB, and NHL**.
It surfaces two classes of opportunity across related contracts:

1. **Layer-consistency violations** — a deeper outcome must not price above a prerequisite that
   contains it (e.g. *Win Tournament ≤ Reach Final ≤ Reach Semifinal*). Framed as buy-only
   opportunities: **Buy YES** on the broader leg, **Buy NO** on the deeper leg.
2. **Dutch-book arbitrage** — a mutually-exclusive-and-exhaustive pair of 2-outcome markets where
   covering both outcomes costs under 100¢. True arbitrage: both legs are outcomes of the *same*
   event and settle together, so no settlement-rule caveat applies.

Results are split into Actionable / Blocked / Near-edge sections with collapsed diagnostics, per-player
detail, and debug. The dashboard auto-refreshes on a timer under a process-wide rate throttle.

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
| Golf | Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win Tournament |
| Soccer (World Cup) | Reach Round of 16 ⊇ Reach Quarterfinals ⊇ Reach Semifinals ⊇ Reach Finals |
| MLB | Reach Playoffs ⊇ Win League ⊇ Win World Series |
| NHL | Reach Playoffs ⊇ Win Conference ⊇ Win Championship |

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

Beyond the 2-outcome case the module also covers **soccer 3-way games** (Home/Away/Tie, both directions)
and **tournament-winner fields** (≥3 "win the tournament" markets). A winner field is mutually exclusive
(one champion) but not provably exhaustive, so it is **overround-only**: Buy NO on the priceable subset of
entrants, which is safe because an untraded or unlisted winner only pays more (floor `(k−1)×100¢` for the
`k` legs bought, `gap = Σ yes_bid(subset) − 100`). Empty-book longshots are skipped; many legs are illiquid
so these are often only partly fillable.

**Sport coverage:** tennis matches + NBA/WNBA/NHL playoff series + per-game (`KX*GAME`) for NBA/WNBA/MLB/NHL +
soccer 3-way games + tournament-winner fields (all sports). MLB and NHL also have NBA-shape futures ladders
(MLB: Reach Playoffs ⊇ Win League ⊇ Win World Series; NHL: Reach Playoffs ⊇ Win Conference ⊇ Win
Championship); MLB and NHL game books carry the per-game `settlement_caveat` (a postponed/suspended game
can settle differently). Props and advancement markets are excluded (`KXMLBSERIES` too — a regular-season
series can tie 2-2, so it isn't MECE; NHL's `KXNHLSERIES` IS a clean best-of-7 playoff series, so it stays
in). Unknown series are always excluded.

---

## Multi-Sport Engine (`sports.py`)

One detection engine, swappable data per sport. Each sport is a `SportConfig` holding the series
prefixes, a structured identity resolver (stable competitor UUID → normalized name fallback), market
classification (family + ladder node + eligibility), the containment ladder, and labels. Adding a
sport is a matter of dropping in a new `SportConfig` and calling `register()`. Unknown series resolve
to the explicit `UNKNOWN` sport — never silently to tennis.

Registered sports:

| Sport | Series prefixes / ownership | Identity key | Match family |
|---|---|---|---|
| Tennis 🎾 | `KXATP*`, `KXWTA*` | `custom_strike.tennis_competitor` UUID | `match` |
| NBA 🏀 | `KXNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |
| WNBA 🏀 | `KXWNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |
| Golf ⛳ | `exact_series` (`KXPGATOP5/10/20`, `KXPGATOUR`) | `custom_strike.golf_competitor` UUID | — (no dutch books) |
| Soccer ⚽ | `exact_series` (`KXWC*` World Cup) | `custom_strike.soccer_team` UUID | — (3-way games) |
| MLB ⚾ | `KXMLB*` (allow-list) | `custom_strike.baseball_team` UUID | — (`KXMLBGAME` games) |
| NHL 🏒 | `KXNHL*` (allow-list) | `custom_strike.hockey_team` UUID | `match` (playoff series) |

---

## How it works

Kalshi organizes contracts as **Series → Event → Market (outcome)**. The app:

1. **Fetches** the selected sport's series. An optional **"Scan all"** checkbox dynamically discovers
   every series matching the sport's prefixes for extra contract types. Series list is cached 3600 s;
   contracts are cached for `REFRESH_TTL` (30 s).
2. **Classifies** each market by type (family + stage + ladder node) using the sport's `SportConfig`.
3. **Indexes** contracts by the participant's stable identity key (competitor/team UUID, or name
   fallback) so the same participant merges across all series.
4. **Stamps** each contract with a never-empty `tournament` grouping key (`data.tournament_of`).
   Containment ladders group by `(participant_key, tournament)` — ladders never mix across
   tournaments, and a fallback key never collapses to an empty string.
5. **Tournament is a client-side filter**, not a fetch gate — all events for a sport are included,
   and the user narrows by tournament in the sidebar. The French Open is one of several tennis
   tournaments, not a special case.

### Discovery modes

- **Default (fast):** fetch only the sport's `default_series` — typically 6 well-known series.
- **Scan all (default ON):** dynamically discover every series matching the sport's prefixes; widens
  coverage to set-winner, exact-score, per-game, and other contract types.

### Pricing columns

Rather than a single implied probability, each row exposes:

- **Display %** — YES midpoint when the bid/ask spread is reasonable (≤ 20¢), otherwise last trade,
  otherwise blank. An empty `0.00/1.00` order book is never disguised as a fake 50%.
- **YES mid % / Last % / YES bid % / YES ask % / Spread ¢** — the raw components.
- **Quote** — quality flag (Tight / OK / Wide / Very wide / One-sided / No quote) so an unreliable
  price is immediately visible.

### Stage 0 dashboard clarity (shipped)

- **Timezone selector** with Lisbon as the default; comparison math stays exact UTC, only display
  converts.
- **Always-visible data-freshness strip** (per-second ticks) showing data age and coverage — no
  stale data passes silently.
- **"Show IDs & codes" toggle** to surface raw tickers, event IDs, and other debug fields without
  cluttering the default view.
- **Debug and diagnostics** hidden behind an Advanced toggle; the opportunity-ranking bar chart was
  removed as misleading (the Actionable table is the ranking surface).

---

## Project layout

| File | Responsibility |
|---|---|
| `config.py` | Base URL, series tickers, thresholds, rate-limit + refresh knobs, timezone options |
| `kalshi_client.py` | Read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide throttle |
| `sports.py` | Sport abstraction — `SportConfig`, registry, `sport_for_series`; imports only `config` + stdlib |
| `data.py` | Parsing, `tournament_of`, `build_contracts` (all events, all sports), cent-exact pricing helpers (no Streamlit) |
| `consistency.py` | Containment ladder + match-alignment classifier, `build_checks`, `bucket_of`, buy-only action plans (no Streamlit) |
| `dutchbook.py` | Dutch-book / MECE arbitrage detector — 2-outcome events (no Streamlit) |
| `glossary.py` | `GLOSSARY`, `BLOCKERS`, `WATCHLIST_NOTE`, `help_for` — single-sourced terminology (no Streamlit) |
| `filters.py` | `apply_membership` (tournament/family/layer/event/participant/volume) + `apply_thresholds` (size/quote/status) (no Streamlit) |
| `viz.py` | `payoff_chart_data` + `ladder_prices` — tidy chart frames (no Streamlit) |
| `app.py` | Streamlit UI: sidebar controls, auto-refresh fragment, dashboard sections, charts |
| `tests/` | ~480 pytest tests — pure-logic layers, the in-process engine + REST API, and headless NiceGUI smoke (no network) |

`data.py`, `consistency.py`, `dutchbook.py`, `sports.py`, `glossary.py`, `filters.py`, and `viz.py`
are **Streamlit-free** and independently testable.

---

## Setup & run

Two front-ends share one read-only engine. The **Streamlit** app is the original UI; the **FastAPI +
NiceGUI** server (`serve.py`) is the opportunity-first dashboard + a typed REST API on one port.

```bash
pip install -r requirements.txt          # streamlit, requests, pandas, altair, fastapi, nicegui, uvicorn
streamlit run app.py                     # Streamlit UI
python serve.py                          # FastAPI + NiceGUI dashboard at /, REST at /opportunities etc.
```

The app opens in your browser. Auto-refresh is on by default (120 s interval; configurable in the
sidebar). Data is public — no API key required. The REST API serves `/healthz` (liveness), **`/readyz`**
(readiness — `ready`/`degraded`/`not_ready`: DB writable + a fresh snapshot), `/coverage`, and a
low-cardinality `/metrics` (scan counters + heartbeat) for monitoring. `POST /scan` triggers a scan (the
dashboard's own "Scan now" button is non-force — it respects the refresh TTL); on a LAN, set `SCAN_TOKEN`
to require an `X-Scan-Token` header on `POST /scan` (off by default). `SNAPSHOT_DB_PATH` points the
snapshot store at a writable path. For office-LAN hosting, `scripts/build_deploy_repo.py` builds a clean
runtime-only deploy artifact and `deploy/` ships the systemd + scan-timer + `scan.sh` templates — see
`docs/DEPLOYMENT.md`.

## Tests

Pure logic + the in-process engine are covered by unit tests (no network); the NiceGUI dashboard has
**headless browser smoke tests** (`tests/test_browser.py`, via `nicegui.testing` — no selenium).

```bash
pip install -r requirements-dev.txt      # adds pytest, pytest-asyncio, ruff
pytest -q                                # full suite (engine + API + viewmodel + browser smoke)
ruff check .                             # lint
```

Verify without a browser: `pytest -q`; `python -c "import app, serve"`; a headless Streamlit boot
(`streamlit run app.py --server.headless true --server.port 8765` → `/_stcore/health` 200) and a `serve.py`
boot (`GET /`, `/healthz`, `/metrics` → 200 and `/readyz` → ready/degraded). See
`docs/RELEASE_CHECKLIST.md` for the full pre-ship checklist.

---

## Mapping audit

Each contract carries a `mapping_confidence` (high when keyed to the stable competitor UUID; low for a
name-only fallback) and a `mapping_reason`. The per-participant detail view shows an explicit
**expected-vs-found** progression ladder (a missing layer is surfaced explicitly, not implied), and
offers a **per-participant export** (JSON snapshot + CSV) of contracts and consistency comparisons.

Directly beneath the progression ladder, the detail view shows **raw stage-ladder spreads** — the
percentage-point and cents gaps between adjacent layers. These are raw price differences only (not a
probability model); an inverted spread is the same inconsistency the consistency table flags. Each row
shows the worse of the two layers' **Quote** quality; a `missing_price` row is shown blank rather than
as a misleading number.

---

## Architecture (shipped) & roadmap

The engine was migrated behind a **FastAPI** back-end (typed REST API: `/healthz`, `/readyz`,
`/opportunities`, `/coverage`, `/metrics`, `/scan`, `/alerts`, …) with a **NiceGUI** opportunity-first
dashboard mounted on the same server (`serve.py`), hardened for office-LAN hosting (readiness probe,
env-driven DB path, non-force manual scan, a Linux-first runbook, and a clean deploy-repo builder +
`deploy/` systemd templates). A SQLite **snapshot store** persists each scan (opportunities + per-sport
evidence frames); a **ScanManager** singleflights scans behind a non-blocking `POST /scan`. The dashboard
surfaces
ranked Actionable / Review / Blocked sections, a participant-detail panel, a diagnostics/debug section with
AG-Grids, truthful empty states, snapshot export, and live freshness — all reading the engine in-process.
The Streamlit app (`app.py`) is still shipped alongside it. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for
the staged history and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for office-LAN hosting.

The synthetic exact-score bundle is hedged two ways — against the **match-winner** market and against the
**advance / win-tournament** market the match implies (winning a quarterfinal ≡ reaching the semifinal),
emitted independently and review-only.

Remaining (not yet built): the advancement-field detector (n-outcome reach-a-stage fields) and field
underround — both need an exhaustiveness proof. See **Known limits** below for what the edges deliberately
do not model.

---

## Known limits (not modeled)

Every edge the app reports — `exec_gap_c`, ROI, "Gross profit $", "Max units" — is **gross and
top-of-book**. The engine never silently nets execution costs into the actionability decision, so a finding
can look positive yet be unprofitable in practice. Three limits are **documented but not built** (until the
owner opts in); they are single-sourced in `glossary.py` (term **"Known limits"**):

- **Net-of-fees not modeled.** Kalshi's trading / settlement fees are not subtracted; a thin gross gap can
  turn net-negative after fees. Fee metadata may be captured for honest caveats, but it never drives the
  gap — "gross-only" means "don't silently net fees", not "ignore fees".
- **Position limits & collateral not modeled.** Sizes are the top-of-book quote size; the app does not
  account for Kalshi's per-market position caps or the collateral needed to hold every leg, so "Max units"
  and "Gross profit" assume you can take the full quoted size.
- **Full-depth execution not modeled.** Prices and sizes are **top-of-book only**; filling more than the
  top resting size walks the book to worse prices. The app does not model depth, so the displayed size is
  the max at the quoted price, not the total tradable edge.

Treat every edge as an upper bound on what the quotes imply, not a guaranteed take-home.

---

## Notes

- Read-only / on-demand snapshot. No trading, no stored history, no authentication required.
- Between rounds (no open events for a sport), the app shows an informational message rather than an
  empty table — empty results are valid, not errors.
- Failed series are reported in the in-app **Debug** expander — never silently dropped.
- The rate throttle is **process-wide only** — multiple processes/containers each have their own
  limiter; aggregate rate = `MAX_RPS × process count`.
- The Kalshi **web** site is bot-throttled (HTTP 429), so automated link-reachability checks from this
  environment are unreliable. Links point at the specific market via the verified deep-link format;
  `scripts/check_links.py` does a best-effort live check meant to run from an unthrottled network.
