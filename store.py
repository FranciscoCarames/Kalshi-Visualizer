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
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import config

_log = logging.getLogger(__name__)


# --- env-overridable footprint knobs (config holds the DEFAULTS; the override is read HERE, the boundary
# that consumes them, keeping config.py import-free per convention). Bad values fall back to the config default.
def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None and v.strip() != "" else default
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Process-local counter so heavy DB housekeeping (incremental_vacuum + WAL checkpoint) runs only every Nth
# snapshot write, not on every scan (bounds the post-commit cost at high cadence).
_snapshots_written = 0

# Bump when the on-disk schema changes; `_migrate` brings an older file forward. Held in the SQLite
# `user_version` pragma so no bookkeeping table is needed. v3 adds `snapshot_frames` (per-sport/per-frame
# evidence) + WAL; the v2->v3 upgrade backs up the file first and falls back to a fresh DB on failure.
# v4 adds `backlog_intervals` (durable 7-day opportunity lifecycle per category, independent of the
# 30h snapshot retention) — a pure additive table, so the v3->v4 step just creates it.
SCHEMA_VERSION = 4

# Columns promoted out of each opportunity row into indexed SQL columns for cheap lifecycle/backlog
# filtering; the FULL row always round-trips in the `data` JSON blob, so no field is ever lost. Stable
# order — a schema test guards it.
PROMOTED_COLUMNS = ("opportunity_id", "relationship_type", "bucket", "status", "blocked_reason")

# v3 addition: per-snapshot evidence frames (the per-sport contracts / checks / dutch-book DataFrames the
# scanner produces), each stored as one JSON blob, partial-loadable by (sport, frame_type), with its OWN
# `schema_version` so a frame's shape can evolve independently of the snapshot schema. Kept as a separate
# constant so the v2->v3 migration can create it via a single forward step.
_FRAMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_frames (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    sport           TEXT,
    frame_type      TEXT,                -- 'contracts' | 'checks' | 'dutchbook' | ... (scanner-defined)
    schema_version  INTEGER,             -- per-frame version (NOT the global SCHEMA_VERSION)
    rows_json       TEXT NOT NULL,       -- the frame's rows as a JSON array (NaN->null, tuples->arrays)
    row_count       INTEGER
);
CREATE INDEX IF NOT EXISTS ix_frame_snapshot ON snapshot_frames(snapshot_id);
"""

# v4 addition: the DURABLE interval backlog. One row per opportunity-lifecycle-in-a-category — an open
# interval (`left_ts IS NULL`) while the opportunity is in a tracked category, closed (`left_ts` set) when
# it drops out. An opportunity that appears, leaves, then reappears yields TWO intervals (a surrogate `id`
# PK, not a unique (opportunity_id, category) — so re-entry never merges/erases the first lifecycle). The
# PARTIAL unique index enforces at-most-one OPEN interval per (opportunity_id, category). Maintained
# incrementally in `write_snapshot`; retained `BACKLOG_RETENTION_SECONDS` after close.
_BACKLOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog_intervals (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id        TEXT NOT NULL,
    category              TEXT NOT NULL,        -- 'actionable' | 'bounded_loss' | 'statistical_arbitrage'
    sport                 TEXT,
    name                  TEXT,
    url                   TEXT,
    first_seen_ts         REAL,                 -- epoch of the first snapshot of THIS interval
    last_seen_ts          REAL,                 -- advances while the interval is open
    left_ts               REAL,                 -- NULL while OPEN; set to the snapshot ts it dropped out
    last_bucket           TEXT,                 -- the bucket it last sat in (category interpretation)
    last_status           TEXT,
    peak_roi_pct          REAL,                 -- best ROI% over the interval
    best_case_profit_c    REAL,                 -- best best-case profit (¢) over the interval
    worst_case_profit_c   REAL,                 -- best (least-negative) worst-case (¢) over the interval
    last_settlement_caveat TEXT,
    last_legs             TEXT,                 -- full N-leg plan JSON, as last in-category
    data                  TEXT                  -- last full unified row JSON (NaN-safe)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_backlog_open
    ON backlog_intervals(opportunity_id, category) WHERE left_ts IS NULL;
CREATE INDEX IF NOT EXISTS ix_backlog_left ON backlog_intervals(left_ts);
"""

# Current (v4) schema — used to create a FRESH DB complete. `meta` (v2) holds per-scan coverage JSON;
# `snapshot_frames` (v3) holds the per-sport/per-frame evidence; `backlog_intervals` (v4) the durable
# 7-day lifecycle backlog.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,          -- original timestamp text (display)
    fetched_ts  REAL NOT NULL,          -- epoch seconds, UTC (ordering / retention / windows)
    meta        TEXT                    -- per-scan coverage metadata as JSON (v2; NULL for v1 rows)
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
""" + _FRAMES_SCHEMA + _BACKLOG_SCHEMA

# Read-path performance indexes (PR1). Kept OUTSIDE the versioned schema and (re)applied idempotently on
# every _connect via _ensure_indexes, so an existing v4 DB self-heals without a schema-version bump:
#   - (snapshot_id, bucket)        drives actionable_history_since's per-snapshot `WHERE snapshot_id=? AND
#                                  bucket='actionable'` (only ~9 of ~1126 rows/snapshot, vs expanding all).
#   - (snapshot_id, opportunity_id) drives latest_rows_by_id's `WHERE snapshot_id=? AND opportunity_id IN(..)`.
#   - snapshots(fetched_ts, id)    drives the MAX(fetched_ts)/window/order reads.
_PERF_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_opp_snap_bucket ON opportunities(snapshot_id, bucket);
CREATE INDEX IF NOT EXISTS ix_opp_snap_oid    ON opportunities(snapshot_id, opportunity_id);
CREATE INDEX IF NOT EXISTS ix_snap_ts         ON snapshots(fetched_ts, id);
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


# --- readiness probe -----------------------------------------------------------------
def db_writable(db_path: str | None = None) -> bool:
    """MIGRATION-FREE writability probe for readiness checks (PR S1, used by `/readyz`). Unlike
    `_connect`, this NEVER opens the database or runs `_migrate` — so a health probe can't migrate or
    create the production DB. It only asks the filesystem whether we *could* write: a file that exists is
    writable per `os.access`, otherwise its parent directory must exist and be writable so the app could
    create the file. `:memory:` is always writable."""
    resolved = db_path or config.SNAPSHOT_DB_PATH
    if resolved == ":memory:":
        return True
    if os.path.exists(resolved):
        return os.access(resolved, os.W_OK)
    parent = os.path.dirname(os.path.abspath(resolved))
    return os.path.isdir(parent) and os.access(parent, os.W_OK)


# --- connection / migration ----------------------------------------------------------
# File paths whose schema has been migrated + indexed this process. Migration (a PRAGMA check) and the
# read-path index build (3× CREATE INDEX IF NOT EXISTS — a writer-lock op) are durable on disk, so they
# only need to run on the FIRST connect to a path, NOT on every read (the ~1s dashboard poll, /metrics,
# /coverage, /readyz all open a connection). A fresh :memory: DB is a new database each connect, so it is
# NEVER cached and always initializes.
_initialized_paths: set[str] = set()


def _reset_init_cache() -> None:
    """Test hook: forget which DB paths have been schema-initialized (so a reused/recreated path re-migrates)."""
    _initialized_paths.clear()


def _connect(db_path: str | None) -> sqlite3.Connection:
    resolved = db_path or config.SNAPSHOT_DB_PATH
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    # auto_vacuum MUST be set before the DB header is written (the next write — `journal_mode = WAL` — fixes
    # it), so it goes FIRST. On a fresh DB this enables INCREMENTAL page reclamation; on an existing DB whose
    # header already exists it is silently ignored (a no-op until scripts/compact_store.py VACUUMs it). Harmless
    # for :memory:.
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets a reader proceed while a scan write holds the writer lock; busy_timeout bounds the wait on a
    # held lock instead of raising "database is locked" immediately. These are per-connection, so they run
    # every connect. (No-ops / harmless for :memory:.)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {int(config.SNAPSHOT_BUSY_TIMEOUT_MS)}")
    if resolved == ":memory:" or resolved not in _initialized_paths:
        _migrate(conn, resolved)
        _ensure_indexes(conn)
        if resolved != ":memory:":
            _initialized_paths.add(resolved)
    return conn


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Apply the read-path performance indexes idempotently (CREATE INDEX IF NOT EXISTS). Cheap no-op once
    they exist; the first connect to a large legacy DB pays the one-time build (the original is untouched —
    indexes are additive, so rollback is just DROP INDEX). Kept out of the versioned migration so an
    already-v4 DB self-heals without a schema-version bump."""
    conn.executescript(_PERF_INDEXES)


def _backup_before_migration(conn: sqlite3.Connection, db_path: str) -> None:
    """Snapshot the CURRENT (pre-upgrade) DB to ``<db>.pre-v<N>-backup`` via SQLite's online backup API
    (WAL-safe, captures the committed state) so an older file is never lost across a migration. Skipped for
    in-memory / unnamed databases (nothing on disk to preserve)."""
    if not db_path or db_path == ":memory:":
        return
    backup_path = f"{db_path}.pre-v{SCHEMA_VERSION}-backup"
    with sqlite3.connect(backup_path) as bck:
        conn.backup(bck)


def _reset_to_fresh(conn: sqlite3.Connection) -> None:
    """Drop everything and recreate the current schema at SCHEMA_VERSION (the fresh-DB fallback)."""
    for table in ("backlog_intervals", "snapshot_frames", "opportunities", "snapshots"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _migrate(conn: sqlite3.Connection, db_path: str = "") -> None:
    """Bring the file to SCHEMA_VERSION. A fresh (user_version 0) file is created at the current version;
    an older file is BACKED UP and walked forward step-by-step. If a forward step fails on a malformed
    file, we warn and reset to a fresh v3 DB — the original is preserved in the backup. A
    newer-than-supported file is a hard error (never downgrade-write)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"snapshot DB schema v{version} is newer than supported v{SCHEMA_VERSION}"
        )
    if version == 0:
        # Fresh DB: create the FULL current schema (incl. v2 `meta` + v3 `snapshot_frames`). auto_vacuum is
        # already set to INCREMENTAL in `_connect` (before the WAL header write) so it takes effect here.
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return
    # Upgrading an EXISTING older file: back it up first, then apply incremental forward steps.
    _backup_before_migration(conn, db_path)
    try:
        if version < 2:
            conn.execute("ALTER TABLE snapshots ADD COLUMN meta TEXT")   # v1 -> v2: per-scan coverage JSON
        if version < 3:
            conn.executescript(_FRAMES_SCHEMA)                            # v2 -> v3: per-frame evidence
        if version < 4:
            conn.executescript(_BACKLOG_SCHEMA)                           # v3 -> v4: durable interval backlog
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except sqlite3.DatabaseError as exc:
        # ASCII-only (Windows cp1252 consoles can't encode non-ASCII and would crash the print).
        print(f"WARNING: snapshot DB migration v{version}->v{SCHEMA_VERSION} failed ({exc}); starting a "
              f"fresh DB. The previous data is preserved at {db_path}.pre-v{SCHEMA_VERSION}-backup.")
        _reset_to_fresh(conn)


def _apply_retention(conn: sqlite3.Connection, retention_seconds: float | None = None) -> int:
    """Drop snapshots older than the retention window, measured back from the NEWEST stored snapshot.
    Returns the number of snapshots dropped."""
    keep = (_env_int("SNAPSHOT_RETENTION_SECONDS", config.SNAPSHOT_RETENTION_SECONDS)
            if retention_seconds is None else retention_seconds)
    newest = conn.execute("SELECT MAX(fetched_ts) AS m FROM snapshots").fetchone()["m"]
    if newest is None:
        return 0
    cutoff = newest - keep
    old = [r["id"] for r in conn.execute(
        "SELECT id FROM snapshots WHERE fetched_ts < ?", (cutoff,)).fetchall()]
    if not old:
        return 0
    marks = ",".join("?" * len(old))
    conn.execute(f"DELETE FROM snapshot_frames WHERE snapshot_id IN ({marks})", old)
    conn.execute(f"DELETE FROM opportunities WHERE snapshot_id IN ({marks})", old)
    conn.execute(f"DELETE FROM snapshots WHERE id IN ({marks})", old)
    return len(old)


def _db_size_bytes(db_path: str) -> int | None:
    """On-disk size of the DB file, or None for in-memory / not-yet-flushed databases."""
    if not db_path or db_path == ":memory:":
        return None
    try:
        return os.path.getsize(db_path)
    except OSError:
        return None


def footprint_stats(db_path: str | None = None) -> dict[str, Any]:
    """Cheap on-disk footprint counters for /metrics monitoring (so the owner can SEE retention/vacuum
    working): DB + WAL file bytes, snapshot/opportunity row counts, and SQLite page/freelist counts. All
    fast (file stat + indexed COUNT + instant PRAGMAs). Never raises — returns what it can."""
    resolved = db_path or config.SNAPSHOT_DB_PATH
    out: dict[str, Any] = {
        "db_size_bytes": _db_size_bytes(resolved),
        "wal_size_bytes": _db_size_bytes(resolved + "-wal") if resolved != ":memory:" else None,
    }
    try:
        conn = _connect(db_path)
        try:
            out["snapshot_count"] = conn.execute("SELECT COUNT(*) AS c FROM snapshots").fetchone()["c"]
            out["opportunity_rows"] = conn.execute("SELECT COUNT(*) AS c FROM opportunities").fetchone()["c"]
            out["page_count"] = conn.execute("PRAGMA page_count").fetchone()[0]
            out["freelist_pages"] = conn.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _log.warning("footprint_stats query failed: %s", exc)
    return out


def _frame_bearing_snapshots(conn: sqlite3.Connection) -> list[int]:
    """Snapshot ids that currently have at least one frame, NEWEST first (by snapshot id)."""
    return [r["snapshot_id"] for r in conn.execute(
        "SELECT DISTINCT snapshot_id FROM snapshot_frames ORDER BY snapshot_id DESC").fetchall()]


def _frame_bytes(conn: sqlite3.Connection) -> int:
    """Total logical size of all retained frame blobs (sum of rows_json lengths)."""
    return conn.execute("SELECT COALESCE(SUM(LENGTH(rows_json)), 0) AS b FROM snapshot_frames").fetchone()["b"]


def _apply_frame_retention(conn: sqlite3.Connection, db_path: str) -> dict[str, Any]:
    """Heavy-frame tier (v3 size-tier): keep frames only for the latest ``SNAPSHOT_FRAME_RETENTION_N``
    snapshots, then, while the retained frame bytes still exceed ``SNAPSHOT_FRAME_DB_BUDGET_BYTES`` and more
    than one frame-bearing snapshot remains, evict the OLDEST remaining frame-snapshot. Only frames are
    dropped — the snapshots + their lean opportunities stay (the evicted ones report
    ``frame_status == "expired"``).

    Budgeting is on the logical blob length, not the file size: SQLite reuses freed pages, so a DELETE does
    not shrink the file (reported as ``db_size_bytes`` for observability, never the loop condition).
    Returns ``{frame_snapshots_evicted, frame_bytes, db_size_bytes}``."""
    keepers = _frame_bearing_snapshots(conn)                    # newest -> oldest
    kept = keepers[:config.SNAPSHOT_FRAME_RETENTION_N]
    evict = list(keepers[config.SNAPSHOT_FRAME_RETENTION_N:])   # tier 1: everything past the latest N

    budget = config.SNAPSHOT_FRAME_DB_BUDGET_BYTES
    if budget is not None and kept:
        sizes = {sid: conn.execute(
            "SELECT COALESCE(SUM(LENGTH(rows_json)),0) AS b FROM snapshot_frames WHERE snapshot_id = ?",
            (sid,)).fetchone()["b"] for sid in kept}
        retained = sum(sizes.values())
        while retained > budget and len(kept) > 1:             # tier 2: drop the oldest kept until ≤ budget
            sid = kept.pop()                                   # `kept` is newest->oldest, so pop() = oldest
            evict.append(sid)
            retained -= sizes[sid]

    if evict:
        marks = ",".join("?" * len(evict))
        conn.execute(f"DELETE FROM snapshot_frames WHERE snapshot_id IN ({marks})", evict)

    stats = {"frame_snapshots_evicted": len(evict), "frame_bytes": _frame_bytes(conn),
             "db_size_bytes": _db_size_bytes(db_path)}
    if evict:
        print(f"snapshot frame retention: evicted {len(evict)} frame-snapshot(s); "
              f"retained frame bytes={stats['frame_bytes']}, db size={stats['db_size_bytes']} bytes")
    return stats


def _apply_opp_retention(conn: sqlite3.Connection) -> dict[str, Any]:
    """Lean opportunity tier: keep FULL opportunity JSON for the latest N snapshots; for OLDER snapshots,
    drop the heavy SPECULATIVE/diagnostic buckets' rows (``config.SNAPSHOT_OPP_TIER_BUCKETS`` —
    no_structure / data_quality / near_miss, ~61% of stored bytes) while preserving their per-bucket COUNTS
    in ``snapshots.meta`` (``tiered_opp_counts``) for transparency. ``store.latest()`` is NEVER affected (it
    reads the newest snapshot, always inside the latest-N full set). Idempotent: only acts on snapshots that
    still carry tiered-bucket rows. Engine OUTPUT is untouched — this only trims what is PERSISTED for OLD
    snapshots. Safe vs lifecycle/backlog: the recently-actionable backlog reads only ``bucket='actionable'``
    history (never tiered) and ``blocked_change`` uses the latest two snapshots (inside latest-N)."""
    if not _env_flag("SNAPSHOT_OPP_TIER_ENABLED", config.SNAPSHOT_OPP_TIER_ENABLED):
        return {"opp_snapshots_tiered": 0}
    buckets = tuple(config.SNAPSHOT_OPP_TIER_BUCKETS or ())
    n = max(1, _env_int("SNAPSHOT_OPP_FULL_RETENTION_N", config.SNAPSHOT_OPP_FULL_RETENTION_N))
    if not buckets:
        return {"opp_snapshots_tiered": 0}
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM snapshots ORDER BY fetched_ts DESC, id DESC").fetchall()]
    older = ids[n:]                                   # everything past the latest N (newest-first slice)
    if not older:
        return {"opp_snapshots_tiered": 0}
    bmarks = ",".join("?" * len(buckets))
    tiered = 0
    for sid in older:
        counts = conn.execute(
            f"SELECT bucket, COUNT(*) AS c FROM opportunities "
            f"WHERE snapshot_id = ? AND bucket IN ({bmarks}) GROUP BY bucket",
            (sid, *buckets)).fetchall()
        if not counts:
            continue                                  # already tiered (idempotent)
        row = conn.execute("SELECT meta FROM snapshots WHERE id = ?", (sid,)).fetchone()
        meta: dict[str, Any] = {}
        if row and row["meta"]:
            try:
                meta = json.loads(row["meta"])
            except (ValueError, TypeError):
                meta = {}
        tc = dict(meta.get("tiered_opp_counts") or {})
        for cr in counts:
            tc[cr["bucket"]] = cr["c"]
        meta["tiered_opp_counts"] = tc
        meta["opp_tiered"] = True
        conn.execute("UPDATE snapshots SET meta = ? WHERE id = ?", (json.dumps(meta), sid))
        conn.execute(
            f"DELETE FROM opportunities WHERE snapshot_id = ? AND bucket IN ({bmarks})", (sid, *buckets))
        tiered += 1
    return {"opp_snapshots_tiered": tiered}


def _run_db_housekeeping(conn: sqlite3.Connection, db_path: str) -> dict[str, Any]:
    """Reclaim disk after retention/tier deletes: a throttled ``PRAGMA incremental_vacuum`` (only reclaims
    when the DB was created with auto_vacuum=INCREMENTAL — a harmless no-op on legacy DBs until compacted)
    and a WAL ``checkpoint(TRUNCATE)`` so the -wal file doesn't grow unbounded on a long-running server.
    Both env-gated for rollback. Runs in the post-commit housekeeping transaction (off the writer-critical
    path); failures are logged and swallowed so housekeeping can never lose or block a committed snapshot."""
    stats: dict[str, Any] = {}
    if _env_flag("SNAPSHOT_INCREMENTAL_VACUUM_ENABLED", config.SNAPSHOT_INCREMENTAL_VACUUM_ENABLED):
        try:
            conn.execute("PRAGMA incremental_vacuum")
            stats["incremental_vacuum"] = True
        except sqlite3.Error as exc:
            _log.warning("incremental_vacuum skipped: %s", exc)
    if _env_flag("SNAPSHOT_WAL_TRUNCATE_ENABLED", config.SNAPSHOT_WAL_TRUNCATE_ENABLED):
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            stats["wal_truncate"] = True
        except sqlite3.Error as exc:
            _log.warning("wal_checkpoint(TRUNCATE) skipped: %s", exc)
    stats["db_size_bytes"] = _db_size_bytes(db_path)
    return stats


def frame_status(snapshot_id: int, *, db_path: str | None = None) -> str:
    """Honest availability of a snapshot's heavy evidence frames (for the detail UI, PR 24):

    - ``"present"`` — the snapshot has frames.
    - ``"expired"`` — no frames AND the snapshot is older than the latest ``SNAPSHOT_FRAME_RETENTION_N``
      frame-bearing snapshots → its evidence was aged out by retention.
    - ``"absent"``  — no frames AND it is within the latest-N window → evidence was never captured for this
      scan (an opps-only write, or a scan from before frame persistence existed).
    """
    conn = _connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM snapshot_frames WHERE snapshot_id = ? LIMIT 1", (snapshot_id,)).fetchone()
        if has is not None:
            return "present"
        recent = {r["snapshot_id"] for r in conn.execute(
            "SELECT DISTINCT snapshot_id FROM snapshot_frames "
            "ORDER BY snapshot_id DESC LIMIT ?", (config.SNAPSHOT_FRAME_RETENTION_N,)).fetchall()}
        newest_kept = min(recent) if recent else None
    finally:
        conn.close()
    # Older than the oldest still-kept frame-snapshot -> its frames were aged out.
    if newest_kept is not None and snapshot_id < newest_kept:
        return "expired"
    return "absent"


def _load(conn: sqlite3.Connection, clause: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Read snapshots (+ their opportunity rows, JSON-expanded) matching an ORDER/WHERE clause."""
    snaps = conn.execute(
        f"SELECT id, fetched_at, fetched_ts, meta FROM snapshots {clause}", params).fetchall()
    out: list[dict[str, Any]] = []
    for s in snaps:
        rows = conn.execute(
            "SELECT data FROM opportunities WHERE snapshot_id = ? ORDER BY rowid", (s["id"],)
        ).fetchall()
        out.append({
            "snapshot_id": s["id"],
            "fetched_at": s["fetched_at"],
            "fetched_ts": s["fetched_ts"],
            "meta": json.loads(s["meta"]) if s["meta"] else None,
            "opportunities": [json.loads(r["data"]) for r in rows],
        })
    return out


def _frame_rows(frame: dict[str, Any]) -> tuple[Any, Any, Any, str, int]:
    """Flatten one frame spec ``{sport, frame_type, schema_version, rows}`` into the INSERT tuple
    (sport, frame_type, schema_version, rows_json, row_count). ``rows`` is a DataFrame or dict-iterable;
    it is JSON-serialized NaN-safely (reusing `_jsonable`)."""
    rows = [_jsonable(r) for r in _records(frame.get("rows"))]
    return (frame.get("sport"), frame.get("frame_type"), frame.get("schema_version"),
            json.dumps(rows), len(rows))


# --- durable interval backlog (v4) ---------------------------------------------------
def _num_opt(v: Any) -> float | None:
    """A finite float or None (None / NaN / non-numeric -> None), for metric comparisons."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _max_opt(a: Any, b: Any) -> float | None:
    """max of two optional numbers, ignoring None — None when both are None. Used to grow per-interval
    extremes (best ROI / best best-case / least-negative worst-case) as a lifecycle accumulates."""
    na, nb = _num_opt(a), _num_opt(b)
    if na is None:
        return nb
    if nb is None:
        return na
    return na if na >= nb else nb


def _tracked_category(row: dict[str, Any]) -> str | None:
    """The durable backlog category for a row, derived STORE-SIDE from its `bucket` (nothing is added to
    the public unified schema). None -> not tracked. Single-sourced in `config.BACKLOG_CATEGORY_BY_BUCKET`."""
    bucket = _promoted(row, "bucket")
    return config.BACKLOG_CATEGORY_BY_BUCKET.get(bucket) if bucket else None


def _maintain_backlog_intervals(conn: sqlite3.Connection, records: list[dict[str, Any]], ts: float) -> None:
    """Advance the durable interval backlog for one snapshot (called inside the write transaction):
    open/advance an interval for each tracked (opportunity_id, category) present now, close intervals that
    dropped out, then drop intervals closed longer than `BACKLOG_RETENTION_SECONDS` ago. Reappearance opens
    a NEW interval (no open interval exists once the previous one closed), so distinct lifecycles never
    merge."""
    # The tracked set for THIS snapshot: last write wins on a duplicate (opportunity_id, category).
    tracked: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records:
        category = _tracked_category(r)
        if not category:
            continue
        oid = _promoted(r, "opportunity_id")
        if not oid:
            continue
        tracked[(oid, category)] = r

    touched: list[int] = []
    for (oid, category), r in tracked.items():
        roi = _num_opt(r.get("roi_pct"))
        best = _num_opt(r.get("best_case_profit_c"))
        worst = _num_opt(r.get("worst_case_profit_c"))
        legs = r.get("legs")
        legs_json = json.dumps(_clean(legs)) if legs is not None else None
        data_json = json.dumps(_jsonable(r))
        common = (
            _promoted(r, "bucket"), _promoted(r, "status"),
            _clean(r.get("sport")), _clean(r.get("name")), _clean(r.get("url")),
            _clean(r.get("settlement_caveat")), legs_json, data_json,
        )
        open_row = conn.execute(
            "SELECT id, peak_roi_pct, best_case_profit_c, worst_case_profit_c FROM backlog_intervals "
            "WHERE opportunity_id = ? AND category = ? AND left_ts IS NULL", (oid, category)).fetchone()
        if open_row is not None:
            conn.execute(
                "UPDATE backlog_intervals SET last_seen_ts = ?, peak_roi_pct = ?, best_case_profit_c = ?, "
                "worst_case_profit_c = ?, last_bucket = ?, last_status = ?, sport = ?, name = ?, url = ?, "
                "last_settlement_caveat = ?, last_legs = ?, data = ? WHERE id = ?",
                (ts, _max_opt(open_row["peak_roi_pct"], roi),
                 _max_opt(open_row["best_case_profit_c"], best),
                 _max_opt(open_row["worst_case_profit_c"], worst), *common, open_row["id"]))
            touched.append(open_row["id"])
        else:
            cur = conn.execute(
                "INSERT INTO backlog_intervals "
                "(opportunity_id, category, first_seen_ts, last_seen_ts, left_ts, peak_roi_pct, "
                "best_case_profit_c, worst_case_profit_c, last_bucket, last_status, sport, name, url, "
                "last_settlement_caveat, last_legs, data) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (oid, category, ts, ts, roi, best, worst, *common))
            touched.append(cur.lastrowid)

    # Close-out: any interval still open but NOT advanced this snapshot dropped out -> stamp left_ts.
    if touched:
        marks = ",".join("?" * len(touched))
        conn.execute(
            f"UPDATE backlog_intervals SET left_ts = ? WHERE left_ts IS NULL AND id NOT IN ({marks})",
            (ts, *touched))
    else:
        conn.execute("UPDATE backlog_intervals SET left_ts = ? WHERE left_ts IS NULL", (ts,))

    # Retention: drop intervals closed longer than the window ago (measured from this newest write).
    conn.execute("DELETE FROM backlog_intervals WHERE left_ts IS NOT NULL AND left_ts < ?",
                 (ts - config.BACKLOG_RETENTION_SECONDS,))


_BACKLOG_FIELDS = (
    "id", "opportunity_id", "category", "sport", "name", "url", "first_seen_ts", "last_seen_ts",
    "left_ts", "last_bucket", "last_status", "peak_roi_pct", "best_case_profit_c", "worst_case_profit_c",
    "last_settlement_caveat",
)


def backlog_intervals(*, category: str | None = None, include_open: bool = True, days: float | None = None,
                      db_path: str | None = None) -> list[dict[str, Any]]:
    """Read the durable interval backlog (v4), most-recent-activity first. `category` narrows to one
    tracked category; `include_open=False` returns only CLOSED intervals; `days` windows to that many days
    of activity (capped at `BACKLOG_RETENTION_SECONDS`), measured from the newest activity. Each row is the
    promoted columns plus `duration_s`, `last_legs`, and the full `data` (JSON-expanded)."""
    where: list[str] = []
    params: list[Any] = []
    if category is not None:
        where.append("category = ?")
        params.append(category)
    if not include_open:
        where.append("left_ts IS NOT NULL")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = _connect(db_path)
    try:
        if days is not None:
            cap = config.BACKLOG_RETENTION_SECONDS
            window = min(float(days) * 86400.0, cap)
            newest = conn.execute(
                "SELECT MAX(COALESCE(left_ts, last_seen_ts)) AS m FROM backlog_intervals").fetchone()["m"]
            if newest is not None:
                cutoff = newest - window
                where.append("COALESCE(left_ts, last_seen_ts) >= ?")
                params.append(cutoff)
                clause = " WHERE " + " AND ".join(where)
        rows = conn.execute(
            f"SELECT {', '.join(_BACKLOG_FIELDS)}, last_legs, data FROM backlog_intervals{clause} "
            "ORDER BY COALESCE(left_ts, last_seen_ts) DESC, id DESC", tuple(params)).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = {k: r[k] for k in _BACKLOG_FIELDS}
        first, last = r["first_seen_ts"], r["last_seen_ts"]
        d["duration_s"] = (last - first) if (first is not None and last is not None) else None
        d["is_open"] = r["left_ts"] is None
        d["last_legs"] = json.loads(r["last_legs"]) if r["last_legs"] else None
        d["data"] = json.loads(r["data"]) if r["data"] else None
        out.append(d)
    return out


# --- public API ----------------------------------------------------------------------
def write_snapshot(fetched_at: Any, opps: Any, *, meta: Any = None, frames: Any = None,
                   db_path: str | None = None) -> int:
    """Persist one snapshot of opportunity rows and return its snapshot id.

    `fetched_at` is the refresh timestamp (datetime / ISO / load_contracts text / epoch). `opps` is a
    pandas DataFrame or an iterable of dict rows (consistency checks and/or dutch-book findings). `meta`
    (v2) is optional per-scan coverage metadata, stored as JSON. `frames` (v3) is an optional iterable of
    ``{sport, frame_type, schema_version, rows}`` evidence frames written into `snapshot_frames` in the
    SAME transaction (scan = one transaction). An empty `opps` still records a snapshot (a refresh with no
    opportunities is itself information). Retention is applied after the write."""
    records = _records(opps)
    ts = _to_epoch(fetched_at)
    text = _to_text(fetched_at)
    meta_json = json.dumps(meta) if meta is not None else None
    conn = _connect(db_path)
    try:
        sid = conn.execute(
            "INSERT INTO snapshots (fetched_at, fetched_ts, meta) VALUES (?, ?, ?)", (text, ts, meta_json)
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
                    # Stamp the assigned snapshot_id into the row JSON (PR 21a) so every read/exported row
                    # knows which snapshot it came from.
                    json.dumps({**_jsonable(r), "snapshot_id": sid}),
                )
                for r in records
            ],
        )
        if frames:
            conn.executemany(
                "INSERT INTO snapshot_frames "
                "(snapshot_id, sport, frame_type, schema_version, rows_json, row_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(sid, *_frame_rows(f)) for f in frames],
            )
        _maintain_backlog_intervals(conn, records, ts)          # durable tier: 7-day lifecycle intervals
        conn.commit()                                            # snapshot is durable + visible to readers NOW
        # Housekeeping runs in a SEPARATE short transaction AFTER the snapshot commit, so readers aren't held
        # behind the retention scan + per-snapshot size queries while the writer lock covers the insert. The
        # snapshot is already persisted; a retention hiccup can't lose it.
        _apply_retention(conn)                                   # lean tier: time-based whole-snapshot drop
        _apply_frame_retention(conn, db_path or config.SNAPSHOT_DB_PATH)   # heavy tier: latest-N + size budget
        _apply_opp_retention(conn)                               # opp tier: drop OLD speculative-bucket rows
        conn.commit()
        # DB-level reclamation (incremental_vacuum + WAL truncate) is the heaviest step, so it runs only every
        # Nth snapshot — in its OWN transaction after the housekeeping commit, never blocking the writer path.
        global _snapshots_written
        _snapshots_written += 1
        every_n = max(1, _env_int("SNAPSHOT_HOUSEKEEPING_EVERY_N", config.SNAPSHOT_HOUSEKEEPING_EVERY_N))
        if _snapshots_written % every_n == 0:
            _run_db_housekeeping(conn, db_path or config.SNAPSHOT_DB_PATH)
            conn.commit()
        return sid
    finally:
        conn.close()


def load_frames(snapshot_id: int, *, sport: str | None = None, frame_type: str | None = None,
                db_path: str | None = None) -> list[dict[str, Any]]:
    """Load a snapshot's evidence frames (v3), optionally narrowed to one `sport` and/or `frame_type`
    (partial-loadable — the UI fetches only the frame it needs). Each result is
    ``{sport, frame_type, schema_version, row_count, rows}`` with `rows` JSON-expanded. Empty when the
    snapshot has no matching frames (incl. old snapshots written before v3)."""
    clause = "WHERE snapshot_id = ?"
    params: list[Any] = [snapshot_id]
    if sport is not None:
        clause += " AND sport = ?"
        params.append(sport)
    if frame_type is not None:
        clause += " AND frame_type = ?"
        params.append(frame_type)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT sport, frame_type, schema_version, row_count, rows_json "
            f"FROM snapshot_frames {clause} ORDER BY rowid", tuple(params)
        ).fetchall()
    finally:
        conn.close()
    return [{
        "sport": r["sport"], "frame_type": r["frame_type"], "schema_version": r["schema_version"],
        "row_count": r["row_count"], "rows": json.loads(r["rows_json"]),
    } for r in rows]


def latest_snapshot_id(db_path: str | None = None) -> int | None:
    """The id of the single newest snapshot, or None if the store is empty. A lightweight indexed lookup
    (no JSON expansion / no opportunity deserialize) — the cheap "has a new snapshot landed?" probe for
    the dashboard poll loop. This is the SOURCE OF TRUTH for snapshot freshness (the in-memory
    `scan_manager` id is only an optimization hint that can go stale on restart / db-path change)."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM snapshots ORDER BY fetched_ts DESC, id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


def latest(db_path: str | None = None) -> dict[str, Any] | None:
    """The single newest snapshot (or None if the store is empty) — what the read endpoints serve."""
    conn = _connect(db_path)
    try:
        snaps = _load(conn, "ORDER BY fetched_ts DESC, id DESC LIMIT 1")
    finally:
        conn.close()
    return snaps[0] if snaps else None


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


def _load_actionable(conn: sqlite3.Connection, clause: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Like `_load` but each snapshot's `opportunities` is filtered to ``bucket='actionable'`` (JSON-expand
    ONLY those, ~9 of ~1126/snapshot). Returns EVERY snapshot matching `clause` — with ``opportunities=[]``
    when none are actionable — so the lifecycle timeline (left_ts / duration) over the full snapshot
    sequence is preserved."""
    snaps = conn.execute(
        f"SELECT id, fetched_at, fetched_ts, meta FROM snapshots {clause}", params).fetchall()
    out: list[dict[str, Any]] = []
    expanded = 0
    for s in snaps:
        rows = conn.execute(
            "SELECT data FROM opportunities WHERE snapshot_id = ? AND bucket = 'actionable' ORDER BY rowid",
            (s["id"],)).fetchall()
        expanded += len(rows)
        out.append({
            "snapshot_id": s["id"],
            "fetched_at": s["fetched_at"],
            "fetched_ts": s["fetched_ts"],
            "meta": json.loads(s["meta"]) if s["meta"] else None,
            "opportunities": [json.loads(r["data"]) for r in rows],
        })
    _log.debug("actionable_history: snapshots=%d json_rows_expanded=%d", len(out), expanded)
    return out


def actionable_history_since(window: Any, db_path: str | None = None) -> list[dict[str, Any]]:
    """`snapshots_since` narrowed to actionable rows: every snapshot within `window` of the NEWEST stored
    snapshot (oldest -> newest, same newest-relative boundary as `snapshots_since`), each carrying only its
    ``bucket='actionable'`` opportunities (``[]`` when none). The cheap source for the §10 backlog and the
    persistent §8 alert — both consume only actionable rows — avoiding a full ~1M-row JSON expansion.
    Pair with `latest_rows_by_id` for the current state of opportunities that have since left actionable."""
    seconds = window.total_seconds() if isinstance(window, timedelta) else float(window)
    conn = _connect(db_path)
    try:
        newest = conn.execute("SELECT MAX(fetched_ts) AS m FROM snapshots").fetchone()["m"]
        if newest is None:
            return []
        cutoff = newest - seconds
        return _load_actionable(conn, "WHERE fetched_ts >= ? ORDER BY fetched_ts ASC, id ASC", (cutoff,))
    finally:
        conn.close()


# SQLite's default host-parameter limit is 999; chunk IN(...) lists well under it (1 slot is the snapshot_id).
_SQLITE_MAX_VARS = 900


def latest_rows_by_id(ids: Any, db_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Full current rows (ANY bucket), keyed by `opportunity_id`, for `ids`, from the SINGLE latest
    snapshot. Resolves the latest `snapshot_id` ONCE then reads rows from that exact id, so a scan write
    landing mid-call can never blend two snapshots. Returns ``{}`` on empty/blank `ids`. Chunks the
    ``IN (...)`` list under the SQLite host-parameter cap and merges the results."""
    want = [i for i in dict.fromkeys(ids) if i]   # dedup, drop falsy, preserve order
    if not want:
        return {}
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM snapshots ORDER BY fetched_ts DESC, id DESC LIMIT 1").fetchone()
        if row is None:
            return {}
        sid = row["id"]
        out: dict[str, dict[str, Any]] = {}
        for start in range(0, len(want), _SQLITE_MAX_VARS):
            chunk = want[start:start + _SQLITE_MAX_VARS]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT data FROM opportunities WHERE snapshot_id = ? AND opportunity_id IN ({marks})",
                (sid, *chunk)).fetchall()
            for r in rows:
                d = json.loads(r["data"])
                oid = d.get("opportunity_id")
                if oid is not None and oid not in out:
                    out[oid] = d
        _log.debug("latest_rows_by_id: requested=%d resolved=%d snapshot_id=%s", len(want), len(out), sid)
        return out
    finally:
        conn.close()


def contract_frames_since(window: Any, db_path: str | None = None) -> list[dict[str, Any]]:
    """The CONTRACT-frame rows for each snapshot within `window` of the newest, oldest -> newest, for the
    snapshots that still RETAIN frames (heavy frames are kept only for the latest N — `frame_status`).
    Returns ``[{snapshot_id, fetched_ts, rows}]`` with `rows` the contracts rows concatenated across
    sports. A lightweight blob scan (bounded by frame retention) for the 'most volatile now' message —
    NOT a time-series store. Empty when nothing within the window still has contract frames."""
    seconds = window.total_seconds() if isinstance(window, timedelta) else float(window)
    conn = _connect(db_path)
    try:
        newest = conn.execute("SELECT MAX(fetched_ts) AS m FROM snapshots").fetchone()["m"]
        if newest is None:
            return []
        rows = conn.execute(
            "SELECT s.id AS sid, s.fetched_ts AS ts, f.rows_json AS rj FROM snapshot_frames f "
            "JOIN snapshots s ON s.id = f.snapshot_id "
            "WHERE f.frame_type = 'contracts' AND s.fetched_ts >= ? "
            "ORDER BY s.fetched_ts ASC, s.id ASC, f.rowid ASC", (newest - seconds,)).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        parsed = json.loads(r["rj"])
        if out and out[-1]["snapshot_id"] == r["sid"]:     # same snapshot, another sport's frame
            out[-1]["rows"].extend(parsed)
        else:
            out.append({"snapshot_id": r["sid"], "fetched_ts": r["ts"], "rows": list(parsed)})
    return out
