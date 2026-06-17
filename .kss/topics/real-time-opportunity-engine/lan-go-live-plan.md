# [SHIPPED 2026-06-05] NiceGUI LAN Go-Live — implemented as PRs #79–#84 (merged) + docs #85.
# Source plan below (was ~/.claude/plans/zippy-toasting-walrus.md). S1 /readyz, S2 SNAPSHOT_DB_PATH,
# S3 non-force scan, S4 DEPLOYMENT.md, S5 UX, D build_deploy_repo+deploy/. origin/main 2198ea9.

# Plan - NiceGUI LAN Go-Live (re-grounded against origin/main #78)

Status: planning only (not approved). Scope: host `python serve.py` (FastAPI engine + NiceGUI UI) on the
company LAN for every internal user. NiceGUI-only - Streamlit `app.py` is NOT deployed. Go-live is
gross-only; trustworthy-signal hardening is a separate follow-on (section 8). No global disclaimer
banner (removed per owner): trader-facing caveats are carried by the existing per-row "Caveat" column and
the "Review signal" section, and acceptance (section 6) requires those to be visible and understandable.

## 0. Baseline (verify FIRST, do not assume)

- The Internship working tree is on `main` at `2853040` (#78), matching `origin/main`.
- The implementation worktree `C:\Users\Batata\Desktop\kalshi-impl` is on `feat/p30-known-limits-docs`
  at `88c75e3` (one behind #78) - do NOT use it as the base unless it is first updated/recreated from
  `origin/main`.
- Confirm before acting: `git rev-parse origin/main` (expect `2853040`, #78), `git worktree list`,
  `git status`.
- Branch all source-repo work off a freshly-fetched `origin/main`; one PR per change; owner merges.

## 1. Already shipped on origin/main (do NOT rebuild - verify only)

- **Shared scan manager** `scan_manager.py`: one entry point for `POST /scan` AND the UI "Scan now"
  (`webui.engine.run_scan_now`); guards = singleflight + budget cooldown + TTL (all force-overridable).
- **Scan-token gate** (#73): `require_scan_token` on `POST /scan` (header `X-Scan-Token`, env `SCAN_TOKEN`,
  401 on mismatch, OFF when unset). `POST /scan` returns 202 `ScanStatus`; `GET /scan/status` exists.
- **Bind safety** (#19a, `serve.py::bind_safety`): storage-secret fail-hard on a non-loopback bind
  without a real `NICEGUI_STORAGE_SECRET` (escape `ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`) + a best-effort
  multi-worker warning. NOTE: it does NOT check snapshot-store or Kalshi reachability - that readiness
  belongs to the new `/readyz` work (S1). Env-driven bind `API_HOST`/`API_PORT`.
- **`/healthz`**, **`/metrics`**, `/opportunities`, `/backlog`, `/coverage`, `/alerts`.
- **NiceGUI parity** (Phase E): filters/controls, export, detail panels, diagnostics, browser smoke tests.
- **Risk-budget candidates + near-miss books + "Review signal"** speculative surfaces (#29), already built
  and caveated (this was the old deferred "Upside candidates").

Verify-only (open a PR only if a real gap is found):
- SQLite WAL + `busy_timeout` in `store.py::_connect`.
- Leg/URL alignment in `scanner._to_unified_consistency`.
- The NiceGUI auto-refresh timer (`ui.timer(config.UI_REFRESH_SECONDS, refresh)`) reads the stored
  snapshot by default, so users see updated data WITHOUT clicking anything (confirm it polls the store,
  not a fetch).

## 2. Remaining source-repo PRs (the actual go-live gap)

### PR S1 - `/readyz` endpoint (NEW - confirmed absent; only `/healthz` exists at `api.py:209`)
Liveness (`/healthz`) is not readiness. This PR also owns the store/Kalshi readiness signal that
`bind_safety` does NOT provide. Contract:
- 200 `{"status":"ready"}` - DB writable AND a snapshot exists AND not stale.
- 200 `{"status":"degraded","reason":...}` - DB writable but no snapshot yet OR stale OR last scan
  errored (UI still serves; data caveated - stale = degraded-with-warning, never a blank "ready").
- 503 `{"status":"not_ready","reason":...}` - DB not writable or scan-manager unavailable.
- Body: latest snapshot age, last scan status/error (this reflects Kalshi reachability indirectly),
  `scan_manager.manager.status()` state. Does NOT claim scheduler health (no heartbeat), and does NOT
  make a live Kalshi call per request (no upstream load from a health probe).
- HARD RULE: the writability probe must be migration-free - do NOT call `store.latest()` or
  `store._connect()` if those trigger `_migrate()`; use `os.access` on the DB file + parent dir, or a
  dedicated read-only `PRAGMA quick_check`. Never schema work, never a migrating write.
- Tests: empty DB, writable DB + fresh snapshot, locked DB, stale snapshot, last-scan-error, in-progress.

### PR S2 - `SNAPSHOT_DB_PATH` env override (NEW - still hardcoded `= "snapshots.db"` at `config.py:121`)
Read the env var end-to-end. Put the parent-dir check in `serve.py` STARTUP (fail there with a clear
error if missing) - NOT at `config.py` import, so importing `config` in tests/tools never fails. Absolute
paths allowed. Tests: default, env-override, missing-parent-dir (fails at startup, not import).

### PR S3 - UI "Scan now" force policy (small, owner-gated)
Today the button calls `run_scan_now(..., force=True)` (`webui/engine.py:193`), intentionally overriding
the TTL + budget cooldown (the singleflight still collapses concurrent clicks). For shared LAN use this
lets any viewer force repeated fresh scans. Recommended v1: default "Scan now" = NON-force (flows through
the existing ScanManager cooldown/TTL); keep `force=true` only via the token-gated HTTP endpoint
(admin = `SCAN_TOKEN` holder). In-progress UX: if a scan is running, show "scan in progress" (read
ScanManager state), not "done" with empty counts. Tests: a non-forced UI trigger + a concurrent HTTP
trigger yield ONE upstream fetch; a click within cooldown does not refetch.

### PR S4 - `docs/DEPLOYMENT.md` accuracy (source repo)
Correct the shipped deployment doc to match reality: `POST /scan` is 202 + poll `/scan/status` (not the
old coverage payload); remove Docker as a day-one option (decision: NO day-one Docker - systemd/NSSM
only); remove Streamlit dependency wording; egress host `external-api.kalshi.com`; one process / one
worker / one DB file; "internal only, do not expose publicly."

### PR S5 - NiceGUI UX defaults & accessibility (go-live polish)
- Blocked section hidden by default: keep the toggle, default it OFF so the main screen opens cleaner for
  traders.
- Selected-row highlight: when a user selects an opportunity / participant / contract, the selected item
  stays visibly highlighted (persistent selection style, not a momentary hover).
- Clearer selection copy: small inline hints/labels so users understand how to filter/select a
  participant or contract without reading docs.
- Resolution-criteria toggle: a toggle in the detail panel to show the contract's resolution
  criteria/rules (`rules_primary`) - supports trust and is useful for go-live.
- Basic accessibility pass (not a redesign): visible keyboard focus, non-color-only status labels (pair
  color with text/icon), readable contrast, sensible table column labels + tooltips.
- Dark mode toggle: include ONLY if NiceGUI supports it with low risk; otherwise defer to follow-on.

## 3. Deployment-repo Tasks (clean repo)

### Task D1 - Allowlist manifest (DERIVED from the import graph, not hand-curated)
The sync script walks imports from `serve.py` and copies ONLY local first-party `.py` modules; stdlib /
third-party packages are never copied (they are declared in the deploy requirements/lockfile). The
hand-list is a sanity cross-check only - a hand-maintained allowlist silently drops transitive deps
(e.g. `api.py` imports `fetch.py`). The Task D5 import smoke is the hard guard.
Cross-check set: `serve.py`, `api.py`, `scan_manager.py`, `ratelimit.py`, `presence.py`, `config.py`,
`data.py`, `fetch.py`, `consistency.py`, `dutchbook.py`, `synthetic_bundle.py`, `sports.py`,
`glossary.py`, `filters.py`, `viz.py`, `scanner.py`, `store.py`, `lifecycle.py`, `kalshi_client.py`, all
`webui/*.py`; plus a `.gitignore`, a minimal `AGENTS.md`, `.env.example` (or an env-var table in the
README), a tiny deploy `README.md` (install / env / run / health only), the GENERATED pinned deploy
requirements (see D2), and a `deploy/` directory shipping the ops templates:
`kalshi-dashboard.service`, `kalshi-dashboard-scan.service`, `kalshi-dashboard-scan.timer`, and
`scan.sh` (the conditional-header wrapper from §5).
EXCLUDE everything else: `app.py` + Streamlit; `tests/`, `requirements-dev.txt`; ALL of `docs/`; `.kss`,
`.claude`, `tmp_kalshi_docs`; `snapshots.db`/`-wal`/`-shm`; `__pycache__`; `.env`; logs; exports. No
shipped file may import `app.py`, `streamlit`, or `tests/test_app.py`; clean-repo docs must not call the
project "a Streamlit app."

### Task D2 - Sync script + pinned deploy requirements
`scripts/build_deploy_repo.py` (source repo) does the import-graph-derived allowlist copy from a tagged
commit and emits the release artifact. It GENERATES a pinned, Streamlit-free deploy requirements file -
NOTE there is no `constraints.txt` on `origin/main` today, so the script must CREATE the lockfile, not
copy one. Single method (chosen): **`pip-compile`** (pip-tools) from a deploy-specific `requirements.in`
(the runtime deps, no `streamlit`/dev-only) producing a fully pinned, hash-locked `requirements.txt`.
Re-runnable; the deploy repo is regenerated, never hand-edited.

### Task D3 - "No local state committed" check
Sync script + README assert the built repo contains no `snapshots.db`/`-wal`/`-shm`, `__pycache__`,
`.env`, logs, or exports.

### Task D4 - IT access
IT may lack GitHub access to the private source repo: provide a read-only deploy key OR a release-zip.

### Task D5 - Clean-repo smoke (define ready semantics first)
Fresh clone -> `pip install -r requirements.txt` -> import-graph smoke
`python -c "import serve, api, webui.dashboard"` (catches a missing module before boot - the hard guard
for D1) -> `python serve.py` -> `/healthz`=200. `/readyz`: with no snapshot expect `degraded` (not
`ready`), then trigger one scan and expect `ready`. No pytest in the clean repo; this boot smoke is its
only gate.

## 4. Optional source-repo doc cleanup (NOT on the go-live critical path)

Stale planning material on `origin/main` (`docs/historical/*`, `docs/audit/*`,
`docs/PROJECT_BRIEF_whats_next.md`, old roadmaps) is NOT required for LAN go-live, because the clean
deploy repo (Task D1) already excludes all of `docs/`. Prune it later in a SEPARATE, non-blocking
cleanup PR with owner approval (never delete unilaterally). Not a go/no-go item.

## 5. IT / Ops deployment runbook (LINUX-FIRST)

Assumes a **Linux host** (confirm with IT). A Windows host via NSSM is the only alternative and is kept
as a one-line note at the end. The deploy repo README stays minimal (install / env / run / health); this
full runbook lives in `docs/DEPLOYMENT.md` (PR S4).

**Service user + filesystem layout (absolute paths):**
- Run as a dedicated NON-root user `kalshi-dashboard`.
- App code: `/opt/kalshi-dashboard` (optionally `/opt/kalshi-dashboard/releases/<version>` with a
  `/opt/kalshi-dashboard/current` symlink for clean rollbacks).
- Virtualenv: `/opt/kalshi-dashboard/.venv` (Python **3.13**, matching dev).
- Env file: `/etc/kalshi-dashboard.env`, owned `root:kalshi-dashboard`, mode `640` (NOT world-readable).
- SQLite DB: `/var/lib/kalshi-dashboard/snapshots.db` on **LOCAL disk** (never NFS / a network share -
  SQLite WAL needs local fsync). Create the dir and `chown` it to the service user, writable by it.
- Logs: **journald** (`journalctl -u kalshi-dashboard`); retention via existing system/IT policy.

**Install:** create the user + dirs; `python3.13 -m venv /opt/kalshi-dashboard/.venv`;
`/opt/kalshi-dashboard/.venv/bin/pip install -r requirements.txt` (the pinned, Streamlit-free deploy
requirements from Task D2).

**Env file `/etc/kalshi-dashboard.env`** (secrets live ONLY here, never in the repo):
`API_HOST=0.0.0.0`, `API_PORT=<port>`, `NICEGUI_STORAGE_SECRET=<long random>` (bind refuses without it),
`SNAPSHOT_DB_PATH=/var/lib/kalshi-dashboard/snapshots.db`, `SCAN_TOKEN=<token>` (per S3/owner).

**systemd service** `/etc/systemd/system/kalshi-dashboard.service` (sample - one process, never workers):
```
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
`systemctl enable --now kalshi-dashboard`. **Forbidden:** `uvicorn --workers`, gunicorn worker pools,
multiple systemd instances, or multiple containers against the SAME SQLite DB (store + throttle are
process-local; multiple processes fragment them).

**Auto-scan as a systemd timer (REQUIRED, default-on - the scheduler is a deployment deliverable):**
`kalshi-dashboard-scan.timer` (`OnUnitActiveSec=3min`, `OnBootSec=2min`) + a oneshot
`kalshi-dashboard-scan.service`. The header must be CONDITIONAL (sent only when `SCAN_TOKEN` is set), so
the unit's `ExecStart` is a tiny wrapper script `/opt/kalshi-dashboard/scan.sh` - NOT an inline `curl`
(an inline command cannot conditionally add a header, which is why the earlier sample disagreed with the
"omit when unset" text):
```
#!/usr/bin/env bash
set -euo pipefail
URL="http://127.0.0.1:${API_PORT}/scan"
if [ -n "${SCAN_TOKEN:-}" ]; then
  curl -fsS -X POST -H "X-Scan-Token: ${SCAN_TOKEN}" "$URL"
else
  curl -fsS -X POST "$URL"
fi
```
The scan service sets `EnvironmentFile=/etc/kalshi-dashboard.env` so the wrapper sees `API_PORT` +
`SCAN_TOKEN`. Install `scan.sh` at `/opt/kalshi-dashboard/scan.sh`, owned `root:kalshi-dashboard`, mode
`0755` (executable + readable by the service user; it reads the token from the env, never as an arg).
NON-force; 202 is fire-and-forget; freshness must advance with NO manual action.

**Network:**
- `API_HOST=0.0.0.0` binds all interfaces; the **firewall (and optional proxy) controls who can reach
  it.** Open ONLY the app port to the private/company network (e.g. `ufw allow from <lan-cidr> to any
  port <port> proto tcp`, or firewalld). **No public exposure** - no public security-group rule, router
  port-forward, or public reverse proxy unless authentication is added.
- Egress: allow outbound HTTPS to `external-api.kalshi.com` (NOT `api.kalshi.com`).
- Reverse proxy (OPTIONAL, only if auth / TLS / hostname / SSO is required): Nginx or Caddy in front; it
  MUST forward WebSocket upgrade headers (NiceGUI needs WebSockets). A sample config is provided once the
  proxy decision is made (Open decision 4) - not embedded here to avoid premature commitment.

**Host requirements:** working **NTP/time sync** (snapshot age, scan freshness, and stale warnings all
depend on the clock); adequate **disk space** + a writable data dir for the SQLite DB and WAL growth.

**Backup / rollback / monitoring:**
- Back up `snapshots.db` + `snapshots.db-wal` + `snapshots.db-shm` together, or use `sqlite3 .backup`
  (30h retention; safe to lose - it rebuilds on the next scan).
- Rollback: point `current` at the previous release dir (or redeploy the previous tag/zip), reinstall
  deps if they changed, `systemctl restart kalshi-dashboard`.
- Optional monitoring: alert on `/readyz != ready`, stale snapshot age, or repeated scan failures.
- Document the final LAN URL in the README (`http://<server-ip>:<port>/` or
  `http://kalshi-dashboard.local:<port>/`). Browser: any modern browser (NiceGUI uses WebSockets).

**Ownership (confirm):** IT owns firewall, DNS/hostname, optional reverse proxy, backups, and service
restarts; Claude provides the code, the systemd unit/timer, and the `build_deploy_repo.py` script; the
owner/IT hold the secrets.

**Windows alternative (only if the host is Windows):** run `serve.py` under NSSM as a single auto-restart
service, secrets in machine env vars, a Task Scheduler job for the scan, and a Windows Firewall
private-network rule; kill a stale port by OWNING PID
(`Get-NetTCPConnection -LocalPort <port> | Select -Expand OwningProcess | Stop-Process -Id $_`).

## 6. Day-one acceptance + go/no-go

Acceptance (from a second office device): `/healthz`=200; `/readyz`=ready after a scan; `GET /` renders;
the scheduled `POST /scan` advances freshness with NO manual action (auto-scan on by default) and the UI
auto-refreshes the stored snapshot without the user clicking anything; manual "Scan now" works and shows
"in progress" when one is running; opening the page from multiple devices adds ZERO UPSTREAM Kalshi
fetch/scan requests (viewers read the stored snapshot only - measure the Kalshi request counter before
vs after the page loads; the local HTTP hits to our own server don't count); a scan failure leaves the
prior stale snapshot displayed WITH a warning, never blank "ready".

Go/no-go (all must pass):
- [ ] clean clone installs and boots; import-graph smoke passes
- [ ] no shipped doc references a missing script
- [ ] `NICEGUI_STORAGE_SECRET` enforced (non-loopback bind without it refuses to start)
- [ ] scan-token behaves per the owner decision; `force` not open on LAN without a token
- [ ] `/healthz` + `/readyz` correct (degraded/not_ready semantics)
- [ ] scheduled + manual scan go through scan_manager; one fetch under concurrent triggers
- [ ] auto-scan runs by default; freshness advances with NO manual action; UI auto-refreshes the store
- [ ] multi-viewer adds no upstream Kalshi requests (viewers read the store; measured via the Kalshi
      request counter, not local server hits)
- [ ] stale/failed scan shows a warning, not blank
- [ ] Blocked section hidden by default; its toggle shows/hides it
- [ ] a selected opportunity/participant/contract stays visibly highlighted
- [ ] resolution criteria can be shown in the detail panel
- [ ] no color-only meaning (status carries text/icon); keyboard focus visible
- [ ] participant/contract selection is understandable without docs
- [ ] per-row "Caveat" column + "Review signal" section are visible and understandable to a trader
      (they replace the removed global banner)

Linux host checks (go/no-go):
- [ ] runs as the non-root `kalshi-dashboard` user; `/etc/kalshi-dashboard.env` is mode 640 (not
      world-readable); no secrets in the repo
- [ ] on the server: `curl http://127.0.0.1:<port>/healthz` and `/readyz` return expected; a LAN device
      opens `http://<server-ip>:<port>/`
- [ ] `sudo ss -ltnp | grep :<port>` shows exactly ONE process bound; no `--workers`/extra instances
- [ ] DB is on local disk (not NFS) in a writable data dir; adequate free disk; NTP/time sync working
- [ ] `systemctl status kalshi-dashboard` active; survives `systemctl restart` AND a full reboot (app
      returns and the scan timer resumes)
- [ ] firewall opens the port to the LAN only; no public exposure; rollback (previous release) tested
- [ ] company auth/SSO/TLS policy CONFIRMED before exposure (if required, the WS-aware proxy with auth is
      in place first)
- [ ] `deploy/` ships `scan.sh` (mode 0755) + the 3 systemd templates; `scan.sh` sends the token only
      when set
- [ ] "internal only - do not expose publicly" acknowledged

NiceGUI v1 limitations: list only GENUINE remaining gaps vs `app.py` (Phase E shipped filters/export/
detail/diagnostics); build any must-have before handoff or disclose it.

## 7. Open decisions for the owner

1. UI "Scan now" force: default NON-force (recommended) vs keep force=True (S3).
2. `SCAN_TOKEN` required on non-loopback vs accepted-open (gate already exists, off by default).
3. Docker day-one: default NO (systemd/NSSM); flip only to ship a real `Dockerfile`.
4. Auth/SSO/TLS - CONFIRM BEFORE EXPOSURE (blocking gate): does company policy require authentication,
   SSO, or TLS before putting this on the LAN? If yes, a WebSocket-aware reverse proxy (Nginx/Caddy) with
   auth is a PREREQUISITE, not optional - do not expose until it's in place.
5. Which stale `docs/` to prune (section 4, optional, off critical path) - owner approves.
6. Dark mode: ship at go-live only if trivial/low-risk in NiceGUI; otherwise defer to follow-on (S5).
7. Host OS: the runbook assumes a Linux host with systemd (§5). Confirm with IT; if Windows, use the
   NSSM alternative. Confirm the chosen app port and whether a reverse proxy (auth/TLS) is needed.

## 8. Follow-on (SEPARATE plan - not go-live)

Trustworthy-signal foundation (progressive, after go-live): versioned opportunity schema contract
(`tradability_state`; `fee_source` incl. `unknown`; `fee_confidence` {verified, estimated, unknown};
`capacity_source`; `staleness_state`, `scan_completeness`, `rule_review_state`, provenance);
reliability/relabel; fee & size fields (verify the current Kalshi fee formula against official sources
first; net-ranking needs blocking owner sign-off; introducing `fee_confidence` must NOT mass-demote old
snapshots - the gate applies forward; partial scan demotes only rows with missing coverage;
`scope_incomplete` computed over stored opportunities' legs; top-of-book stays actionable but labeled
visible-size-only); coverage audit; factual trust chips; structured logging; invariant + ID tests;
lifecycle event log; "why not actionable" + provenance panel; trust-first default filters; unified
blotter; lifecycle-driven change highlighting (no color-only, ages out); reject-reason analytics; manual
review annotations; backfill fixture tool. Note: the speculative "risk-budget candidates / near-miss /
review-signal" surface is ALREADY shipped (#29). Hard out-of-scope: WS/depth ingestion, real-time
strategy adjustment, external probability modeling, order execution.
