---
topic: real-time-opportunity-engine
status: executing
active_milestone: s5-nicegui-dashboard
last_session: 2026-06-05
last_updated: 2026-06-05
session_focus: Free-tier refresh speedup MERGED — PR #86 (merge 5345d85, 2026-06-05) — in-process auto-scan scheduler (scan_scheduler.py, single loop/process, non-force) + dashboard Auto-refresh toggle/interval; MAX_RPS 5→15 (~75% Basic); stale rate docs swept. Key facts: full scan ≈49–51 GETs, polling floor ~1–3s (latency-bound), keys don't speed public data (only tier ceiling / WebSockets do). Single-process only; disable systemd scan.timer when scheduler on. Worked in SHARED tree (no other session active).
---

# Topic State: real-time-opportunity-engine

## Current Position

Un-parked 2026-06-03; executing the approved 6-stage roadmap
(`~/.claude/plans/make-me-a-multi-atomic-tower.md`). Detection groundwork (dutch-book detector incl.
per-game + multi-sport) already shipped on `main` via PR #35; Stage 0 (dashboard clarity) shipped too.

**Stages 1 & 2 MERGED to `main`** (PR #37, #38). s1 = opportunity schema + SQLite `store.py`. s2 =
`scanner.py` cross-sport aggregator (injected fetch) + additive toggle-gated UI + once-per-fetched_at
snapshot writes. 188 tests; verified offline + live + AppTest.

**Stages 1–4 MERGED to `main`** (PR #37/#38/#39/#40): opportunity schema+store, cross-sport scanner,
lifecycle, FastAPI engine API (`api.py`/`serve.py`/`fetch.py` + store schema v2). 224 tests.

**Stage 5 SHIPPED via PR #41** (awaiting merge): NiceGUI opportunity-first dashboard (`webui/dashboard.py`
+ `webui/engine.py`) mounted on the FastAPI app (`serve.py` via `ui.run_with`), engine in-process; +
`scanner` §0 enrichment for the explanation panel. Streamlit kept alongside. 231 tests; verified offline +
live serve boot + browserless render.

**Next milestone: NOT YET PLANNED.** Two candidates: (a) **deferred follow-up** — port the per-player
deep-dive to NiceGUI, then retire Streamlit (delete `app.py`, drop `streamlit`/`altair`), add a full-scan
toggle; (b) **s6 export overhaul**. Owner to choose order.

**Stage roadmap (→ milestones):** s1 ✅ · s2 ✅ · s3 ✅ · s4 ✅ · s5 NiceGUI dashboard ✅ · s6 export
overhaul *(next candidate)* · + deferred: per-player port + Streamlit retirement + full-scan toggle.

## Recent Decisions

- Un-park; NiceGUI mounted on FastAPI (FastAPI also exposes the engine as REST). First phase is pragmatic:
  REST + polling (WS later), gross-edge first (net-of-fees later). Engine-first sequencing.
- (Earlier) decouple into backend + thin clients; two-tier REST/WS funnel; NiceGUI-first frontend.

## Blockers

None for s1 (pure engine + local SQLite). Deferred end-state facts to verify before the WS/net-of-fees
phase (ROADMAP §6): exact Kalshi fee formula; WS max-subscriptions-per-connection; whether WS is metered
separately from REST.

## Next Action

- ✅ **Stages 1–4 MERGED** (PR #37/#38/#39/#40); s1–s4 closed (SUMMARYs + decisions promoted). Stage 4
  passed an extensive pre-merge battery (224 tests + live `uvicorn` boot) before the owner merged it.
- ✅ **Stage 5 BUILT & SHIPPED** (2026-06-04; PR #41, awaiting owner merge). NiceGUI dashboard mounted on
  the FastAPI app. **Pre-merge battery PASSED 2026-06-04:** `pytest` **235** (+4 dashboard-builder tests +
  an `explanation_lines` extraction for testability; pushed `06ea2a3`), `ruff` clean; live `serve.py` boot
  (`/` NiceGUI 200 + REST coexist + `POST /scan` 368 opps + TTL); browserless render (empty + populated,
  correct bucket split); Streamlit headless 200. Row-click→panel is content-tested via `explanation_lines`
  (literal click needs a real-browser Screen test — N/A in this env). **PR #41 verified — safe to merge.**
- ⏭️ **NEXT — after #41 merges:** `kss:complete-milestone` (close s5), then `kss:plan-milestone` for the
  owner's pick: **s6 export overhaul** OR the **deferred follow-up** (per-player port → Streamlit retirement
  → full-scan toggle) OR the new **detection-correctness/hardening** candidate (below).
- 🆕 **NEW candidate milestone — detection-correctness hardening** (designed 2026-06-04, no code yet):
  5-PR brief responding to an external "scanner ≠ arb certifier" audit. Full spec in
  `note-20260604-detection-correctness-audit.md`. Priority order: **(A)** dutch-book settlement caveat —
  fixes a real contradiction (dutch book claims "true arbitrage" on the same tennis markets the ladder
  flags as walkover/no-ball-risky); **(B)** sport-specific blockers (tennis void, WNBA qualify≠compete,
  TITLE fractional); **(C)** capture `mutually_exclusive`+`rules_secondary` (nowhere today; trivial at
  `data.py:629`); **(D)** transitive containment checks (missing-rung false-negative); **(E)** honest
  top-of-book/gross labels + small-edge advisory. Thematically also fits the paused `audit-hardening`
  topic. Two open decisions in the note (PR A conservatism on team sports; PR C ME-absent policy).
- 🆕 **NEW candidate milestone — NiceGUI hosted workflow parity** (designed 2026-06-04; **Stage 0 LAN access
  implemented but UNCOMMITTED**). Brings the NiceGUI dashboard to the same information as Streamlit `app.py`,
  **for IT hosting on the office LAN** (no-auth internal; scheduled `POST /scan`). This is the long-deferred
  "per-player port → Streamlit retirement" follow-up, now fully designed + expanded for hosting. Architecture:
  **store-everything-per-scan, zero view-time network** (one consistent `snapshot_id` per view). Full plan:
  `Concurrent Plans/nicegui-hosted-parity-plan.md`; session detail: `note-20260604-nicegui-hosted-parity-plan.md`.
  **Prereq (Stage 0.5):** fix `scanner.py:89–91` leg/URL swap (live bug in the panel). Next: commit Stage 0
  (once shared tree clear) → 0.5 → 1a/1b store v3 → s2 scan semantics → 3–7. Open: scan scope+interval
  (benchmark-gated), retention N, scan-token.
- 📌 **Standing owner to-do:** re-publish the 2 Google Docs (connector read-only) — **Project Brief** from
  `docs/PROJECT_BRIEF_OVERVIEW.md` (now the canonical brief) + **Technical Documentation** from
  `docs/TECHNICAL_DOCUMENTATION.md`. Docs reconciled to the built engine (s1–s5) on 2026-06-04 in PR #41.
