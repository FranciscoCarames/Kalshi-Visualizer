---
last_updated: 2026-06-02
---

# Structure

## Top level

| Path | Role |
|---|---|
| `app.py` | Streamlit UI only — sidebar, auto-refresh fragment, all dashboard sections, Altair chart |
| `config.py` | All constants — BASE_URL, rate-limit knobs, refresh options, thresholds, tennis series lists |
| `kalshi_client.py` | Read-only HTTP — paginated GET, process-wide throttle, retry/backoff, series discovery |
| `data.py` | Pure parsing — pricing helpers, `build_contracts()`, `tournament_of()`, URL builder; no Streamlit/pandas |
| `consistency.py` | Layer checker — `build_checks()`, `bucket_of()`, action plans, `layer_spreads()`; no Streamlit |
| `glossary.py` | Single-source help text — `GLOSSARY`, `BLOCKERS`, `COLUMN_HELP`, `help_for()`; no Streamlit |
| `filters.py` | Two-pass filters — `apply_membership()` / `apply_thresholds()`; no Streamlit |
| `viz.py` | Chart data prep — `opportunity_ranking()` tidy frame; no Streamlit |
| `conftest.py` | pytest fixtures shared across test modules |
| `requirements.txt` | Runtime deps: streamlit, requests, pandas |
| `requirements-dev.txt` | Dev/test deps: extends requirements.txt + pytest + ruff |
| `pyproject.toml` | ruff lint/format config (line-length 120, E/F/W/I rules) |
| `tests/` | Unit tests for every pure module + `test_app.py` (AppTest UI smoke test); no network |
| `scripts/` | Dev utilities: `export_glossary.py`, `check_links.py` |
| `docs/` | `GLOSSARY.md` (generated); `audit/` (point-in-time audit reports); `historical/` (archived plans + CONTEXT.md) |
| `.kss/` | kss planning shell |

## Key paths to know

- `data.py:build_contracts` — entry point that fetches + parses all tennis contracts into a flat list of dicts; stamps `tournament`, `player_key`, `kind`, pricing fields, `kalshi_url`
- `consistency.py:build_checks` — groups contracts by `(player_key, tournament)`, runs containment + match-alignment checks, returns a flat DataFrame of comparison rows
- `consistency.py:bucket_of` — routes each comparison row to its dashboard section (actionable / blocked / near_edge / display_signal / wide_signal / data_quality / clean)
- `filters.py` — `apply_membership` narrows all sections; `apply_thresholds` narrows everything except Actionable now
- `app.py:render_dashboard` — the `@st.fragment(run_every=...)` that wraps the entire render + data-fetch cycle (called at the end of `app.py`)
- `glossary.py` — single source of truth for every piece of user-facing help text and blocker reason

## Where state lives

| File | Purpose |
|---|---|
| `config.py` | All tunable constants (edit here to change thresholds, rate limits, refresh cadence) |
| Streamlit session state | Sidebar control values (scan_all default, auto-refresh interval) — ephemeral, not persisted |
| `@st.cache_data` | Series list (TTL 3600s) and contract list (TTL `config.REFRESH_TTL = 30s`) |

---
*Refreshed by map-codebase on 2026-06-02*
