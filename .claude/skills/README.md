# `.claude/skills/` — installed skills

Skills load on demand (by description match or `/name`). These are committed, so they sync across machines.

## Project-authored

| Skill | What it does |
|---|---|
| `add-a-sport` | Step-by-step guide to onboard a new sport via a `SportConfig` drop-in in `sports.py` (identity → classification → ladder → `verify_sport.py` → per-sport test → verify). The one owner-blessed engine extension. |

## Vendored from [`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT — see `LICENSES/`)

| Skill | What it does | Invocation |
|---|---|---|
| `handoff` | Compacts the current conversation into a handoff doc (written to the OS temp dir) so a fresh session can continue. Pairs well with the context-gauge status line. | `/handoff` (user-invoked) |
| `tdd` | Red-green-refactor, one vertical slice at a time; behavior-through-public-interface tests. Fits this repo's "no behavior change without a test" rule. | model- or user-invoked |
| `diagnosing-bugs` | Structured reproduce → minimize → hypothesize → instrument → fix loop (+ a human-in-the-loop reproduction template). | model- or user-invoked |
| `grill-me` / `grilling` | Relentless one-question-at-a-time interview to stress-test a plan before building. (`grill-me` calls `grilling`; keep both.) | `/grill-me` (user-invoked) |
| `git-guardrails-claude-code` | Reference for the git-guardrails pattern. **Its bundled bash script is NOT the active guard** — a customized Python version is wired instead (see below), because the bundled one blocks *all* `git push` and would break feature-branch delivery. | `/git-guardrails-claude-code` |

## Vendored from [`anthropics/skills`](https://github.com/anthropics/skills) (Apache-2.0 — `LICENSE.txt` in each folder)

| Skill | What it does | Runtime dep |
|---|---|---|
| `skill-creator` | Official skill-authoring + iterative-eval/benchmark loop (draft → test → review → improve → optimize description). Use it to write/improve skills like `add-a-sport`. Its `scripts/` call the local `claude -p` CLI (session auth, no extra key). | `claude` CLI (present); subagents for the full eval loop |
| `webapp-testing` | Local web-app testing with Playwright — drive the React SPA, capture screenshots, read console logs. `scripts/with_server.py` boots your dev server + waits on the port. | `pip install playwright && playwright install chromium` (only when used) |

> You also have the `claude-in-chrome` MCP for browser work; `webapp-testing` is the scripted-Playwright alternative.

## Notes
- `tdd` softly references a `/codebase-design` skill that isn't installed — harmless; that step is optional.
- Vet any third-party `SKILL.md` (and its `scripts/`) before installing — a skill is instructions Claude will follow.
  All skills here were read end-to-end (incl. scripts) before install: no network exfil, destructive ops, or secrets.
