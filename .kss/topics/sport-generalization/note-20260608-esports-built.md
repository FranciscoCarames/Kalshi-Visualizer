# Esports (10th sport) — BUILT — 2026-06-08

Branch `feat/esports-sport` (off `main` after the NFL merge #128). Clean `SportConfig` drop-in — v1 is
`sports.py` + `tests/test_esports.py` + docs only; **no engine edits** (esports reuses the NFL-added
`game_mece_by_shape` field, untouched, at its default `True`).

## What shipped (v1)
- One `register(SportConfig(sport_id="esports", …))` in `sports.py`: exact-ownership allow-list
  (`series_prefixes=()`, `exact_series=_ESPORTS_GAME | _ESPORTS_WINNER`), identity
  `custom_strike.esports_competitor`, `match_family=""`, `field_families={"winner"}`,
  `game_mece_by_shape=True` (draw-free → ungated dutch books, unlike NFL), empty ladder, per-title
  `divisions` (`division_label="Title"`).
- `KX*GAME` + `KX*MAP` → `"game"` family → 2-way dutch books (with per-game settlement caveat).
  Per-title winner series (`KXCS2`, …) → `"winner"` → field overround.
- `tests/test_esports.py` (12 tests): registration (10th sport), allow-list, excluded→nothing, labels,
  game + map dutch books, MECE-by-shape no-op (books with no rules text), winner overround, identity,
  grouping, fetch scope.

## Verification
- `pytest -q` → **663 passed** (651 + 12); `ruff check .` clean.
- `python -c "import serve, api, webui.dashboard"` OK; `serve.py` boot on **non-default port 8137**
  (loopback) → `/`, `/healthz`, `/metrics`, `/readyz` all 200 (`readyz` "degraded" = stale snapshot).
- Live `scripts/verify_sport.py esports` → 18 series, **302 contracts** (258 game / 44 winner), 0 false
  ladder rows. Live dutch-book sanity surfaced a real `KXCS2GAME` underround (1¢).

## Deferred (v2) — see [[note-20260608-esports-probe]] for the full exclusion list
Qualifier ownership + provable per-tournament ladders (needs a `qualifier` family + `UNKNOWN_RELATIONSHIP`
emission in `consistency.py`), opponent action labels + map caveat wording (`data.py`/`glossary.py`),
live excluded-series diagnostics + tag-aware discovery (`kalshi_client.py`), `/milestones` grouping,
event-specific majors (maintenance-heavy).
