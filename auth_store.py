"""Per-user authentication store — the credential backbone (separate from the snapshot store).

UI-agnostic, single-writer local SQLite holding ONE thing snapshot history never should: user accounts
and their "remember this device" tokens. Pure standard library + ``argon2-cffi`` (password hashing) and
``hmac`` (constant-time token compare) — NO nicegui / fastapi / pandas import, so it unit-tests against a
tmp file.

Two deliberate departures from ``store.py`` (security-critical — do not "harmonize" them away):

1. **Its OWN SQLite file** (``config.AUTH_DB_PATH``, env-overridable at the serve.py/manage_users.py
   boundary), NEVER the snapshot DB. ``store._reset_to_fresh`` DROPs every snapshot table on a bad
   migration and retention ages rows out; credentials must live where neither can reach them.
2. **The migration FAILS HARD.** Where ``store._migrate`` falls back to a fresh DB on a malformed file,
   here a corrupt/newer file RAISES — we never silently drop the users table. A backup-and-reset that
   loses every account is far worse than a loud startup failure.

Time is INJECTED (every mutator/checker takes ``now`` epoch seconds) so lockout/expiry/rotation logic is
deterministic in tests — there is no internal ``time.time()`` call.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3

import argon2
from argon2.exceptions import VerifyMismatchError

import config

_log = logging.getLogger(__name__)

# Bump when the on-disk auth schema changes; held in the SQLite `user_version` pragma (no bookkeeping
# table). v1 is the initial schema (users + device_tokens). Unlike the snapshot store, a forward-migration
# failure RAISES rather than resetting — credentials are never silently dropped.
AUTH_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash         TEXT NOT NULL,
    created_ts      REAL NOT NULL,
    disabled        INTEGER NOT NULL DEFAULT 0,
    disabled_ts     REAL,
    pw_changed_ts   REAL,
    session_epoch   REAL NOT NULL DEFAULT 0,   -- sessions/tokens issued before this are invalid (revocation)
    failed_count    INTEGER NOT NULL DEFAULT 0,
    locked_until    REAL,
    force_pw_change INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS device_tokens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    selector       TEXT NOT NULL UNIQUE,        -- public lookup half (NOT secret)
    validator_hash TEXT NOT NULL,               -- sha256 of the secret half (high-entropy → fast hash ok)
    created_ts     REAL NOT NULL,
    expires_ts     REAL NOT NULL,
    last_used_ts   REAL,
    label          TEXT,
    revoked_ts     REAL
);
CREATE INDEX IF NOT EXISTS ix_device_tokens_user ON device_tokens(user_id);
"""


# A module-level hasher is fine: PasswordHasher is stateless+thread-safe and just carries the params.
def _hasher() -> argon2.PasswordHasher:
    return argon2.PasswordHasher(
        time_cost=config.AUTH_ARGON2_TIME_COST,
        memory_cost=config.AUTH_ARGON2_MEMORY_COST,
        parallelism=config.AUTH_ARGON2_PARALLELISM,
    )


# A precomputed hash of a throwaway password, used to spend ~the same CPU verifying a NON-existent user as
# a real one — so login response time doesn't leak whether a username exists (timing enumeration).
_DUMMY_HASH = _hasher().hash("dummy-password-for-constant-time-verify")


# --- password policy (single-sourced — CLI seed, env seed, and self-service change all use this) -----
# A small floor, NOT a strength meter: reject obviously-weak/default passwords so a seeded admin is never
# "admin"/"password". Real strength is the operator's responsibility (documented in docs/AUTH.md).
_WEAK_PASSWORDS = {"password", "admin", "administrator", "changeme", "letmein", "kalshi",
                   "12345678", "secret", "passw0rd"}
PASSWORD_MIN_LEN = 10


def validate_password_strength(password: str) -> str | None:
    """Return an error string for an obviously-weak password, else None."""
    if len(password) < PASSWORD_MIN_LEN:
        return f"password must be at least {PASSWORD_MIN_LEN} characters"
    if len(password) > config.AUTH_MAX_CRED_LEN:
        return f"password must be at most {config.AUTH_MAX_CRED_LEN} characters"
    if password.lower() in _WEAK_PASSWORDS:
        return "password is too common; choose something less guessable"
    return None


# Usernames are constrained to a safe, unambiguous charset (used by self-registration; the admin CLI is
# trusted and only length/blank-checked). Keeps display/URLs/logs clean and avoids confusable whitespace.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def validate_username(username: str) -> str | None:
    """Return an error string for an invalid username, else None."""
    if not _USERNAME_RE.match(username or ""):
        return "username must be 3-32 characters: letters, digits, '.', '_' or '-'"
    return None


# --- password hashing (argon2id) -----------------------------------------------------
def _check_cred_len(value: str, what: str) -> None:
    """Reject an over-long credential BEFORE it reaches argon2 (a megabyte password would burn CPU/RAM —
    a cheap DoS). The cap is generous for any real passphrase."""
    if len(value) > config.AUTH_MAX_CRED_LEN:
        raise ValueError(f"{what} exceeds {config.AUTH_MAX_CRED_LEN} characters")


def hash_password(password: str) -> str:
    """Hash a password with argon2id (pinned params). Never logs the password."""
    _check_cred_len(password, "password")
    return _hasher().hash(password)


def verify_password(pw_hash: str, password: str) -> bool:
    """Constant-time-ish argon2 verify. Returns False on mismatch (never raises for a wrong password) and
    NEVER logs the password. An over-long input is rejected as a non-match (it can't be a stored hash)."""
    if len(password) > config.AUTH_MAX_CRED_LEN:
        return False
    try:
        return _hasher().verify(pw_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — a malformed stored hash is a non-match, never an error to the caller
        return False


def verify_dummy(password: str) -> None:
    """Spend argon2 CPU against a dummy hash for an unknown user, so timing doesn't reveal user existence.
    Result is discarded."""
    try:
        _hasher().verify(_DUMMY_HASH, password[: config.AUTH_MAX_CRED_LEN])
    except Exception:  # noqa: BLE001 — always mismatches; we only want the work
        pass


def needs_rehash(pw_hash: str) -> bool:
    """True when a stored hash was made with weaker params than the current pins (upgrade opportunistically
    on the next successful login)."""
    try:
        return _hasher().check_needs_rehash(pw_hash)
    except Exception:  # noqa: BLE001
        return False


# --- connection / migration ----------------------------------------------------------
def _db_path(db_path: str | None) -> str:
    return db_path or config.AUTH_DB_PATH


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the file to AUTH_SCHEMA_VERSION. A fresh (user_version 0) file is created at the current
    version. A newer-than-supported file is a hard error (never downgrade-write). Unlike the snapshot
    store, a malformed/older file that fails to migrate forward RAISES — we NEVER reset/drop the users
    table, because losing every credential silently is unacceptable."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == AUTH_SCHEMA_VERSION:
        return
    if version > AUTH_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"auth DB schema v{version} is newer than supported v{AUTH_SCHEMA_VERSION}")
    if version == 0:
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {AUTH_SCHEMA_VERSION}")
        conn.commit()
        return
    # Future forward steps (v1->v2, ...) go here, each wrapped so a failure RAISES (no reset fallback).
    raise sqlite3.DatabaseError(
        f"auth DB schema v{version} cannot be migrated to v{AUTH_SCHEMA_VERSION}; refusing to continue "
        "(credentials are never auto-reset). Restore a backup or migrate manually.")


# --- user CRUD -----------------------------------------------------------------------
def create_user(username: str, password: str, *, now: float, force_pw_change: bool = False,
                db_path: str | None = None) -> int:
    """Create a user; returns the new id. Raises ValueError on a duplicate username (NOCASE) or a blank/
    over-long credential. Never logs the password."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be blank")
    _check_cred_len(username, "username")
    if not password:
        raise ValueError("password must not be blank")
    pw_hash = hash_password(password)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pw_hash, created_ts, pw_changed_ts, force_pw_change) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, pw_hash, now, now, 1 if force_pw_change else 0))
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"username {username!r} already exists") from exc
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def get_user(username: str, db_path: str | None = None) -> dict | None:
    """Look up by username (case-insensitive). None if absent."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                           ((username or "").strip(),)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_user_by_id(user_id: int, db_path: str | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_users(db_path: str | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE")]
    finally:
        conn.close()


def user_count(db_path: str | None = None) -> int:
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    finally:
        conn.close()


def set_password(username: str, password: str, *, now: float, clear_force: bool = True,
                 db_path: str | None = None) -> None:
    """Change a password. Bumps ``session_epoch`` (invalidating every live cookie + remember token for the
    user) and revokes all device tokens — a password change logs every other device out. Never logs the
    password."""
    if not password:
        raise ValueError("password must not be blank")
    pw_hash = hash_password(password)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                           ((username or "").strip(),)).fetchone()
        if row is None:
            raise ValueError(f"no such user: {username!r}")
        uid = row["id"]
        conn.execute(
            "UPDATE users SET pw_hash = ?, pw_changed_ts = ?, session_epoch = ?, failed_count = 0, "
            "locked_until = NULL, force_pw_change = ? WHERE id = ?",
            (pw_hash, now, now, 0 if clear_force else 1, uid))
        _revoke_all_device_tokens(conn, uid, now)
        conn.commit()
    finally:
        conn.close()


def set_disabled(username: str, disabled: bool, *, now: float, db_path: str | None = None) -> None:
    """Enable/disable an account. Disabling bumps ``session_epoch`` and revokes device tokens, so an
    existing cookie stops working on its next request (real revocation)."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                           ((username or "").strip(),)).fetchone()
        if row is None:
            raise ValueError(f"no such user: {username!r}")
        uid = row["id"]
        if disabled:
            conn.execute("UPDATE users SET disabled = 1, disabled_ts = ?, session_epoch = ? WHERE id = ?",
                         (now, now, uid))
            _revoke_all_device_tokens(conn, uid, now)
        else:
            conn.execute("UPDATE users SET disabled = 0, disabled_ts = NULL, failed_count = 0, "
                         "locked_until = NULL WHERE id = ?", (uid,))
        conn.commit()
    finally:
        conn.close()


# --- lockout (brute-force defense) ---------------------------------------------------
def is_locked(user: dict, *, now: float) -> bool:
    """True when the account is in a temporary lockout window."""
    locked_until = user.get("locked_until")
    return locked_until is not None and now < locked_until


def record_login_failure(user_id: int, *, now: float, db_path: str | None = None) -> None:
    """Increment the failure counter; trip a temporary lockout once it reaches the threshold."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT failed_count FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return
        failed = int(row["failed_count"]) + 1
        locked_until = now + config.AUTH_LOCKOUT_SECONDS if failed >= config.AUTH_LOCKOUT_THRESHOLD else None
        conn.execute("UPDATE users SET failed_count = ?, locked_until = ? WHERE id = ?",
                     (failed, locked_until, user_id))
        conn.commit()
    finally:
        conn.close()


def reset_login_failures(user_id: int, db_path: str | None = None) -> None:
    """Clear the failure counter + lockout after a successful login."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE users SET failed_count = 0, locked_until = NULL WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def unlock(username: str, db_path: str | None = None) -> None:
    """Admin recovery: clear a lockout (and failure count) so a locked-out user can try again — the
    counter to the lockout-as-DoS risk (an attacker can't permanently brick an account)."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE users SET failed_count = 0, locked_until = NULL "
                     "WHERE username = ? COLLATE NOCASE", ((username or "").strip(),))
        conn.commit()
    finally:
        conn.close()


# --- remember-me device tokens (OWASP selector+validator, rotating) ------------------
def _hash_validator(validator: str) -> str:
    """The validator is a 256-bit random secret, so a fast hash (sha256) is sufficient — no need for a slow
    password hash. Storing the hash means a DB read never exposes a usable token."""
    return hashlib.sha256(validator.encode("utf-8")).hexdigest()


def issue_device_token(user_id: int, *, now: float, label: str | None = None,
                       db_path: str | None = None) -> tuple[str, str]:
    """Mint a remember-me token for a device. Returns ``(selector, validator)`` — the RAW validator is
    returned ONCE (only its hash is stored) and goes into the user's cookie as ``selector:validator``."""
    selector = secrets.token_urlsafe(12)
    validator = secrets.token_urlsafe(32)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO device_tokens (user_id, selector, validator_hash, created_ts, expires_ts, label) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, selector, _hash_validator(validator), now, now + config.AUTH_REMEMBER_MAX_AGE, label))
        conn.commit()
        return selector, validator
    finally:
        conn.close()


def consume_device_token(selector: str, validator: str, *, now: float,
                         db_path: str | None = None) -> tuple[dict | None, tuple[str, str] | None]:
    """Validate a remember-me cookie and ROTATE it (single-use). Returns ``(user, new_token)`` where
    ``new_token`` is the fresh ``(selector, validator)`` to re-set in the cookie, or ``(None, None)`` on any
    failure (unknown/expired/revoked/disabled/epoch-stale).

    Theft detection: a KNOWN selector with a WRONG validator means an old/stolen copy was replayed — we
    revoke ALL of that user's tokens and refuse (forces a fresh password login everywhere)."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM device_tokens WHERE selector = ?", (selector,)).fetchone()
        if row is None:
            return None, None
        if not hmac.compare_digest(row["validator_hash"], _hash_validator(validator)):
            _revoke_all_device_tokens(conn, row["user_id"], now)   # replay/theft → nuke the family
            conn.commit()
            return None, None
        if row["revoked_ts"] is not None or now >= row["expires_ts"]:
            return None, None
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user is None or user["disabled"] or row["created_ts"] < user["session_epoch"]:
            return None, None
        # Rotate: revoke this token, mint a replacement (keep the label/expiry window fresh).
        conn.execute("UPDATE device_tokens SET revoked_ts = ?, last_used_ts = ? WHERE id = ?",
                     (now, now, row["id"]))
        new_selector = secrets.token_urlsafe(12)
        new_validator = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO device_tokens (user_id, selector, validator_hash, created_ts, expires_ts, label) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["user_id"], new_selector, _hash_validator(new_validator), now,
             now + config.AUTH_REMEMBER_MAX_AGE, row["label"]))
        conn.commit()
        return dict(user), (new_selector, new_validator)
    finally:
        conn.close()


def revoke_device_token(token_id: int, *, now: float, user_id: int | None = None,
                        db_path: str | None = None) -> None:
    """Revoke one device token. When ``user_id`` is given, only revoke if it belongs to that user (so a
    user can't revoke another user's device)."""
    conn = _connect(db_path)
    try:
        if user_id is None:
            conn.execute("UPDATE device_tokens SET revoked_ts = ? WHERE id = ? AND revoked_ts IS NULL",
                         (now, token_id))
        else:
            conn.execute("UPDATE device_tokens SET revoked_ts = ? WHERE id = ? AND user_id = ? "
                         "AND revoked_ts IS NULL", (now, token_id, user_id))
        conn.commit()
    finally:
        conn.close()


def revoke_device_by_selector(selector: str, *, now: float, db_path: str | None = None) -> None:
    """Revoke a single device token by its public selector (used by logout — clears THIS device only,
    without the theft-revoke-all semantics of a bad-validator ``consume``)."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE device_tokens SET revoked_ts = ? WHERE selector = ? AND revoked_ts IS NULL",
                     (now, selector))
        conn.commit()
    finally:
        conn.close()


def _revoke_all_device_tokens(conn: sqlite3.Connection, user_id: int, now: float) -> None:
    conn.execute("UPDATE device_tokens SET revoked_ts = ? WHERE user_id = ? AND revoked_ts IS NULL",
                 (now, user_id))


def revoke_all_device_tokens(user_id: int, *, now: float, db_path: str | None = None) -> None:
    """Revoke every active device token for a user ("sign out everywhere")."""
    conn = _connect(db_path)
    try:
        _revoke_all_device_tokens(conn, user_id, now)
        conn.commit()
    finally:
        conn.close()


def list_device_tokens(user_id: int, *, active_only: bool = True,
                       db_path: str | None = None) -> list[dict]:
    """List a user's device tokens (active by default) for the "trusted devices" panel. Never returns the
    validator (only its hash is stored)."""
    conn = _connect(db_path)
    try:
        sql = "SELECT id, label, created_ts, expires_ts, last_used_ts, revoked_ts FROM device_tokens " \
              "WHERE user_id = ?"
        if active_only:
            sql += " AND revoked_ts IS NULL"
        sql += " ORDER BY created_ts DESC"
        return [dict(r) for r in conn.execute(sql, (user_id,))]
    finally:
        conn.close()


def purge_expired(*, now: float, db_path: str | None = None) -> int:
    """Delete expired/revoked tokens (housekeeping). Returns the number removed."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM device_tokens WHERE expires_ts < ? OR revoked_ts IS NOT NULL",
                           (now,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
