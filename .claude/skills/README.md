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
| `git-guardrails-claude-code` | **Setup** skill: wires a PreToolUse hook that blocks dangerous git. **Inert until you run it.** ⚠️ As shipped it blocks **all** `git push`, which would break this repo's feature-branch delivery — customize the blocked list (block `origin/main` pushes / `--force` / `reset --hard` / `clean -f` / `branch -D`, but **allow** feature-branch pushes) before activating. Its script also needs `jq`. | `/git-guardrails-claude-code` |

## Notes
- `tdd` softly references a `/codebase-design` skill that isn't installed — harmless; that step is optional.
- To add an official Anthropic skill later (Apache-2.0, [`anthropics/skills`](https://github.com/anthropics/skills)),
  copy the skill's folder here and vendor its `LICENSE.txt`. Candidates that fit this repo: `skill-creator`,
  `webapp-testing`.
- Vet any third-party `SKILL.md` (and its `scripts/`) before installing — a skill is instructions Claude will follow.
