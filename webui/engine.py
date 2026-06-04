"""In-process engine accessors for the NiceGUI dashboard (Stage 5).

Thin wrappers over the pure engine (`store` / `lifecycle` / `scanner`) so the dashboard stays declarative
and these can be unit-tested without NiceGUI. The dashboard calls the engine IN-PROCESS (no self-HTTP);
the REST `api.py` is a sibling consumer for external clients. `db_path=None` uses `config.SNAPSHOT_DB_PATH`
(the live store); tests pass a tmp path.

Scan scope is honest: the scan fetch is `api.fetch_dep()` → **core series only** (`scan_all=False`).
"""
from __future__ import annotations

from typing import Any

import config
import consistency
import data
import lifecycle
import scan_manager
import store
from api import _scan_run_fn, _scan_write_fn, fetch_dep


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
        return {"meta_present": False, "snapshot_id": None, "fetched_at": None, "data_age_seconds": None,
                "stale": False, "opportunities": 0, "scanned": 0, "loaded": 0, "failed": 0, "excluded": 0}
    age = data.data_age_seconds(snap["fetched_at"])
    meta = snap.get("meta") or {}
    return {
        "meta_present": bool(snap.get("meta")),
        "snapshot_id": snap.get("snapshot_id"),
        "fetched_at": snap["fetched_at"],
        "data_age_seconds": age,
        "stale": data.is_stale(age, config.STALE_AFTER_SECONDS),
        "opportunities": len(snap.get("opportunities") or []),
        "scanned": meta.get("scanned", 0), "loaded": meta.get("loaded", 0),
        "failed": meta.get("failed", 0), "excluded": meta.get("excluded", 0),
        # Volume counters + Kalshi requests (PR 21a) — distinct from the opportunity count.
        "contracts_scanned": meta.get("contracts_scanned", 0), "checks_tested": meta.get("checks_tested", 0),
        "kalshi_requests": meta.get("kalshi_requests"),
    }


def frames(db_path: str | None = None) -> list[dict[str, Any]]:
    """The latest snapshot's persisted evidence frames (contracts/checks/dutchbook, all sports), or [] when
    the store is empty / the snapshot predates frame persistence. The export (PR 23) is the first reader."""
    snap = store.latest(db_path=db_path)
    if snap is None:
        return []
    return store.load_frames(snap["snapshot_id"], db_path=db_path)


# --- per-(snapshot, sport, frame) frame cache (PR 24) — the detail panel reads frames repeatedly --------
# A process-local cache keyed (snapshot_id, sport, frame_type); cleared whenever the latest snapshot_id
# changes (a new scan), so it never serves stale evidence. The detail panel opens the same frame many
# times (chain/spreads/expected/all-contracts), so caching avoids re-reading + re-JSON-parsing the DB.
_FRAME_CACHE: dict[tuple, list[dict[str, Any]]] = {}


def _cached_frame_rows(snapshot_id: int, sport: str, frame_type: str, db_path: str | None) -> list[dict[str, Any]]:
    if _FRAME_CACHE and any(k[0] != snapshot_id for k in _FRAME_CACHE):
        _FRAME_CACHE.clear()                              # a newer snapshot — drop the whole cache
    key = (snapshot_id, sport, frame_type)
    if key not in _FRAME_CACHE:
        loaded = store.load_frames(snapshot_id, sport=sport, frame_type=frame_type, db_path=db_path)
        _FRAME_CACHE[key] = loaded[0]["rows"] if loaded else []
    return _FRAME_CACHE[key]


def participant_contracts(sport: str, player_key: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """A participant's stored contract rows for the latest snapshot (cached), or [] when absent."""
    snap = store.latest(db_path=db_path)
    if snap is None or not player_key:
        return []
    rows = _cached_frame_rows(snap["snapshot_id"], sport, "contracts", db_path)
    return [r for r in rows if r.get("player_key") == player_key]


def participant_checks(sport: str, player_key: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """A participant's stored consistency-check rows for the latest snapshot (cached), or []."""
    snap = store.latest(db_path=db_path)
    if snap is None or not player_key:
        return []
    rows = _cached_frame_rows(snap["snapshot_id"], sport, "checks", db_path)
    return [r for r in rows if r.get("player_key") == player_key]


def frame_availability(db_path: str | None = None) -> str:
    """Whether the latest snapshot's evidence frames are present / expired / absent (PR 20 honesty)."""
    snap = store.latest(db_path=db_path)
    return store.frame_status(snap["snapshot_id"], db_path=db_path) if snap else "absent"


def payoff_for_opp(opp: dict[str, Any], db_path: str | None = None) -> dict[str, Any] | None:
    """The per-state scenario payoff for an opportunity, from its matched STORED checks row (by
    opportunity_id), or None for a non-containment / dutch-book / unmatched row (so the chart is guarded).
    Reuses `consistency.scenario_payoffs` — no recomputation."""
    sport = opp.get("sport") or ""
    pkey = opp.get("participant_key") or ""
    oid = opp.get("opportunity_id")
    match = next((c for c in participant_checks(sport, pkey, db_path) if c.get("opportunity_id") == oid), None)
    return consistency.scenario_payoffs(match, opp.get("exec_min_size")) if match else None


def run_scan_now(db_path: str | None = None) -> dict[str, Any]:
    """Run a fresh scan (core series, all sports) through the shared ScanManager and return its coverage.
    A MANUAL trigger — `force=True` overrides the TTL (the button means "scan now"), but the singleflight
    still collapses a button click + a concurrent `POST /scan` to one upstream fetch. Bounded-waits for the
    result so the button can report counts; returns `{}` if it's still in flight past the bound."""
    st = scan_manager.manager.trigger(
        run_fn=_scan_run_fn(fetch_dep()), write_fn=_scan_write_fn, force=True,
        wait_timeout=config.SCAN_WAIT_TIMEOUT_SECONDS, db_path=db_path)
    return st.get("last_result") or {}
