"""Tests for /readyz readiness (PR S1): the pure decision (`diagnostics.build_readiness`), the
migration-free writability probe (`store.db_writable`), and the endpoint (ready / degraded / not_ready)
via the FastAPI TestClient with a seeded tmp store — no network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
import config
import scan_manager
import store
from webui import diagnostics


# --- pure decision -------------------------------------------------------------------
def _scan(status="idle", error=None):
    return {"status": status, "last_result": ({"error": error} if error else None)}


def test_build_readiness_not_ready_when_unwritable():
    code, body = diagnostics.build_readiness(
        writable=False, snapshot=None, age=None, stale=None, scan_status=_scan())
    assert code == 503 and body["status"] == "not_ready"


def test_build_readiness_degraded_when_no_snapshot():
    code, body = diagnostics.build_readiness(
        writable=True, snapshot=None, age=None, stale=None, scan_status=_scan())
    assert code == 200 and body["status"] == "degraded" and body["reason"] == "no snapshot yet"


def test_build_readiness_degraded_on_last_scan_error():
    code, body = diagnostics.build_readiness(
        writable=True, snapshot={"x": 1}, age=10.0, stale=False,
        scan_status=_scan("error", error="boom"))
    assert code == 200 and body["status"] == "degraded"
    assert body["last_scan_error"] == "boom" and "boom" in body["reason"]


def test_build_readiness_degraded_when_stale():
    code, body = diagnostics.build_readiness(
        writable=True, snapshot={"x": 1}, age=9999.0, stale=True, scan_status=_scan())
    assert code == 200 and body["status"] == "degraded" and body["reason"] == "snapshot is stale"


def test_build_readiness_ready():
    code, body = diagnostics.build_readiness(
        writable=True, snapshot={"x": 1}, age=5.0, stale=False, scan_status=_scan("done"))
    assert code == 200 and body["status"] == "ready" and body["reason"] is None
    assert body["last_scan_status"] == "done"


def test_build_readiness_scan_in_progress_passes_through_while_ready():
    code, body = diagnostics.build_readiness(
        writable=True, snapshot={"x": 1}, age=5.0, stale=False, scan_status=_scan("in_progress"))
    assert code == 200 and body["status"] == "ready" and body["last_scan_status"] == "in_progress"


# --- migration-free writability probe ------------------------------------------------
def test_db_writable_memory_true():
    assert store.db_writable(":memory:") is True


def test_db_writable_existing_file(tmp_path):
    db = tmp_path / "x.db"
    db.write_text("")
    assert store.db_writable(str(db)) is True


def test_db_writable_parent_dir_when_absent(tmp_path):
    assert store.db_writable(str(tmp_path / "not-created.db")) is True


def test_db_writable_false_when_parent_missing(tmp_path):
    # parent dir does not exist -> cannot create the DB -> not writable (drives /readyz not_ready)
    assert store.db_writable(str(tmp_path / "nope" / "x.db")) is False


def test_db_writable_does_not_create_the_db(tmp_path):
    db = tmp_path / "probe.db"
    store.db_writable(str(db))
    assert not db.exists()      # the probe must NOT create/migrate the file


# --- endpoint ------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "ready.db")
    api.app.dependency_overrides[api.db_path_dep] = lambda: db
    scan_manager.manager.reset()
    yield TestClient(api.app), db
    api.app.dependency_overrides.clear()
    scan_manager.manager.reset()


def _seed(db, *, age_seconds):
    when = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    store.write_snapshot(when, [], db_path=db)


def test_readyz_degraded_when_no_snapshot(client):
    c, _ = client
    r = c.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded" and r.json()["reason"] == "no snapshot yet"


def test_readyz_ready_with_fresh_snapshot(client):
    c, db = client
    _seed(db, age_seconds=5)
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_readyz_degraded_with_stale_snapshot(client):
    c, db = client
    _seed(db, age_seconds=config.STALE_AFTER_SECONDS + 100)
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "degraded"
    assert r.json()["reason"] == "snapshot is stale"


def test_readyz_not_ready_when_db_unwritable(tmp_path):
    # DB under a MISSING parent dir -> not writable -> 503 (no migration/connect attempted)
    bad = str(tmp_path / "missing" / "x.db")
    api.app.dependency_overrides[api.db_path_dep] = lambda: bad
    scan_manager.manager.reset()
    try:
        r = TestClient(api.app).get("/readyz")
        assert r.status_code == 503 and r.json()["status"] == "not_ready"
    finally:
        api.app.dependency_overrides.clear()
        scan_manager.manager.reset()
