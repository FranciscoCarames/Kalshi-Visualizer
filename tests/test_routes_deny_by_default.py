"""Deny-by-default guard: enumerate every route registered on the FastAPI app and assert each is either
in the explicit PUBLIC allowlist or gated by the auth middleware. This fails the moment someone adds a new
data route that accidentally lands under a public prefix — the whole point of deny-by-default."""
from __future__ import annotations

import api
import auth

# The ONLY paths intended to be reachable without a session/token. Auth-router paths are gate-exempt but
# enforce their own auth internally (me/devices). Static prefixes (/terminal, /assets) and the SPA root
# serve the public bundle. If you add a route here, you are explicitly making it public — think twice.
EXPECTED_PUBLIC = {
    "/", "/index.html", "/healthz", "/favicon.ico", "/docs", "/redoc", "/openapi.json",
    "/auth/login", "/auth/logout", "/auth/me", "/auth/config", "/auth/register", "/auth/password",
    "/auth/devices", "/auth/devices/{token_id}/revoke",
}

# Data/operational routes that MUST be gated (a representative, must-stay-gated set).
MUST_BE_GATED = {
    "/opportunities", "/opportunities/{opportunity_id}", "/coverage", "/metrics", "/readyz",
    "/scan", "/scan/status", "/alerts", "/backlog", "/backlog/events",
    "/api/terminal/feed", "/api/terminal/detail", "/api/terminal/payoff", "/api/terminal/ladder",
    "/api/terminal/diagnostics", "/api/terminal/telemetry", "/api/terminal/orderbook",
    "/api/terminal/export",
}


def _route_paths() -> set[str]:
    return {r.path for r in api.app.routes if getattr(r, "path", None)}


def test_every_route_is_classified_public_or_gated():
    paths = _route_paths()
    public = {p for p in paths if auth.is_public(p)}
    # No surprise public routes: the computed public set must be a subset of the explicit allowlist.
    assert public <= EXPECTED_PUBLIC, f"unexpected public routes: {public - EXPECTED_PUBLIC}"


def test_data_routes_are_gated():
    paths = _route_paths()
    for p in MUST_BE_GATED:
        assert p in paths, f"expected route {p} not registered (rename?)"
        assert not auth.is_public(p), f"data route {p} is PUBLIC — deny-by-default violation"


def test_allowlist_entries_actually_exist():
    """Keep EXPECTED_PUBLIC honest: every non-static allowlisted path is a real registered route (so a
    typo'd allowlist entry can't mask a gap)."""
    paths = _route_paths()
    for p in EXPECTED_PUBLIC:
        if p in ("/", "/index.html"):
            continue                      # served by StaticFiles mounts added in serve.py, not api.app
        assert p in paths, f"allowlisted path {p} is not a registered route"
