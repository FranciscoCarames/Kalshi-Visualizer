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


# --- schema v1 -> v2 migration (preferences table) -----------------------------------
def test_v1_to_v2_migration_adds_preferences_without_dropping_users(tmp_path):
    db = _db(tmp_path)
    # Build a v1 file by hand: only the v1 tables, user_version = 1.
    conn = sqlite3.connect(db)
    try:
        conn.executescript(auth_store._SCHEMA)
        conn.execute("INSERT INTO users (username, pw_hash, created_ts) VALUES ('hank', 'x', 1.0)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()
    # Opening through auth_store migrates v1 -> v2 (creates preferences) and KEEPS the user.
    assert auth_store.user_count(db_path=db) == 1
    uid = auth_store.get_user("hank", db_path=db)["id"]
    auth_store.set_preferences(uid, {"theme": "hc"}, now=2.0, db_path=db)   # table now exists
    assert auth_store.get_preferences(uid, db_path=db)["theme"] == "hc"


# --- preferences storage + sanitization ----------------------------------------------
def test_preferences_roundtrip_and_default_empty(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("iris", "pw-correct-horse", now=1.0, db_path=db)
    assert auth_store.get_preferences(uid, db_path=db) == {}        # none yet
    stored = auth_store.set_preferences(
        uid, {"theme": "hc", "split": "vertical", "layoutPreset": "triage"}, now=2.0, db_path=db)
    assert stored["version"] == config.AUTH_PREFS_VERSION
    got = auth_store.get_preferences(uid, db_path=db)
    assert got["theme"] == "hc" and got["split"] == "vertical" and got["layoutPreset"] == "triage"


def test_sanitize_drops_unknown_keys_and_bad_values(tmp_path):
    clean = auth_store.sanitize_prefs({
        "theme": "neon",                       # invalid enum -> dropped
        "split": "vertical",                   # valid
        "layoutPreset": "evil",                # invalid -> dropped
        "evil_key": {"x": 1},                  # unknown top-level -> dropped
        "settings": {"showIds": True, "autoRefresh": "weird", "tz": "utc", "bogus": 1},
        "columns": {"opp": ["a", "b"], "notakey": ["x"], "risk": [1, 2]},  # bad key/values filtered
        "showNet": "yes",                      # not a bool -> dropped
    })
    assert clean == {
        "version": config.AUTH_PREFS_VERSION, "split": "vertical",
        "settings": {"showIds": True, "tz": "utc"},
        "columns": {"opp": ["a", "b"]},
    }


def test_sanitize_rejects_non_object(tmp_path):
    with pytest.raises(ValueError):
        auth_store.sanitize_prefs(["not", "a", "dict"])


def test_preferences_size_cap(tmp_path):
    db = _db(tmp_path)
    uid = auth_store.create_user("jack", "pw-correct-horse", now=1.0, db_path=db)
    huge = {"columns": {"opp": ["x" * 1000] * 100}}     # well over the cap once serialized
    with pytest.raises(ValueError):
        auth_store.set_preferences(uid, huge, now=2.0, db_path=db)


def test_corrupt_preferences_row_returns_empty(tmp_path, caplog):
    db = _db(tmp_path)
    uid = auth_store.create_user("kate", "pw-correct-horse", now=1.0, db_path=db)
    auth_store.set_preferences(uid, {"theme": "hc"}, now=2.0, db_path=db)
    conn = sqlite3.connect(db)                          # corrupt the JSON directly
    try:
        conn.execute("UPDATE preferences SET prefs_json = '{not valid json' WHERE user_id = ?", (uid,))
        conn.commit()
    finally:
        conn.close()
    assert auth_store.get_preferences(uid, db_path=db) == {}   # never raises / 500s
    assert "kate" not in caplog.text and "{not valid" not in caplog.text   # no content leaked


def test_delete_user_cascades_to_prefs_and_tokens(tmp_path):
    """FK cascade requires PRAGMA foreign_keys=ON per connection (_connect sets it)."""
    db = _db(tmp_path)
    uid = auth_store.create_user("liam", "pw-correct-horse", now=1.0, db_path=db)
    auth_store.set_preferences(uid, {"theme": "hc"}, now=2.0, db_path=db)
    auth_store.issue_device_token(uid, now=2.0, db_path=db)
    conn = auth_store._connect(db)
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM preferences WHERE user_id = ?", (uid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM device_tokens WHERE user_id = ?",
                            (uid,)).fetchone()[0] == 0
    finally:
        conn.close()
