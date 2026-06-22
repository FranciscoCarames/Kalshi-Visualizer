---
paths:
  - "serve.py"
  - "api.py"
  - "scan_manager.py"
  - "scan_scheduler.py"
  - "presence.py"
  - "ratelimit.py"
---

# Serve / hosting / scan ops — do not regress

**LAN hosting:** `serve.py` serves the API + dashboard on one app (default loopback `127.0.0.1:8000`);
`API_HOST`/`API_PORT`/`SNAPSHOT_DB_PATH` are env-overridable. A non-loopback bind **requires**
`NICEGUI_STORAGE_SECRET` (`serve.bind_safety` fail-hard, no auth — escape
`ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`) and warns on `WEB_CONCURRENCY>1` (store + throttle are
process-local). `POST /scan` is **non-blocking** (202) behind a process-local `scan_manager.ScanManager`
singleflight (shared with `webui.run_scan_now` → one upstream fetch); `?wait`/`?force` modify it,
`GET /scan/status` polls; the dashboard "Scan now" is **non-force**. Full runbook + deploy artifact
(`scripts/build_deploy_repo.py`, `deploy/`): `docs/DEPLOYMENT.md`.

**Auto-refresh:** the dashboard reads the persisted snapshot store; a process-local `scan_scheduler`
runs background scans on a timer (on by default — `config.AUTO_SCAN_DEFAULT_ENABLED`, every
`AUTO_SCAN_DEFAULT_SECONDS`), and the browser re-reads the latest snapshot on a `ui.timer`.

**Per-user auth (in scope, owner-requested 2026-06):** app-level login over the read-only surface, gated
behind `AUTH_ENABLED`; see `docs/AUTH.md` (`auth_store.py`/`auth.py`/`manage_users.py`). It must NOT
alter engine logic.

**The running server caches imported modules.** After editing a module while `serve.py` runs, **fully
stop and restart** (there is no auto-reload); for a phantom `ImportError` clear bytecode too:
`rm -rf __pycache__ tests/__pycache__`.
