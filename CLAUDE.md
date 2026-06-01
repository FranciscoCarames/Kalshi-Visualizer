# CLAUDE.md

Guidance for **Claude Code** working in this repository. Self-contained — read top to bottom.

## Project

A small, **read-only** Streamlit app that reads live [Kalshi](https://kalshi.com) prediction-market
data for the **French Open** tennis tournament. You pick a player, see all of their French Open
contracts with transparent pricing, a **Layer Consistency Checker** flags when a deeper outcome prices
above a prerequisite that contains it, and — beneath the per-player ladder — **raw stage-ladder spreads**
show the price gaps between adjacent layers.

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer` (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Roadmap:** simple-first — see `kalshi-plan.md`. v1 is raw spreads; probability models / scenario
  trees / signals are an optional "expand later" menu, **not** committed scope.
- **Scope guard — do NOT add unless explicitly asked:** trading, authentication, order placement,
  historical storage, alerts, conditional-probability/de-vig models, or a generic all-sports engine.

## Run & verify

```bash
pip install -r requirements.txt          # runtime: streamlit, requests, pandas
streamlit run app.py
pip install -r requirements-dev.txt      # adds pytest
pytest -q                                # unit tests for the pure layers (no network)
```

To verify without a browser: `pytest -q`; `python -c "import app"`; and a headless boot —
`streamlit run app.py --server.headless true --server.port 8765` then check
`http://localhost:8765/_stcore/health` returns `200`. Live Kalshi calls, `pip`, and `git push` in this
environment require running the Bash tool with the sandbox disabled (network is otherwise blocked).

## Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Pagination via a `cursor` param — loop until it's empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `yes_bid_size_fp`/`yes_ask_size_fp`; volume `volume_fp`,
  `open_interest_fp`. An **empty order book is `0.00/1.00`** — never a real 50%.
- **Player identity:** `custom_strike.tennis_competitor` (stable UUID) is the join key across all series;
  `yes_sub_title` is the display name.
- **French Open filter:** event belongs to the FO when `product_metadata.competition` contains
  "french open" (fallbacks: title/rules keywords, then a date window). Match events are head-to-head
  (2 markets, `mutually_exclusive`); winner/advancement/set/score markets are single-sided (no opponent).

### Relevant per-player series
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH` / `KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXATPADVANCE` / `KXWTAADVANCE` | reach a stage (`…-26FOSF`, `…-26FOFIN`) | `advance` | Stage advancement |
| `KXFOMEN` / `KXFOWOMEN` | win the tournament (1 market/player) | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER` / `KXWTASETWINNER` | set winner | `set_winner` | Set winner |

The women's winner title is the ugly "win the KXFOWOMEN-26?" → synthesize "Win the French Open".

## Architecture

```
config.py          # BASE_URL, DEFAULT_SERIES, discovery prefixes, FO keywords/window, thresholds
kalshi_client.py   # read-only HTTP: paginated GET, retry/backoff, sized pool,
                   #   discover_tennis_series(), get_events_for_series() (concurrent + retry pass)
data.py            # NO streamlit: parsing, to_cents(), FO filtering, classify_kind/tour_of,
                   #   pricing helpers (yes_mid/spread/quote_quality/display_prob), build_contracts()
consistency.py     # NO streamlit: node_of, build_player_nodes, representative, expected_nodes,
                   #   layer_spreads, build_checks (the checker)
app.py             # Streamlit ONLY: consistency table + per-player detail; right-hand controls
tests/             # pytest: test_data.py, test_consistency.py    (conftest.py, requirements-dev.txt)
```

`data.py` and `consistency.py` MUST stay free of Streamlit imports (independently testable).

- **Default vs full scan:** default fetches `config.DEFAULT_SERIES` (6 core series, ~2s). A "Scan all
  tennis series" checkbox runs `discover_tennis_series()` (~61 series, ~20s). Series list cached ttl 3600;
  contracts cached ttl 60.
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source,
  mapping_confidence, mapping_reason, tour, kind, category, contract, stage, stage_rank, opponent,
  display_pct, yes_mid_pct, last_pct, yes_bid_pct, yes_ask_pct, spread_cents, quote_quality, yes_bid_c,
  yes_ask_c, last_c, display_c, yes_bid_size, yes_ask_size, volume, open_interest, status, time_value,
  time_kind, kalshi_url, series, event_ticker, market_ticker, event_title, market_title, raw_yes_bid,
  raw_yes_ask, raw_last, rules_primary`.

## Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last
  trade, else blank. A `0.00/1.00` book is "No quote" (never a fake 50%).
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote.
- Surface every component (mid / last / bid / ask / spread) so a price is never opaque.

## Layer Consistency Checker — hard rules (do not regress)

Containment ladder, broad → deep: `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`; a child (deeper)
price must be ≤ its parent (broader). Adjacent containment pairs use market contracts; **match-alignment**
pairs (`Quarterfinal win ≡ Reach Semifinal`, etc.) are included only when the round maps confidently.
Anything unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

- **Call findings "executable inconsistencies", NEVER "arbitrage."** True arbitrage also needs the two
  markets' settlement rules to match, which we don't auto-verify → match-alignment rows always carry
  `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` if a light `rules_primary` token compare differs).
- **All comparison logic in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.
- **Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
  positive sizes**; a missing display blocks only the display test.
- **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, sizes > 0) is the ONLY "Broken" status.**
  `DISPLAY_VIOLATION` is "Warning"; a sizeless price-cross → `QUOTE_SIZE_MISSING`, **unless the display
  prices also cross** (then `DISPLAY_VIOLATION`). Crossed books (`ask < bid`) → "Crossed" quality, never executable.
- Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
  QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
  WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown relationship=UNKNOWN_RELATIONSHIP.

**Known live test cases (women's draw):** Cirstea `Quarterfinal win ≡ Reach Semifinal` → `EXECUTABLE_VIOLATION`
(~2¢) flagged `RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display → `DISPLAY_VIOLATION`,
her early-round match → `UNKNOWN_RELATIONSHIP`; Gauff/Swiatek empty books → `MISSING_QUOTE`.

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

- **Group/select by `player_key`, not display name** (`build_checks` groups on key; the Player selector maps
  labels→keys, disambiguating `"Name [key6]"` only on collision) — two same-named players never merge.
- **Truthful evidence:** the `EXECUTABLE_VIOLATION` reason quotes the *winning* cross direction (equivalence
  checks forward and reverse).
- **Crossed books** (`ask < bid`) → `quote_quality == "Crossed"`: never Tight, never a midpoint, never fed to
  the executable test.
- **`tour_of`** classifies every `FO_WINNER_TICKERS` variant explicitly (`KXFOPENWMENSINGLE` → WTA).
- **No silent truncation:** `get_paginated` raises if `MAX_PAGES` (100) is hit with a cursor pending. *(PR #13)*
- **Deterministic duplicates:** `build_player_nodes` picks the representative by a stable rule; `duplicate_node_sources` surfaces it. *(PR #13)*
- **FO filter:** a present non-FO `competition` is disqualifying; date-window fallback only with no competition info. *(PR #13)*

## UI

`st.columns([3, 1])`: main area left, **controls panel right**. Controls: Refresh, Tournament radio
(Women/Men/Both, **default Women**), Scan-all checkbox, Contract type (**default Tournament winner +
Stage advancement**; enabling Match result adds alignment rows), Outcome status, Quote quality, Min
volume, Player. Main: consistency table (sorted Broken→Warning→Missing→Unknown→Clean; clean rows
filterable, never hidden); per-player detail = progression chain → raw ladder spreads → mapping
confidence + expected-vs-found → all contracts → export → debug expander. Tables only, no charts. Use
`width="stretch"` (the `use_container_width` arg is deprecated).

## Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`.
- Use `data.to_cents` (Decimal, exact) for any comparison logic — no float drift.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Empty results are valid (between rounds → no open events), not errors — handle gracefully.
- Always loop the `cursor` for pagination; the client raises if the `MAX_PAGES` cap is hit with a cursor
  still pending (no silent partial data).
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- **Streamlit caches imported modules in the running server.** After editing `data.py`/`consistency.py`/…,
  a browser "Rerun" won't pick it up — **fully stop and restart** `streamlit run app.py`. For a phantom
  `ImportError`, clear stale bytecode too: `rm -rf __pycache__ tests/__pycache__`. (This already cost time once.)
- The FO date window in `config.py` is year-specific — update for future tournaments.
- The Kalshi **web** site (`kalshi.com`) is bot-throttled (HTTP 429); row links point to the series page
  `https://kalshi.com/markets/<series>` as best effort.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` here-doc for multi-line commit/PR text. The PowerShell
  `@'...'@` here-string syntax **corrupts** messages when invoked through the Bash tool (it bit us twice —
  stray `@` characters). Reference code as `path:line`.
- Verify changes with `pytest -q` plus a headless Streamlit boot (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, and `.claude/` (local settings — keep out of the repo).

## Git workflow (strict — owner confirmed)

- **Never commit or push to `main`.** The owner merges manually; you push branches and open PRs.
- Branch off the current `main` (now canonical). **Do not stack on unmerged branches** — a past stack
  caused a merge mess; one PR per change, based on `main`. Verify (`pytest -q`, headless) before pushing.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR bodies end with the Claude Code footer.

## Repository status

`main` is **canonical and current** — full app (multi-contract discovery, transparent pricing, Layer
Consistency Checker), mapping-audit hardening, **v1 raw ladder spreads** (+ NaN-fix/Quote column), and the
**audit Tier-1 correctness fixes** are all merged (PRs #1, #4, #6, #7, #8, #9, #11, #12); `pytest` ~42.
**Pending: PR #13** — audit Tier-2 robustness (pagination-truncation surfacing, deterministic duplicates,
date-window corroboration). Older PRs #2/#3/#5 are closed/superseded.

## Iteration history (intent)
1. Per-player French Open match viewer.
2. All per-player FO contracts via dynamic series discovery.
3. Transparent pricing (Display % + components + quote quality), default core series, richer debug.
4. Layer Consistency Checker: containment + match-alignment, executable-vs-display, conservative rule flags.
5. Mapping-audit hardening (confidence + reasons, expected-vs-found, per-player export) + first tests.
6. v1 raw stage-ladder spreads beneath the ladder; NaN-safe + Quote column.
7. Audit hardening — Tier-1 (key-based grouping, truthful reasons, tour map, crossed-book guard, JSON
   safety) merged; Tier-2 (pagination/duplicate/date-window) in PR #13.
