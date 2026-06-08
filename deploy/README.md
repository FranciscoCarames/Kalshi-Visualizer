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
