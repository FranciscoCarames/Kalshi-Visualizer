---
topic: real-time-opportunity-engine
created: 2026-06-02
---

# Session Log: real-time-opportunity-engine

Newest sessions at top. One entry per session, terse.

## 2026-06-05 (later) — Free-tier refresh speedup: in-process auto-scan + UI toggle (PR #86, MERGED 5345d85)

**Plan:** `~/.claude/plans/warm-baking-stallman.md` (approved; 4 owner-revision rounds).
**Context:** owner asked "make the NiceGUI app as close to real-time as possible on the FREE tier."
Investigated live: a full cross-sport scan is only **~49–51 GETs** (~150–200ms each), so the artificial
`MAX_RPS=5` (~25%) was the bottleneck, NOT Kalshi. Polling floor is ~1–3s (latency-bound, 49 reqs ÷
concurrency × RTT); keys do NOT speed the public market-data path — they only raise the tier ceiling or
unlock WebSockets (true sub-second). Tier table: Basic 200 tok/s≈20 GET/s · Advanced 30 · Premier 100 ·
Paragon 200 · Prime 400.
**Did (one PR off current origin/main `2198ea9`):**
- `MAX_RPS` 5→**15** (~75% of Basic; 429 exp-backoff is the hard ban floor, honors Retry-After IF present
  — Kalshi may omit it). `SCAN_MIN_INTERVAL_SECONDS`→8; `UI_REFRESH_SECONDS`→10; new
  `AUTO_SCAN_INTERVAL_OPTIONS/DEFAULT_SECONDS/DEFAULT_ENABLED`.
- **`scan_scheduler.py` (new):** one process-wide daemon loop driving the NON-force scan; separate
  `_stop`/`_wake` Events (live reconfig, never stops); injected `scan_fn`; singleton **constructed but NOT
  started at import** (tests never spawn it). Started ONLY in `serve.py` `__main__` (not under test harness).
- Dashboard: **Auto-refresh switch + interval select** wired to the scheduler (server-wide shared state).
  Manual button stays non-force (PR S3); only token-gated `POST /scan?force=true` bypasses TTL.
- Swept every stale `MAX_RPS=5`/"~25%" → 15/~75% (kalshi_client, CLAUDE.md, TECHNICAL_DOCUMENTATION,
  DEPLOYMENT) + corrected 429/Retry-After wording + explicit single-process caveat. In-process scheduler
  documented as primary; systemd `scan.timer` = "safe but redundant", disable when scheduler on.
**Verified:** 493 pytest + ruff clean; new `tests/test_scan_scheduler.py` (9). Live boot — `/readyz`
`/docs` `/` 200; scheduler auto-scanned on startup → fresh **all-sports** snapshot incl. golf(543)+
soccer(253), 51 GETs, 0 failed.
**Also resolved:** "golf/soccer missing from the app" was NOT a bug — the dashboard renders
`store.latest()`, and the displayed snapshot (#8) was written by pre-sync code before golf/soccer were
registered. A fresh scan (now automatic) fixes it.
**Merged:** PR #86 → main `5345d85` (owner merged 2026-06-05); local main fast-forwarded, scan_scheduler.py
+ test now on main. Feature branch deleted after merge.
**Note:** worked directly in the SHARED tree (C:\Users\Batata\Desktop\Internship) on branch
`feat/nicegui-auto-scan-scheduler`, NOT an isolated worktree — no other session was active this time.

## 2026-06-05 — NiceGUI LAN GO-LIVE — 6 PRs SHIPPED (#79–#84) + docs (#85)

**Milestone:** — (hosting hardening; focused go-live plan, not a UNIFIED-PLAN phase)
**Plan:** `lan-go-live-plan.md` (this dir; source `~/.claude/plans/zippy-toasting-walrus.md`).
**Did:** Implemented it as 6 PRs off origin/main, ALL MERGED:
- **S1 #79** `/readyz` readiness (ready/degraded/not_ready + 503) — migration-free `store.db_writable`
  probe (never `_connect`/`_migrate`), pure `diagnostics.build_readiness`, reflects the last scan, no live
  Kalshi call.
- **S2 #80** env-overridable `SNAPSHOT_DB_PATH` — applied at `serve._apply_snapshot_db_path()` startup with
  a parent-dir check (NOT at config import; `config.py` stays import-free).
- **S3 #81** dashboard "Scan now" NON-force by default (respects the ScanManager TTL/cooldown); returns the
  full status so the button reports done/skipped/in-progress honestly. Force only via the token-gated HTTP.
- **S4 #82** Linux-first `docs/DEPLOYMENT.md` — systemd service + scan `.timer` + `scan.sh`, no day-one
  Docker, `/readyz`, NTP, `-wal`/`-shm` backup, single-process checks.
- **D #83** `scripts/build_deploy_repo.py` (AST import-graph allowlist → runtime-only, no Streamlit/tests/
  docs/state; pip-compile pinned reqs) + `deploy/` templates + `.gitattributes` LF guard.
- **S5 #84** dashboard UX: Blocked hidden by default, persistent selected-row highlight (cross-table
  dedup), resolution-criteria toggle (`rules_primary`), dark mode, a11y tooltips.
- **docs #85 (OPEN)** sync `CLAUDE.md`/`README.md`/`AGENTS.md`.

**Verify:** each PR full pytest + ruff + import/browser/build smoke on its own branch; merged main
(`2198ea9`) re-verified 484 pytest + ruff + app import (`/readyz` wired) + a real deploy build (24 modules)
+ fresh-import smoke. Every PR in an isolated worktree off origin/main, removed after push; the shared tree
and the `kalshi-impl` session were untouched.

**Already-on-main (verified, NOT rebuilt):** `bind_safety` storage-secret fail-hard, scan-token gate (#73),
`/metrics` (#25), WAL+busy_timeout (#19), ScanManager singleflight (#21b).

**Next:** IT/ops day-one (routable segment, stable IP/hostname, firewall LAN-only, `NICEGUI_STORAGE_SECRET`,
NTP, office-device acceptance per `DEPLOYMENT.md §5`) + owner decisions (SCAN_TOKEN on/off, reverse-proxy
auth, final port). Optional: generate the standing deploy repo + pinned `requirements.txt` (needs pip-tools).

---

## 2026-06-05 — PR 29 "Beyond the strict rule" (NiceGUI) — BUILT + MERGED (#78)

**Milestone:** — (NiceGUI follow-on, post-UNIFIED-PLAN)
**Did:** Built & merged a NiceGUI-only feature adding two opt-in sections past the strict <100¢ rule:
**risk-budget candidates** (containment near-miss — bounded loss, CONVEX upside; new `RISK_BUDGET_CANDIDATE`
status, containment-only, honest `tradable_now`, reuses `scenario_payoffs`) and **near-miss books** (dutch
over-cost — FLAT-payout watchlist; new `NEAR_MISS_DUTCH_BOOK`, strict-XOR-near-miss per event via
`_select_edge`/`payout_floor_c`). Both bands default 0 = pure no-op; scanner persists the full bands
(`config.RISK_BUDGET_MAX_LOSS_C=25`/`NEAR_MISS_MAX_OVER_C=5`), NiceGUI controls filter live (no rescan).
Integer cents only; new buckets isolated from the strict lifecycle/alerts/backlog. Plan went through 2
adversarial design-audit rounds (`~/.claude/plans/lazy-launching-robin.md`). **Verified:** 455 tests (14
new), ruff clean, headless boot, live scan = 378 risk-budget + 64 near-miss, fields round-trip store v3 +
REST API. Built in isolated worktree off fresh `origin/main`; worktree removed after merge. Full detail:
`note-20260605-pr29-beyond-strict-rule.md`. **Follow-up:** GDrive docs refresh (bundle w/ #77).

## 2026-06-04 — NiceGUI hosted workflow-parity plan (design) + Stage 0 LAN access shipped

**Milestone:** — (new candidate: NiceGUI hosted parity / Streamlit-retirement follow-up)
**Did:** Designed the full plan to bring the NiceGUI dashboard to the same information as Streamlit `app.py`,
**for IT hosting on the office LAN**. Plan hardened over 4 adversarial review rounds (60+ issues triaged).
Key architecture: **store-everything-per-scan, zero view-time network** (rejected per-viewer live-fetch to
guarantee one consistent truth). Implemented **Stage 0 LAN access** (env-driven `serve.py` bind +
`docs/LAN_ACCESS.md` + `docs/DEPLOYMENT.md` + `serve_lan.ps1`); verified live (`0.0.0.0:8010`, `/healthz` ok,
`/` renders) and the owner opened it on **Android over a phone hotspot** (office WiFi blocked it = client
isolation → must host on a routable server segment). Found a real bug: `scanner.py:89–91` leg/URL swap (Stage
0.5 prereq). **No code committed** — shared working tree with the m5 session (PR #42); commit Stage 0 once clear.
**Plan:** full text in `Concurrent Plans/nicegui-hosted-parity-plan.md` (+ `~/.claude/plans/jiggly-chasing-bachman.md`);
session detail in `note-20260604-nicegui-hosted-parity-plan.md`.
**Tasks moved:** none merged (design + uncommitted Stage 0).
**Notes:** plan v4 / store schema v3. Next: commit Stage 0 → Stage 0.5 leg/URL fix → 1a/1b store v3 → s2 scan
semantics → 3–7. Open decisions: scan scope+interval (benchmark-gated), retention N, scan-token.

## 2026-06-04 — Detection-logic correctness audit → scoped hardening brief (no code)

**Milestone:** —
**Did:** Stress-tested an external "you're a scanner not an arb certifier" audit as critical partner, then
turned it into a 5-PR brief for a future detection-correctness/hardening milestone. Key real bug: dutch
book claims "no rule caveat / true arbitrage" on the SAME tennis match markets the ladder flags as
walkover/no-ball-risky — internal contradiction. Other live findings: `mutually_exclusive`/`rules_secondary`
captured nowhere (trivial add at `data.py:629`); `build_checks` only walks adjacent pairs → missing-rung
false-negative. Rejected the audit's "riskless" strawman (word isn't in the code) + execution-grade
critiques (read-only app). Full brief in note.
**Tasks moved:** —
**Notes:** `note-20260604-detection-correctness-audit.md` (topic root — survives s5 closure)

## 2026-06-04 — Docs polish: PROJECT_BRIEF_OVERVIEW language + CLAUDE.md de-bloat

**Did:** (1) Rewrote `docs/PROJECT_BRIEF_OVERVIEW.md` language to be more human while fully professional
(one-line hook, narrative intros, concrete examples, parallel bullets, tentative verbs only in the ideas
section) — owner decided OVERVIEW is the canonical simple brief; `PROJECT_BRIEF.md` is a redirect.
(2) Condensed `CLAUDE.md` 506→414 lines: the engine was described 4× (architecture tree, engine section,
repository status, iteration history) — deduped to one role each; merged the two restart-after-edit notes
and the config-import-free / engine-vs-Streamlit / .db-gitignored notes; trimmed verbose tree comments +
iteration items 13–20. All hard-rule sections preserved verbatim.
**Carry-over:** OVERVIEW left uncommitted earlier for owner wordsmithing (owner wants to add more of their
own ideas); GDrive "Project Brief" should re-publish from OVERVIEW. [[keep-gdrive-docs-in-sync]]

## 2026-06-04 — Docs reconciled to the built engine (s1–s5)

**Did:** Reconciled README.md + CLAUDE.md + `docs/TECHNICAL_DOCUMENTATION.md` (3 parallel agents) +
`docs/PROJECT_BRIEF_OVERVIEW.md` (owner's new canonical brief — updated for s5) + `docs/PROJECT_BRIEF.md`
(→ redirect to OVERVIEW) + `.kss/PROJECT.md` (what-this-is, tech stack, topic status). Flipped FastAPI/
NiceGUI from "planned" → built; added store/scanner/lifecycle/api/serve/webui to architecture + file maps;
two entrypoints (`streamlit run app.py` | `python serve.py`); tests ~235. Owner decision: OVERVIEW is the
canonical simple brief. Docs-only (no code); committed to PR #41 (`01421db`).
**Carry-over (owner-only, manual):** re-publish the 2 Google Docs — **Project Brief** from
`docs/PROJECT_BRIEF_OVERVIEW.md` (now canonical) and **Technical Documentation** from
`docs/TECHNICAL_DOCUMENTATION.md` ([[keep-gdrive-docs-in-sync]]).

## 2026-06-04 — Stage 5 shipped: NiceGUI opportunity-first dashboard (PR #41)

**Milestone:** s5-nicegui-dashboard → SHIPPED (PR #41, awaiting merge)
**Did:**
- `scanner` §0: additive `UNIFIED_COLUMNS` enrichment (action_1/2_price_c, cost_c, ticker_1/2, url_2) for
  the explanation panel; both mappers + `test_scanner`.
- `webui/engine.py` (NEW): in-process accessors over store/lifecycle/scanner (reuse `api.fetch_dep()`).
- `webui/dashboard.py` (NEW): `@ui.page('/')` — per-second freshness strip, sortable Actionable/Blocked
  tables, recently-actionable backlog, clickable explanation panel (row→dialog), new-actionable +
  blocked-change alerts (polling), timezone/Show-IDs controls, honest "Scan now (core series)".
- `serve.py`: mount NiceGUI via `ui.run_with(api.app, mount_path='/')`; secret from env (config dev
  fallback only); `config` NICEGUI_STORAGE_SECRET_FALLBACK + UI_REFRESH_SECONDS; `requirements` += nicegui.
- Tests: new `test_webui.py` + `test_scanner` §0 → **231 pass**, ruff clean.
**Verified:** live `serve.py` boot — `/` NiceGUI dashboard (200) + REST coexists (no collision), `POST
/scan` → 368 opps; **browserless render** (NiceGUI `User` over the mounted app) executed `dashboard()`
clean with correct bucket split; Streamlit untouched (headless 200).
**Decisions:** keep Streamlit (retire later); opportunity-first core only; engine in-process (REST API for
external clients); honest core-series scan scope. User-fixture impractical here (async + no pytest-asyncio
+ ui.run_with) → engine-accessor unit tests + a live browserless render as the proof.
**Tasks moved:** s5 all 6 ✓. **Next:** after #41 merges, close s5 + plan **deferred follow-up** (port
per-player deep-dive → retire Streamlit → full-scan toggle) and/or **s6 export overhaul**.

## 2026-06-03 — Stage 4 shipped: FastAPI engine API (PR #40)

**Milestone:** s4-fastapi-api → SHIPPED (PR #40, awaiting merge)
**Did:**
- `fetch.py` (NEW): extracted `fetch_contracts` from `app.load_contracts` (now a thin cached wrapper) →
  the engine fetch is Streamlit-free and reusable by the API.
- `store.py` schema **v2**: `meta` coverage column; base CREATE includes it (fresh DBs complete) +
  staged `_migrate` (v1 → ALTER ADD COLUMN); `write_snapshot(meta=)`, `latest()`.
- `scanner.run_scan(fetch_fn, *, fetched_at)`: coverage aggregation (scanned/loaded/failed/excluded +
  per-sport/series errors) + unified frame; pure, partial-failure tolerant.
- `api.py` (NEW): FastAPI + Pydantic + thin handlers — /opportunities (+filters), /opportunities/{id}
  (404), /backlog, /coverage (honest, meta_present), /alerts, /healthz, POST /scan (store-backed TTL
  guard: skip → skipped:true + no duplicate write; force overrides). Overridable db/fetch deps → no
  network in tests. `serve.py` uvicorn entrypoint; config API_HOST/PORT/SCAN_MIN_INTERVAL_SECONDS;
  deps fastapi/uvicorn[standard]/pydantic (+httpx dev).
- Tests: new test_api.py + test_store (both migration paths + meta + latest) + test_scanner (run_scan)
  → **223 pass**, ruff clean, streamlit headless 200. Live uvicorn boot: /docs+/healthz 200, POST /scan
  → 367 opps / 18 series / 0 failed, /coverage honest, re-scan skipped by TTL guard.
**Method:** plan-mode plan (2 review rounds — explicit fresh/v1 migration tests; store-backed TTL guard
returning skipped without duplicate) approved; branch `feat/s4-fastapi-api` off `main` (s3/PR#39 merged).
**Tasks moved:** s4 all 8 ✓. **Next:** after #40 merges, close s4 + plan **s5-nicegui-dashboard**
(NiceGUI mounted on the FastAPI app; consumes these endpoints; Streamlit cutover/retirement).

## 2026-06-03 — Stage 3 shipped: lifecycle engine (PR #39)

**Milestone:** s3-lifecycle → SHIPPED (PR #39, awaiting merge)
**Did:**
- `lifecycle.py` (NEW, pure — snapshots passed in, state derived from history, NO DB migration):
  `new_actionable`, `persisting_new_actionable` (full-history window filter — avoids windowed-slice
  false "new"), `blocked_change` (§9 what-changed), `recently_actionable` (§10 backlog,
  reason_left precedence disappeared→leg inactive→blocked→clean), `first_seen` (numeric ts).
- Persisted the diff inputs additively: `scanner.UNIFIED_COLUMNS` += `rule_flag` + normalized
  `market_status`; `dutchbook._detect_pair` emits `market_status` from `both_active`.
- config: BACKLOG_WINDOWS/DEFAULT + ALERT_PERSISTENCE_OPTIONS. glossary: 3 lifecycle terms.
- app.py (toggle-gated cross-sport section): persistent new-actionable banner + "New" flag column
  (safe latest_two normalization), windowed TZ-aware recently-actionable table, minimal
  changed-while-blocked table.
- Tests: new test_lifecycle.py + scanner/dutchbook field assertions → **203 pass**, ruff clean,
  headless 200 (python -m streamlit), AppTest renders the lifecycle UI, live prev/cur smoke on the real
  persisted schema (blocked_change + recently_actionable correct).
**Method:** plan-mode plan `~/.claude/plans/immutable-gathering-valiant.md` (3 review rounds — banner
persistence, numeric first_seen, market_status field, blocked-change UI, safe latest_two, full-history)
approved; branch `feat/s3-lifecycle` off `main` (s2/PR#38 merged first).
**Tasks moved:** s3 all 8 ✓. **Next:** after #39 merges, close s3 + plan **s4-fastapi-api** (expose the
engine — scanner/store/lifecycle — as a typed REST API; the seam NiceGUI consumes at s5).

## 2026-06-03 — Stage 2 shipped: cross-sport scanner (PR #38)

**Milestone:** s2-cross-sport-scanner → SHIPPED (PR #38, awaiting merge)
**Did:**
- `scanner.py` (NEW, pure — Streamlit-free + network-free via injected `fetch_fn`):
  `unified_opportunities(fetch_fn, store_writer, fetched_at)` aggregates `build_checks` +
  `find_dutch_books` across `sports.all_sports()` into one frame, stamps `sport`, normalizes both row
  shapes onto `UNIFIED_COLUMNS`, ranks `(bucket_priority, -gross_edge_c, opportunity_id)`; per-sport
  failure recorded not fatal; first real caller of `store.write_snapshot`.
- `filters.apply_membership`: `sports` filter (no-ops when `sport` column absent).
- `app.py`: additive, toggle-gated "All loaded markets — cross-sport" table (default off; single-sport
  dashboard untouched); cached load_contracts as fetch_fn; once-per-fetched_at snapshot; refresh clamp.
- Tests: new `test_scanner.py` + `test_filters` ext → **188 pass**, ruff clean, headless 200. Live
  cross-sport scan: 366 opps / 3 sports / real actionable NBA dutch book / snapshot round-trip.
**Method:** plan-mode plan (`~/.claude/plans/immutable-gathering-valiant.md`) approved; built on branch
`feat/s2-cross-sport-scanner` off `main` (s1/PR#37 merged first).
**Tasks moved:** s2 all 8 ✓. **Next:** after #38 merges, close s2 + plan **s3-lifecycle** (alerts +
recently-actionable; consumes the snapshots s2 now writes).

## 2026-06-03 — Stage 1 shipped: opportunity schema + SQLite store (PR #37)

**Milestone:** s1-opportunity-schema-store → SHIPPED (PR #37, awaiting merge)
**Did:**
- `data.opportunity_id(*parts)` — one shared deterministic sha1 helper (no randomness/time).
- `consistency.build_checks/_row`: stamp `relationship_type` (containment_adjacent | match_alignment),
  stable `opportunity_id`, `bucket`, and required `blocked_reason` (non-empty IFF bucket==blocked).
- `dutchbook._detect_pair`: same four; relationship_type "dutch_book"; id = check|event|sorted(keys)
  (leg-order-independent); bucket = actionable if tradable else blocked.
- `store.py` (NEW): standalone SQLite snapshot store — pure stdlib, no Streamlit/pandas import
  (DataFrame duck-typed). write_snapshot/latest_two/snapshots_since + PRAGMA user_version migration +
  retention (relative to newest snapshot). Promoted indexed cols + full-row JSON blob (NaN-safe).
- config: SNAPSHOT_DB_PATH + SNAPSHOT_RETENTION_SECONDS (import-free); .gitignore *.db.
- Tests: new test_store.py + extensions → **180 pass** (+22), ruff clean, headless 200.
**Open questions resolved:** id recipe node/stage-based (survives representative flips), unmapped-match
rows disambiguate on event ticker (collision test added); full JSON blob carries every §9 field;
dutchbook→data acyclic.
**Tasks moved:** s1 all 7 tasks ✓. **Next:** plan + build s2-cross-sport-scanner (kss:plan-milestone).

## 2026-06-03 — S9 doc reconciliation shipped (PR #36)

**Milestone:** s1-opportunity-schema-store (planned — still no s1 tasks started)
**Did:**
- Executed **SEED S9**: reconciled all 4 stale docs (`README.md`, `docs/PROJECT_BRIEF.md`,
  `docs/TECHNICAL_DOCUMENTATION.md`, `CLAUDE.md`) from "French Open tennis only / 2026-06-02" to current
  `main` reality — multi-sport (tennis+NBA+WNBA via `sports.py`), dutch-book detector (incl. per-game),
  Stage 0 clarity; NiceGUI/FastAPI roadmap labelled **planned, not built**. Folded in m1.1 task #5
  (CLAUDE.md per-game dutch-book flipped out-of-scope → in-scope).
- Method: 4 parallel sonnet agents (one per doc). Verified facts against code (`pytest --collect-only` →
  **158**; `sports.py`/`dutchbook.py` identifiers confirmed). Docs-only — no code touched; imports clean.
- Branch `docs/reconcile-multisport-s9` → **PR #36** (awaiting owner merge).
**Tasks moved:** S9 done (PR #36)
**Carry-over:** re-publish the 2 Google Docs manually from the updated `docs/` mirrors **after #36 merges**
(connector read-only). Then build s1.

## 2026-06-03 — Un-parked; Stage 0 shipped; 6-stage NiceGUI/FastAPI roadmap planned

**Milestone:** s1-opportunity-schema-store (planned)
**Did:**
- Shipped **Stage 0** (dashboard clarity: TZ/Lisbon, per-second freshness+coverage strip, Show IDs &
  codes toggle, debug/diagnostics behind Advanced, ranking graph removed; live data-age fix). Integrated
  with the full feature set (NBA-depth + WNBA + dutch-book + per-game) into `feat/complete-v1` → **PR #35,
  MERGED to `main`** (feature-complete, 158 tests).
- Reworked the roadmap to **NiceGUI mounted on FastAPI** (FastAPI also exposes engine as REST), engine-
  first, gross-edge-first → `~/.claude/plans/make-me-a-multi-atomic-tower.md` (saved & approved).
- Organized in kss: closed `full-tennis-coverage` **m1.1** (shipped-with-gaps via #35), **un-parked this
  topic**, scoped **s1** (opportunity_id + relationship_type + required blocked_reason + SQLite store.py).
- Carry-over: Google Drive docs need manual re-publish (connector read-only); `docs/TECHNICAL_DOCUMENTATION.md`
  still lists dutch-book/WNBA as "planned" — reconcile to built; CLAUDE.md per-game scope note (m1.1 #5).
**Tasks moved:** s1 planned (no tasks started yet)
**Notes:** —

## 2026-06-02 — Roadmap drafted, topic created

- Acted as trader/architect brainstorming partner; questioned UI, frontend (Streamlit), backend, scope.
- Collected roadmap parameters via AskUserQuestion: small private group · few-second latency · read-only
  now (auto-execution very-long-term) · all sports + all Kalshi categories.
- Verified live Kalshi facts: WS feed exists (`wss://external-api-ws.kalshi.com/trade-api/ws/v2`,
  channels ticker/trade/orderbook_delta) but **every WS connection needs API-key auth**; REST tiers
  (Basic 200 read tok/s ≈ 20 GET/s … Prime 4000); unified book ⇒ no within-market arb.
- Core theses: (1) net-of-fees edge is non-negotiable; (2) dutch-book/sum-to-one detector generalizes
  the tennis ladder to all categories; (3) the three user choices break the Streamlit monolith → shared
  backend + thin clients; (4) two-tier funnel (REST scan-wide / WS stream-narrow).
- Wrote full plan to `docs/ROADMAP.md` (Phases 0–4). No code changes.
- Created this topic and parked it (build deferred). Next: `plan-milestone` for Phase 0 when starting.
