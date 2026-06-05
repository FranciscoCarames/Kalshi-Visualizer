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
4. Install the wrapper + units:
   ```bash
   sudo install -m 0755 deploy/scan.sh /opt/kalshi-dashboard/scan.sh
   sudo cp deploy/kalshi-dashboard*.service deploy/kalshi-dashboard-scan.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now kalshi-dashboard kalshi-dashboard-scan.timer
   ```

## Env vars
| Var | Required | Notes |
|---|---|---|
| `API_HOST` | yes | `0.0.0.0` for LAN |
| `API_PORT` | yes | e.g. 8000 (open the firewall to the LAN only) |
| `NICEGUI_STORAGE_SECRET` | yes (LAN) | serve.py refuses a non-loopback bind without it |
| `SNAPSHOT_DB_PATH` | yes | local-disk path, writable by the service user |
| `SCAN_TOKEN` | optional | gate `POST /scan`; `scan.sh` sends the header when set |

## Health
- `curl http://127.0.0.1:$API_PORT/healthz` → `{"status":"ok"}` (liveness)
- `curl http://127.0.0.1:$API_PORT/readyz` → `ready` after the first scan (`degraded` before)
- One process only: `sudo ss -ltnp | grep :$API_PORT`
