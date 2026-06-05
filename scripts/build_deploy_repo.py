"""Build the clean, runtime-only DEPLOY artifact from this source repo (PR D1-D5).

The hosted app is NiceGUI on FastAPI via ``serve.py``. The deploy artifact ships ONLY the first-party
runtime modules it imports + the ops templates + a pinned requirements lock — never the
tests, docs, planning folders, or local state (``snapshots.db`` / caches / ``.env``).

The module allowlist is DERIVED from the import graph (a static AST walk of imports from ``serve.py`` /
``api.py``), so a transitive dependency can never be silently dropped — a hand-maintained list missed
``fetch.py`` (imported by ``api.py``) once. A fresh-clone import smoke
(``python -c "import serve, api, webui.dashboard"``) is the hard guard after the copy.

Usage: ``python scripts/build_deploy_repo.py <output_dir>`` (add ``--no-pip-compile`` to skip the lock).
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# webui.dashboard / webui.engine etc. are reached transitively from these two.
ENTRYPOINTS = ("serve.py", "api.py")

# Files copied verbatim alongside the import-derived modules.
STATIC_INCLUDES = (
    "deploy/kalshi-dashboard.service",
    "deploy/kalshi-dashboard-scan.service",
    "deploy/kalshi-dashboard-scan.timer",
    "deploy/scan.sh",
    "deploy/.env.example",
    "deploy/README.md",
    ".gitignore",
)
# Anything matching these must NEVER appear in the artifact (asserted after the build).
FORBIDDEN_NAMES = (".env",)
FORBIDDEN_DIRS = ("tests", "docs", ".kss", ".claude", "__pycache__", "tmp_kalshi_docs")


def _prefix_candidates(dotted: str, root: Path) -> list[Path]:
    """Every local-file candidate for a dotted import name AND its package prefixes, e.g. ``webui.dashboard``
    -> ``webui/__init__.py`` and ``webui/dashboard.py``."""
    parts = dotted.split(".")
    out: list[Path] = []
    for i in range(1, len(parts) + 1):
        out.append(root.joinpath(*parts[:i]).with_suffix(".py"))
        out.append(root.joinpath(*parts[:i], "__init__.py"))
    return out


def local_modules(entries: tuple[str, ...], root: Path = REPO_ROOT) -> set[Path]:
    """First-party ``.py`` files transitively imported from ``entries``. A dotted import that resolves to a
    file under ``root`` is first-party and returned; one that does not (stdlib / third-party) is skipped —
    those belong in requirements, not the copy. Static AST parse only (never executes the modules)."""
    seen: set[Path] = set()
    queue = [(root / e).resolve() for e in entries]
    while queue:
        path = queue.pop()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names)
        for name in names:
            for cand in _prefix_candidates(name, root):
                if cand.is_file():
                    queue.append(cand.resolve())
    return seen


def _assert_no_local_state(out_dir: Path) -> None:
    """Guard: the built artifact must contain no local state / dev / docs (snapshots.db + WAL/SHM, .env,
    tests/, docs/, caches)."""
    bad: set[str] = set()
    for p in out_dir.rglob("*"):
        rel = p.relative_to(out_dir)
        if p.name in FORBIDDEN_NAMES or p.suffix == ".db" or p.name.endswith(("-wal", "-shm")):
            bad.add(rel.as_posix())
        if any(part in FORBIDDEN_DIRS for part in rel.parts):
            bad.add(rel.as_posix())
    if bad:
        raise AssertionError(f"deploy artifact contains forbidden files: {sorted(bad)}")


def build(out_dir: Path, root: Path = REPO_ROOT, *, run_pip_compile: bool = True) -> dict:
    """Build the artifact at ``out_dir`` (recreated). Returns a small manifest. ``run_pip_compile=False``
    copies ``requirements.in`` unpinned (for CI/tests without pip-tools / network)."""
    rel_modules = sorted(m.relative_to(root).as_posix() for m in local_modules(ENTRYPOINTS, root))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for rel in rel_modules:                                    # 1) first-party runtime modules
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    for rel in STATIC_INCLUDES:                                # 2) ops templates + .gitignore
        src = root / rel
        if src.exists():
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    reqs_in = root / "deploy" / "requirements.in"              # 3) pinned, Streamlit-free requirements
    if reqs_in.exists():
        if run_pip_compile:
            subprocess.run([sys.executable, "-m", "piptools", "compile", str(reqs_in),
                            "--output-file", str(out_dir / "requirements.txt"), "--quiet"], check=True)
        else:
            shutil.copy2(reqs_in, out_dir / "requirements.txt")
    _assert_no_local_state(out_dir)
    return {"modules": rel_modules, "module_count": len(rel_modules)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the runtime-only Kalshi deploy artifact.")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--no-pip-compile", action="store_true",
                    help="copy requirements.in unpinned instead of running pip-compile (no pip-tools needed)")
    args = ap.parse_args()
    info = build(args.out_dir, run_pip_compile=not args.no_pip_compile)
    print(f"Built deploy artifact at {args.out_dir} with {info['module_count']} first-party modules.")
    print('Import smoke (run from a fresh clone): python -c "import serve, api, webui.dashboard"')


if __name__ == "__main__":
    main()
