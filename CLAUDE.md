# CLAUDE.md

Guidance for **Claude Code** working in this repository. Self-contained — read top to bottom.

## Project

A small, **read-only NiceGUI trader dashboard** (on FastAPI, via `serve.py`) over live
[Kalshi](https://kalshi.com) prediction-market data for **tennis (ATP/WTA), NBA, WNBA, golf, soccer,
MLB, NHL, motorsport (F1/NASCAR/IndyCar/MotoGP), NFL, and esports** — 10 sports. It surfaces **executable
inconsistencies** across a participant's related contracts (a deeper outcome must not price above a
prerequisite that contains it) and **dutch-book arbitrage** on MECE events, as buy-only opportunities
(**Buy YES / Buy NO**), ranked Actionable / Review / Blocked with collapsed diagnostics and
per-participant detail. A background scan refreshes a SQLite snapshot store under a process-wide rate
throttle. The **React "Kalshi Structured Scanner" SPA** (`frontend/`, built to `frontend/dist`) is the
**default UI at `/`**; the legacy NiceGUI dashboard is **retained (not deleted) at `/dashboard`** as a
read-only fallback. (The older Streamlit `app.py` was retired.) Both are read-only views of the same
engine — the SPA reads it solely through `GET /api/terminal/feed` (+ thin `/api/terminal/*` parity views).

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer`
  (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Scope guard — do NOT add unless explicitly asked:** trading, order placement,
  conditional-probability/de-vig models, net-of-fees math. Adding a **new sport** is in scope via a
  `SportConfig` drop-in; non-sport-config work is not. **Per-user authentication is now IN SCOPE**
  (owner-requested 2026-06) — app-level login over the read-only surface, gated behind `AUTH_ENABLED`;
  see `docs/AUTH.md` (`auth_store.py`/`auth.py`/`manage_users.py`). It must NOT alter engine logic.

## NEVER EVER DO

These rules are ABSOLUTE:

### NEVER Publish Sensitive Data
- NEVER publish passwords, API keys, tokens to git/npm/docker
- Before ANY commit: verify no secrets included

### NEVER Commit .env Files
- NEVER commit `.env` to git
- ALWAYS verify `.env` is in `.gitignore`

## Workflow docs

Specialized review/workflow guidance lives in separate files — link to them, don't inline their content here:

- **`AGENTS.md`** — operating guide for Codex and other `AGENTS.md`-aware reviewers.
- **`docs/REVIEW_PROTOCOL.md`** — shared review protocol: plan reviews, diff reviews, risk classes,
  verdicts, blockers, missing tests, current-doc checks, conservative labeling.
- **`docs/PR_CHECKLIST.md`** — required pre-merge checklist before opening or marking a PR ready.
- **`docs/AGENT_WORKFLOW.md`** — day-to-day workflow for Claude Code, Codex, multiple
  terminals/worktrees, WIP limits, stale plans, and documentation-size rules.

Claude Code follows `docs/AGENT_WORKFLOW.md` before creating new plans and `docs/PR_CHECKLIST.md` before
handing work back. Do not add long workflow procedures here — link to the specialized docs instead.

## Multi-sport (`sports.py`)

`sports.py` defines a `SportConfig` abstraction (`IdentityResolver`, `LadderSpec`,
`MarketClassification`); `sport_for_series()` resolves a series ticker to its config, returning the
explicit `UNKNOWN` sport when unrecognized — **never a silent tennis default**. Adding a sport = one
`register(SportConfig(...))` call. `build_contracts` includes **all events for all registered sports**;
ladders group by **(player_key, tournament)** per sport. Tournament is a client-side filter.
`data.tournament_of` **season-scopes** every non-tennis grouping key (`_season_token` → `· <season>`,
so co-loaded seasons never form a false cross-season ladder; tennis byte-for-byte unchanged).
`SportConfig.winner_label` gives the winner family per-sport wording ("Win the World Series" / "Win the
Stanley Cup" / default "Win the tournament").

| Sport | Identity | match_family | Ladder (broad→deep) / notes |
|---|---|---|---|
| Tennis | `tennis_competitor` UUID | `match` | Reach SF ⊇ Reach Final ⊇ Win Tournament |
| NBA | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Win Conference ⊇ Win Championship; `KX*GAME` games |
| WNBA | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Reach SF ⊇ Reach Finals ⊇ Win Championship; games |
| Golf | `golf_competitor` UUID | `""` (no dutch books) | `exact_series` Top20 ⊇ Top10 ⊇ Top5 ⊇ Win |
| Soccer | `soccer_team` UUID | `""` (3-way games) | `exact_series` `KXWCGAME` (Home/Away/Tie dutch books) + `KXWCROUND`/`KXWCGROUPQUAL` advance ladder Reach RO32 (=group qualifier) ⊇ RO16 ⊇ QF ⊇ SF ⊇ Final ⊇ Win the World Cup (outright = `KXMENWORLDCUP`, live-verified 2026-06-10; `KXWC`/`KXMWORLDCUP` have no open events). Plus `KXWCGROUPWIN` (win-group leaf), `KXWCGROUPQUAL`/`KXWCGROUPBOTTOM` cardinality baskets, `KXWCGROUPORDER` exact-order diagnostics, `KXWCSTAGEOFELIM` 7-bucket stage-of-elimination book (tail-sum layer Review-only), and 9 recognized-but-excluded `KXWC*` props (`_SOCCER_KNOWN_OTHER`) |
| MLB | `baseball_team` UUID | `""` | Reach Playoffs ⊇ Win League ⊇ Win World Series; `KXMLBGAME` games. `KXMLBSERIES` excluded as non-MECE (can tie 2-2) |
| NHL | `hockey_team` UUID | `match` | Reach Playoffs ⊇ Win Conference ⊇ Win Stanley Cup; `KXNHLSERIES` (clean bo7) + `KXNHLGAME` dutch books. Live series wording "1st/2nd Round" → no rung → `UNKNOWN_RELATIONSHIP` |
| Motorsport | multi-path (driver UUID / team UUID / constructor NAME), role-namespaced `player_key` | `""` | **field sport like golf**; one-winner FIELDS → overround; Top-N/Podium → finishing-position ladder |
| NFL | `football_team` UUID | `""` | Reach Playoffs (`KXNFLPLAYOFF`) ⊇ Win Conference (`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`) ⊇ Win Super Bowl (`KXSB` winner field → overround); `KXNFLGAME` games are tie-capable → `game_mece_by_shape=False` gates the dutch book on `dutchbook._proves_fixed_sum` ($0.50-tie / no-tie proof). Props/totals/spreads/division/awards/draft → `other` |
| Esports | `esports_competitor` UUID | `""` | **field sport, NO ladder (v1)**; `exact_series` curated allow-list across CS2/LoL/Valorant/Dota2/CoD/R6/… `KX*GAME`+`KX*MAP` are 2-way DRAW-FREE → `"game"` family → ungated dutch books (`game_mece_by_shape=True`); per-title winner series (`KXCS2`, …) → overround. `divisions` per title. Totalmaps/qualifiers/props/legacy/dupes/event-majors → `other` (unowned → UNKNOWN, never fetched). Qualifier ladders / opponent labels / tag discovery = v2 |

Identity is `custom_strike.<key>`. Classification is an **allow-list** (`family_fn`), not a bare prefix —
MLB/NHL/motorsport lookalikes & props → `other`. Motorsport: `field_families`
(winner/race_winner/pole/fastest_lap/constructor/team) get the overround; Top-N/Podium → a per-competition
`ladder_fn`; grouping is per RACE INSTANCE (`tournament_key_fn` → `competition · session · token`);
`player_key` is role-namespaced so a constructor sharing the driver UUID path never merges.

## Run & verify

```bash
pip install -r requirements.txt          # runtime: requests, pandas, fastapi, nicegui, uvicorn
cd frontend && npm install && npm run build && cd ..   # build the default SPA UI → frontend/dist
python serve.py                          # SPA (/) + NiceGUI dashboard (/dashboard) + REST API, one app
pip install -r requirements-dev.txt      # adds pytest, pytest-asyncio, ruff
pytest -q                                # pure layers + in-process engine/API + headless NiceGUI smoke
ruff check .                             # lint
```

Verify without a browser: `pytest -q`; `python -c "import serve, api, webui.dashboard"`; a `serve.py`
boot — `GET /` (SPA), `/dashboard/` (NiceGUI), `/healthz`, `/metrics` → 200, `/readyz` →
`ready`/`degraded`/`not_ready`. The SPA is served from `frontend/dist` only when built (gitignored
artifact); an unbuilt tree leaves `/` unmounted but never breaks boot. Headless
NiceGUI smoke is `tests/test_browser.py` (`nicegui.testing`, no selenium). Live Kalshi calls, `pip`, and
`git push` need the Bash tool with the sandbox disabled (network is otherwise blocked).

**LAN hosting (do not regress):** `serve.py` serves the API + dashboard on one app (default loopback
`127.0.0.1:8000`); `API_HOST`/`API_PORT`/`SNAPSHOT_DB_PATH` are env-overridable. A non-loopback bind
**requires** `NICEGUI_STORAGE_SECRET` (`serve.bind_safety` fail-hard, no auth — escape
`ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`) and warns on `WEB_CONCURRENCY>1` (store + throttle are
process-local). `POST /scan` is **non-blocking** (202) behind a process-local `scan_manager.ScanManager`
singleflight (shared with `webui.run_scan_now` → one upstream fetch); `?wait`/`?force` modify it,
`GET /scan/status` polls; the dashboard "Scan now" is **non-force**. Full runbook + deploy artifact
(`scripts/build_deploy_repo.py`, `deploy/`): `docs/DEPLOYMENT.md`.

## Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Paginate via `cursor` until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `*_size_fp`; volume `volume_fp`, `open_interest_fp`. An
  **empty book is `0.00/1.00`** — never a real 50%.
- **NO-side prices** (`no_bid_dollars`, `no_ask_dollars`) read directly (the "Buy NO" price); `no_ask ==
  1 − yes_bid` on the unified book. There are **no NO-side size fields** — a Buy-NO leg's tradable size
  is `yes_bid_size`; fallback Buy-NO cents = `100 − yes_bid_c` when `no_ask_c` is absent.
- **Market `status`** (`active`/`finalized`/`settled`/…): only `active` is tradable → drives `tradable_now`.
- **Web URL (verified):** `https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`,
  `slug = data._slugify(series.title)`; titles from `/series/<ticker>`
  (`kalshi_client.get_series_titles`), falling back to the series page when missing.
- **Identity:** the stable `custom_strike.*` UUID is the per-sport join key; `yes_sub_title` is the display name.

### Relevant tennis series
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH`/`KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXITFMATCH`/`KXITFWMATCH` | ITF lower-tour match winner (exact-owned) | `match` | Match result |
| `KXATPADVANCE`/`KXWTAADVANCE` | reach a stage | `advance` | Stage advancement |
| `KXFOMEN`/`KXFOWOMEN` | win the tournament | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER`/`KXWTASETWINNER` | set winner | `set_winner` | Set winner |

Match events are head-to-head (2 markets, `mutually_exclusive`); winner/advance/set/score are
single-sided. NBA/WNBA/MLB/NHL/golf/soccer/motorsport series are fully configured in `sports.py`.

## Architecture (module map)

```
config.py        # BASE_URL, DEFAULT_SERIES, prefixes, thresholds, rate-limit + refresh knobs
sports.py        # SportConfig registry + sport_for_series (no UI imports)
kalshi_client.py # read-only paginated GET, Retry-After/backoff, process-wide throttle, discovery
data.py          # parsing, to_cents, classify_kind/tour_of, pricing, tournament_of, build_contracts, fmt_time/age/stale
consistency.py   # nodes, representative, expected_nodes, layer_spreads, build_checks (groups [player_key,tournament]),
                 #   buy-only plan + tradable_now + blockers, bucket_of
dutchbook.py     # find_dutch_books — MECE detector (2-way / soccer n-way / winner field); EXECUTABLE_DUTCH_BOOK
synthetic_bundle.py # find_synthetic_bundles — N-leg exact-score bundle vs 2 hedges; EXECUTABLE_SYNTHETIC_BUNDLE
glossary.py      # GLOSSARY{short,long}, BLOCKERS, WATCHLIST_NOTE, help_for — single-sourced terms
filters.py       # apply_membership / apply_thresholds — the two-pass filter split
viz.py           # payoff_chart_data + ladder_prices (tidy chart frames)
fetch.py         # load_contracts (fetch-by-family) extracted from the old app
scanner.py       # cross-sport unified_opportunities (dutch-book + synthetic + containment)
store.py         # SQLite snapshot store (v3: opportunities + per-sport evidence frames); no pandas import
lifecycle.py     # new / changed / recently-actionable diffs over the store
scan_manager.py / scan_scheduler.py / presence.py / ratelimit.py  # singleflight, background loop, viewer gate, limiter
api.py           # FastAPI: /healthz /readyz /opportunities /coverage /metrics /scan /alerts /backlog
serve.py         # entrypoint: FastAPI API + NiceGUI dashboard on one app — the SOLE UI
webui/           # NiceGUI dashboard.py + pure viewmodel.py / diagnostics.py / engine.py / export.py
scripts/         # build_deploy_repo, check_links, export_glossary (→ docs/GLOSSARY.md, on demand), verify_sport, benchmark_scan
tests/           # pytest: full suite (pure layers + engine + API + viewmodel + headless browser)
```

`sports.py`, `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` MUST stay free of UI
imports (no `nicegui`, no `streamlit`) — pure logic, independently testable.

- **Fetch by family (do not regress):** `fetch.py` (from the old `app.load_contracts`) pulls ONLY the series whose contract family is enabled (`data.series_for_families`) — **family toggles are the only control that changes what's fetched**. The hosted scan path `api.fetch_dep()` → core series only (`scan_all=False`; `True` would widen via `discover_tennis_series()`).
- **Auto-refresh (do not regress):** the dashboard reads the persisted snapshot store; a process-local `scan_scheduler` runs background scans on a timer (on by default — `config.AUTO_SCAN_DEFAULT_ENABLED`, every `AUTO_SCAN_DEFAULT_SECONDS`), and the browser re-reads the latest snapshot on a `ui.timer`.
- **Rate limiting (free tier):** Kalshi Basic read ≈ 20 req/s. `kalshi_client._throttle` caps issuance at `config.MAX_RPS` (15, ~75%); `_get` backs off on 429 (honoring `Retry-After` when present) via `MAX_RETRIES`/`BACKOFF_*`; fan-out `CONCURRENCY` (4). **The throttle is PROCESS-WIDE ONLY** — safe for ONE process; N processes each have their own limiter (aggregate = `MAX_RPS × N`).
- **Contract row (`build_contracts`), key fields:** identity (`player`, `player_key`, `player_key_source`, `mapping_confidence`, `mapping_reason`), classification (`tour`, `kind`, `category`, `contract`, `stage`, `stage_rank`, `opponent`, `tournament`, `tournament_source`), pricing (`*_pct`, `*_c` cents, `*_size`, `spread_cents`, `quote_quality`, `subpenny`), `volume`, `open_interest`, `status`, `time_value`/`time_kind`, links (`kalshi_url`, `series`, `*_ticker`, `*_title`), `raw_*`, `rules_primary`.

## Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last
  trade, else blank. A `0.00/1.00` book is "No quote" (never a fake 50%). Surface every component (mid /
  last / bid / ask / spread) so a price is never opaque.
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote / Crossed.
- **Known limits (single-sourced in `glossary.py` "Known limits"):** every edge is **GROSS and
  TOP-OF-BOOK**. Three costs are documented, NOT modeled, until the owner opts in — **fees** (never
  netted; "gross-only" ≠ "ignore fees"), **position limits / collateral**, and **full-depth execution**.
  Treat edges as an upper bound.

## Layer Consistency Checker — hard rules (do not regress)

Containment ladder broad→deep; a child (deeper) price must be ≤ its parent (broader). Adjacent
containment pairs use market contracts; **match-alignment** pairs (`Quarterfinal win ≡ Reach Semifinal`)
only when the round maps confidently. Unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

- **Call findings "executable inconsistencies", NEVER "arbitrage."** Settlement rules aren't
  auto-verified → match-alignment rows carry `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` on a light
  `rules_primary` token diff).
- **Buy-only language (do not regress):** every opportunity is two BUYS — **Buy YES** broader/parent,
  **Buy NO** deeper/child — never "sell"/"long"/"short". `_classify` emits `action_1_*`/`action_2_*` (+
  `tradable_now`, `blockers`, `watchlist_note`); the Buy-NO price is the real `no_ask_c` (fallback
  `100 − yes_bid_c`). `tradable_now` is "Yes" only for `EXECUTABLE_VIOLATION` + both legs `active` + no
  rule flag ("Yes — rule-dependent" for equivalence). **`WIDE_QUOTE` gets no action.** Blocker/glossary
  text is single-sourced from `glossary.py`.
- **All comparison logic in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.
- **Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
  positive sizes**; a missing display blocks only the display test.
- **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, sizes > 0) is the ONLY "Broken" status.**
  `DISPLAY_VIOLATION` is "Warning"; a sizeless cross → `QUOTE_SIZE_MISSING`, **unless the display prices
  also cross** (then `DISPLAY_VIOLATION` — AUDIT-002). Crossed books (`ask < bid`) → "Crossed", never
  executable.
- Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
  QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
  WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown=UNKNOWN_RELATIONSHIP.
  (For repeatable assertions use the unit tests, not live data.)

## Dutch-book / MECE detector — `dutchbook.py` (do not regress)

A **separate check family** from the containment ladder. A dutch book covers EVERY outcome of a MECE set
for under the guaranteed payout floor. **2-outcome** = head-to-head match/game (floor 100¢);
**n-outcome** = soccer 3-way (Home/Away/Tie via `prove_mece`); **winner field** = ≥3 "win" markets.
`find_dutch_books` dispatches soccer → `_detect_n_way`, winner fields → `_detect_field`, else the 2-way
`_detect_pair`; ≤1 finding/event; consumes `df.to_dict("records")` so it is **NaN-safe**.

- **Two directions, both pairs of BUYS** (never "sell"): **underround** Buy YES all (`Σ yes_ask < 100`);
  **overround** Buy NO all (`Σ no_ask < (n−1)·100`, with the `100 − yes_bid` fallback). Mutually
  exclusive (`bid ≤ ask`) → only one fires. Exact integer cents.
- **Sport-agnostic via `_is_two_way_row`:** eligible families are the sport's `match_family` AND the
  `"game"` family (`KX*GAME`). Props/winner/advance are not two-way → ignored; `UNKNOWN` sport excluded.
  `_detect_pair` enforces a normalized **same-series guard** (both legs must share a series).
- **Tie-capable games (do not regress):** `game_mece_by_shape=False` (NFL — games can tie) GATES the
  `"game"` book on `dutchbook._proves_fixed_sum` (exact proof a tie pays `$0.50`/side → 100¢ floor holds,
  or no tie possible); unproven ⇒ skipped, basis stamped on the finding. Default `True` = identical elsewhere.
- **One status `EXECUTABLE_DUTCH_BOOK`** carrying `tradable_now` + `blockers`. Routing is the only
  `consistency.py` touch (`bucket_of` + a `STATUS_GROUP` entry; the status string is a guarded literal).
  **Conservative wording — never "riskless"/"locked"/"true arbitrage"** (single-sourced via
  `glossary.DUTCH_BOOK_BASIS`): a **gross two-way pricing discrepancy under normal one-winner
  settlement**. A **per-game (`KX*GAME`) book carries a non-blocking postponement `settlement_caveat`**
  (`BLOCKERS["game_settlement"]`) — advisory, never changes `tradable_now`/bucket.
- **Winner FIELD is overround-only** (`prove_field_mece` sets `exhaustive=False`): MECE-but-not-exhaustive, safe on any priceable subset (`_field_overround_subset`: firm no-side + `yes_bid>0`) since an untraded winner only pays more. `gap = Σ yes_bid(subset) − 100`; the id keys on the EVENT; non-blocking `field_overround` caveat. **Out of scope (seed):** advance fields; field underround (needs exhaustiveness).

## Synthetic exact-score bundle — `synthetic_bundle.py` (do not regress)

A **separate N-leg family** (no UI/pandas). A player wins iff one of the MECE set scores occurs (bo5
{3-0,3-1,3-2} / bo3 {2-0,2-1}) — that bundle *replicates* "they win", priced against **TWO independent
hedges** (`hedge_kind ∈ {match, advance}`, distinct `opportunity_id`s): the match-winner market, and the
advance/win-tournament node the match implies (`ladder.match_stage_to_node`). Grouped by event + by
**`player_key` UUID** (not the display name).

- **NOT a dutch book / NOT true arbitrage.** A score ≠ the match-winner; on a retirement the score legs
  settle to Fair Market Price while the hedge settles cleanly → EVERY finding carries
  `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, `tradable_now="Review rules"`, routed **review/blocked, NEVER
  Actionable**. Gross / top-of-book; never "riskless"/"locked"/"true arbitrage".
- **Two directions** (exact cents): forward = Buy YES states + Buy NO hedge (`Σ yes_ask(states) + no_ask(hedge) < 100`); reverse = Buy NO states + Buy YES hedge (`Σ no_ask(states) + yes_ask(hedge) < N×100`). Best direction wins.
- **Gates (any fail → silent skip):** (1) **format proven** from `SportConfig.score_format_fn` (men's
  Grand Slam bo5, WTA + non-Slam ATP bo3 — NOT keyed off ATP/WTA alone), never from discovered markets;
  (2) **exhaustive** (found == expected); (3) **hedge present + round aligned** (match: same `stage`;
  advance: hedge node == `match_stage_to_node[score_stage]`); (4) **firm ask per leg** (else
  blocked/review, not dropped). Scoreline from `custom_strike["Set Score"]`, regex-fallback on the subtitle.
- **Two hedge kinds:** the match hedge keeps the 4-part `opportunity_id`; the advance hedge uses a 6-part
  recipe + an extra caveat (`BLOCKERS["synthetic_settlement_advance"]`: a walkover advances without a
  match win). `_advance_hedge_index` is tournament-keyed; the advance close-time gate checks score legs only.
- **Config + engine:** `SportConfig.state_bundles` + `score_format_fn`, both DEFAULTED (empty for
  non-tennis). `scanner.unified_opportunities` → `_to_unified_synthetic`; the N-leg plan lives in a
  `legs` list (`legs`/`n_legs` in `UNIFIED_COLUMNS` + the `api.Opportunity` model); `action_1/2_*`
  backfilled. Routing `STATUS_GROUP["EXECUTABLE_SYNTHETIC_BUNDLE"]="Warning"` + a `bucket_of` branch.

## Mapping audit & robustness invariants (do not regress)

- **Mapping confidence:** `build_contracts` stamps `mapping_confidence` ("high" = stable UUID; "low" =
  name fallback) + `mapping_reason`. No downstream row without `kind` + confidence.
- **Expected-vs-found:** `consistency.expected_nodes` makes a missing ladder layer explicit; the detail
  view exports a JSON snapshot + CSV.
- **Raw stage-ladder spreads:** `consistency.layer_spreads` returns per-adjacent-pair `spread_pct` (pp)
  and `spread_cents` (broader − deeper) — raw prices, not a probability model; reuse
  `consistency.representative`; `missing_layer` vs `missing_price` are both NaN-safe; a `quote` (worst
  leg) column; `inverted` is None-safe.
- **Group/select by `player_key`, not display name** (`build_checks` on `(player_key, tournament)`) — two
  same-named players never merge, and one player's tournaments never merge. `data.tournament_of` returns a
  **never-empty** key (cleaned `competition` → winner-ticker → title keyword → `Unknown · <id>`, with
  `tournament_source`) so a fallback never collapses to `""`.
- **Truthful evidence:** the `EXECUTABLE_VIOLATION` reason quotes the *winning* cross direction. **`tour_of`** classifies every `FO_WINNER_TICKERS` variant explicitly.
- **No silent truncation:** `get_paginated` raises if `MAX_PAGES` (100) is hit with a cursor pending. **Deterministic duplicates:** `build_player_nodes` picks a representative by a stable rule (`duplicate_node_sources` surfaces it).

## UI — NiceGUI dashboard (`webui/dashboard.py`)

The **sole UI**, mounted on FastAPI via `serve.py`. Layout: display + scan controls, a filter row
(Sport / Tournament / Participant / Min size / Active-only / Review / Blocked), the ranked **Actionable**
table, **Review** + **Blocked** (toggle-gated), opt-in **Risk-budget** / **Near-miss** sections, a
recently-actionable backlog, a click-to-open explanation dialog + participant detail panel, and a
collapsed Diagnostics & debug expander. `viewmodel.py` + `diagnostics.py` are the pure cores.

- **Filter split (critical — do not regress):** `consistency.bucket_of(row)` routes each comparison;
  `webui/viewmodel.filter_opps` reuses the two-pass `filters.py` split — **membership**
  (sport/tournament/participant/min-volume) narrows **every section**; **thresholds** (min size, quote,
  market status) spare **Actionable** but gate the others. Full diagnostics is built from the
  membership-filtered set (NOT the thresholded set) so **finalized markets stay visible** there. (Fully
  closed events are excluded at the API level — `get_events` passes `status="open"`.)
- **Section order:** Actionable is always visible, **ranked best→worst**; Review/Blocked + opt-in
  sections follow; detail/diagnostics/debug collapsed below.
- **Status display labels** (no "Potential edge"; "edge" only for a positive executable gap):
  `EXECUTABLE_VIOLATION`→"Actionable gross edge", `DISPLAY_VIOLATION`→"Display inconsistency",
  `WIDE_QUOTE`→"Wide quote / watchlist", `MISSING_QUOTE`→"Missing firm quote",
  `QUOTE_SIZE_MISSING`→"Blocked: no size", `CLEAN`→"Consistent". Internal status strings are unchanged.

## Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`
  (Decimal, exact) for any comparison logic.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Empty results are valid (between rounds → no open events), not errors.
- Always loop the `cursor`; the client raises on the `MAX_PAGES` cap with a cursor pending.
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- **The running server caches imported modules.** After editing a module while `serve.py` runs, **fully
  stop and restart** (there is no auto-reload); for a phantom `ImportError` clear bytecode too:
  `rm -rf __pycache__ tests/__pycache__`.
- The FO date window in `config.py` is year-specific — update it for future tournaments.
- The Kalshi **web** site is bot-throttled (429), so live link-reachability checks are unreliable here;
  `data.link_audit` proves link *correctness* deterministically, and `scripts/check_links.py` does a
  best-effort live check meant to run from an unthrottled network.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` for multi-line commit/PR text. PowerShell `@'...'@`
  here-strings corrupt messages through the Bash tool (stray `@`). Reference code as `path:line`.
- Verify with `pytest -q` + a `serve.py` boot (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, `*.db`, `.claude/`, `.kss/`.

## Git workflow (strict — owner confirmed)

- **Never commit, push, or merge to `main`.** The owner merges manually.
- **Branch-only delivery (near-term policy, owner 2026-06-09 — supersedes "one PR per change"):** do NOT
  open a PR per change. Implement the **full scope** of a work item across **one or more feature branches**;
  verify (`pytest -q`, `ruff check .`, `serve.py` boot); then hand the branch back. The owner **tests
  manually** and **merges to `main` only when satisfied**. `main` stays frozen until then.
- Branch off the latest `main` — or, since `main` is frozen, off the unmerged branch a feature depends on
  (state the base in the handoff). Keep verifying before handing back; commits on the branch are fine.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  If a PR is opened for review, its body ends with the Claude Code footer.

## Status & history

Shipped state, current limits, and the approved next-work list live in **`docs/STATUS.md`**. Detailed
build history and decisions live in `.kss/` (topics + milestones). `pytest` is the full suite (pure
layers + engine + API + viewmodel + per-sport `test_*` + headless `test_browser`).

