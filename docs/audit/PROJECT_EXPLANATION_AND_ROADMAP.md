# Project Explanation And Roadmap

Date: 2026-06-01
Project folder: `C:\Users\Batata\Desktop\Internship`
Scope: local repository only, no GitHub or remote history used.

## Executive Summary

This project is a read-only Streamlit app that loads public Kalshi French Open tennis markets, normalizes them into per-player contract rows, builds a simple progression ladder, checks layer consistency, and shows raw adjacent ladder spreads. It is deliberately simple-first: it exposes current prices, quote quality, missing data, and conservative inconsistency checks without trading, account access, alerts, or probability models.

The current local code is substantially hardened compared with the older `AUDIT_REPORT.md`. Several Critical/High findings are fixed in code and tests: player grouping now uses `player_key`, crossed books are guarded, winner ticker tour mapping includes the problematic women's variant, and equivalence reasons name the actual cross direction. Two important audit concerns still remain: AUDIT-002 remains present relative to the audit's strict recommendation, although local docs/tests appear to accept it as a product decision; AUDIT-006 duplicate node/source overwrites are still present. Medium risks also remain around pagination truncation, date-window fallback, sample-data mode, expected-layer semantics, and tooling.

The project is useful for its intended read-only analytical purpose, but its next work should be correctness and confidence, not modeling. The best next coding task is deterministic duplicate node/source handling, because the current representative selection can silently overwrite rows.

## Repository Map

Concise local tree:

```text
.
|-- AGENTS.md
|-- AUDIT_REPORT.md
|-- CLAUDE.md
|-- CONTEXT.md
|-- README.md
|-- app.py
|-- config.py
|-- conftest.py
|-- consistency.py
|-- data.py
|-- kalshi-plan.md
|-- kalshi_client.py
|-- requirements-dev.txt
|-- requirements.txt
`-- tests
    |-- test_consistency.py
    `-- test_data.py
```

Entrypoint: `app.py`.

Core modules: `data.py`, `consistency.py`.

Data/client module: `kalshi_client.py`.

Config/dependencies: `config.py`, `requirements.txt`, `requirements-dev.txt`, `conftest.py`.

Tests: `tests/test_data.py`, `tests/test_consistency.py`.

Docs/guides: `README.md`, `kalshi-plan.md`, `CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, `AUDIT_REPORT.md`.

## File-By-File Explanation

| File | Purpose | Key functions/classes | Inputs | Outputs | Risks / notes |
|---|---|---|---|---|---|
| `app.py` | Streamlit UI and orchestration. | `discover`, `load_contracts`, `_passes_type`, `_passes_quote`; top-level Streamlit layout. | User controls, cached Kalshi results via `kalshi_client`, normalized rows from `data.py`. | Main consistency table, player ladder, raw spread table, expected layers, exports, debug tables. | Well-scoped as UI only, but large enough that view-model helpers would help. Top-level data load makes deterministic app smoke tests hard. |
| `config.py` | Constants and project settings. | `BASE_URL`, `DEFAULT_SERIES`, `FO_WINNER_TICKERS`, `FO_KEYWORDS`, `FO_WINDOW`, `SPREAD_REASONABLE`, `DISPLAY_TOL_C`, `MAX_PAGES`. | None at runtime beyond imports. | Shared constants for client/data/checker. | Year-specific FO window must be maintained. `MAX_PAGES` is a safety cap but current pagination does not report truncation. |
| `kalshi_client.py` | Read-only public Kalshi HTTP client. | `KalshiError`, `_get`, `get_paginated`, `get_events`, `discover_tennis_series`, `get_events_for_series`. | Series tickers, API path/params, public Kalshi API. | Events/series lists plus per-series error list. | Uses only GET and no auth. JSON decode is wrapped. Pagination cap still silently returns partial data if cursor remains. |
| `data.py` | Pure data normalization and price handling. | `to_float`, `to_cents`, `is_french_open_event`, `filter_french_open`, `yes_mid`, `spread`, `quote_quality`, `display_prob`, `display_cents`, `classify_kind`, `tour_of`, `build_contracts`. | Raw event/market dictionaries from Kalshi. | Flat per-player contract row dictionaries. | No Streamlit import, good separation. Date-window fallback can still accept in-window non-FO events. Name fallback remains collision-prone by nature, though marked low confidence. |
| `consistency.py` | Pure ladder, spread, and consistency logic. | `node_of`, `build_player_nodes`, `representative`, `layer_spreads`, `expected_nodes`, `_classify`, `build_checks`. | DataFrame/records from `data.build_contracts`. | Consistency DataFrame, expected layer rows, raw spread rows. | Now groups checks by `player_key`. Duplicate node/source rows are still overwritten by last row. `AUDIT-002` behavior remains accepted in tests but conflicts with the old audit recommendation. |
| `conftest.py` | Pytest root helper. | None. | Pytest invocation. | Lets tests import project modules directly. | Intentionally tiny and well-scoped. |
| `tests/test_data.py` | Unit tests for data layer. | Test functions for parsing, quote quality, crossed books, tour mapping, classification, round extraction, mapping confidence, build_contracts. | Synthetic events/markets. | Assertions, no network. | Good for current Tier-1 edge cases. Missing date-window fallback and pagination tests. |
| `tests/test_consistency.py` | Unit tests for consistency/spreads. | Test functions for `_classify`, rule flags, expected nodes, layer spreads, NaN path, key grouping, reverse reason, crossed legs, AUDIT-002 accepted behavior. | Synthetic contract rows/DataFrames. | Assertions, no network. | Covers many core checker paths. Missing duplicate node/source deterministic behavior. |
| `requirements.txt` | Runtime dependencies. | `streamlit`, `requests`, `pandas`. | pip. | Runtime environment. | No pinned upper bounds; acceptable for small app but can drift. |
| `requirements-dev.txt` | Test dependencies. | includes runtime deps plus `pytest`. | pip. | Dev/test environment. | Minimal and simple. |
| `README.md` | User-facing project overview. | N/A. | Reader. | Setup, behavior, pricing, mapping summary. | Mostly aligned, but local terminal displays mojibake due encoding. Does not mention all current audit decisions. |
| `kalshi-plan.md` | Simple-first roadmap. | N/A. | Reader. | Current roadmap and deferred items. | Says Tier-1 done and Tier-2 deferred. It is more current than `AUDIT_REPORT.md`, but some statements depend on fixes not present in code. |
| `CONTEXT.md` | Large handoff/context dump. | N/A. | Reader. | Narrative history, architecture, decisions, PR timeline. | Useful but not fully reliable locally: it says Tier-2 items and ~42 tests exist, while local code has 36 tests and several Tier-2 items are not implemented. |
| `AGENTS.md` | Codex/agent operating guide. | N/A. | Agent. | Project constraints, setup, architecture, gotchas. | Contains stricter status wording than current tests for AUDIT-002; should be reconciled with owner decision. |
| `CLAUDE.md` | Claude Code operating guide. | N/A. | Agent. | Similar guide for another agent. | Same risk as `AGENTS.md`: must stay aligned with actual code decisions. |
| `AUDIT_REPORT.md` | Prior adversarial audit baseline. | N/A. | Reader. | Findings, tests, roadmap suggestions. | Found and used. Some High findings are now fixed; one High finding remains accepted/contested; some Medium findings remain. |

## End-To-End Data Flow

Text diagram:

```text
User opens Streamlit app
-> app.py loads cached/default or full-scan series list
-> kalshi_client.py GETs public Kalshi events with nested markets
-> data.py filters French Open events
-> data.py flattens event/market payloads into contract rows
-> app.py filters by tournament/tour
-> consistency.py groups rows by player_key
-> consistency.py builds ladder nodes
-> consistency.py computes consistency checks and raw spreads
-> app.py applies UI filters
-> Streamlit renders tables and download exports
```

Detailed flow:

1. `app.py` defines cached `discover()` and `load_contracts(full_scan)`.
2. If full scan is off, `load_contracts` uses `config.DEFAULT_SERIES`. If full scan is on, it calls `discover_tennis_series()`.
3. `kalshi_client.get_events_for_series` concurrently calls `get_events`, which calls `get_paginated("/events", ..., with_nested_markets=true)`.
4. `data.build_contracts` receives each series and event list.
5. `data.is_french_open_event` keeps events with French Open keyword evidence, or as a final fallback, events inside `FO_WINDOW`.
6. `data.classify_kind` classifies a series as match, advance, winner, exact score, set winner, grand slam, or other.
7. `data.tour_of` assigns ATP/WTA, including explicit winner ticker variants.
8. Each market becomes one contract row with `player`, `player_key`, mapping confidence, stage, opponent, identifiers, raw fields, and pricing fields.
9. Price strings are parsed with `to_float` for display and `to_cents` for exact comparison.
10. `yes_mid` and `spread` reject missing, empty, one-sided, and crossed books.
11. `display_prob` uses midpoint only when spread is reasonable, otherwise last trade, otherwise blank.
12. `quote_quality` labels Tight/OK/Wide/Very wide/One-sided/No quote/Crossed.
13. `app.py` filters rows by tournament radio.
14. `consistency.build_checks` groups by stable `player_key`, builds nodes, and emits containment, match-alignment, missing-layer, and unknown-relationship rows.
15. `consistency.layer_spreads` reuses the same representative selection and computes broader-minus-deeper adjacent raw spreads.
16. `app.py` applies contract type, status, quote quality, and volume filters to the consistency table.
17. Per-player UI uses selected `player_key`, not just display name.
18. Export buttons serialize the selected player's contracts, expected layers, ladder spreads, and consistency comparisons.

## UI Explanation

| UI element | Where | Depends on | How to interpret | Risks / missing context |
|---|---|---|---|---|
| Page title/header | Top of main app | Static `st.title`. | Identifies the French Open layer consistency tool. | Uses tennis icon; no issue. |
| Refresh data button | Right controls panel | Streamlit caches. | Clears series discovery and contract cache, then reruns. | Users may not realize Streamlit module imports still need full server restart after code edits. |
| Tournament radio | Right controls panel | `tour` column from `data.tour_of`. | Filters Women, Men, or Both. | Correctness depends on tour classification. Current known winner variant is fixed. |
| Scan all tennis series checkbox | Right controls panel | `discover_tennis_series`. | Default scans 6 core series; full scan discovers tennis series and may include extra contract types. | Full scan can be slower and increases duplicate/overlap risk. |
| Contract type multiselect | Right controls panel | `child_category`, `parent_category`. | Controls which consistency rows remain visible. Match result enables alignment rows. | Default excludes Match result, so some useful alignment/unknown rows are hidden until selected. |
| Outcome status selectbox | Right controls panel | `status_group`. | Filters Clean, Broken, Warning, Missing data, Unknown relationship, or All. | Clear enough. |
| Quote quality selectbox | Right controls panel | `comp_quote_quality`. | All, Tight/OK only, or Include wide. | "Include wide" excludes One-sided/No quote/Crossed, which is reasonable but could be named more explicitly. |
| Minimum volume slider | Right controls panel | `volume` in check rows. | Filters comparisons below a minimum pair volume. | No open-interest slider exists. Volume semantics are min of child/parent volumes, not obvious to users. |
| Player selector | Right controls panel | Unique `player_key` and display `player`. | Selects one player for detail view; labels disambiguate only on display collision. | Good fix for name collisions. A debug-visible short key helps trust. |
| Main consistency table | Main area | `consistency.build_checks`, UI filters. | Shows child/parent logical comparisons, price gaps, status, rule flags, reason, tickers, links. | Reason quality is central. Reverse reason is now fixed. AUDIT-002 status semantics may still confuse if docs disagree. |
| Progression ladder table | Player detail | `build_player_nodes`, `representative`, `NODE_ORDER`. | Shows Reach Semifinal, Reach Final, Win Tournament, source, price, bid/ask, quote. | Missing layers are visible. Expected semantics can be noisy for players without ladder-market data. |
| Raw adjacent-ladder spread table | Under progression ladder | `layer_spreads`. | Shows broad layer minus deeper layer in percentage points and cents. Negative means inverted. | It is raw price difference, not conditional probability. Caption says this clearly. |
| Missing layer / missing price states | Ladder/spread tables | `layer_spreads`, `expected_nodes`. | `missing_layer` means no node; `missing_price` means node exists but no usable display price. | Good distinction. Needs clearer not-applicable wording for early-round-only players. |
| Quote-quality display | Main and detail tables | `quote_quality`, `_worst_quality`. | Indicates reliability of the price inputs. | Could use badges/color in future, but tables are acceptable. |
| Debug expander | Bottom of player detail | `errors`, selected player's raw rows, selected checks. | Shows failed series, raw identifiers, mapping fields, raw prices, comparison reasons. | Good for audit. Duplicate diagnostics are not yet surfaced. |
| Export snapshot button | Player detail | Selected player snapshot dict. | Downloads JSON with mapping, expected layers, spreads, contracts, checks. | Useful. Should eventually get schema regression tests. |
| Export contracts CSV button | Player detail | Selected player's contract DataFrame. | Downloads flat contract rows. | Useful for offline review. |
| Empty/error states | Main app | Load result and filters. | Shows "No comparisons match" or Kalshi load error. | Empty filtered state is okay. No deterministic sample-data mode for offline UX testing. |
| Open interest filter | Not present | N/A. | N/A. | Requested category says "if present"; it is not present. |

## Audit Issue Follow-Up

`AUDIT_REPORT.md` was found and used as the baseline. The current code was inspected directly afterward.

| Audit ID | Severity | Original issue | Current status | Evidence | Remaining work |
|---|---:|---|---|---|---|
| AUDIT-001 | Critical | Checks grouped by display `player`, causing same-name collision risk. | Fixed | `consistency.py` groups by `player_key`; `_row` carries `player_key`; `app.py` selector uses `player_key`; `tests/test_consistency.py` has a collision regression. | Keep export/debug key visible. Consider name-fallback collision warnings. |
| AUDIT-002 | High | Sizeless price cross plus display cross returns `DISPLAY_VIOLATION` instead of `QUOTE_SIZE_MISSING`. | Still present, apparently accepted | `consistency.py` keeps `DISPLAY_VIOLATION` when `exec_gap > 0`, `not sizes_ok`, and display also violates; `tests/test_consistency.py` documents this as owner decision. | Reconcile `AGENTS.md`/audit wording with actual product decision, or change code if strict audit semantics are still required. |
| AUDIT-003 | High | Reverse-direction equivalence reason could quote wrong legs. | Fixed | `consistency.py` stores candidate `frag` strings and chooses the winning direction; test asserts `parent bid 37c > child ask 35c`. | None beyond keeping tests. |
| AUDIT-004 | High | `KXFOPENWMENSINGLE` mapped to ATP. | Fixed | `data.py` has `_WOMEN_WINNER_TICKERS` including `KXFOPENWMENSINGLE`; `tests/test_data.py` covers all winner variants. | None. |
| AUDIT-005 | High | Crossed books were labeled Tight and used for display midpoint. | Fixed | `data.py` rejects `ask < bid`, returns `Crossed`; `consistency._leg` treats Crossed as unusable; tests cover both. | Maybe add UI copy explaining Crossed if seen live. |
| AUDIT-006 | High | Duplicate node/source rows silently overwrite representatives. | Still present | `build_player_nodes` still does `nodes.setdefault(node, {})[source] = row`; no `duplicate_node_sources` exists in local `consistency.py` despite `CONTEXT.md` saying it does. | Add deterministic duplicate handling and debug diagnostics. |
| AUDIT-007 | Medium | Pagination cap silently truncates when cursor remains. | Still present | `kalshi_client.get_paginated` loops `MAX_PAGES` then returns `items` without checking remaining cursor. | Raise `KalshiError` or return an explicit truncation error. |
| AUDIT-008 | Medium | Date-window fallback can accept non-FO in-window events. | Still present | `is_french_open_event` returns any in-window market timestamp after keyword checks fail. | Require corroborating tennis/competition signal or mark fallback confidence. |
| AUDIT-009 | Medium | No deterministic sample-data mode for app smoke tests. | Still present | `app.py` loads data through top-level Streamlit execution; tests cover pure modules only. | Add local fixture/sample mode for app smoke. |
| AUDIT-010 | Medium | Expected ladder semantics noisy for early-round/non-ladder players. | Still present | `expected_nodes` always expects `NODE_ORDER` for any player rows. | Add not-applicable or tracked-ladder confidence semantics. |
| AUDIT-011 | Low | No lint/type/format tooling. | Still present | No tooling config found. | Optional, needs dependency decision. |

Documentation mismatch: `CONTEXT.md` claims Tier-2 duplicate/pagination/date-window work is current or pending with ~42 tests. Local code has 36 passing tests and does not implement duplicate diagnostics, pagination cap failure, or gated date-window fallback.

## Robustness Assessment

| Area | Rating | Reason |
|---|---|---|
| Read-only safety | Strong | Only GET market-data calls found; no auth/trading/account paths. |
| Data loading reliability | Adequate | Retries, timeout, concurrent load, sequential retry, error surfacing exist. Pagination truncation remains weak. |
| Contract classification | Adequate | Series kind ordering and winner ticker variants are covered. Unknown future ticker shapes remain possible. |
| Player grouping | Adequate | Checks and selector now use `player_key`; name fallback is still low-confidence and collision-prone by nature. |
| Missing-data handling | Adequate | Missing layer vs missing price is clear; expected-layer semantics can overstate missingness. |
| Price/cents/percentage handling | Adequate | Decimal cents and NaN-safe paths exist; sub-cent rounding assumptions remain implicit. |
| Quote-quality handling | Adequate | Empty, one-sided, wide, and crossed books handled. UI could explain Crossed. |
| Ladder construction | Adequate | Simple and readable. Duplicate node/source overwrite keeps it from Strong. |
| Consistency checks | Adequate | Core logic and tests are good; AUDIT-002 semantics need doc alignment. |
| Raw spread calculation | Strong | Reuses representative, distinguishes missing states, NaN-safe, tested. |
| UI clarity | Adequate | Tables and captions are conservative. More filters/badges could improve scanning. |
| Debuggability | Adequate | Raw fields, failed series, and reasons are available. Duplicate diagnostics missing. |
| Export usefulness | Adequate | JSON and CSV are useful; schema tests missing. |
| Test coverage | Adequate | 36 unit tests pass, many core edge cases covered. App/UI/client failure modes need more. |
| Documentation | Weak | Multiple docs disagree with local code and audit status. |
| Maintainability | Adequate | Good pure/UI separation. `app.py` is getting large. |
| Performance | Adequate | Default scan is bounded; full scan uses concurrency. No performance instrumentation. |

## Test Coverage Summary

Local verification run for this report:

```text
pytest -q
36 passed, 1 warning
```

The warning is a pytest cache permission warning under `.pytest_cache`; it does not indicate test failure.

| Feature | Existing coverage | Missing tests | Priority |
|---|---|---|---|
| Price parsing | `to_float`, `to_cents` basics. | Sub-cent/fractional rounding behavior. | Should-have |
| Quote quality | Normal buckets, empty book, crossed book. | UI treatment of Crossed. | Should-have |
| Display price | Midpoint, last fallback, blank, crossed rejection. | Last-trade fallback freshness/staleness semantics. | Nice-to-have |
| Series kind classification | Winner/advance/exact/set/match/grand slam/other. | Unknown future ticker fixtures. | Nice-to-have |
| Tour mapping | Winner variants including `KXFOPENWMENSINGLE`. | Future winner ticker names. | Nice-to-have |
| French Open filtering | Positive FO and negative outside-window case. | In-window non-FO false positive. | Must-have |
| Build contracts | Synthetic match event, mapping confidence, opponent, stage. | Advancement/winner/set/exact synthetic payloads. | Should-have |
| Player grouping | Same display name, different `player_key`. | Name fallback collision warning behavior. | Must-have |
| Consistency status | Core statuses, display/executable split, rule flags. | More integrated full-ladder mixed status snapshots. | Should-have |
| AUDIT-002 accepted behavior | Covered as current decision. | Docs/guides consistency test is not applicable, but docs need sync. | Must-have docs |
| Equivalence checks | Both directions and truthful reverse reason. | More rule-token combinations. | Nice-to-have |
| Raw spreads | Full chain, missing layer, missing price, inverted, NaN records, quote worst. | Duplicate representative effect. | Must-have |
| Duplicate node/source | Not covered. | Deterministic selection and diagnostics. | Must-have |
| Pagination | Not covered. | `MAX_PAGES` cursor-remains failure. | Must-have |
| Client JSON failure | Code wraps JSON decode; no visible local test found. | Non-JSON 200 mock test. | Should-have |
| UI filters | Not covered. | Contract/status/quote/volume/player filter view-model tests. | Should-have |
| Export snapshot | Not covered. | JSON schema/content regression. | Should-have |
| App smoke | Streamlit health can be run, but no deterministic render test. | Sample-data mode and offline app render. | Must-have |

## Simple-First Extension Roadmap

| Order | Extension | Why useful | Complexity | Risk | Dependencies | Acceptance criteria | Timing |
|---:|---|---|---|---|---|---|---|
| 1 | Duplicate node/source diagnostics | Prevent silent representative overwrite in ladders/checks. | Medium | Low to medium | `consistency.py`, tests, debug UI. | Duplicate rows are deterministic, surfaced in debug/export, and tested. | Now |
| 2 | Pagination cap failure | Prevent silent partial data. | Small | Low | `kalshi_client.py`, tests. | Cursor remaining after `MAX_PAGES` raises/returns explicit error surfaced in UI. | Now |
| 3 | Date-window fallback confidence | Reduce non-FO contamination risk. | Small | Medium | `data.py`, tests. | In-window non-keyword event is rejected or flagged with fallback confidence. | Now |
| 4 | Sample-data mode | Make app smoke tests deterministic and offline. | Medium | Low | Synthetic fixture data, `app.py` boundary. | App renders one clean and one broken synthetic player without network. | Soon |
| 5 | Show only inverted spreads filter | Fast user triage of concerning raw spreads. | Small | Low | `app.py`, `layer_spreads` output. | Checkbox filters spread rows to `inverted=True`. | Soon |
| 6 | Show missing layers / missing prices filters | Makes data gaps easier to audit. | Small | Low | `app.py`. | User can isolate `missing_layer` and `missing_price`. | Soon |
| 7 | Weak quote-quality filter | Focus on risky rows without hiding them globally. | Small | Low | `app.py`. | Filter for Wide/Very wide/One-sided/No quote/Crossed. | Soon |
| 8 | Export schema tests | Protect offline audit output. | Small | Low | Tests and maybe helper builder. | Snapshot JSON has stable top-level keys and expected row fields. | Soon |
| 9 | Timing/performance debug panel | Helps understand default vs full scan latency. | Small | Low | `app.py`, client timing metadata. | Debug shows scanned series, loaded series, failed series, elapsed load time. | Later |
| 10 | Historical snapshot saving | Useful only if users need comparison over time. | Medium | Medium | Storage decision, privacy/scope review. | Explicit user-triggered snapshot persistence with clear read-only semantics. | Later |
| 11 | Local replay mode | Useful if historical snapshots are added. | Medium | Medium | Snapshot format. | App can load a saved snapshot instead of live data. | Later |
| 12 | Basic market-implied normalization | Only after raw quote handling earns trust. | Medium | Medium | Clear math spec and tests. | Clearly labeled non-trading model output, optional and separate from raw tables. | Later |
| 13 | Multi-tournament support | Useful after French Open workflow stabilizes. | Medium/large | Medium | Config/date/tournament abstraction. | Can switch tournaments without breaking FO-specific tests. | Later |
| 14 | General event-ladder abstraction | Could reduce tennis specificity after one workflow proves useful. | Large | High | Stable multi-tournament needs. | Generic abstraction passes tennis fixtures and one new domain fixture. | Deferred |
| 15 | Elo / Monte Carlo / conditional tree / trading signals / alerts / live trading | These change the product from transparent read-only inspection into modeling or action. | Large | High | External ratings, draw data, scope lift, safety review. | Not applicable under current scope. | Deferred |

## Structural Improvement Suggestions

- Keep `data.py` and `consistency.py` free of Streamlit. That boundary is good and should not be weakened.
- Make `app.py` thinner when the next UI change arrives. Extract small view-model builders for consistency table rows, player options, ladder table rows, spread table rows, and export snapshot assembly.
- Centralize missing-value handling if more modules need NaN/None normalization. Right now `_num` lives in `consistency.py`; if UI view-models start doing more numeric logic, a small utility may help.
- Keep price/quote logic in `data.py` for now. A separate `pricing.py` is only justified if price helpers grow or are reused outside contract normalization.
- Keep raw spread logic in `consistency.py` for now because it shares node construction and representative selection. A future `spreads.py` only makes sense if spreads gain independent features or multiple ladder types.
- A schema/constants module could help later for column names and status labels. Trigger condition: more export/view-model tests or repeated column lists across modules.
- DuckDB, Polars, SQL, and React are not justified now. Current data size and UI are table-centric and simple. Consider storage only after historical snapshots are a committed feature. Consider a frontend rewrite only if Streamlit blocks a concrete workflow.
- Measure before changing technology: full-scan latency, row counts, duplicate rates, failed series frequency, user time-to-find-inverted spread, and export/debug usage.

## Recommended Next 3 Coding Tasks

1. Task name: Deterministic duplicate node/source handling
   Why it should come next: AUDIT-006 is the remaining High correctness risk. Silent overwrites can alter ladders, checks, and spreads.
   Files likely affected: `consistency.py`, `app.py`, `tests/test_consistency.py`.
   Acceptance criteria: duplicate node/source candidates are not silently overwritten; representative choice is deterministic; duplicate diagnostics appear in debug/export.
   Tests needed: duplicate Reach Final rows with different prices; duplicate market vs match sources; stable representative selection.
   Risk level: Medium.

2. Task name: Explicit pagination cap failure
   Why it should come next: partial API data is worse than a visible load error for a checker that reasons about missing layers.
   Files likely affected: `kalshi_client.py`, `tests/test_data.py` or a new client test file.
   Acceptance criteria: if `MAX_PAGES` is hit and a cursor remains, a `KalshiError` or surfaced error is produced.
   Tests needed: mocked `_get` returns `MAX_PAGES + 1` cursors; assert explicit failure.
   Risk level: Low.

3. Task name: Tournament fallback confidence hardening
   Why it should come next: date-window fallback can admit unrelated in-window tennis events, and the FO window is year-specific.
   Files likely affected: `data.py`, `tests/test_data.py`, maybe export/debug fields in `app.py`.
   Acceptance criteria: non-keyword in-window events are rejected or clearly marked as fallback/low-confidence; tests cover both keyword and fallback paths.
   Tests needed: explicit FO competition, FO title/rules keyword, non-FO in-window event, missing competition with in-window event.
   Risk level: Medium.

## Open Questions / Assumptions

- I treated the current local files as truth even when `CONTEXT.md` and `kalshi-plan.md` described work not present locally.
- `AUDIT_REPORT.md` was found and used.
- I did not modify production code, tests, or existing docs.
- I ran `pytest -q` to confirm current test status; it passed with 36 tests and a pytest cache warning.
- I did not make live Kalshi API calls.
- The current local branch is `docs/context-dump...origin/docs/context-dump`.
- `AUDIT_REPORT.md` is currently untracked in git status. This report does not assume whether it should be committed.

