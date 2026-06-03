# Kalshi Visualizer — Multi-Sport Executable-Inconsistency Dashboard

A small, read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for **tennis (ATP/WTA), NBA, and WNBA**.
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
| Tennis 🎾 | `KXATP*`, `KXWTA*` | `custom_strike.tennis_competitor` UUID | `match` |
| NBA 🏀 | `KXNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |
| WNBA 🏀 | `KXWNBA*` | `custom_strike.basketball_team` UUID | `match` (playoff series) |

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
| `tests/` | ~158 pytest unit tests covering all pure-logic layers (no network required) |

`data.py`, `consistency.py`, `dutchbook.py`, `sports.py`, `glossary.py`, `filters.py`, and `viz.py`
are **Streamlit-free** and independently testable.

---

## Setup & run

```bash
pip install -r requirements.txt          # streamlit, requests, pandas, altair
streamlit run app.py
```

The app opens in your browser. Auto-refresh is on by default (120 s interval; configurable in the
sidebar). Data is public — no API key required.

## Tests

Pure logic is covered by unit tests (no network):

```bash
pip install -r requirements-dev.txt      # adds pytest + ruff
pytest -q                                # ~158 tests
ruff check .                             # lint
```

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

## Roadmap (planned — not yet built)

The forward plan is to migrate from a pure Streamlit front-end to a **FastAPI back-end** exposing the
engine as a REST API, with a **NiceGUI** interface mounted on the same server. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for the 6-stage plan. The Streamlit app is the current production
UI; no FastAPI/NiceGUI code exists yet.

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
