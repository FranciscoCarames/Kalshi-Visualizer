# Audit Report

Date: 2026-06-01
Project: Kalshi Visualizer, local folder `C:\Users\Batata\Desktop\Internship`
Branch observed: `feat/spread-nan-fix...origin/feat/spread-nan-fix`

## Executive Summary

This local project is a read-only Streamlit app for French Open Kalshi market data. It fetches public market data, flattens player contracts, builds a progression ladder, runs layer-consistency checks, and displays raw adjacent ladder spreads. The read-only boundary looks intact: the only HTTP method used by application code is GET, no authentication or account access was found, and exports are generated through Streamlit download buttons rather than server-side writes.

The production test suite passes locally: `30 passed`. That result is not strong enough. Audit-only probes found five concrete failures in core edge cases: display-name player collisions can create false ladder comparisons, quote-size-missing crosses can be downgraded to display warnings, equivalence violation reasons can describe the wrong bid/ask direction, a configured women's winner ticker variant maps to ATP, and malformed crossed books are treated as Tight and usable.

The most important next coding task is to make all consistency grouping key-based (`player_key`, not display `player`) and add regression tests proving two players with the same display name cannot be compared.

## Current App Behavior

Based only on local code:

- `app.py` is the Streamlit entry point. It renders right-side controls, a main consistency table, per-player ladder details, raw stage-ladder spreads, exports, and a debug expander.
- `kalshi_client.py` is the read-only HTTP layer. It uses a shared `requests.Session`, GET requests, retry/backoff, pagination, and concurrent series fetches.
- `data.py` filters French Open events, classifies series, parses prices, assigns player keys, creates display prices, quote quality, and flattened contract rows.
- `consistency.py` maps contracts into logical nodes, builds expected nodes, picks representatives, computes ladder spreads, and builds consistency rows.
- `tests/test_data.py` covers price parsing, quote buckets, classification, round extraction, mapping confidence, and one synthetic match flattening path.
- `tests/test_consistency.py` covers status classification, rule flags, expected nodes, layer spreads, NaN handling, and representative selection.

Docs mostly match current behavior, but `kalshi-plan.md` is stale: it says PR #7 is pending and v1 ladder spreads are future work, while local code already includes raw ladder spreads and a larger 30-test suite.

## Read-Only Safety Assessment

Verdict: the project appears read-only.

Evidence:

- `kalshi_client.py:43` uses `_session.get(...)`.
- No application POST, PUT, PATCH, or DELETE calls were found.
- No API key, auth header, account, portfolio, order placement, buy, or sell code path was found.
- `.gitignore` excludes `.env`, `*.pem`, and `.streamlit/secrets.toml`.
- Export behavior in `app.py:307` and `app.py:311` uses `st.download_button`, not server-side file writes.

Caveats:

- The app still uses live network data by default, so deterministic smoke testing is weak.
- `requests.Response.json()` at `kalshi_client.py:55` can raise a non-`KalshiError` JSON decode exception.
- Failed series are surfaced in the UI debug expander, which is good.

## Architecture Map

- Config/constants: `config.py`
- App entry point/UI: `app.py`
- Data fetching: `kalshi_client.py`
- Data normalization: `data.py`
- Contract classification: `data.classify_kind`, `data.tour_of`
- Player grouping input: `data.build_contracts`
- Player grouping for checks: `consistency.build_checks`
- Quote/price handling: `data.to_float`, `data.to_cents`, `data.quote_quality`, `data.display_prob`, `data.display_cents`
- Ladder construction: `consistency.node_of`, `consistency.build_player_nodes`, `consistency.expected_nodes`
- Representative selection: `consistency.representative`
- Consistency checks: `consistency._classify`, `consistency.build_checks`
- Raw ladder spreads: `consistency.layer_spreads`
- Export/debug: `app.py` snapshot and CSV download buttons, debug expander

## Local Verification Results

Commands run:

- `git status --short --branch`
  - Result: branch `feat/spread-nan-fix...origin/feat/spread-nan-fix`; untracked `.audit_tmp/` after audit probes; warning: could not open `.pytest_cache/` due permission denied.
- `pytest -q`
  - Result: `30 passed, 1 warning in 2.91s`.
  - Warning: pytest could not create cache path under `.pytest_cache` due access denied.
- `python -m py_compile config.py kalshi_client.py data.py consistency.py app.py`
  - Result: passed.
- `python -c "import config, kalshi_client, data, consistency; print('core imports ok')"`
  - Result: passed.
- Headless Streamlit health:
  - Command used `python -m streamlit run app.py --server.headless true --server.port 8765 --browser.gatherUsageStats false`, then checked `http://localhost:8765/_stcore/health`.
  - Result: HTTP `200`, body `ok`.
- `pip check`
  - Result: `No broken requirements found.`
- Dependency import presence check:
  - Result: `streamlit`, `requests`, `pandas`, and `pytest` present.
- Lint/type/format checks:
  - No `pyproject.toml`, `setup.cfg`, `tox.ini`, `.flake8`, `ruff.toml`, `mypy.ini`, or pre-commit config found, so no configured lint/type/format command was run.

Standalone `import app` was not run because importing `app.py` executes the Streamlit script body and may call the live Kalshi data path outside a Streamlit runtime. The headless Streamlit health check is the safer app boot verification.

## Exploratory Audit Tests Run

Temporary audit-only file created:

- `.audit_tmp/test_audit_behavior.py`
  - Purpose: encode suspected edge cases without modifying production tests or production code.

Command:

- `pytest -q .audit_tmp`

Result:

- `5 failed, 2 warnings`.

Exploratory tests and outcomes:

- `test_build_checks_must_not_merge_distinct_player_keys_with_same_name`
  - Target: display-name grouping collision.
  - Expected: two different `player_key` values with the same display name must not be compared.
  - Actual: failed. A clean `Reach Final <= Reach Semifinal` comparison was built across different player keys.
- `test_quote_size_missing_should_not_be_hidden_by_display_violation`
  - Target: status precedence for price crosses with zero/missing size.
  - Expected: `QUOTE_SIZE_MISSING`.
  - Actual: failed with `DISPLAY_VIOLATION`.
- `test_equivalence_reverse_cross_reason_describes_actual_cross_direction`
  - Target: evidence string for reverse-direction equivalence crosses.
  - Expected: reason describes `parent bid 37c > child ask 35c`.
  - Actual: failed. Reason says `child bid 19c > parent ask 40c -> 2c`, which is false.
- `test_explicit_womens_winner_ticker_variant_maps_to_wta`
  - Target: configured women's winner ticker variant.
  - Expected: `data.tour_of("KXFOPENWMENSINGLE") == "WTA"`.
  - Actual: failed with `ATP`.
- `test_crossed_books_are_not_labeled_tight_or_used_for_display_midpoint`
  - Target: malformed bid/ask validation.
  - Expected: crossed book is not Tight and does not produce a midpoint display price.
  - Actual: failed. `quote_quality(0.60, 0.40)` returns `Tight`.

## Findings By Severity

### AUDIT-001

Severity: Critical
Confidence: High
Type: Observed bug
Area: Correctness, player grouping, consistency checks
Location: `data.py:317`, `consistency.py:314`, `app.py:93`

Problem: consistency checks group by display `player`, not stable `player_key`. `data.build_contracts` creates a stable key, but `consistency.build_checks` ignores it and uses `df.groupby("player")`.

Why it matters: two distinct players with the same display name, or a name fallback collision, can be merged into one ladder. That can create false `CLEAN`, `DISPLAY_VIOLATION`, or `EXECUTABLE_VIOLATION` rows across two different people.

Evidence: audit-only test `test_build_checks_must_not_merge_distinct_player_keys_with_same_name` failed. It created two `Alex Smith` rows with different UUIDs; the checker compared one player's Reach Final to another player's Reach Semifinal.

Reproduction: `pytest -q .audit_tmp`.

Suggested fix: group checks and player selectors by `player_key`, carry display name as a label, and treat missing/low-confidence keys explicitly.

Suggested regression test: build a DataFrame with two identical display names and different `player_key` values; assert no cross-key comparison is produced.

Estimated implementation size: medium.

### AUDIT-002

Severity: High
Confidence: High
Type: Observed bug
Area: Correctness, status precedence
Location: `consistency.py:230` to `consistency.py:239`

Problem: a price cross with missing/zero size can become `DISPLAY_VIOLATION` when display prices also cross. The repository instructions say a price cross with missing/zero size should be `QUOTE_SIZE_MISSING`.

Why it matters: the UI changes the group from `Missing data` to `Warning`, hiding the fact that executable status cannot be confirmed because order size is absent.

Evidence: audit-only test `test_quote_size_missing_should_not_be_hidden_by_display_violation` failed: child bid 37c crossed parent ask 35c, child bid size was zero, and the classifier returned `DISPLAY_VIOLATION`.

Reproduction: `pytest -q .audit_tmp`.

Suggested fix: in the `exec_gap > 0 and not sizes_ok` branch, return `QUOTE_SIZE_MISSING` regardless of display violation; include display gap in the reason as secondary context.

Suggested regression test: cross with zero child bid size and display child > parent must return `QUOTE_SIZE_MISSING`.

Estimated implementation size: small.

### AUDIT-003

Severity: High
Confidence: High
Type: Observed bug
Area: Correctness, UI evidence, debug output
Location: `consistency.py:211` to `consistency.py:232`

Problem: equivalence checks evaluate both directions but the reason string always reports `child bid > parent ask`. If the maximum executable gap came from the reverse direction, the displayed evidence is false.

Why it matters: the UI can claim an executable inconsistency using bid/ask numbers that do not cross. This directly undermines trust in the consistency table.

Evidence: audit-only test `test_equivalence_reverse_cross_reason_describes_actual_cross_direction` failed. The executable gap came from `parent bid 37c > child ask 35c`, but the reason said `child bid 19c > parent ask 40c -> 2c`.

Reproduction: `pytest -q .audit_tmp`.

Suggested fix: store direction metadata with each candidate gap, then build the reason from the selected candidate.

Suggested regression test: reverse-only equivalence cross should return `EXECUTABLE_VIOLATION` and mention parent bid/child ask.

Estimated implementation size: small.

### AUDIT-004

Severity: High
Confidence: High
Type: Observed bug
Area: Correctness, tournament filtering
Location: `config.py` winner ticker variants, `data.py:262` to `data.py:266`

Problem: configured women's winner ticker `KXFOPENWMENSINGLE` maps to ATP because `tour_of` only checks `KXWTA` prefix or the literal substring `WOMEN`.

Why it matters: if this configured ticker appears in a full scan, women's winner contracts can disappear under the default Women filter and appear under Men.

Evidence: audit-only test `test_explicit_womens_winner_ticker_variant_maps_to_wta` failed: expected WTA, actual ATP.

Reproduction: `pytest -q .audit_tmp`.

Suggested fix: make `tour_of` use explicit ticker maps for winner series, or add robust women/men pattern handling for all configured ticker variants.

Suggested regression test: every ticker in `FO_WINNER_TICKERS` is classified as the intended tour.

Estimated implementation size: small.

### AUDIT-005

Severity: High
Confidence: High
Type: Observed bug
Area: Price handling, malformed data
Location: `data.py:177` to `data.py:199`

Problem: crossed books where `ask < bid` are labeled as `Tight`, and `display_prob` can use the crossed midpoint.

Why it matters: a malformed or transient crossed book can be shown as high-quality price data. This can pollute display prices, ladder spreads, and consistency checks.

Evidence: audit-only test `test_crossed_books_are_not_labeled_tight_or_used_for_display_midpoint` failed: `quote_quality(0.60, 0.40)` returned `Tight`.

Reproduction: `pytest -q .audit_tmp`.

Suggested fix: add a guard for `ask < bid` and classify as invalid/malformed or missing quote; prevent midpoint display from crossed books.

Suggested regression test: bid 60c / ask 40c should not produce quote quality Tight and should not produce a display midpoint.

Estimated implementation size: small.

### AUDIT-006

Severity: High
Confidence: Medium
Type: Risk
Area: Correctness, duplicate handling, nondeterminism
Location: `consistency.py:66` to `consistency.py:74`, `kalshi_client.py:128`

Problem: `build_player_nodes` silently overwrites duplicate rows for the same node/source. Concurrent series loading means row order is not a stable correctness guarantee.

Why it matters: duplicate markets, overlapping series variants, or repeated player rows can change the chosen representative and therefore change both checks and spreads without warning.

Evidence: code uses `nodes.setdefault(node, {})[source] = row`, keeping only the last row per source.

Reproduction or suggested test: create two `advance` rows for Reach Final with different prices and assert duplicate handling is explicit.

Suggested fix: retain all candidates per node/source, choose a representative by a documented rule, and surface duplicate diagnostics.

Suggested regression test: duplicate node/source rows produce a deterministic representative and a debug flag.

Estimated implementation size: medium.

### AUDIT-007

Severity: Medium
Confidence: High
Type: Risk
Area: Data fetching, production readiness
Location: `kalshi_client.py:68` to `kalshi_client.py:77`

Problem: pagination stops after `MAX_PAGES` and returns partial data silently if a cursor still exists.

Why it matters: silent truncation is dangerous in an app whose primary job is to surface missing layers and failed series accurately.

Evidence: `for _ in range(MAX_PAGES)` exits and returns `items` without recording that a cursor remained.

Reproduction or suggested test: mock `_get` to return more than `MAX_PAGES` cursors and assert a `KalshiError` or warning is returned.

Suggested fix: after the loop, if `cursor` remains, raise or return a truncation error that the UI can surface.

Suggested regression test: pagination cap produces an explicit failure, not partial success.

Estimated implementation size: small.

### AUDIT-008

Severity: Medium
Confidence: Medium
Type: Risk
Area: Tournament filtering
Location: `data.py:130` to `data.py:150`

Problem: if no French Open keyword is present anywhere, any market timestamp inside the configured French Open window can make an event count as French Open.

Why it matters: unrelated tennis events during the same date range could contaminate ladders and player rows.

Evidence: `is_french_open_event` falls back to `_within_window(...)` without requiring any tennis/tournament corroboration.

Reproduction or suggested test: unknown competition, neutral title, timestamp inside the window should be reviewed. Current code returns true if a market has an in-window occurrence or close time.

Suggested fix: require an explicit tennis/competition signal before date-window fallback, or mark fallback rows with a low-confidence tournament reason in debug/export.

Suggested regression test: non-FO event inside date window with no keyword is rejected or flagged low-confidence.

Estimated implementation size: small to medium.

### AUDIT-009

Severity: Medium
Confidence: High
Type: Risk
Area: Testability, production readiness
Location: `app.py:73`

Problem: the Streamlit script loads data at top level. There is no deterministic sample-data mode or pure render path for CI smoke tests.

Why it matters: app import/smoke verification is tied to live network behavior, caches, and Kalshi availability. The health endpoint can return 200 without proving the script rendered data successfully.

Evidence: `df_all, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)` is top-level script execution.

Reproduction or suggested test: add a sample-data mode and run a headless render or app test without network.

Suggested fix: support a local fixture mode gated by an environment variable or function boundary, while keeping production default live and read-only.

Suggested regression test: app can render a synthetic one-player ladder without network.

Estimated implementation size: medium.

### AUDIT-010

Severity: Medium
Confidence: Medium
Type: Risk
Area: UI/product, missing data semantics
Location: `consistency.py:144` to `consistency.py:163`

Problem: `expected_nodes` expects every player that appears in any French Open data to have Reach Semifinal, Reach Final, and Win Tournament layers.

Why it matters: players with only early-round match rows, set-winner rows, exact-score rows, or partial data can be shown as missing the entire ladder, which may be technically true for the tracked ladder but noisy or misleading.

Evidence: the function unconditionally iterates `NODE_ORDER` for all `player_rows`.

Reproduction or suggested test: player with only a Round of 16 match should show a careful "not tracked" or "not expected for this contract set" state, not just missing ladder layers.

Suggested fix: distinguish "expected because player has ladder-market universe" from "tracked ladder absent from this selected data."

Suggested regression test: early-round-only player produces an explicit not-applicable or low-confidence expected-layer state.

Estimated implementation size: medium.

### AUDIT-011

Severity: Low
Confidence: High
Type: Improvement
Area: Tooling
Location: repository root

Problem: no configured lint, type, or formatting check exists.

Why it matters: bugs found here are exactly the kind of edge cases lint will not solve, but a small configured tooling baseline would prevent style drift and catch some dead code/import issues.

Evidence: no `pyproject.toml`, `ruff.toml`, `mypy.ini`, `.flake8`, `tox.ini`, or pre-commit config found.

Suggested fix: add minimal `ruff` or a documented "no lint configured" decision later. This requires owner sign-off because it adds a dependency.

Suggested regression test: CI command list includes whatever tooling is chosen.

Estimated implementation size: small.

## Existing Test Coverage Gaps

Covered reasonably:

- Basic price parsing.
- Empty 0/1 book handling.
- Quote quality buckets for normal bid <= ask cases.
- Display midpoint versus last fallback.
- Basic series classification.
- Basic match flattening and opponent extraction.
- Core consistency statuses.
- NaN handling for ladder spreads.
- Representative preference.

Missing or weak:

- No tests prove consistency grouping uses `player_key`.
- No tests for display-name collisions or name fallback collisions.
- No tests for configured winner ticker tour classification variants.
- No tests for crossed/malformed books.
- No tests for duplicate node/source rows.
- No tests for pagination truncation.
- No tests for Kalshi JSON decode failure.
- No tests for date-window false positives.
- No tests for UI filtering behavior.
- No deterministic app render test with sample data.
- No export snapshot schema regression test.

## Proposed Production Test Plan

Must-have:

- `test_consistency_groups_by_player_key`: consistency integration; two identical display names with different keys do not compare.
- `test_name_fallback_collision_is_marked_low_confidence_and_not_silently_merged`: data/consistency integration; fallback names collide; expected explicit risk or separate handling.
- `test_quote_size_missing_precedes_display_warning`: unit; crossed firm prices with zero size returns `QUOTE_SIZE_MISSING`.
- `test_equivalence_reverse_cross_reason`: unit; reverse equivalence cross reason names parent bid and child ask.
- `test_winner_ticker_tour_map_all_configured_variants`: unit; every `FO_WINNER_TICKERS` variant maps to intended ATP/WTA.
- `test_crossed_book_is_invalid`: unit; bid > ask cannot be Tight or produce display midpoint.
- `test_duplicate_node_source_deterministic`: unit/integration; duplicate Reach Final rows are surfaced and representative selection is stable.
- `test_pagination_cap_is_explicit_failure`: unit with mocked `_get`; no silent truncation after `MAX_PAGES`.
- `test_empty_dataset_ui_path`: smoke; no crash and clear empty state.
- `test_export_snapshot_schema`: integration; JSON contains mapping, expected layers, ladder spreads, contracts, and comparisons.

Should-have:

- `test_date_window_fallback_requires_corrobation`: unit; non-FO in-window event is rejected or flagged.
- `test_round_abbreviations`: unit; QF/SF/Final variants map as expected if live titles use abbreviations.
- `test_one_sided_book_no_display_without_last`: unit; one-sided books do not create fake midpoints.
- `test_no_quote_with_last_fallback_is_visibly_no_quote`: integration; display price can exist while quote quality remains No quote.
- `test_status_sort_order`: UI/dataframe logic; Broken, Warning, Missing, Unknown, Clean order is stable.
- `test_min_volume_uses_pair_volume`: unit; volume filter semantics are documented.
- `test_failed_series_are_present_in_debug_payload`: app/helper integration.
- `test_full_player_ladder_synthetic_clean`: integration; clean SF/Final/Win ladder creates expected checks/spreads.
- `test_full_player_ladder_synthetic_broken`: integration; executable and display violations are separated.

Nice-to-have:

- Lightweight fuzz for `to_float` and `to_cents`.
- Property-style check that `display_prob` never returns a midpoint for missing, one-sided, empty, or crossed books.
- Snapshot tests for column names used by exports and UI tables.
- Local fixture generator for a synthetic tournament subset.

## Suggested Fixes

Fix immediately:

- AUDIT-001: use `player_key` as the primary grouping and selection identity. Preserve display player as label. Add collision regression tests.
- AUDIT-002: return `QUOTE_SIZE_MISSING` for executable price crosses lacking positive sizes, even when display also crosses.
- AUDIT-003: carry direction metadata through executable comparison candidates and render truthful reasons.
- AUDIT-004: make tour classification explicit for all winner ticker variants.
- AUDIT-005: reject or flag crossed books before quote quality and display price selection.

Fix soon:

- AUDIT-006: preserve duplicate candidates and surface duplicate diagnostics.
- AUDIT-007: make pagination cap truncation explicit.
- AUDIT-008: mark or tighten date-window fallback.
- AUDIT-009: add deterministic local fixture/sample-data mode for app smoke tests.
- AUDIT-010: refine expected-layer language for early-round-only or non-ladder data.

Optional cleanup:

- AUDIT-011: add a minimal configured lint command after owner approval.
- Update `kalshi-plan.md` so local repository state matches current code.
- Add a short smoke script once deterministic sample mode exists.

## UI Review

What works:

- The UI keeps controls on the right and analysis on the left.
- The progression chain appears before raw stage-ladder spreads.
- The spread table labels percentage-point gaps as pp.
- The app avoids arbitrage language and uses executable inconsistency language.
- Debug expander surfaces failed series and raw fields.
- Per-player export includes contracts, comparisons, expected layers, and ladder spreads.

Problems:

- If AUDIT-001 happens, the UI can show a ladder assembled from different people with the same display name.
- If AUDIT-003 happens, the reason column can show impossible bid/ask evidence.
- Quote quality is shown, but crossed books are currently treated as Tight by the data layer.
- Missing layer and missing price states are present, but expected layers can be noisy for players without a ladder-market universe.
- Default filters exclude Match result rows, so alignment and unknown relationship rows are hidden until the user opts in. That is defensible, but the user may not realize match-alignment checks are off by default.

Simple UI improvements:

- Add `player_key` or a shortened key in debug/export and use it internally in selectors.
- Add an optional "show only inverted spreads" filter.
- Add an optional "show missing ladder data" filter.
- Add a visible malformed/crossed quote state if such data is encountered.
- Add clearer expected-layer text for "not present in selected data" versus "expected but missing."

## Simple Feature Suggestions

In scope for the simple-first roadmap:

- Deterministic sample-data mode for local smoke tests.
- Synthetic fixture library for full-player clean/broken ladders.
- Export schema regression tests.
- Show only inverted spreads filter.
- Show only missing layers/missing prices filter.
- Duplicate-contract debug panel.
- Tournament-filter confidence reason in debug/export.
- Audit/smoke command script once sample mode exists.

Out of scope for now:

- Trading, order placement, auth, account access.
- Alerts.
- Monte Carlo, Elo, de-vig, conditional probability models.
- Generic multi-sport framework.

## Recommended Next 3 Coding Tasks

1. Fix key-based player grouping and selectors, then add collision tests.
2. Fix consistency status/reason correctness for quote-size-missing and reverse equivalence crosses.
3. Harden price/ticker edge cases: crossed books and all configured winner ticker tour variants.

## Open Questions And Assumptions

- I assumed the local folder is the only source of truth and did not use GitHub or remote PR history.
- I did not make live Kalshi API calls except the Streamlit health endpoint against localhost. The stock tests are unit-only.
- The current branch is not `main`; I did not switch branches.
- `.pytest_cache` exists but is not writable by pytest in this environment.
- I kept `.audit_tmp/test_audit_behavior.py` because it materially documents the failing probes.

## Coverage Limitations

- I did not verify live Kalshi payloads or current production market shapes.
- I did not verify the browser-rendered Streamlit UI beyond the headless health endpoint.
- I did not inspect remote branches, PRs, or GitHub.
- I did not run lint/type/format tools because none are configured.
- I did not test under a clean virtual environment.

