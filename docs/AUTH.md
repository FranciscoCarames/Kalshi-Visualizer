# Authentication & hardening

Per-user authentication for the Kalshi Structured Scanner, for a **loopback + trusted-LAN** deployment.
The app is read-only over public Kalshi data; auth exists to keep the data surface and scan controls
private once the app leaves `127.0.0.1`, and to give a per-user identity for future per-user features.

Everything is **gated behind `AUTH_ENABLED`**. **`python serve.py` turns it ON by default** (and turns
self-registration on) — see *Secure defaults* below. The gate itself reads the env per request: unset →
open (legacy `SCAN_TOKEN`-only behaviour, used by the test suite); `1` → deny-by-default, login required.

## Secure defaults & the supported entrypoint

`serve.py` calls `apply_runtime_defaults()` at startup, which `setdefault`s **`AUTH_ENABLED=1`** and
**`AUTH_ALLOW_SIGNUP=1`**. So a plain `python serve.py` is auth-on with open self-registration; an operator
opts out with `AUTH_ENABLED=0` / `AUTH_ALLOW_SIGNUP=0`.

These defaults are applied in the `serve.py` entrypoint only (NOT at module import, which would gate the
test suite). **`python serve.py` is therefore the supported secure entrypoint** — exactly like the
fail-closed bind guard, which also only protects `serve.py`. Running `uvicorn api:app` directly bypasses
both; if you must, set `AUTH_ENABLED=1` yourself.

## Account creation

- **Self-registration (default ON):** the login screen shows a "create one" link; `POST /auth/register`
  validates the username (3–32 chars, `[A-Za-z0-9._-]`), rejects a taken name, and logs the new user
  straight in. Rate-limited by (IP, username) like login. The **only** way to access an account's data is
  its username + password.
- **Password policy (owner decision, 2026-06-17):** there is **NO strength floor** — any non-empty
  password is accepted (subject only to a max-length DoS cap, `AUTH_MAX_CRED_LEN`). The former 10-char
  minimum and common-password blocklist were removed. This is a **deliberate downgrade for a read-only,
  trusted-LAN deployment behind WireGuard** — it is NOT appropriate for an internet-facing install. Keep
  the app off the public internet, and prefer `AUTH_ALLOW_SIGNUP=0` (admin-created accounts only) if weak
  user-chosen passwords are a concern. Passwords are still hashed with argon2id.
- **Admin-created:** `python -m manage_users add <username>` (see Operations). Use this and set
  `AUTH_ALLOW_SIGNUP=0` if you want a closed set of accounts.
- **Trade-offs to know (trusted-LAN model):** open registration means anyone who can reach the host can
  create an account and view the (read-only) data / trigger scans (rate-limited); and a duplicate-name
  registration returns `409`, so registration reveals whether a username is taken. Login itself stays
  non-enumerable (a generic 401). Acceptable on a trusted LAN; close signup if that's not your network.

## Per-user preferences (profiles)

Each account has a private profile — **theme, settings, shown/ordered columns, band thresholds, the
bounded-loss split, and the chosen layout preset** — saved server-side in `auth.db` and restored on login,
so a user's setup follows their account across devices. (Transient *filters* are deliberately NOT saved —
a shared/debug URL must never silently persist a narrowed dashboard.)

- **Endpoints:** `GET`/`PUT /auth/preferences`, session-only. Identity is the session cookie — there is
  **no `user_id` parameter anywhere**, so a user can only ever read/write their own row. Isolation is
  proven by `tests/test_security_regression.py` (two users) + a route-introspection test.
- **Validation:** the server sanitizes a *versioned envelope* (unknown keys dropped, enums/types checked)
  and size-caps the blob (`AUTH_PREFS_MAX_BYTES`, 32 KiB). A corrupt row degrades to `{}` (logged without
  content), never a 500. The client also allow-lists on apply.
- **Sensitivity:** preferences are *user-private app data* (which columns/filters/layout you favour can
  hint at what you watch), not secret financial records. They are protected by auth isolation + the
  `auth.db` file, and are excluded from the ZIP export (which only packages snapshot market data).
- **Multi-tab:** whole-profile writes are last-write-wins (no merge); fine for a personal dashboard. A
  failed save is swallowed (logged), never blocking the dashboard.

## Threat model

- **In scope:** a trusted home/LAN where you want to keep casual/other-device access out, and avoid
  leaking ops data / scan triggers to anyone who can reach the host.
- **Out of scope:** the public internet, guest/office/shared Wi-Fi, a determined attacker with LAN packet
  capture **and** no TLS. The session cookie travels in cleartext until TLS is on — so a non-loopback bind
  **fails closed** without TLS (see below).
- The protected asset is the **data**, not the public JS bundle. The SPA shell + `/healthz` stay open;
  the login screen loads, then everything else requires a session or a machine token.

## Route inventory (gated vs. open)

Gating is a single **deny-by-default** HTTP middleware (`auth.gate_and_harden`); `is_public()` is the only
allowlist. `tests/test_routes_deny_by_default.py` fails if a new route lands under a public prefix.

| Surface | Access |
|---|---|
| `GET /healthz`, `GET /favicon.ico` | **public** (minimal liveness / icon) |
| static SPA bundle: `/`, `/index.html`, `/terminal/*`, `/assets/*`, `/static/*` | **public** (HTML/JS/CSS — no data/secrets; the login screen loads from here) |
| `POST /auth/login`, `POST /auth/register`, `GET /auth/config` | **public** (the entry points) |
| `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`, `GET/PUT /auth/preferences`, `GET /auth/devices`, `POST /auth/devices/{id}/revoke` | **gate-exempt but session-required** (enforce their own auth; user-only → machine token gets 403) |
| `/opportunities(/{id})`, `/coverage`, `/metrics`, `/readyz`, `/scan`, `/scan/status`, `/alerts`, `/backlog(/events)` | **gated** (session or machine token) |
| all `/api/terminal/*` — `feed`, `detail`, `payoff`, `ladder`, `diagnostics`, `telemetry`, `orderbook`, **`export` (ZIP)** | **gated** |
| the NiceGUI `/dashboard*` mount | **gated** (anon HTML nav → redirect to `/`) — unless `DASHBOARD_PUBLIC=1` (transition escape hatch, see env-var table) makes it **public** |
| `/docs`, `/redoc`, `/openapi.json` | **disabled** when `AUTH_ENABLED` & not `APP_DEV=1` |

**Machine token** (`X-API-Token`) reaches the *data* routes but is **403** on the user-only `/auth/*`
profile/credential endpoints (it has no user identity). State-changing browser requests (`/scan`, the
`/auth/*` writes) are additionally **Origin-checked** (CSRF defense-in-depth on top of `SameSite=Strict`);
a token call skips the Origin check (no ambient cookie to abuse).

## Sessions, revocation, and remember-me

- **Session cookie** (`kss_session`): signed with `itsdangerous` (NOT Starlette `SessionMiddleware`, which
  would collide with NiceGUI's). `httponly`, `SameSite=Strict`, `Secure` when `APP_TLS=1`. Idle window 12h
  (slides on each request), absolute cap 12h.
- **Real revocation:** every gated request reloads the user row. Disabling a user or changing a password
  bumps `session_epoch`, which **immediately invalidates** all of that user's existing cookies and
  remember-me tokens.
- **Remember-me** (`kss_remember`, opt-in): a DB-backed **rotating** token (OWASP selector+validator).
  Single-use — each automatic re-login rotates it; a replay of an old copy (selector matches, validator
  doesn't) **revokes the whole family** (theft signal). Issued **only when the cookie can be `Secure`**
  (TLS) — on plain HTTP it falls back to the 12h session unless `AUTH_REMEMBER_ENABLED=1` is set knowingly.
  Manage from the SPA "trusted devices" panel.
- **Machine token** for scripts/automation: send `X-API-Token: <APP_API_TOKEN>` (the legacy `SCAN_TOKEN`
  is still honored). Constant-time compare; no ambient cookie, so it is CSRF-immune and skips the Origin
  check.

## Login defenses

- Generic `401 "Invalid username or password"` for both unknown-user and wrong-password (no enumeration),
  with a dummy argon2 verify on the unknown-user path so response timing doesn't leak existence.
- Login rate-limited by **(IP, username)** *before* the expensive argon2 verify; a temporary 15-minute
  lockout after repeated failures (clear early with `python -m manage_users unlock <name>`).
- Passwords hashed with **argon2id** (OWASP-minimum params, pinned in `config.py`), re-hashed
  opportunistically on login when the params change. Inputs capped at 256 chars before hashing.

## CSRF

`SameSite=Strict` means a forged cross-site request arrives **without** the session cookie → the gate
returns 401. As defense-in-depth, cookie-authenticated state-changing requests (`POST /scan`,
`/api/terminal/export`, `/auth/logout`) also require the `Origin`/`Referer` host to match. A full
CSRF-token system is **not** used (unnecessary for same-origin + SameSite=Strict). **Contingency:** if the
SPA is ever served cross-origin, add `CORSMiddleware` with an explicit allowlist (`allow_credentials=True`,
never `*`) + a double-submit token and downgrade to `SameSite=Lax`. Do not enable CORS until needed.

## Deployment (fail-closed)

`serve.py`'s bind guard refuses to start (`SystemExit(2)`) on a **non-loopback** bind when `AUTH_ENABLED`
unless ALL of:

1. a real `APP_SESSION_SECRET` (or `NICEGUI_STORAGE_SECRET`) — not the public dev fallback;
2. at least one user account exists;
3. TLS is on (`APP_TLS=1`) **or** a trusted HTTPS-terminating proxy is declared (`TRUST_PROXY=1`).

Multi-worker (`WEB_CONCURRENCY>1` / `--workers`) is **fatal** in auth mode — the snapshot store, Kalshi
throttle, and login rate-limiter are process-local and would fragment. Run a single worker.

### TLS

- Direct: `uvicorn` with `--ssl-keyfile`/`--ssl-certfile` (a self-signed cert is fine on a LAN) and set
  `APP_TLS=1` so the cookie is `Secure`.
- Or terminate TLS at a reverse proxy (e.g. Caddy with automatic HTTPS) and set `TRUST_PROXY=1`.
- Until TLS is on, **the LAN session cookie travels in cleartext** — only acceptable on a genuinely
  trusted network.

## Operations

```bash
# Create / manage users (passwords are prompted, never echoed/logged):
python -m manage_users add <username> [--force-pw-change]
python -m manage_users passwd <username>
python -m manage_users list
python -m manage_users disable <username>     # revokes live sessions + device tokens
python -m manage_users enable <username>
python -m manage_users unlock <username>      # clear a brute-force lockout

# First-admin bootstrap (one-shot, only when zero users exist; never overwrites). No strength floor is
# enforced (owner policy) — still choose a long passphrase for an admin account:
export APP_ADMIN_USER=admin APP_ADMIN_PASSWORD='a-long-passphrase'
python serve.py
```

- **Credential + profile isolation:** users, device tokens, and preferences live in their OWN SQLite file
  (`AUTH_DB_PATH`, default `auth.db`), separate from the snapshot store (which self-resets on a bad
  migration). Its migration **fails hard** rather than ever dropping a table, and deleting a user cascades
  to their tokens + preferences (`PRAGMA foreign_keys=ON`).
- **Backups & permissions:** `auth.db` is gitignored and excluded from the ZIP export. Back it up
  separately (it holds the only copy of accounts + profiles); restrict its file permissions to the service
  user; a corrupt prefs row degrades to defaults rather than failing login.
- **Dependencies (advisory sweep):** `pip-audit` (dependency CVEs) + `bandit -r . -x tests,frontend`
  (static analysis) are in `requirements-dev.txt`; run them periodically. The deploy artifact pins via
  `pip-compile`, the frontend via `package-lock.json`.

## Environment variables (read only at boundaries)

| Var | Purpose |
|---|---|
| `AUTH_ENABLED` | turn the gate + login on; **`python serve.py` defaults it to `1`** (set `0` to opt out) |
| `AUTH_ALLOW_SIGNUP` | allow self-registration (`POST /auth/register` + a "create account" link); **`python serve.py` defaults it to `1`** (set `0` for admin-created accounts only) |
| `APP_SESSION_SECRET` | session cookie signing key (falls back to `NICEGUI_STORAGE_SECRET`, then a public dev fallback) |
| `AUTH_DB_PATH` | auth store path (default `auth.db`) |
| `APP_ADMIN_USER` / `APP_ADMIN_PASSWORD` | one-shot first-admin seed |
| `APP_API_TOKEN` | machine token for scripted access (`X-API-Token`); legacy `SCAN_TOKEN` still honored |
| `AUTH_REMEMBER_ENABLED=1` | allow remember-me without TLS (knowingly-trusted LAN) |
| `APP_TLS=1` | mark the cookie `Secure`; satisfies the fail-closed TLS requirement |
| `TRUST_PROXY=1` | declare an HTTPS-terminating reverse proxy (satisfies the TLS requirement) |
| `APP_ALLOWED_HOSTS` | comma-separated Host allowlist for `TrustedHostMiddleware` (default `*`) |
| `APP_DEV=1` | re-enable `/docs` `/redoc` `/openapi.json` in an auth-on deployment |
| `DASHBOARD_PUBLIC=1` | **transition escape hatch** — serve the legacy NiceGUI `/dashboard/` mount WITHOUT auth even while `AUTH_ENABLED`, so users hitting `…/dashboard/` get the old engine view login-free while the SPA at `/` keeps its login + per-user settings. Off by default. ⚠️ the dashboard reads the snapshot store in-process, so this exposes the same read-only engine data unauthenticated — a deliberate bypass, remove once the NiceGUI→SPA migration is done |
| `AUTH_PREFS_MAX_BYTES` | cap on a stored preferences blob (default 32 KiB; in `config.py`) |
