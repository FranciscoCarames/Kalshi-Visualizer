# Kalshi Visualizer — Multi-Sport Executable-Inconsistency Dashboard

A small, read-only [NiceGUI](https://nicegui.io/)-on-[FastAPI](https://fastapi.tiangolo.com/) dashboard
(run via `serve.py`) over live [Kalshi](https://kalshi.com/) prediction-market data for **tennis
(ATP/WTA), NBA, WNBA, golf, soccer, MLB, NHL, motorsport (F1/NASCAR/IndyCar/MotoGP), NFL, and esports** —
10 sports. It finds two classes of opportunity across a participant's related contracts and ranks them
best-first.

1. **Layer-consistency violations** — a deeper outcome must not price above a prerequisite that
   contains it (e.g. *Win Tournament ≤ Reach Final ≤ Reach Semifinal*). Framed as buy-only:
   **Buy YES** on the broader leg, **Buy NO** on the deeper leg.
2. **Dutch-book edges** — a mutually-exclusive set of binary markets whose every outcome can be
   covered for under the guaranteed payout floor.

Findings are ranked into **Actionable / Review / Blocked** with collapsed diagnostics and a
per-participant detail panel. A background scan refreshes a SQLite snapshot store under a process-wide
rate throttle, and the browser re-reads the latest snapshot on a timer.

> **Read-only by design.** No trading, no authentication, no order placement. Every reported edge is
> **gross and top-of-book** — see [Known limits](#known-limits).

---

## Quickstart

```bash
pip install -r requirements.txt          # requests, pandas, fastapi, nicegui, uvicorn
python serve.py                          # dashboard at /, REST API alongside it
```

The dashboard opens at `/`; the data is public, so no API key is required. The REST API serves
`/opportunities`, `/coverage`, `/backlog`, `/alerts`, `/metrics`, `/healthz` (liveness), `/readyz`
(readiness — `ready`/`degraded`/`not_ready`: DB writable + a fresh snapshot), and `POST /scan` (a
non-blocking, singleflighted scan). Background auto-scan is on by default. For office-LAN hosting (bind
safety, systemd service + scan timer, the clean deploy artifact), see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

### Tests

```bash
pip install -r requirements-dev.txt      # adds pytest, pytest-asyncio, ruff
pytest -q                                # pure layers + in-process engine/API + headless NiceGUI smoke
ruff check .                             # lint
```

Verify without a browser: `pytest -q`; `python -c "import serve, api, webui.dashboard"`; and a `serve.py`
boot (`GET /`, `/healthz`, `/metrics` → 200, `/readyz` → ready/degraded). The NiceGUI dashboard has
headless browser smoke tests (`tests/test_browser.py`, via `nicegui.testing` — no selenium).

---

## Layer Consistency Checker

The ladder compares contracts with a provable **containment** relationship and flags **executable
inconsistencies** — a firm bid/ask cross with order size behind it. It is deliberately conservative:

- **Executable test** uses firm YES bid/ask **and positive order sizes**, compared in exact integer
  cents. A child YES bid above the parent YES ask is `EXECUTABLE_VIOLATION` — the only *Broken* status.
- **Display test** compares the display %; a breach is `DISPLAY_VIOLATION` (a *Warning*, may not be tradable).
- Wide/empty books, missing sizes, missing layers, and unprovable relationships surface as
  `WIDE_QUOTE` / `MISSING_QUOTE` / `QUOTE_SIZE_MISSING` / `MISSING_LAYER` / `UNKNOWN_RELATIONSHIP` —
  **never** mislabelled as violations.
- **Match-alignment** rows (winning your current match ⇔ reaching the next stage) are included only when
  the round maps confidently, and always carry a `RULE_CHECK_REQUIRED` / `RULE_MISMATCH` flag. These are
  called *executable inconsistencies*, **not arbitrage**, because the two markets' settlement rules are
  not auto-verified.

### Containment ladders by sport

| Sport | Ladder (broad → deep) |
|---|---|
| Tennis | Reach Semifinal ⊇ Reach Final ⊇ Win Tournament |
| NBA | Reach Playoffs ⊇ Win Conference ⊇ Win Championship |
| WNBA | Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship |
| Golf | Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win Tournament |
| Soccer (World Cup) | Reach Round of 32 ⊇ Reach Round of 16 ⊇ Reach Quarterfinals ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win the World Cup |
| MLB | Reach Playoffs ⊇ Win League ⊇ Win World Series |
| NHL | Reach Playoffs ⊇ Win Conference ⊇ Win Stanley Cup |
| NFL | Reach Playoffs ⊇ Win Conference ⊇ Win Super Bowl |
| Motorsport | per-race finishing position, e.g. Top 10 ⊇ Top 5 ⊇ Podium ⊇ Win Race |

Esports has no containment ladder in v1 (winner-field overround + per-game/per-map dutch books only).

---

## Dutch-Book Detector (`dutchbook.py`)

A **separate check family** from the containment ladder, in its own UI-free module. It covers a MECE
(mutually-exclusive-and-exhaustive) set of binary markets, in two directions — both expressed as **buys**,
never sells:

- **Underround → Buy YES on all legs.** `Σ yes_ask < 100¢` — one outcome wins and pays 100¢.
- **Overround → Buy NO on all legs.** `Σ no_ask < (n−1)·100¢` — every loser's NO pays 100¢.

The two directions are mutually exclusive (`bid ≤ ask`), so at most one fires per event. All comparisons
are exact integer cents; the status is `EXECUTABLE_DUTCH_BOOK`. The wording stays conservative — a **gross
two-way pricing discrepancy under normal one-winner settlement**, never "riskless" or "true arbitrage".

Shapes handled: **2-outcome** head-to-head match/series or single game; **soccer 3-way** games
(Home/Away/Tie); and **tournament-winner fields** (≥3 "win" markets). A winner field is mutually exclusive
(one champion) but not provably exhaustive, so it is **overround-only** on the priceable subset of
entrants — safe because an untraded or unlisted winner only pays more.

**Coverage:** tennis matches; NBA/WNBA/NHL playoff series; per-game (`KX*GAME`) for NBA/WNBA/MLB/NHL/NFL;
esports per-game and per-map (`KX*GAME`/`KX*MAP`, draw-free); soccer 3-way games; one-winner fields (all
sports, including motorsport race winners and per-title esports champions). Per-game and `KX*GAME`/`KX*MAP`
books carry a non-blocking `settlement_caveat` (a postponed/suspended game can settle differently). NFL
games **can tie**, so their two-way book is gated on a proof that a tie pays $0.50/side (`game_mece_by_shape`
+ `dutchbook._proves_fixed_sum`); the draw-free sports are ungated. Props and advancement markets are
excluded; `KXMLBSERIES` is excluded as non-MECE (a regular-season series can tie 2-2), while NHL's
`KXNHLSERIES` is a clean best-of-7 and stays in. Unknown series are always excluded.

A third family, the **synthetic exact-score bundle** (`synthetic_bundle.py`), replicates "this player wins
their match" from the MECE set of set-scores and prices it against two independent hedges. Because an exact
score settles differently from a match-winner on a retirement, every finding is settlement-caveated and
routed **review-only, never Actionable**.

---

## Multi-Sport Engine (`sports.py`)

One detection engine, swappable data per sport. Each sport is a `SportConfig` holding the series prefixes,
a structured identity resolver (stable competitor UUID → normalized name fallback), market classification
(family + ladder node + eligibility), the containment ladder, and labels. Adding a sport is a single
`register(SportConfig(...))` call. Unknown series resolve to an explicit `UNKNOWN` sport — never silently
to tennis.

| Sport | Series ownership | Identity key | Dutch-book shape |
|---|---|---|---|
| Tennis 🎾 | `KXATP*`, `KXWTA*` | `tennis_competitor` UUID | head-to-head matches |
| NBA 🏀 | `KXNBA*` | `basketball_team` UUID | playoff series + games |
| WNBA 🏀 | `KXWNBA*` | `basketball_team` UUID | playoff series + games |
| Golf ⛳ | `exact_series` (`KXPGATOP5/10/20`, `KXPGATOUR`) | `golf_competitor` UUID | winner field only |
| Soccer ⚽ | `exact_series` (`KXWCGAME`, `KXWCROUND`, `KXWCGROUPQUAL`, dormant `KXWC` outright) | `soccer_team` UUID | 3-way games + winner field |
| MLB ⚾ | `KXMLB*` (allow-list) | `baseball_team` UUID | `KXMLBGAME` games + winner field |
| NHL 🏒 | `KXNHL*` (allow-list) | `hockey_team` UUID | `KXNHLSERIES` + `KXNHLGAME` + field |
| NFL 🏈 | `KXNFL*` (allow-list) + `KXSB` | `football_team` UUID | `KXNFLGAME` games (tie-gated) + `KXSB` field |
| Motorsport 🏁 | `KXF1`/`KXNASCAR`/`KXINDY`/`KXMOTOGP` | driver/team UUID or constructor name | one-winner field overround |
| Esports 🎮 | `exact_series` (CS2/LoL/Valorant/Dota2/CoD/R6/… `KX*GAME`+`KX*MAP`, per-title winner) | `esports_competitor` UUID | draw-free games + maps + winner field |

Contracts are grouped by `(participant_key, tournament)`; the tournament key is season-scoped so
co-loaded seasons never form a false cross-season ladder. Tournament is a **client-side filter**, not a
fetch gate — all events for a sport are loaded and the user narrows in the UI.

---

## How it works

Kalshi organizes contracts as **Series → Event → Market (outcome)**. Each scan:

1. **Fetches** the enabled contract families' series (the hosted path uses each sport's core series;
   family toggles are the only control that changes what's fetched).
2. **Classifies** every market by type (family + stage + ladder node) via its `SportConfig`.
3. **Indexes** contracts by the participant's stable identity key (competitor/team UUID, or a low-confidence
   name fallback) so one participant merges across all series.
4. **Stamps** each contract with a never-empty `tournament` grouping key (`data.tournament_of`), so ladders
   never mix across tournaments and a fallback never collapses to an empty string.
5. **Detects** containment violations, dutch books, and synthetic bundles, ranks them, and writes a
   snapshot the dashboard reads.

### Pricing columns

Rather than a single implied probability, each row exposes the components so a price is never opaque:

- **Display %** — YES midpoint when the bid/ask spread is reasonable (≤ 20¢), otherwise last trade,
  otherwise blank. An empty `0.00/1.00` book is never disguised as a fake 50%.
- **YES mid / Last / YES bid / YES ask / Spread ¢** — the raw components.
- **Quote** — a quality flag (Tight / OK / Wide / Very wide / One-sided / No quote / Crossed) so an
  unreliable price is immediately visible.

---

## Project layout

| File | Responsibility |
|---|---|
| `config.py` | Base URL, series tickers, thresholds, rate-limit + refresh knobs |
| `kalshi_client.py` | Read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide throttle |
| `sports.py` | Sport abstraction — `SportConfig`, registry, `sport_for_series` (imports only `config` + stdlib) |
| `data.py` | Parsing, `tournament_of`, `build_contracts` (all events, all sports), cent-exact pricing helpers |
| `consistency.py` | Containment ladder + match-alignment classifier, `build_checks`, `bucket_of`, buy-only plans |
| `dutchbook.py` | Dutch-book / MECE detector (2-way, soccer 3-way, winner field) |
| `synthetic_bundle.py` | N-leg exact-score bundle detector (review-only) |
| `scanner.py` | Cross-sport `unified_opportunities` over the whole loaded universe |
| `store.py` / `lifecycle.py` | SQLite snapshot store + new/changed/recently-actionable diffs |
| `api.py` / `serve.py` | FastAPI REST API + NiceGUI dashboard on one app — the sole UI |
| `webui/` | NiceGUI `dashboard.py` + pure `viewmodel.py` / `diagnostics.py` cores |
| `glossary.py` / `filters.py` / `viz.py` | Single-sourced terms; two-pass filters; tidy chart frames |
| `tests/` | pytest suite — pure-logic layers, the in-process engine + REST API, headless NiceGUI smoke |

`data.py`, `consistency.py`, `dutchbook.py`, `sports.py`, `glossary.py`, `filters.py`, and `viz.py` are
**free of UI imports** (no `nicegui`, no `streamlit`) and independently testable.

---

## Mapping audit

Each contract carries a `mapping_confidence` (high when keyed to the stable competitor UUID; low for a
name-only fallback) and a `mapping_reason`. The per-participant detail view shows an explicit
**expected-vs-found** progression ladder (a missing layer is surfaced, not implied) and offers a
**per-participant export** (JSON snapshot + CSV). Beneath it, **raw stage-ladder spreads** show the
percentage-point and cents gaps between adjacent layers — raw price differences, not a probability model;
each row shows the worse of the two layers' quote quality, and a missing price is shown blank rather than
as a misleading number.

---

## Known limits

Every edge the app reports — `exec_gap_c`, ROI, "Gross profit $", "Max units" — is **gross and
top-of-book**. The engine never silently nets execution costs into the actionability decision, so a finding
can look positive yet be unprofitable in practice. Three costs are **documented but not modeled** (until
the owner opts in; single-sourced in `glossary.py`, term **"Known limits"**):

- **Fees not modeled.** Kalshi's trading/settlement fees are not subtracted; a thin gross gap can turn
  net-negative. "Gross-only" means "don't silently net fees", not "ignore fees".
- **Position limits & collateral not modeled.** Sizes are the top-of-book quote size; per-market position
  caps and the collateral to hold every leg are not accounted for.
- **Full-depth execution not modeled.** Prices and sizes are top-of-book only; filling past the top resting
  size walks the book to worse prices.

Treat every edge as an upper bound on what the quotes imply, not a guaranteed take-home.

---

## Notes

- Read-only / on-demand snapshot. No trading, no authentication, no order placement.
- Between rounds (no open events for a sport), the dashboard shows an informational message rather than an
  empty table — empty results are valid, not errors.
- Failed series are reported in the in-app **Debug** section — never silently dropped.
- The rate throttle is **process-wide only** — run a single worker; multiple processes each get their own
  limiter (aggregate rate = `MAX_RPS × process count`).
- See [`docs/STATUS.md`](docs/STATUS.md) for shipped state, current limits, and approved next work, and
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for office-LAN hosting.
