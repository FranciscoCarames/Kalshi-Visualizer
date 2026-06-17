---
last_updated: 2026-06-02
---

# Stack

## Languages

- Python 3.13 — entire codebase (app, data layer, tests)

## Frameworks

- Streamlit ≥1.40 — UI, sidebar controls, auto-refresh via `@st.fragment(run_every=...)`
- pytest ≥8.0 — unit tests for all pure modules + an AppTest UI smoke test (no network; ~95 tests)
- ruff ≥0.4 — lint + import sort (config in `pyproject.toml`)

## Package managers

- pip — runtime (`requirements.txt`), dev (`requirements-dev.txt`)

## Key dependencies

| Package | Version | Role |
|---|---|---|
| streamlit | ≥1.40 | UI, layout, fragments, caching (`@st.cache_data`) |
| requests | ≥2.32 | HTTP calls to Kalshi public API; session + HTTPAdapter |
| pandas | ≥2.2 | Contract and comparison DataFrames; filter passes |
| altair | bundled via Streamlit | Opportunity-ranking bar chart |
| decimal | stdlib | Exact integer-cent arithmetic (no float drift in comparisons) |
| ruff | ≥0.4 (dev) | Lint + import sort; `ruff check .` must pass clean |

## Build / run

- Dev: `streamlit run app.py`
- Test: `pytest -q`
- Lint: `ruff check .`
- Headless verify: `streamlit run app.py --server.headless true --server.port 8765` → check `/_stcore/health`
- Deploy: manual (no CI pipeline)

## Notable absences

- No Docker / containerisation
- No CI/CD pipeline
- No authentication (Kalshi market-data endpoints are public; trading is out of scope)
- No database or local storage (all data fetched live from Kalshi on each refresh cycle)
- No TypeScript / JavaScript frontend (pure Streamlit)

---
*Refreshed by map-codebase on 2026-06-02*
