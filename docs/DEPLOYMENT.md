# Deployment Plan — Kalshi Opportunity Dashboard (internal office hosting)

Hand-off guide for hosting the dashboard so **any device on the office network** can open it in a
browser. Verified working over a controlled network (phone hotspot); the only remaining work is to host
it where every office device can route to it. No authentication is required (internal, read-only public
market data) per the agreed decisions below.

## Decisions (locked)

| Topic | Decision |
|---|---|
| Host environment | **IT's choice** — Linux service, Windows service, or Docker (all covered below) |
| Access control | **Open on the internal network** — no login. Data is read-only public market data |
| Data refresh | **Scheduled auto-scan** — an external scheduler calls `POST /scan` every 2–5 min |

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
- **UI:** `GET /` · **REST:** `/opportunities`, `/backlog`, `/coverage`, `/alerts`, `POST /scan` ·
  **OpenAPI:** `/docs` · **Health:** `/healthz` → `{"status":"ok"}`.
- **State:** a single SQLite file (`snapshots.db`, path = `config.SNAPSHOT_DB_PATH`) holding ranked
  opportunity snapshots. The UI reads the latest snapshot; a scan writes a new one.
- **Outbound:** the process fetches live data from `https://external-api.kalshi.com` (read-only, no auth).
- **Run EXACTLY ONE worker / one instance.** The snapshot store and the Kalshi request throttle
  (`MAX_RPS=5`) are **process-local**: multiple workers (`WEB_CONCURRENCY>1`, `uvicorn --workers N`) or
  replicas each keep their own, which both **fragments the data** (divergent snapshots) and multiplies the
  request rate past Kalshi's free-tier limit. `serve.py` warns if `WEB_CONCURRENCY>1` / `--workers` is set.

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

### Runtime
- **Python 3.13**, a dedicated virtualenv.
- `pip install -r requirements.txt` (streamlit, requests, pandas, fastapi, uvicorn, `nicegui>=3.12,<4`,
  pydantic).
- Launch command: `python serve.py` (single worker — see §1).

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

### Run as an auto-restart service — pick ONE pattern

**A) Linux + systemd** (`/etc/systemd/system/kalshi-dash.service`):
```ini
[Unit]
Description=Kalshi Opportunity Dashboard
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/kalshi-visualizer
Environment=API_HOST=0.0.0.0
Environment=API_PORT=8000
Environment=NICEGUI_STORAGE_SECRET=__SET_ME__
ExecStart=/opt/kalshi-visualizer/.venv/bin/python serve.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now kalshi-dash`

**B) Windows service via NSSM:**
- Install the app + venv, set the three env vars (machine-level or in NSSM).
- `nssm install KalshiDash "C:\path\.venv\Scripts\python.exe" "C:\path\serve.py"`
- Set AppDirectory to the repo, `Start=auto`, recovery = restart on failure.

**C) Docker** (sample `Dockerfile` — to be added in a follow-up; reference only):
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV API_HOST=0.0.0.0 API_PORT=8000
EXPOSE 8000
CMD ["python", "serve.py"]
```
Run with `-e NICEGUI_STORAGE_SECRET=...`, a persistent volume for `snapshots.db`, and
`--restart unless-stopped`. **One container only** (single worker — see §1).

---

## 4. Scheduled auto-scan (keeps data fresh)

The dashboard only updates when a scan runs; the UI's own timer just re-reads the store. So schedule an
external call to `POST /scan`.

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
- Scan scope = **core series, all sports** (tennis + NBA + WNBA + golf + soccer). Full-scan breadth is a
  possible follow-up, not part of this deployment.

---

## 5. Acceptance test (run after hosting)

1. `GET http://<host>:<port>/healthz` → `{"status":"ok"}`.
2. `GET http://<host>:<port>/` renders the dashboard.
3. `POST /scan` returns coverage (scanned/failed counts); the freshness strip updates.
4. Open `http://<host>:<port>/` from **an office Wi-Fi device's browser** — it loads.
5. Confirm the scheduled scan is firing (freshness timestamp advances every few minutes).

---

## 6. Operations

- **Logs:** capture stdout/stderr (systemd journal / NSSM logs / `docker logs`).
- **Restart:** the service auto-restarts; manual restart after a code update.
- **Persistence:** `snapshots.db` (30h retention). Put it on durable storage if history matters; safe to
  delete (it rebuilds on the next scan).
- **Updates:** `git pull` → `pip install -r requirements.txt` → restart the service. (Module changes are
  cached by uvicorn — a full restart is required, not just a browser refresh.)
- **One instance / one worker only** — see §1.
- **Egress:** ensure the host can reach `external-api.kalshi.com` (HTTPS out).

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
- Optional reverse proxy + TLS + friendly hostname.
- Full-scan breadth for the scheduled scan (currently core series).
- A committed `Dockerfile` if IT chooses the container path.
- The broader UI-parity work (Phase E PRs 19–26) is separate from hosting and can proceed independently.
