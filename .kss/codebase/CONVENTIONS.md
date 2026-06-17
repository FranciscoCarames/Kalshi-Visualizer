---
last_updated: 2026-06-02
---

# Conventions

## Code patterns

- **Layer boundary is absolute:** `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` must never import Streamlit (or each other across the boundary). Only `app.py` imports Streamlit.
- **Exact cents for comparisons:** all comparison logic uses `data.to_cents()` (Decimal-backed integer); `data.to_float()` is display-only. Never `float()` a raw price field directly.
- **Two-pass filtering:** `universe = apply_membership(...)` → `thresholded = apply_thresholds(universe, ...)`. Actionable now reads `universe`; every other section reads `thresholded`. Full diagnostics reads `universe` (so finalized markets stay visible even with "Active only" default).
- **Fetch by family only:** the only control that changes what is fetched from Kalshi is the contract-family toggle. All other filters (tournament, participant, stage, etc.) are client-side against the already-fetched frame.
- **Pagination always looped:** `get_paginated` loops on the cursor until empty; raises if `MAX_PAGES` (100) is hit with a cursor still pending — no silent partial data.
- **Failed series surface in Debug, never silently dropped.**
- **Empty results are valid**, not errors (between rounds → no open events).

## Naming

- **Player identity:** use `player_key` (the stable `tennis_competitor` UUID) for grouping and de-duplication — never the display name. Two players with the same name never merge; one player's ladders across tournaments never cross.
- **Status strings are internal:** UI labels differ from status constants. `EXECUTABLE_VIOLATION` → "Actionable gross edge"; `DISPLAY_VIOLATION` → "Display inconsistency", etc.
- **Buy-only language everywhere:** "Buy YES" and "Buy NO" only. Never "sell", "short", or "long".
- **"Executable inconsistency", never "arbitrage":** true arbitrage requires identical settlement rules; match-alignment pairs carry `RULE_CHECK_REQUIRED`.

## Testing

- Framework: pytest ≥8.0, all tests in `tests/`
- Tests cover every pure module: `test_data`, `test_consistency`, `test_glossary`, `test_client`, `test_filters`, `test_viz`
- `test_app.py` is an `AppTest` UI smoke test — mocks the three `kalshi_client` network entry points and runs the real pipeline end-to-end, asserting `not at.exception`
- No network in tests — all Kalshi responses are mocked
- Run: `pytest -q` (~95 tests); lint with `ruff check .` (must pass clean)

## Gotchas

- **Streamlit caches imported modules.** After editing any non-`app.py` file, a browser "Rerun" won't pick up the change — fully stop and restart `streamlit run app.py`. For phantom `ImportError`, clear bytecode: `rm -rf __pycache__ tests/__pycache__`.
- **Kalshi prices are fixed-point dollar strings since Mar 2026** (`"0.6500"`, not `0.65`). Use `data.to_cents` / `data.to_float`, never `float()` directly.
- **Empty order book is `0.00/1.00`, never a real 50%.** Treat `yes_bid=0, yes_ask=1` as "No quote".
- **`no_ask == 1 − yes_bid` exactly** on Kalshi's unified book. No-side size fields don't exist; Buy-NO tradable size is `yes_bid_size`.
- **`pandas` truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- **Kalshi web site (kalshi.com) is bot-throttled** (HTTP 429 from this environment). `check_links.py` must be run from an unthrottled network.
- **Windows LF→CRLF git warnings** are harmless.

## Anti-patterns to avoid

- Don't gate `build_contracts` on French Open — all tennis events are in scope now; use `tournament_of()` for grouping.
- Don't group consistency ladders by display name — always `(player_key, tournament)`.
- Don't add a `WIDE_QUOTE` action plan — it's watchlist-only (ordering is consistent there).
- Don't run multiple Python processes with the assumption that the rate limiter is shared — it's PROCESS-WIDE ONLY.
- Don't use `float()` on any price comparison — use `Decimal`/`to_cents` throughout.

---
*Refreshed by map-codebase on 2026-06-02*
