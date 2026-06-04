"""FastAPI engine API — Stage 4 (the boundary).

Exposes the pure engine (scanner + store + lifecycle) as a typed REST API. Read endpoints serve the
LATEST persisted snapshot from the store (fast, deterministic); `POST /scan` runs a Streamlit-free scan
on demand (store-backed TTL guard) and persists the result with coverage metadata. Handlers are THIN —
they only call engine functions; no detection logic lives here. The db path and the scan fetch are
FastAPI dependencies so tests override them (seeded tmp store + stub fetch, no network).

Run: `python serve.py` (or `uvicorn api:app`). OpenAPI docs at `/docs`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

import config
import data
import fetch
import lifecycle
import scanner
import sports
import store

app = FastAPI(title="Kalshi opportunity engine", version="4.0")


# --- response models (stable — Stage 6 export reuses these) --------------------------
class Opportunity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    opportunity_id: str | None = None
    sport: str | None = None
    sport_label: str | None = None
    source: str | None = None
    name: str | None = None
    detail: str | None = None
    tournament: str | None = None
    tour: str | None = None
    action_1_text: str | None = None
    action_2_text: str | None = None
    exec_gap_c: float | None = None
    exec_min_size: float | None = None
    exec_max_profit_dollars: float | None = None
    bucket: str | None = None
    status: str | None = None
    tradable_now: str | None = None
    blocked_reason: str | None = None
    market_status: str | None = None
    rule_flag: str | None = None
    relationship_type: str | None = None
    url: str | None = None
    # N-leg plan for synthetic-bundle findings (must be DECLARED — extra="ignore" drops undeclared
    # fields, so an N>2 plan would be silently lost otherwise). None for the 2-leg shapes.
    legs: list[dict[str, Any]] | None = None
    n_legs: int | None = None


class Coverage(BaseModel):
    meta_present: bool
    fetched_at: str | None = None
    data_age_seconds: float | None = None
    stale: bool = False
    scanned: int = 0
    loaded: int = 0
    failed: int = 0
    excluded: int = 0
    skipped_no_name: int = 0
    sport_errors: list[dict[str, Any]] = []
    series_errors: list[dict[str, Any]] = []


class BacklogItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    opportunity_id: str | None = None
    sport: str | None = None
    name: str | None = None
    became_ts: float | None = None
    left_ts: float | None = None
    duration_s: float | None = None
    reason_left: str | None = None
    last_edge_c: float | None = None
    last_action_1_text: str | None = None
    last_action_2_text: str | None = None
    current_status: str | None = None
    current_bucket: str | None = None
    url: str | None = None


class BlockedChange(BaseModel):
    opportunity_id: str
    prev_bucket: str | None = None
    cur_bucket: str | None = None
    transitioned: bool = False
    changes: list[str] = []


class Alerts(BaseModel):
    new_actionable: list[Opportunity] = []
    blocked_changes: list[BlockedChange] = []


class ScanResult(BaseModel):
    skipped: bool
    fetched_at: str | None = None
    opportunities: int = 0
    scanned: int = 0
    loaded: int = 0
    failed: int = 0
    excluded: int = 0
    skipped_no_name: int = 0
    sport_errors: list[dict[str, Any]] = []
    series_errors: list[dict[str, Any]] = []


# --- dependencies (overridable in tests) ---------------------------------------------
def db_path_dep() -> str | None:
    """The snapshot DB path. None → store uses config.SNAPSHOT_DB_PATH. Tests override to a tmp file."""
    return None


def fetch_dep() -> Callable[[str], tuple]:
    """The per-sport fetch used by POST /scan — the real network fetch (all families, core series).
    Tests override with a stub so /scan touches no network."""
    def _fetch(sport_id: str) -> tuple:
        cfg = sports.get_sport(sport_id)
        families = tuple(sorted(set(cfg.category_labels.values())))
        return fetch.fetch_contracts(families, False, sport_id)
    return _fetch


def _opps(db_path: str | None) -> list[dict[str, Any]]:
    snap = store.latest(db_path=db_path)
    return snap["opportunities"] if snap else []


# --- endpoints (thin: each only calls the engine) ------------------------------------
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/opportunities", response_model=list[Opportunity])
def get_opportunities(sport: str | None = None, bucket: str | None = None,
                      status: str | None = None, db_path: str | None = Depends(db_path_dep)):
    rows = _opps(db_path)
    if sport:
        rows = [r for r in rows if r.get("sport") == sport]
    if bucket:
        rows = [r for r in rows if r.get("bucket") == bucket]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return [Opportunity(**r) for r in rows]


@app.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def get_opportunity(opportunity_id: str, db_path: str | None = Depends(db_path_dep)):
    match = next((r for r in _opps(db_path) if r.get("opportunity_id") == opportunity_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"opportunity '{opportunity_id}' not in the latest snapshot")
    return Opportunity(**match)


@app.get("/backlog", response_model=list[BacklogItem])
def get_backlog(window_s: float = config.BACKLOG_WINDOWS["1 hour"],
                db_path: str | None = Depends(db_path_dep)):
    snaps = store.snapshots_since(window_s, db_path=db_path)
    return [BacklogItem(**b) for b in lifecycle.recently_actionable(snaps)]


@app.get("/coverage", response_model=Coverage)
def get_coverage(db_path: str | None = Depends(db_path_dep)):
    snap = store.latest(db_path=db_path)
    if snap is None:
        return Coverage(meta_present=False)
    age = data.data_age_seconds(snap["fetched_at"])
    stale = data.is_stale(age, config.STALE_AFTER_SECONDS)
    meta = snap.get("meta")
    if not meta:   # snapshot written without coverage (e.g. by the Streamlit app) — never fake counts
        return Coverage(meta_present=False, fetched_at=snap["fetched_at"], data_age_seconds=age, stale=stale)
    return Coverage(meta_present=True, fetched_at=snap["fetched_at"], data_age_seconds=age, stale=stale,
                    scanned=meta.get("scanned", 0), loaded=meta.get("loaded", 0),
                    failed=meta.get("failed", 0), excluded=meta.get("excluded", 0),
                    skipped_no_name=meta.get("skipped_no_name", 0),
                    sport_errors=meta.get("sport_errors", []), series_errors=meta.get("series_errors", []))


@app.get("/alerts", response_model=Alerts)
def get_alerts(persistence_s: float | None = None, db_path: str | None = Depends(db_path_dep)):
    pair = store.latest_two(db_path=db_path)
    prev = pair[0] if len(pair) == 2 else None
    cur = pair[-1] if pair else None
    if persistence_s is None:
        new_rows = lifecycle.new_actionable(prev, cur)
    else:
        history = store.snapshots_since(config.SNAPSHOT_RETENTION_SECONDS, db_path=db_path)
        new_rows = lifecycle.persisting_new_actionable(history, persistence_s, now_ts=None)
    changes = lifecycle.blocked_change(prev, cur)
    return Alerts(
        new_actionable=[Opportunity(**r) for r in new_rows],
        blocked_changes=[BlockedChange(opportunity_id=c["opportunity_id"], prev_bucket=c["prev_bucket"],
                                       cur_bucket=c["cur_bucket"], transitioned=c["transitioned"],
                                       changes=c["changes"]) for c in changes],
    )


def _scan_result(*, skipped: bool, n_opps: int, coverage: dict[str, Any] | None) -> ScanResult:
    cov = coverage or {}
    return ScanResult(skipped=skipped, fetched_at=cov.get("fetched_at"), opportunities=n_opps,
                      scanned=cov.get("scanned", 0), loaded=cov.get("loaded", 0),
                      failed=cov.get("failed", 0), excluded=cov.get("excluded", 0),
                      skipped_no_name=cov.get("skipped_no_name", 0),
                      sport_errors=cov.get("sport_errors", []), series_errors=cov.get("series_errors", []))


@app.post("/scan", response_model=ScanResult)
def post_scan(force: bool = False, db_path: str | None = Depends(db_path_dep),
              fetch_fn: Callable[[str], tuple] = Depends(fetch_dep)):
    now = datetime.now(timezone.utc)
    latest = store.latest(db_path=db_path)
    # Store-backed TTL guard (sane after a restart): skip a too-soon scan, return the latest result
    # marked skipped, and write NOTHING (no duplicate snapshot).
    if latest is not None and not force:
        age = now.timestamp() - (latest.get("fetched_ts") or 0.0)
        if age < config.SCAN_MIN_INTERVAL_SECONDS:
            return _scan_result(skipped=True, n_opps=len(latest.get("opportunities") or []),
                                coverage=latest.get("meta"))
    fetched_at = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    unified, coverage = scanner.run_scan(fetch_fn, fetched_at=fetched_at)
    store.write_snapshot(fetched_at, unified, meta=coverage, db_path=db_path)
    return _scan_result(skipped=False, n_opps=len(unified), coverage=coverage)
