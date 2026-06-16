"""Tests for the manage_users CLI + serve.seed_admin_from_env. Drives the command handlers directly
against a tmp auth.db (AUTH_DB_PATH env), with getpass monkeypatched so no terminal is needed."""
from __future__ import annotations

import pytest

import auth_store
import manage_users


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    db = str(tmp_path / "auth.db")
    monkeypatch.setenv("AUTH_DB_PATH", db)
    return db


def test_add_list_disable_enable_unlock(auth_db, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "a-strong-passphrase")
    manage_users.main(["add", "alice"])
    assert auth_store.get_user("alice", db_path=auth_db) is not None

    manage_users.main(["list"])
    assert "alice" in capsys.readouterr().out

    manage_users.main(["disable", "alice"])
    assert auth_store.get_user("alice", db_path=auth_db)["disabled"] == 1
    manage_users.main(["enable", "alice"])
    assert auth_store.get_user("alice", db_path=auth_db)["disabled"] == 0

    manage_users.main(["unlock", "alice"])  # no-op but must not error


def test_add_rejects_weak_password(auth_db, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "password")
    with pytest.raises(SystemExit):
        manage_users.main(["add", "bob"])
    assert auth_store.get_user("bob", db_path=auth_db) is None


def test_add_rejects_mismatched_confirmation(auth_db, monkeypatch):
    answers = iter(["a-strong-passphrase", "different-passphrase"])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(answers))
    with pytest.raises(SystemExit):
        manage_users.main(["add", "carol"])


def test_passwd_unknown_user_errors(auth_db, monkeypatch):
    with pytest.raises(SystemExit):
        manage_users.main(["passwd", "ghost"])


def test_seed_admin_from_env_idempotent(auth_db, monkeypatch):
    import serve
    monkeypatch.setenv("APP_ADMIN_USER", "root")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-strong-admin-pass")
    serve.seed_admin_from_env()
    assert auth_store.user_count(db_path=auth_db) == 1
    first = auth_store.get_user("root", db_path=auth_db)
    assert first["force_pw_change"] == 1
    # Second call is a no-op (never overwrites).
    serve.seed_admin_from_env()
    assert auth_store.user_count(db_path=auth_db) == 1


def test_seed_admin_rejects_weak(auth_db, monkeypatch):
    import serve
    monkeypatch.setenv("APP_ADMIN_USER", "root")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "admin")
    with pytest.raises(SystemExit):
        serve.seed_admin_from_env()
    assert auth_store.user_count(db_path=auth_db) == 0


def test_seed_admin_noop_without_env(auth_db, monkeypatch):
    import serve
    monkeypatch.delenv("APP_ADMIN_USER", raising=False)
    monkeypatch.delenv("APP_ADMIN_PASSWORD", raising=False)
    serve.seed_admin_from_env()
    assert auth_store.user_count(db_path=auth_db) == 0
