"""Tests for scripts/build_deploy_repo.py (PR D-tasks): the import-graph walker derives the first-party
runtime modules (including transitive deps like fetch.py and the webui package) and excludes
stdlib/third-party; the built artifact carries the ops templates and no local state / dev / docs."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "build_deploy_repo", REPO / "scripts" / "build_deploy_repo.py")
bdr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bdr)


def _rel(modules):
    return {m.relative_to(REPO).as_posix() for m in modules}


def test_walker_includes_entrypoints_and_transitive_deps():
    mods = _rel(bdr.local_modules(("serve.py", "api.py"), REPO))
    assert "serve.py" in mods and "api.py" in mods
    assert "fetch.py" in mods                       # transitive (api.py imports fetch) — the hand-list bug
    assert {"config.py", "store.py", "scan_manager.py", "data.py"} <= mods
    assert "webui/dashboard.py" in mods and "webui/engine.py" in mods
    assert "webui/__init__.py" in mods              # the package init is pulled in too


def test_walker_excludes_stdlib_and_third_party():
    mods = _rel(bdr.local_modules(("serve.py", "api.py"), REPO))
    assert not any(m.startswith(("fastapi", "nicegui", "pydantic", "pandas", "uvicorn")) for m in mods)
    assert "os.py" not in mods and "json.py" not in mods and "ast.py" not in mods


def test_build_produces_clean_artifact(tmp_path):
    out = tmp_path / "deploy_repo"
    info = bdr.build(out, run_pip_compile=False)     # no pip-tools/network in CI -> unpinned copy
    assert info["module_count"] >= 10
    assert (out / "serve.py").exists() and (out / "webui" / "dashboard.py").exists()
    assert (out / "fetch.py").exists()
    assert not list(out.rglob("*.db"))               # no snapshots.db
    assert not (out / "tests").exists() and not (out / "docs").exists()
    # ops templates + requirements ship
    assert (out / "deploy" / "scan.sh").exists()
    assert (out / "deploy" / "kalshi-dashboard.service").exists()
    assert (out / "deploy" / "kalshi-dashboard-scan.timer").exists()
    assert (out / "requirements.txt").exists()


def test_no_local_state_assertion_catches_injected_db(tmp_path):
    out = tmp_path / "deploy_repo"
    bdr.build(out, run_pip_compile=False)
    (out / "snapshots.db").write_text("x")           # inject local state
    with pytest.raises(AssertionError):
        bdr._assert_no_local_state(out)
