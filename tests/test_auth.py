"""Tests for the auth layer (auth.py): the /auth router + the deny-by-default gate, driven through the
FastAPI TestClient with AUTH_ENABLED=1 and a seeded tmp auth.db. No network; cookies persist on the
client, so login → gated-access → logout flows are exercised end to end."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import api
import auth
import auth_store


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
    auth_store.create_user("alice", "correct horse battery", now=time.time(), db_path=auth_db)
    api.app.dependency_overrides[api.db_path_dep] = lambda: snap_db
    c = TestClient(api.app)
    yield c, auth_db
    api.app.dependency_overrides.clear()
    auth._reset_login_limiters()


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


def test_doc_urls_disabled_in_prod(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.delenv("APP_DEV", raising=False)
    assert api._doc_urls() == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    monkeypatch.setenv("APP_DEV", "1")
    assert api._doc_urls()["docs_url"] == "/docs"
