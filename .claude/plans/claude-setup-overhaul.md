# Plan: Claude Code Setup Overhaul

**Status:** DRAFT — brainstormed, NOT yet approved, NOTHING started. Do not change anything until the
owner explicitly says "go."
**Created:** 2026-06-17 (desktop, branch `desktop-sync`).
**Goal of this effort:** a ground-up rebuild of the entire *agent-facing surface* of the project
(CLAUDE.md, AGENTS.md, docs, MEMORY.md/memories, `.claude/` hooks/skills/agents/settings, MCP, and the
parallel-work harness), optimized to attack the app's real pains efficiently.

> **Rule #1 (owner, explicit): trust NO document as correct until verified against the code.** Every
> existing doc/memory may be stale. The first real phase is a drift audit, not a rewrite.

---

## A. Context captured from the brainstorm (so a fresh session has full picture)

### The app (destination)
- **What it is:** read-only NiceGUI + React SPA trader dashboard over live Kalshi prediction-market data
  for 10 sports; surfaces executable inconsistencies (containment ladders) + dutch-book arbitrage +
  synthetic bundles, ranked Actionable/Review/Blocked. SPA at `/` is default UI; NiceGUI at `/dashboard`.
- **Audience:** a **small group of trusted, experienced traders.** Usability must be judged **from a
  trader's perspective**, not a casual user's.
- **Wants the app to be GREAT at (all four):** trustworthy signals · speed/real-time edge · breadth of
  coverage · clarity/actionability.
- **Biggest issues TODAY (owner's words):** not real-time enough · coverage gaps · signal trust/accuracy
  · "UI is full of issues and compromises usability."
- **6–12 month vision:** start small, expand later; become **as good as possible as a resource for the
  traders.**

### The workflow contract (vehicle) — how the owner wants to work from now on
- **Loop:** brainstorm ideas → reach a plan the owner approves → after approval, make a NEW branch off
  the **most current version of the code** (`origin/main`, per git policy) → build the WHOLE plan
  **autonomously** in that branch → run a **fully comprehensive set of tests at EVERY stage** → owner
  opens the running app and **manually tests** → merge **only if fully correct.**
- **Planning:** mix of `.kss` topics/milestones + plan-mode, chosen per situation.
- **Parallelism:** owner wants to **implement multiple features in parallel** for efficiency.
- **Parallel merge strategy:** **batch parallel features onto ONE integration branch**, run the full
  gate on the combined result, owner manual-tests the whole bundle once.
- **Definition of done:** **full gate every time** (pytest + ruff + frontend build/vitest + `serve.py`
  boot + browser check of any UI change) + owner manual test at the end.
- **Codex role:** mostly Claude Code; Codex used rarely → **AGENTS.md = thin pointer to CLAUDE.md**
  (parity for free, no heavy Codex investment).
- **Doc authorship:** **collaborative, section by section** — owner + agent converge per section. Owner
  is rewriting CLAUDE.md to optimize it; agent supplies verified facts and drafts per section.
- **Hooks appetite:** **MODERATE** — guardrails + confirmations only. No auto-pytest-on-stop, no
  surprise heavy commands, no auto-format.

### Key structural fact that shapes everything
`.claude/` is **gitignored** (verified). So hooks/skills/agents/settings are **local-only**, never part
of a PR. The overhaul splits into two tracks:
- **Tracked track** (CLAUDE.md, AGENTS.md, `docs/`, `MEMORY.md`) → feature branch off `origin/main` →
  owner manual-test → merge. This is the **collaborative** track.
- **Local track** (`.claude/` hooks/skills/agents/permissions/MCP) → applied to the working tree
  directly, mirrored to the private `desktop` remote only, **never** pushed to `origin`. More autonomous.

### Repo state at planning time (2026-06-17)
- **PR #152 (`feat/scanner-consolidated`) MERGED** into `origin/main` (`3975058`). (MEMORY.md still
  calls it "OPEN" — that's drift to fix.) origin/main now = SPA + NiceGUI + auth + consolidated
  detectors + full ladder closure + Stage-1 SSE + S2 numeric (diagnostic-only) + pop-outs + table clarity.
  Reported at merge: pytest 1282 · vitest 85 · ruff clean.
- Current branch `desktop-sync` is 1 ahead (local mirror snapshot `9b96dc4`) / 1 behind (the #152 merge).
- Open app-level items: S2 numeric ladders are diagnostic-only (owner wants them wired later behind an F0
  gate); `snapshots.db` compaction not yet run (`snapshots.db.pre-compact-backup` exists untracked).

### Current setup inventory (what exists today)
- **Docs:** CLAUDE.md (~300 dense lines), AGENTS.md, `docs/` (AGENT_WORKFLOW, REVIEW_PROTOCOL,
  PR_CHECKLIST, STATUS, DEPLOYMENT, AUTH, TERMINAL_SPA, DASHBOARD_COLUMN_GUIDE, REALTIME_LIVE_FEED_PLAN).
  Stale root handoffs: CONSOLIDATION_HANDOFF.md, HANDOFF-convergence-20260610.md, S2_NUMERIC_PROBE.md,
  WAVE2_STATUS.md.
- **`.kss/`:** full planning system in active use (topics, milestones, codebase snapshot, CANONICAL-KB).
- **`.claude/`:** `settings.json` (1 PreToolUse hook), `hooks/guard_git.py` (79-line git-safety guard —
  GOOD, keep), `skills/run-latest/` (1 skill), `settings.local.json` (**heavily crufted** — ~120 perms,
  many from OTHER projects: `Desktop/Internship`, `kalshi-retire-streamlit`, `kalshi-perf`,
  `kalshi-ui-bakeoff`, plus one-off temp paths).
- **MCP available:** Playwright, GitHub, Context7, Canva, Gamma, Google Drive. Relevant = Playwright
  (UI verify) + GitHub (PRs) + Context7 (lib docs); rest not relevant here.
- **Memories (`MEMORY.md` index):** several entries stale (PR #152 "OPEN", "awaiting merge" entries now
  in main).

---

## B. The proposed plan (4 levers / phased)

> Sequencing recommendation: **Phase 1 (drift audit) first** — read-only, grounds the rewrite in verified
> facts, and demonstrates the parallelism goal. (OPEN — see open questions.)

### Phase 0 — Branch + scaffold *(autonomous, fast)*
- `git fetch origin`; create `feat/claude-setup-overhaul` off `origin/main`.
- Open a `.kss` topic to hold work + history.

### Phase 1 — Drift audit ("trust nothing") *(autonomous, read-only, PARALLEL)*
- Fan out read-only agents (one per doc / claim-cluster) to verify every claim in CLAUDE.md / AGENTS.md /
  `docs/*` / `MEMORY.md` against the actual modules (`sports.py`, `consistency.py`, `dutchbook.py`,
  `synthetic_bundle.py`, `api.py`, `serve.py`, `data.py`, etc.).
- Output: a **drift report** (accurate / stale / wrong / duplicated) → becomes the fact-list for Phase 2.

### Phase 2 — Docs rewrite *(COLLABORATIVE, section by section)* — on the feature branch
- **CLAUDE.md:** full rewrite, single-sourced, with an explicit **trader-POV usability rule**. Section by
  section with the owner.
- **AGENTS.md:** reduce to a thin pointer to CLAUDE.md.
- **`docs/`:** dedupe AGENT_WORKFLOW / REVIEW_PROTOCOL / PR_CHECKLIST; archive stale root handoffs
  (CONSOLIDATION_HANDOFF, HANDOFF-convergence, S2_NUMERIC_PROBE, WAVE2_STATUS) into `.kss` history.
- **MEMORY.md + memory files:** fix #152-merged drift; retire "awaiting merge" entries.

### Phase 3 — Workflow tooling *(autonomous, local `.claude/`)*
- **Hooks (MODERATE):** keep `guard_git.py`; add (a) staging-hygiene confirm on `git add -A` / `git add .`;
  (b) scope-guard confirm when an edit introduces out-of-scope concepts (order placement / de-vig in the
  SPA / net-of-fees math); (c) non-blocking full-gate reminder on `git commit` / `git push`.
- **Skills:** `/new-branch` (fetch + branch off freshest base), `/full-gate` (the exact pytest + ruff +
  build + vitest + boot + healthz/readyz sequence), `/pre-pr` (gate + PR_CHECKLIST + draft PR),
  `/verify-sport <sport>`, `/add-sport` (SportConfig scaffold), `/ui-review` (Playwright walkthrough
  scored from a trader's POV). Keep `run-latest`.
- **Custom agents (`.claude/agents/`):** `detector-auditor` (trust), `trader-ux-reviewer` (UI),
  `sport-adder` (coverage), `doc-verifier`.
- **Permissions:** prune `settings.local.json` to this-project-only (remove Internship/kalshi-perf/
  kalshi-ui-bakeoff/temp-path cruft). Optionally regenerate via `/fewer-permission-prompts`.
- **MCP:** document keep = Playwright + GitHub + Context7; ignore Canva / Gamma / Google Drive.

### Phase 4 — Parallel-build harness *(convention + scripts)*
- Worktree-isolated parallel features → **integration-branch batching** → combined full gate → owner
  manual test (matches the chosen parallel-merge strategy).
- Optional reusable Workflow scripts for wide sweeps (doc audit, multi-sport verification).

**Gate per phase:** any phase touching runnable code (skills/agents/hooks) gets smoke-tested; the docs
branch rides the full pytest / ruff / build / boot gate before handback.

---

## C. How each app pain maps to the setup (why this is worth doing)
- **Signal trust** → `detector-auditor` agent + drift audit + (later) adversarial-verify workflows.
- **Real-time** → skill to arm/test the Stage-1 SSE / live feed; keep realtime plan doc current.
- **Coverage** → `/add-sport` + `/verify-sport` + `sport-adder` agent.
- **UI/usability** → `trader-ux-reviewer` agent + `/ui-review` Playwright skill (trader-POV is the lens).
- **Workflow contract enforcement** → `/full-gate`, `/pre-pr`, `/new-branch` skills + moderate hooks.

---

## D. OPEN QUESTIONS to resolve before locking the plan
1. **Sequencing:** start with Phase 1 (drift audit) as recommended, or do the quick `settings.local.json`
   cleanup first as a confidence-builder? (Owner has not answered.)
2. **Scope:** does this overhaul also produce a concrete **app-roadmap doc** (sequencing the real-time /
   coverage / trust / UI work itself), or stay strictly about the Claude Code *setup* and tackle the app
   roadmap separately afterward? (Owner has not answered.)
3. Any phases to **cut or add**, and the final ordering.

## E. Next action for a fresh session
Re-read this file. Confirm repo state (`git fetch origin`, check whether `desktop-sync` / `origin/main`
moved). Resolve the open questions in section D with the owner, then ask for explicit "go" before
Phase 0. Until then: **brainstorm/plan only — change nothing.**
