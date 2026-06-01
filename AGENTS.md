# AGENTS.md

Operating guide for **Codex** (and other AGENTS.md-aware coding agents) in this repository.
Self-contained — everything you need is here.

## Project overview

A small, **read-only** Streamlit app that reads live [Kalshi](https://kalshi.com) prediction-market
data for the **French Open** tennis tournament. It lets a user pick a player, view all of their French
Open contracts with a transparent price breakdown, and runs a **Layer Consistency Checker** that flags
when a deeper outcome prices above a prerequisite that logically contains it.

- **Owner / GitHub:** FranciscoCarames. Repo `Kalshi-Visualizer` (private), default branch `main`.
- **OS:** Windows 11 (PowerShell), Python 3.13.
- **Out of scope (do not implement unless explicitly requested):** trading, authentication, order
  placement, historical/time-series storage, alerts, generic multi-sport support.

## Setup commands

```bash
pip install -r requirements.txt    # streamlit, requests, pandas
streamlit run app.py               # launches the app in a browser
```

There is no build step and no separate dependency manifest beyond `requirements.txt`.

## Testing / verification

There is no formal test suite. Verify changes with these checks before committing:

1. **Compile:** `python -m py_compile config.py kalshi_client.py data.py consistency.py app.py`
2. **Data + consistency layer** (pure, no UI) — run a one-off script that calls
   `kalshi_client.get_events_for_series([...])`, `data.build_contracts(...)`, and
   `consistency.build_checks(df)`, and assert the known live cases below.
3. **Headless app boot:** `streamlit run app.py --server.headless true --server.port 8765`, then confirm
   `http://localhost:8765/_stcore/health` returns `200` and the logs show no tracebacks.

Network egress may be sandboxed in some environments; live Kalshi calls, `pip`, and `git push` need
network access enabled. `api.kalshi.com` does not resolve — use `external-api.kalshi.com`.

## Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2` (NOT `api.kalshi.com`).
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Pagination via a `cursor` query param; loop until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); order sizes `yes_bid_size_fp`/`yes_ask_size_fp`; volumes
  `volume_fp`, `open_interest_fp`. An **empty order book is `0.00/1.00`** — not a real 50%.
- **Player identity:** `custom_strike.tennis_competitor` is a stable per-player UUID — the join key across
  all series; `yes_sub_title` is the display name.
- **French Open filter:** an event is FO when `product_metadata.competition` contains "french open"
  (fallbacks: title/rules keywords, then a date window). Match events are head-to-head (2 markets,
  `mutually_exclusive`); winner/advancement/set/score markets are single-sided (no opponent).

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
config.py          # BASE_URL, DEFAULT_SERIES, discovery prefixes, FO keywords/window, thresholds
kalshi_client.py   # read-only HTTP: paginated GET, retry/backoff, sized connection pool,
                   #   discover_tennis_series(), get_events_for_series() (concurrent + sequential retry)
data.py            # NO streamlit: parsing, FO filtering, classify_kind/tour_of, build_contracts();
                   #   pricing helpers (yes_mid/spread/quote_quality/display_prob), to_cents()
consistency.py     # NO streamlit: node_of/build_player_nodes/classify/build_checks (the checker)
app.py             # Streamlit ONLY: main consistency table + player detail; right-hand controls
```

- **Layering rule:** `data.py` and `consistency.py` must not import Streamlit; all UI lives in `app.py`.
- **Default vs full scan:** default fetches `config.DEFAULT_SERIES` (6 core series, ~2s). A "Scan all tennis
  series" checkbox runs `discover_tennis_series()` (~61 series, ~20s). Series list cached 1h; contracts 60s.
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source, tour, kind,
  category, contract, stage, stage_rank, opponent, display_pct, yes_mid_pct, last_pct, yes_bid_pct,
  yes_ask_pct, spread_cents, quote_quality, yes_bid_c, yes_ask_c, last_c, display_c, yes_bid_size,
  yes_ask_size, volume, open_interest, status, time_value, time_kind, kalshi_url, series, event_ticker,
  market_ticker, event_title, market_title, raw_yes_bid, raw_yes_ask, raw_last, rules_primary`.

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
   `DISPLAY_VIOLATION` is a "Warning". A price cross with a missing/zero size → `QUOTE_SIZE_MISSING`.
5. Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
   QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
   WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown relationship=UNKNOWN_RELATIONSHIP.

**Known live cases to assert (women's draw):** Cirstea `Quarterfinal win ≡ Reach Semifinal` →
`EXECUTABLE_VIOLATION` (~2¢) flagged `RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display →
`DISPLAY_VIOLATION`, her early-round match → `UNKNOWN_RELATIONSHIP`; Gauff/Swiatek empty books → `MISSING_QUOTE`.

## UI conventions

`st.columns([3, 1])`: main area left, **controls panel right**. Controls: Refresh, Tournament radio
(Women/Men/Both, default Women), Scan-all checkbox, Contract type (default Tournament winner + Stage
advancement; enabling Match result adds alignment rows), Outcome status, Quote quality, Min volume, Player.
Main: consistency table (sorted Broken→Warning→Missing→Unknown→Clean; clean rows filterable, never hidden)
plus per-player detail (progression chain, all contracts, debug expander with reasons). Use `width="stretch"`
on `st.dataframe` (`use_container_width` is deprecated).

## Code style

- Python 3.13, `from __future__ import annotations`; type hints on public functions; module + function docstrings.
- Standard library + `requests`, `pandas`, `streamlit` only. No new dependencies without owner sign-off.
- Pure logic (`data.py`, `consistency.py`) stays import-free of Streamlit.
- **Never `float()` a raw price string** — use `data.to_float` (None-safe) or `data.to_cents` (Decimal, exact).
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Handle empty results gracefully (between rounds → no open events is valid, not an error).
- **Surface failed series in the Debug expander — never silently drop them** (hard requirement).

## Commit & PR instructions

- **Never commit or push to `main`.** The owner merges manually. Create a feature branch, commit, push,
  open a PR. New work stacks on the latest unmerged branch so it includes prior iterations.
- Before committing: run the verification checks above and ensure `py_compile` passes.
- Commit messages: imperative subject + a short body explaining the why. Append a `Co-Authored-By:` trailer
  for the authoring agent.
- For multi-line commit/PR text on Windows, prefer a heredoc or `--body-file` over inline quoting.
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`. Never commit secrets; market data needs none.

### Branch / PR history (stacked — merge in order #1 → #2 → #3)
- `main` — initial commit (basic match viewer).
- PR #1 `feat/all-player-contracts` → main: all per-player FO contracts via dynamic discovery.
- PR #2 `feat/contract-display-and-defaults` → #1: price-component columns, default core series, debug.
- PR #3 `feat/layer-consistency-checker` → #2: the consistency checker (latest code).

> Note: the latest application code (incl. `consistency.py` and the cent-exact fields) lives on
> `feat/layer-consistency-checker` until these PRs merge; `main` currently holds only the initial viewer.

## Gotchas

- `api.kalshi.com` does not resolve — always `external-api.kalshi.com`.
- The Kalshi web frontend (`kalshi.com`) is bot-throttled (HTTP 429); per-row links point to the series
  page `https://kalshi.com/markets/<series>` as a best-effort link.
- The French Open date window in `config.py` is year-specific — update for future tournaments.
- Windows line-ending warnings (LF→CRLF) on commit are harmless.
