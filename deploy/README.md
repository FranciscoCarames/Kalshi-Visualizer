# Kalshi LAN dashboard — deploy artifact

Runtime-only (NiceGUI on FastAPI via `serve.py`). **Generated** from the source repo by
`scripts/build_deploy_repo.py` — do not hand-edit. Full runbook: the source repo's `docs/DEPLOYMENT.md`.
Internal-only; **do not expose to the public internet.**

## Install (Linux + systemd)
1. Create the service user + data dir:
   ```bash
   sudo useradd --system --home /opt/kalshi-dashboard --shell /usr/sbin/nologin kalshi-dashboard
   sudo install -d -o kalshi-dashboard -g kalshi-dashboard /var/lib/kalshi-dashboard
   ```
2. Put this repo at `/opt/kalshi-dashboard`, create the venv, install (Python **3.13**):
   ```bash
   python3.13 -m venv /opt/kalshi-dashboard/.venv
   /opt/kalshi-dashboard/.venv/bin/pip install -r requirements.txt
   ```
3. `sudo cp deploy/.env.example /etc/kalshi-dashboard.env`, edit it, then
   `sudo chmod 640 /etc/kalshi-dashboard.env && sudo chown root:kalshi-dashboard /etc/kalshi-dashboard.env`.
4. Install the units and enable the service:
   ```bash
   sudo cp deploy/kalshi-dashboard.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now kalshi-dashboard
   ```
   `kalshi-dashboard.service` runs the in-process auto-scan loop on its own — this is the default and
   all you need. For **headless 24/7** scanning (no browser ever connected), set
   `AUTO_SCAN_PAUSE_WHEN_IDLE=0` in the env file (below) so the loop keeps scanning with zero viewers.

   > **Pick ONE scan model — never both.** Do **not** also enable `kalshi-dashboard-scan.timer`
   > alongside the service: the in-process loop and the external timer would BOTH scan, doubling the
   > Kalshi request rate. Only enable the timer if you instead disable the in-process loop
   > (`AUTO_SCAN_DEFAULT_ENABLED`); see the source repo's `docs/DEPLOYMENT.md`. To use the external
   > timer install its units + wrapper:
   > ```bash
   > sudo install -m 0755 deploy/scan.sh /opt/kalshi-dashboard/scan.sh
   > sudo cp deploy/kalshi-dashboard-scan.service deploy/kalshi-dashboard-scan.timer /etc/systemd/system/
   > sudo systemctl daemon-reload && sudo systemctl enable --now kalshi-dashboard-scan.timer
   > ```

## Env vars
| Var | Required | Notes |
|---|---|---|
| `API_HOST` | yes | `0.0.0.0` for LAN |
| `API_PORT` | yes | e.g. 8000 (open the firewall to the LAN only) |
| `NICEGUI_STORAGE_SECRET` | yes (LAN) | serve.py refuses a non-loopback bind without it |
| `SNAPSHOT_DB_PATH` | yes | local-disk path, writable by the service user |
| `AUTO_SCAN_PAUSE_WHEN_IDLE` | optional | `0` = headless 24/7 (scan with no viewer); default/`1` = pause when no browser connected |
| `SCAN_TOKEN` | optional | gate `POST /scan`; `scan.sh` sends the header when set |

## Health
- `curl http://127.0.0.1:$API_PORT/healthz` → `{"status":"ok"}` (liveness)
- `curl http://127.0.0.1:$API_PORT/readyz` → `ready` after the first scan (`degraded` before)
- One process only: `sudo ss -ltnp | grep :$API_PORT`

## Updating (after a new release)
A bare `git pull` updates **code only** — NOT the installed Python packages and NOT the built frontend
(`frontend/dist` is gitignored and is what prod serves). Run the bundled script, which does the whole safe
sequence (clean-tree + branch check → record commit + print a rollback line → `git pull --ff-only` →
`uv pip install -r requirements.txt` → `npm ci && npm run build` → `systemctl restart` → poll `/healthz`):
```bash
sudo -E SERVICE=kalshi-dashboard HEALTH_URL=http://127.0.0.1:$API_PORT deploy/update.sh
```
Defaults: `SERVICE=kalshi-dashboard`, `HEALTH_URL=http://127.0.0.1:8000`, `VENV=.venv`, `BRANCH=main`.
If it reports unhealthy it prints the exact rollback command (`git checkout <old> && systemctl restart …`).

### Toolchain assumptions (don't drift)
- **Python 3.13**, venv is **uv-managed** (no `pip` inside): install with `uv pip install -r requirements.txt`
  — `requirements.txt` is the source of truth (a new import MUST be added there).
- **Node**: deploys use `npm ci` (needs `package-lock.json`), not `npm install`, for reproducibility.
- `frontend/dist` must be rebuilt on every deploy that pulls frontend changes (the update script does this).

## Upgrading from an older (auth-less) deploy — READ THIS
The React rewrite turned **authentication ON by default** (`serve.apply_runtime_defaults()` setdefaults
`AUTH_ENABLED=1` + open signup). With auth on, `serve.py`'s fail-closed bind guard **refuses a non-loopback
bind** unless you also have a seeded user, TLS (or a declared HTTPS reverse proxy), and `APP_ALLOWED_HOSTS`.
A previously auth-less LAN deployment ("WireGuard is the perimeter") will therefore **fail to start** after
the update. Two choices:
- **Keep the old open posture:** set `AUTH_ENABLED=0` in the env file (the guard messages are otherwise
  buried in `journalctl`).
- **Adopt auth:** seed a user (`python manage_users.py add <name>`), set `APP_ALLOWED_HOSTS`, and put TLS /
  a reverse proxy in front. See `docs/AUTH.md`.

Note (2026-06-17): the password **strength floor was removed** by owner decision — any non-empty password is
accepted on a trusted-LAN install. Keep this app off the public internet, and consider `AUTH_ALLOW_SIGNUP=0`
so only admin-created accounts exist. See `docs/AUTH.md`.
