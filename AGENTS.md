# AGENTS.md

Operating guide for **Codex** (and other AGENTS.md-aware coding agents) in this repository.
Self-contained — everything you need is here.

## Project overview

A small, **read-only** Streamlit **trader dashboard** over live [Kalshi](https://kalshi.com)
prediction-market data for **tennis** (generalized from the French Open). It surfaces **executable
inconsistencies** across a participant's related contracts (a deeper outcome must not price above a
prerequisite that contains it), in buy-only terms (**Buy YES / Buy NO**), split into Actionable /
Blocked / Near-edge sections with collapsed diagnostics, per-player detail, and debug. It auto-refreshes
on a timer under a process-wide request throttle, and groups containment ladders by
**(player, tournament)**.

- **Owner / GitHub:** FranciscoCarames. Repo `Kalshi-Visualizer` (private), default branch `main`.
- **OS:** Windows 11 (PowerShell), Python 3.13.
- **Generalization (shipped):** no French-Open gate — all tennis events are included, each stamped with
  a never-empty `tournament` key (`data.tournament_of`); tournament is a client-side filter.
- **Out of scope (do not implement unless explicitly requested):** trading, authentication, order
  placement, historical/time-series storage, alerts, conditional-probability/de-vig models, and
  **non-tennis** sports (tennis generalization is in scope; other sports are not yet).

## Setup & run

```bash
pip install -r requirements.txt        # runtime: streamlit, requests, pandas
streamlit run app.py
pip install -r requirements-dev.txt    # adds pytest (tests only)
```

## Testing / verification

There **is** a test suite now (added with the mapping-audit work). Before committing:

1. **Tests:** `pytest -q` — pure-layer unit tests, no network (`test_data`, `test_consistency`,
   `test_glossary`, `test_client`, `test_filters`, `test_viz`). ~94 tests (pricing, consistency
   precedence + (player,tournament) grouping, tournament derivation, filters, throttle/backoff, charts).
2. **Compile:** `python -m py_compile config.py kalshi_client.py data.py consistency.py filters.py viz.py app.py`
3. **Headless boot / AppTest:** `python -m streamlit run app.py --server.headless true --server.port 8765`
   → `/_stcore/health` = `200`, no tracebacks. Or `streamlit.testing.v1.AppTest.from_file("app.py").run()`
   and assert `not at.exception` (exercises the auto-refresh fragment + filters). Use `python -m streamlit`
   (the bare `streamlit` shim isn't executable under the Bash tool).

Network egress may be sandboxed; live Kalshi calls, `pip`, and `git push` need network access enabled.
`api.kalshi.com` does not resolve — use `external-api.kalshi.com`.

## Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2` (NOT `api.kalshi.com`).
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Pagination via a `cursor` query param; loop until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); order sizes `yes_bid_size_fp`/`yes_ask_size_fp`; volumes
  `volume_fp`, `open_interest_fp`. An **empty order book is `0.00/1.00`** — not a real 50%.
- **Player identity:** `custom_strike.tennis_competitor` is a stable per-player UUID — the join key across
  all series; `yes_sub_title` is the display name.
- **NO-side prices** exist (`no_bid_dollars`/`no_ask_dollars`); `no_ask == 1 − yes_bid` exactly, no
  NO-side size fields. **Market `status`** (`active`/`finalized`/…) is the "tradable now" signal.
- **Tournament grouping (generalized):** `build_contracts` includes ALL tennis events (no FO gate) and
  stamps a never-empty `tournament` key + `tournament_source` via `data.tournament_of` (cleaned
  `competition` → winner-ticker → title keyword → `Unknown · <id>`). `build_checks` groups by
  `(player_key, tournament)`. Match events are head-to-head (2 markets, `mutually_exclusive`);
  winner/advancement/set/score markets are single-sided (no opponent). `is_french_open_event` remains a
  helper, not a gate.

### Relevant per-player series
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH` / `KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXATPADVANCE` / `KXWTAADVANCE` | reach a stage (`…-26FOSF`, `…-26FOFIN`) | `advance` | Stage advancement |
| `KXFOMEN` / `KXFOWOMEN` | win the tournament (1 market/player) | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER` / `KXWTASETWINNER` | set winner | `set_winner` | Set winner |

The women's winner market title is literally "win the KXFOWOMEN-26?" → synthesize "Win the French Open".

## Architecture

```
config.py          # BASE_URL, DEFAULT_SERIES, discovery prefixes, thresholds, rate-limit
                   #   (MAX_RPS/CONCURRENCY/BACKOFF_*) and refresh (REFRESH_TTL/OPTIONS/NEAR_EDGE_MIN_C) knobs
kalshi_client.py   # read-only HTTP: paginated GET, Retry-After/exponential backoff, process-wide
                   #   throttle (MAX_RPS), discover_tennis_series(), get_series_titles(), get_events_for_series()
data.py            # NO streamlit/pandas: parsing, to_cents(), classify_kind/tour_of, pricing helpers,
                   #   tournament_of()->(key,source), series_for_families(), kalshi_market_url(), build_contracts()
consistency.py     # NO streamlit: build_player_nodes, representative, expected_nodes, layer_spreads,
                   #   build_checks (groups by [player_key, tournament]); buy-only action plan,
                   #   tradable_now, blockers, bucket_of (dashboard routing)
glossary.py        # NO streamlit: GLOSSARY{term:{short,long}}, BLOCKERS, WATCHLIST_NOTE, help_for
filters.py         # NO streamlit: apply_membership / apply_thresholds — the two-pass filter split
viz.py             # NO streamlit: opportunity_ranking (tidy frame for the ranking bar chart)
app.py             # Streamlit ONLY: sidebar, auto-refresh fragment, dashboard sections, Altair chart
tests/             # pytest: test_data, test_consistency, test_glossary, test_client, test_filters, test_viz
```

- **Layering rule:** `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` must not import
  Streamlit (all UI in `app.py`); `data.py` also must not import pandas.
- **Fetch by family:** `load_contracts(families, scan_all)` fetches ONLY the enabled families' series
  (`series_for_families`) — the only control that changes what's fetched. `scan_all` (default ON) widens
  to all tennis via `discover_tennis_series()`; else `DEFAULT_SERIES`. Tournament/event/participant
  filters are client-side. Series list cached 1h; contracts cached `config.REFRESH_TTL` (30s).
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source,
  mapping_confidence, mapping_reason, tour, kind, category, contract, stage, stage_rank, opponent,
  competition, tournament, tournament_source, display_pct, …, yes_bid_c, yes_ask_c, last_c, display_c,
  yes_bid_size, yes_ask_size, no_bid_pct, no_ask_pct, no_bid_c, no_ask_c, volume, open_interest, status,
  time_value, time_kind, kalshi_url, series, event_ticker, market_ticker, event_title, market_title,
  raw_yes_bid, raw_yes_ask, raw_no_bid, raw_no_ask, raw_last, rules_primary`.

## Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last trade,
  else blank. A `0.00/1.00` book is "No quote" (never a synthesized 50%).
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote.
- Always expose every component (mid / last / bid / ask / spread) so prices are auditable.

## Layer Consistency Checker — invariants (must hold)

Containment ladder, broad → deep: `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`; a child (deeper) price
must be ≤ its parent (broader). Adjacent containment pairs use market contracts; **match-alignment** pairs
(`Quarterfinal win ≡ Reach Semifinal`, `Semifinal win ≡ Reach Final`, `Final win ≡ Win Tournament`) are
included only when the round maps confidently. Anything unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

1. **Terminology:** findings are "executable inconsistencies", **never "arbitrage."** Match-alignment rows
   always carry `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` if a light `rules_primary` token compare differs),
   because the two markets' settlement rules are not auto-verified.
2. **Exact integer cents** for all comparison logic (`data.to_cents`, `Decimal`). Floats only for display.
3. **Executable and display tests are independent.** Executable requires firm `yes_bid_c`/`yes_ask_c` **and
   positive sizes**; a missing display blocks only the display test (and vice versa).
4. **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask with positive sizes) is the ONLY "Broken" status.**
   `DISPLAY_VIOLATION` is a "Warning". A sizeless price-cross → `QUOTE_SIZE_MISSING`, **unless the
   display prices also cross** (then `DISPLAY_VIOLATION`). Malformed crossed books (`ask < bid`) are
   "Crossed" quality and never feed the executable test or a display midpoint.
5. Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
   QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
   WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown relationship=UNKNOWN_RELATIONSHIP.

**Known live cases to assert (women's draw):** Cirstea `Quarterfinal win ≡ Reach Semifinal` →
`EXECUTABLE_VIOLATION` (~2¢) flagged `RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display →
`DISPLAY_VIOLATION`, her early-round match → `UNKNOWN_RELATIONSHIP`; Gauff/Swiatek empty books → `MISSING_QUOTE`.

## Mapping audit & per-player export

- `data.build_contracts` stamps every row with `mapping_confidence` ("high" = keyed to the stable
  `tennis_competitor` UUID; "low" = name fallback) + a `mapping_reason`. No downstream layer should consume
  a row lacking `kind` + confidence.
- `consistency.expected_nodes(player_rows)` returns the **expected-vs-found** progression ladder so a
  missing layer is explicit, not implied-by-omission.
- The player-detail view offers a **per-player export** (JSON snapshot + CSV) of the contracts and their
  consistency comparisons for offline mapping review.

## Raw stage-ladder spreads (v1, shipped)

`consistency.layer_spreads(player_rows)` returns, for each adjacent ladder pair, the **raw price gap**:
`spread_pct` = percentage-**point** difference, `spread_cents` = cents difference (broader − deeper). These
are **raw spreads, not a probability model** — no conditional probabilities, no de-vig. Rules:

- Reuse `consistency.representative(node_entry)` (market source else match) — the **single** price-row
  selector shared by the progression chain and the spreads; do not duplicate source-selection logic.
- Distinguish **`missing_layer`** (node absent) from **`missing_price`** (node present, no usable display
  price). Both checks are **NaN-safe** (a `None` price round-trips to float NaN via `to_dict("records")`).
- The row carries a `quote` field (worst of the two legs' quality) — most ladder legs are illiquid, so the
  UI shows a Quote column; trust mainly Tight/OK rows.
- `inverted` is None-safe (true only when `spread_pct` is a real number < 0); an inverted spread is the same
  inconsistency the consistency table flags.
- In the UI the pp gap is labelled **"pp"** (layer prices stay "%"). The spread table sits **directly beneath**
  the progression-chain ladder (do not replace the ladder).

## Correctness & robustness invariants (audit hardening — do not regress)

- **Group/select by `player_key`, never display name.** `build_checks` groups on `player_key`; the app's
  Player selector maps display labels → keys (disambiguating `"Name [key6]"` only on collision). Two
  competitors who share a display name must never be merged.
- **Truthful evidence.** The `EXECUTABLE_VIOLATION` reason quotes the *winning* cross direction (equivalence
  checks both forward and reverse); never describe a reverse cross with forward legs.
- **Malformed quotes.** `ask < bid` → `quote_quality == "Crossed"`: never Tight, never a midpoint
  (`yes_mid`/`spread`/`display_*` return None), and `_leg` excludes it from the executable test.
- **Tour map.** `data.tour_of` classifies every `FO_WINNER_TICKERS` variant explicitly (e.g.
  `KXFOPENWMENSINGLE` → WTA), not by substring.
- **No silent truncation.** `get_paginated` raises `KalshiError` if `MAX_PAGES` is hit with a cursor pending
  (`MAX_PAGES=100` so the full `/series` list paginates). *(PR #13)*
- **Deterministic duplicates.** When >1 row maps to the same (node, source), `build_player_nodes` picks by a
  stable rule (usable price → higher volume → smaller ticker); `duplicate_node_sources` surfaces it. *(PR #13)*
- **FO filter.** A present-but-non-FO `competition` is disqualifying; the date-window fallback only fires when
  there is no competition info at all. *(PR #13)*

## UI conventions

**Controls in `st.sidebar`; main page full width.** Order: Refresh, **Contract family** (default ALL,
read before the fetch — *only this changes what's fetched*), then Tour (default Both), Tournament
(multiselect), Auto-refresh+interval, **Market universe** (one merged **Participant** selectbox that
also drives the detail section; Event + Stage/layer multiselects), **Thresholds** (Min available size,
Quote, **Market status = Active only** by default), **Sections** toggles, **Advanced — data scope LAST**
(Scan-all default ON via session-state read-ahead; Min traded volume; Show explanations).

**Two-pass filtering (`filters.py`):** `apply_membership` (tournament/family/layer/event/participant/
volume) narrows ALL sections incl. Actionable; `apply_thresholds` (size/quote/market-status) narrows
all EXCEPT Actionable. **Full diagnostics is built from the membership `universe` (not thresholds) +
Outcome-status**, so finalized markets stay visible there despite Active-only default. `bucket_of`
routes each comparison to a section.

**Main:** header → 6 metric cards + Export expander → **Actionable now** (always visible, sorted by
gross edge ↓; "Buy YES"/"Buy NO" cols) → **opportunity-ranking Altair bar** → Blocked / Near-edge
(toggled) → collapsed Watchlist-signals / Data-quality / Player-detail / Full-diagnostics / Debug.
Use `width="stretch"` on `st.dataframe` and `st.altair_chart` (`use_container_width` is deprecated).
Charts are allowed (the ranking bar); status wording avoids "Potential edge" ("edge" = positive
executable gap only).

## Code style

- Python 3.13, `from __future__ import annotations`; type hints on public functions; module + function docstrings.
- Standard library + `requests`, `pandas`, `streamlit` (+ `altair`, which ships with Streamlit, for the
  one ranking chart; `pytest` dev) only. No new top-level deps without owner sign-off.
- Pure logic (`data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py`) stays Streamlit-free.
- **Never `float()` a raw price string** — use `data.to_float` (None-safe) or `data.to_cents` (Decimal, exact).
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Handle empty results gracefully (between rounds → no open events is valid, not an error).
- **Surface failed series in the Debug expander — never silently drop them** (hard requirement).

## Commit & PR instructions

- **Never commit or push to `main`.** The owner merges manually. Branch off `main` (now canonical — see
  below), commit, push, open a PR. **Do not stack on unmerged branches** (a past stack caused a merge mess);
  one PR per change, based on current `main`.
- Before committing: run the verification checks above (`pytest -q`, `py_compile`, headless boot).
- Commit messages: imperative subject + a short body explaining the why; append a `Co-Authored-By:` trailer.
- For multi-line commit/PR text on Windows, prefer a heredoc or `--body-file` over inline quoting.
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, `.claude/`. Never commit secrets; data needs none.

## Repository status

`main` is **canonical and current** through the trader-dashboard, auto-refresh, and market-filter work
(merged via PRs up to #18). On top of that, the **all-tennis generalization + sidebar cleanup + ranking
chart** work is in progress on a feature branch (data-layer generalization, fetch-by-family, the
restructured sidebar, and the Altair ranking chart). `pytest` ~94. Owner merges PRs manually.

## Iteration history (intent)
1. Per-player French Open match viewer.
2. All per-player FO contracts via dynamic series discovery.
3. Transparent pricing (Display % + components + quote quality), richer debug.
4. Layer Consistency Checker: containment + match-alignment, executable-vs-display, conservative rule flags.
5. Mapping-audit hardening (confidence + reasons, expected-vs-found, per-player export) + first tests.
6. v1 raw stage-ladder spreads; NaN-safe + Quote column.
7. Audit hardening (key-based grouping, truthful reasons, tour map, crossed-book guard, pagination/
   duplicate/date-window).
8. Buy-only action plan: real NO prices, verified deep links, `tradable_now` + blockers, glossary.
9. Trader-first dashboard (sidebar controls, Actionable/Blocked/Near-edge on top, diagnostics collapsed,
   `bucket_of`; "Potential edge" removed).
10. Auto-refresh (`st.fragment(run_every)`) + process-wide throttle + `Retry-After`/exponential backoff.
11. Market-universe + threshold sidebar filters (`filters.py`, two-pass; thresholds spare Actionable).
12. Generalized to all tennis (`tournament_of`, grouping by player+tournament, fetch-by-family), sidebar
    cleanup (merged participant, Active-only default w/ finalized still in diagnostics, Advanced last),
    Actionable ranked by edge, opportunity-ranking chart (`viz.py` + Altair).

## Gotchas

- `api.kalshi.com` does not resolve — always `external-api.kalshi.com`.
- **Streamlit caches imported modules in the running server.** After editing an imported module
  (`data.py`/`consistency.py`/…), a browser "Rerun" won't pick it up — **fully stop and restart**
  `streamlit run app.py`. For a phantom `ImportError`, also clear stale bytecode: `rm -rf __pycache__
  tests/__pycache__` (PowerShell `Remove-Item -Recurse -Force __pycache__, tests\__pycache__`).
- The Kalshi web frontend (`kalshi.com`) is bot-throttled (HTTP 429) — automated link checks from a
  server give false negatives. Per-row links use the verified deep-link format
  `kalshi.com/markets/<series>/<slug>/<event>` (`data.kalshi_market_url`, slug from the series title)
  with a series-page fallback; `data.link_audit` + tests prove construction, and `scripts/check_links.py`
  is a local (unthrottled) reachability check.
- The FO date window in `config.py` is only used by the `is_french_open_event` helper (no longer a gate)
  and is year-specific; `tournament_of` derives the tournament key for all tennis.
- Windows line-ending warnings (LF→CRLF) on commit are harmless.
