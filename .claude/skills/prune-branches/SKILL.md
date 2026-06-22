---
name: prune-branches
description: Clean up merged git branches (local, and list deletable remote ones). Use when the user wants to prune/tidy/delete merged branches, reduce branch sprawl, or clean up after merges.
---

# Prune merged branches

This repo accumulates many merged branches (local per-machine; ~190 on the remote). Use the bundled script
— it only ever deletes branches **fully merged into origin/main**, with `git branch -d` (the safe,
merged-only delete; never `-D`), and never touches the current branch, `main`, `master`, or `desktop-sync`.

## Steps

1. **Dry run first** (shows what would go, deletes nothing):
   ```bash
   bash scripts/prune_merged_branches.sh
   ```
2. Review the two lists: merged **local** branches (safe to delete) and merged **remote** branches (printed
   as ready-to-run `git push origin --delete …` lines for you to review).
3. **Apply** to delete the merged local branches + prune stale remote-tracking refs (`git remote prune origin`):
   ```bash
   bash scripts/prune_merged_branches.sh --apply
   ```
4. **Remote branch deletion is left to the human** — it's an outward action on `origin` (and the `desktop`
   mirror). Run the printed `git push origin --delete <branch>` lines only for branches you're sure about.

Note: the `block-dangerous-git` hook permits `git branch -d` (safe) and blocks `git branch -D` (force) — so
this script's deletions pass, but a careless force-delete won't. Consider running this periodically (e.g. a
weekly `/schedule` routine) so branch count never balloons again.
