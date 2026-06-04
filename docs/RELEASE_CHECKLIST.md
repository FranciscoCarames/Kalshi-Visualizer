# Release checklist — Kalshi Visualizer

A manual checklist to run before shipping/hosting a build. Pairs with `docs/DEPLOYMENT.md` (the office-LAN
hosting guide). The automated suite covers the engine + pure builders; the steps below cover the things a
headless test can't (real-browser interactions, live endpoints, bind safety).

## 1. Automated gates (must be green)
- [ ] `pytest -q` — full suite green (engine, dutch-book/synthetic detectors, viewmodel, API, **headless
      NiceGUI browser smoke tests** in `tests/test_browser.py`).
- [ ] `ruff check .` — clean.
- [ ] `python -c "import webui.dashboard, serve, app"` — imports clean.

## 2. Boots
- [ ] FastAPI + NiceGUI: `python serve.py` → `GET /` 200, `GET /healthz` 200, `GET /coverage` 200,
      `GET /metrics` 200 (JSON counters + scan heartbeat).
- [ ] Streamlit (legacy, still shipped): `streamlit run app.py --server.headless true --server.port 8765`
      → `/_stcore/health` 200.

## 3. Live scan + data
- [ ] `POST /scan?wait=true` (loopback) → 202; `GET /scan/status` → `done`; `GET /coverage` shows
      `meta_present: true` with non-zero counters.
- [ ] Dashboard `/` shows the scanned opportunities; the freshness/scope line updates.

## 4. Manual UI interactions (NOT covered by the headless User — real browser required)
- [ ] **Click an opportunity row** → the "🔬 Selected participant detail" panel fills (ladder / spreads /
      expected / all-contracts; charts for a containment row).
- [ ] **⬇ Export (ZIP)** downloads a snapshot zip (opportunities + per-sport frame CSVs + manifest).
- [ ] **AG-Grids** in "🔧 Diagnostics & debug" page/filter/sort (full-diagnostics + non-laddered).
- [ ] Filters narrow every section; "Clear filters" restores; the URL reflects the filter state.
- [ ] Auto-refresh: a new scan updates the tables without a manual reload.

## 5. Security / LAN exposure (only if hosting beyond loopback)
- [ ] `NICEGUI_STORAGE_SECRET` set to a long random string (serve.py refuses a non-loopback bind without it).
- [ ] **`SCAN_TOKEN`** set if `POST /scan` is reachable on the LAN: `POST /scan` without the header → 401;
      with `-H "X-Scan-Token: <value>"` → 202. The scheduled-scan caller sends the header.
- [ ] Single worker only (the snapshot store + Kalshi throttle + viewer count are process-local).

## 6. Docs / sign-off
- [ ] `README.md` + `CLAUDE.md` reflect the shipped feature set.
- [ ] Google Drive **Project Brief** (simple) + **Technical Documentation** (full) updated to match
      (standing rule — owner-triggered, since it publishes externally).
