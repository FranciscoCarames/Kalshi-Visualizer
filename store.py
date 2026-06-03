"""SQLite snapshot store for opportunity history — Stage 1 durable backbone.

UI-agnostic, single-writer local SQLite. Persists one SNAPSHOT per refresh: the opportunity rows
(consistency checks + dutch-book findings) present at that moment, each keyed by its stable
``opportunity_id`` and carrying the fields the Stage-3 change-classifier will diff. Pure standard
library (``sqlite3`` + ``json``) — NO Streamlit, and NO pandas import (a DataFrame is duck-typed via
``.to_dict``), so the store is independently unit-testable against a tmp file. No multi-user / locking
/ server: a future single-writer scanner (Stage 2) is its first caller, and the schema is versioned
(``PRAGMA user_version``) so it can evolve without a rewrite.

Time handling is deterministic and exact-UTC: every ``fetched_at`` is normalized to an epoch second
(``fetched_ts``) for ordering, retention, and window math, while the original text is preserved for
display. Retention and ``snapshots_since`` are computed RELATIVE TO THE NEWEST STORED SNAPSHOT (not
wall-clock ``now``), so behaviour is reproducible in tests and independent of when a query runs.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import config

# Bump when the on-disk schema changes; `_migrate` brings an older file forward. Held in the SQLite
# `user_version` pragma so no bookkeeping table is needed.
SCHEMA_VERSION = 1

# Columns promoted out of each opportunity row into indexed SQL columns for cheap lifecycle/backlog
# filtering; the FULL row always round-trips in the `data` JSON blob, so no field is ever lost. Stable
# order — a schema test guards it.
PROMOTED_COLUMNS = ("opportunity_id", "relationship_type", "bucket", "status", "blocked_reason")

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,          -- original timestamp text (display)
    fetched_ts  REAL NOT NULL           -- epoch seconds, UTC (ordering / retention / windows)
);
CREATE TABLE IF NOT EXISTS opportunities (
    snapshot_id        INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    opportunity_id     TEXT NOT NULL,
    relationship_type  TEXT,
    bucket             TEXT,
    status             TEXT,
    blocked_reason     TEXT,
    data               TEXT NOT NULL    -- full row as JSON (NaN->null, tuples->arrays)
);
CREATE INDEX IF NOT EXISTS ix_opp_snapshot ON opportunities(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_opp_id       ON opportunities(opportunity_id);
"""


# --- time normalization (exact UTC; deterministic) -----------------------------------
_DISPLAY_FMT = "%Y-%m-%d %H:%M:%S UTC"   # the format load_contracts stamps fetched_at with


def _to_epoch(fetched_at: Any) -> float:
    """Epoch seconds (UTC) for a fetched_at given as datetime, ISO string, the load_contracts display
    string, or a raw numeric epoch (test convenience). Raises ValueError if unparseable — we never
    silently store an unorderable timestamp."""
    if isinstance(fetched_at, bool):  # guard: bool is an int subclass
        raise ValueError(f"unparseable fetched_at: {fetched_at!r}")
    if isinstance(fetched_at, (int, float)):
        return float(fetched_at)
    if isinstance(fetched_at, datetime):
        dt = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).timestamp()
    s = str(fetched_at or "").strip()
    if s:
        try:
            return datetime.strptime(s, _DISPLAY_FMT).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            try:
                dt = datetime.fromisoformat(s)
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
            except ValueError:
                pass
    raise ValueError(f"unparseable fetched_at: {fetched_at!r}")


def _to_text(fetched_at: Any) -> str:
    """The original timestamp text to preserve for display (ISO for a datetime)."""
    if isinstance(fetched_at, datetime):
        dt = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(fetched_at if fetched_at is not None else "")


# --- record sanitizing ---------------------------------------------------------------
def _records(opps: Any) -> list[dict[str, Any]]:
    """Coerce the input to a list of plain dicts. Accepts a pandas DataFrame (duck-typed via
    `to_dict`) or any iterable of dict-like rows, so the store never imports pandas."""
    if opps is None:
        return []
    if hasattr(opps, "to_dict"):              # pandas DataFrame
        return opps.to_dict("records")
    return [dict(r) for r in opps]


def _clean(v: Any) -> Any:
    """Make a value JSON-safe and deterministic: float NaN -> None, tuples -> lists, numpy scalars ->
    python, anything exotic -> str. Keeps the stored JSON valid (no bare NaN) and stable."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return None if v != v else v          # NaN -> None
    if isinstance(v, (str, int)):
        return v
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    item = getattr(v, "item", None)           # numpy scalar -> python scalar
    if callable(item):
        try:
            return _clean(item())
        except (ValueError, TypeError):
            pass
    return str(v)


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _clean(v) for k, v in row.items()}


def _promoted(row: dict[str, Any], key: str) -> str | None:
    v = row.get(key)
    if v is None or (isinstance(v, float) and v != v):
        return None
    return str(v)


# --- connection / migration ----------------------------------------------------------
def _connect(db_path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SNAPSHOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the file to SCHEMA_VERSION. A fresh (user_version 0) file is created at the current
    version; future intermediate versions apply forward steps here. A newer-than-supported file is a
    hard error (never downgrade-write)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"snapshot DB schema v{version} is newer than supported v{SCHEMA_VERSION}"
        )
    # v0 (fresh) -> v1: create the base schema. (Add `if version < 2: ...` style steps as the
    # schema grows; each step migrates one version forward.)
    conn.executescript(_SCHEMA_V1)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _apply_retention(conn: sqlite3.Connection, retention_seconds: float | None = None) -> int:
    """Drop snapshots older than the retention window, measured back from the NEWEST stored snapshot.
    Returns the number of snapshots dropped."""
    keep = config.SNAPSHOT_RETENTION_SECONDS if retention_seconds is None else retention_seconds
    newest = conn.execute("SELECT MAX(fetched_ts) AS m FROM snapshots").fetchone()["m"]
    if newest is None:
        return 0
    cutoff = newest - keep
    old = [r["id"] for r in conn.execute(
        "SELECT id FROM snapshots WHERE fetched_ts < ?", (cutoff,)).fetchall()]
    if not old:
        return 0
    marks = ",".join("?" * len(old))
    conn.execute(f"DELETE FROM opportunities WHERE snapshot_id IN ({marks})", old)
    conn.execute(f"DELETE FROM snapshots WHERE id IN ({marks})", old)
    return len(old)


def _load(conn: sqlite3.Connection, clause: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Read snapshots (+ their opportunity rows, JSON-expanded) matching an ORDER/WHERE clause."""
    snaps = conn.execute(
        f"SELECT id, fetched_at, fetched_ts FROM snapshots {clause}", params).fetchall()
    out: list[dict[str, Any]] = []
    for s in snaps:
        rows = conn.execute(
            "SELECT data FROM opportunities WHERE snapshot_id = ? ORDER BY rowid", (s["id"],)
        ).fetchall()
        out.append({
            "snapshot_id": s["id"],
            "fetched_at": s["fetched_at"],
            "fetched_ts": s["fetched_ts"],
            "opportunities": [json.loads(r["data"]) for r in rows],
        })
    return out


# --- public API ----------------------------------------------------------------------
def write_snapshot(fetched_at: Any, opps: Any, db_path: str | None = None) -> int:
    """Persist one snapshot of opportunity rows and return its snapshot id.

    `fetched_at` is the refresh timestamp (datetime / ISO / load_contracts text / epoch). `opps` is a
    pandas DataFrame or an iterable of dict rows (consistency checks and/or dutch-book findings). An
    empty `opps` still records a snapshot (a refresh with no opportunities is itself information).
    Retention is applied after the write."""
    records = _records(opps)
    ts = _to_epoch(fetched_at)
    text = _to_text(fetched_at)
    conn = _connect(db_path)
    try:
        sid = conn.execute(
            "INSERT INTO snapshots (fetched_at, fetched_ts) VALUES (?, ?)", (text, ts)
        ).lastrowid
        conn.executemany(
            "INSERT INTO opportunities "
            "(snapshot_id, opportunity_id, relationship_type, bucket, status, blocked_reason, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    sid,
                    _promoted(r, "opportunity_id") or "",
                    _promoted(r, "relationship_type"),
                    _promoted(r, "bucket"),
                    _promoted(r, "status"),
                    _promoted(r, "blocked_reason"),
                    json.dumps(_jsonable(r)),
                )
                for r in records
            ],
        )
        _apply_retention(conn)
        conn.commit()
        return sid
    finally:
        conn.close()


def latest_two(db_path: str | None = None) -> list[dict[str, Any]]:
    """The two most recent snapshots, ordered OLDEST -> NEWEST (i.e. ``[prev, cur]`` for diffing).
    Fewer than two stored -> a shorter list (possibly empty)."""
    conn = _connect(db_path)
    try:
        snaps = _load(conn, "ORDER BY fetched_ts DESC, id DESC LIMIT 2")
    finally:
        conn.close()
    return list(reversed(snaps))


def snapshots_since(window: Any, db_path: str | None = None) -> list[dict[str, Any]]:
    """All snapshots within `window` of the NEWEST stored snapshot, oldest -> newest. `window` is a
    `timedelta` or a number of seconds. The boundary is inclusive (``fetched_ts >= newest - window``).
    Empty when nothing is stored."""
    seconds = window.total_seconds() if isinstance(window, timedelta) else float(window)
    conn = _connect(db_path)
    try:
        newest = conn.execute("SELECT MAX(fetched_ts) AS m FROM snapshots").fetchone()["m"]
        if newest is None:
            return []
        cutoff = newest - seconds
        return _load(conn, "WHERE fetched_ts >= ? ORDER BY fetched_ts ASC, id ASC", (cutoff,))
    finally:
        conn.close()
