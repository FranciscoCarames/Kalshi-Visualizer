"""Tests for the auth layer (auth.py): the /auth router + the deny-by-default gate, driven through the
FastAPI TestClient with AUTH_ENABLED=1 and a seeded tmp auth.db. No network; cookies persist on the
client, so login → gated-access → logout flows are exercised end to end."""
from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import auth
import auth_store
import scan_manager


def _stub_fetch(_sport_id):
    """Hermetic fetch so a /scan that passes the Origin check returns instantly (no network, no lingering
    scan thread that could touch the real Kalshi client in a later test)."""
    return pd.DataFrame(), "2026-06-15 00:00:00 UTC", [], 1, 0, 0, 0


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth_db = str(tmp_path / "auth.db")
    snap_db = str(tmp_path / "snap.db")
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_DB_PATH", auth_db)
    monkeypatch.delenv("APP_API_TOKEN", raising=False)
    monkeypatch.delenv("SCAN_TOKEN", raising=False)
    monkeypatch.delenv("APP_TLS", raising=False)
    monkeypatch.setenv("AUTH_REMEMBER_ENABLED", "1")          # allow remember-me without TLS in tests
    auth._reset_login_limiters()
    auth._reset_action_limiters()
    scan_manager.manager.reset()
    api._scan_limiter.reset()
    auth_store.create_user("alice", "correct horse battery", now=time.time(), db_path=auth_db)
    api.app.dependency_overrides[api.db_path_dep] = lambda: snap_db
    api.app.dependency_overrides[api.fetch_dep] = lambda: _stub_fetch
    c = TestClient(api.app)
    yield c, auth_db
    api.app.dependency_overrides.clear()
    auth._reset_login_limiters()
    auth._reset_action_limiters()
    scan_manager.manager.reset()
    api._scan_limiter.reset()


def _login(c, username="alice", password="correct horse battery", remember=False):
    return c.post("/auth/login", json={"username": username, "password": password, "remember": remember})


def test_config_reports_enabled(env):
    c, _ = env
    body = c.get("/auth/config").json()
    assert body["auth_enabled"] is True


def test_login_success_sets_cookie_and_me(env):
    c, _ = env
    r = _login(c)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert api.config.AUTH_COOKIE_NAME in r.cookies or api.config.AUTH_COOKIE_NAME in c.cookies
    me = c.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]["username"] == "alice"


def test_no_user_enumeration(env):
    c, _ = env
    unknown = c.post("/auth/login", json={"username": "ghost", "password": "whatever-long"})
    badpw = c.post("/auth/login", json={"username": "alice", "password": "wrong-but-long"})
    assert unknown.status_code == badpw.status_code == 401
    assert unknown.json()["detail"] == badpw.json()["detail"] == "Invalid username or password"


def test_gated_route_401_without_auth_200_with(env):
    c, _ = env
    assert c.get("/api/terminal/feed").status_code == 401
    assert c.get("/opportunities").status_code == 401
    _login(c)
    assert c.get("/opportunities").status_code == 200          # empty snapshot store → [] but 200


def test_healthz_stays_public(env):
    c, _ = env
    assert c.get("/healthz").status_code == 200


def test_machine_token_reaches_gated_routes(env, monkeypatch):
    c, _ = env
    monkeypatch.setenv("APP_API_TOKEN", "s3cr3t-machine-token")
    assert c.get("/opportunities").status_code == 401         # no token
    r = c.get("/opportunities", headers={"X-API-Token": "s3cr3t-machine-token"})
    assert r.status_code == 200


def test_disable_invalidates_live_cookie(env):
    c, db = env
    _login(c)
    assert c.get("/auth/me").status_code == 200
    auth_store.set_disabled("alice", True, now=time.time(), db_path=db)
    assert c.get("/auth/me").status_code == 401               # reload sees disabled → revoked


def test_password_change_invalidates_old_session(env):
    c, db = env
    _login(c)
    assert c.get("/auth/me").status_code == 200
    auth_store.set_password("alice", "a-new-strong-password", now=time.time() + 10_000, db_path=db)
    assert c.get("/auth/me").status_code == 401               # iat < session_epoch


def test_logout_clears_cookie(env):
    c, _ = env
    _login(c)
    assert c.post("/auth/logout").status_code == 200
    assert c.get("/auth/me").status_code == 401


def test_login_rate_limited(env):
    c, _ = env
    last = None
    for _ in range(api.config.AUTH_LOGIN_MAX_PER_WINDOW + 2):
        last = c.post("/auth/login", json={"username": "alice", "password": "wrong-but-long"})
    assert last.status_code == 429


def test_cross_origin_cookie_post_rejected_token_bypasses(env, monkeypatch):
    c, _ = env
    _login(c)
    # A cookie-authenticated POST with a foreign Origin is rejected (CSRF defense-in-depth).
    r = c.post("/scan", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    # Same-origin (matching host) is allowed through the gate (reaches the handler / rate limiter).
    ok = c.post("/scan", headers={"Origin": "http://testserver"})
    assert ok.status_code != 403
    # A machine-token POST bypasses the Origin check entirely.
    monkeypatch.setenv("APP_API_TOKEN", "tok")
    r2 = c.post("/scan", headers={"Origin": "http://evil.example", "X-API-Token": "tok"})
    assert r2.status_code != 403


def test_absolute_expiry_rejected(env):
    c, _ = env
    # Craft a session cookie whose iat is older than the absolute cap.
    old = time.time() - api.config.AUTH_SESSION_ABSOLUTE_SECONDS - 100
    token = auth._serializer().dumps({"uid": 1, "iat": old})
    c.cookies.set(api.config.AUTH_COOKIE_NAME, token)
    assert c.get("/auth/me").status_code == 401


def test_remember_me_transparent_relogin_and_rotation(env):
    c, db = env
    r = _login(c, remember=True)
    assert api.config.AUTH_REMEMBER_COOKIE_NAME in r.cookies or \
        api.config.AUTH_REMEMBER_COOKIE_NAME in c.cookies
    remember_raw = c.cookies.get(api.config.AUTH_REMEMBER_COOKIE_NAME)
    assert remember_raw and ":" in remember_raw
    # New client carrying ONLY the remember cookie (no session) → transparent re-login on a gated route.
    fresh = TestClient(api.app)
    fresh.cookies.set(api.config.AUTH_REMEMBER_COOKIE_NAME, remember_raw)
    assert fresh.get("/auth/me").status_code == 200
    # The original token rotated (single-use): replaying it on a third client fails.
    third = TestClient(api.app)
    third.cookies.set(api.config.AUTH_REMEMBER_COOKIE_NAME, remember_raw)
    # the second use of the SAME validator is now revoked
    assert third.get("/api/terminal/feed").status_code == 401


def test_register_disabled_by_default(env):
    c, _ = env
    r = c.post("/auth/register", json={"username": "newbie", "password": "a-strong-passphrase"})
    assert r.status_code == 403
    assert c.get("/auth/config").json()["signup_enabled"] is False


def test_register_enabled_auto_logs_in(env, monkeypatch):
    c, _ = env
    monkeypatch.setenv("AUTH_ALLOW_SIGNUP", "1")
    assert c.get("/auth/config").json()["signup_enabled"] is True
    r = c.post("/auth/register", json={"username": "newbie", "password": "a-strong-passphrase"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "newbie"
    # Auto-logged-in: the session cookie is set, so a gated route + /me work immediately.
    assert c.get("/auth/me").json()["user"]["username"] == "newbie"
    assert c.get("/opportunities").status_code == 200
    # And the new account can log in fresh.
    fresh = TestClient(api.app)
    assert _login(fresh, username="newbie", password="a-strong-passphrase").status_code == 200


def test_register_rejects_duplicate_weak_and_bad_username(env, monkeypatch):
    c, _ = env
    monkeypatch.setenv("AUTH_ALLOW_SIGNUP", "1")
    assert c.post("/auth/register",
                  json={"username": "alice", "password": "a-strong-passphrase"}).status_code == 409
    assert c.post("/auth/register",
                  json={"username": "bob", "password": "short"}).status_code == 400
    assert c.post("/auth/register",
                  json={"username": "b b", "password": "a-strong-passphrase"}).status_code == 400


def test_self_service_password_change(env):
    c, db = env
    _login(c)
    # Wrong current password → 403, password unchanged.
    bad = c.post("/auth/password", json={"current_password": "nope-wrong", "new_password": "a-fresh-strong-pw"})
    assert bad.status_code == 403
    # Weak new password → 400.
    weak = c.post("/auth/password",
                  json={"current_password": "correct horse battery", "new_password": "short"})
    assert weak.status_code == 400
    # Valid change → 200, session survives (cookie re-issued), and the new password works on a fresh login.
    ok = c.post("/auth/password",
                json={"current_password": "correct horse battery", "new_password": "a-fresh-strong-pw"})
    assert ok.status_code == 200
    assert c.get("/auth/me").status_code == 200
    fresh = TestClient(api.app)
    assert _login(fresh, password="a-fresh-strong-pw").status_code == 200


def test_devices_list_and_revoke(env):
    c, _ = env
    _login(c, remember=True)
    devices = c.get("/auth/devices").json()["devices"]
    assert len(devices) == 1
    tid = devices[0]["id"]
    assert c.post(f"/auth/devices/{tid}/revoke").status_code == 200
    assert c.get("/auth/devices").json()["devices"] == []


def test_docs_hidden_in_prod_but_open_in_dev(env, monkeypatch):
    c, _ = env                                       # env sets AUTH_ENABLED=1
    monkeypatch.delenv("APP_DEV", raising=False)
    assert c.get("/docs").status_code == 404         # hidden in an auth-on deployment
    assert c.get("/openapi.json").status_code == 404
    monkeypatch.setenv("APP_DEV", "1")
    assert c.get("/docs").status_code == 200          # re-enabled for dev
    assert c.get("/openapi.json").status_code == 200


# --- Branch 1 hardening regressions --------------------------------------------------
def test_gating_is_exhaustive(env):
    """Deny-by-default invariant (C2): EVERY non-allowlisted route returns 401 to an anonymous caller.
    Iterates the live route table so a future data route registered at the wrong (public) prefix is caught."""
    import re as _re

    from starlette.routing import Route
    c, _ = env
    checked = 0
    for r in api.app.routes:
        path = getattr(r, "path", None)
        if not path or not isinstance(r, Route) or auth.is_public(path):
            continue                                  # public/allowlisted or a Mount — skip
        methods = getattr(r, "methods", None) or set()
        method = "GET" if "GET" in methods else ("POST" if "POST" in methods else None)
        if method is None:
            continue
        concrete = _re.sub(r"\{[^}]+\}", "1", path)   # fill path params; the gate 401s before validation
        resp = c.request(method, concrete)
        assert resp.status_code == 401, f"{method} {concrete} anon -> {resp.status_code}, expected 401"
        checked += 1
    assert checked >= 8                               # sanity: the data surface was actually exercised


def test_dashboard_public_flag_opens_only_the_dashboard_mount(env, monkeypatch):
    """Transition escape hatch: DASHBOARD_PUBLIC=1 serves the legacy NiceGUI /dashboard/ mount to anon while
    the SPA's engine data (/api/terminal/feed) stays gated. Off by default — the dashboard is gated like any
    other non-public path. The "gate opens" direction is asserted via `is_public()` (the pure decision the
    gate consults) rather than by requesting /dashboard/: once an earlier test imports `serve`, that path
    routes into the real NiceGUI sub-app, which isn't TestClient-drivable. The deny direction (401) is
    request-level and safe — the gate short-circuits before reaching the mount."""
    c, _ = env
    # Default (flag unset): the dashboard mount is gated, and so is the SPA data.
    assert auth.is_public("/dashboard/") is False
    assert c.get("/dashboard/").status_code == 401
    assert c.get("/api/terminal/feed").status_code == 401

    monkeypatch.setenv("DASHBOARD_PUBLIC", "1")
    # The whole sub-app prefix is now public (page + _nicegui resources + websocket all share the mount)...
    assert auth.is_public("/dashboard") is True
    assert auth.is_public("/dashboard/") is True
    assert auth.is_public("/dashboard/_nicegui/anything") is True
    # ...but the carve-out is scoped: the SPA data surface is untouched and still requires login.
    assert auth.is_public("/api/terminal/feed") is False
    assert c.get("/api/terminal/feed").status_code == 401


def test_security_headers_and_vary_present(env):
    """A5/E2: _harden stamps all five security headers (incl. Vary: Cookie) on gated AND public responses."""
    c, _ = env
    for resp in (c.get("/opportunities"), c.get("/healthz")):   # gated 401, then public 200
        h = resp.headers
        assert h["x-frame-options"] == "DENY"
        assert h["x-content-type-options"] == "nosniff"
        assert h["content-security-policy"] == "frame-ancestors 'none'"
        assert h["referrer-policy"] == "no-referrer"
        assert h["vary"] == "Cookie"
    assert c.get("/opportunities").headers["cache-control"] == "no-store"   # no-store on the gated 401


def test_no_store_on_401_and_403(env):
    """A.4 lock-in: error responses (401 anon, 403 cross-origin) carry Cache-Control: no-store."""
    c, _ = env
    assert c.get("/opportunities").headers["cache-control"] == "no-store"
    _login(c)
    forbidden = c.post("/scan", headers={"Origin": "http://evil.example"})
    assert forbidden.status_code == 403 and forbidden.headers["cache-control"] == "no-store"


def test_readyz_public_but_redacted_for_anon(env):
    """C3: /readyz is reachable anonymously (LB probe) but its detail is redacted; an authed caller sees it.
    The tmp snap.db is empty -> deterministic 'degraded / no snapshot yet'."""
    c, _ = env
    anon = c.get("/readyz")
    assert anon.status_code == 200                    # public — not 401
    b = anon.json()
    assert b["status"] == "degraded"
    assert b["reason"] is None and b["last_scan_status"] is None and b["snapshot_age_seconds"] is None
    _login(c)
    full = c.get("/readyz").json()
    assert full["status"] == "degraded" and full["reason"] == "no snapshot yet"   # detail visible to authed


def test_scan_token_does_not_lock_out_logged_in_user(env, monkeypatch):
    """C1/E4: with SCAN_TOKEN set AND auth on, a logged-in session can still trigger /scan (no header)."""
    c, _ = env
    monkeypatch.setenv("SCAN_TOKEN", "lan-token")
    _login(c)
    r = c.post("/scan", headers={"Origin": "http://testserver"})
    assert r.status_code != 401                       # session satisfies; not blocked by the scan-token gate


def test_login_limiter_is_bounded(monkeypatch):
    """A2: the per-(ip,username) login-limiter map cannot grow without bound."""
    monkeypatch.setattr(api.config, "AUTH_LOGIN_LIMITER_MAX", 10)
    auth._reset_login_limiters()
    now = time.time()
    for i in range(100):
        auth._login_allowed(f"ip{i}", f"user{i}", now=now)
    assert len(auth._login_limiters) <= 10
    auth._reset_login_limiters()


def test_cookie_secure_flag(monkeypatch):
    """E3: cookies are marked Secure only over real TLS or a declared HTTPS-terminating proxy."""
    monkeypatch.delenv("APP_TLS", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert auth.cookie_secure() is False
    monkeypatch.setenv("APP_TLS", "1")
    assert auth.cookie_secure() is True
    monkeypatch.delenv("APP_TLS", raising=False)
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert auth.cookie_secure() is True


def _scope_request(headers: dict[str, str], hostname: str = "testserver"):
    from starlette.requests import Request
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                    "headers": raw, "server": (hostname, 80), "scheme": "http", "client": ("1.2.3.4", 1)})


def test_origin_ok_edges():
    """E5: _origin_ok — absent Origin/Referer passes (native), matching host passes, foreign/malformed fail,
    Referer is the fallback when Origin is absent."""
    assert auth._origin_ok(_scope_request({})) is True
    assert auth._origin_ok(_scope_request({"origin": "http://testserver"})) is True
    assert auth._origin_ok(_scope_request({"origin": "http://evil.example"})) is False
    assert auth._origin_ok(_scope_request({"referer": "http://testserver/x"})) is True
    assert auth._origin_ok(_scope_request({"origin": "::::nonsense"})) is False
