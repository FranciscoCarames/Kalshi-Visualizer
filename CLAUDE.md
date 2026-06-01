# CLAUDE.md

Guidance for **Claude Code** working in this repository. Self-contained — read top to bottom.

## Project

A small, **read-only** Streamlit app that reads live [Kalshi](https://kalshi.com) prediction-market
data for the **French Open** tennis tournament. You pick a player, see all of their French Open
contracts with transparent pricing, and a **Layer Consistency Checker** flags when a deeper outcome
prices above a prerequisite that contains it.

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer` (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Scope guard — do NOT add unless explicitly asked:** trading, authentication, order placement,
  historical storage, alerts, or a generic all-sports engine. This stays a read-only French Open viewer.

## Run & verify

```bash
pip install -r requirements.txt    # streamlit, requests, pandas
streamlit run app.py
```

To verify a change without a browser: run the data/consistency layer in a one-off `python -c …`, and
boot the app headless — `streamlit run app.py --server.headless true --server.port 8765` then check
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
kalshi_client.py   # read-only HTTP: paginated GET, retry/backoff, sized connection pool,
                   #   discover_tennis_series(), get_events_for_series() (concurrent + retry pass)
data.py            # NO streamlit: parsing, FO filtering, classify_kind/tour_of, build_contracts();
                   #   pricing helpers (yes_mid/spread/quote_quality/display_prob), to_cents()
consistency.py     # NO streamlit: node_of/build_player_nodes/classify/build_checks (the checker)
app.py             # Streamlit ONLY: main consistency table + player detail; right-hand controls
```

`data.py` and `consistency.py` MUST stay free of Streamlit imports (independently testable).

- **Default vs full scan:** default fetches `config.DEFAULT_SERIES` (6 core series, ~2s). A "Scan all
  tennis series" checkbox runs `discover_tennis_series()` (~61 series, ~20s). Series list cached ttl 3600;
  contracts cached ttl 60.
- **Contract row (build_contracts), partial schema:** `player, player_key, player_key_source, tour, kind,
  category, contract, stage, stage_rank, opponent, display_pct, yes_mid_pct, last_pct, yes_bid_pct,
  yes_ask_pct, spread_cents, quote_quality, yes_bid_c, yes_ask_c, last_c, display_c, yes_bid_size,
  yes_ask_size, volume, open_interest, status, time_value, time_kind, kalshi_url, series, event_ticker,
  market_ticker, event_title, market_title, raw_yes_bid, raw_yes_ask, raw_last, rules_primary`.

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
  `DISPLAY_VIOLATION` is "Warning"; a price cross without size → `QUOTE_SIZE_MISSING`.
- Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
  QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
  WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown relationship=UNKNOWN_RELATIONSHIP.

**Known live test cases (women's draw):** Cirstea `Quarterfinal win ≡ Reach Semifinal` → `EXECUTABLE_VIOLATION`
(~2¢) flagged `RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display → `DISPLAY_VIOLATION`,
her early-round match → `UNKNOWN_RELATIONSHIP`; Gauff/Swiatek empty books → `MISSING_QUOTE`.

## UI

`st.columns([3, 1])`: main area left, **controls panel right**. Controls: Refresh, Tournament radio
(Women/Men/Both, **default Women**), Scan-all checkbox, Contract type (**default Tournament winner +
Stage advancement**; enabling Match result adds alignment rows), Outcome status, Quote quality, Min
volume, Player. Main: consistency table (sorted Broken→Warning→Missing→Unknown→Clean; clean rows
filterable, never hidden) + per-player detail (chain, all contracts, debug expander with reasons). Use
`width="stretch"` (the `use_container_width` arg is deprecated).

## Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`.
- Use `data.to_cents` (Decimal, exact) for any comparison logic — no float drift.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Empty results are valid (between rounds → no open events), not errors — handle gracefully.
- Always loop the `cursor` for pagination (the client caps pages as a backstop).
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- The FO date window in `config.py` is year-specific — update for future tournaments.
- The Kalshi **web** site (`kalshi.com`) is bot-throttled (HTTP 429); row links point to the series page
  `https://kalshi.com/markets/<series>` as best effort.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` here-doc for multi-line commit/PR text. The PowerShell
  `@'...'@` here-string syntax **corrupts** messages when invoked through the Bash tool (it has bitten us
  twice — stray `@` characters). Reference code as `path:line`.
- Verify changes by running the data layer headless and a headless Streamlit boot (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, and `.claude/` (local settings — keep out of the repo).

## Git workflow (strict — owner confirmed)

- **Never commit or push to `main`.** The owner merges manually; you push branches and open PRs.
- Each iteration → a **new feature branch** (stacked on the previous unmerged branch so it includes prior
  work), commit there, push, open a **PR**.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR bodies end with the Claude Code footer.

### Branch / PR history (stacked — merge in order #1 → #2 → #3)
- `main` — initial commit (basic match viewer).
- PR #1 `feat/all-player-contracts` → main: all per-player FO contracts via dynamic discovery.
- PR #2 `feat/contract-display-and-defaults` → #1: price-component columns, default core series, debug.
- PR #3 `feat/layer-consistency-checker` → #2: the consistency checker (latest code).

> The latest app code lives on `feat/layer-consistency-checker` until the PRs merge; `main` is still the
> initial viewer. `consistency.py` and the cent-exact fields exist only on that branch so far.

## Iteration history (intent)
1. Per-player French Open match viewer.
2. All per-player FO contracts via dynamic series discovery.
3. Transparent pricing (Display % + components + quote quality), default core series, richer debug.
4. Layer Consistency Checker: containment + match-alignment, executable-vs-display, conservative rule flags.
