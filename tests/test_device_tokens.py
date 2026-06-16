"""Unit tests for the remember-me device-token rotation (auth_store.py). Covers issue → new session on a
session-less request, single-use rotation (the old validator dies), expiry, per-device + global revoke,
the password-change/disable sweep, and the theft signal (known selector + wrong validator → revoke all)."""
from __future__ import annotations

import auth_store
import config


def _db(tmp_path):
    return str(tmp_path / "auth.db")


def _user(tmp_path, now=0.0):
    db = _db(tmp_path)
    uid = auth_store.create_user("alice", "pw-correct-horse", now=now, db_path=db)
    return db, uid


def test_issue_and_consume_returns_user_and_rotates(tmp_path):
    db, uid = _user(tmp_path)
    selector, validator = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    user, new_token = auth_store.consume_device_token(selector, validator, now=2.0, db_path=db)
    assert user is not None and user["id"] == uid
    assert new_token is not None and new_token[0] != selector   # rotated to a new selector
    # The OLD token is single-use — replaying it now fails.
    again, _ = auth_store.consume_device_token(selector, validator, now=3.0, db_path=db)
    assert again is None
    # The NEW token works.
    user2, _ = auth_store.consume_device_token(new_token[0], new_token[1], now=4.0, db_path=db)
    assert user2 is not None and user2["id"] == uid


def test_expired_token_rejected(tmp_path):
    db, uid = _user(tmp_path)
    selector, validator = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    expired_at = 1.0 + config.AUTH_REMEMBER_MAX_AGE + 1
    user, new = auth_store.consume_device_token(selector, validator, now=expired_at, db_path=db)
    assert user is None and new is None


def test_wrong_validator_revokes_all_tokens(tmp_path):
    """A known selector with a bad validator is a replay/theft signal → revoke the whole family."""
    db, uid = _user(tmp_path)
    sel_a, _val_a = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    sel_b, val_b = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    user, new = auth_store.consume_device_token(sel_a, "totally-wrong-validator", now=2.0, db_path=db)
    assert user is None and new is None
    # The OTHER device's token is now revoked too.
    user_b, _ = auth_store.consume_device_token(sel_b, val_b, now=3.0, db_path=db)
    assert user_b is None
    assert auth_store.list_device_tokens(uid, db_path=db) == []


def test_unknown_selector_returns_none(tmp_path):
    db, _uid = _user(tmp_path)
    user, new = auth_store.consume_device_token("no-such-selector", "x", now=1.0, db_path=db)
    assert user is None and new is None


def test_disabled_user_token_rejected(tmp_path):
    db, uid = _user(tmp_path)
    selector, validator = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    auth_store.set_disabled("alice", True, now=2.0, db_path=db)   # also sweeps tokens
    user, new = auth_store.consume_device_token(selector, validator, now=3.0, db_path=db)
    assert user is None and new is None


def test_epoch_stale_token_rejected(tmp_path):
    """A token created before a session_epoch bump (e.g. password change) is invalid even if not yet
    swept — the epoch check is the backstop."""
    db, uid = _user(tmp_path)
    selector, validator = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    # Bump the epoch directly past the token's created_ts WITHOUT revoking (simulate the backstop path).
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE users SET session_epoch = 50.0 WHERE id = ?", (uid,))
        conn.commit()
    finally:
        conn.close()
    user, new = auth_store.consume_device_token(selector, validator, now=60.0, db_path=db)
    assert user is None and new is None


def test_per_device_and_global_revoke(tmp_path):
    db, uid = _user(tmp_path)
    sel_a, val_a = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    sel_b, val_b = auth_store.issue_device_token(uid, now=1.0, db_path=db)
    tokens = auth_store.list_device_tokens(uid, db_path=db)
    assert len(tokens) == 2
    # Revoke just device A.
    auth_store.revoke_device_token(tokens[0]["id"], now=2.0, user_id=uid, db_path=db)
    assert len(auth_store.list_device_tokens(uid, db_path=db)) == 1
    # Global revoke clears the rest.
    auth_store.revoke_all_device_tokens(uid, now=3.0, db_path=db)
    assert auth_store.list_device_tokens(uid, db_path=db) == []


def test_purge_expired(tmp_path):
    db, uid = _user(tmp_path)
    auth_store.issue_device_token(uid, now=1.0, db_path=db)
    removed = auth_store.purge_expired(now=1.0 + config.AUTH_REMEMBER_MAX_AGE + 5, db_path=db)
    assert removed == 1
