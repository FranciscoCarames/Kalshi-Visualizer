# Authentication & hardening

Per-user authentication for the Kalshi Structured Scanner, for a **loopback + trusted-LAN** deployment.
The app is read-only over public Kalshi data; auth exists to keep the data surface and scan controls
private once the app leaves `127.0.0.1`, and to give a per-user identity for future per-user features.

Everything is **gated behind `AUTH_ENABLED`** (env). Unset → the app behaves exactly as before (open,
with the legacy optional `SCAN_TOKEN` gate on `POST /scan`). Set to `1` → the deny-by-default gate is
live and a login is required.

## Account creation

Two paths:

- **Admin-created (default, safest):** `python -m manage_users add <username>` (see Operations below).
  Self-registration stays off, so only an admin makes accounts.
- **Self-registration (opt-in):** set `AUTH_ALLOW_SIGNUP=1`. The login screen then shows a "create one"
  link; `POST /auth/register` validates the username (3–32 chars, `[A-Za-z0-9._-]`) + password strength,
  rejects a taken name, and logs the new user straight in. It is rate-limited by (IP, username) like
  login. **Trade-off:** anyone who can reach the app can then create an account and view the data /
  trigger scans (rate-limited) — only enable it on a trusted network.

## Threat model

- **In scope:** a trusted home/LAN where you want to keep casual/other-device access out, and avoid
  leaking ops data / scan triggers to anyone who can reach the host.
- **Out of scope:** the public internet, guest/office/shared Wi-Fi, a determined attacker with LAN packet
  capture **and** no TLS. The session cookie travels in cleartext until TLS is on — so a non-loopback bind
  **fails closed** without TLS (see below).
- The protected asset is the **data**, not the public JS bundle. The SPA shell + `/healthz` stay open;
  the login screen loads, then everything else requires a session or a machine token.

## What is gated vs. open

| Open | Gated (session or machine token) |
|---|---|
| `GET /healthz`, `GET /favicon.ico` | `/opportunities`, `/coverage`, `/metrics`, `/readyz`, `/scan`, `/scan/status`, `/alerts`, `/backlog(/events)` |
| `POST /auth/login`, `/auth/logout`, `GET /auth/me`, `GET /auth/config` | all `/api/terminal/*` (feed, detail, payoff, ladder, diagnostics, telemetry, orderbook, export) |
| static SPA bundle: `/`, `/index.html`, `/terminal/*`, `/assets/*` | the NiceGUI `/dashboard*` mount (anon → redirect to `/`) |
| `/auth/password`, `/auth/devices*` (enforce their own auth internally) | `/docs`, `/redoc`, `/openapi.json` are **disabled** in prod unless `APP_DEV=1` |

Gating is a single deny-by-default HTTP middleware (`auth.gate_and_harden`). `tests/test_routes_deny_by_default.py`
fails if a new route lands under a public prefix by accident.

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

# First-admin bootstrap (one-shot, only when zero users exist; never overwrites; rejects weak passwords):
export APP_ADMIN_USER=admin APP_ADMIN_PASSWORD='a-long-passphrase'
python serve.py
```

- **Credential isolation:** users live in their OWN SQLite file (`AUTH_DB_PATH`, default `auth.db`),
  separate from the snapshot store (which self-resets on a bad migration). `auth.db` is gitignored; back it
  up separately. Its migration **fails hard** rather than ever dropping the users table.
- **Dependencies:** run `pip-audit` periodically; the deploy artifact pins via `pip-compile`, the frontend
  via `package-lock.json`.

## Environment variables (read only at boundaries)

| Var | Purpose |
|---|---|
| `AUTH_ENABLED=1` | turn the gate + login on (default off) |
| `AUTH_ALLOW_SIGNUP=1` | allow self-registration (`POST /auth/register` + a "create account" link); default off (admin-created accounts only) |
| `APP_SESSION_SECRET` | session cookie signing key (falls back to `NICEGUI_STORAGE_SECRET`, then a public dev fallback) |
| `AUTH_DB_PATH` | auth store path (default `auth.db`) |
| `APP_ADMIN_USER` / `APP_ADMIN_PASSWORD` | one-shot first-admin seed |
| `APP_API_TOKEN` | machine token for scripted access (`X-API-Token`); legacy `SCAN_TOKEN` still honored |
| `AUTH_REMEMBER_ENABLED=1` | allow remember-me without TLS (knowingly-trusted LAN) |
| `APP_TLS=1` | mark the cookie `Secure`; satisfies the fail-closed TLS requirement |
| `TRUST_PROXY=1` | declare an HTTPS-terminating reverse proxy (satisfies the TLS requirement) |
| `APP_ALLOWED_HOSTS` | comma-separated Host allowlist for `TrustedHostMiddleware` (default `*`) |
| `APP_DEV=1` | re-enable `/docs` `/redoc` `/openapi.json` in an auth-on deployment |
