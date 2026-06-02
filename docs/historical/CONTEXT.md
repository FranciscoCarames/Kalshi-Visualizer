# CONTEXT.md — Kalshi Visualizer: full project context

A single, comprehensive context dump for this project: what it is, how it's built, every
decision and why, the hard-won gotchas, the full PR history, and where things stand. For the
concise tool-facing guides see `AGENTS.md` (Codex) and `CLAUDE.md` (Claude Code); for the roadmap
see `kalshi-plan.md`. This file is the narrative/handoff superset.

---

## 1. Snapshot

A small, **read-only** Streamlit app over public [Kalshi](https://kalshi.com) prediction-market
data for the **French Open** tennis tournament. You pick a player and see **all** their French Open
contracts (match result, stage advancement, tournament winner; opt-in: set winner, exact score) with
a transparent price breakdown; a **Layer Consistency Checker** flags when a deeper outcome prices
above a prerequisite that contains it; and beneath the per-player ladder, **raw stage-ladder spreads**
show the price gaps between adjacent layers.

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo **`Kalshi-Visualizer`** (private), default branch `main`.
- **Origin story:** started from a `.env` with a Kalshi API key + RSA key, but the app only needs
  **public market data (no auth)**, so the credentials were removed and the scope is read-only.
- **Today:** core app + consistency checker + mapping audit + v1 spreads + audit hardening are merged;
  Tier-2 robustness (PR #13) and a guides refresh (PR #14) are pending. ~42 `pytest` tests.

## 2. Environment & tooling

- **OS:** Windows 11, PowerShell (primary). A Bash tool is also available.
- **Python:** 3.13. Deps: `streamlit`, `requests`, `pandas` (runtime); `pytest` (dev, in `requirements-dev.txt`).
- **Network:** the agent sandbox blocks egress by default — live Kalshi calls, `pip`, and `git push`
  need the sandbox disabled. `google.com` resolves; **`api.kalshi.com` does NOT** (use `external-api`).
- **GitHub:** authenticated via `gh` CLI as FranciscoCarames; pushes over HTTPS.

## 3. Read-only scope guard (hard rule)

No trading, authentication, order placement, account/portfolio access, historical/time-series storage,
alerts, probability/de-vig models, or generic multi-sport support — **unless the owner explicitly
lifts the guard**. Market data is public; nothing here needs a key. `.gitignore` pre-empts `.env`,
`*.pem`, `.streamlit/secrets.toml`, `__pycache__/`, `.claude/`.

## 4. Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. `api.kalshi.com` does not resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Auth/RSA signing is only for trading.
- **Hierarchy:** Series → Event → Market(outcome). **Pagination** via a `cursor` query param; loop until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026 the legacy integer-cent fields were removed):
  `yes_bid_dollars`, `yes_ask_dollars`, `no_*`, `last_price_dollars` (e.g. `"0.6500"`); order sizes
  `yes_bid_size_fp`/`yes_ask_size_fp`; volumes `volume_fp`, `open_interest_fp`. An **empty order book is
  `0.00/1.00`** — not a real 50%.
- **Player identity:** `custom_strike.tennis_competitor` is a **stable per-player UUID** — the join key
  across every series; `yes_sub_title` is the display name.
- **French Open filter:** an event is FO when `product_metadata.competition` contains "french open"
  (fallbacks: title/rules keywords; then a date window only if no competition info at all). Match events
  are head-to-head (2 markets, `mutually_exclusive`); winner/advancement/set/score markets are
  single-sided (`yes_sub == no_sub`, no opponent). Women's winner market title is the unhelpful "win the
  KXFOWOMEN-26?" → we synthesize "Win the French Open".

**Relevant per-player series:**

| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH` / `KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXATPADVANCE` / `KXWTAADVANCE` | reach a stage (events `…-26FOSF`, `…-26FOFIN`) | `advance` | Stage advancement |
| `KXFOMEN` / `KXFOWOMEN` | win the tournament (1 market/player) | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER` / `KXWTASETWINNER` | set winner | `set_winner` | Set winner |

## 5. Architecture

```
config.py          # BASE_URL, DEFAULT_SERIES, discovery prefixes, FO_WINNER_TICKERS, FO keywords/window, thresholds
kalshi_client.py   # read-only HTTP: paginated GET, retry/backoff, sized connection pool,
                   #   discover_tennis_series(), get_events_for_series() (concurrent + sequential retry pass)
data.py            # NO streamlit: parsing (to_float/to_cents), FO filtering, classify_kind/tour_of,
                   #   pricing helpers (yes_mid/spread/quote_quality/display_prob/display_cents), build_contracts()
consistency.py     # NO streamlit: node_of, build_player_nodes, representative, expected_nodes,
                   #   layer_spreads, duplicate_node_sources, _classify, build_checks
app.py             # Streamlit ONLY: main consistency table + per-player detail; right-hand controls
tests/             # pytest: test_data.py, test_consistency.py     (conftest.py makes root importable; requirements-dev.txt)
README.md, AGENTS.md, CLAUDE.md, kalshi-plan.md, CONTEXT.md (this)
```

- **Layering rule (do not break):** `data.py` and `consistency.py` import no Streamlit; all UI is in `app.py`.
- **Default vs full scan:** default fetches `config.DEFAULT_SERIES` (6 core series, ~2s); a "Scan all
  tennis series" checkbox runs `discover_tennis_series()` (~61 series, ~20s). Series list cached ~1h,
  contracts 60s. Fetches use `with_nested_markets=true` to avoid N+1.

## 6. Data model & contract-row schema

One row per player-per-market (`build_contracts`). Fields (partial):
`player, player_key, player_key_source, mapping_confidence, mapping_reason, tour, kind, category,
contract, stage, stage_rank, opponent, competition, display_pct, yes_mid_pct, last_pct, yes_bid_pct,
yes_ask_pct, spread_cents, quote_quality, yes_bid_c, yes_ask_c, last_c, display_c, yes_bid_size,
yes_ask_size, volume, open_interest, status, time_value, time_kind, kalshi_url, series, event_ticker,
market_ticker, event_title, market_title, raw_yes_bid, raw_yes_ask, raw_last, rules_primary`.

- `player_key` = competitor UUID when present (`player_key_source="competitor_uuid"`, `mapping_confidence="high"`),
  else the casefolded name (`"name_fallback"`, `"low"`). `*_c` are exact integer cents (Decimal-parsed).
- `time_value`/`time_kind`: match contracts show occurrence ("Match time"); others show close/expiration.

## 7. Pricing model

- **Display %** = YES midpoint when the spread is "reasonable" (`SPREAD_REASONABLE = 0.20`), else the last
  trade, else blank. An empty `0.00/1.00` book → "No quote" (never a synthesized 50%).
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote / **Crossed**
  (`ask < bid`, malformed). Crossed/empty books never produce a midpoint.
- Every component (mid / last / bid / ask / spread, in % and cents) is surfaced so prices are auditable.
- **Liquidity reality:** advancement/winner markets are mostly illiquid — on live data ~95% of ladder
  pairs have a No-quote/wide leg, so most display prices come from stale last trades. The UI exposes
  quote quality so the few trustworthy (Tight/OK) numbers stand out.

## 8. Layer Consistency Checker (the core analytical feature)

Containment ladder, broad → deep: `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`; a child (deeper)
price must be ≤ its parent (broader). Comparisons:
- **Adjacent containment** (market contracts): `Win Tournament ≤ Reach Final`, `Reach Final ≤ Reach Semifinal`.
- **Match alignment** (equivalence, only when the round maps confidently): `Quarterfinal win ≡ Reach
  Semifinal`, `Semifinal win ≡ Reach Final`, `Final win ≡ Win Tournament`.
- Anything unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

**Invariants (do not regress):**
1. Findings are **"executable inconsistencies", never "arbitrage"** — true arbitrage needs the two
   markets' settlement *rules* to match, which we don't auto-verify, so match-alignment rows carry
   `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` if a light `rules_primary` token compare differs).
2. **Exact integer cents** for all comparison logic; floats only for display.
3. **Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
   positive sizes**; a missing display blocks only the display test.
4. **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, positive sizes) is the ONLY "Broken" status.**
   `DISPLAY_VIOLATION` is a "Warning". A sizeless price-cross → `QUOTE_SIZE_MISSING`, **unless display also
   crosses** (then `DISPLAY_VIOLATION` — decided, see §17 AUDIT-002).
5. Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
   QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
   WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown=UNKNOWN_RELATIONSHIP.

**Known live test cases (women's draw):** Cirstea `Quarterfinal win ≡ Reach Semifinal` → `EXECUTABLE_VIOLATION`
(~2¢) flagged `RULE_MISMATCH`; Sabalenka Reach Final > Reach Semifinal on display → `DISPLAY_VIOLATION`;
her early-round match → `UNKNOWN_RELATIONSHIP`; Gauff/Swiatek empty books → `MISSING_QUOTE`.

## 9. v1 — raw stage-ladder spreads

`consistency.layer_spreads(player_rows)`: per adjacent pair, `spread_pct` (percentage **points**) and
`spread_cents` (broader − deeper). **Raw spreads, not a probability model.** Reuses `representative()`
(market else match — the single shared price-row selector, also used by the chain). Distinguishes
`missing_layer` (node absent) from `missing_price` (node present, no usable display price); both NaN-safe.
A `quote` field (worst leg) drives a Quote column. `inverted` (negative spread) cross-references the
consistency table. UI: pp gap labelled "pp"; the spread table sits **directly beneath** the ladder
(the ladder view is preserved, not replaced). Tables only, no charts.

## 10. Mapping audit & per-player export

`mapping_confidence`/`mapping_reason` on every row; `expected_nodes()` shows an explicit
expected-vs-found ladder; the per-player detail offers a **JSON snapshot + CSV export** of contracts and
their consistency comparisons. `duplicate_node_sources()` surfaces duplicate node/source collisions in
the debug expander. **Failed series are always shown in the Debug expander, never silently dropped.**

## 11. UI

`st.columns([3, 1])`: main content left, **controls panel right**. Controls: Refresh, Tournament radio
(Women/Men/Both, default Women), "Scan all tennis series" checkbox, Contract type (default Tournament
winner + Stage advancement; enabling Match result adds alignment rows), Outcome status, Quote quality,
Min volume, **Player** (selected by stable `player_key`, label disambiguated only on display-name
collision). Main: consistency table (sorted Broken→Warning→Missing→Unknown→Clean; clean rows filterable,
never hidden) → per-player detail = progression ladder → raw spreads → mapping confidence +
expected-vs-found → all contracts → export → debug expander. Use `width="stretch"` (not the deprecated
`use_container_width`). The earlier bar chart was removed as potentially misleading.

## 12. Tests

`pytest -q` (no network; `conftest.py` makes the repo root importable). ~42 cases covering: price
parsing, cents, quote buckets incl. empty/crossed books, `display_prob`/`display_cents`, `classify_kind`,
`tour_of` (all winner-ticker variants), round extraction, `build_contracts` typing + FO filter, the full
`_classify` precedence ladder + equivalence both-directions + truthful reason + rule flags, `layer_spreads`
(full/missing-layer/inverted/missing-price + the DataFrame-records NaN path), `representative`,
deterministic duplicate handling, pagination-cap raise, and date-window corroboration.

## 13. Conventions & hard-won gotchas

- **`external-api.kalshi.com`**, never `api.kalshi.com`.
- **Never `float()` a raw price string** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`.
- **`None` → NaN trap:** `df.to_dict("records")` turns a `None` numeric into float **NaN**, so a plain
  `is None` check misses it. Use NaN-safe checks (`consistency._isna/_num`). This caused a real bug where
  33% of "ok" spreads were silently NaN.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None`.
- **Streamlit caches imported modules in the running server.** After editing `data.py`/`consistency.py`/…,
  a browser "Rerun" won't pick it up — **fully stop and restart** `streamlit run app.py`. For a phantom
  `ImportError`, clear stale bytecode: `rm -rf __pycache__ tests/__pycache__`. (A stale long-lived server
  once produced an `ImportError` for code that was actually correct on disk.)
- **Commit/PR text on Windows:** use the **Bash tool here-doc** (`<<'EOF'`) or `gh --body-file -`. The
  PowerShell `@'...'@` here-string **corrupts** messages when run via the Bash tool (stray `@` chars — bit
  us twice).
- **Leftover headless servers:** kill with PowerShell `Get-Process streamlit | Stop-Process -Force`.
- **Pagination:** always loop the `cursor`; `get_paginated` now **raises** if `MAX_PAGES` (100) is hit with
  a cursor pending (no silent partial data).
- The **FO date window** in `config.py` is year-specific — update for future tournaments.
- The Kalshi **web** site (`kalshi.com`) is bot-throttled (HTTP 429); per-row links point to the series
  page `https://kalshi.com/markets/<series>` as best effort (deep per-market URLs not verifiable).
- Windows LF→CRLF warnings on commit are harmless.

## 14. Git workflow & the reconciliation history

**Strict rule (owner-confirmed):** never commit or push to `main`. The agent pushes a feature/docs branch
and opens a PR; the owner reviews and merges manually. Branch off **current `main`**; **do not stack on
unmerged branches** (a past stack caused a mess). Commit messages end with a `Co-Authored-By:` trailer;
PR bodies end with the Claude Code footer.

**The merge mess (resolved):** early on the branches were stacked (#1→#2→#3). PR #2 was **closed unmerged**
and PR #3 was merged into PR #2's branch instead of `main`, so `main` was missing iterations 3–4. This was
reconciled by **PR #6** (`feat/layer-consistency-checker → main`), which cleanly brought the full stack in.
Lesson encoded in the guides: branch off `main`, one PR per change, no stacking.

## 15. PR / iteration timeline

| PR | Branch → base | What | State |
|---|---|---|---|
| — | `main` | initial per-player match viewer | base |
| #1 | all-player-contracts → main | all per-player FO contracts via dynamic discovery | merged |
| #2 | contract-display-and-defaults → #1 | price components, default core series, debug | **closed** (mistake) |
| #3 | layer-consistency-checker → #2 | the consistency checker | merged into #2's branch (mistake) |
| #4 | ai-agent-guides → main | independent `CLAUDE.md` + `AGENTS.md` | merged |
| #5 | plan-accuracy-update → main | `kalshi-plan.md` accuracy rewrite | **closed** (superseded by #8) |
| #6 | layer-consistency-checker → main | **reconcile** main (brings iter 3–4) | merged |
| #7 | mapping-audit-hardening → main | mapping confidence, expected-vs-found, export, first tests | merged |
| #8 | plan-simplify → main | simplified, simple-first `kalshi-plan.md` | merged |
| #9 | ladder-spreads → main | **v1 raw stage-ladder spreads** | merged |
| #10 | agent-guides-refresh → main | guides refresh | merged |
| #11 | spread-nan-fix → main | NaN-safe spreads + Quote column | merged |
| #12 | audit-tier1-fixes → main | audit Tier-1 (key grouping, truthful reason, tour map, crossed-book, JSON) | merged |
| #13 | audit-tier2 → main | audit Tier-2 (pagination/duplicate/date-window) | **open** |
| #14 | guides-refresh-2 → main | guides refresh (v1 + audit hardening) | **open** |

## 16. Roadmap (simple-first) & deferred items

Principle: start with the simplest useful math (raw spreads) and add models/features **only if needed**.
The "expand later" menu (each independent, none committed): conditional advance probabilities + de-vig;
spread-edge signals; skill/Elo-adjusted probabilities (**needs an external rating source**); scenario/
bracket trees (**needs a draw-structure source** Kalshi doesn't expose); confidence/liquidity scoring;
real-time updates; alerts; trading (paper→live, **only if the read-only guard is lifted**).

**Deferred audit items** (from `audit_report.md`, beyond what's merged/in #13): a deterministic
sample-data mode for offline app smoke tests (AUDIT-009); clearer expected-layer semantics for
early-round-only players (AUDIT-010); a minimal lint config (AUDIT-011, needs a dep decision); plus the
broader regression-test matrix.

## 17. Key decisions log (what & why)

- **Read-only, public data only** — the credentials were unnecessary; removed to avoid leaking a real key.
- **`external-api` host** — `api.kalshi.com` doesn't resolve (discovered empirically).
- **Default 6 series + opt-in full scan** — full discovery (~61 series, ~20s) is too slow as a default; 6
  core series load in ~2s.
- **Transparent pricing, no fake 50%** — empty `0/1` books are "No quote", not a midpoint.
- **"Executable inconsistency", never "arbitrage"; integer cents; only EXECUTABLE_VIOLATION is Broken** —
  owner constraints to avoid overclaiming and float drift, and to keep "Broken" meaning genuinely tradable.
- **AUDIT-002 — keep `DISPLAY_VIOLATION`** when a sizeless price-cross *also* crosses on display (matches
  the original "downgrade to DISPLAY_VIOLATION or QUOTE_SIZE_MISSING" instruction). Codex preferred strict
  QUOTE_SIZE_MISSING; owner chose to keep current; docs clarified.
- **Key-based grouping (AUDIT-001)** — group/select by stable `player_key`, never display name.
- **Simple-first roadmap** — the original 11-stage plan was overcomplicated; collapsed to v1 + optional menu.
- **Removed the bar chart** — variable quote quality made it potentially misleading; tables only for v1.
- **Two independent agent guides** — `AGENTS.md` (Codex) and `CLAUDE.md` (Claude Code), each self-contained.

## 18. Known limitations / open risks

- **Liquidity:** most ladder markets are illiquid, so few spreads/consistency checks are high-confidence.
  This is a data-availability limit, not a code bug — surfaced honestly via Quote quality.
- **Bracket/draw structure & player ratings are unavailable** from Kalshi → scenario trees and skill
  models are blocked until an external source is chosen.
- **Date-window FO fallback** is a heuristic (now gated by competition info), still year-specific.
- **No deterministic offline/sample mode** yet → CI smoke testing relies on live data + a headless health
  check (AUDIT-009, deferred).
- The match-alignment equivalence assumes rule compatibility it does not verify → always `RULE_CHECK_REQUIRED`.
