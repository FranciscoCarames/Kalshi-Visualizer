# Agent Workflow

The practical day-to-day workflow for using **Claude Code**, **Codex**, multiple terminals, and future
worktrees on this repo. Goal: reduce manual back-and-forth, avoid stale approved plans, and keep
**implementation throughput higher than planning throughput**.

Companion docs (not repeated here): `docs/REVIEW_PROTOCOL.md` (risk classes + verdicts),
`docs/PR_CHECKLIST.md` (pre-merge pass), `AGENTS.md` (Codex's review contract).

## 0. Near-term delivery policy (owner, 2026-06-09)

**Branch from the latest `origin/main` — current policy (owner 2026-06-16, supersedes the "main is frozen →
stack on unmerged branches" rule).** `origin/main` is the single source of truth ("main" = `origin/main`,
never stale local `main`). Before any new work: `git fetch origin` and branch off **`origin/main`**
(`git checkout -b <feature> origin/main`). Each feature → its own branch, **pushed to origin**
(`git push -u origin <feature>`); the owner reviews/merges it to `origin/main`. **Never push/merge to
`origin/main` directly**, and **never stack a new feature on an unmerged branch** (that drift caused a large
SPA‑vs‑NiceGUI reconciliation in June 2026). Verify before handoff (`pytest -q`, `ruff`, `vitest`+`build` for
frontend, `serve.py` boot, browser check); note the base branch.

## 1. Default workflow

1. **Triage the idea** — what's the actual change and is it ready to implement soon?
2. **Classify risk** using `docs/REVIEW_PROTOCOL.md` (Low / Medium / High / Critical).
3. **Low-risk** → skip heavy plan review; go straight to a small PR.
4. **Medium / High-risk** → get a **concise** plan first (see §4).
5. **Codex** → use mainly for blocker-focused plan review on **high-risk** changes, and for
   implementation/diff review before merge.
6. **Implement small PRs** — one scoped change at a time.
7. **Finish with `docs/PR_CHECKLIST.md`.**

## 2. WIP limits

- At most **1 high-risk** implementation PR active at once.
- At most **1 medium-risk** implementation PR active at once, and only if it doesn't touch the same core
  files as another active PR.
- **Low-risk** docs/UI/test PRs may run in parallel — only if they don't touch the same files.
- Do **not** write full plans for work that can't enter implementation soon.
- Keep future ideas in `docs/STATUS.md` or a backlog — **not** as fully audited plans.

## 3. Parallel terminal / worktree rules

- One terminal / worktree per branch.
- Branch off **current `main`**.
- No stacking on unmerged branches.
- Never let two terminals edit the same **high-risk core file** at the same time.
- **High-risk core files:** `sports.py`, `data.py`, `consistency.py`, `dutchbook.py`,
  `synthetic_bundle.py`, `scanner.py`, `api.py`, `webui/viewmodel.py`, `webui/dashboard.py`, `store.py`,
  `lifecycle.py`, `fetch.py`, `kalshi_client.py`, `config.py`.

## 4. Plan lifecycle

- Plans are **short and implementation-oriented**.
- A plan includes: intended files, tests, risk class, assumptions, and rollback/revert notes.
- Plans **older than 7 days**, or plans touching files changed since they were written, require
  **revalidation** before building on them.
- Stop iterating once **no blockers remain** under the stated review scope.
- Don't wait for "no issues" — use **"no blockers found under this review scope."**

## 5. Codex usage

- Use Codex for **independent audit**, not routine implementation.
- Codex reviews follow `AGENTS.md` and `docs/REVIEW_PROTOCOL.md`.
- Ask Codex specifically for **blockers, major issues, missing tests, and regression risks**.
- Don't send every minor plan revision to Codex.
- Prefer Codex **diff review after implementation** over repeated plan loops — except for **high-risk
  market-logic** changes, where a plan review is worth it.

## 6. Claude Code usage

- Claude Code implements **small scoped branches**.
- Run `docs/PR_CHECKLIST.md` before handing work back.
- Do **not** modify `CLAUDE.md` unless explicitly asked.
- When new guidance would bloat `CLAUDE.md`, propose a separate `docs/*.md` file instead.

## 7. Documentation size rule

- Keep `CLAUDE.md` focused on **durable project invariants, scope guards, architecture boundaries,
  critical commands, and current workflow rules**.
- Do **not** add long feature history, sports matrices, API-assumption dumps, detailed review protocols,
  or PR checklists to `CLAUDE.md`.
- Put specialized material into `docs/*.md`.
- Before adding more than a short paragraph to `CLAUDE.md`, propose whether it belongs in a separate
  docs file.

## 8. Handoff format

Every active branch should carry:

- **Branch name**
- **Goal**
- **Risk class**
- **Touched files**
- **Current status**
- **Tests run**
- **Blockers / residual risks**
- **Next action**
