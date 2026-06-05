"""Unit tests for serve.bind_safety — the LAN-bind safety gate (PR 19a). Pure: no uvicorn, no network.

The dashboard has no auth and NiceGUI signs its session cookie with the storage secret, so exposing a
non-loopback host with only the dev-fallback secret must be refused (fatal); the snapshot store + Kalshi
throttle are process-local, so multiple workers must be warned against.
"""
from __future__ import annotations

import importlib

import pytest

import config
import serve


def _levels(issues):
    return sorted(level for level, _ in issues)


# --- storage-secret fail-hard ----------------------------------------------------------------
def test_loopback_needs_no_secret():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert serve.bind_safety(host, storage_secret_set=False, allow_dev_on_lan=False) == []


def test_non_loopback_without_secret_is_fatal():
    issues = serve.bind_safety("0.0.0.0", storage_secret_set=False, allow_dev_on_lan=False)
    assert _levels(issues) == ["fatal"]
    assert "NICEGUI_STORAGE_SECRET" in issues[0][1]


def test_non_loopback_escape_downgrades_to_warn():
    issues = serve.bind_safety("0.0.0.0", storage_secret_set=False, allow_dev_on_lan=True)
    assert _levels(issues) == ["warn"]
    assert "ALLOW_DEV_STORAGE_SECRET_ON_LAN" in issues[0][1]


def test_non_loopback_with_secret_is_clean():
    assert serve.bind_safety("192.168.1.42", storage_secret_set=True, allow_dev_on_lan=False) == []


# --- multi-worker guard ----------------------------------------------------------------------
def test_web_concurrency_gt_1_warns():
    # Independent of the secret rule: a secret-clean LAN bind with workers -> exactly one (worker) warn.
    issues = serve.bind_safety("0.0.0.0", storage_secret_set=True, allow_dev_on_lan=False,
                               web_concurrency=4)
    assert _levels(issues) == ["warn"] and "PROCESS-LOCAL" in issues[0][1]


def test_workers_arg_warns():
    issues = serve.bind_safety("127.0.0.1", storage_secret_set=False, allow_dev_on_lan=False,
                               has_workers_arg=True)
    assert _levels(issues) == ["warn"]


def test_single_worker_is_silent():
    assert serve.bind_safety("127.0.0.1", storage_secret_set=False, allow_dev_on_lan=False,
                             web_concurrency=1) == []


def test_fatal_and_worker_warn_are_independent():
    # Non-loopback + no secret + workers -> a fatal (secret) AND a warn (workers), both reported.
    issues = serve.bind_safety("0.0.0.0", storage_secret_set=False, allow_dev_on_lan=False,
                               web_concurrency=2)
    assert _levels(issues) == ["fatal", "warn"]


# --- SNAPSHOT_DB_PATH env override (PR S2) ---------------------------------------------------
def test_resolve_db_path_unset_keeps_default():
    assert serve.resolve_snapshot_db_path(None) is None
    assert serve.resolve_snapshot_db_path("") is None


def test_resolve_db_path_valid_parent_returns_path(tmp_path):
    p = str(tmp_path / "snapshots.db")            # parent (tmp_path) exists
    assert serve.resolve_snapshot_db_path(p) == p


def test_resolve_db_path_missing_parent_exits_at_startup(tmp_path):
    with pytest.raises(SystemExit):
        serve.resolve_snapshot_db_path(str(tmp_path / "missing" / "snapshots.db"))


def test_config_does_not_read_env_at_import(monkeypatch):
    # The override lives at the serve boundary, NOT in config.py (which stays import-free): setting the env
    # and re-importing config must NOT change its default.
    monkeypatch.setenv("SNAPSHOT_DB_PATH", "/somewhere/else.db")
    importlib.reload(config)
    assert config.SNAPSHOT_DB_PATH == "snapshots.db"


def test_apply_sets_config_when_env_set(tmp_path, monkeypatch):
    original = config.SNAPSHOT_DB_PATH
    target = str(tmp_path / "snap.db")
    monkeypatch.setenv("SNAPSHOT_DB_PATH", target)
    try:
        serve._apply_snapshot_db_path()
        assert config.SNAPSHOT_DB_PATH == target
    finally:
        config.SNAPSHOT_DB_PATH = original


def test_apply_noop_when_env_unset(monkeypatch):
    original = config.SNAPSHOT_DB_PATH
    monkeypatch.delenv("SNAPSHOT_DB_PATH", raising=False)
    serve._apply_snapshot_db_path()
    assert config.SNAPSHOT_DB_PATH == original
