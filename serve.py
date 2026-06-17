"""Entrypoint: the FastAPI engine API + the React SPA + the NiceGUI dashboard, served by uvicorn (Stage 5).

The REST API (`api.app`), the React "Kalshi Structured Scanner" SPA, and the legacy NiceGUI dashboard run
on ONE app. The SPA (built `frontend/dist`) is the DEFAULT UI at ``/``; the NiceGUI dashboard is RETAINED
(not deleted) under ``/dashboard`` — importing `webui.dashboard` registers its `@ui.page('/')` and
`ui.run_with(mount_path="/dashboard")` relocates the whole NiceGUI app under that prefix. (The legacy
Streamlit app was retired.)
Run: ``python serve.py``  (SPA at ``/``, dashboard at ``/dashboard``, REST at ``/opportunities`` etc.,
OpenAPI at ``/docs``).

**Bind / LAN safety (PR 19a).** The bind address/port are env-overridable (``API_HOST``/``API_PORT``) so
the same code serves loopback-only (the safe default, ``127.0.0.1``) or the whole LAN
(``API_HOST=0.0.0.0`` — see ``docs/DEPLOYMENT.md``). Before binding, ``bind_safety`` enforces two rules:
the dashboard has **no auth** and NiceGUI signs its session cookie with the storage secret, so exposing it
on a non-loopback host with only the dev-fallback secret is refused (set ``NICEGUI_STORAGE_SECRET``, or
``ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`` to override on a trusted LAN); and the snapshot store + Kalshi
throttle are **process-local**, so ``WEB_CONCURRENCY>1`` / ``--workers`` is warned against (it would
fragment them). The guard protects ``python serve.py``; a process manager running ``uvicorn api:app
--host 0.0.0.0 --workers N`` bypasses it — see ``docs/DEPLOYMENT.md``.
"""
from __future__ import annotations

import os
import pathlib
import sys

import uvicorn
from fastapi.staticfiles import StaticFiles
from nicegui import ui

import api
import config
import presence
import scan_scheduler
import webui.dashboard  # noqa: F401  — importing registers the @ui.page('/') dashboard
from webui import engine

# Real storage secret comes from the env; the config value is only a clearly-labeled dev fallback.
_storage_secret = os.getenv("NICEGUI_STORAGE_SECRET") or config.NICEGUI_STORAGE_SECRET_FALLBACK

def mount_spa(fastapi_app, dist_dir: pathlib.Path, mount_path: str = "/terminal") -> bool:
    """Mount the built Kalshi Structured Scanner SPA at ``mount_path`` when its dist exists, returning
    whether it mounted.

    The dist is a build artifact (gitignored) — ``cd frontend && npm run build`` — so this is CONDITIONAL:
    a CI run or fresh clone that hasn't built the UI simply leaves the SPA unmounted and never breaks boot.
    `html=True` serves index.html for the directory (the SPA has no client-side routing). The SPA reads the
    engine only through the read-only GET /api/terminal/feed. A mount at ``"/"`` is a catch-all, so it MUST
    be registered AFTER the API routes and the relocated NiceGUI mount (see below) — Starlette resolves
    routes in registration order, so the catch-all wins only for paths nothing more specific claimed."""
    if not dist_dir.is_dir():
        return False
    name = "spa" + (mount_path.rstrip("/").replace("/", "_") or "_root")
    fastapi_app.mount(mount_path, StaticFiles(directory=str(dist_dir), html=True), name=name)
    return True


# UI mounting. When the SPA is built it is the DEFAULT UI at "/" and the legacy NiceGUI dashboard is
# RETAINED (not deleted) under "/dashboard"; when it ISN'T built (fresh clone / CI before `npm run build`)
# NiceGUI stays at "/" so the root UI still works and boot never breaks. `ui.run_with(mount_path=...)`
# relocates the whole NiceGUI app (its `@ui.page('/')` becomes "<prefix>/", assets/websocket under the same
# prefix). Registration order is load-bearing — Starlette resolves in order, so the "/" catch-all must be
# LAST: API routes (from `import api`) → NiceGUI → SPA at "/terminal" (back-compat / favicon) → SPA at "/".
_SPA_DIST = pathlib.Path(__file__).resolve().parent / "frontend" / "dist"
_spa_built = _SPA_DIST.is_dir()
ui.run_with(api.app, mount_path="/dashboard" if _spa_built else "/", storage_secret=_storage_secret)
if _spa_built:
    mount_spa(api.app, _SPA_DIST, "/terminal")
    mount_spa(api.app, _SPA_DIST, "/")

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def bind_safety(host: str, *, storage_secret_set: bool, allow_dev_on_lan: bool,
                web_concurrency: int = 0, has_workers_arg: bool = False,
                auth_enabled: bool = False, session_secret_real: bool = False,
                has_users: bool = False, tls_or_proxy: bool = False,
                host_allowlist_set: bool = False,
                allow_any_host: bool = False) -> list[tuple[str, str]]:
    """Pure, no-IO safety check for a chosen bind configuration. Returns ``(level, message)`` pairs where
    ``level`` is ``"fatal"`` (startup MUST abort) or ``"warn"`` (print and continue).

    - **Storage-secret fail-hard (security):** exposing a non-loopback host without a real
      ``NICEGUI_STORAGE_SECRET`` is ``fatal`` — the NiceGUI dashboard signs its cookie with it and the
      dev-fallback secret is public. ``allow_dev_on_lan`` (``ALLOW_DEV_STORAGE_SECRET_ON_LAN=1``) downgrades
      it to a loud ``warn``.
    - **Auth-mode fail-closed (security):** when ``AUTH_ENABLED`` and the bind is non-loopback, it is
      ``fatal`` to start without (a) a real ``APP_SESSION_SECRET``/``NICEGUI_STORAGE_SECRET``, (b) at least
      one user account, (c) TLS (``APP_TLS=1``) or a declared HTTPS-terminating reverse proxy
      (``TRUST_PROXY=1``), and (d) an ``APP_ALLOWED_HOSTS`` allowlist (the default ``*`` leaves the Host
      header unvalidated, which the Origin/CSRF check derives from) — otherwise the session cookie travels
      in cleartext, the gate has no one to let in, or the Host is unvalidated. ``ALLOW_ANY_HOST_ON_LAN=1``
      overrides (d) on a trusted LAN.
    - **Multi-worker guard:** ``web_concurrency > 1`` / ``--workers`` is ``warn`` normally but ``fatal`` in
      auth mode — the snapshot store, Kalshi throttle, login rate-limiter, and session state are all
      PROCESS-LOCAL, so multiple workers fragment them (and split the auth limiter → weaker brute-force
      defense).
    """
    issues: list[tuple[str, str]] = []
    exposed = host not in _LOOPBACK_HOSTS
    if exposed and not storage_secret_set:
        if allow_dev_on_lan:
            issues.append(("warn",
                           f"Binding {host} with the DEV-FALLBACK storage secret "
                           "(ALLOW_DEV_STORAGE_SECRET_ON_LAN=1). Anyone on the network could forge a "
                           "session cookie — only acceptable on a trusted LAN for a quick test. Set "
                           "NICEGUI_STORAGE_SECRET for anything you leave running."))
        else:
            issues.append(("fatal",
                           f"Refusing to bind {host}: no NICEGUI_STORAGE_SECRET set and the dashboard has "
                           "no auth. Set NICEGUI_STORAGE_SECRET to a long random string (the cookie is "
                           "signed with it), or set ALLOW_DEV_STORAGE_SECRET_ON_LAN=1 to override on a "
                           "trusted LAN. (Loopback 127.0.0.1 needs neither.)"))
    if exposed and auth_enabled:
        if not session_secret_real:
            issues.append(("fatal",
                           f"Refusing to bind {host} with AUTH_ENABLED but no real APP_SESSION_SECRET "
                           "(the dev-fallback is public — sessions could be forged). Set APP_SESSION_SECRET "
                           "(or NICEGUI_STORAGE_SECRET) to a long random string."))
        if not has_users:
            issues.append(("fatal",
                           f"Refusing to bind {host} with AUTH_ENABLED but zero user accounts exist. Seed "
                           "one first: `python -m manage_users add <name>` (or APP_ADMIN_USER/"
                           "APP_ADMIN_PASSWORD)."))
        if not tls_or_proxy:
            issues.append(("fatal",
                           f"Refusing to bind {host} with AUTH_ENABLED but no TLS: the session cookie would "
                           "travel in cleartext on the LAN. Enable TLS (APP_TLS=1 with uvicorn "
                           "--ssl-keyfile/--ssl-certfile) or declare an HTTPS-terminating reverse proxy "
                           "(TRUST_PROXY=1). See docs/AUTH.md."))
        if not host_allowlist_set and not allow_any_host:
            issues.append(("fatal",
                           f"Refusing to bind {host} with AUTH_ENABLED but no APP_ALLOWED_HOSTS: with the "
                           "default '*' the Host header is unvalidated (DNS-rebinding surface, and the "
                           "Origin/CSRF check derives from it). Set APP_ALLOWED_HOSTS to a comma-separated "
                           "host list, or ALLOW_ANY_HOST_ON_LAN=1 to override on a trusted LAN. "
                           "(Loopback needs neither.)"))
    if web_concurrency > 1 or has_workers_arg:
        level = "fatal" if auth_enabled else "warn"
        issues.append((level,
                       "Multiple workers requested (WEB_CONCURRENCY>1 / --workers): the snapshot store, the "
                       "Kalshi request throttle, and the auth login rate-limiter are PROCESS-LOCAL, so each "
                       "worker keeps its own and they fragment (duplicate scans, divergent data, weaker "
                       "brute-force defense). Run a single worker."))
    return issues


def _enforce_bind_safety(host: str) -> None:
    """Apply ``bind_safety`` for the live environment: print warnings, abort on any fatal (before bind)."""
    try:
        web_concurrency = int(os.getenv("WEB_CONCURRENCY", "0") or "0")
    except ValueError:
        web_concurrency = 0
    auth_enabled = os.getenv("AUTH_ENABLED") == "1"
    has_users = False
    if auth_enabled:
        import auth_store
        try:
            has_users = auth_store.user_count(db_path=os.getenv("AUTH_DB_PATH", config.AUTH_DB_PATH)) > 0
        except Exception as exc:  # noqa: BLE001 — a broken auth.db must not crash the guard before its message
            print(f"WARNING: could not read the auth store for the bind guard ({exc}); treating as no users.")
    issues = bind_safety(
        host,
        storage_secret_set=bool(os.getenv("NICEGUI_STORAGE_SECRET")),
        allow_dev_on_lan=os.getenv("ALLOW_DEV_STORAGE_SECRET_ON_LAN") == "1",
        web_concurrency=web_concurrency,
        has_workers_arg=any(a == "--workers" or a.startswith("--workers=") for a in sys.argv[1:]),
        auth_enabled=auth_enabled,
        session_secret_real=bool(os.getenv("APP_SESSION_SECRET") or os.getenv("NICEGUI_STORAGE_SECRET")),
        has_users=has_users,
        tls_or_proxy=os.getenv("APP_TLS") == "1" or os.getenv("TRUST_PROXY") == "1",
        host_allowlist_set=bool(os.getenv("APP_ALLOWED_HOSTS", "").strip()),
        allow_any_host=os.getenv("ALLOW_ANY_HOST_ON_LAN") == "1",
    )
    # ASCII-only prefixes: Windows consoles default to cp1252, which can't encode ⚠/✖ and would crash
    # the print (UnicodeEncodeError) before the refusal is shown.
    for level, msg in issues:
        print(f"{'ERROR (refused):' if level == 'fatal' else 'WARNING:'} {msg}")
    if any(level == "fatal" for level, _ in issues):
        raise SystemExit(2)


def live_feed_safety(enabled: bool, *, key_id: str | None, key_path: str | None,
                     key_readable: bool, key_world_readable: bool, web_concurrency: int = 0
                     ) -> list[tuple[str, str]]:
    """Pure fail-hard check for the real-time Stage 2 live feed (the FIRST time the app holds Kalshi
    EXCHANGE credentials). Returns ``(level, message)`` pairs; ``"fatal"`` aborts boot. All checks are
    inert when ``enabled`` is False (default), so a normal deploy is unaffected. Mirrors `bind_safety`'s
    shape so the same enforcement boundary prints + aborts. Unit-testable (no IO — the filesystem facts are
    passed in)."""
    issues: list[tuple[str, str]] = []
    if not enabled:
        return issues
    if not key_id:
        issues.append(("fatal", "KALSHI_LIVE_ENABLED=1 but KALSHI_API_KEY_ID is unset. The live feed needs "
                                "the Kalshi access-key id. Unset it (or KALSHI_LIVE_ENABLED) to stay OFF."))
    if not key_path:
        issues.append(("fatal", "KALSHI_LIVE_ENABLED=1 but KALSHI_PRIVATE_KEY_PATH is unset. Point it at the "
                                "RSA private key (.pem) for the WS handshake."))
    elif not key_readable:
        issues.append(("fatal", f"KALSHI_PRIVATE_KEY_PATH={key_path!r} is missing or unreadable."))
    elif key_world_readable:
        issues.append(("fatal", f"Refusing to load {key_path!r}: the private key file is group/world-"
                                "readable. Restrict it (chmod 600) — it authenticates to the exchange."))
    if web_concurrency > 1:
        issues.append(("fatal", "KALSHI_LIVE_ENABLED=1 with WEB_CONCURRENCY>1: the live WS connection + book "
                                "state are PROCESS-LOCAL. A 2nd worker = a 2nd authenticated WS session, "
                                "doubled subscriptions, and snapshot races. Run a single worker."))
    return issues


def _key_is_world_readable(path: str) -> bool:
    """Best-effort POSIX permission check (group/other readable). Windows has different ACL semantics — the
    stat mode bits aren't meaningful there, so we skip the check (return False) and rely on NTFS ACLs."""
    if os.name == "nt":
        return False
    try:
        import stat
        mode = os.stat(path).st_mode
        return bool(mode & (stat.S_IRGRP | stat.S_IROTH))
    except OSError:
        return False


def _enforce_live_feed_safety() -> None:
    """Boundary for the live feed: read the env + filesystem, fail-hard on any fatal, and (when safe) build
    the process-wide `live_feed.LiveFeed` singleton + flip `config.LIVE_FEED_ENABLED`. The FastAPI lifespan
    (api.py) starts/stops the singleton on the event loop. A no-op unless `KALSHI_LIVE_ENABLED=1`."""
    enabled = os.getenv("KALSHI_LIVE_ENABLED") == "1"
    key_id = os.getenv("KALSHI_API_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    try:
        web_concurrency = int(os.getenv("WEB_CONCURRENCY", "0") or "0")
    except ValueError:
        web_concurrency = 0
    key_readable = bool(key_path) and os.path.isfile(key_path) and os.access(key_path, os.R_OK)
    issues = live_feed_safety(
        enabled, key_id=key_id, key_path=key_path, key_readable=key_readable,
        key_world_readable=_key_is_world_readable(key_path) if key_readable else False,
        web_concurrency=web_concurrency)
    for level, msg in issues:
        print(f"{'ERROR (refused):' if level == 'fatal' else 'WARNING:'} {msg}")
    if any(level == "fatal" for level, _ in issues):
        raise SystemExit(2)
    if not enabled:
        return
    # Safe to arm: load the key (never logged), build the singleton, flip the config switch. The lifespan
    # will start it on the loop. Subscriptions are seeded from the latest snapshot (bounded).
    import live_feed
    with open(key_path, "rb") as fh:   # noqa: PTH123 — small one-shot read at boot
        pem = fh.read()
    config.LIVE_FEED_ENABLED = True
    # Stage 2D opt-in: allow live-derived rows to rank Actionable (still gated per-leg). Default OFF = 2C.
    if os.getenv("KALSHI_LIVE_ACTIONABILITY") == "1":
        config.LIVE_ACTIONABILITY_ENABLED = True
    live_feed.feed_singleton = live_feed.LiveFeed(key_id, pem, tickers=live_feed.plan_subscriptions())
    mode = "2D (live actionability)" if config.LIVE_ACTIONABILITY_ENABLED else "2C (live display)"
    print("Live feed ARMED: the app now holds Kalshi EXCHANGE credentials (read-only WS). "
          f"Subscribing to {len(live_feed.feed_singleton._tickers)} markets from the latest snapshot. "
          f"Mode: {mode}.")


def apply_runtime_defaults() -> None:
    """Secure-by-default for the served app: authentication ON and self-registration ON unless the operator
    explicitly sets them. Applied ONLY here (the supported ``python serve.py`` entrypoint), NOT at module
    import — so `import api` / the test suite keep their open-by-default contract. (An operator who runs
    `uvicorn api:app` directly bypasses this, exactly like the bind guard — `python serve.py` is the
    supported secure entrypoint; see docs/AUTH.md.) Opt out with AUTH_ENABLED=0 / AUTH_ALLOW_SIGNUP=0."""
    os.environ.setdefault("AUTH_ENABLED", "1")
    os.environ.setdefault("AUTH_ALLOW_SIGNUP", "1")


def seed_admin_from_env() -> None:
    """One-shot first-admin bootstrap from the environment (boundary — config stays import-free). When
    ``APP_ADMIN_USER`` and ``APP_ADMIN_PASSWORD`` are both set AND the auth store has ZERO users, create the
    first admin with ``force_pw_change`` so the env password is replaced at first login. Idempotent: once any
    user exists this is a no-op (it NEVER overwrites an existing account). A weak/default-like password is
    refused. The password is never logged. ``AUTH_DB_PATH`` is read here (the same boundary as the CLI)."""
    import auth_store

    user = os.getenv("APP_ADMIN_USER")
    password = os.getenv("APP_ADMIN_PASSWORD")
    if not user or not password:
        return
    db = os.getenv("AUTH_DB_PATH", config.AUTH_DB_PATH)
    if auth_store.user_count(db_path=db) > 0:
        return
    err = auth_store.validate_password_strength(password)
    if err:
        raise SystemExit(f"APP_ADMIN_PASSWORD rejected: {err}")
    import time
    auth_store.create_user(user, password, now=time.time(), force_pw_change=True, db_path=db)
    print(f"Seeded first admin user {user!r} (must change password at first login).")


def resolve_pause_when_idle(raw: str | None, default: bool) -> bool:
    """Resolve the effective presence-gate setting from the ``AUTO_SCAN_PAUSE_WHEN_IDLE`` env override
    (``config.py`` stays import-free, so the env read lives here at the boundary). ``"0"``/``"false"``/
    ``"no"``/``"off"`` -> ``False`` (scan even with no viewer — the headless 24/7 mode); ``"1"``/
    ``"true"``/``"yes"``/``"on"`` -> ``True``; unset/blank/unrecognized -> the config default. Pure and
    unit-testable."""
    if raw is None or not raw.strip():
        return default
    val = raw.strip().lower()
    if val in ("0", "false", "no", "off"):
        return False
    if val in ("1", "true", "yes", "on"):
        return True
    return default


def server_mode_pause_default(host: str, config_default: bool) -> bool:
    """The DEFAULT idle-pause for a given bind host. A non-loopback (server / LAN) bind is a "deployed"
    server, so it defaults to **24/7 scanning** (no idle pause) — the snapshot stays fresh even with no
    browser open. A loopback (local dev) bind keeps the interactive `config_default` (pause when idle).
    The `AUTO_SCAN_PAUSE_WHEN_IDLE` env override still wins over this default either way. Pure/testable."""
    return False if host not in _LOOPBACK_HOSTS else config_default


def resolve_snapshot_db_path(raw: str | None) -> str | None:
    """Validate an explicit ``SNAPSHOT_DB_PATH`` override (the env value; ``None``/empty -> keep the
    config default, return ``None``). Raises ``SystemExit`` with a clear message if the parent directory
    is missing — fail FAST at startup instead of surfacing a confusing sqlite "unable to open database
    file" on the first write. ``config.py`` stays import-free, so the env is read here at the boundary
    (like ``SCAN_TOKEN`` in ``api.py``). Pure apart from the directory check; unit-testable."""
    if not raw:
        return None
    parent = os.path.dirname(os.path.abspath(raw))
    if not os.path.isdir(parent):
        raise SystemExit(
            f"SNAPSHOT_DB_PATH={raw!r}: parent directory {parent!r} does not exist. "
            "Create it (writable by the service user) before starting.")
    return raw


def _apply_snapshot_db_path() -> None:
    """Point the snapshot store at ``SNAPSHOT_DB_PATH`` from the env, applied ONCE at startup so every
    store read/write — the REST API and the in-process dashboard alike — uses it (``store`` reads
    ``config.SNAPSHOT_DB_PATH`` at call time)."""
    resolved = resolve_snapshot_db_path(os.getenv("SNAPSHOT_DB_PATH"))
    if resolved:
        config.SNAPSHOT_DB_PATH = resolved


if __name__ == "__main__":
    apply_runtime_defaults()
    _apply_snapshot_db_path()
    seed_admin_from_env()
    _host = os.getenv("API_HOST", config.API_HOST)
    _port = int(os.getenv("API_PORT", str(config.API_PORT)))
    _enforce_bind_safety(_host)
    _enforce_live_feed_safety()   # arms the Stage 2 live feed only when KALSHI_LIVE_ENABLED=1 (else no-op)
    if _host not in _LOOPBACK_HOSTS:
        print(f"Serving on http://{_host}:{_port}  ·  reach it from the LAN at "
              f"http://<this-machine-LAN-IP>:{_port}  (see docs/DEPLOYMENT.md)")
    # Start the in-process auto-scan loop HERE (runtime only) so `import serve` / the test harnesses never
    # spawn a background scan. It drives the NON-force scan; the ScanManager TTL/budget/singleflight guards
    # bound every tick. (When using this, disable the optional systemd scan.timer — see docs/DEPLOYMENT.md.)
    # Presence gate (P4): pause auto-scanning while no viewer is connected (config default on). For a
    # headless 24/7 server (no browser ever connected) set AUTO_SCAN_PAUSE_WHEN_IDLE=0 to scan regardless.
    # A non-loopback (server / LAN) bind defaults to 24/7 scanning; loopback (local dev) keeps the
    # interactive config default. An explicit AUTO_SCAN_PAUSE_WHEN_IDLE env var overrides either.
    _pause_when_idle = resolve_pause_when_idle(
        os.getenv("AUTO_SCAN_PAUSE_WHEN_IDLE"), server_mode_pause_default(_host, config.AUTO_SCAN_PAUSE_WHEN_IDLE))
    # Idle gate: scan when a NiceGUI viewer is connected OR the Terminal Pro SPA polled its feed recently
    # (the SPA isn't a NiceGUI client; its feed poll heartbeats presence). When idle-pause is OFF, gate=None
    # (headless 24/7 scanning, unchanged).
    _gate = (lambda: presence.count() > 0
             or presence.recently_active(config.TERMINAL_PRESENCE_WINDOW_S)) if _pause_when_idle else None
    # ASCII-only (Windows cp1252 consoles can't encode some punctuation and would crash the print).
    print("Auto-scan presence gate: "
          + ("ON (paused while no viewer connected; terminal feed poll counts as a viewer)" if _pause_when_idle
             else "OFF (headless - scanning 24/7 regardless of viewers)"))
    scan_scheduler.scheduler.start(lambda: engine.run_scan_now(force=False), gate=_gate)
    uvicorn.run(api.app, host=_host, port=_port)
