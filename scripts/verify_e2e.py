"""End-to-end "is everything working?" verification.

Boots the REAL ``serve.py`` (its own ephemeral port + a throwaway tmp ``auth.db``/snapshot DB, so your live
data is never touched), waits for health, then drives the COMPLETE user journey over real HTTP - the same
paths a browser hits - and prints a PASS/FAIL report. Exit code 0 iff every check passes.

Run:  python scripts/verify_e2e.py        (add -v to tail the server log on failure)

This complements the in-process pytest suite (`pytest -q`): it proves the built SPA is served, the auth
middleware is wired in the real ASGI stack, cookies round-trip across separate clients, and the
secure-by-default runtime actually engages - things a TestClient can't fully exercise.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
BASE_TIMEOUT = 25                       # seconds to wait for the server to come up
API_TOKEN = "e2e-machine-token-xyz"

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(base: str, proc: subprocess.Popen) -> bool:
    deadline = time.time() + BASE_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            return False                # server died during boot
        try:
            if requests.get(f"{base}/healthz", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.4)
    return False


def run_checks(base: str) -> None:
    S = requests.Session

    # 1. Health + public surface + secure-by-default config.
    print("\n# Health & secure defaults")
    r = requests.get(f"{base}/healthz", timeout=5)
    check("/healthz returns 200 + ok", r.status_code == 200 and r.json().get("status") == "ok")
    cfg = requests.get(f"{base}/auth/config", timeout=5).json()
    check("auth is ON by default (serve.py)", cfg.get("auth_enabled") is True, str(cfg))
    check("self-registration is ON by default", cfg.get("signup_enabled") is True, str(cfg))
    check("remember-me available (flag set)", cfg.get("remember_available") is True, str(cfg))
    idx = requests.get(f"{base}/", timeout=5)
    check("SPA index served at / (built bundle)", idx.status_code == 200 and "root" in idx.text.lower())

    # 2. Deny-by-default gating for the anonymous user.
    print("\n# Gating (anonymous -> 401 / docs off)")
    for path in ("/api/terminal/feed", "/opportunities", "/metrics", "/coverage", "/readyz",
                 "/alerts", "/backlog", "/auth/preferences", "/auth/devices"):
        code = requests.get(f"{base}{path}", timeout=5).status_code
        check(f"anon GET {path} -> 401", code == 401, f"got {code}")
    check("/docs disabled in prod -> 404", requests.get(f"{base}/docs", timeout=5).status_code == 404)
    check("/openapi.json disabled -> 404", requests.get(f"{base}/openapi.json", timeout=5).status_code == 404)

    # 3. Registration + auto-login.
    print("\n# Registration & login")
    alice = S()
    r = alice.post(f"{base}/auth/register", json={"username": "alice", "password": "alice-strong-pw-1"})
    check("register alice -> 200 + auto-login", r.status_code == 200 and r.json()["user"]["username"] == "alice")
    sc = r.headers.get("set-cookie", "").lower()
    check("session cookie is HttpOnly + SameSite=Strict", "httponly" in sc and "samesite=strict" in sc, sc)
    check("alice /auth/me -> 200", alice.get(f"{base}/auth/me").json()["user"]["username"] == "alice")
    check("alice reaches a gated data route", alice.get(f"{base}/opportunities").status_code == 200)
    dup = requests.post(f"{base}/auth/register", json={"username": "alice", "password": "another-strong-pw"})
    check("duplicate registration -> 409", dup.status_code == 409, f"got {dup.status_code}")
    weak = requests.post(f"{base}/auth/register", json={"username": "weaky", "password": "short"})
    check("weak password registration -> 400", weak.status_code == 400)

    # 4. Per-user profile persistence + isolation.
    print("\n# Profiles: persistence & cross-user isolation")
    alice.put(f"{base}/auth/preferences",
              json={"prefs": {"theme": "hc", "layoutPreset": "triage", "split": "vertical", "evil": 1}})
    ap = alice.get(f"{base}/auth/preferences").json()["prefs"]
    check("alice profile saved (sanitized envelope)",
          ap.get("theme") == "hc" and ap.get("layoutPreset") == "triage" and "evil" not in ap, str(ap))
    # Persistence across a NEW session (fresh login picks up the stored profile).
    alice2 = S()
    alice2.post(f"{base}/auth/login", json={"username": "alice", "password": "alice-strong-pw-1"})
    check("profile persists across a fresh login",
          alice2.get(f"{base}/auth/preferences").json()["prefs"].get("theme") == "hc")
    # Bob is isolated.
    bob = S()
    bob.post(f"{base}/auth/register", json={"username": "bob", "password": "bob-strong-pw-1"})
    check("bob sees his OWN empty profile, not alice's",
          bob.get(f"{base}/auth/preferences").json()["prefs"] == {})
    check("bob cannot read alice via ?user_id=1",
          bob.get(f"{base}/auth/preferences?user_id=1").json()["prefs"] == {})
    bob.put(f"{base}/auth/preferences", json={"prefs": {"theme": "amber"}, "user_id": 1})
    check("bob's write does NOT touch alice's profile",
          alice.get(f"{base}/auth/preferences").json()["prefs"].get("theme") == "hc")
    big = {"columns": {"opp": ["x" * 1000] * 100}}
    check("oversize profile rejected -> 400",
          alice.put(f"{base}/auth/preferences", json={"prefs": big}).status_code == 400)

    # 5. CSRF (Origin) on a cookie write.
    print("\n# CSRF / Origin")
    cross = alice.put(f"{base}/auth/preferences", headers={"Origin": "http://evil.example"},
                      json={"prefs": {"theme": "amber"}})
    check("cross-origin cookie PUT -> 403", cross.status_code == 403, f"got {cross.status_code}")
    check("alice profile unchanged after blocked CSRF",
          alice.get(f"{base}/auth/preferences").json()["prefs"].get("theme") == "hc")

    # 6. Machine token policy.
    print("\n# Machine token")
    h = {"X-API-Token": API_TOKEN}
    check("token reaches a DATA route -> 200",
          requests.get(f"{base}/opportunities", headers=h).status_code == 200)
    check("token is 403 on a USER-ONLY route (/auth/preferences)",
          requests.get(f"{base}/auth/preferences", headers=h).status_code == 403)
    check("bad token -> 401", requests.get(f"{base}/opportunities", headers={"X-API-Token": "nope"}).status_code == 401)

    # 7. Password change -> rotation + revocation.
    print("\n# Password change")
    pc = alice.post(f"{base}/auth/password",
                    json={"current_password": "alice-strong-pw-1", "new_password": "alice-strong-pw-2"})
    check("password change -> 200", pc.status_code == 200, f"got {pc.status_code}")
    check("changing password revokes the OTHER session",
          alice2.get(f"{base}/auth/me").status_code == 401)
    check("caller stays logged in after own change", alice.get(f"{base}/auth/me").status_code == 200)
    check("old password no longer works",
          S().post(f"{base}/auth/login", json={"username": "alice", "password": "alice-strong-pw-1"}).status_code == 401)
    check("new password works",
          S().post(f"{base}/auth/login", json={"username": "alice", "password": "alice-strong-pw-2"}).status_code == 200)

    # 8. Remember-me transparent re-login + rotation.
    print("\n# Remember this PC")
    rmb = S()
    rr = rmb.post(f"{base}/auth/login", json={"username": "bob", "password": "bob-strong-pw-1", "remember": True})
    remember = rr.cookies.get("kss_remember")
    check("remember cookie issued on opt-in", bool(remember))
    if remember:
        fresh = S()
        fresh.cookies.set("kss_remember", remember)
        check("fresh client w/ only remember cookie -> re-logged-in",
              fresh.get(f"{base}/auth/me").status_code == 200)

    # 9. Login rate-limit (brute-force defense).
    print("\n# Rate limiting")
    codes = [requests.post(f"{base}/auth/login",
                           json={"username": "ratelimit-victim", "password": f"wrong-{i}"}).status_code
             for i in range(7)]
    check("repeated bad logins eventually -> 429", 429 in codes, f"codes={codes}")

    # 10. Logout clears the session.
    print("\n# Logout")
    bob.post(f"{base}/auth/logout")
    check("after logout, profile route -> 401", bob.get(f"{base}/auth/preferences").status_code == 401)


def main() -> int:
    verbose = "-v" in sys.argv
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp(prefix="kss-e2e-")
    log_path = pathlib.Path(tmp) / "serve.log"
    env = {
        **os.environ,
        "API_HOST": "127.0.0.1", "API_PORT": str(port),
        "AUTH_DB_PATH": str(pathlib.Path(tmp) / "auth.db"),
        "SNAPSHOT_DB_PATH": str(pathlib.Path(tmp) / "snap.db"),
        "NICEGUI_STORAGE_SECRET": "e2e-real-secret-not-the-dev-fallback",
        "APP_SESSION_SECRET": "e2e-real-session-secret",
        "APP_API_TOKEN": API_TOKEN,
        "AUTH_REMEMBER_ENABLED": "1",
        "AUTO_SCAN_PAUSE_WHEN_IDLE": "1",
        # auth + signup default ON via serve.apply_runtime_defaults(); leave them unset to prove that.
    }
    for k in ("AUTH_ENABLED", "AUTH_ALLOW_SIGNUP"):
        env.pop(k, None)

    print(f"Booting serve.py on {base}  (tmp data: {tmp})")
    with open(log_path, "w") as log:
        proc = subprocess.Popen([sys.executable, "serve.py"], cwd=str(REPO), env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    try:
        if not _wait_healthy(base, proc):
            print("FAIL: server did not become healthy.")
            print(log_path.read_text(errors="replace")[-2000:])
            return 1
        run_checks(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if verbose:
            print("\n--- server log (tail) ---")
            print(log_path.read_text(errors="replace")[-3000:])

    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{'=' * 52}\nRESULT: {passed}/{total} checks passed"
          + (" - ALL GREEN" if passed == total else " - SEE FAILURES ABOVE"))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
