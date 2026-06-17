---
topic: unified-plan-build
created: 2026-06-04
---

# Session Log: unified-plan-build

Newest sessions at top. One entry per session, terse.

## 2026-06-05 — Session close: milestone `phase-f-followons` COMPLETED

- Ran `complete-milestone`: wrote `milestones/phase-f-followons/SUMMARY.md` (status: shipped), appended to
  MILESTONES.md, logged seeds S5–S8 (advancement-FIELD, field-underround, K-of-N, GDrive refresh), reset
  topic STATE → between-milestones and project `.kss/STATE.md` → active_milestone null (it was badly stale
  at phase-e). **UNIFIED-PLAN core (Phases A–F) complete**; `origin/main` #76, PR #77 (docs) open.
- Next session: `plan-milestone` for new work, or `complete-milestone --archive-topic` to retire the topic
  if the seeds aren't wanted. GDrive docs refresh pending once #77 merges.

## 2026-06-05 — Phase F PR 28: known-limits documentation (PR #77)

- #76 (winner field) merged → `origin/main` `d9c9be6`. Shipped the **known-limits docs** (synthetic P5),
  the quick item that closes the plan's CORE Phase F. Docs-only, no detector change.
- New single-sourced glossary term **"Known limits"** (gross + top-of-book; net-of-fees / position-limits-
  &-collateral / full-depth execution all documented-not-modeled). README "Known limits (not modeled)"
  section; GLOSSARY.md regen (17 terms). tech-doc §16: +3 known-limits bullets AND corrected 3 stale
  bullets recent PRs invalidated (dutch-book n-outcome coverage, sport set incl golf/soccer, snapshot
  retention). CLAUDE.md pricing-model note + Phase F status refreshed. 441 pytest, ruff clean. Branch
  `feat/p30-known-limits-docs` off `d9c9be6` → **PR #77** (open).
- **Phase F CORE COMPLETE** (27a advance hedge #75 merged, 27b winner field #76 merged, 28 docs #77 open).
  Remaining = SEEDS only (advancement-FIELD detector, field underround — both need an exhaustiveness proof)
  + owner-gated PR 11. **NEXT:** after #77 merges, `complete-milestone`; GDrive docs refresh (standing
  rule) pending across 27a/27b/28.

## 2026-06-05 — Phase F PR 27b: tournament-winner FIELD dutch book (PR #76)

- #75 (advance hedge) merged → `origin/main` `ec46d59`. Continued Phase F with the **n-outcome FIELD
  detector** (winner field, issue #6).
- **Live discovery gate** (raw /events): all winner fields are `mutually_exclusive=True` (KXFOMEN 68,
  KXFOWOMEN 59, KXNBA 30, KXWNBA 15, KXPGATOUR 106) but list FEWER markets than the draw → **not
  exhaustive**. Forces the safety asymmetry: **underround unsafe (never emitted); overround-only.**
- **Key insight:** overround is safe on ANY priceable SUBSET of a mutually-exclusive set (buy NO on k
  legs pays ≥(k-1)*100; an untraded/unlisted winner only pays more). So trade the priceable legs (firm
  no-side price + yes_bid>0), skipping empty-book longshots — `gap = Σ yes_bid(subset) - 100`. This
  sidesteps the "one empty book kills the whole field" problem and is gap-maximal.
- `dutchbook.py`: `prove_field_mece` (ME, ≥3 distinct, exhaustive=False), `_field_overround_subset`,
  `_detect_field` (overround-only, floor (k-1)*100, **event-keyed stable id**, `field_overround` advisory
  caveat), `_is_field_row` + separate grouping in `find_dutch_books`. 2-way + soccer paths byte-identical.
  Scanner generic (legs flow through); app/webui/glossary headings generalized; GLOSSARY regenerated.
- **+13 tests, 441 pytest, ruff clean, headless boots 200.** Live smoke: 353 winner rows / 6 fields all
  evaluated to overround pricing, zero false positives (efficient markets). Branch
  `feat/p29-winner-field-dutchbook` off `ec46d59` → **PR #76** (open).
- **NEXT:** PR 28 (known-limits docs, quick) and/or the advancement-field detector + field-underround
  (seeds needing an exhaustiveness proof). PR 11 = owner decision. GDrive docs refresh still pending.

## 2026-06-05 — Phase F PR 27a: advancement-hedge synthetic detector (PR #75)

- **Baseline re-reconciled:** UNIFIED-PLAN + the older LOG/STATE were stale (narrate to ~#57, assume #47).
  Reality: `origin/main` is at **#74** — **Phases A–E (PRs 1–26) ALL merged** (m1 #48–50, transitive #51,
  golf #52, soccer #53–55, synthetic capture/gates/labeling/caveat/leg-schema/review-bucket #56–61, full
  NiceGUI parity #62–74). Only Phase F + owner-gated PR 11 remain. `README.md:215` confirms remaining =
  "follow-on detectors (advancement hedge + n-outcome FIELDs) + known-limits docs."
- **Owner picked PR 27a (advancement-hedge detector); chose emit-both-hedges-independently.** Built on
  `synthetic_bundle.py`: a score bundle ("wins this match") is now also hedged against the advance/win-
  tournament market at the node the match implies (QF win ≡ Reach Semifinal; Final ≡ Win Tournament — the
  match_alignment equivalence). hedge_kind ∈ {match, advance}; match keeps the 4-part opportunity_id,
  advance uses 6-part. Extra caveat `synthetic_settlement_advance` (advance on a walkover ≠ winning a
  match). Review-only, never Actionable.
- **Two live-smoke-driven correctness fixes beyond the plan:** (1) `_advance_hedge_index` keyed by
  tournament (no cross-tournament mis-join); (2) close-time-sync gate scoped to the SCORE legs for advance
  — an advance market's scheduled close is the later stage's date but it settles on THIS match, so the
  score-vs-advance gap is expected (without this, EVERY advance hedge was wrongly close-time-suppressed).
- `synthetic_bundle.py` kept pandas-free via a local `_node_of` (mirrors `consistency.node_of`). scanner +
  app.py labels generalized to "match-winner / advance". Docs: README, CLAUDE.md, new tech-doc §9c, regen
  GLOSSARY.md. **+13 tests, 429 pytest pass, ruff clean, headless boots 200.**
- **Live smoke** (KXATPEXACTMATCH/ADVANCE/MATCH + WTA + winner): advance hedge resolves to the correct
  single market (FO Semifinal bundle → Reach Final hedge), no longer close-time-suppressed, both directions
  priced (fwd 101¢/100¢, rev 303¢/300¢ → no edge), zero false positives. Branch `feat/p28-advance-hedge`
  off `origin/main` `f8f84fe` → **PR #75** (open, awaiting owner merge).
- **NEXT:** PR 27b (n-outcome FIELD detectors — bigger, needs field-completeness proof + live gate) or the
  quick PR 28 (known-limits docs). PR 11 = owner decision. GDrive docs refresh still pending (standing rule).

## 2026-06-05 — Phase E PR 26c: Headless browser smoke tests + docs (PR #74, opened) — CLOSES Phase E

- PR 26b (#73) MERGED → `origin/main` `0b1c178`. Built **PR 26c (#74) `feat/p27-browser-tests`** (`0833965`).
- Harness (de-risked FIRST by installing pytest-asyncio + running 1 minimal User test before building out):
  `requirements-dev` += `pytest-asyncio>=0.23` (installed via sandbox-disabled pip locally); `pyproject`
  `[tool.pytest.ini_options] asyncio_mode="auto"` + `markers=[nicegui_main_file]`; `conftest.py`
  `pytest_plugins=["nicegui.testing.user_plugin"]` (the **no-selenium** plugin — `nicegui.testing.plugin`
  imports selenium/webdriver which isn't installed; `user_plugin` doesn't).
- `tests/nicegui_main.py`: standalone NiceGUI sim entrypoint. ⚠ CANNOT point the harness at serve.py —
  `user_simulation` runs the main file via `runpy.run_path(run_name='__main__')`, so serve.py's
  `uvicorn.run` would HANG. Uses `importlib.reload(webui.dashboard)` so `@ui.page('/')` re-registers in
  nicegui's per-sim RESET registry — without reload a plain import is a cached no-op when an earlier test
  already imported webui.dashboard → page missing → "/ not found" (passed alone, failed in full suite).
- `tests/test_browser.py` (4 tests): render core sections (header/Actionable/Diagnostics/Scan-now);
  empty states (no-scan "No scan yet", 0-opp "no opportunities right now"); detail+diagnostics sections
  render ("Selected participant detail"/"Category honesty"/"Sum of independent row maxima"/"Full
  diagnostics"). Seeds a tmp store (monkeypatch config.SNAPSHOT_DB_PATH + write_snapshot) BEFORE
  user.open('/'); resets _FRAME_CACHE/scan_manager/presence per test.
- ⚠ KEY LIMITATION (documented, not a bug): headless `User` sees server-side LABELS/structure, NOT
  Quasar-table / AG-Grid ROW DATA (client-rendered) and can't drive table-ROW selection (a content click
  doesn't fire `on_select`). So `should_see("Player One")` [table data] FAILS and row-click→detail +
  ⬇Export downloads are MANUAL checks in `docs/RELEASE_CHECKLIST.md`. Their content builders are already
  exhaustively unit-tested.
- Docs: NEW `docs/RELEASE_CHECKLIST.md` (automated gates / boots / live scan / real-browser interactions /
  LAN+SCAN_TOKEN / GDrive sync). README "Setup&run"+"Tests"+"Roadmap→Architecture(shipped)" rewritten;
  CLAUDE.md "Run & verify" + "Repository status" updated (dropped stale "#35 / ~158 tests / no FastAPI").
- Verify: 416 pytest (was 412, +4 browser GREEN IN FULL SUITE after the reload fix), ruff clean (auto-fixed
  import sort), import-clean, serve `/`+`/metrics` 200, streamlit health 200. Clean base off 0b1c178.
- **Phase E (NiceGUI hosted parity) COMPLETE after #74 merges.** RESUME → Phase F: PR 27 follow-on
  detectors (advancement hedge + n-outcome FIELDs, each w/ a field-completeness proof); PR 28 known-limits
  docs (net-of-fees, position-limits/collateral, full-depth non-top-of-book execution — documented, not
  built, until owner opts in).

## 2026-06-05 — Phase E PR 26b: /scan scan-token gate + rate-limit (PR #73, opened)

- PR 26a (#72) MERGED → `origin/main` `1c4ba7b`. Built **PR 26b (#73) `feat/p26-scan-token`** (`74bd32c`).
- NEW **`ratelimit.py`** (top-level, thread-safe, clock-INJECTED — `SlidingWindow(max_events, window_s)`,
  `allow(now)` prunes >window-old events + records if under cap else False, `reset()`). Top-level so api
  imports w/o cycle; pure clock injection → deterministic tests.
- `config.py`: `SCAN_HTTP_MAX_PER_WINDOW=10` / `SCAN_HTTP_WINDOW_SECONDS=60` (literals only — config stays
  IMPORT-FREE per the convention at config.py:165; the `SCAN_TOKEN` env read lives in api.py).
- `api.py`: `import hmac,logging,os,ratelimit` + `Header`; module `logger=getLogger("kalshi.api")` +
  `_scan_limiter`. `require_scan_token(x_scan_token=Header(alias="X-Scan-Token"))` reads
  `os.getenv("SCAN_TOKEN","")` AT CALL TIME → set: `hmac.compare_digest` else 401; unset: open. Applied via
  `dependencies=[Depends(require_scan_token)]` on POST /scan (runs before body → bad token 401s w/o
  consuming rate budget or scanning). Body: `_scan_limiter.allow(time.time())` else 429 + `logger.info`
  every accepted trigger. `GET /scan/status` UNGATED. In-process `engine.run_scan_now` (dashboard button)
  bypasses BOTH guards by design.
- `docs/DEPLOYMENT.md`: SCAN_TOKEN env-var row + blockquote (rate-limit knobs) + Scheduled-auto-scan curl
  with `-H "X-Scan-Token: $SCAN_TOKEN"`.
- Tests: `test_ratelimit.py` (cap→False, window expiry frees, reset); `test_api.py` +4 (open when unset;
  401 no/wrong header + 202 correct when set; 429 past a shrunk cap; /scan/status ungated). Fixture resets
  `api._scan_limiter` + pops `SCAN_TOKEN` per test (removed unused `import config` → F401).
- Verify: 412 pytest (was 406), ruff clean, import-clean, LIVE (freed port 8000 by PID between boots): token
  UNSET → POST /scan 202 + /scan/status 200; `SCAN_TOKEN=s3cret` → 401(no header)/401(wrong)/202(correct).
  Clean base off 1c4ba7b (no stacking).
- RESUME after #73 merges → **PR 26c** browser smoke tests (`nicegui.testing.User` HEADLESS — user_plugin
  imports w/o selenium but needs pytest `asyncio_mode=auto` [add pytest-asyncio dev dep] + register the
  `module_under_test` marker; cover tabs/row-click/aggrid/downloads/timers via `await user.open('/')` +
  `should_see`) + finalize CLAUDE.md/README + GDrive docs as release checklist. Then Phase F (PR 27/28).

## 2026-06-05 — Phase E PR 26a: Truthful empty states + responsive (PR #72, opened)

- PR 25b (#71) MERGED → `origin/main` `7b9374f`. **PR 26 (hardening) SPLIT 3 ways** (owner via
  AskUserQuestion): 26a UX honesty + 26b /scan scan-token gate (env-gated X-Scan-Token, OFF by default +
  log + rate-limit) + 26c headless `nicegui.testing.User` browser tests (NO selenium — sandbox can't run
  it; adds pytest-asyncio) + finalize docs/README + GDrive checklist.
- Built **PR 26a (#72) `feat/p25-empty-states`** (`0f33378`). NEW `vm.empty_state(*, cov, total_opps,
  shown_opps, scan_status) -> str|None` — one honest message per empty scope (no-scan / scanning[in_progress]
  / scan-failed[error+msg] / no-opportunities[total==0] / filter-hid-all[total>0,shown==0]); None when
  content. `engine.scan_status()` = scan_manager.manager.status() (so dashboard reads heartbeat w/o
  importing scan_manager). dashboard.py: static "No scan yet" label → dynamic, set in refresh() from
  empty_state(cov,len(opps),len(view),scan_status). Responsive: opportunity + backlog tables get
  `overflow-x-auto` (audited control rows already flex-wrap). app.py: "finalized"→"finalized-within-open-
  events" wording (Outcome-status help text + 2 comments; matches CLAUDE.md scope note).
- Verify: 406 pytest (was 403), ruff clean, viewmodel import-clean, scripted empty_state over real engine
  states (empty store→no-scan, 0-opp snapshot→no-opportunities, snapshot+hiding-filter→filter-hid-all,
  content→None) all correct, serve GET / 200, streamlit health 200. Clean base off 7b9374f (no stacking).
- RESUME after #72 merges → **PR 26b** /scan scan-token gate (env SCAN_TOKEN; UNSET→open[today], SET→
  require X-Scan-Token header else 401; + log every trigger + per-process rate-limit; loopback unaffected;
  api.py /scan dependency + config knob + tests). Then **PR 26c** browser smoke tests (nicegui User: tabs/
  row-click/aggrid/downloads/timers; pytest-asyncio + asyncio_mode + module_under_test marker setup) +
  finalize CLAUDE.md/README + GDrive docs as release checklist. Then Phase F (PR 27/28).

## 2026-06-05 — Phase E PR 25b: Diagnostics & debug UI + viewer_count (PR #71, opened)

- PR 25a (#70) MERGED → `origin/main` `575b2b3`. Built **PR 25b (#71) `feat/p24-diag-ui`** (`4e46ef0`).
- NEW **`presence.py`** (top-level, pure stdlib `threading` — `connect`/`disconnect`/`count`/`reset`,
  floored at 0). Top-level (not in webui) so `api.py` reads it for `/metrics` with ZERO cycle risk.
- `webui/diagnostics.py`: `build_metrics` gains `viewer_count` param (was hardcoded None). `api.py`
  `/metrics` + `engine.metrics()` pass `presence.count()`. `engine`: `all_checks()`/`all_contracts()`
  concat the latest snapshot's frames across sports (category_breakdown refactored to reuse all_contracts).
- `webui/viewmodel.py`: pure builders `diagnostics_rows` (project checks frame), `non_laddered_rows`
  (filter `not ladder_eligible`, sort family↑/volume↓), `raw_fields_rows`, `sum_row_maxima` (sum
  exec_max_profit_dollars over actionable — the HONEST "Sum of independent row maxima", NOT "gross profit"),
  `link_audit_rows`/`duplicate_rows` passthroughs to data/consistency (keeps dashboard importing only vm).
- `webui/dashboard.py`: `from nicegui import app` + module-load `app.on_connect`/`on_disconnect` →
  presence. NEW `_aggrid_options(rows, fields)` helper (client-side pagination+filter+sortable). NEW
  "🔧 Diagnostics & debug" expansion populated in `refresh()` via `render_diagnostics(view)`: heartbeat
  (engine.metrics incl viewer_count), honest Sum-of-independent-row-maxima line, category honesty table
  (engine.category_breakdown), scan failures (engine.diagnostics), full-diagnostics `ui.aggrid`
  (engine.all_checks), non-laddered `ui.aggrid` (engine.all_contracts). PR 24 `render_detail` gains a
  `show_ids`-gated raw-fields/link-audit/duplicates sub-expansion over the clicked participant's contracts.
- Verify: 403 pytest (was 395), ruff clean (fixed E702 semicolons in test_presence + I001 in api via
  --fix), presence+viewmodel import-clean of nicegui+streamlit, serve `/` 200 + `/metrics` 200 carrying
  `viewer_count` (0 w/o a browser ws), streamlit health 200. Clean base off 575b2b3 (no stacking).
- ⚠ Render/browser test BLOCKED this PR (→ PR 26): `nicegui.testing.plugin` imports `selenium` (NOT
  installed); the no-selenium `nicegui.testing.user_plugin` imports OK but the `user` async fixture +
  `module_under_test` marker need pytest `asyncio_mode` + marker registration that isn't set up. So the
  page-BODY render (built on ws connect, incl. render_diagnostics/aggrid) is NOT exercised by GET / (which
  only returns the SPA shell + proves registration). PR 26 owns setting up selenium+async-mode for the
  consolidated browser smoke tests. All new logic here is in unit-tested pure builders; ui.aggrid(options
  dict) + app.on_connect APIs verified against installed nicegui 3.12.1.
- RESUME after #71 merges → **PR 26** `[nicegui 7]` Hardening: truthful empty states by scope, scan-token
  gate on `/scan` (OFF until owner confirms), responsive/mobile, the BROWSER SMOKE TESTS (selenium+async),
  finalize CLAUDE.md/README, GDrive docs as release checklist. Then Phase F (PR 27/28).

## 2026-06-04 — Phase E PR 25a: Backend observability /metrics (PR #70, opened)

- PR 24 (#69) MERGED → `origin/main` `c9f582f`. **PR 25 SPLIT** (owner via AskUserQuestion): 25a backend +
  25b AG-Grid UI; AG-Grid = **client-side** over the in-memory snapshot (not server-side data source).
- Built **PR 25a (#70) `feat/p23-metrics`** (`c818836`). NEW **`webui/diagnostics.py`** (PURE; imports only
  `sports`; no nicegui/store/scan_manager/api/engine): `build_metrics` (low-cardinality JSON — counters +
  scan heartbeat, NO per-row data / unbounded lists; `sport_error_count` is a COUNT), `build_failures` (the
  meta `sport_errors`/`series_errors`/skipped/excluded lists that `coverage()` curates away),
  `build_category_breakdown` (HONESTY axes SEPARATE — `non_laddered` via `ladder_eligible`, `low_confidence`
  via `mapping_confidence!="high"`, `unsupported` via `sport_for_series`==unknown, `by_family`; never one
  lumped "unmapped"; a low-conf laddered row counts in both).
- `webui/engine.py`: thin `metrics()`/`diagnostics()`/`category_breakdown()` (fetch store.latest +
  scan_manager.manager.status() + the stored contracts frames → pure builders; `import time` for
  in-progress elapsed).
- `api.py`: `GET /metrics` + `Metrics(BaseModel, extra=ignore)`, built from store + scan_manager directly
  (mirrors `/coverage`). **No cycle**: engine imports api, so api must NOT import engine — the pure module
  is the shared core (same split as viewmodel/export). `from webui import diagnostics` safe
  (`webui/__init__` is empty). `/coverage` unchanged (already has the failure lists).
- Verify: 395 pytest (was 385), ruff clean, `webui.diagnostics` import-clean of nicegui+streamlit AND
  engine/api (asserted), serve `/metrics` 200 (real payload: snapshot_id, 1099 opps, counters, scan_status)
  + `/coverage` 200 unchanged + `/healthz` 200, streamlit health 200. Clean base off c9f582f (no stacking).
- ⚠ GOTCHA (cost ~10min): a STALE `serve.py` (PID 27256, predating the `/metrics` route) kept port 8000
  bound; my fresh `python serve.py` couldn't bind, so curl hit the OLD process → `/metrics` 404 via NiceGUI
  catch-all while `/coverage` 200. `pkill -f serve.py` MISSED it; killed by PID via PowerShell
  `Get-NetTCPConnection -LocalPort 8000 | Stop-Process -Force` → clean reboot → `/metrics` 200. In-process
  `TestClient(serve.api.app)` always returned 200, which localized it to the live process, not the code.
  Lesson: before trusting a boot smoke of a NEW route, free port 8000 by PID, not pkill.
- RESUME after #70 merges → **PR 25b** `[nicegui 6b]` client-side AG-Grid full-diagnostics + debug section
  (errors by sport/family, failed series, `link_audit`, `duplicate_node_sources`, raw fields,
  `tournament_source`, non-laddered table) + "Sum of independent row maxima" relabel + live `viewer_count`
  (NiceGUI client tracking) into `/metrics`. Then PR 26 (hardening + browser smoke), Phase F (27/28).

## 2026-06-04 — Phase E PR 24: Participant/team detail panel (PR #69, opened)

- PR 23 (#68) MERGED → `origin/main` `c3bd8d8`. Built **PR 24 (#69) `feat/p22-detail-panel`** (`2928083`).
- NEW NiceGUI "🔬 Selected participant detail" section, populated on opp row-click from STORED
  contracts/checks frames (PR 21a) — **no fetch**. Leads with the 2-leg action summary
  (`explanation_lines`) + `relationship_explanation` (containment/dutch_book/synthetic_bundle/equivalence,
  SAFE fallback for a future type), then chain / spreads / expected-vs-found / all-contracts tables, then
  the **optional/last GUARDED charts** (ladder + per-unit payoff via `ui.echart`) — rendered only when the
  builder returns non-None (containment shape; dutch-book/game/missing → None → skipped). Frame-status
  honesty when evidence isn't captured.
- `scanner.py`: `participant_key` → UNIFIED_COLUMNS + 3 mappers (consistency→player_key,
  dutchbook→player_key_a, synthetic→player_key). Additive, no DB migration.
- `webui/engine.py`: the **DEFERRED FRAME CACHE** keyed `(snapshot_id, sport, frame_type)`, invalidated
  when latest snapshot_id changes; `participant_contracts` / `participant_checks` / `frame_availability` /
  `payoff_for_opp` (matches the stored checks row by opportunity_id → consistency.scenario_payoffs).
- `webui/viewmodel.py`: pure builders `detail_chain` (iterates the sport's node_order via
  build_player_nodes+representative, mirrors app.py:1048-1072) / `detail_spreads` / `detail_expected` /
  `detail_contracts` / `relationship_explanation` / `ladder_chart_option` / `payoff_chart_option`. Reuses
  consistency.* + viz.* (ladder_chart_option ADAPTS lowercase chain keys → viz.ladder_prices'
  "Layer"/"Display %"). Stays import-clean of nicegui + streamlit (charts = plain ECharts dicts).
- Verify: 385 pytest (was 375), ruff clean, viewmodel import-clean confirmed, serve `/`+`/coverage` 200,
  streamlit health 200, LIVE stored-frame smoke (seed frames → detail builders + both chart options
  non-None for containment, None for unmatched/dutch-book; snapshot_id UNCHANGED after building → no fetch;
  cache serves repeat opens). Clean base off c3bd8d8 (no stacking). **Awaiting owner merge of #69.**
- RESUME after #69 merges → **PR 25** `[nicegui 6]` diagnostics/metrics (AG-Grid full diagnostics,
  `/metrics`, debug), then PR 26 (hardening + browser smoke), Phase F (27/28).

## 2026-06-04 — Phase E PR 23: Export ZIP + manifest (PR #68, opened)

- PR 22 (#67) MERGED → `origin/main` `124bafa`. Built **PR 23 (#68) `feat/p21-export-zip`** (`8a7677c`).
- NEW `webui/export.py` (pure stdlib zipfile/csv/json, no nicegui/store/network): build_export_zip(...) →
  ZIP bytes = opportunities.csv (FILTERED view, UNIFIED_COLUMNS order, header first, legs→JSON cell) +
  frames/<sport>_<frame_type>.csv per non-empty persisted frame + backlog.csv + manifest.json (snapshot_id,
  fetched_at, exported_at, scope counters incl contracts_scanned/checks_tested/kalshi_requests,
  active_filters, per-frame schema_version+row_count, backlog window+snapshot_range). _rows_to_csv
  NaN/None-safe + JSON-encodes list/dict cells. engine: coverage() gains snapshot_id; new frames() wraps
  store.load_frames(latest) — the export is the FIRST frame reader (detail panels=PR24). dashboard: ⬇ Export
  button → ui.download.content(blob, name, "application/zip") (NiceGUI 3.12 in-memory bytes API verified via
  ui.download.content). +5 tests → 375 pytest, ruff clean (autofixed import sort), export import-clean.
  LIVE smoke: build over live snapshot → opportunities.csv+manifest.json+backlog.csv+11 frame CSVs, manifest
  counters match /coverage (contracts=1495/checks=1098/reqs=48), export did NOT change snapshot_id (no
  fetch), boots 200.
- RESUME after #68 merges: **PR 24** `[nicegui 5]` Participant/team detail panels — ladder/chain/spreads/
  expected/all-contracts from STORED contracts (consume the persisted frames + frame_status[PR20]); lead
  with a dense 2-leg action summary + relationship-type explanation (safe fallback for future types); charts
  optional/last (ui.echart via scenario_payoffs/viz.*), guarded for None + dutch-book/game rows. **This is
  where the deferred FRAME CACHE (keyed snapshot_id+frame+version) lands** (per-panel frame loading). Then
  PR 25 (diagnostics/metrics + AG-Grid), PR 26 (hardening + browser smoke tests), Phase F (PR 27/28).
  Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 22: viewmodel + opportunity-first controls (PR #67, opened)

- PR 21b (#66) MERGED → `origin/main` `63b1218`. Re-entered plan mode for PR 22 (big, only sketched);
  scoped it (trimmed frame-cache→PR24, quote/layer filters→PR24/25 since unified rows lack those fields).
  Built **PR 22 (#67) `feat/p20-viewmodel-controls`** (`3345836`).
- NEW `webui/viewmodel.py` (pure, NiceGUI-/streamlit-free): moved opp_row/backlog_row/explanation_lines/
  ts_disp out of dashboard.py + filter_opps (shape-branched: membership sport/tournament/participant narrows
  ALL; thresholds min_size/active_only spare actionable+dutch_book), derive_options (id→label, only present),
  scope_banner (surfaces PR21a contracts_scanned/checks_tested/kalshi_requests, age live), state_from_query/
  query_from_state (compact URL state, graceful reset of unknown sport/tournament), active_filter_chips.
  dashboard.py: filters row (none fetches — re-render from stored snapshot), chips, scope banner, @ui.page
  query-param seeding + history.replaceState URL sync, stale-while-scanning (only Scan btn disables), 1s
  freshness tick kept. engine.coverage() exposes the 3 counters. test_webui retargeted to vm + new
  test_viewmodel. 370 pytest, ruff clean, viewmodel import-clean of nicegui+streamlit. Interactive smoke:
  dashboard + URL-filters render 200, stale ?sport=golf resets gracefully, loading dashboard 3x did NOT
  change scan snapshot_id (no fetch on page/controls), scope banner contracts=1493/checks=1098, boots 200.
- RESUME after #67 merges: **PR 23** `[nicegui 4]` Export — one button → ZIP of clean CSV(s) (columns as
  first row) + manifest.json (snapshot_id, fetched_at, scope, active filters, per-frame schema versions,
  contracts_scanned, checks_tested; backlog exports add scan window + snapshot range). Download verified vs
  NiceGUI 3.12. Uses PR 21a's snapshot_id/counters + the persisted frames. Then PR 24 (detail panels +
  frame cache, consume frames + frame_status), PR 25 (diagnostics/metrics), PR 26 (hardening + browser smoke
  tests), Phase F (PR 27/28). Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 21b: ScanManager + non-blocking /scan 202 (PR #66, opened)

- PR 21a (#65) MERGED → `origin/main` `2064bf9`. Built **PR 21b (#66) `feat/p19-scan-manager`** (`a9927b9`).
  Owner Q3 = non-blocking default (202). **PR 21 now COMPLETE (21a+21b).**
- NEW `scan_manager.py`: process-local ScanManager singleflight — ONE entry for POST /scan AND
  webui.run_scan_now (two triggers → one upstream fetch). trigger() guards in order (force overrides all):
  singleflight (in-flight→return status) → budget cooldown → store TTL. Non-blocking by default (daemon
  thread, returns at once); wait_timeout joins up to a bound. run_fn/write_fn INJECTED (unit-testable, no
  network). Budget-blowing scan (time/kalshi_requests/failed caps) → cooldown skips next non-forced trigger.
- api.py: POST /scan → 202 {status,since,last_snapshot_id,reason} (ScanStatus model; old ScanResult/skipped
  REMOVED — breaking but only cron+dashboard call it); ?wait=true bounded join; ?force=true overrides; new
  GET /scan/status. webui.run_scan_now routes through the manager. config SCAN_WAIT_TIMEOUT=60 + budget caps
  + cooldown. scripts/benchmark_scan.py (manual scan-all metrics, scope injectable, no default change).
  DEPLOYMENT §4 + CLAUDE.md 202 docs. Rewrote 3 test_api scan tests + new test_scan_manager.py (singleflight/
  TTL/force/wait/cooldown/failure). 359 pytest, ruff clean. LIVE smoke: POST /scan→202 instant, ?wait=true→
  done (contracts=1493/checks=1098/reqs=48), rapid 2nd→in_progress (singleflight), within-30s→skipped ttl,
  force→in_progress, boots 200.
- RESUME after #66 merges: **PR 22** `[nicegui 3]` — neutral `viewmodel.py` (input→frame builders, NOT a 2nd
  app.py); shape-branched filtering (membership on consistency+dutchbook; thresholds on consistency only;
  Actionable+dutchbook spared); NO control triggers a fetch; sport-aware labels; compact URL state + graceful
  reset for absent participant key; filter chips; scope banner from stored snapshot meta (both counters);
  stale-while-scanning (disable only Scan btn); pagination/row caps; frame cache keyed snapshot_id+frame+ver.
  Then PR 23 (export ZIP — uses 21a snapshot_id/counters/frames). Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 21a: scanner persistence (PR #65, opened)

- PR 20 (#64) MERGED → `origin/main` `04884e6`. Split the big PR 21 into **21a (persistence, additive)** +
  **21b (ScanManager + non-blocking /scan)**. Owner Q3 answered: **non-blocking default (202)** for 21b.
- **PR 21a (#65) `feat/p18-scanner-persistence`** (`4f31165`): scanner.unified_opportunities gets a
  `frames_out` OUT-param (keeps 2-tuple return + all callers unchanged) collecting per-sport
  {sport,frame_type,schema_version,rows} for contracts/checks/dutchbook. run_scan now returns
  (unified, coverage, FRAMES); coverage gains contracts_scanned/checks_tested (from frames) + kalshi_requests
  via an INJECTED request_count callable (scanner stays kalshi_client-free per its docstring — used DI not
  import). kalshi_client: process-wide request counter ticked per HTTP attempt in _get (retries counted) +
  request_count()/reset_request_count(). store.write_snapshot stamps snapshot_id into each opp row JSON +
  UNIFIED_COLUMNS gains snapshot_id. api.post_scan + webui.run_scan_now pass frames= + inject the counter;
  Coverage model + /coverage gain the 3 fields. +4 tests → 352 pytest, ruff clean. **LIVE smoke (real data
  this time!): 1098 opps, contracts_scanned=1493, checks_tested=1098, kalshi_requests=48, rows carry
  snapshot_id.**
- RESUME after #65 merges: **PR 21b** `feat/p19-scan-manager` off updated origin/main — new `scan_manager.py`
  (process-local singleflight, single entry for POST /scan AND webui.run_scan_now), POST /scan → **202**
  {status,since,last_snapshot_id} default non-blocking + bounded ?wait=true + GET /scan/status, TTL/force/skip
  matrix + scan budget cooldown, benchmark spike (scripts/), DEPLOYMENT 202 docs, rewrite the 3 test_api scan
  tests + new test_scan_manager.py. Then PR 22 (viewmodel) / 23 (export) — sketched in the plan. Worktree
  C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 20: retention size-tiers (PR #64, opened)

- PR 19 (#63) MERGED → `origin/main` `73eedcb`. Built **PR 20 (#64) `feat/p17-retention-size-tiers`**
  (`2c3db27`). Owner Q7 answered: **generous tier (latest 12 / 500 MB)**.
- store.py `_apply_frame_retention(conn, db_path)` runs after lean `_apply_retention` (same txn): tier 1
  keep frames for latest N=12 snapshots (older keep opps, lose evidence); tier 2 evict oldest while retained
  LOGICAL bytes (SUM(LENGTH(rows_json))) > 500MB budget & >1 frame-snap remains. Budget on blob length not
  file size (deterministic; file doesn't shrink w/o VACUUM = documented known-limit; db_size_bytes logged
  only when evicting). New `frame_status(sid)→present|expired|absent` = honest signal for PR-24 detail UI.
  config: SNAPSHOT_FRAME_RETENTION_N=12 + SNAPSHOT_FRAME_DB_BUDGET_BYTES=500MB.
- **Caught + fixed a PR-19 bug:** .gitignore inline `# comments` made `*.db-wal`/`*.pre-v*-backup` match
  NOTHING (gitignore has no inline comments) → WAL sidecars + migration backups weren't ignored. Moved
  comments to own lines (verified git check-ignore now matches).
- Store-only, additive (read paths unchanged; frames have no producer till PR 21). +5 store tests → 349
  pytest, ruff clean, store import-clean of streamlit+pandas. Smoke: 15 snaps → exactly latest 12 keep
  frames, 1-3 "expired", all 15 lean opps retained, size logged; serve /healthz+/ 200, streamlit 200.
  **Boundary:** PR 21 writes frames (+db_size into coverage meta); PR 24 renders frame_status. RESUME after
  #64 merges: Phase E **PR 21** (scanner persistence + ScanManager singleflight + NON-BLOCKING /scan →
  202; **owner Q3 = the 202 contract decision** — Option A hard-break vs Option B ?wait=true default;
  persist contracts/checks/dutchbook frames + coverage counters contracts_scanned/checks_tested + request
  counter in kalshi_client._get). Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 19: store schema v3 (PR #63, opened)

- PR 19a (#62) MERGED → `origin/main` `e843eba`. Built **PR 19 (#63) `feat/p16-store-schema-v3`** (`02068dc`).
  Plan: `joyful-singing-lemon.md`.
- store.py SCHEMA_VERSION 2→3: new `snapshot_frames(snapshot_id, sport, frame_type, schema_version,
  rows_json, row_count)` table (partial-loadable by sport/frame_type, per-frame schema_version); _connect
  sets PRAGMA journal_mode=WAL + busy_timeout (config.SNAPSHOT_BUSY_TIMEOUT_MS=5000) so readers survive a
  scan write; v2→v3 migration backs up first via SQLite online backup API (`<db>.pre-v3-backup`) then
  incremental forward step, fresh-DB-on-failure (ASCII warning — reused the cp1252 lesson from PR 19a);
  write_snapshot(...,frames=) writes frames in the SAME transaction; new load_frames(); retention drops
  frames with their snapshot. .gitignore: *.db-wal/-shm + *.pre-v*-backup. **ADDITIVE — api/app/webui/
  lifecycle return shapes unchanged, untouched.**
- **Boundary noted in plan + PR:** PR 19 = store capability only; the scanner that PRODUCES frames + the
  volume counters (contracts_scanned/checks_tested/request count/per-frame counts) is **PR 21** — no
  scanner/api/app/webui change here (avoids colliding with PR 21).
- +9 store tests (migration v1→v3/v2→v3+backup, fresh-on-failure, WAL, frame round-trip type guarantees via
  dict+DataFrame, partial load, retention) → 344 pytest, ruff clean, store import-clean of streamlit+pandas.
  Manual smoke: real v2→v3 preserves data+meta+backup, frame NaN→None, **concurrent 50 reads+20 writes under
  WAL = ZERO "database is locked"**, serve /healthz+/ 200, streamlit 200. RESUME after #63 merges: Phase E
  **PR 20** (retention size-tiers: lean unified-opp history 30h + heavy frames latest-N under a DB-size
  budget, "evidence expired" honesty, scope-mismatch guard) — then PR 21 (scanner persistence + ScanManager
  + non-blocking /scan; owner Q3 = the 202 contract). Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase E PR 19a: LAN-access finalization (PR #62, opened)

- Phase D fully MERGED (#60, #61) → `origin/main` `1451a36`. Started Phase E (NiceGUI parity) with its hard
  prerequisite **PR 19a (#62) `feat/p15-lan-finalization`** (`34c11c8`). Plan: `joyful-singing-lemon.md`.
- **serve.py**: env-driven bind (API_HOST/API_PORT, default loopback) + pure `bind_safety(host, *,
  storage_secret_set, allow_dev_on_lan, web_concurrency, has_workers_arg)`: storage-secret FAIL-HARD on
  non-loopback without NICEGUI_STORAGE_SECRET (escape ALLOW_DEV_STORAGE_SECRET_ON_LAN=1 → warn); multi-worker
  WARN (WEB_CONCURRENCY>1/--workers; store+throttle process-local). __main__ prints warns + SystemExit(2) on
  fatal before bind. **Bug caught by manual smoke: ⚠/✖ unicode crashed print on Windows cp1252 → switched to
  ASCII prefixes** (exactly why the live fail-hard check matters). requirements: nicegui>=2.0 → >=3.12,<4
  (installed 3.12.1, suite green). Committed the uncommitted LAN groundwork (docs/LAN_ACCESS.md fail-hard
  update, docs/DEPLOYMENT.md secret-required+single-worker, serve_lan.ps1 port→8000) + CLAUDE.md pointer.
  +8 tests (test_serve.py) → 337 pytest, ruff clean. Manual smoke: no-secret 0.0.0.0→exit2+refusal,
  +escape→warn+200, +secret→clean, loopback→/healthz+/ both 200, streamlit 200. **Merge-readiness verified:
  trial-merge of #62 onto origin/main (1451a36, unmoved) is CLEAN → branch == merged state. Owner OK to merge.**
- **NOTE:** the Internship working tree still has the OLD uncommitted serve.py/docs/serve_lan.ps1 (the
  warn-only versions). After #62 merges, discard those locals (they're superseded by the committed, hardened
  versions): `git -C Internship checkout -- serve.py` + delete the now-tracked untracked copies, or just
  `git stash`/reset once on the synced main. RESUME after #62 merges: Phase E **PR 19** (store schema v3:
  snapshot_frames table, WAL+busy_timeout, per-snapshot metadata + the two volume counters, v2→v3 migration
  with backup/fresh-on-failure). Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase D leftovers PR 18: review_signal bucket + synthetic UX (PR #61, opened)

- PR 13 (#60) MERGED → `origin/main` `4faa985`. Built **PR 18 (#61) `feat/p14-synthetic-review-bucket`**
  (`3301d1e`, off origin/main WITH #60 — conflict-free since it extends PR 13's synthetic table + reuses
  `scanner.gross_roi_pct`).
- Added a dedicated **`review_signal`** bucket so synthetic exact-score bundles aren't lumped with
  no-size/inactive `blocked` rows: consistency.DASHBOARD_BUCKETS (after actionable) + bucket_of split
  (EXECUTABLE_SYNTHETIC_BUNDLE → review_signal when tradable_now startswith "Review" else blocked;
  EXECUTABLE_VIOLATION/DUTCH_BOOK unchanged); synthetic_bundle._build_finding mirrors it; scanner.BUCKET_PRIORITY
  review_signal=1 (blocked→2…clean→7). app: Review-signal framing + Stake($) column + Sort-by[gross|ROI]
  toggle. webui: dedicated Review-signal table between Actionable and Blocked. glossary "Review signal" term
  + COLUMN_HELP; docs/GLOSSARY.md regenerated (16 terms). Updated test_scanner + test_synthetic_bundle
  (blocked→review_signal, +no-size→blocked, +BUCKET_PRIORITY-in-sync invariant). 329 pytest, ruff clean,
  glossary export OK, streamlit+serve boots 200.
- **Phase D COMPLETE** (PR 13 #60 merged, PR 18 #61 open). Housekeeping: killed 9 zombie python serve
  processes from background boots. RESUME after #61 merges: next UNIFIED-PLAN block is **Phase E (NiceGUI
  parity)** — start with **PR 19a LAN finalization** (storage-secret fail-hard on non-loopback bind +
  ALLOW_DEV escape, WEB_CONCURRENCY guard, pin nicegui>=3.12,<4 + compat pass, commit the uncommitted
  serve.py/docs/serve_lan.ps1 LAN groundwork) — the hard prerequisite for PR 19–26. Then Phase F (PR 27/28).
  Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase D leftovers PR 13: unified leg-schema completion (PR #60, opened)

- Phase B (#58/#59) MERGED → `origin/main` `7b73d2d`. Owner chose Phase D leftovers (PR 13 + PR 18) as next.
  Plan: `joyful-singing-lemon.md`.
- **PR 13 (#60) `feat/p13-leg-schema-completion`** (`b75b856`, off origin/main): normalized the unified
  N-leg schema. Added `payout_floor_c` + `roi_pct` to UNIFIED_COLUMNS; producers emit a payout floor
  (dutchbook 2-way=100, synthetic propagates discarded threshold_c forward=100/reverse=N×100, n-way already
  had it); new public `scanner.gross_roi_pct(gap,cost)` + `legs_of(row)` (synthesizes a 2-leg list from
  action fields → covers 2-leg shapes AND old snapshots); `_finalize_unified` stamps floor/ROI/legs on every
  mapped row; api.Opportunity declares the previously-dropped fields (cost_c/action_*_price_c/
  settlement_caveat/ticker_1/2/url_2/payout_floor_c/roi_pct), BacklogItem gains last_legs+floor+roi;
  lifecycle carries last_legs; app dutch+synthetic tables get Floor/ROI columns; webui ROI column + panel.
  Store JSON-blob transparent (no DB migration). +9 tests → 327 pytest, ruff clean, store round-trip +
  streamlit/serve boots 200.
- **PR 18 NOT STARTED — intentionally paused.** It extends the SAME synthetic table PR 13 reworked + reuses
  `scanner.gross_roi_pct`, so it must branch off origin/main AFTER #60 merges (else a synthetic-table merge
  conflict — the no-stack rule). RESUME: once owner merges #60, branch `feat/p14-synthetic-review-bucket`
  off fetched origin/main; add `review_signal` bucket (consistency DASHBOARD_BUCKETS after "actionable" +
  bucket_of: EXECUTABLE_SYNTHETIC_BUNDLE→review_signal when tradable_now startswith "Review" else blocked;
  synthetic_bundle._build_finding mirrors it; scanner.BUCKET_PRIORITY review_signal=1 shift others); app
  Stake$ col + sort-by-ROI; webui review_signal table; glossary "Review signal" term; UPDATE
  test_synthetic_bundle.py::test_status_group_and_bucket_route_to_review_blocked (blocked→review_signal) +
  add a no-size/inactive→blocked case + BUCKET_PRIORITY-in-sync invariant. Worktree C:\Users\Batata\Desktop\kalshi-impl.

## 2026-06-04 — Phase B dutch-book settlement honesty: PR 5 (#58) + PR 6 (#59), both opened

- After #57 (synthetic gates) merged → `origin/main` `0bab5bb`. Mapped roadmap completion: Phases A/C/D +
  Phase B PR 4 all merged; the **leapfrogged Phase B PR 5 + PR 6** are the earliest unfinished items.
  Owner chose them (plan `joyful-singing-lemon.md`). Two coherent fixes: the dutch book isn't riskless
  *because* a game can be postponed/abandoned — PR 6 establishes the risk, PR 5 corrects the wording.
- **PR 5 (#58) `feat/p11-dutchbook-conservative-labeling`** (`ab80618`): drop "locked/riskless/true
  arbitrage" from all dutch-book copy → single-sourced `glossary.DUTCH_BOOK_BASIS` ("gross two-way
  pricing discrepancy … under normal one-winner settlement"). Reworded glossary short/long, both
  dutchbook.py reason strings, app.py caption/help + column rename "Locked edge (¢)"→"Gross edge (¢)",
  CLAUDE.md. Strings only, no math change. +2 tests → 314 pytest.
- **PR 6 (#59) `feat/p12-game-settlement-caveat`** (`555ca01`, off origin/main, sequences after #58):
  non-blocking `settlement_caveat` on game-family findings (NBA/WNBA 2-way + soccer 3-way), single-sourced
  `BLOCKERS["game_settlement"]`. Dedicated field (NOT blockers/blocked_reason) so an actionable game book
  stays actionable + the blocked_reason-iff-blocked invariant holds. Added `settlement_caveat` to
  UNIFIED_COLUMNS + 3 mappers (persists to store/webui, JSON-blob transparent, no DB migration); app.py
  `dutch_caveat_text`; webui row + panel. +4 tests → 316 pytest.
- Both verified: pytest + ruff + import smoke + streamlit/serve boots 200; live smoke empty (off-window) →
  clean no-crash. **Phase B now COMPLETE** (pending owner merge of #58, #59). No-stack rule honored
  (PR 6 off origin/main, localized edits, clean merge either order).

## 2026-06-04 — Synthetic hardening PR 2: safety gates (PR #57, opened)

- Built the **second/final** synthetic-hardening PR: `find_synthetic_bundles(rows, _diag=None)` now runs
  `_unsafe_reason` (3 hard suppression gates) over the score legs + match-winner hedge, applied in
  `_detect_player_bundle` after the stage gate. Each gate suppresses **only on proven-unsafe evidence**
  (absent metadata passes → back-compat preserved):
  1. **Binary settlement (#15):** leg `market_type` present and ≠ `"binary"` → suppress. Keys on
     `market_type` ONLY — `fractional_trading_enabled=True` is the NORM (live trap), deliberately not gated.
  2. **Close-time sync (#22):** every leg must close within `_CLOSE_TIME_TOLERANCE_S` (6h); partial/
     unparseable → pass.
  3. **Rule-token divergence (#9/#20):** divergent `data.rule_tokens(rules_primary)` set across legs →
     suppress. Residual matching-but-unverified case keeps the `SETTLEMENT_CHECK_REQUIRED` review caveat.
- Mirrors `dutchbook.find_dutch_books(_diag)` (`_record` → `_diag["suppressed"]`). `app.py` passes a `_diag`
  and renders a "🚫 Suppressed bundles" expander. +10 tests (each gate's bad case + visible `_diag` reason;
  clean fire; tolerance/partial/matching-token negatives; the binary+fractional trap; **format-proof
  circularity guard**). Module 33 tests; full suite **312 pass**, ruff clean, headless boot 200, engine
  streamlit-free. Live smoke = empty (between tournaments, expected) → clean no-crash.
- Branch `feat/p10-synthetic-safety-gates` off `origin/main` 5bfe843 in worktree; pushed → **PR #57** to
  main (awaiting owner merge). **Synthetic-hardening milestone now code-complete** (both PRs done; #56 merged,
  #57 open).

## 2026-06-04 — Synthetic hardening PR 1: exact-score data capture (PR #56)

- Soccer milestone complete (#53/#54/#55 merged → `origin/main` at `7b4d928`). Chose **synthetic hardening**
  as the next step (Phase D). Exploration finding: the synthetic detector is **already review-only** (never
  actionable) and the **format proof is already non-circular** — so hardening makes the review signal
  trustworthy, not a live false-positive fix. Plan = 2 PRs (capture → gates), in floating-squishing-teapot.md.
- **PR 1 (of 2):** `build_contracts` stamps exact-score/settlement metadata (score_state, market_type,
  strike_type, fractional_trading_enabled, price_ranges, rules_secondary, close/expiration) + identity
  hardening (exact-score keys on tennis_competitor UUID). **Live probe caught a trap:**
  `fractional_trading_enabled=True` is the NORM (order size, not scalar settlement) → the binary gate keys
  on `market_type=="binary"`. 302 pytest, ruff clean. Branch `feat/p9-synthetic-data-capture` → **PR #56
  MERGED by owner** (`origin/main` now `5bfe843`, commit `dffe5fd`).
- **NEXT (PR 2): safety gates** (binary-settlement keyed on `market_type=="binary"`, close-time sync,
  settlement-rule divergence via `data.rule_tokens`, circularity guard) in `synthetic_bundle.py` — **now
  unblocked**; branch fresh off `origin/main` `5bfe843`.

## 2026-06-04 — Soccer milestone PR 3 (final): dutch-book UI + glossary/docs (PR #55)

- #54 merged → `origin/main` at `fcb45a9`. **PR 3 (final):** Streamlit dutch-book section renders the full
  N-leg plan ("Plan (all legs)" column via `app.dutch_plan_text`, was fixed Leg1/Leg2 showing only 2 of 3);
  heading/help generalized to n-outcome + `(n−1)·100` floor. `_detect_n_way` sets `player_a/b` to the real
  team rows (participant filter robust; Tie never matches). Glossary "Dutch book" rewritten for n-outcome +
  "true arbitrage"→"gross edge under normal one-winner settlement"; `docs/GLOSSARY.md` regenerated; CLAUDE/
  TECH docs updated. 299 pytest, ruff clean. **PR #55** (MERGEABLE/CLEAN, off `fcb45a9`, no drift).
- **SOCCER + n-outcome milestone COMPLETE** (#53 register+typing, #54 detector, #55 UI/docs). On merge:
  run `complete-milestone`. Next roadmap chunk: synthetic-bundle hardening (Phase D PR 15–18) or NiceGUI
  parity (Phase E).

## 2026-06-04 — Soccer milestone PR 2: n-outcome dutch-book detector (PR #54)

- #53 merged → `origin/main` at `1e519c9`. **PR 2 (of 3):** generalized dutchbook to n-outcome —
  `find_dutch_books` dispatches soccer `game` → new `_detect_n_way` (NBA/WNBA/tennis 2-way byte-identical,
  regression-tested); `prove_mece` (2 participants + 1 Tie via is_participant, ME flag, draw phrase, shared
  basis); underround Σyes_ask<100 / overround Σno_ask<(n−1)·100; emits the existing `legs` schema (scanner
  passthrough) → flows through store/api/webui unmodified. Extracted shared `data.rule_tokens`
  (`_rule_flag` refactored, no legacy change). `proof_audit` + `_diag`. 10 tests, 298 pytest, ruff clean.
  **Live smoke: 72 real 3-way games all PASS prove_mece, both directions priced, 0 arb (eligible-non-
  firing) — correct conservative result.** Branch `feat/p7-soccer-nway-dutchbook` → **PR #54** (MERGEABLE/
  CLEAN; off `1e519c9`, no drift).
- **NEXT (PR 3): app.py n-leg dutch-book rendering + participant filter over legs + glossary/docs** —
  depends on #54 merging.

## 2026-06-04 — Soccer milestone PR 1: register SOCCER + participant typing (PR #53)

- Golf #52 merged → `origin/main` at `c4f2e8b`. Exploration found the **N-leg `legs` schema already
  end-to-end** (m5) → soccer n-outcome needs NO leg-schema migration (big shrink; plan v in floating-
  squishing-teapot.md).
- **PR 1 (of 3):** registered SOCCER (`exact_series={KXWCGAME,KXWCROUND}`, game/advance families,
  reach-stage ladder R16⊇QF⊇SF⊇Final, soccer_team identity, `match_family=""`). Added **participant
  typing**: build_contracts stamps `is_participant`/`participant_type`/`mutually_exclusive`; Tie →
  `tie::<event>` synthetic key + `is_participant=False` via new `cfg.tie_fn`; selector gated. 288 pytest,
  ruff clean. **Live smoke: 2 series / 472 contracts / 192 reach-stage comparisons, monotonic pricing.**
  Branch `feat/p6-soccer-register` → **PR #53** (open).
- **NEXT (PR 2): n-outcome dutch-book detector** — DEPENDS ON #53 MERGING (needs SOCCER + the
  mutually_exclusive/participant fields). PR 3 = UI/glossary/docs.

## 2026-06-04 — Phase C: GOLF registered (PR #52)

- m1 PRs #48–50 + PR4 #51 all merged by owner → `origin/main` at `069fa6f`.
- **Registered Golf (5th sport)** as a clean SportConfig drop-in on the merged foundation: `exact_series`
  ownership of `KXPGATOP5/10/20`+`KXPGATOUR` (round-finishers/H2H/props → UNKNOWN), ladder Top20⊇Top10⊇
  Top5⊇Win, `golf_competitor` identity, `match_family=""`. No other engine change. 9 new tests + scanner
  coverage test made sport-count-robust. Docs updated. **282 pytest pass, ruff clean, import smoke.**
  **Live smoke:** 4 series / 724 contracts / 543 ladder comparisons, sane pricing, no prop/round/H2H leak.
  Branch `feat/p5-golf-register` → **PR #52** (open, awaiting owner merge).

## 2026-06-04 — m1 pushed as PRs #48–50, PR 4 opened #51, research gates answered

- Landed m1 as **3 clean independent PRs** off `origin/main` (rebuilt p2/p3 via cherry-pick so no
  stacking): **#48** (PR1 scanner leg/URL), **#49** (PR2 exact_series), **#50** (PR3 category dispatch).
  **Owner MERGED all three** → `origin/main` now at `0e65608`. **Verified post-merge:** all 3 fixes present
  on main, 270 tests pass, ruff clean. Deleted the merged local branches.
- **PR 4 — transitive containment** built off `origin/main`, 266 tests green + ruff, pushed → **PR #51**.
- **research-gates workflow** (4 agents, live API) answered §7 Q1/Q2/Q3 → findings in
  `note-20260604-research-gates.md`; UNIFIED-PLAN §7 updated. Verdicts: Golf GO; Soccer GREEN (register
  KXWCGAME+KXWCROUND only — KXFIFAGAME/KXFIFAADVANCE not live); n-outcome detector GREEN. **Q3 /scan is now
  the live OWNER DECISION** (Option A 202-break vs Option B ?wait=true) gating nicegui PR 21.
- Phase C (golf/soccer register) + Phase D (n-outcome detector) are now unblocked.

## 2026-06-04 — m1-foundation built, tested, merged to LOCAL main (PRs 1–3)

- Implemented the collision core in the worktree (`kalshi-impl`), one branch per PR off `origin/main`,
  each verified then merged `--no-ff` into local `main`:
  - **PR 1** `feat/p1-scanner-leg-url-fix` (`6aa41af`): fixed `scanner.py` `_to_unified_consistency`
    url/url_2 reversal (url→parent/leg1, url_2→child/leg2) + leg↔ticker↔url regression tests (both shapes).
  - **PR 2** `feat/p2-exact-series` (`8ba8b10`): `exact_series` field (defaulted last) + exact-first
    `sport_for_series` (two-pass) + `discover_series_for_sport` include/short-circuit + tests.
  - **PR 3** `feat/p3-category-dispatch` (`e109600`): per-sport category dispatch in `consistency._row`
    (`_sport_for_row(...).category_labels.get(kind,"Other")`); dropped unused CATEGORY import; NBA-label test.
- Verified after each + final on merged main: **270 pytest pass**, ruff clean, import smoke (engine
  streamlit-free; app/serve import). Local `main` now 6 commits ahead of `origin/main`.
- **NOT pushed to origin** (standing "never push to main" rule; "merge" ≠ "push") — awaiting owner go to push.
- Branches kept (not deleted) so they can be pushed as real PRs if preferred.

## 2026-06-04 — topic created + implementation environment set up (no code)

- Audited & merged the 4 concurrent plans into `Concurrent Plans/UNIFIED-PLAN.md` (9-agent workflow +
  several curation/consistency rounds). Final audit caught that `origin/main` is already at #47 (s1–s5 + m5),
  not the stale local #40/#42 — corrected the plan's baseline framing (PR 0 = sync, not merge; synthetic =
  harden existing).
- Setup: FF local `main` → `origin/main` #47; created impl worktree `C:\Users\Batata\Desktop\kalshi-impl`;
  verified **263 tests pass** on #47; re-anchored F1 (scanner leg/URL) to `scanner.py:92-93` on #47.
- Created this coordinating topic. Next: `plan-milestone` for Phase A (foundation).
