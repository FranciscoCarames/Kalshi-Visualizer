---
milestone: s5-nicegui-dashboard
topic: real-time-opportunity-engine
created: 2026-06-04
last_updated: 2026-06-04
status: planned
---

# Milestone Plan: s5 — NiceGUI opportunity-first dashboard

> Stage 5 of the roadmap. Full design + verification: `~/.claude/plans/immutable-gathering-valiant.md`.
> Builds on s4 (FastAPI API + engine, PR #40 merged). The roadmap's final UI home (I1, I2, I4–I10).

## Goal (one sentence)

Build the opportunity-first, cross-sport dashboard in **NiceGUI mounted on the FastAPI app** (`serve.py`),
calling the engine in-process — Actionable/Blocked tables, recently-actionable backlog, a clickable
explanation panel, new-actionable + blocked-change alerts, a per-second freshness strip, and a Scan
button — keeping Streamlit alongside (retire later).

## Success Criteria

- [ ] NiceGUI dashboard at `@ui.page('/')` mounted via `ui.run_with(api.app, mount_path='/', storage_secret=…)`;
      `serve.py` runs it; REST endpoints still 200 (coexist).
- [ ] Opportunity-first cross-sport: coverage/freshness strip with a per-second `ui.timer`; sortable
      Actionable + Blocked `ui.table`s; recently-actionable backlog (window selector); clickable
      explanation panel (legs/prices/edge/size/profit/relationship/links — from the enriched row).
- [ ] Alerts: new-actionable (`ui.notify` + "🆕" tag) + blocked-change marker via polling; persistence selector.
- [ ] Controls: timezone (Lisbon), Show-IDs, Advanced, sport filter, **Scan now** (labelled **core series**
      honestly), auto-refresh interval, optional auto-scan toggle.
- [ ] `scanner.UNIFIED_COLUMNS` enriched (additive, no migration) so the panel has numeric leg prices,
      cost, per-leg tickers + second link; `test_scanner` asserts the new fields.
- [ ] Streamlit untouched (kept); secret via `NICEGUI_STORAGE_SECRET` env (config holds only a dev fallback).
- [ ] Tests green (`test_webui.py` engine-accessors + NiceGUI `User`-fixture smoke or TestClient `/` 200);
      ruff; live `serve.py` boot serves `/` (NiceGUI) + REST 200 + `POST /scan` populates; Streamlit regression 200.

## Out of Scope

- No per-player deep-dive (ladder/payoff/spreads/diagnostics) — **deferred follow-up** (port later).
- No Streamlit retirement / `app.py` deletion this milestone (kept until parity confirmed).
- No full-scan scan-scope (core series only this milestone; full-scan toggle deferred).
- No auth, no custom JS, no net-of-fees, no live Kalshi WebSocket feed (REST polling; NiceGUI's own
  browser connection is inherent/expected).

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `scanner.py` §0: enrich `UNIFIED_COLUMNS` (action_1/2_price_c, cost_c, ticker_1/2, url_2) + both mappers; `test_scanner` asserts | ✓ |
| 2 | `webui/engine.py`: in-process accessors over store/lifecycle/scanner; reuse `api.fetch_dep()` | ✓ |
| 3 | `webui/dashboard.py`: `@ui.page('/')` — freshness strip (ui.timer 1s), Actionable/Blocked tables, backlog, explanation panel, alerts, controls | ✓ |
| 4 | `serve.py`: mount NiceGUI on `api.app` (env storage secret); `config` fallback+UI_REFRESH_SECONDS; `requirements` += nicegui | ✓ |
| 5 | `tests/test_webui.py`: engine accessors over tmp-seeded store + dashboard import smoke (User-fixture impractical — async/no pytest-asyncio + ui.run_with) | ✓ |
| 6 | Verify: pip install nicegui, pytest + ruff, live serve boot, browserless render, Streamlit regression 200 → **PR #41** | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

**SHIPPED 2026-06-04 via PR #41** (awaiting owner merge). 231 tests, ruff clean. Live `serve.py` boot: `/`
serves the NiceGUI dashboard (200) + REST coexists at `/` (no collision; `/healthz` JSON, `/docs`,
`/opportunities` 200); `POST /scan` → 368 opps / 18 series / 0 failed. **Browserless render** (NiceGUI
`User` over the mounted app) executed `dashboard()` with no error — sections/controls render, Actionable
table populated with correct bucket split. Streamlit untouched (headless 200). Open questions resolved:
mount `/` coexists fine; User-fixture impractical here → engine-accessor unit tests + live render as the
proof; honest core-series scan label.

## Open Questions

- Mount path `/` vs API coexistence (fall back to `/api` namespace only if a collision surfaces).
- NiceGUI test depth in this env: `User` fixture (preferred) vs TestClient `/` 200 smoke; engine/API tests stay the backbone.
- Auto-scan default off (manual Scan now); honest "core series" scan-scope label; full-scan toggle deferred.

## Notes

- Stage 5 spec: `~/.claude/plans/make-me-a-multi-atomic-tower.md`. NiceGUI docs ref: `/zauberzeug/nicegui`
  (`ui.run_with` mount, `User`-fixture testing, `ui.table`/`ui.timer`/`ui.notify`).
- **Build prerequisite:** branch off `main` (PR #40 merged ✓). `nicegui` not installed → `pip install` (sandbox off).
- **Deferred follow-up milestone(s):** port the per-player deep-dive to NiceGUI, then retire Streamlit
  (delete `app.py`, drop `streamlit`/`altair`); add a full-scan scan-scope toggle.

---
*Planned via plan-milestone on 2026-06-04*
