# CLAUDE.md

Guidance for **Claude Code** in this repository. This file holds the **always-on essentials**; the
per-module "do not regress" invariants live in path-scoped **`.claude/rules/`** and auto-load only when
you open a matching file (see [Rules map](#rules-map) below). Keep this file **under 200 lines** — a Stop
hook warns at end of turn if it (or a rule file) grows past that. Module detail belongs in a rule, not here.

## Project

A small, **read-only NiceGUI trader dashboard** (on FastAPI, via `serve.py`) over live
[Kalshi](https://kalshi.com) prediction-market data for **tennis (ATP/WTA), NBA, WNBA, golf, soccer,
MLB, NHL, motorsport (F1/NASCAR/IndyCar/MotoGP), NFL, and esports** — 10 sports. It surfaces **executable
inconsistencies** across a participant's related contracts (a deeper outcome must not price above a
prerequisite that contains it) and **dutch-book arbitrage** on MECE events, as buy-only opportunities
(**Buy YES / Buy NO**), ranked Actionable / Review / Blocked with collapsed diagnostics and
per-participant detail. A background scan refreshes a SQLite snapshot store under a process-wide rate
throttle. The **React "Kalshi Structured Scanner" SPA** (`frontend/`, built to `frontend/dist`) is the
**default UI at `/`**; the legacy NiceGUI dashboard is **retained (not deleted) at `/dashboard`** as a
read-only fallback. (The older Streamlit `app.py` was retired.) Both are read-only views of the same
engine — the SPA reads it solely through `GET /api/terminal/feed` (+ thin `/api/terminal/*` parity views).

- **Owner / GitHub:** FranciscoCarames (`franciscocarames1@gmail.com`). Repo `Kalshi-Visualizer`
  (private), default branch `main`.
- **Platform:** Windows 11, PowerShell, Python 3.13. (The Bash tool is also available.)
- **Scope guard — do NOT add unless explicitly asked:** trading, order placement,
  conditional-probability/de-vig models, net-of-fees math. **Exception (owner‑approved 2026‑06‑16):** the
  field‑implied **de‑vig conditional‑probability panel exists in the legacy NiceGUI `/dashboard/`** (merged
  from `origin/main`); the React **SPA stays display‑only / no de‑vig**. **Exception (owner‑approved
  2026‑06‑19):** the **conditional‑blend opponent‑resolution detector** (`conditional_blend.py`) computes a
  market‑implied blend (a conditional‑probability transform) and may surface a **display‑only `speculative_model`
  section in the React SPA** — but it is **DEFAULT‑OFF** (`config.CONDITIONAL_BLEND_DEFAULT_ENABLED` / env
  `CONDITIONAL_BLEND_ENABLED`) and must NOT be flipped on until its live forward‑test clears the predeclared
  gate (`CONDITIONAL_BLEND_VALIDATION.md`); it is `exec_gap_c=None`, never ranked/Actionable, and never net‑of‑fees.
  Adding a **new sport** is in scope
  via a `SportConfig` drop-in; non-sport-config work is not. **Per-user authentication is now IN SCOPE**
  (owner-requested 2026-06) — app-level login over the read-only surface, gated behind `AUTH_ENABLED`;
  see `docs/AUTH.md` (`auth_store.py`/`auth.py`/`manage_users.py`). It must NOT alter engine logic.

## NEVER EVER DO

These rules are ABSOLUTE:

### NEVER Publish Sensitive Data
- NEVER publish passwords, API keys, tokens to git/npm/docker
- Before ANY commit: verify no secrets included

### NEVER Commit .env Files
- NEVER commit `.env` to git
- ALWAYS verify `.env` is in `.gitignore`

## Workflow docs

Specialized review/workflow guidance lives in separate files — link to them, don't inline their content here:

- **`AGENTS.md`** — operating guide for Codex and other `AGENTS.md`-aware reviewers.
- **`docs/REVIEW_PROTOCOL.md`** — shared review protocol: plan reviews, diff reviews, risk classes,
  verdicts, blockers, missing tests, current-doc checks, conservative labeling.
- **`docs/PR_CHECKLIST.md`** — required pre-merge checklist before opening or marking a PR ready.
- **`docs/AGENT_WORKFLOW.md`** — day-to-day workflow for Claude Code, Codex, multiple
  terminals/worktrees, WIP limits, stale plans, and documentation-size rules.

Claude Code follows `docs/AGENT_WORKFLOW.md` before creating new plans and `docs/PR_CHECKLIST.md` before
handing work back. Do not add long workflow procedures here — link to the specialized docs instead.

## Rules map

Per-module invariants live in `.claude/rules/`. Each loads automatically when you open a file matching its
`paths:`. Read the rule before changing the module — they encode "do not regress" behavior.

| Rule file | Loads when editing | Covers |
|---|---|---|
| `rules/sports.md` | `sports.py`, `data.py`, `fetch.py` | `SportConfig` registry, the 10-sport table, identity/classification, fetch-by-family, the `build_contracts` row |
| `rules/kalshi-api.md` | `kalshi_client.py`, `data.py`, `fetch.py` | live Kalshi API (URLs, dollar-string prices, NO-side, status), tennis series, rate limiting |
| `rules/pricing.md` | `data.py`, `viz.py`, `glossary.py` | display %, quote quality, gross/top-of-book known limits |
| `rules/consistency.md` | `consistency.py`, `scanner.py`, `data.py` | Layer Consistency Checker hard rules, statuses, mapping/robustness invariants |
| `rules/dutchbook.md` | `dutchbook.py`, `scanner.py` | MECE dutch-book detector (2-way / n-way / winner field) |
| `rules/synthetic-bundle.md` | `synthetic_bundle.py`, `scanner.py` | N-leg exact-score synthetic bundle vs 2 hedges |
| `rules/ui.md` | `webui/**` | NiceGUI dashboard layout, the critical filter split, status labels |
| `rules/frontend.md` | `frontend/**`, `webui/feed.py` | React SPA (default UI): PRIME INVARIANT (view not engine), `/api/terminal/*` boundary, build/verify |
| `rules/serve-ops.md` | `serve.py`, `api.py`, `scan_manager.py`, `scan_scheduler.py` | LAN hosting / bind safety, non-blocking scan, auto-refresh |

## Run & verify

```bash
pip install -r requirements.txt          # runtime: requests, pandas, fastapi, nicegui, uvicorn
cd frontend && npm install && npm run build && cd ..   # build the default SPA UI → frontend/dist
python serve.py                          # SPA (/) + NiceGUI dashboard (/dashboard) + REST API, one app
pip install -r requirements-dev.txt      # adds pytest, pytest-asyncio, ruff
pytest -q                                # pure layers + in-process engine/API + headless NiceGUI smoke
ruff check .                             # lint
```

Verify without a browser: `pytest -q`; `python -c "import serve, api, webui.dashboard"`; a `serve.py`
boot — `GET /` (SPA), `/dashboard/` (NiceGUI), `/healthz`, `/metrics` → 200, `/readyz` →
`ready`/`degraded`/`not_ready`. The SPA is served from `frontend/dist` only when built (gitignored
artifact); an unbuilt tree leaves `/` unmounted but never breaks boot. Headless NiceGUI smoke is
`tests/test_browser.py` (`nicegui.testing`, no selenium). Live Kalshi calls, `pip`, and `git push` need
the Bash tool with the sandbox disabled (network is otherwise blocked). LAN/deploy specifics:
`rules/serve-ops.md` + `docs/DEPLOYMENT.md`.

## Architecture (module map)

```
config.py        # BASE_URL, DEFAULT_SERIES, prefixes, thresholds, rate-limit + refresh knobs
sports.py        # SportConfig registry + sport_for_series (no UI imports)
kalshi_client.py # read-only paginated GET, Retry-After/backoff, process-wide throttle, discovery
data.py          # parsing, to_cents, classify_kind/tour_of, pricing, tournament_of, build_contracts, fmt_time/age/stale
consistency.py   # nodes, representative, expected_nodes, layer_spreads, build_checks (groups [player_key,tournament]),
                 #   buy-only plan + tradable_now + blockers, bucket_of
dutchbook.py     # find_dutch_books — MECE detector (2-way / soccer n-way / winner field); EXECUTABLE_DUTCH_BOOK
synthetic_bundle.py # find_synthetic_bundles — N-leg exact-score bundle vs 2 hedges; EXECUTABLE_SYNTHETIC_BUNDLE
glossary.py      # GLOSSARY{short,long}, BLOCKERS, WATCHLIST_NOTE, help_for — single-sourced terms
filters.py       # apply_membership / apply_thresholds — the two-pass filter split
viz.py           # payoff_chart_data + ladder_prices (tidy chart frames)
fetch.py         # load_contracts (fetch-by-family) extracted from the old app
scanner.py       # cross-sport unified_opportunities (dutch-book + synthetic + containment)
store.py         # SQLite snapshot store (v3: opportunities + per-sport evidence frames); no pandas import
lifecycle.py     # new / changed / recently-actionable diffs over the store
scan_manager.py / scan_scheduler.py / presence.py / ratelimit.py  # singleflight, background loop, viewer gate, limiter
api.py           # FastAPI: /healthz /readyz /opportunities /coverage /metrics /scan /alerts /backlog
serve.py         # entrypoint: FastAPI API + NiceGUI dashboard on one app — the SOLE UI
webui/           # NiceGUI dashboard.py + pure viewmodel.py / diagnostics.py / engine.py / export.py
scripts/         # build_deploy_repo, check_links, export_glossary (→ docs/GLOSSARY.md, on demand), verify_sport, benchmark_scan
tests/           # pytest: full suite (pure layers + engine + API + viewmodel + headless browser)
```

`sports.py`, `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` MUST stay free of UI
imports (no `nicegui`, no `streamlit`) — pure logic, independently testable. **All price comparison logic
in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.

## Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`
  (Decimal, exact) for any comparison logic.
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks.
- Empty results are valid (between rounds → no open events), not errors.
- Always loop the `cursor`; the client raises on the `MAX_PAGES` cap with a cursor pending.
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- **The running server caches imported modules.** After editing a module while `serve.py` runs, **fully
  stop and restart** (there is no auto-reload); for a phantom `ImportError` clear bytecode too:
  `rm -rf __pycache__ tests/__pycache__`.
- The FO date window in `config.py` is year-specific — update it for future tournaments.
- The Kalshi **web** site is bot-throttled (429), so live link-reachability checks are unreliable here;
  `data.link_audit` proves link *correctness* deterministically, and `scripts/check_links.py` does a
  best-effort live check meant to run from an unthrottled network.
- Windows LF→CRLF warnings on commit are harmless.

## Claude Code specifics

- **Shell here-docs:** use the Bash tool's `<<'EOF'` for multi-line commit/PR text. PowerShell `@'...'@`
  here-strings corrupt messages through the Bash tool (stray `@`). Reference code as `path:line`.
- Verify with `pytest -q` + a `serve.py` boot (see Run & verify).
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, `*.db`, `.kss/`, and the machine-local
  `.claude/settings.local.json`. The rest of `.claude/` (`settings.json`, `rules/`, `memory/`) is **shared
  via git** so config follows you across machines — see `.claude/README.md` for the one-time per-machine setup.

## Git workflow (strict — owner confirmed 2026-06-16)

**`origin/main` is the single source of truth — always the most up‑to‑date code.** Whenever the owner says
"main" / "the main" they mean **`origin/main`** (the remote), NOT local `main` (which is often stale —
treat it as untrustworthy).

- **Always start from the freshest relevant code.** Before any new work: `git fetch origin`, then choose the
  base by the goal — **`origin/main` by default**, or **the newest relevant feature branch** when the work
  intentionally builds on un‑merged features (the owner says which; when unsure, ask). Never start from a
  *stale local* `main`. If you base on an unmerged branch, keep it current (periodically merge `origin/main`
  in) so it can't drift far behind.
- **Each new feature → its own branch, pushed to origin** (`git push -u origin <feature-branch>`). A pushed
  origin feature branch is the delivery unit; the owner reviews/merges it to `origin/main` when satisfied.
- **Never push or merge to `origin/main` directly** — the owner merges (PR). The agent only delivers
  verified feature branches on origin.
- Verify before handing back: `pytest -q`, `ruff check .`, `npm run build` + `npx vitest run` (if frontend),
  a `serve.py` boot, and a browser check of any UI change. State the base branch in the handoff.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  PR bodies end with the Claude Code footer.
- **Why this policy (lesson, 2026-06-16):** the prior "main is frozen → stack features on unmerged branches"
  rule let a long SPA feature stack drift ~8 days behind `origin/main`'s parallel NiceGUI work, forcing a
  large reconciliation merge. Stacking on an unmerged branch is fine *when the goal needs it* — the fix is to
  keep that branch current with `origin/main` so it never drifts that far again.
- **Staging hygiene:** stage explicit paths (`git add <files>`), never `git add -A`/`git add .` — the working
  tree carries untracked scratch (`.playwright-mcp/`, screenshots, mockups, `*.log`) that must NOT be committed.

## Status & history

Shipped state, current limits, and the approved next-work list live in **`docs/STATUS.md`**. Detailed
build history and decisions live in `.kss/` (topics + milestones). `pytest` is the full suite (pure
layers + engine + API + viewmodel + per-sport `test_*` + headless `test_browser`).
