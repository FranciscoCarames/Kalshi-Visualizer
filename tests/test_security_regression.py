"""Security regression suite — exercises the designed security PROPERTIES of the auth + per-user-profile
system end to end (FastAPI TestClient, AUTH_ENABLED=1, a two-user tmp auth.db). This is a regression net,
NOT a proof of zero vulnerabilities: it pins cross-user isolation, session-derived identity, no
credential leakage, session/cookie hardening, CSRF, machine-token policy, prefs validation, FK cascade,
and engine-payload isolation.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import auth
import auth_store
import config
import scan_manager
from webui import feed

ALICE_PW = "alice-correct-horse"
BOB_PW = "bob-correct-horse"


def _stub_fetch(_sport_id):
    """Hermetic fetch for the /scan-bypass tests — no network, returns instantly, so a triggered scan can
    never spawn a lingering thread that hits the real Kalshi client (and pollutes other tests' mocks)."""
    return pd.DataFrame(), "2026-06-15 00:00:00 UTC", [], 1, 0, 0, 0


@pytest.fixture
def two_users(tmp_path, monkeypatch):
    auth_db = str(tmp_path / "auth.db")
    snap_db = str(tmp_path / "snap.db")
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_DB_PATH", auth_db)
    monkeypatch.delenv("APP_API_TOKEN", raising=False)
    monkeypatch.delenv("SCAN_TOKEN", raising=False)
    monkeypatch.delenv("APP_TLS", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    auth._reset_login_limiters()
    auth._reset_action_limiters()
    scan_manager.manager.reset()
    api._scan_limiter.reset()
    auth_store.create_user("alice", ALICE_PW, now=time.time(), db_path=auth_db)
    auth_store.create_user("bob", BOB_PW, now=time.time(), db_path=auth_db)
    api.app.dependency_overrides[api.db_path_dep] = lambda: snap_db
    api.app.dependency_overrides[api.fetch_dep] = lambda: _stub_fetch
    a, b = TestClient(api.app), TestClient(api.app)
    a.post("/auth/login", json={"username": "alice", "password": ALICE_PW})
    b.post("/auth/login", json={"username": "bob", "password": BOB_PW})
    yield a, b, auth_db, snap_db
    api.app.dependency_overrides.clear()
    auth._reset_login_limiters()
    auth._reset_action_limiters()
    scan_manager.manager.reset()
    api._scan_limiter.reset()


# --- cross-user isolation (the headline) ---------------------------------------------
def test_one_user_cannot_read_or_write_anothers_profile(two_users):
    a, b, _db, _snap = two_users
    a.put("/auth/preferences", json={"prefs": {"theme": "hc", "split": "vertical"}})
    # Bob sees his own (empty) profile, never alice's.
    assert b.get("/auth/preferences").json()["prefs"] == {}
    # Bob writing his own profile does not touch alice's.
    b.put("/auth/preferences", json={"prefs": {"theme": "amber"}})
    assert a.get("/auth/preferences").json()["prefs"]["theme"] == "hc"
    assert b.get("/auth/preferences").json()["prefs"]["theme"] == "amber"


def test_user_id_in_query_or_body_is_ignored(two_users):
    a, b, db, _snap = two_users
    a.put("/auth/preferences", json={"prefs": {"theme": "hc"}})
    bob_id = auth_store.get_user("bob", db_path=db)["id"]
    alice_id = auth_store.get_user("alice", db_path=db)["id"]
    # Bob tries to name alice via query + body — both ignored; he only ever reads his own ({}).
    assert b.get(f"/auth/preferences?user_id={alice_id}").json()["prefs"] == {}
    b.put("/auth/preferences", json={"prefs": {"theme": "amber"}, "user_id": alice_id,
                                     "username": "alice"})
    assert a.get("/auth/preferences").json()["prefs"]["theme"] == "hc"   # alice untouched
    assert bob_id != alice_id


def test_one_user_cannot_see_or_revoke_anothers_devices(two_users, monkeypatch):
    a, b, db, _snap = two_users
    monkeypatch.setenv("AUTH_REMEMBER_ENABLED", "1")
    # Alice registers a remembered device.
    a2 = TestClient(api.app)
    a2.post("/auth/login", json={"username": "alice", "password": ALICE_PW, "remember": True})
    alice_devs = a2.get("/auth/devices").json()["devices"]
    assert len(alice_devs) == 1
    # Bob never sees alice's devices, and revoking her token id is a no-op.
    assert b.get("/auth/devices").json()["devices"] == []
    b.post(f"/auth/devices/{alice_devs[0]['id']}/revoke")
    assert len(a2.get("/auth/devices").json()["devices"]) == 1     # alice's still active


def test_logout_does_not_flash_other_users_state(two_users):
    a, b, _db, _snap = two_users
    a.put("/auth/preferences", json={"prefs": {"theme": "hc"}})
    a.post("/auth/logout")
    assert a.get("/auth/preferences").status_code == 401            # alice anon now
    assert b.get("/auth/preferences").json()["prefs"] == {}         # bob never sees alice's


# --- no credential leakage -----------------------------------------------------------
def test_password_hash_never_appears_in_any_response(two_users):
    a, _b, db, _snap = two_users
    a.put("/auth/preferences", json={"prefs": {"theme": "hc"}})
    pw_hash = auth_store.get_user("alice", db_path=db)["pw_hash"]
    for path in ("/auth/me", "/auth/preferences", "/auth/devices"):
        body = a.get(path).text
        assert pw_hash not in body and ALICE_PW not in body and "pw_hash" not in body


def test_session_cookie_contains_no_sensitive_data(two_users):
    a, _b, _db, _snap = two_users
    raw = a.cookies.get(config.AUTH_COOKIE_NAME)
    payload = auth._serializer().loads(raw, max_age=config.AUTH_SESSION_IDLE_SECONDS)
    assert set(payload.keys()) == {"uid", "iat"}      # ONLY a minimal identifier, no pw/prefs/token


# --- session / cookie hardening ------------------------------------------------------
def test_login_sets_hardened_cookie_flags(two_users):
    _a, _b, _db, _snap = two_users
    fresh = TestClient(api.app)
    r = fresh.post("/auth/login", json={"username": "alice", "password": ALICE_PW})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc


def test_cookie_secure_under_tls(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("APP_TLS", "1")
    auth._reset_login_limiters()
    auth_store.create_user("zoe", "zoe-correct-horse", now=time.time(), db_path=str(tmp_path / "auth.db"))
    c = TestClient(api.app)
    r = c.post("/auth/login", json={"username": "zoe", "password": "zoe-correct-horse"})
    assert "secure" in r.headers["set-cookie"].lower()


def test_password_change_rotates_and_revokes_other_sessions(two_users):
    a, _b, _db, _snap = two_users
    before = a.cookies.get(config.AUTH_COOKIE_NAME)
    # A second alice session elsewhere.
    other = TestClient(api.app)
    other.post("/auth/login", json={"username": "alice", "password": ALICE_PW})
    r = a.post("/auth/password", json={"current_password": ALICE_PW, "new_password": "alice-brand-new-pw"})
    assert r.status_code == 200
    assert a.cookies.get(config.AUTH_COOKIE_NAME) != before    # caller's cookie rotated
    assert a.get("/auth/me").status_code == 200                 # caller stays in
    assert other.get("/auth/me").status_code == 401             # the OTHER session is revoked


def test_disabled_user_session_dies(two_users):
    a, _b, db, _snap = two_users
    assert a.get("/auth/me").status_code == 200
    auth_store.set_disabled("alice", True, now=time.time(), db_path=db)
    assert a.get("/auth/me").status_code == 401


# --- CSRF (Origin) on every state-changing endpoint ----------------------------------
@pytest.mark.parametrize("method,path,body", [
    ("post", "/auth/logout", None),
    ("put", "/auth/preferences", {"prefs": {"theme": "hc"}}),
    ("post", "/auth/password", {"current_password": ALICE_PW, "new_password": "x-new-strong-pw"}),
    ("post", "/scan", None),
])
def test_cross_origin_cookie_write_rejected(two_users, method, path, body):
    a, _b, _db, _snap = two_users
    fn = getattr(a, method)
    r = fn(path, headers={"Origin": "http://evil.example"}, **({"json": body} if body else {}))
    assert r.status_code == 403


def test_machine_token_post_scan_bypasses_origin(two_users, monkeypatch):
    a, _b, _db, _snap = two_users
    monkeypatch.setenv("APP_API_TOKEN", "machine-tok")
    r = a.post("/scan", headers={"Origin": "http://evil.example", "X-API-Token": "machine-tok"})
    assert r.status_code != 403


# --- machine-token policy: 403 on user-only endpoints --------------------------------
def test_machine_token_cannot_reach_user_only_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("APP_API_TOKEN", "machine-tok")
    auth._reset_action_limiters()
    api.app.dependency_overrides[api.db_path_dep] = lambda: str(tmp_path / "snap.db")
    try:
        c = TestClient(api.app)
        h = {"X-API-Token": "machine-tok"}
        # Token reaches DATA routes …
        assert c.get("/api/terminal/feed", headers=h).status_code == 200
        # … but NOT user-only profile/credential endpoints (403, not 401/200).
        assert c.get("/auth/preferences", headers=h).status_code == 403
        assert c.get("/auth/devices", headers=h).status_code == 403
        assert c.put("/auth/preferences", headers=h, json={"prefs": {"theme": "hc"}}).status_code == 403
    finally:
        api.app.dependency_overrides.clear()


# --- preferences validation / hardening ----------------------------------------------
def test_preferences_non_object_and_oversize_rejected(two_users):
    a, _b, _db, _snap = two_users
    assert a.put("/auth/preferences", json={"prefs": ["not", "a", "dict"]}).status_code == 422  # pydantic
    big = {"columns": {"opp": ["x" * 1000] * 100}}
    assert a.put("/auth/preferences", json={"prefs": big}).status_code == 400


def test_preferences_unknown_keys_sanitized_server_side(two_users):
    a, _b, _db, _snap = two_users
    a.put("/auth/preferences", json={"prefs": {"theme": "hc", "evil": "x", "layoutPreset": "bogus"}})
    got = a.get("/auth/preferences").json()["prefs"]
    assert got.get("theme") == "hc"
    assert "evil" not in got and "layoutPreset" not in got        # unknown + invalid dropped


def test_preferences_put_rate_limited(two_users, monkeypatch):
    a, _b, _db, _snap = two_users
    monkeypatch.setattr(config, "AUTH_ACTION_LIMITS", {**config.AUTH_ACTION_LIMITS, "preferences": (2, 60)})
    auth._reset_action_limiters()
    codes = [a.put("/auth/preferences", json={"prefs": {"theme": "hc"}}).status_code for _ in range(4)]
    assert 429 in codes


# --- engine payload isolation (auth must not touch the engine) -----------------------
def test_feed_payload_is_engine_identical_under_auth(two_users):
    a, _b, _db, snap = two_users
    authed = a.get("/api/terminal/feed").json()
    direct = feed.build_feed(db_path=snap)             # the exact engine call the handler makes
    assert authed == direct                            # the gate passes the body through unchanged


# --- gated without a session ---------------------------------------------------------
def test_data_routes_require_a_session(two_users):
    _a, _b, _db, _snap = two_users
    anon = TestClient(api.app)
    for path in ("/api/terminal/feed", "/opportunities", "/metrics", "/coverage",
                 "/alerts", "/backlog"):
        assert anon.get(path).status_code == 401, path
    assert anon.get("/healthz").status_code == 200     # public liveness probe
    # /readyz is public for LB probes but its detail is redacted for anon (see test_auth.py).
    rz = anon.get("/readyz")
    assert rz.status_code in (200, 503) and rz.json().get("last_scan_status") is None
