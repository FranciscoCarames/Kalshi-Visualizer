"""Unit tests for the per-user auth store (auth_store.py). Run against a tmp file — no network, no shared
state. Covers schema migration/versioning, NOCASE uniqueness, argon2 round-trip + never-logs-password,
lockout, password-change/disable revocation, the credential-length cap, and the two security invariants
that distinguish it from the snapshot store: a corrupt/newer DB RAISES (never drops users), and a snapshot
reset cannot touch auth.db."""
from __future__ import annotations

import sqlite3

import pytest

import auth_store
import config


def _db(tmp_path):
    return str(tmp_path / "auth.db")


# --- migration / versioning ----------------------------------------------------------
def test_fresh_db_created_at_current_version(tmp_path):
    db = _db(tmp_path)
    assert auth_store.user_count(db_path=db) == 0
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == auth_store.AUTH_SCHEMA_VERSION
    finally:
        conn.close()


def test_newer_schema_raises_never_resets(tmp_path):
    """A file claiming a newer schema must HARD-FAIL — unlike the snapshot store, we never reset/drop."""
    db = _db(tmp_path)
    auth_store.create_user("alice", "pw-correct-horse", now=1000.0, db_path=db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(f"PRAGMA user_version = {auth_store.AUTH_SCHEMA_VERSION + 5}")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        auth_store.get_user("alice", db_path=db)
    # And the users table is still intact (nothing was dropped) once we restore the version.
    conn = sqlite3.connect(db)
    try:
        conn.execute(f"PRAGMA user_version = {auth_store.AUTH_SCHEMA_VERSION}")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        conn.close()


def test_snapshot_reset_cannot_reach_auth_db(tmp_path):
    """The snapshot store's destructive reset only knows its own tables; auth.db is a separate file with a
    `users` table it never names. Proves credential isolation."""
    import store
    auth_db = _db(tmp_path)
    snap_db = str(tmp_path / "snap.db")
    auth_store.create_user("alice", "pw-correct-horse", now=1.0, db_path=auth_db)
    conn = sqlite3.connect(snap_db)
    try:
        store._reset_to_fresh(conn)   # the exact destructive path that DROPs snapshot tables
    finally:
        conn.close()
    assert auth_store.user_count(db_path=auth_db) == 1
    assert "users" not in store._SCHEMA  # the reset schema never even mentions a users table


# --- argon2 hashing ------------------------------------------------------------------
def test_hash_roundtrip_and_wrong_password(tmp_path, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    secret = "correct horse battery staple"
    h = auth_store.hash_password(secret)
    assert h != secret and h.startswith("$argon2")
    assert auth_store.verify_password(h, secret) is True
    assert auth_store.verify_password(h, "wrong password") is False
    # The password must NEVER appear in logs.
    assert secret not in caplog.text


def test_cred_length_cap(tmp_path):
    db = _db(tmp_path)
    huge = "x" * (config.AUTH_MAX_CRED_LEN + 1)
    with pytest.raises(ValueError):
        auth_store.hash_password(huge)
    with pytest.raises(ValueError):
        auth_store.create_user("bob", huge, now=1.0, db_path=db)
    # An over-long password to verify is a clean non-match, not an exception.
    h = auth_store.hash_password("short-enough")
    assert auth_store.verify_password(h, huge) is False


def test_needs_rehash_on_param_change(tmp_path, monkeypatch):
    h = auth_store.hash_password("pw")
    assert auth_store.needs_rehash(h) is False
    monkeypatch.setattr(config, "AUTH_ARGON2_MEMORY_COST", config.AUTH_ARGON2_MEMORY_COST * 2)
    assert auth_store.needs_rehash(h) is True


# --- user CRUD + NOCASE --------------------------------------------------------------
def test_username_unique_nocase(tmp_path):
    db = _db(tmp_path)
    auth_store.create_user("Alice", "pw-one-two-three", now=1.0, db_path=db)
    with pytest.raises(ValueError):
        auth_store.create_user("alice", "pw-four-five-six", now=2.0, db_path=db)
    assert auth_store.get_user("ALICE", db_path=db)["username"] == "Alice"


def test_blank_username_or_password_rejected(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        auth_store.create_user("   ", "pw", now=1.0, db_path=db)
    with pytest.raises(ValueError):
        auth_store.create_user("carol", "", now=1.0, db_path=db)


# --- lockout -------------------------------------------------------------------------
def test_lockout_trips_and_unlocks(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("dave", "pw-correct", now=0.0, db_path=db)
    for i in range(config.AUTH_LOCKOUT_THRESHOLD):
        auth_store.record_login_failure(uid, now=float(i), db_path=db)
    user = auth_store.get_user("dave", db_path=db)
    assert auth_store.is_locked(user, now=100.0) is True
    # Past the window it is no longer locked.
    assert auth_store.is_locked(user, now=user["locked_until"] + 1) is False
    # CLI unlock clears it immediately (anti-DoS).
    auth_store.unlock("dave", db_path=db)
    assert auth_store.is_locked(auth_store.get_user("dave", db_path=db), now=100.0) is False


def test_reset_failures_after_success(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("erin", "pw-correct", now=0.0, db_path=db)
    auth_store.record_login_failure(uid, now=1.0, db_path=db)
    auth_store.reset_login_failures(uid, db_path=db)
    assert auth_store.get_user("erin", db_path=db)["failed_count"] == 0


# --- revocation (session_epoch) ------------------------------------------------------
def test_password_change_bumps_epoch_and_revokes_tokens(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("frank", "pw-original", now=10.0, db_path=db)
    auth_store.issue_device_token(uid, now=11.0, db_path=db)
    auth_store.set_password("frank", "pw-new-value", now=20.0, db_path=db)
    user = auth_store.get_user("frank", db_path=db)
    assert user["session_epoch"] == 20.0          # invalidates cookies issued before 20.0
    assert user["pw_changed_ts"] == 20.0
    assert auth_store.list_device_tokens(uid, db_path=db) == []   # all tokens revoked


def test_disable_bumps_epoch_and_revokes(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("gina", "pw-original", now=10.0, db_path=db)
    auth_store.issue_device_token(uid, now=11.0, db_path=db)
    auth_store.set_disabled("gina", True, now=30.0, db_path=db)
    user = auth_store.get_user("gina", db_path=db)
    assert user["disabled"] == 1 and user["session_epoch"] == 30.0
    assert auth_store.list_device_tokens(uid, db_path=db) == []
