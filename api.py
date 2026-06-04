"""FastAPI engine API — Stage 4 (the boundary).

Exposes the pure engine (scanner + store + lifecycle) as a typed REST API. Read endpoints serve the
LATEST persisted snapshot from the store (fast, deterministic); `POST /scan` runs a Streamlit-free scan
on demand (store-backed TTL guard) and persists the result with coverage metadata. Handlers are THIN —
they only call engine functions; no detection logic lives here. The db path and the scan fetch are
FastAPI dependencies so tests override them (seeded tmp store + stub fetch, no network).

Run: `python serve.py` (or `uvicorn api:app`). OpenAPI docs at `/docs`.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict

import config
import data
import fetch
import kalshi_client
import lifecycle
import presence
import scan_manager
import scanner
import sports
import store
from webui import diagnostics

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
    # Numeric leg prices + combined cost (must be DECLARED — extra="ignore" drops undeclared fields).
    action_1_price_c: float | None = None
    action_2_price_c: float | None = None
    cost_c: float | None = None
    exec_gap_c: float | None = None
    exec_min_size: float | None = None
    exec_max_profit_dollars: float | None = None
    # Guaranteed payout floor + gross ROI on cost (PR 13).
    payout_floor_c: float | None = None
    roi_pct: float | None = None
    bucket: str | None = None
    status: str | None = None
    tradable_now: str | None = None
    blocked_reason: str | None = None
    market_status: str | None = None
    rule_flag: str | None = None
    settlement_caveat: str | None = None
    relationship_type: str | None = None
    # Per-leg tickers + the second leg's link (the panel surfaces both legs).
    ticker_1: str | None = None
    ticker_2: str | None = None
    url: str | None = None
    url_2: str | None = None
    # N-leg plan for synthetic-bundle findings (must be DECLARED — extra="ignore" drops undeclared
    # fields, so an N>2 plan would be silently lost otherwise). Synthesized 2-leg for the other shapes.
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
    # Volume counters + Kalshi requests issued this scan (PR 21a), distinct from the opportunity count.
    contracts_scanned: int = 0
    checks_tested: int = 0
    kalshi_requests: int = 0
    sport_errors: list[dict[str, Any]] = []
    series_errors: list[dict[str, Any]] = []


class Metrics(BaseModel):
    """Low-cardinality monitoring payload (PR 25a) — counters + scan heartbeat, no per-row data. Distinct
    from `/coverage` (which carries the full failure lists): `/metrics` is for dashboards/alerting."""
    model_config = ConfigDict(extra="ignore")
    snapshot_id: int | None = None
    snapshot_age_seconds: float | None = None
    stale: bool | None = None
    opportunities: int = 0
    actionable: int = 0
    contracts_scanned: int = 0
    checks_tested: int = 0
    kalshi_requests: int = 0
    scanned_series: int = 0
    failed_series: int = 0
    sport_error_count: int = 0
    scan_status: str = "idle"
    scan_since: float | None = None
    scan_in_progress_seconds: float | None = None
    last_scan_error: str | None = None
    viewer_count: int | None = None


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
    # The full N-leg plan of the opportunity as it last looked actionable (PR 13); None for old snapshots.
    last_legs: list[dict[str, Any]] | None = None
    payout_floor_c: float | None = None
    roi_pct: float | None = None
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


class ScanStatus(BaseModel):
    # Non-blocking /scan (PR 21b): POST /scan returns this with a 202; GET /scan/status returns the live
    # state. `status` ∈ {idle, in_progress, done, skipped, error}; `reason` explains a skip (ttl / budget
    # cooldown). `last_result` (the coverage of the most recent completed scan) is included on /scan/status.
    model_config = ConfigDict(extra="ignore")
    status: str
    since: float | None = None
    last_snapshot_id: int | None = None
    reason: str | None = None
    last_result: dict[str, Any] | None = None


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
                    contracts_scanned=meta.get("contracts_scanned", 0),
                    checks_tested=meta.get("checks_tested", 0),
                    kalshi_requests=meta.get("kalshi_requests", 0),
                    sport_errors=meta.get("sport_errors", []), series_errors=meta.get("series_errors", []))


@app.get("/metrics", response_model=Metrics)
def get_metrics(db_path: str | None = Depends(db_path_dep)):
    """Low-cardinality scan-health metrics for monitoring (PR 25a). Built from the store + scan-manager
    status directly (mirrors `/coverage`; no engine import → no cycle). Honest when there is no scan."""
    snap = store.latest(db_path=db_path)
    age = data.data_age_seconds(snap["fetched_at"]) if snap else None
    stale = data.is_stale(age, config.STALE_AFTER_SECONDS) if age is not None else None
    return Metrics(**diagnostics.build_metrics(
        snapshot=snap, scan_status=scan_manager.manager.status(), now_age=age,
        stale=stale, now=time.time(), viewer_count=presence.count()))


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


def _scan_run_fn(fetch_fn: Callable[[str], tuple]) -> Callable[[str], tuple]:
    def run_fn(fetched_at: str) -> tuple:
        return scanner.run_scan(fetch_fn, fetched_at=fetched_at, request_count=kalshi_client.request_count)
    return run_fn


def _scan_write_fn(fetched_at: str, unified, coverage, frames, db_path: str | None):
    return store.write_snapshot(fetched_at, unified, meta=coverage, frames=frames, db_path=db_path)


@app.post("/scan", response_model=ScanStatus, status_code=202)
def post_scan(response: Response, force: bool = False, wait: bool = False,
              db_path: str | None = Depends(db_path_dep),
              fetch_fn: Callable[[str], tuple] = Depends(fetch_dep)):
    """Non-blocking (PR 21b): trigger a scan via the process-local singleflight and return 202 with the
    current status immediately. `?wait=true` blocks up to SCAN_WAIT_TIMEOUT_SECONDS for the scan to finish
    (still 202 past the bound). `?force=true` overrides the TTL/budget guards. Two triggers (or a button +
    this) collapse to one upstream fetch. Poll `GET /scan/status` for completion."""
    st = scan_manager.manager.trigger(
        run_fn=_scan_run_fn(fetch_fn), write_fn=_scan_write_fn, force=force,
        wait_timeout=(config.SCAN_WAIT_TIMEOUT_SECONDS if wait else 0.0), db_path=db_path)
    response.status_code = 202
    return ScanStatus(**st)


@app.get("/scan/status", response_model=ScanStatus)
def get_scan_status():
    return ScanStatus(**scan_manager.manager.status())
