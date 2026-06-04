"""In-process engine accessors for the NiceGUI dashboard (Stage 5).

Thin wrappers over the pure engine (`store` / `lifecycle` / `scanner`) so the dashboard stays declarative
and these can be unit-tested without NiceGUI. The dashboard calls the engine IN-PROCESS (no self-HTTP);
the REST `api.py` is a sibling consumer for external clients. `db_path=None` uses `config.SNAPSHOT_DB_PATH`
(the live store); tests pass a tmp path.

Scan scope is honest: the scan fetch is `api.fetch_dep()` → **core series only** (`scan_all=False`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import config
import data
import kalshi_client
import lifecycle
import scanner
import store
from api import fetch_dep


def latest_opportunities(db_path: str | None = None) -> list[dict[str, Any]]:
    """All opportunities in the latest snapshot (already ranked), or [] when the store is empty."""
    snap = store.latest(db_path=db_path)
    return list(snap.get("opportunities") or []) if snap else []


def opportunities_in_bucket(bucket: str, db_path: str | None = None) -> list[dict[str, Any]]:
    return [o for o in latest_opportunities(db_path=db_path) if o.get("bucket") == bucket]


def backlog(window_s: float, db_path: str | None = None) -> list[dict[str, Any]]:
    """Recently-actionable backlog over the window (§10)."""
    return lifecycle.recently_actionable(store.snapshots_since(window_s, db_path=db_path))


def alerts(persistence_s: float | None = None, db_path: str | None = None) -> dict[str, list]:
    """New-actionable (§8) + blocked-change (§9), diffed over the two latest snapshots."""
    pair = store.latest_two(db_path=db_path)
    prev = pair[0] if len(pair) == 2 else None
    cur = pair[-1] if pair else None
    if persistence_s is None:
        new_rows = lifecycle.new_actionable(prev, cur)
    else:
        history = store.snapshots_since(config.SNAPSHOT_RETENTION_SECONDS, db_path=db_path)
        new_rows = lifecycle.persisting_new_actionable(history, persistence_s, now_ts=None)
    return {"new_actionable": new_rows, "blocked_changes": lifecycle.blocked_change(prev, cur)}


def coverage(db_path: str | None = None) -> dict[str, Any]:
    """Latest snapshot's coverage + live data age/stale; honest when the store is empty or meta-less."""
    snap = store.latest(db_path=db_path)
    if snap is None:
        return {"meta_present": False, "fetched_at": None, "data_age_seconds": None, "stale": False,
                "opportunities": 0, "scanned": 0, "loaded": 0, "failed": 0, "excluded": 0}
    age = data.data_age_seconds(snap["fetched_at"])
    meta = snap.get("meta") or {}
    return {
        "meta_present": bool(snap.get("meta")),
        "fetched_at": snap["fetched_at"],
        "data_age_seconds": age,
        "stale": data.is_stale(age, config.STALE_AFTER_SECONDS),
        "opportunities": len(snap.get("opportunities") or []),
        "scanned": meta.get("scanned", 0), "loaded": meta.get("loaded", 0),
        "failed": meta.get("failed", 0), "excluded": meta.get("excluded", 0),
    }


def run_scan_now(db_path: str | None = None) -> dict[str, Any]:
    """Run a fresh scan (core series, all sports) and persist it with coverage; returns the coverage.
    Manual trigger — always runs (no TTL guard; that guard is the API's POST /scan concern)."""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    unified, cov, frames = scanner.run_scan(
        fetch_dep(), fetched_at=fetched_at, request_count=kalshi_client.request_count)
    store.write_snapshot(fetched_at, unified, meta=cov, frames=frames, db_path=db_path)
    return cov
