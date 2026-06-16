"""One-time snapshot-store compaction (footprint remediation).

WHY: SQLite never shrinks a DB file on its own — `_apply_retention` deletes old snapshots but the freed
pages stay in the file (a long-running server steady-stated to ~28 GB). New DBs created after this change
are `auto_vacuum=INCREMENTAL` and self-reclaim, but an EXISTING bloated `snapshots.db` was created with
`auto_vacuum=NONE`, which can only be changed by a full VACUUM. This script:

  1. backs up the DB (+ `-wal`/`-shm`) and verifies the backup opens,
  2. optionally prunes to the current retention window first (so VACUUM has freed pages to reclaim),
  3. sets `PRAGMA auto_vacuum=INCREMENTAL` and runs `VACUUM` (rebuilds the file compactly and turns on
     incremental reclamation going forward),
  4. reports before/after sizes.

VACUUM rebuilds through a temporary file and can need up to ~2x the DB size in free disk — the script
checks and refuses if there isn't enough. ALL tables (incl. `backlog_intervals`) are preserved by VACUUM;
nothing is dropped. Run with the server STOPPED.

Usage:
    python scripts/compact_store.py                 # backup + VACUUM the default snapshots.db
    python scripts/compact_store.py --prune         # also apply retention first (more reclaim)
    python scripts/compact_store.py --db other.db --no-backup
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
import store  # noqa: E402


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _backup(db: str) -> str:
    """Copy the DB and any sidecar WAL/SHM next to it, then verify the copy opens. Returns the backup path."""
    dst = db + ".pre-compact-backup"
    shutil.copy2(db, dst)
    for ext in ("-wal", "-shm"):
        if os.path.exists(db + ext):
            shutil.copy2(db + ext, dst + ext)
    con = sqlite3.connect(dst)                      # verify it opens + has the snapshots table
    try:
        con.execute("SELECT COUNT(*) FROM snapshots").fetchone()
    finally:
        con.close()
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="Compact (VACUUM) the snapshot store and enable auto_vacuum.")
    ap.add_argument("--db", default=config.SNAPSHOT_DB_PATH, help="snapshot DB path")
    ap.add_argument("--no-backup", action="store_true", help="skip the safety backup (not recommended)")
    ap.add_argument("--prune", action="store_true",
                    help="apply retention (drop snapshots older than SNAPSHOT_RETENTION_SECONDS) before VACUUM")
    args = ap.parse_args()

    db = args.db
    if not os.path.exists(db):
        print(f"ERROR: {db} does not exist")
        return 2

    before = _size(db)
    print(f"DB: {db}")
    print(f"size before: {before/1e9:.2f} GB")

    free = shutil.disk_usage(os.path.dirname(os.path.abspath(db))).free
    if free < before * 2:
        print(f"ERROR: VACUUM may need ~2x the DB size in free disk ({before*2/1e9:.2f} GB); "
              f"only {free/1e9:.2f} GB free. Free space or move the DB, then retry.")
        return 3

    if not args.no_backup:
        bk = _backup(db)
        print(f"backup written + verified: {bk} ({_size(bk)/1e9:.2f} GB)")

    # Use a RAW connection (not store._connect) so we control the pragmas and don't re-init/migrate.
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row          # store._apply_retention reads rows by column name
    try:
        if args.prune:
            con.execute("PRAGMA foreign_keys = ON")
            dropped = store._apply_retention(con)
            con.commit()
            print(f"retention: dropped {dropped} snapshot(s) older than the window")
        print("setting auto_vacuum=INCREMENTAL and running VACUUM (this can take a while)...")
        con.execute("PRAGMA auto_vacuum = INCREMENTAL")
        con.execute("VACUUM")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        av = con.execute("PRAGMA auto_vacuum").fetchone()[0]
        con.commit()
    finally:
        con.close()

    after = _size(db)
    print(f"size after:  {after/1e9:.2f} GB  (auto_vacuum={'INCREMENTAL' if av == 2 else av})")
    saved = before - after
    print(f"reclaimed:   {saved/1e9:.2f} GB ({100*saved/before:.0f}%)" if before else "reclaimed: n/a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
