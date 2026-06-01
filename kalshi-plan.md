# Engineering Plan - Kalshi Contract Probability Tool

> **Status:** Audited 2026-06-01 and corrected to match the **implemented** code. The original
> draft described the initial match-only prototype; several "future" items were already built.
> See **§0 Repository state** for the canonical branch and an important merge caveat.
>
> **Scope guard:** read-only only. No trading, account access, or order execution at this stage.
> Preserve read-only scope until the mapping, graph, probability, and signal layers are validated.

---

## 0. Repository state (read this first)

The accurate, **canonical** codebase is the branch **`feat/layer-consistency-checker`** — the tip of
a linear stack of four iterations:

1. initial match viewer (`main`),
2. all per-player FO contracts via dynamic discovery (`feat/all-player-contracts`),
3. price-component columns + default core series + richer debug (`feat/contract-display-and-defaults`, `b60ec5d`),
4. the Layer Consistency Checker (`feat/layer-consistency-checker`, `f15073c`).

**Merge caveat:** `main` is currently **missing iterations 3 and 4**. PR #1 (iter 2) and PR #4 (the
`CLAUDE.md`/`AGENTS.md` docs) merged into `main`; **PR #2 was closed unmerged and PR #3 was merged into
PR #2's branch instead of `main`.** Until that is reconciled, `main` shows only iteration-2 code, while
`feat/layer-consistency-checker` is the real current state this plan describes.

## 1. Executive Summary

**Objective.** Build an achievable, testable engineering path for a Kalshi event-contract tool. The
current example is French Open tennis contracts; the long-term architecture should support event trees
across other sports and non-sport event structures.

**Current status.** The app is a read-only Streamlit tool that discovers French Open per-player
contracts across **multiple market types** (match result, stage advancement, tournament winner; plus an
opt-in full scan that also surfaces set-winner / exact-score), presents a transparent price breakdown
per contract, and runs a **Layer Consistency Checker** that flags when a deeper outcome prices above a
prerequisite it is contained in. It is **not** a trading system: no account access, orders, portfolio,
probability model, alerts, or WebSocket streaming.

**Near-term recommendation.** Do not add trading automation next. The mapping/typing/quote-quality work
that an earlier draft listed as "next" is already built; the next best step is to **harden the mapping
audit** (confidence + reasons, export, explicit expected-contract buckets, unit tests), then a
relationship/bracket graph once a draw-structure data source exists.

**Core principle.** Build in layers: market discovery, contract mapping, relationship graph, probability
engine, signal engine, paper trading, and only then limited live execution.

## 2. What the App Already Does

Based on the implemented code on `feat/layer-consistency-checker`: `app.py`, `config.py`,
`kalshi_client.py`, `data.py`, and `consistency.py`.

### 2.1 Current product shape

Streamlit web app titled "French Open — Layer Consistency Checker", wide layout. Read-only: no order
placement, authentication, portfolio retrieval, or trading. A 60-second data cache (and a separate
~1-hour cache for the series list) backs a Refresh button that clears caches and reruns. Empty/error
states (no open contracts, no rows matching filters, failed loads) are surfaced, not failed silently.

### 2.2 Market data collection

`BASE_URL = https://external-api.kalshi.com/trade-api/v2` (note: `api.kalshi.com` does not resolve).
By default fetches the core French Open series — `KXATPMATCH`, `KXWTAMATCH`, `KXATPADVANCE`,
`KXWTAADVANCE`, `KXFOMEN`, `KXFOWOMEN` — concurrently (`get_events_for_series`, thread pool + a
sequential retry pass). An optional "Scan all tennis series" checkbox runs `discover_tennis_series()`
(every `KXATP*`/`KXWTA*` plus named winner tickers, ~61 series). Events are fetched with nested markets
to avoid N+1; cursor pagination with a page cap; retry/backoff on 429/5xx; a sized connection pool.
HTTP concerns stay in `kalshi_client.py`. **Failed series are returned and shown in the debug expander,
never silently dropped.**

### 2.3 French Open filtering

Narrows generic ATP/WTA series to French Open / Roland Garros in `data.py`. Primary signal:
`product_metadata.competition`. Fallbacks: event/market titles, subtitles, and market rules keywords;
then a padded 2026 date window as a last resort.

### 2.4 Per-player contract index and typing

Flattens events into one row per player-side market. Each row is **classified** by `kind`
(`match`, `advance`, `winner`, `set_winner`, `exact_score`, …) and a user-facing `category`
("Match result", "Stage advancement", "Tournament winner", …). Players are keyed by the stable
`custom_strike.tennis_competitor` UUID when present (`player_key_source = "competitor_uuid"`), falling
back to a normalized name (`"name_fallback"`); `NAME_ALIASES` allows display overrides. For head-to-head
match events, the opponent is derived from the sibling market; winner/advancement markets are
single-sided (no opponent). Round/stage is extracted from title/rules via regex.

### 2.5 Quote, pricing, and quote-quality fields

Fixed-point strings are parsed to numbers (`to_float`) and to **exact integer cents** (`to_cents`,
Decimal). Per row the app stores: `display_pct` (midpoint when the spread is reasonable, else last,
else blank), the components `yes_mid_pct / last_pct / yes_bid_pct / yes_ask_pct`, `spread_cents`, a
`quote_quality` label (Tight / OK / Wide / Very wide / One-sided / No quote), cent-exact
`yes_bid_c / yes_ask_c / last_c / display_c`, order sizes `yes_bid_size / yes_ask_size`, `volume`,
`open_interest`, `status`, `time_value`/`time_kind` (match time for matches; close/expiration
otherwise), `kalshi_url`, and identifiers (`series`, `event_ticker`, `market_ticker`, titles,
`rules_primary`). An empty `0.00/1.00` book is treated as "No quote", never a fake 50%.

### 2.6 Layer Consistency Checker

`consistency.py` builds, per player, a containment ladder `Reach Semifinal ⊇ Reach Final ⊇ Win
Tournament` and compares adjacent layers (`build_player_nodes`, `build_checks`): a deeper outcome's
price must be ≤ its prerequisite's. It also adds **match-alignment** checks (winning the current match
⇔ reaching the next stage) only when the round maps confidently. Findings are **"executable
inconsistencies", never "arbitrage"**: the executable test requires a firm child-bid > parent-ask with
**positive order sizes**, in integer cents; a display-only breach is a softer warning. Statuses:
`CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`; only `EXECUTABLE_VIOLATION` is "Broken". Match-alignment rows
carry a `RULE_CHECK_REQUIRED`/`RULE_MISMATCH` flag because settlement rules are not auto-verified.

### 2.7 Current UI behavior

`st.columns([3, 1])`: main content left, **right-hand controls panel** with Refresh, Tournament radio
(Women/Men/Both, default Women), "Scan all tennis series" checkbox, Contract type (default winner +
advancement), Outcome status, Quote quality, Minimum volume, and Player select. Main area shows the
**layer-consistency table** (sorted Broken→Warning→Missing→Unknown→Clean; clean rows filterable, never
hidden) and a **per-player detail** view (progression chain, all contracts table, debug expander with
raw fields and per-comparison reasons). There is no chart (an earlier bar chart was removed as
potentially misleading).

### 2.8 Code organization

| File | Current responsibility |
| --- | --- |
| app.py | Streamlit UI only: layout, caching, controls/filters, consistency table, player detail, debug, empty/error states. |
| config.py | Read-only constants: API base URL, `DEFAULT_SERIES`, discovery prefixes + winner tickers, FO keywords/date window, `SPREAD_REASONABLE`, `DISPLAY_TOL_C`, name aliases, user agent, timeout, page cap. |
| kalshi_client.py | Public-data HTTP client: session/pool, GET, retry/backoff, pagination, `get_events`, `discover_tennis_series`, concurrent `get_events_for_series` (with error capture). |
| data.py | Pure data logic (no Streamlit): parsing, `to_cents`, FO filtering, `classify_kind`/`tour_of`, round extraction, pricing/quote-quality helpers, `build_contracts`. |
| consistency.py | Pure logic (no Streamlit): node/chain building, `_classify`, `build_checks`, statuses + rule flags. |

## 3. Current Limitations and Corrections

| Area | Current reality | Implication for next work |
| --- | --- | --- |
| Contract coverage | Match, stage-advancement, and tournament-winner are fetched by default; set-winner/exact-score appear under full scan. | Coverage is broad. Verify completeness per player (expected-but-missing buckets). |
| Contract taxonomy | Rows carry `kind` + `category`. | Taxonomy exists; only a numeric confidence is missing. |
| Mapping confidence | Stable UUID vs name fallback is recorded as `player_key_source`, but there is no numeric `mapping_confidence` or reason string. | Add `mapping_confidence` + explicit reasons. |
| Expected/missing contracts | The consistency checker emits `MISSING_LAYER` for absent ladder nodes, but there is no per-player "expected contract set" enumeration. | Add explicit expected-contract buckets. |
| Quote quality | Spread (`spread_cents`) and `quote_quality` labels exist; display price degrades gracefully. | Add freshness/stale scoring (feasibility caveat below). |
| Real-time behavior | Cached polling / manual refresh; no WebSocket. | Keep real-time as a later milestone. |
| Debug/export | A per-player debug expander shows raw fields and comparison reasons, but there is **no downloadable export**. | Add an exportable (JSON/CSV) per-player snapshot. |
| Tests | **No automated tests** for `data.py`/`consistency.py`. | Add unit tests before stacking more layers. |
| Trading/account | None. | Maintain hard separation between read-only, paper, and live modes. |

## 4. Roadmap Overview

| Stage | Milestone | Ready-to-advance test | Status |
| --- | --- | --- | --- |
| 1 | Contract Mapping Audit | High-confidence mappings correct on manual review; missing buckets explicit. | **Mostly built** — needs confidence/reasons, export, expected buckets, tests. |
| 2 | Contract Relationship Graph | Mini-bracket generates valid future matchups and rejects impossible paths. | **Partial** — containment edges exist; future-matchup bracket not built (needs draw source). |
| 3 | Baseline Probability Engine | Probabilities are stable, explained, and separated from quote quality. | Not started (v2/v3 need an external rating source). |
| 4 | Scenario Probability Calculator | **After de-vig**, mutually exclusive scenario paths sum to 1.00 ± tol. | Not started. |
| 5 | Confidence and Liquidity Scoring | Every probability output includes uncertainty and liquidity reasons. | Quote-quality groundwork exists. |
| 6 | Real-Time Read-Only Engine | Simulated rapid updates do not freeze the UI or corrupt state. | Not started. |
| 7 | Signal Engine | Signals are sparse, interpretable, not stale-price artifacts. | Not started. |
| 8 | Alerts and Notifications | Alerts are deduplicated and actionable. | Not started. |
| 9 | Paper Trading | (Vision; out of current read-only scope.) | Out of scope now. |
| 10 | Limited Live Trading | (Vision; out of current read-only scope.) | Out of scope now. |
| 11 | Generalization | A second sport/event type reuses the common layers. | Vision. |

## 5. Stage Details and Gates

### Stage 1 - Contract Mapping Audit (mostly built; harden the gaps)

**Already done:** contract typing (`kind`/`category`), mapping source (`player_key_source`),
spread + quote-quality, `MISSING_LAYER` flagging.
**Still to build:** numeric `mapping_confidence` + reasons; an **exportable** per-player debug snapshot
(JSON/CSV); explicit **expected-contract enumeration** per player; **unit tests**.
**Test gate.** A manual review of a defined sample (e.g. 20–50 named players) confirms ≥95% of
high-confidence mappings are correct. Define the ground-truth source and what "correct"/"high-confidence"
mean before measuring.

### Stage 2 - Contract Relationship Graph

**Milestone.** Represent event structure as a graph rather than a flat table.
**Dependency (blocking):** a **draw/bracket adjacency source** (who can meet whom). Kalshi exposes
current matches + per-player advancement markets, not the full draw. If unavailable, descope to
"downstream containment scenarios" using advancement markets (which the current checker approximates).
**Test gate.** The graph generates all valid future matchups and rejects impossible ones.

### Stage 3 - Baseline Probability Engine

**Build.** v1: market-implied (with de-vig). v2: skill-adjusted. v3: hybrid weighted by quote/data quality.
**Dependency (blocking for v2/v3):** an external **rating source** (ATP/WTA ranking or Elo) — none exists
in Kalshi data; identify and ingest one first.
**Test gate.** Probabilities are stable, sensible, and explainable across a sample of matches.

### Stage 4 - Scenario Probability Calculator

**Build.** Deterministic scenario-tree enumeration; later Monte Carlo for larger brackets.
**Note (correctness):** raw market-implied YES prices across mutually exclusive outcomes sum to **> 1**
(spread/overround; observed ≈1.01 live). A **de-vig/normalization** step is required first.
**Test gate.** After de-vig, mutually exclusive scenario probabilities sum to 1.00 within rounding tolerance.

### Stage 5 - Confidence and Liquidity Scoring

Score spread, volume, quote freshness, mapping confidence, market status, expiration, and skill-data
quality, each with explicit reasons. Do not let low-confidence outputs look precise.
**Feasibility caveat:** the snapshot exposes `updated_time`/`last_updated_ts`, not a true last-quote
timestamp — "freshness" is approximate; confirm what is derivable before promising stale flags.
**Test gate.** Confidence scores improve interpretation without creating false certainty.

### Stage 6 - Real-Time Read-Only Engine

Begin with simulated/polled updates; authenticated WebSocket later. Handle stale, missing, and
out-of-order updates and UI responsiveness. **Test gate.** Rapid simulated updates don't freeze the UI
or corrupt calculations.

### Stage 7 - Signal Engine

Compute model probability, market probability, gross edge, liquidity score, confidence score, and signal
status (No signal / Watch / Alert / Blocked), with a full reason trail. **Test gate.** Signals are sparse,
interpretable, and not mostly stale-price artifacts.

### Stage 8 - Alerts and Notifications

In-app alert log first; email/webhook next. **Test gate.** Alerts are deduplicated and actionable.

### Stages 9-11 - Paper Trading, Limited Live Trading, Generalization (VISION — OUT OF CURRENT SCOPE)

These remain **out of the current read-only scope** and must not be started until the mapping, graph,
probability, and signal layers are validated and the owner explicitly lifts the read-only guard.
- **9 Paper Trading:** executable bid/ask (not midpoint); simulate fees, slippage, latency, partial
  fills, settlement; track signal/trade counts, fill rate, edge, P&L, drawdown.
- **10 Limited Live Trading:** manual approval, tiny size, no market orders, hard loss limits, kill
  switch, full audit logs.
- **11 Generalization:** factor tennis-specific logic into a generic event-graph framework with
  sport-specific adapters; do not over-generalize early.

## 6. Immediate Next Iteration

**Recommended next build — Mapping-Audit Hardening.** The base mapping/typing/pricing work is already
implemented, so build only the missing slice that future probability/scenario/signal layers depend on.

### Implementation tasks
- Add numeric `mapping_confidence` + reason strings, formalizing the existing `player_key_source`
  (e.g. `competitor_uuid` → high, `name_fallback` → medium/low with a reason).
- Add explicit **expected-contract enumeration** per player (which ladder/market types *should* exist),
  surfacing missing ones beyond the implicit `MISSING_LAYER` rows.
- Add an **exportable per-player debug snapshot** (JSON/CSV download) containing flattened rows, raw
  event/market IDs, mapping reasons, quote-quality, and comparison statuses/reasons.
- Add **unit tests** for `data.to_cents`, `quote_quality`, `display_prob`, `classify_kind`, and the
  `consistency._classify` precedence (executable vs display vs missing/size vs wide).

(Do **not** re-add `contract_type`, spread, quote-quality, or a close-time column — already present.
Do **not** add a "stage-advancement / tournament-winner not loaded" warning — those markets *are* loaded.)

### Definition of done
- Every contract row carries a `kind`/`category`, a `mapping_confidence`, and a reason; no downstream
  layer consumes a row lacking these.
- Missing or not-yet-supported contract buckets are explicit per player, not implied-by-omission.
- A downloadable per-player debug snapshot exists for investigating misclassified/missing contracts.
- Unit tests for the pricing and consistency logic pass.

## 7. Near-Term Checklist
- [x] Document current behavior accurately (this revision).
- [x] `kind`/`category`, spread, quote-quality, `player_key_source` (mapping source).
- [x] Show match time / close time clearly (`time_value`/`time_kind`).
- [x] Multi-contract coverage (match + advancement + winner) and the consistency checker.
- [ ] Numeric `mapping_confidence` + reasons.
- [ ] Explicit expected-but-missing contract buckets per player.
- [ ] Exportable per-player debug snapshot.
- [ ] Unit tests for `data.py` / `consistency.py`.
- [ ] Reconcile `main` to include iterations 3–4 (see §0).
- [ ] Only after the audit hardening passes, build the relationship/bracket graph (needs a draw source).
