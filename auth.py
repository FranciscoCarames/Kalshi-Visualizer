"""Auth layer for the FastAPI app — session cookies, the deny-by-default gate, and the /auth router.

UI-agnostic (no nicegui / pandas import). Two deliberate, code-accurate choices for THIS app:

1. **The session cookie is signed directly with ``itsdangerous``**, NOT Starlette ``SessionMiddleware``.
   NiceGUI already installs its own session middleware via ``ui.run_with`` (serve.py); a second one would
   collide on ``request.session``. So we own a separate, clearly-named cookie (``config.AUTH_COOKIE_NAME``)
   and read/write it ourselves.
2. **Gating is a deny-by-default HTTP middleware**, not a per-route dependency — the data routes are
   individual ``@app.get`` decorators (no shared ``/api/*`` router) and the SPA bundle + the NiceGUI
   ``/dashboard`` mount are StaticFiles/sub-apps a dependency can't reach. One middleware covers them all.

Everything is **behind ``AUTH_ENABLED``** (env, read per-request): unset → the middleware is a pass-through
(today's open behaviour + the legacy ``SCAN_TOKEN`` gate on ``/scan`` still applies), so the app and its
test suite are unchanged until an operator turns auth on. Env is read at this boundary (config stays
import-free); ``now`` is injected into the store layer so logic stays deterministic.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

import auth_store
import config
import ratelimit

logger = logging.getLogger("kalshi.auth")

# Public (un-gated) surface. Everything else requires auth when AUTH_ENABLED. Kept explicit so the
# deny-by-default test can assert no data route ever slips in. The SPA bundle (HTML/JS/CSS — no secrets)
# stays public so the login screen can load; the DATA behind it does not.
_PUBLIC_EXACT = {"/", "/index.html", "/healthz", "/favicon.ico", "/docs", "/redoc", "/openapi.json"}
_PUBLIC_PREFIXES = ("/auth/", "/terminal/", "/assets/", "/static/")

_COOKIE_MAX_AGE = config.AUTH_SESSION_ABSOLUTE_SECONDS


# --- env boundary helpers ------------------------------------------------------------
def auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED") == "1"


def auth_db_path() -> str:
    return os.getenv("AUTH_DB_PATH", config.AUTH_DB_PATH)


def tls_on() -> bool:
    return os.getenv("APP_TLS") == "1"


def cookie_secure() -> bool:
    """Mark cookies ``Secure`` over real TLS (``APP_TLS=1``) OR behind a declared HTTPS-terminating reverse
    proxy (``TRUST_PROXY=1``) — where TLS ends at the proxy and the app sees plain HTTP but the browser
    connection is still HTTPS. Without this, a proxied deployment would ship non-Secure cookies."""
    return os.getenv("APP_TLS") == "1" or os.getenv("TRUST_PROXY") == "1"


def _session_secret() -> str:
    return (os.getenv("APP_SESSION_SECRET") or os.getenv("NICEGUI_STORAGE_SECRET")
            or config.NICEGUI_STORAGE_SECRET_FALLBACK)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(), salt="kss-auth-session")


def allowed_hosts() -> list[str]:
    """Host allowlist for TrustedHostMiddleware. Default ``["*"]`` (no restriction — keeps loopback/dev and
    the test client working); an operator sets ``APP_ALLOWED_HOSTS`` (comma-separated) to lock it down."""
    raw = os.getenv("APP_ALLOWED_HOSTS", "").strip()
    if not raw:
        return ["*"]
    return [h.strip() for h in raw.split(",") if h.strip()]


# --- session cookie (itsdangerous) ---------------------------------------------------
def _set_session_cookie(response: Response, uid: int, iat: float) -> None:
    token = _serializer().dumps({"uid": uid, "iat": iat})
    response.set_cookie(
        config.AUTH_COOKIE_NAME, token, max_age=_COOKIE_MAX_AGE, httponly=True,
        samesite="strict", secure=cookie_secure(), path="/")


def _clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/")


def _read_session(request: Request, *, now: float) -> dict | None:
    """Decode + validate the session cookie. Enforces the IDLE window (cookie timestamp) and the ABSOLUTE
    cap (payload ``iat``). Returns ``{"uid", "iat"}`` or None. Does NOT touch the DB — the caller reloads
    the user for revocation."""
    raw = request.cookies.get(config.AUTH_COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=config.AUTH_SESSION_IDLE_SECONDS)
    except (SignatureExpired, BadSignature):
        return None
    iat = data.get("iat")
    if not isinstance(iat, (int, float)) or (now - iat) > config.AUTH_SESSION_ABSOLUTE_SECONDS:
        return None
    if not isinstance(data.get("uid"), int):
        return None
    return data


def _set_remember_cookie(response: Response, selector: str, validator: str) -> None:
    response.set_cookie(
        config.AUTH_REMEMBER_COOKIE_NAME, f"{selector}:{validator}",
        max_age=config.AUTH_REMEMBER_MAX_AGE, httponly=True, samesite="strict",
        secure=cookie_secure(), path="/")


def remember_available() -> bool:
    """Remember-me issues a long-lived token ONLY when the cookie can be ``Secure`` (TLS or a trusted
    HTTPS-terminating proxy) — a 30-day token on plain HTTP is the riskiest combination.
    ``AUTH_REMEMBER_ENABLED=1`` overrides for a knowingly-trusted LAN."""
    return cookie_secure() or os.getenv("AUTH_REMEMBER_ENABLED") == "1"


def signup_enabled() -> bool:
    """Self-registration is OPT-IN (``AUTH_ALLOW_SIGNUP=1``). Off by default so the safe model is
    admin-creates-accounts; on, anyone who can reach the app can register (rate-limited). The deployment
    chooses."""
    return os.getenv("AUTH_ALLOW_SIGNUP") == "1"


# --- token auth (machine / scripts) --------------------------------------------------
def _valid_api_token(request: Request) -> bool:
    """A machine token reaches gated routes without a browser session. Honors ``APP_API_TOKEN`` and, for
    back-compat, the legacy ``SCAN_TOKEN``. Constant-time compare. No ambient cookie → CSRF-immune, so the
    Origin check is skipped for token calls."""
    presented = request.headers.get("X-API-Token") or request.headers.get("X-Scan-Token") or ""
    for env_name in ("APP_API_TOKEN", "SCAN_TOKEN"):
        configured = os.getenv(env_name, "")
        if configured and hmac.compare_digest(presented, configured):
            return True
    return False


# --- the principal resolver ----------------------------------------------------------
class _Principal:
    """The authenticated party for one request. ``user`` is the DB row for a session login (None for a
    machine token). ``refresh`` carries cookies the middleware must (re)set on the response (sliding the
    session, or a rotated remember-me token)."""

    def __init__(self, *, user: dict | None, via: str) -> None:
        self.user = user
        self.via = via                       # "session" | "token" | "remember"
        self.refresh: list[tuple[str, Any]] = []


def _authenticate(request: Request, *, now: float) -> _Principal | None:
    if _valid_api_token(request):
        return _Principal(user=None, via="token")
    db = auth_db_path()
    sess = _read_session(request, now=now)
    if sess is not None:
        user = auth_store.get_user_by_id(sess["uid"], db_path=db)
        if user is not None and not user["disabled"] and sess["iat"] >= user["session_epoch"]:
            p = _Principal(user=user, via="session")
            p.refresh.append(("session", (user["id"], sess["iat"])))   # slide the idle window
            return p
    # No valid session — try a remember-me token (transparent re-login + rotation).
    raw = request.cookies.get(config.AUTH_REMEMBER_COOKIE_NAME)
    if raw and ":" in raw:
        selector, _, validator = raw.partition(":")
        user, new_token = auth_store.consume_device_token(selector, validator, now=now, db_path=db)
        if user is not None and new_token is not None:
            p = _Principal(user=user, via="remember")
            p.refresh.append(("session", (user["id"], now)))
            p.refresh.append(("remember", new_token))
            return p
    return None


def _origin_ok(request: Request) -> bool:
    """For a cookie-authenticated state-changing request, require the Origin/Referer host to match the
    request host (defense-in-depth on top of SameSite=Strict). Absent Origin (non-browser/native) passes;
    a present, mismatched Origin is rejected."""
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if not referer:
            return True
        origin = referer
    try:
        from urllib.parse import urlparse
        return urlparse(origin).hostname == request.url.hostname
    except Exception:  # noqa: BLE001
        return False


def is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(pre) for pre in _PUBLIC_PREFIXES)


_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# --- the deny-by-default gate + security headers (one HTTP middleware) ----------------
def _harden(response: Response, *, no_store: bool) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if no_store:
        response.headers["Cache-Control"] = "no-store"
    return response


_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


def docs_hidden() -> bool:
    """In an auth-on deployment the OpenAPI docs/schema are hidden (they leak the full API shape) unless
    ``APP_DEV=1``. Decided at REQUEST time so the secure default (set after import) takes effect."""
    return auth_enabled() and os.getenv("APP_DEV") != "1"


async def gate_and_harden(request: Request, call_next):
    """Deny-by-default auth gate + security headers. Pass-through (headers only) when AUTH_ENABLED is unset
    or the path is public; otherwise require a session or machine token, enforce Origin on cookie POSTs,
    and slide/rotate cookies on success."""
    now = time.time()
    path = request.url.path
    # Hide the OpenAPI docs/schema in an auth-on prod deployment (404 — as if they don't exist).
    if path in _DOCS_PATHS and docs_hidden():
        return _harden(JSONResponse({"detail": "Not Found"}, status_code=404), no_store=True)
    if not auth_enabled() or is_public(path):
        return _harden(await call_next(request), no_store=False)

    principal = _authenticate(request, now=now)
    if principal is None:
        # HTML navigation (e.g. the gated /dashboard) → bounce to the SPA login; API/data → 401 JSON.
        accepts_html = "text/html" in request.headers.get("accept", "")
        if accepts_html and not path.startswith(("/api/", "/scan", "/opportunities", "/coverage",
                                                  "/metrics", "/alerts", "/backlog", "/readyz")):
            return _harden(RedirectResponse(url="/", status_code=303), no_store=True)
        return _harden(JSONResponse({"detail": "Authentication required"}, status_code=401), no_store=True)

    if principal.via != "token" and request.method in _UNSAFE_METHODS and not _origin_ok(request):
        logger.warning("Rejected %s %s: cross-origin cookie request", request.method, path)
        return _harden(JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403),
                       no_store=True)

    response = await call_next(request)
    for kind, payload in principal.refresh:
        if kind == "session":
            _set_session_cookie(response, payload[0], payload[1])
        elif kind == "remember":
            _set_remember_cookie(response, payload[0], payload[1])
    return _harden(response, no_store=True)


# --- login rate limiting (per ip+username, BEFORE argon2) ----------------------------
_login_limiters: dict[str, ratelimit.SlidingWindow] = {}


def _login_allowed(ip: str, username: str, *, now: float) -> bool:
    key = f"{ip}|{(username or '').lower()}"
    limiter = _login_limiters.get(key)
    if limiter is None:
        limiter = ratelimit.SlidingWindow(config.AUTH_LOGIN_MAX_PER_WINDOW, config.AUTH_LOGIN_WINDOW_SECONDS)
        _login_limiters[key] = limiter
    return limiter.allow(now)


def _reset_login_limiters() -> None:
    """Test hook."""
    _login_limiters.clear()


# Per-(user, action) limiters for the post-login state-changers (password / preferences / device), so a
# debounce burst or a script can't hammer them. Process-local (single worker — enforced by the bind guard).
_action_limiters: dict[str, ratelimit.SlidingWindow] = {}


def _action_allowed(uid: int, action: str, *, now: float) -> bool:
    max_events, window = config.AUTH_ACTION_LIMITS.get(action, (60, 60))
    key = f"{uid}:{action}"
    limiter = _action_limiters.get(key)
    if limiter is None:
        limiter = ratelimit.SlidingWindow(max_events, window)
        _action_limiters[key] = limiter
    return limiter.allow(now)


def _reset_action_limiters() -> None:
    """Test hook."""
    _action_limiters.clear()


def _require_user_session(request: Request, *, now: float) -> dict:
    """Return the authenticated USER (a real login), or raise. 401 when anonymous; **403 when the caller
    is a machine token** (token principals have no profile — they must not reach user-only endpoints)."""
    principal = _authenticate(request, now=now)
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if principal.user is None:
        raise HTTPException(status_code=403, detail="This endpoint requires a user session")
    return principal.user


def _enforce_write_guards(request: Request, uid: int, action: str, *, now: float) -> None:
    """Defense-in-depth for a cookie-authenticated state change: reject a cross-origin request (CSRF — on
    top of SameSite=Strict) and rate-limit the action per user."""
    if not _origin_ok(request):
        logger.warning("Rejected /auth %s: cross-origin", action)
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
    if not _action_allowed(uid, action, now=now):
        raise HTTPException(status_code=429, detail="Too many requests; slow down.")


# --- /auth router --------------------------------------------------------------------
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


def _public_user(user: dict) -> dict:
    return {"username": user["username"], "force_pw_change": bool(user["force_pw_change"])}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    """Authenticate and set the session cookie. Rate-limited by (ip, username) BEFORE argon2; a generic
    401 for both unknown-user and wrong-password (no enumeration), with a dummy hash spent on the
    unknown-user path so timing doesn't leak existence. Temporary lockout on repeated failures."""
    now = time.time()
    ip = request.client.host if request.client else "?"
    if not _login_allowed(ip, body.username, now=now):
        raise HTTPException(status_code=429, detail="Too many login attempts; slow down.")
    db = auth_db_path()
    user = auth_store.get_user(body.username, db_path=db)
    if user is None:
        auth_store.verify_dummy(body.password)                 # constant-time vs a real verify
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user["disabled"]:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if auth_store.is_locked(user, now=now):
        raise HTTPException(status_code=429, detail="Account temporarily locked; try again later.")
    if not auth_store.verify_password(user["pw_hash"], body.password):
        auth_store.record_login_failure(user["id"], now=now, db_path=db)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth_store.reset_login_failures(user["id"], db_path=db)
    if auth_store.needs_rehash(user["pw_hash"]):
        auth_store.set_password(body.username, body.password, now=now, clear_force=False, db_path=db)
    _set_session_cookie(response, user["id"], now)
    _maybe_remember(response, user["id"], body.remember, now=now, db=db)
    logger.info("Login ok for %r", user["username"])
    return {"ok": True, "user": _public_user(user)}


def _maybe_remember(response: Response, uid: int, remember: bool, *, now: float, db: str) -> None:
    """Issue a "remember this device" token + cookie when the user asked AND it is permitted (TLS-gated /
    AUTH_REMEMBER_ENABLED). Shared by login and register."""
    if remember and remember_available():
        selector, validator = auth_store.issue_device_token(uid, now=now, db_path=db)
        _set_remember_cookie(response, selector, validator)


class RegisterBody(BaseModel):
    username: str
    password: str
    remember: bool = False


@router.post("/register")
def register(body: RegisterBody, request: Request, response: Response) -> dict:
    """Self-service account creation (opt-in via AUTH_ALLOW_SIGNUP). Validates the username + password,
    rejects a taken username, then logs the new user straight in (sets the session cookie). Rate-limited by
    (ip, username) like login to bound mass-registration."""
    if not signup_enabled():
        raise HTTPException(status_code=403, detail="Self-registration is disabled")
    now = time.time()
    ip = request.client.host if request.client else "?"
    if not _login_allowed(ip, body.username, now=now):
        raise HTTPException(status_code=429, detail="Too many attempts; slow down.")
    name_err = auth_store.validate_username(body.username)
    if name_err:
        raise HTTPException(status_code=400, detail=name_err)
    pw_err = auth_store.validate_password_strength(body.password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)
    db = auth_db_path()
    try:
        uid = auth_store.create_user(body.username, body.password, now=now, db_path=db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_session_cookie(response, uid, now)
    _maybe_remember(response, uid, body.remember, now=now, db=db)
    logger.info("Registered new user %r", body.username)
    return {"ok": True, "user": {"username": body.username.strip(), "force_pw_change": False}}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    """Clear the session, revoke this device's remember-me token (server-side state, not just the browser
    cookie), and clear both cookies. Origin-checked (CSRF defense-in-depth)."""
    now = time.time()
    if not _origin_ok(request):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
    raw = request.cookies.get(config.AUTH_REMEMBER_COOKIE_NAME)
    if raw and ":" in raw:
        auth_store.revoke_device_by_selector(raw.partition(":")[0], now=now, db_path=auth_db_path())
    _clear_cookie(response, config.AUTH_COOKIE_NAME)
    _clear_cookie(response, config.AUTH_REMEMBER_COOKIE_NAME)
    return {"ok": True}


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordChangeBody, request: Request, response: Response) -> dict:
    """Self-service password change (the ``force_pw_change`` path). Requires the current session + the
    current password; rejects a weak new password. ``set_password`` bumps ``session_epoch`` (logging every
    OTHER device out), so we re-issue THIS session's cookie with a fresh ``iat`` to keep the caller logged
    in."""
    now = time.time()
    user = _require_user_session(request, now=now)
    _enforce_write_guards(request, user["id"], "password", now=now)
    if not auth_store.verify_password(user["pw_hash"], body.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    err = auth_store.validate_password_strength(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db = auth_db_path()
    auth_store.set_password(user["username"], body.new_password, now=now, db_path=db)
    _set_session_cookie(response, user["id"], now)             # keep the current device logged in
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    """Current user, or 401 when anonymous. The SPA calls this on boot to decide login-vs-app."""
    now = time.time()
    principal = _authenticate(request, now=now)
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if principal.user is None:
        return {"user": {"username": "(machine token)", "force_pw_change": False}}
    return {"user": _public_user(principal.user)}


@router.get("/config")
def auth_config() -> dict:
    """Public auth config the login view needs (no secrets): whether auth is on, whether the remember-me
    checkbox should be offered, and whether self-registration is open."""
    return {"auth_enabled": auth_enabled(), "remember_available": remember_available(),
            "signup_enabled": signup_enabled()}


@router.get("/devices")
def list_devices(request: Request) -> dict:
    user = _require_user_session(request, now=time.time())
    return {"devices": auth_store.list_device_tokens(user["id"], db_path=auth_db_path())}


@router.post("/devices/{token_id}/revoke")
def revoke_device(token_id: int, request: Request) -> dict:
    now = time.time()
    user = _require_user_session(request, now=now)
    _enforce_write_guards(request, user["id"], "device", now=now)
    # user_id is the AUTHENTICATED user's — the store only revokes a token that belongs to them, so a
    # token_id owned by another user is a silent no-op (cross-user isolation).
    auth_store.revoke_device_token(token_id, now=now, user_id=user["id"], db_path=auth_db_path())
    return {"ok": True}


# --- per-user preferences (session-only; uid is ALWAYS the authenticated user, never client-supplied) ---
class PreferencesBody(BaseModel):
    prefs: dict


@router.get("/preferences")
def get_preferences(request: Request) -> dict:
    """The CURRENT user's saved preferences envelope ({} if none). Identity is the session — there is no
    user_id param, so a user can only ever read their own."""
    user = _require_user_session(request, now=time.time())
    return {"prefs": auth_store.get_preferences(user["id"], db_path=auth_db_path())}


@router.put("/preferences")
def put_preferences(body: PreferencesBody, request: Request) -> dict:
    """Replace the CURRENT user's preferences. Server-sanitizes into a versioned envelope (unknown keys
    dropped, enums/types checked) and size-caps it; 400 on a non-object or over-cap blob. Origin-checked +
    rate-limited."""
    now = time.time()
    user = _require_user_session(request, now=now)
    _enforce_write_guards(request, user["id"], "preferences", now=now)
    try:
        stored = auth_store.set_preferences(user["id"], body.prefs, now=now, db_path=auth_db_path())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "prefs": stored}
