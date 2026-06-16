"""Deny-by-default guard: enumerate every route registered on the FastAPI app and assert each is either
gate-exempt by explicit allowlist or gated by the auth middleware. Fails the moment a new data route lands
under a public prefix. Also asserts that NO endpoint derives identity from a client-supplied user id."""
from __future__ import annotations

import inspect

import api
import auth

# The ONLY paths reachable without going through the deny-by-default middleware. The /auth/* paths are
# gate-EXEMPT but enforce their OWN auth internally (me/password/preferences/devices) — exempt from the
# middleware, not from authentication. Static prefixes (/terminal, /assets) + the SPA root serve the public
# bundle. Adding a path here is an explicit decision to make it gate-exempt — think twice.
GATE_EXEMPT_ROUTES = {
    "/", "/index.html", "/healthz", "/readyz", "/favicon.ico", "/docs", "/redoc", "/openapi.json",
    "/auth/login", "/auth/logout", "/auth/me", "/auth/config", "/auth/register", "/auth/password",
    "/auth/preferences", "/auth/devices", "/auth/devices/{token_id}/revoke",
}
# `/readyz` is gate-exempt so a load-balancer probe works unauthenticated — but its DETAIL is REDACTED for
# an anonymous caller (status + HTTP code only; the snapshot age / last-scan error stay in gated /metrics).
# See `test_readyz_public_but_redacted_for_anon` in test_auth.py.

# Data/operational routes that MUST be gated (a representative, must-stay-gated set, incl. the ZIP export).
MUST_BE_GATED = {
    "/opportunities", "/opportunities/{opportunity_id}", "/coverage", "/metrics",
    "/scan", "/scan/status", "/alerts", "/backlog", "/backlog/events",
    "/api/terminal/feed", "/api/terminal/detail", "/api/terminal/payoff", "/api/terminal/ladder",
    "/api/terminal/diagnostics", "/api/terminal/telemetry", "/api/terminal/orderbook",
    "/api/terminal/export",
}

# Identity must ALWAYS come from the validated session cookie, never a request param. No endpoint may take
# one of these as a path/query/body field (a body model with one of these would let a caller name another
# user). `token_id` is allowed — it's a device-token row id, and the store enforces it belongs to the
# authenticated user.
FORBIDDEN_IDENTITY_PARAMS = {"user_id", "uid", "username", "user", "account", "owner"}


def _route_paths() -> set[str]:
    return {r.path for r in api.app.routes if getattr(r, "path", None)}


def test_every_route_is_classified_public_or_gated():
    paths = _route_paths()
    public = {p for p in paths if auth.is_public(p)}
    assert public <= GATE_EXEMPT_ROUTES, f"unexpected gate-exempt routes: {public - GATE_EXEMPT_ROUTES}"


def test_data_routes_are_gated():
    paths = _route_paths()
    for p in MUST_BE_GATED:
        assert p in paths, f"expected route {p} not registered (rename?)"
        assert not auth.is_public(p), f"data route {p} is gate-exempt — deny-by-default violation"


def test_allowlist_entries_actually_exist():
    """Keep GATE_EXEMPT_ROUTES honest: every non-static allowlisted path is a real registered route."""
    paths = _route_paths()
    for p in GATE_EXEMPT_ROUTES:
        if p in ("/", "/index.html"):
            continue                      # served by StaticFiles mounts added in serve.py, not api.app
        assert p in paths, f"allowlisted path {p} is not a registered route"


def test_no_endpoint_accepts_a_client_supplied_user_id():
    """Isolation invariant: no /auth/* or /api/* handler signature exposes a user-identifying parameter —
    identity is session-derived. A FastAPI route param named user_id/username/... would be client-settable
    (path/query/body), which would break cross-user isolation."""
    offenders = []
    for route in api.app.routes:
        path = getattr(route, "path", "") or ""
        handler = getattr(route, "endpoint", None)
        if handler is None or not (path.startswith("/auth/") or path.startswith("/api/")):
            continue
        for name in inspect.signature(handler).parameters:
            if name.lower() in FORBIDDEN_IDENTITY_PARAMS:
                offenders.append(f"{path} :: {name}")
    assert not offenders, f"endpoints expose a client-supplied identity param: {offenders}"
