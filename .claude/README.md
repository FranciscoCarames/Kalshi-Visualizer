# `.claude/` — shared Claude Code config

This directory is **committed to git on purpose** so your Claude Code setup follows you across machines.
Only machine-local files are gitignored.

## What's tracked (shared across machines)

| Path | Purpose |
|---|---|
| `settings.json` | Team/project settings: permissions + the doc-size guard hook |
| `rules/*.md` | Path-scoped "do not regress" invariants — auto-load when you open a matching file (see `CLAUDE.md` → "Rules map") |
| `memory/*.md` | Auto-memory notes (preferences, project direction). `MEMORY.md` is the index |
| `skills/*/SKILL.md` | Installed skills (load on demand). `add-a-sport` is project-authored; others vendored from `mattpocock/skills` (MIT). See `skills/README.md` |
| `hooks/check_doc_size.py` | Stop hook that warns (once per turn, non-blocking) when `CLAUDE.md`/a rule file exceeds its line budget |
| `statusline.py` | Status-line script (wired via `settings.json` `statusLine`): coloured context-window gauge that warns "⚠ WRAP UP" past 85% usage, so you know when to `/compact` or start a fresh session |

## What stays local (gitignored)

- `settings.local.json` — machine-specific. Holds `autoMemoryDirectory` (an **absolute** path that differs
  per machine) plus any personal permission overrides.

## One-time setup on a new machine

Auto-memory must point at this repo's `.claude/memory/` so notes sync through git. The setting requires an
**absolute** path, so each checkout sets its own in the gitignored `settings.local.json`:

```jsonc
// .claude/settings.local.json   (NOT committed)
{
  "autoMemoryDirectory": "<absolute path to this repo>/.claude/memory"
}
```

Replace `<absolute path to this repo>` with the real checkout location (forward slashes work on Windows),
then restart Claude Code and accept the workspace-trust prompt if shown. Confirm with `/memory` that the
folder resolves to the in-repo `.claude/memory/`.

## Syncing memory

Because memory lives in git, Claude's mid-session memory writes appear as **uncommitted changes** under
`.claude/memory/`. Commit and push them (alongside your other work) to carry them to your other machine.
They are preference/roadmap notes, never secrets — but, as always, glance at a diff before committing.
