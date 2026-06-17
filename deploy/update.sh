#!/usr/bin/env bash
# One-command update for a systemd deployment of this app (#12 of the scanner backlog).
#
# WHY: a bare `git pull` updates CODE but not the two things the code depends on — installed Python
# packages and the BUILT frontend (frontend/dist, gitignored). It also can't warn about behavioral
# changes (e.g. auth now defaults ON). This script does the full, safe sequence.
#
# Usage (from the deploy checkout, as the operator):  sudo -E deploy/update.sh
# Override defaults via env, e.g.:
#   SERVICE=structured-scanner HEALTH_URL=http://127.0.0.1:5300 VENV=/opt/app/.venv deploy/update.sh
#
# It is intentionally conservative: fast-forward-only pull, no DB/.env backup (copying a live SQLite file
# mid-write risks corruption — stop the service first if you want a cold backup), and it prints an exact
# rollback command before restarting so a bad deploy is a one-liner to revert.
set -euo pipefail

SERVICE="${SERVICE:-kalshi-dashboard}"          # systemd unit name
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000}"
VENV="${VENV:-.venv}"                            # path to the virtualenv (uv-managed, Python 3.13)
BRANCH="${BRANCH:-main}"                         # expected branch
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"          # ~30s of /healthz polling after restart

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "git not found"
[ -d .git ] || die "run from the repository root (no .git here)"

# 1) Safety: clean tree + expected branch, and record the current commit for rollback.
[ -z "$(git status --porcelain)" ] || die "working tree is dirty — commit/stash or clean it before updating"
cur_branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$cur_branch" = "$BRANCH" ] || die "on branch '$cur_branch', expected '$BRANCH' (set BRANCH= to override)"
OLD_COMMIT="$(git rev-parse HEAD)"
log "current commit: $OLD_COMMIT"
echo "    rollback if needed:  git checkout $OLD_COMMIT && sudo systemctl restart $SERVICE"

# 2) Pull CODE (fast-forward only — never silently merge).
log "git pull --ff-only origin $BRANCH"
git pull --ff-only origin "$BRANCH"

# 3) Sync Python deps (uv-managed venv has no pip inside; fall back to the venv's pip if uv is absent).
log "installing Python dependencies"
if command -v uv >/dev/null; then
  VIRTUAL_ENV="$(pwd)/$VENV" uv pip install -r requirements.txt
else
  "$VENV/bin/pip" install -r requirements.txt
fi

# 4) Rebuild the SPA (frontend/dist is gitignored — prod serves it, so it MUST be rebuilt every deploy).
if [ -d frontend ]; then
  log "rebuilding the SPA (npm ci && npm run build)"
  ( cd frontend && npm ci && npm run build )
fi

# 5) Restart and verify health (fail loudly — do NOT leave a broken service "started").
log "restarting $SERVICE"
sudo systemctl restart "$SERVICE"

log "waiting for health at $HEALTH_URL/healthz"
ok=""
for _ in $(seq 1 "$HEALTH_RETRIES"); do
  if curl -fsS "$HEALTH_URL/healthz" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || die "service did not become healthy. Roll back:  git checkout $OLD_COMMIT && sudo systemctl restart $SERVICE"
ready="$(curl -fsS "$HEALTH_URL/readyz" 2>/dev/null || true)"
log "healthy. /readyz: ${ready:-<no response>}"
echo "    (updated $OLD_COMMIT -> $(git rev-parse HEAD))"
