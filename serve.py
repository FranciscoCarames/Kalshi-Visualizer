"""Entrypoint: the FastAPI engine API + the NiceGUI dashboard, served by uvicorn (Stage 5).

The REST API (`api.app`) and the NiceGUI opportunity-first dashboard run on ONE app: importing
`webui.dashboard` registers the `@ui.page('/')`, and `ui.run_with` mounts NiceGUI onto `api.app`. The
Streamlit app (`app.py`) is unchanged and still runs separately until a later retirement milestone.
Run: ``python serve.py``  (UI at ``/``, REST at ``/opportunities`` etc., OpenAPI at ``/docs``).

**Bind / LAN safety (PR 19a).** The bind address/port are env-overridable (``API_HOST``/``API_PORT``) so
the same code serves loopback-only (the safe default, ``127.0.0.1``) or the whole LAN
(``API_HOST=0.0.0.0`` — see ``docs/LAN_ACCESS.md``). Before binding, ``bind_safety`` enforces two rules:
the dashboard has **no auth** and NiceGUI signs its session cookie with the storage secret, so exposing it
on a non-loopback host with only the dev-fallback secret is refused (set ``NICEGUI_STORAGE_SECRET``, or
``ALLOW_DEV_STORAGE_SECRET_ON_LAN=1`` to override on a trusted LAN); and the snapshot store + Kalshi
throttle are **process-local**, so ``WEB_CONCURRENCY>1`` / ``--workers`` is warned against (it would
fragment them). The guard protects ``python serve.py``; a process manager running ``uvicorn api:app
--host 0.0.0.0 --workers N`` bypasses it — see ``docs/DEPLOYMENT.md``.
"""
from __future__ import annotations

import os
import sys

import uvicorn
from nicegui import ui

import api
import config
import webui.dashboard  # noqa: F401  — importing registers the @ui.page('/') dashboard

# Real storage secret comes from the env; the config value is only a clearly-labeled dev fallback.
_storage_secret = os.getenv("NICEGUI_STORAGE_SECRET") or config.NICEGUI_STORAGE_SECRET_FALLBACK

ui.run_with(api.app, mount_path="/", storage_secret=_storage_secret)

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def bind_safety(host: str, *, storage_secret_set: bool, allow_dev_on_lan: bool,
                web_concurrency: int = 0, has_workers_arg: bool = False) -> list[tuple[str, str]]:
    """Pure, no-IO safety check for a chosen bind configuration. Returns ``(level, message)`` pairs where
    ``level`` is ``"fatal"`` (startup MUST abort) or ``"warn"`` (print and continue).

    - **Storage-secret fail-hard (security):** exposing a non-loopback host without a real
      ``NICEGUI_STORAGE_SECRET`` is ``fatal`` — the dashboard has no auth and the dev-fallback secret is
      public. ``allow_dev_on_lan`` (``ALLOW_DEV_STORAGE_SECRET_ON_LAN=1``) downgrades it to a loud ``warn``.
    - **Multi-worker guard (operational, best-effort):** ``web_concurrency > 1`` or a ``--workers`` arg →
      ``warn``; the snapshot store + Kalshi throttle are per-process, so multiple workers fragment them.
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
    if web_concurrency > 1 or has_workers_arg:
        issues.append(("warn",
                       "Multiple workers requested (WEB_CONCURRENCY>1 / --workers): the snapshot store and "
                       "the Kalshi request throttle are PROCESS-LOCAL, so each worker keeps its own and "
                       "they fragment (duplicate scans, divergent data). Run a single worker."))
    return issues


def _enforce_bind_safety(host: str) -> None:
    """Apply ``bind_safety`` for the live environment: print warnings, abort on any fatal (before bind)."""
    try:
        web_concurrency = int(os.getenv("WEB_CONCURRENCY", "0") or "0")
    except ValueError:
        web_concurrency = 0
    issues = bind_safety(
        host,
        storage_secret_set=bool(os.getenv("NICEGUI_STORAGE_SECRET")),
        allow_dev_on_lan=os.getenv("ALLOW_DEV_STORAGE_SECRET_ON_LAN") == "1",
        web_concurrency=web_concurrency,
        has_workers_arg=any(a == "--workers" or a.startswith("--workers=") for a in sys.argv[1:]),
    )
    # ASCII-only prefixes: Windows consoles default to cp1252, which can't encode ⚠/✖ and would crash
    # the print (UnicodeEncodeError) before the refusal is shown.
    for level, msg in issues:
        print(f"{'ERROR (refused):' if level == 'fatal' else 'WARNING:'} {msg}")
    if any(level == "fatal" for level, _ in issues):
        raise SystemExit(2)


if __name__ == "__main__":
    _host = os.getenv("API_HOST", config.API_HOST)
    _port = int(os.getenv("API_PORT", str(config.API_PORT)))
    _enforce_bind_safety(_host)
    if _host not in _LOOPBACK_HOSTS:
        print(f"Serving on http://{_host}:{_port}  ·  reach it from the LAN at "
              f"http://<this-machine-LAN-IP>:{_port}  (see docs/LAN_ACCESS.md)")
    uvicorn.run(api.app, host=_host, port=_port)
