# CLAUDE.md

Guidance for **Claude Code** working in this repository. Self-contained — read top to bottom.

## Project

A small, **read-only** **NiceGUI trader dashboard** (on FastAPI, via `serve.py`) over live
[Kalshi](https://kalshi.com) prediction-market data for **tennis (ATP/WTA), NBA, WNBA, golf, soccer,
MLB, NHL, and motorsport (F1 / NASCAR / IndyCar / MotoGP)**. It surfaces **executable inconsistencies**
across a participant's related contracts (a
deeper outcome must not price above a prerequisite that contains it) and **dutch-book arbitrage** on
2-outcome MECE events, framed as buy-only opportunities (**Buy YES / Buy NO**), split into Actionable /
Blocked / Near-edge sections with collapsed diagnostics, per-player detail, and debug. Auto-refreshes on
a timer under a process-wide rate throttle. (The legacy Streamlit `app.py` was **retired** — NiceGUI is
the sole UI.)

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer` (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Multi-sport (shipped):** `sports.py` defines a `SportConfig` abstraction; tennis, NBA, WNBA, golf,
  soccer, MLB, NHL, and motorsport are registered sports (8). Adding a new sport = one
  `register(SportConfig(...))` call. (Golf
  uses `exact_series` ownership of its 4 finishing-position series + `match_family=""`; no dutch books.
  MLB: NBA-shape futures ladder Reach Playoffs ⊇ Win League ⊇ Win World Series + per-game `KXMLBGAME` dutch
  books; identity `custom_strike.baseball_team`; `match_family=""` (`KXMLBSERIES` excluded as non-MECE).
  NHL: NBA-shape futures ladder Reach Playoffs ⊇ Win Conference ⊇ Win Championship + `KXNHLSERIES`
  playoff-series AND `KXNHLGAME` per-game dutch books; identity `custom_strike.hockey_team`;
  `match_family="match"` (live `KXNHLSERIES` rounds are only "1st/2nd Round" → no ladder rung →
  `UNKNOWN_RELATIONSHIP`).
  `SportConfig.winner_label` gives the winner family its per-sport wording — "Win the World Series" /
  "Win the Stanley Cup" / "Win the Championship" / default "Win the tournament". Non-tennis grouping keys
  are season-scoped (`data.tournament_of` appends `· <season>` so co-loaded seasons never cross-pair).
  Motorsport (F1/NASCAR Cup+Truck+O'Reilly/IndyCar/MotoGP, prefixes `KXF1`/`KXNASCAR`/`KXINDY`/`KXMOTOGP`):
  a **field sport like golf** (`match_family=""`, no pair dutch books). Identity multi-path
  `racing_competitor`(driver UUID) / `nascar_team`(UUID) / `Participant`(constructor NAME → low conf via
  `IdentityResolver.id_validator`); `player_key` is **role-namespaced** (`driver:`/`constructor:`/`team:`)
  from the classified family so a constructor sharing the driver UUID path never merges. **One-winner
  FIELDS** (`field_families` = winner/race_winner/pole/fastest_lap/constructor/team — all
  `mutually_exclusive`) get the overround dutch book; **Top-N/Podium are `mutually_exclusive=False`** → the
  per-competition finishing-position **ladder** (`ladder_fn`: F1 Top10⊇Top5⊇Podium⊇WinRace; Cup
  Top20⊇Top10⊇Top5⊇Top3⊇WinRace; Truck/IndyCar Top10⊇Top3⊇WinRace; MotoGP/O'Reilly none). Kalshi "Games"
  scope = **race winner** (NOT the app `game` family). Grouping is per RACE INSTANCE via `tournament_key_fn`
  → `competition · session · token` (e.g. `F1 · main-race · MONGP26`); raw `competition_scope` is never in
  the key. `KXF1H2H`/`KXNASCARH2H` listed-but-deferred → "other".)
  `build_contracts`
  includes **all events for all registered sports**; containment ladders group by **(player_key,
  tournament)** per sport. Tournament is a client-side filter.
- **Scope guard — do NOT add unless explicitly asked:** trading, authentication, order placement,
  historical/time-series storage, alerts, conditional-probability/de-vig models. Adding a **new sport**
  is in scope via a `SportConfig` drop-in; non-sport-config work is not. (The approved roadmap will
  introduce a SQLite snapshot store and alerts in a future stage — do not add those until asked.)

## Run & verify

```bash
pip install -r requirements.txt          # runtime: requests, pandas, fastapi, nicegui, uvicorn
python serve.py                          # FastAPI + NiceGUI dashboard (/) + REST API
pip install -r requirements-dev.txt      # adds pytest, pytest-asyncio, ruff
pytest -q                                # unit tests for the pure layers + headless NiceGUI smoke (no network)
ruff check .                             # lint
```

To verify without a browser: `pytest -q`; `python -c "import serve, api, webui.dashboard"`; and a
`serve.py` boot — `GET /`, `/healthz`, `/metrics` → `200` plus `/readyz` (readiness:
`ready`/`degraded`/`not_ready`). The NiceGUI dashboard itself has headless browser smoke tests
(`tests/test_browser.py`, via `nicegui.testing` — no selenium). Live Kalshi calls, `pip`, and
`git push` in this environment require running the Bash tool with the sandbox disabled (network is
otherwise blocked).

**NiceGUI dashboard / LAN hosting:** `python serve.py` runs the FastAPI engine API + NiceGUI dashboard on
one app (default loopback `127.0.0.1:8000`). `API_HOST`/`API_PORT` are env-overridable; binding a
non-loopback host **requires** `NICEGUI_STORAGE_SECRET` (`serve.bind_safety` fail-hard, no auth — escape:
`ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`) and warns on `WEB_CONCURRENCY>1` (store + throttle are process-local).
**Liveness** `/healthz`; **readiness** `/readyz` (PR S1 — `ready`/`degraded`/`not_ready`+503: DB writable
+ a fresh snapshot, via the MIGRATION-FREE probe `store.db_writable`; reflects the last scan, no live
Kalshi call). `SNAPSHOT_DB_PATH` is env-overridable (PR S2 — applied at `serve._apply_snapshot_db_path()`
startup with a parent-dir check; `config.py` stays import-free). **Deploy artifact:**
`scripts/build_deploy_repo.py` builds a clean runtime-only repo (import-graph allowlist → no
tests/docs/state; pinned `requirements.txt`); `deploy/` ships the systemd service + scan
`.timer` + `scan.sh` wrapper (PR D). See `docs/LAN_ACCESS.md` / `docs/DEPLOYMENT.md` (+ `serve_lan.ps1`).
**`POST /scan` is NON-BLOCKING** (202; PR 21b): a process-local `scan_manager.ScanManager` singleflight
(shared by `POST /scan` AND `webui.run_scan_now` → one upstream fetch) runs the scan on a background
thread; `?wait=true` bounded-blocks, `?force=true` overrides the TTL/budget, `GET /scan/status` polls. The
dashboard "Scan now" button is **NON-force by default** (PR S3 — it respects the TTL/cooldown like the
scheduler; force is reachable only via the token-gated HTTP endpoint, no UI force button). The scanner
persists per-sport
contracts/checks/dutchbook frames + coverage counters (`contracts_scanned`/`checks_tested`/`kalshi_requests`)
per scan (PR 21a).

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
**MLB series** (`sports.py` `MLB`): identity `custom_strike.baseball_team`. `KXMLB` (World Series winner), `KXMLBAL`/`KXMLBNL` (advance = win the AL/NL pennant → "Win League"), `KXMLBPLAYOFFS` (advance = reach the playoffs, a many-Yes qualifier field), `KXMLBGAME` (per-game dutch book, carries the per-game `settlement_caveat`). `KXMLBSERIES`/`KXMLBWS`/divisions/`KXMLBASGAME`/`KXMLBSTGAME`/props → `other` (allow-list, not the `KXMLB` prefix). `KXMLBSERIES` is excluded as non-MECE (a regular-season series can tie 2-2).

**NHL series** (`sports.py` `NHL`): identity `custom_strike.hockey_team`. `KXNHL` (Stanley Cup winner → "Win the Stanley Cup"), `KXNHLEAST`/`KXNHLWEST` (advance = win conference → "Win Conference"), `KXNHLPLAYOFF` (advance = reach the playoffs, a many-team qualifier field), `KXNHLSERIES` (playoff-series `match` dutch book), `KXNHLGAME` (per-game dutch book, carries the per-game `settlement_caveat`). Lookalikes (`KXNHLSERIESGAMES`/`KXNHLFINALSEXACT`/props) → `other` (exact-equality allow-list, not the `KXNHL` prefix). Unlike MLB, `KXNHLSERIES` IS a clean best-of-7 → kept; but live series wording is only "1st/2nd Round" (read from title + `rules_primary`, ticker suffix `Rn`), which maps to NO ladder rung → series match-alignment is safely `UNKNOWN_RELATIONSHIP`.

## Architecture

```
config.py          # BASE_URL, DEFAULT_SERIES, discovery prefixes, thresholds, rate-limit
                   #   (MAX_RPS/CONCURRENCY/BACKOFF_*) + refresh (REFRESH_TTL/OPTIONS/NEAR_EDGE_MIN_C) knobs
sports.py          # NO streamlit: SportConfig registry — Tennis, NBA, WNBA, Golf registered; sport_for_series()
                   #   resolves a series ticker to its SportConfig (UNKNOWN when unrecognized, never silent
                   #   tennis default); IdentityResolver, MarketClassification, LadderSpec dataclasses;
                   #   adding a sport = register(SportConfig(...))
kalshi_client.py   # read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide
                   #   throttle (MAX_RPS), discover_tennis_series(), get_series_titles(), get_events_for_series()
data.py            # NO streamlit/pandas: parsing, to_cents(), classify_kind/tour_of, pricing helpers,
                   #   tournament_of()->(key,source), series_for_families(), kalshi_market_url(),
                   #   build_contracts() (ALL events for all registered sports — stamps tournament/tournament_source)
                   #   + fmt_time/data_age_seconds/is_stale (display-only TZ + staleness helpers, Stage 0)
consistency.py     # NO streamlit: node_of, build_player_nodes, representative, expected_nodes,
                   #   layer_spreads, build_checks (groups by [player_key, tournament]); buy-only action
                   #   plan + tradable_now + blockers; bucket_of (dashboard routing, incl. dutch-book)
dutchbook.py       # NO streamlit: find_dutch_books() — MECE dutch-book detector, 2-outcome + n-outcome (soccer 3-way via prove_mece/_detect_n_way); a check family
                   #   SEPARATE from the containment ladder); covers match/series AND per-game (game family);
                   #   status EXECUTABLE_DUTCH_BOOK; see section below
synthetic_bundle.py# NO streamlit/pandas: find_synthetic_bundles() — N-leg exact-score / state-bundle
                   #   detector. A player's MECE set scores ({3-0,3-1,3-2} bo5 / {2-0,2-1} bo3) replicate
                   #   "they win", priced vs TWO independent hedges (match-winner AND the implied advance/
                   #   win-tournament market); both directions; ALWAYS settlement-caveated (review-only,
                   #   never Actionable). parse_scoreline + expected_states (format-gated); status
                   #   EXECUTABLE_SYNTHETIC_BUNDLE; see section below
glossary.py        # NO streamlit: GLOSSARY{term:{short,long}}, BLOCKERS, WATCHLIST_NOTE, help_for
filters.py         # NO streamlit: apply_membership (tournament/family/layer/event/participant/volume)
                   #   / apply_thresholds (size/quote/market-status) — the two-pass filter split
viz.py             # NO streamlit: payoff_chart_data + ladder_prices (tidy chart frames). NOTE: the
                   #   opportunity_ranking bar chart was REMOVED (Stage 0) — it was misleading; the
                   #   Actionable table is the ranking surface (Stage 2 adds a sortable unified table).
serve.py / api.py  # FastAPI engine API + NiceGUI dashboard entrypoint — the SOLE UI (Streamlit retired)
webui/             # NiceGUI dashboard (dashboard.py) + pure viewmodel.py / diagnostics.py cores
scripts/           # check_links.py (local link reachability), export_glossary.py (-> docs/GLOSSARY.md)
docs/GLOSSARY.md   # generated in-depth glossary (also published as a Google Doc)
tests/             # pytest: test_data, test_consistency, test_dutchbook, test_glossary, test_client,
                   #   test_filters, test_viz, test_sports, test_api, test_webui, … (full suite)
```

`sports.py`, `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` MUST stay free of UI
imports (no `nicegui`, no `streamlit`) — they are pure logic, independently testable.

- **Fetch by family (do not regress):** the fetch (`fetch.py`, extracted from the old
  `app.load_contracts`) pulls ONLY the series whose contract family is enabled
  (`data.series_for_families`) — **family toggles are the only control that changes what's fetched**.
  The hosted scan path is `api.fetch_dep()` → **core series only** (`scan_all=False`); tournament/event/
  participant filters are client-side. (`scan_all=True` would widen via `discover_tennis_series()`.)
- **Auto-refresh (do not regress):** the NiceGUI dashboard refreshes from the persisted snapshot store;
  a process-local **`scan_manager`/`scan_scheduler`** runs background scans on a timer (on by default —
  `config.AUTO_SCAN_DEFAULT_ENABLED`, every `AUTO_SCAN_DEFAULT_SECONDS`), and the browser re-reads the
  latest snapshot on a `ui.timer`. `POST /scan` is non-blocking + singleflight (one upstream fetch shared
  by the API and the dashboard's "Scan now"). (The retired Streamlit app used an `@st.fragment(run_every)`
  re-fetch instead.)
- **Rate limiting (free tier):** Kalshi Basic read ≈ 20 req/s (200 tokens/s ÷ 10/GET; verified at
  docs.kalshi.com/getting_started/rate_limits). `kalshi_client._throttle` caps issuance at
  `config.MAX_RPS` (15, ~75%) via a min-interval limiter; the hard ban floor is `_get`'s exponential
  backoff on 429 (honoring `Retry-After` when the 429 carries one — Kalshi may omit it) via
  `MAX_RETRIES`/`BACKOFF_*`; fan-out concurrency is `CONCURRENCY` (4). **The throttle is PROCESS-WIDE
  ONLY** — 15/s is safe for ONE process; multiple processes/workers/replicas each have their own limiter
  (aggregate = `MAX_RPS × process count`), so don't run several without a shared limiter.
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source,
  mapping_confidence, mapping_reason, tour, kind, category, contract, stage, stage_rank, opponent,
  tournament, tournament_source, subpenny, display_pct, yes_mid_pct, last_pct, yes_bid_pct, yes_ask_pct,
  spread_cents, quote_quality, yes_bid_c,
  yes_ask_c, last_c, display_c, yes_bid_size, yes_ask_size, no_bid_pct, no_ask_pct, no_bid_c, no_ask_c,
  volume, open_interest, status, time_value, time_kind, kalshi_url, series, event_ticker, market_ticker,
  event_title, market_title, raw_yes_bid, raw_yes_ask, raw_no_bid, raw_no_ask, raw_last, rules_primary`.

## Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last
  trade, else blank. A `0.00/1.00` book is "No quote" (never a fake 50%).
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote.
- Surface every component (mid / last / bid / ask / spread) so a price is never opaque.
- **Known limits (gross, top-of-book — single-sourced in `glossary.py` "Known limits"):** every edge is
  GROSS and TOP-OF-BOOK. Three costs are documented, NOT modeled, until the owner opts in — exchange
  **fees** (never netted into the gap; "gross-only" ≠ "ignore fees"), **position limits / collateral**, and
  **full-depth execution** (filling past the top size walks the book). Treat edges as an upper bound.

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
A dutch book is an executable edge on a **mutually-exclusive-and-exhaustive** set of binary markets:
cover EVERY outcome for under the guaranteed payout floor. **2-outcome** case = a head-to-head match/game
(two distinct-participant markets; floor 100¢). **n-outcome** case = a soccer World Cup 3-way game
(Home/Away/Tie; `prove_mece` requires 2 participants + 1 Tie via `is_participant`, the `mutually_exclusive`
flag, the draw-excluded phrase, and a shared settlement basis). Underround = Buy YES all (`Σ yes_ask <
100`); overround = Buy NO all (`Σ no_ask < (n−1)·100` — the generalized payout floor). `find_dutch_books`
dispatches soccer to `_detect_n_way` (emitting the N-leg `legs` schema) and every other sport to the
unchanged 2-way `_detect_pair`; ≤1 finding/event.

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
  string is held as a literal in `consistency.py` (a test guards the contract). **Conservative wording —
  never "riskless"/"locked"/"true arbitrage"** (single-sourced via `glossary.DUTCH_BOOK_BASIS`): it is a
  **gross two-way pricing discrepancy under normal one-winner settlement**. Match/series legs settle
  together; a **per-game (`KX*GAME`) book carries a non-blocking postponement caveat** (`settlement_caveat`
  from `BLOCKERS["game_settlement"]` — abnormal resolution like a postponed/abandoned/no-contest game can
  break it). The caveat is advisory: it never changes `tradable_now`/bucket, so a game book can still be
  Actionable.
- **UI:** dutch-book findings flow through `scanner.unified_opportunities` into the NiceGUI dashboard's
  ranked Actionable/Review/Blocked tables (membership-filtered; thresholds spare Actionable). The Caveat
  column shows `settlement_caveat` + `blockers`. (Historically the retired Streamlit `app.py` rendered a
  dedicated "Dutch-book arbitrage — match books" section, since both legs are the *same* side.)
- **In scope (built):** per-game 2-outcome books (NBA/WNBA `KX*GAME`) — milestone m1.1; soccer 3-way games
  (`_detect_n_way`, milestone m1 soccer); the **N-leg exact-score synthetic bundle** (`synthetic_bundle.py`,
  m5 — see next section); and **tournament-winner FIELDS** (`_detect_field`, PR 27b). A winner field is
  mutually exclusive (one champion) but NOT provably exhaustive (fewer "win" markets than the draw), so it is
  **overround-only** (`prove_field_mece` sets `exhaustive=False` → underround never emitted). The overround is
  safe on **any priceable subset** (`_field_overround_subset`: legs with a firm no-side price + `yes_bid>0`):
  buying NO on k legs pays ≥`(k−1)·100` and an untraded/unlisted winner only pays more, so empty-book
  longshots are skipped. `gap = Σ yes_bid(subset) − 100`; the id keys on the EVENT (stable across subset
  shifts); a non-blocking `field_overround` advisory caveat flags the subset/partial-fill nature.
  `find_dutch_books` groups winner rows separately (`_is_field_row`) → `_detect_field`; the 2-way/soccer paths
  stay byte-identical. **Out of scope (seed):** n-outcome ADVANCE fields; field underround (needs
  exhaustiveness). `find_dutch_books` consumes `df.to_dict("records")` so it is **NaN-safe**.

## Synthetic exact-score bundle detector — `synthetic_bundle.py` (do not regress)

A **separate, N-leg check family** (NO streamlit/pandas). A player wins their match iff one of the exact set
scores occurs — **best-of-5 {3-0,3-1,3-2}, best-of-3 {2-0,2-1}** — so that MECE set *replicates* "they win".
That bundle is priced against **TWO independent hedges**, emitted separately (`hedge_kind` ∈ `{match,
advance}`, distinct `opportunity_id`s): (1) the same match's **match-winner** market; (2) the
**advance / win-tournament** market at the node the match *implies* (`ladder.match_stage_to_node`: winning a
Quarterfinal ≡ Reach Semifinal, winning the Final ≡ Win Tournament — the `match_alignment` equivalence).
`find_synthetic_bundles(rows)` groups exact-score rows by event and by **`player_key` UUID** (NOT the display
name, which carries the scoreline subtitle).

- **NOT a dutch book / NOT true arbitrage.** An exact score is NOT the match-winner. On a retirement /
  no-ball-played the score legs settle to **Fair Market Price** while the hedge settles cleanly (verified
  live) — so EVERY finding carries `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, `tradable_now="Review rules"`,
  and is routed **review/blocked, NEVER Actionable**. Labels say **gross / top-of-book** (fees + full-depth
  fill not modeled). Conservative wording — never "riskless"/"locked"/"true arbitrage".
- **Two directions** (exact integer cents): **forward** = Buy YES every state + Buy NO hedge, fires when
  `Σ yes_ask(states) + no_ask(hedge) < 100¢`; **reverse** = Buy NO every state + Buy YES hedge, fires when
  `Σ no_ask(states) + yes_ask(hedge) < N×100¢` (N = number of states). Best firing direction wins.
- **Gates (any fail → silent skip, never a false positive):** (1) **format proven** — the expected state set
  comes from a verified signal (`expected_states`: division + tournament via `SportConfig.score_format_fn`;
  men's Grand Slam = bo5, WTA + non-Slam ATP = bo3 — **NOT keyed off ATP/WTA alone**), never from the
  discovered markets (else completeness is circular); (2) **exhaustive** — found set == expected set; (3)
  **hedge present + round aligned** — match hedge: same `stage`; advance hedge: the hedge's node ==
  `match_stage_to_node[score_stage]` (a round mismatch is a hard rules-conflict); (4) **firm ask per
  leg** (priced-but-no-size / inactive → emitted blocked/review, not dropped). Scoreline is read from the
  structured `custom_strike["Set Score"]` (verified live), regex-fallback on the subtitle.
- **Two hedge kinds (PR 27a):** the match hedge keeps the legacy 4-part `opportunity_id` recipe
  (`synthetic_bundle, event, player_key, direction`) so lifecycle tracking is continuous; the advance hedge
  uses a 6-part recipe (`…, "advance", node, direction`) and carries an **extra caveat**
  (`BLOCKERS["synthetic_settlement_advance"]`: a player can reach the next round on a walkover WITHOUT
  winning a match). `_advance_hedge_index` maps `player_key → {tournament → {node → advance/winner row}}`
  (tournament-keyed so a player's advance market in one tournament never hedges their match in another)
  via a local `_node_of` (mirrors `consistency.node_of`, kept local so the module stays pandas-free). The
  close-time safety gate for the advance hedge checks the **score legs only** — an advance market's
  scheduled `close_time` is the later stage's date but it settles on THIS match (verified live), so the
  score-vs-advance gap is expected; the binary + rule-token gates still span all legs.
- **Config:** `SportConfig.state_bundles` (format_key → per-player states) + `score_format_fn`, both DEFAULTED
  (NBA/WNBA empty) so adding a sport stays one `register()` call.
- **Engine wiring (mirrors dutch-book):** `scanner.unified_opportunities` calls `find_synthetic_bundles` and
  maps it via `_to_unified_synthetic`; the **N-leg plan lives in a `legs` list** (`legs`/`n_legs` added to
  `UNIFIED_COLUMNS` and the api.py `Opportunity` model — DECLARED so `extra="ignore"` doesn't drop them);
  `action_1/2_*` backfilled from the first two legs so 2-leg consumers keep working. Routing:
  `STATUS_GROUP["EXECUTABLE_SYNTHETIC_BUNDLE"]="Warning"` + a `bucket_of` branch (review/blocked, since
  `tradable_now="Review rules"` never starts with "Yes").
- **UI:** NiceGUI `explanation_lines`/leg-links iterate `legs`; synthetic-bundle findings route
  review/blocked in the NiceGUI dashboard tables (membership-filtered). Glossary term "Synthetic
  bundle" → "Bundle (all legs)" column. NaN-safe.

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

## UI — trader-first dashboard (NiceGUI; `webui/dashboard.py`)

The UI is the **NiceGUI dashboard** mounted on FastAPI via `serve.py` (the Streamlit `app.py` was
retired). Layout: display + scan controls, a filter row (Sport / Tournament / Participant / Min size /
Active-only / Review / Blocked toggles), the ranked **Actionable** table, **Review** + **Blocked**
(toggle-gated), the opt-in **Risk-budget** / **Near-miss** sections, a recently-actionable backlog, a
click-to-open explanation dialog + selected-participant detail panel, and a collapsed Diagnostics &
debug expander. `webui/viewmodel.py` (`opp_row`/`filter_opps`/`derive_options`/…) and
`webui/diagnostics.py` are the pure, testable cores.

**Filter split (critical — do not regress):** `consistency.bucket_of(row)` routes each comparison
(actionable / blocked / near_edge / display_signal / wide_signal / data_quality / clean). The same
two-pass `filters.py` split is reused in `webui/viewmodel.filter_opps`: **membership**
(sport/tournament/participant/min-volume) narrows **Actionable now and every section**, while
**thresholds** (min size, quote, **market status**) spare **Actionable now** but gate the others. Full
diagnostics is built from the membership-filtered set (NOT the thresholded set), so **finalized markets
stay visible there** even with Active-only as the default elsewhere. (Scope: "finalized" = markets with
`status=finalized` within events the API still returns as `status=open`; fully closed events are excluded
at the API level — `kalshi_client.get_events` passes `status="open"`.)

**Section order:** Actionable is always visible, **ranked best→worst**; Review/Blocked and the opt-in
Risk-budget/Near-miss sections follow; detail/diagnostics/debug are collapsed below.

(Historical: the retired Streamlit `app.py` used an `st.sidebar` control stack, `st.metric` cards, an
`@st.fragment(run_every=…)` auto-refresh, and a dedicated dutch-book section; the opportunity-ranking
bar chart was removed in Stage 0 as misleading — the Actionable table is the ranking surface.)

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
- **The running server caches imported modules.** After editing `data.py`/`consistency.py`/… while
  `python serve.py` is running, the change won't take effect — **fully stop and restart** `serve.py`
  (there is no auto-reload). For a phantom `ImportError`, clear stale bytecode too:
  `rm -rf __pycache__ tests/__pycache__`. (This already cost time once.)
- The FO date window in `config.py` is year-specific — update for future tournaments.
- The Kalshi **web** site (`kalshi.com`) is bot-throttled (HTTP 429), so automated link-reachability
  checks from this environment are unreliable (everything 429s — not a broken link). Links now point at
  the specific market via the verified deep-link format (see API section); `data.link_audit` proves
  link *correctness* (URL ↔ contract identifiers) deterministically, and `scripts/check_links.py` does a
  best-effort live reachability check meant to be run from your own (unthrottled) network.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` here-doc for multi-line commit/PR text. The PowerShell
  `@'...'@` here-string syntax **corrupts** messages when invoked through the Bash tool (it bit us twice —
  stray `@` characters). Reference code as `path:line`.
- Verify changes with `pytest -q` plus a `serve.py` boot (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, and `.claude/` (local settings — keep out of the repo).

## Git workflow (strict — owner confirmed)

- **Never commit or push to `main`.** The owner merges manually; you push branches and open PRs.
- Branch off the current `main` (now canonical). **Do not stack on unmerged branches** — a past stack
  caused a merge mess; one PR per change, based on `main`. Verify (`pytest -q`, `serve.py` boot) before pushing.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR bodies end with the Claude Code footer.

## Repository status

`main` has shipped the full engine + the NiceGUI front-end (the legacy Streamlit `app.py` was retired).
On main:

- All-tennis generalization + multi-sport abstraction (`sports.py`): Tennis, NBA, WNBA, golf, soccer via
  `SportConfig`; dutch-book / MECE detector (`dutchbook.py`) + synthetic exact-score bundles
  (`synthetic_bundle.py`).
- **Engine-behind-an-API:** SQLite snapshot store (`store.py`, v3 — opportunities + per-sport evidence
  frames), cross-sport `scanner.py`, lifecycle/alerts, a typed **FastAPI** REST API (`api.py`:
  `/healthz` `/readyz` `/opportunities` `/coverage` `/metrics` `/scan` `/alerts` …), non-blocking
  `POST /scan` behind a **ScanManager** singleflight + per-process HTTP rate-limit + env-gated `SCAN_TOKEN`.
- **NiceGUI dashboard** (`webui/`, mounted on FastAPI via `serve.py`) — the **sole UI**: ranked
  Actionable/Review/Blocked, participant-detail panel, diagnostics/debug with AG-Grids, truthful empty
  states, snapshot export, live freshness; pure `webui/viewmodel.py` + `webui/diagnostics.py` cores.
- **LAN go-live (PRs S1–S5 + D):** `/readyz` readiness, env `SNAPSHOT_DB_PATH`, NON-force "Scan now",
  Linux-first `docs/DEPLOYMENT.md`, a clean deploy-repo builder (`scripts/build_deploy_repo.py`) + `deploy/`
  systemd/timer/`scan.sh` templates, and dashboard UX defaults (Blocked hidden, persistent row highlight,
  resolution-criteria toggle, dark mode, a11y tooltips).

`pytest` is the full suite (`test_data`, `test_consistency`, `test_dutchbook`, `test_synthetic_bundle`,
`test_store`, `test_scanner`, `test_lifecycle`, `test_api`, `test_webui`, `test_viewmodel`,
`test_diagnostics`, `test_ratelimit`, `test_browser` [headless NiceGUI], …). All UNIFIED-PLAN Phase A–E PRs
are merged; Phase F shipped the advancement-hedge synthetic detector, the tournament-winner FIELD dutch
book, and the known-limits docs — only seed follow-ons (advancement-FIELD detector, field underround) remain.

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
13. **Multi-sport generalization** (`sports.py`): `SportConfig` abstraction with `IdentityResolver`,
    `LadderSpec`, `MarketClassification`; Tennis, NBA, and WNBA registered as first-class sports.
    `sport_for_series()` resolves any series ticker to its sport (explicit `UNKNOWN` when unrecognized —
    no silent tennis default). Engine (`data.py`, `consistency.py`) reads sport config off the registry;
    no sport name is hardcoded in the engine. NBA ladder: Reach Playoffs ⊇ Win Conference ⊇ Win
    Championship; WNBA ladder: Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship.
14. **Dutch-book / MECE detector** (`dutchbook.py`): `find_dutch_books()` detects executable arbitrage
    on 2-outcome MECE events — head-to-head matches/series (tennis, NBA/WNBA) AND per-game (`KX*GAME`)
    markets (milestone m1.1). Both underround (Buy YES both) and overround (Buy NO both) directions;
    dedicated dashboard section; `EXECUTABLE_DUTCH_BOOK` status. Per-game eligibility is sport-agnostic
    via the `"game"` family — tennis is unaffected (no game family in its config).
15. **Stage 0 dashboard clarity**: Lisbon default timezone + per-second freshness/coverage strip so data
    age is always visible; "Show IDs & codes" toggle collapses internal identifiers by default;
    opportunity-ranking bar chart removed (misleading; Actionable table is the ranking surface); debug +
    full diagnostics moved behind the Advanced expander. Forward plan (not yet built): engine-first
    architecture migrating UI from Streamlit → NiceGUI on FastAPI, with a SQLite snapshot store,
    cross-sport scanner, lifecycle/alerts, and a REST API (Stages 1–6; detail in `docs/ROADMAP.md`).
16. **MLB (7th sport)**: NBA-shape futures ladder (Reach Playoffs ⊇ Win League ⊇ Win World Series) +
    `KXMLBGAME` per-game dutch books, registered via a `SportConfig` drop. Adds a defaulted
    `SportConfig.winner_label` + makes `data._contract_label` sport-aware (winner via `winner_label`,
    advance prefers the ladder node → "Win League"/"Win Conference"/"Top 5"; also fixed latent NBA "Reach
    Conference" and golf "Reach Top 5"); a shared `data.non_other_families(cfg)` so the Streamlit cross-
    sport and `/scan` API fetch paths exclude the "Other" bucket identically; `time_kind="Game time"` for
    every `kind=="game"` row (NBA/WNBA/soccer/MLB); and `last_settlement_caveat` carried onto the
    recently-actionable backlog (lifecycle → `api.BacklogItem` → Streamlit table/CSV + NiceGUI).
17. **NHL (8th sport)**: NBA-shape futures ladder (Reach Playoffs ⊇ Win Conference ⊇ Win Championship) +
    `KXNHLSERIES` playoff-series AND `KXNHLGAME` per-game dutch books, registered via a `SportConfig` drop
    (identity `custom_strike.hockey_team`, `winner_label="Win the Stanley Cup"`), consuming the MLB
    cross-sport foundation. Two NHL-owned general fixes: `data.tournament_of` now **season-scopes** every
    non-tennis grouping key (`_season_token` → `· <season>`, so co-loaded seasons never form a false
    cross-season ladder; tennis byte-for-byte unchanged), and `dutchbook._detect_pair` adds a normalized
    **same-series guard** (both legs must share a series). Live `KXNHLSERIES` rounds ("1st/2nd Round") map
    to no ladder rung → `UNKNOWN_RELATIONSHIP`; NHL's value is the advance+winner ladder + series/game books.
