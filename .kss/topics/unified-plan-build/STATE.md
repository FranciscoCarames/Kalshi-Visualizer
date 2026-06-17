---
topic: unified-plan-build
status: between-milestones
active_milestone: null
last_session: 2026-06-05
last_updated: 2026-06-05
---

# Topic State: unified-plan-build

Last shipped: **phase-f-followons** on 2026-06-05 (see `milestones/phase-f-followons/SUMMARY.md`).

## Where things stand

The UNIFIED-PLAN core (Phases A–F) is **complete and fully merged** — PRs #48–#77 all on `origin/main`
(incl. 27a advance hedge #75, 27b winner FIELD #76, 28 known-limits docs #77).

Run `plan-milestone` to scope the next milestone, or close the topic with
`complete-milestone --archive-topic` if the remaining work below isn't wanted.

## Remaining (all optional — seeds, see SEEDS.md)

- Advancement-FIELD detector (n-outcome reach-a-stage 1-of-N) — needs a live discovery gate + exhaustiveness proof (S5).
- Field UNDERROUND — needs an exhaustiveness signal we don't currently have (S6).
- K-of-N qualifier fields (S7).
- **PR 11** — soccer tournament-scope missing-layer suppression (owner decision §7 Q9; default = skip) (S2).
- **GDrive docs refresh** (standing rule) across 27a/27b/28 — **now actionable** (#77 merged); do next (S8).

## Environment

- Impl worktree: `C:\Users\Batata\Desktop\kalshi-impl` (currently on `feat/p30-known-limits-docs`; branch
  fresh off fetched `origin/main` for any next PR; delete merged branches).
- Primary tree `C:\Users\Batata\Desktop\Internship` stays on `feat/round-parser-fix` (planning docs).
- Per-PR battery: `pytest -q` + `ruff check .` + import smoke + headless boots (streamlit `/_stcore/health`,
  `serve.py /healthz` on a NON-default port — never touch the shared :8000 process) + a sandbox-disabled
  live smoke. Never push to `main`; owner merges.
