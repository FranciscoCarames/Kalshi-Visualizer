#!/usr/bin/env bash
# Prune branches that are fully merged into origin/main — safely.
#
# Default: DRY RUN (prints what would be removed, deletes nothing).
#   bash scripts/prune_merged_branches.sh
# Apply:  deletes merged LOCAL branches (git branch -d, the safe merged-only delete) and prunes stale
#         remote-tracking refs (git remote prune origin).
#   bash scripts/prune_merged_branches.sh --apply
#
# Never touches: the current branch, main, master, or desktop-sync. Never force-deletes (-d, not -D).
# Never deletes REMOTE branches — that is an outward action; this script only LISTS them so you can
# review and delete the ones you want by hand.
set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

KEEP='^\*|^\+|/?(main|master|desktop-sync)$'

git fetch origin --quiet --prune

echo "== Local branches merged into origin/main (safe to delete) =="
mapfile -t MERGED < <(git branch --merged origin/main | sed 's/^[* +]*//' | grep -vE "$KEEP" || true)
if [ "${#MERGED[@]}" -eq 0 ]; then
  echo "  (none)"
else
  printf '  %s\n' "${MERGED[@]}"
fi

echo
echo "== Remote branches on origin merged into origin/main (review + delete by hand) =="
git branch -r --merged origin/main \
  | sed 's/^[ ]*//' \
  | grep -vE 'origin/(main|HEAD)' \
  | sed 's#^origin/#  git push origin --delete #' || echo "  (none)"

if [ "$APPLY" -eq 1 ] && [ "${#MERGED[@]}" -gt 0 ]; then
  echo
  echo "== Applying: deleting ${#MERGED[@]} merged local branch(es) =="
  printf '%s\n' "${MERGED[@]}" | xargs -r -n1 git branch -d
  git remote prune origin
  echo "Done."
else
  echo
  echo "(dry run — re-run with --apply to delete the merged LOCAL branches and prune stale refs)"
fi
