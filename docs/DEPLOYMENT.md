# Deployment Plan — Kalshi Opportunity Dashboard (internal office hosting)

Hand-off guide for hosting the dashboard so **any device on the office network** can open it in a
browser. Verified working over a controlled network (phone hotspot); the only remaining work is to host
it where every office device can route to it. No authentication is required (internal, read-only public
market data) per the agreed decisions below.

## Decisions (locked)

| Topic | Decision |
|---|---|
| Host environment | **Linux + systemd** (primary). Windows/NSSM is the only alternative. **No day-one Docker** (deferred follow-up) |
| Access control | **Open on the internal network** — no login. Data is read-only public market data |
| Data refresh | **Scheduled auto-scan (REQUIRED, default-on)** — a systemd timer calls `POST /scan` every 2–5 min |

---

## 0. Prerequisite (satisfied by the LAN-finalization PR)

`serve.py` reads `API_HOST`/`API_PORT` from the environment; the default is `127.0.0.1` (loopback only)
so LAN exposure is a deliberate opt-in. Exposing a non-loopback host (`API_HOST=0.0.0.0`) **requires**
`NICEGUI_STORAGE_SECRET` — `serve.py` refuses to start without it (the dashboard has no auth and the
session cookie is signed with the secret). For a quick trusted-LAN test you may override with
`ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`, which starts with a loud warning.

- Verify after cloning: `serve.py`'s `__main__` reads `os.getenv("API_HOST", ...)` and calls
  `bind_safety(...)` before binding.

---

## 1. What IT is running (architecture recap)

- One Python process: **FastAPI engine API + NiceGUI dashboard on the same app/port** (`python serve.py`).
- **UI:** `GET /` · **REST:** `/opportunities`, `/backlog`, `/coverage`, `/alerts`, `/metrics`, `POST /scan` ·
  **OpenAPI:** `/docs` · **Liveness:** `/healthz` → `{"status":"ok"}` · **Readiness:** `/readyz` →
  `ready`/`degraded`/`not_ready` (DB writable + a fresh snapshot; 503 when not ready).
- **State:** a single SQLite file (`snapshots.db`, path = `config.SNAPSHOT_DB_PATH`) holding ranked
  opportunity snapshots. The UI reads the latest snapshot; a scan writes a new one.
- **Outbound:** the process fetches live data from `https://external-api.kalshi.com` (read-only, no auth).
- **Run EXACTLY ONE worker / one instance.** The snapshot store, the Kalshi request throttle
  (`MAX_RPS=15`, ~75% of the Basic ceiling), and the in-process auto-scan scheduler are **process-local**:
  multiple workers (`WEB_CONCURRENCY>1`, `uvicorn --workers N`) or replicas each keep their own, which
  **fragments the data** (divergent snapshots), runs a scan loop per worker, and multiplies the request
  rate past Kalshi's free-tier limit (aggregate = `15 × N`). `serve.py` warns if `WEB_CONCURRENCY>1` /
  `--workers` is set. The 15/s cap is safe only for a single process.
- **Auto-scan: prefer the in-process scheduler.** `python serve.py` runs a built-in periodic scan loop
  (default-on; cadence via the dashboard's Auto-refresh toggle). The optional systemd `scan.timer` below is
  **safe but redundant** alongside it — and only loosely deduped (`SCAN_MIN_INTERVAL_SECONDS=8`), so a
  3-minute external fire can still add the occasional extra scan. **Disable the `scan.timer` when relying on
  the in-process scheduler** (use the timer only if you run the app under a manager that can't keep the loop alive).

---

## 2. Network reachability (the crux — IT action)

This is what turns "works on my hotspot" into "works for everyone."

- Office Wi-Fi likely **isolates clients** (devices can't reach each other). So **do not host on the
  client Wi-Fi segment.** Place the server where the client Wi-Fi can **route to it** — a server
  VLAN/subnet reachable from the client network, or a wired host with the appropriate firewall/routing.
- Give the host a **stable address**: a fixed internal IP (DHCP reservation) **or** a DNS hostname
  (e.g. `kalshi-dash.internal`). Devices use `http://<host>:<port>`.
- Agree a **port** (e.g. `8000`, or `80` behind a reverse proxy). Allow **inbound TCP** on it to the host.
- (Optional) Put a **reverse proxy** (nginx/Caddy) in front for a clean hostname, port 80/443, and TLS.
  Not required for the no-auth internal setup, but nicer for users.

**Acceptance for this step:** from a device on the office Wi-Fi, `ping <host>` succeeds and
`http://<host>:<port>/healthz` returns `{"status":"ok"}`.

---

## 3. Server setup — runtime, env, service

### Service user + filesystem layout (Linux)
Run as a dedicated **non-root** user `kalshi-dashboard`, with clear absolute paths:
- App code: `/opt/kalshi-dashboard` (the **clean deploy repo** — NiceGUI-only, no `app.py`/Streamlit).
- Virtualenv: `/opt/kalshi-dashboard/.venv` (**Python 3.13**, matching dev).
- Env file: `/etc/kalshi-dashboard.env`, owned `root:kalshi-dashboard`, mode **640** (NOT world-readable).
- SQLite DB: `/var/lib/kalshi-dashboard/snapshots.db` on **LOCAL disk** — never NFS / a network share
  (SQLite WAL needs local fsync). Create the dir and `chown` it to the service user.

```bash
sudo useradd --system --home /opt/kalshi-dashboard --shell /usr/sbin/nologin kalshi-dashboard
sudo install -d -o kalshi-dashboard -g kalshi-dashboard /var/lib/kalshi-dashboard
```

### Runtime
- **Python 3.13**, a dedicated virtualenv: `python3.13 -m venv /opt/kalshi-dashboard/.venv`.
- `/opt/kalshi-dashboard/.venv/bin/pip install -r requirements.txt` — the **pinned** deploy
  requirements (the hosted app is NiceGUI on FastAPI via `serve.py`, the sole UI).
- Launch command: `python serve.py` (**single worker** — see §1).

### Environment variables
| Var | Value | Notes |
|---|---|---|
| `API_HOST` | `0.0.0.0` | Bind all interfaces (required for remote access) |
| `API_PORT` | e.g. `8000` | Must match the firewall/reverse-proxy port |
| `NICEGUI_STORAGE_SECRET` | a long random string | **REQUIRED for LAN exposure** — `serve.py` refuses to bind a non-loopback host without it. **Generate once and persist** (env/secret store). Signs the session cookie |
| `ALLOW_DEV_STORAGE_SECRET_ON_LAN` *(optional)* | `1` | Trusted-LAN escape hatch — start with the dev fallback secret + a warning instead of refusing. Don't use for anything left running |
| `SNAPSHOT_DB_PATH` *(optional)* | absolute path | Point at a writable, backed-up location instead of the CWD default |
| `SCAN_TOKEN` *(optional)* | a long random string | **Scan-token gate** — when set, HTTP `POST /scan` requires a matching `X-Scan-Token: <value>` header (401 otherwise). **Off by default** (today's open behaviour). Loopback dev needs nothing; on a LAN, set it so only your scheduler can trigger scans. The dashboard's own "Scan now" button runs in-process and is **unaffected** |

Generate a secret (any of): `python -c "import secrets; print(secrets.token_hex(32))"`.

> **Scan-token gate (PR 26b).** `POST /scan` is also per-process rate-limited
> (`SCAN_HTTP_MAX_PER_WINDOW`/`SCAN_HTTP_WINDOW_SECONDS`, default 10/60s → 429 when exceeded). If you set
> `SCAN_TOKEN`, the scheduled-scan caller below **must** send the `X-Scan-Token` header or it gets 401.

### Refresh rate & Kalshi API keys (no `.env` key needed)

**A Kalshi API key will NOT make the data refresh faster, so there is no key to put in the env file.**
The market-data endpoints this app uses (`/series`, `/events`, `/markets`) are **public and need no
authentication** — keys only matter for *trading*, which is out of scope. What actually bounds the refresh
loop is two things, both already tuned for the free tier:

- **Request throttle** — a process-wide limiter paces every GET at `config.MAX_RPS = 15` req/s (~75% of
  Kalshi's ~20/s Basic ceiling); `_get` backs off on any `429`. A full cross-sport scan is **many** GETs
  (≈50 at the last live measurement, and higher now that golf/soccer/MLB/NHL are registered — re-measure
  live with `GET /coverage` → `kalshi_requests`), but the throttle just makes a scan take a few **seconds**;
  it never exceeds the rate.
- **Scan cadence** — the background auto-scan runs every `config.AUTO_SCAN_DEFAULT_SECONDS` (10s) while a
  viewer is connected, and the dashboard surfaces a new snapshot within ~1s of it finishing.

To go faster you would lift the throttle (`MAX_RPS`) and/or shorten the cadence in `config.py` — but
pushing `MAX_RPS` toward/over ~20 invites sustained `429`s (the backoff absorbs them; throughput won't
improve past the ceiling). The only way to beat REST polling is a Kalshi **WebSocket** feed, which is not
implemented (and still wouldn't need a *read* key). **Run exactly one process** — the throttle is
per-process, so N workers issue `15 × N` req/s (see §1).

### Run as an auto-restart systemd service (Linux — primary)

`/etc/systemd/system/kalshi-dashboard.service` (env comes from the 640 env file; **one worker**):
```ini
[Unit]
Description=Kalshi LAN dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=kalshi-dashboard
WorkingDirectory=/opt/kalshi-dashboard
EnvironmentFile=/etc/kalshi-dashboard.env
ExecStart=/opt/kalshi-dashboard/.venv/bin/python serve.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now kalshi-dashboard`. **One process, one worker, one DB file** (§1).

### Scheduled auto-scan as a systemd timer (REQUIRED — see §4)

The `X-Scan-Token` header must be **conditional** (sent only when `SCAN_TOKEN` is set), so the timer runs
a small wrapper `/opt/kalshi-dashboard/scan.sh` (install mode **0755**), NOT an inline `curl`:
```bash
#!/usr/bin/env bash
set -euo pipefail
URL="http://127.0.0.1:${API_PORT}/scan"
if [ -n "${SCAN_TOKEN:-}" ]; then
  curl -fsS -X POST -H "X-Scan-Token: ${SCAN_TOKEN}" "$URL"
else
  curl -fsS -X POST "$URL"
fi
```
`/etc/systemd/system/kalshi-dashboard-scan.service` (oneshot; same env file → sees `API_PORT`/`SCAN_TOKEN`):
```ini
[Unit]
Description=Trigger a Kalshi dashboard scan
[Service]
Type=oneshot
EnvironmentFile=/etc/kalshi-dashboard.env
ExecStart=/opt/kalshi-dashboard/scan.sh
```
`/etc/systemd/system/kalshi-dashboard-scan.timer`:
```ini
[Unit]
Description=Periodic Kalshi dashboard scan
[Timer]
OnBootSec=2min
OnUnitActiveSec=3min
[Install]
WantedBy=timers.target
```
`sudo systemctl enable --now kalshi-dashboard-scan.timer`. (These three unit files + `scan.sh` ship in the
deploy repo's `deploy/` directory — copy them in and `systemctl daemon-reload`.)

### Windows alternative (only if the host is Windows)

Run `serve.py` under **NSSM** as a single auto-restart service (secrets in machine env vars), a **Task
Scheduler** job (every 2–5 min) for the scan, and a **Windows Firewall** private-network rule. Kill a
stale port by owning PID:
`Get-NetTCPConnection -LocalPort <port> | Select -Expand OwningProcess | Stop-Process -Id $_`.

---

## 4. Scheduled auto-scan (keeps data fresh)

Auto-scan is **REQUIRED and default-on**: the dashboard only updates when a scan runs (its own UI timer
just re-reads the store), so freshness must advance with **NO manual action**. On Linux this is the
systemd timer in §3; the mechanics below apply to any scheduler.

**`POST /scan` is NON-BLOCKING (202).** It returns immediately with
`202 {status, since, last_snapshot_id}` and runs the scan in a background thread; the cron just
fire-and-forgets. A process-local **singleflight** collapses overlapping triggers (cron + a dashboard
"Scan now") to ONE upstream fetch, and a store-backed **TTL guard** (30s) + a **scan budget** keep it
under Kalshi's rate limit. Observe progress with `GET /scan/status` (`status` ∈
`in_progress|done|skipped|error`). `?force=true` overrides the TTL/budget; `?wait=true` blocks up to
`SCAN_WAIT_TIMEOUT_SECONDS` (then still returns 202).

- **Recommended interval: every 2–5 minutes.** (Pick one comfortably longer than a real scan — measure
  with `python scripts/benchmark_scan.py`.)
- **Linux cron** (every 3 min): `*/3 * * * * curl -s -X POST http://localhost:8000/scan >/dev/null`
  (the cron doesn't wait — the 202 returns at once; the scan finishes in the background).
- **Windows Task Scheduler:** a 3-min recurring task running
  `powershell -Command "Invoke-RestMethod -Method Post http://localhost:8000/scan"`.
- **If `SCAN_TOKEN` is set** (see Environment variables), the scheduled caller MUST send the header, e.g.
  `curl -s -X POST -H "X-Scan-Token: $SCAN_TOKEN" http://localhost:8000/scan >/dev/null` (otherwise 401).
- Scan scope = **core series, all sports** (tennis + NBA + WNBA + golf + soccer + MLB + NHL). Full-scan breadth is a
  possible follow-up, not part of this deployment.

---

## 5. Acceptance test (run after hosting)

1. On the server: `curl http://127.0.0.1:<port>/healthz` → `{"status":"ok"}`, and
   `curl http://127.0.0.1:<port>/readyz` → `ready` after the first scan (`degraded` before any scan).
2. `GET http://<host>:<port>/` renders the dashboard.
3. `POST /scan` returns **202** + a `ScanStatus`; poll `GET /scan/status` until `done`; the freshness
   strip advances.
4. Open `http://<host>:<port>/` from **an office Wi-Fi device's browser** — it loads.
5. The scheduled timer fires with **no manual action** (freshness advances every few minutes);
   `sudo ss -ltnp | grep :<port>` shows exactly **one** process bound.
6. `sudo systemctl restart kalshi-dashboard` and a full **reboot**: the service comes back and the scan
   timer resumes.

---

## 6. Operations

- **Logs:** journald — `journalctl -u kalshi-dashboard` (and `-u kalshi-dashboard-scan`). Retention via
  the system's existing journald policy.
- **Restart:** the service auto-restarts (`Restart=always`) and survives a host reboot.
- **Time sync:** the host MUST run **NTP** — snapshot age, scan freshness, and stale warnings all depend
  on the clock.
- **Backup:** the SQLite DB is three files — back up `snapshots.db` + `snapshots.db-wal` +
  `snapshots.db-shm` **together** (or use `sqlite3 .backup`). 30h retention; safe to lose (it rebuilds on
  the next scan). Keep it on local disk (§3).
- **Rollback / updates:** the deploy repo is regenerated per release. Deploy into a versioned dir (e.g.
  `/opt/kalshi-dashboard/releases/<version>` with a `current` symlink); to roll back, repoint `current` to
  the previous release (reinstall deps if they changed) and `systemctl restart kalshi-dashboard`.
- **One instance / one worker only** — see §1.
- **Egress:** the host needs outbound HTTPS to `external-api.kalshi.com`.

---

## 7. Security posture

- **No authentication** by decision — anyone who can reach the host can view it. Keep it **internal
  only**; do **not** port-forward it to the public internet.
- The NiceGUI session cookie is signed with `NICEGUI_STORAGE_SECRET`; set a real one (§3). `serve.py`
  refuses a non-loopback bind without it precisely so a public dev-fallback secret never ships to a LAN.
- Only read-only public market data is exposed; no credentials or trading.
- If policy later requires a login, add it at a reverse proxy (basic-auth/SSO) — this is a new scope item.

---

## 8. Open follow-ups (not blocking)
- Optional reverse proxy + TLS + friendly hostname (the proxy MUST forward WebSocket upgrade headers —
  NiceGUI needs WebSockets). Add company auth/SSO here if policy requires it before exposure.
- Full-scan breadth for the scheduled scan (currently core series).
- Docker is a **deferred follow-up** (NOT day-one; the locked decision is systemd / NSSM). A committed
  `Dockerfile` can be added later if IT elects the container path.
- The broader UI-parity work is separate from hosting and can proceed independently.
