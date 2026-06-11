"""In-process engine accessors for the NiceGUI dashboard (Stage 5).

Thin wrappers over the pure engine (`store` / `lifecycle` / `scanner`) so the dashboard stays declarative
and these can be unit-tested without NiceGUI. The dashboard calls the engine IN-PROCESS (no self-HTTP);
the REST `api.py` is a sibling consumer for external clients. `db_path=None` uses `config.SNAPSHOT_DB_PATH`
(the live store); tests pass a tmp path.

Scan scope is honest: the scan fetch is `api.fetch_dep()` → **core series only** (`scan_all=False`).
"""
from __future__ import annotations

import time
from typing import Any

import config
import consistency
import data
import lifecycle
import presence
import scan_manager
import store
from api import _scan_run_fn, _scan_write_fn, fetch_dep
from webui import diagnostics as diagnostics_mod

# --- latest-snapshot cache (P1) ---------------------------------------------------------------------
# coverage()/latest_opportunities()/frames()/participant_*/frame_availability() each fetch the latest
# snapshot every call, and alerts() fetches the latest two — the dashboard poll loop calls several per
# tick, so the latest snapshot was deserialized 3+ times. Memoize the deserialized latest snapshot (and
# latest_two, for alerts) keyed by (db_path, latest_snapshot_id) so one snapshot is deserialized ONCE and
# shared, refreshed only when `store.latest_snapshot_id()` (the cheap source of truth) advances. Keying on
# db_path keeps tests (each a distinct tmp store) from cross-contaminating.
_LATEST_CACHE: dict[str, Any] = {"key": None, "snap": None}
_LATEST_TWO_CACHE: dict[str, Any] = {"key": None, "two": None}


def _cache_key(db_path: str | None) -> tuple:
    """(effective db path, latest snapshot id). Resolve `None` to `config.SNAPSHOT_DB_PATH` so a
    runtime/test db-path swap (which keeps `db_path=None` but changes the resolved file) never serves a
    stale cross-db hit — two distinct stores can both have snapshot id 1."""
    eff = db_path if db_path is not None else config.SNAPSHOT_DB_PATH
    return (eff, store.latest_snapshot_id(db_path=db_path))


def _cached_latest(db_path: str | None) -> dict[str, Any] | None:
    """The latest snapshot, deserialized once per (db, snapshot_id) and cached."""
    key = _cache_key(db_path)
    if _LATEST_CACHE["key"] != key:
        _LATEST_CACHE.update(key=key, snap=(store.latest(db_path=db_path) if key[1] is not None else None))
    return _LATEST_CACHE["snap"]


def _cached_latest_two(db_path: str | None) -> list[dict[str, Any]]:
    """The two most recent snapshots ([prev, cur]), cached per (db, latest snapshot_id)."""
    key = _cache_key(db_path)
    if _LATEST_TWO_CACHE["key"] != key:
        _LATEST_TWO_CACHE.update(key=key, two=store.latest_two(db_path=db_path))
    return _LATEST_TWO_CACHE["two"]


def latest_snapshot_id(db_path: str | None = None) -> int | None:
    """The id of the newest stored snapshot (or None). The dashboard poll loop's cheap "has new data
    landed?" probe — a single indexed query, no deserialize. Thin wrapper so the dashboard stays off
    `store` directly."""
    return store.latest_snapshot_id(db_path=db_path)


def latest_opportunities(db_path: str | None = None) -> list[dict[str, Any]]:
    """All opportunities in the latest snapshot (already ranked), or [] when the store is empty."""
    snap = _cached_latest(db_path)
    return list(snap.get("opportunities") or []) if snap else []


def opportunities_in_bucket(bucket: str, db_path: str | None = None) -> list[dict[str, Any]]:
    return [o for o in latest_opportunities(db_path=db_path) if o.get("bucket") == bucket]


def backlog(window_s: float, db_path: str | None = None) -> list[dict[str, Any]]:
    """Recently-actionable backlog over the window (§10).

    Read-path-optimized: pull only actionable rows across the window (not all ~1M opp rows) plus the
    CURRENT rows of those ids — semantically identical to `recently_actionable(snapshots_since(window))`."""
    hist = store.actionable_history_since(window_s, db_path=db_path)
    ids = {r.get("opportunity_id") for snap in hist for r in (snap.get("opportunities") or [])
           if r.get("opportunity_id")}
    current = store.latest_rows_by_id(ids, db_path=db_path)
    return lifecycle.recently_actionable_from_actionable_history(hist, current)


def backlog_events(days: float = 7.0, category: str | None = None,
                   db_path: str | None = None) -> list[dict[str, Any]]:
    """The DURABLE interval backlog (v4) over the last `days` of activity, optionally narrowed to one
    category. Reads the dedicated `backlog_intervals` table (independent of snapshot retention)."""
    return store.backlog_intervals(category=category, days=days, db_path=db_path)


def alerts(persistence_s: float | None = None, db_path: str | None = None) -> dict[str, list]:
    """New-actionable (§8) + blocked-change (§9), diffed over the two latest snapshots."""
    pair = _cached_latest_two(db_path)
    prev = pair[0] if len(pair) == 2 else None
    cur = pair[-1] if pair else None
    if persistence_s is None:
        new_rows = lifecycle.new_actionable(prev, cur)
    else:
        # `persisting_new_actionable` only ever inspects actionable rows (its `first_seen` is
        # actionable_only and its window=None branch is `new_actionable`, both bucket-filtered), so the
        # actionable-narrowed history is identical input at a fraction of the JSON expansion.
        history = store.actionable_history_since(config.SNAPSHOT_RETENTION_SECONDS, db_path=db_path)
        new_rows = lifecycle.persisting_new_actionable(history, persistence_s, now_ts=None)
    return {"new_actionable": new_rows, "blocked_changes": lifecycle.blocked_change(prev, cur)}


def coverage(db_path: str | None = None) -> dict[str, Any]:
    """Latest snapshot's coverage + live data age/stale; honest when the store is empty or meta-less."""
    snap = _cached_latest(db_path)
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
    snap = _cached_latest(db_path)
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
    snap = _cached_latest(db_path)
    if snap is None or not player_key:
        return []
    rows = _cached_frame_rows(snap["snapshot_id"], sport, "contracts", db_path)
    return [r for r in rows if r.get("player_key") == player_key]


def tournament_field(sport: str, tournament: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """Every stored contract row for one tournament (the whole field across all participants) from the
    latest snapshot (cached), or [] when absent. Mirrors `participant_contracts` but filters on
    `tournament` instead of `player_key` — feeds the DISPLAY-ONLY field-de-vig conditional panel. No
    live fetch."""
    snap = _cached_latest(db_path)
    if snap is None or not tournament:
        return []
    rows = _cached_frame_rows(snap["snapshot_id"], sport, "contracts", db_path)
    return [r for r in rows if r.get("tournament") == tournament]


def participant_checks(sport: str, player_key: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """A participant's stored consistency-check rows for the latest snapshot (cached), or []."""
    snap = _cached_latest(db_path)
    if snap is None or not player_key:
        return []
    rows = _cached_frame_rows(snap["snapshot_id"], sport, "checks", db_path)
    return [r for r in rows if r.get("player_key") == player_key]


def contract_by_ticker(market_ticker: str, sport: str | None = None,
                       db_path: str | None = None) -> dict[str, Any] | None:
    """The stored contract row for a given market ticker in the latest snapshot, or None. Market tickers
    are globally unique on Kalshi, so this searches by TICKER ALONE — the optional `sport` is only a
    narrowing hint (checked first for speed, tolerated when blank/mismatched). N-leg / soccer / field /
    synthetic legs can span shapes where the opportunity's participant_key/sport isn't reliable, so the
    lookup must not depend on them. Carries `rules_primary` (and the rest of the contract row) for the UI."""
    if not market_ticker:
        return None
    snap = _cached_latest(db_path)
    if snap is not None and sport:           # fast path: try the hinted sport's contracts frame first
        hint = _cached_frame_rows(snap["snapshot_id"], sport, "contracts", db_path)
        for r in hint:
            if r.get("market_ticker") == market_ticker:
                return r
    return next((r for r in all_contracts(db_path=db_path)
                 if r.get("market_ticker") == market_ticker), None)


def frame_availability(db_path: str | None = None) -> str:
    """Whether the latest snapshot's evidence frames are present / expired / absent (PR 20 honesty)."""
    snap = _cached_latest(db_path)
    return store.frame_status(snap["snapshot_id"], db_path=db_path) if snap else "absent"


def scan_status(db_path: str | None = None) -> dict[str, Any]:
    """The scan-manager heartbeat (status / since / last_result / reason) — read by the dashboard for the
    truthful empty states (PR 26a) without it importing scan_manager."""
    return scan_manager.manager.status()


def payoff_for_opp(opp: dict[str, Any], db_path: str | None = None) -> dict[str, Any] | None:
    """The per-state scenario payoff for an opportunity, from its matched STORED checks row (by
    opportunity_id), or None for a non-containment / dutch-book / unmatched row (so the chart is guarded).
    Reuses `consistency.scenario_payoffs` — no recomputation."""
    sport = opp.get("sport") or ""
    pkey = opp.get("participant_key") or ""
    oid = opp.get("opportunity_id")
    match = next((c for c in participant_checks(sport, pkey, db_path) if c.get("opportunity_id") == oid), None)
    return consistency.scenario_payoffs(match, opp.get("exec_min_size")) if match else None


# --- observability accessors (PR 25a) — thin wrappers over the pure diagnostics builders ---------------
def diagnostics(db_path: str | None = None) -> dict[str, Any]:
    """The latest snapshot's scan failure lists (sport/series errors, skipped, excluded) — surfaced for the
    debug UI (PR 25b), which `coverage()` curates away."""
    return diagnostics_mod.build_failures(store.latest(db_path=db_path))


def _all_frame_rows(frame_type: str, db_path: str | None) -> list[dict[str, Any]]:
    """Concat the latest snapshot's frames of one type across all sports."""
    rows: list[dict[str, Any]] = []
    for f in frames(db_path=db_path):
        if f.get("frame_type") == frame_type:
            rows.extend(f.get("rows") or [])
    return rows


def all_checks(db_path: str | None = None) -> list[dict[str, Any]]:
    """Every stored consistency-check row in the latest snapshot (all sports) — the full-diagnostics grid."""
    return _all_frame_rows("checks", db_path)


def all_contracts(db_path: str | None = None) -> list[dict[str, Any]]:
    """Every stored contract row in the latest snapshot (all sports) — the non-laddered/category surfaces."""
    return _all_frame_rows("contracts", db_path)


def recent_contract_frames(window_s: float, db_path: str | None = None) -> list[dict[str, Any]]:
    """Recent per-snapshot contract frames (oldest -> newest) for the 'most volatile now' message (#12b);
    bounded by the heavy-frame retention. Thin pass-through to the store's windowed blob scan."""
    return store.contract_frames_since(window_s, db_path=db_path)


def category_breakdown(db_path: str | None = None) -> dict[str, Any]:
    """Honest contract-category counts over the latest snapshot's stored contracts frames (all sports):
    non-laddered vs low-confidence vs unsupported as separate axes, plus per-family counts."""
    return diagnostics_mod.build_category_breakdown(all_contracts(db_path=db_path))


def metrics(db_path: str | None = None) -> dict[str, Any]:
    """The low-cardinality monitoring payload (counters + scan heartbeat + live viewer count) for the
    latest snapshot."""
    snap = store.latest(db_path=db_path)
    age = data.data_age_seconds(snap["fetched_at"]) if snap else None
    return diagnostics_mod.build_metrics(
        snapshot=snap, scan_status=scan_manager.manager.status(), now_age=age,
        stale=data.is_stale(age, config.STALE_AFTER_SECONDS), now=time.time(),
        viewer_count=presence.count())


def run_scan_now(db_path: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Trigger a scan (core series, all sports) through the shared ScanManager and return its STATUS dict
    (`status` ∈ idle/in_progress/done/skipped/error, plus `reason` and `last_result`).

    NON-FORCE by default (PR S3): the dashboard "Scan now" button now respects the SAME TTL + budget
    cooldown as the scheduler and `POST /scan`, so repeated clicks — or many LAN viewers each clicking —
    can't hammer Kalshi; a click within the TTL window returns `skipped`, not a refetch. The singleflight
    still collapses a click + a concurrent `POST /scan` into ONE upstream fetch. Force is reachable only via
    the token-gated `POST /scan?force=true` (there is deliberately no UI force button). Bounded-waits so a
    completed scan reports counts; a still-running scan returns `in_progress`."""
    return scan_manager.manager.trigger(
        run_fn=_scan_run_fn(fetch_dep()), write_fn=_scan_write_fn, force=force,
        wait_timeout=config.SCAN_WAIT_TIMEOUT_SECONDS, db_path=db_path)
