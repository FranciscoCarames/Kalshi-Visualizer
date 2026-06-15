"""FastAPI engine API — Stage 4 (the boundary).

Exposes the pure engine (scanner + store + lifecycle) as a typed REST API. Read endpoints serve the
LATEST persisted snapshot from the store (fast, deterministic); `POST /scan` runs a scan
on demand (store-backed TTL guard) and persists the result with coverage metadata. Handlers are THIN —
they only call engine functions; no detection logic lives here. The db path and the scan fetch are
FastAPI dependencies so tests override them (seeded tmp store + stub fetch, no network).

Run: `python serve.py` (or `uvicorn api:app`). OpenAPI docs at `/docs`.
"""
from __future__ import annotations

import hmac
import io
import logging
import os
import threading
import time
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

import auth
import config
import data
import fetch
import kalshi_client
import lifecycle
import presence
import ratelimit
import scan_manager
import scanner
import sports
import store
from webui import diagnostics, feed

# The OpenAPI docs routes are always CONSTRUCTED, but hidden at REQUEST time by the auth middleware when
# `AUTH_ENABLED` and not `APP_DEV` (it returns 404). Doing this in the middleware — not via the
# `FastAPI(docs_url=None)` constructor — is deliberate: `apply_runtime_defaults()` sets `AUTH_ENABLED`
# AFTER `import api`, so a constructor-time check would miss the secure default. See `auth.gate_and_harden`.
app = FastAPI(title="Kalshi Structured Scanner", version="4.0")
# Host allowlist (default "*" — no restriction until an operator sets APP_ALLOWED_HOSTS) + the
# deny-by-default auth gate / security-headers middleware. Both are no-ops for loopback/dev and the test
# client until AUTH_ENABLED / APP_ALLOWED_HOSTS are set; see auth.py.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=auth.allowed_hosts())
app.middleware("http")(auth.gate_and_harden)
app.include_router(auth.router)
logger = logging.getLogger("kalshi.api")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    """Redirect the browser's implicit /favicon.ico probe to the SPA's SVG icon (kills the root 404 on both
    the dashboard at "/" and the SPA). Registered before NiceGUI's "/" mount so this explicit route wins."""
    return RedirectResponse(url="/terminal/favicon.svg")

# Per-process HTTP `/scan` rate limiter (PR 26b) — distinct from the ScanManager scan TTL. Guards the
# endpoint itself; the in-process dashboard button (engine.run_scan_now) never touches it.
_scan_limiter = ratelimit.SlidingWindow(config.SCAN_HTTP_MAX_PER_WINDOW, config.SCAN_HTTP_WINDOW_SECONDS)


def require_scan_token(request: Request,
                       x_scan_token: str | None = Header(default=None, alias="X-Scan-Token")) -> None:
    """Scan-token gate (PR 26b, locked decision §8). When the `SCAN_TOKEN` env var is SET, `POST /scan`
    requires a matching `X-Scan-Token` header (constant-time compare); when UNSET the gate is OFF (today's
    open behaviour). Loopback dev simply leaves it unset; a LAN scheduler must send the header.

    When AUTH_ENABLED, a request that already carries a valid session or machine token has passed the
    deny-by-default gate — don't double-gate it out of /scan when SCAN_TOKEN is also set (otherwise a
    logged-in human could never trigger a scan from the SPA). The legacy header path is unchanged when auth
    is off."""
    if auth.auth_enabled() and auth.authenticated(request):
        return
    token = os.getenv("SCAN_TOKEN", "")
    if token and not hmac.compare_digest(x_scan_token or "", token):
        logger.warning("Rejected POST /scan: missing or invalid X-Scan-Token")
        raise HTTPException(status_code=401, detail="Invalid or missing X-Scan-Token")


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
    # "Beyond the strict rule" (PR 29): edge_class ("strict" | "risk_budget" | "near_miss") + the convex
    # per-unit profit bounds (worst == best for a flat dutch book; worst is the bounded loss, best the $1
    # bonus for a containment risk-budget candidate). None on rows with no buy-plan.
    edge_class: str | None = None
    worst_case_profit_c: float | None = None
    best_case_profit_c: float | None = None
    # Probability-context display outrights (risk-budget "spread / outright" view). display_c is the
    # DISPLAY OUTRIGHT price (reasonable-quote midpoint, else last trade), NOT executable. None elsewhere.
    parent_display_c: float | None = None
    child_display_c: float | None = None
    display_spread_c: float | None = None
    spread_over_parent: float | None = None
    spread_over_child: float | None = None
    # Firm-quote passthrough (Phase 1, display-only): parent YES bid + child YES ask for the conservative
    # tradable-side success gap. Declared so REST /opportunities matches the dashboard (extra="ignore" would
    # otherwise drop them). None on non-containment shapes + pre-field snapshots.
    parent_yes_bid_c: float | None = None
    child_yes_ask_c: float | None = None
    # Phase 2 E (display-only): ladder rung labels ("Wins if …") + worst-leg quote quality ("Quote health").
    child_node: str | None = None
    parent_node: str | None = None
    comp_quote_quality: str | None = None
    bucket: str | None = None
    status: str | None = None
    tradable_now: str | None = None
    blocked_reason: str | None = None
    market_status: str | None = None
    rule_flag: str | None = None
    settlement_caveat: str | None = None
    relationship_type: str | None = None
    # Bounded-Loss vertical (simultaneous resolution) vs calendar (sequential). Optional → old stored rows
    # without it read as None and the dashboard treats a missing value as "calendar" (the safe default).
    resolution_mode: str | None = None
    # Per-leg tickers + the second leg's link (the panel surfaces both legs).
    ticker_1: str | None = None
    ticker_2: str | None = None
    url: str | None = None
    url_2: str | None = None
    # N-leg plan for synthetic-bundle findings (must be DECLARED — extra="ignore" drops undeclared
    # fields, so an N>2 plan would be silently lost otherwise). Synthesized 2-leg for the other shapes.
    legs: list[dict[str, Any]] | None = None
    n_legs: int | None = None
    # All participants on the opportunity (every leg) for the participant multi-select filter (PR6).
    # Parallel lists key<->label; must be DECLARED or extra="ignore" would drop them.
    participant_keys: list[str] = []
    participant_labels: list[str] = []
    # World Cup Qualifier Setups (PR1): cross-cutting product tag, separate from bucket/routing. Must be
    # DECLARED — extra="ignore" would drop them. "" for every non-qualifier row.
    setup_family: str | None = None
    setup_type: str | None = None
    # Diagnostic-only numeric fields for the qualifier_setup section (PR3 schema; PR4/PR5 fill them). None
    # on every non-diagnostic row. exact-order #4 premium-proxy + inputs; game-support #5 ask-support score.
    qualifier_vs_top2_premium_c: float | None = None
    synthetic_top_two_cost_c: float | None = None
    qualifier_yes_ask_c: float | None = None
    ask_support_score_total_c: float | None = None
    ask_support_score_per_game_c: float | None = None
    join_confidence: str | None = None
    # Exact-order top-two bundle two-tier economics (#4 redux). opportunity_class tags the tier; the top2_*
    # fields are the explicit gross economics; the *_quote_quality / wide_bundle_leg_count fields split
    # bundle-leg execution risk from the comparator. Must be DECLARED — extra="ignore" would drop them.
    opportunity_class: str | None = None
    top2_net_if_top2_c: float | None = None
    top2_loss_if_not_top2_c: float | None = None
    top2_max_units: float | None = None
    worst_bundle_quote_quality: str | None = None
    wide_bundle_leg_count: float | None = None
    comparator_quote_quality: str | None = None


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
    # Non-blocking per-game settlement caveat as it last looked actionable (blank for non-game books).
    last_settlement_caveat: str | None = None
    # The full N-leg plan of the opportunity as it last looked actionable (PR 13); None for old snapshots.
    last_legs: list[dict[str, Any]] | None = None
    payout_floor_c: float | None = None
    roi_pct: float | None = None
    current_status: str | None = None
    current_bucket: str | None = None
    url: str | None = None


class BacklogInterval(BaseModel):
    """One durable interval-backlog row (v4) — a single open/closed lifecycle of an opportunity in a
    tracked category (`actionable` / `bounded_loss`; `statistical_arbitrage` reserved). Distinct from
    `BacklogItem` (the short live `recently_actionable` view): this is the 7-day durable store, so an
    opportunity that appeared, left, and returned shows as SEPARATE intervals."""
    model_config = ConfigDict(extra="ignore")
    id: int | None = None
    opportunity_id: str | None = None
    category: str | None = None
    sport: str | None = None
    name: str | None = None
    url: str | None = None
    first_seen_ts: float | None = None
    last_seen_ts: float | None = None
    left_ts: float | None = None
    duration_s: float | None = None
    is_open: bool | None = None
    last_bucket: str | None = None
    last_status: str | None = None
    peak_roi_pct: float | None = None
    best_case_profit_c: float | None = None
    worst_case_profit_c: float | None = None
    last_settlement_caveat: str | None = None
    last_legs: list[dict[str, Any]] | None = None


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


class ReadyZ(BaseModel):
    # Readiness (PR S1), distinct from the liveness-only /healthz. `status` ∈ {ready, degraded, not_ready};
    # ready/degraded are 200, not_ready is 503. `last_scan_status` is the scan-manager state; no scheduler
    # health is claimed and no live Kalshi call is made.
    model_config = ConfigDict(extra="ignore")
    status: str
    reason: str | None = None
    snapshot_age_seconds: float | None = None
    last_scan_status: str | None = None
    last_scan_error: str | None = None


# --- dependencies (overridable in tests) ---------------------------------------------
def db_path_dep() -> str | None:
    """The snapshot DB path. None → store uses config.SNAPSHOT_DB_PATH. Tests override to a tmp file."""
    return None


def fetch_dep() -> Callable[[str], tuple]:
    """The per-sport fetch used by POST /scan — the real network fetch (all families, core series).
    Tests override with a stub so /scan touches no network."""
    def _fetch(sport_id: str) -> tuple:
        cfg = sports.get_sport(sport_id)
        families = data.non_other_families(cfg)   # in-scope families only (excludes the "other" bucket)
        return fetch.fetch_contracts(families, False, sport_id)
    return _fetch


def _opps(db_path: str | None) -> list[dict[str, Any]]:
    snap = store.latest(db_path=db_path)
    return snap["opportunities"] if snap else []


# --- endpoints (thin: each only calls the engine) ------------------------------------
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", response_model=ReadyZ)
def readyz(request: Request, response: Response, db_path: str | None = Depends(db_path_dep)):
    """Readiness (PR S1), distinct from the liveness-only /healthz: ready/degraded → 200, not_ready → 503.
    The DB-writability probe is MIGRATION-FREE (`store.db_writable` → `os.access`; never `_connect`/
    `_migrate`, so a health probe can't migrate or create the prod DB); the latest snapshot is read only
    when the DB file already exists. Reflects the LAST scan's status (no live Kalshi call) and never claims
    scheduler health.

    `/readyz` is PUBLIC (allowlisted) so an unauthenticated load-balancer / orchestrator probe still works
    under AUTH_ENABLED — but for an anonymous caller the DETAIL (snapshot age, last-scan error, scan state)
    is REDACTED to just the status + HTTP code, so operational internals don't leak. An authenticated
    caller (or auth-off dev) gets the full body; the detail also lives in the gated /metrics."""
    resolved = db_path or config.SNAPSHOT_DB_PATH
    writable = store.db_writable(resolved)
    snap = store.latest(db_path=resolved) if (writable and os.path.exists(resolved)) else None
    age = data.data_age_seconds(snap["fetched_at"]) if snap else None
    stale = data.is_stale(age, config.STALE_AFTER_SECONDS) if age is not None else None
    code, body = diagnostics.build_readiness(
        writable=writable, snapshot=snap, age=age, stale=stale,
        scan_status=scan_manager.manager.status())
    response.status_code = code
    if auth.auth_enabled() and not auth.authenticated(request):
        return ReadyZ(status=body["status"])           # redacted: status + HTTP code only, no internals
    return ReadyZ(**body)


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


@app.get("/api/terminal/feed")
def get_terminal_feed(db_path: str | None = Depends(db_path_dep)) -> dict[str, Any]:
    """Denormalized, read-only VIEW of the latest snapshot for the Terminal Pro SPA (`/terminal`).

    A faithful 1:1 view, NOT a second engine: `webui.feed.build_feed` re-presents `store.latest()` through
    the existing display-row builders and adds only DISPLAY-ONLY fields (ripeness / conditional / net-of-
    fees estimate). `bucket`/`status`/`tradable_now`/`rule_flag` are copied verbatim from the same rows
    `/opportunities` serves — parity is asserted in tests/test_feed.py. No re-bucketing, no re-ranking.

    Records a presence heartbeat (the SPA isn't a NiceGUI client) so the background scan's idle-gate keeps
    refreshing the snapshot while this terminal is open. ONLY this endpoint touches terminal presence."""
    presence.touch()
    return feed.build_feed(db_path=db_path)


# --- Terminal Pro parity endpoints (read-only VIEWS; reuse engine/viewmodel/viz/export only) -----------
# Each is a THIN adapter over an existing pure/engine function — never a second engine, never a mutation,
# never a re-bucket. `webui.engine` is imported LAZILY inside handlers (engine imports api → import cycle).
_DIAG_ROW_CAP = 2000


class TerminalDetail(BaseModel):
    """Data-driven participant drill-down (the old dashboard's detail panel), scoped to one
    (sport, player_key, tournament). All fields display-only; never feeds classification/ranking."""
    chain: list[dict[str, Any]] = []
    indicators: list[dict[str, Any]] = []
    spreads: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    raw_fields: list[dict[str, Any]] = []
    link_audit: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []


class TerminalPayoff(BaseModel):
    scenarios: list[dict[str, Any]] = []
    cost_c: float | None = None


class TerminalLadder(BaseModel):
    layers: list[dict[str, Any]] = []


class TerminalDiagnostics(BaseModel):
    checks: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    category: dict[str, Any] = {}
    failures: dict[str, Any] = {}
    checks_truncated: int = 0
    contracts_truncated: int = 0


class ExportRequest(BaseModel):
    opportunity_ids: list[str] = []
    snapshot_id: int | None = None


class TerminalOrderbook(BaseModel):
    """Live resting order book for one market (DISPLAY-ONLY depth view — gross / top-of-book limits still
    apply; NOT net executable capacity). yes/no are [[price_c, size], …] ascending (best bid last)."""
    ticker: str
    yes: list[list[int]] = []
    no: list[list[int]] = []
    ok: bool = True
    error: str | None = None
    age_s: float = 0.0


class TerminalTelemetry(BaseModel):
    """Snapshot-context market telemetry (DISPLAY-ONLY — NOT an opportunity signal): most-liquid sports +
    contracts, tightest books, most-traded, and a one-line 'most volatile now' message."""
    snapshot_id: int | None = None
    top_sports: list[list[Any]] = []
    top_contracts: list[list[Any]] = []
    tightest: list[list[Any]] = []
    most_traded: list[list[Any]] = []
    volatility: str | None = None


# Telemetry is recomputed at most ONCE per snapshot (liquidity_panel scans all contracts; volatility scans
# recent frames) — cached here so repeated SPA fetches / surface switches don't re-aggregate every time.
_telemetry_cache: dict[str, Any] = {"snapshot_id": object(), "data": None}
_telemetry_cache_lock = threading.Lock()                 # serialize the check+compute+store (compute once)
_TELEMETRY_VOLATILITY_WINDOW_S = 3600.0

# Live order-book fetch (the SPA depth ladder): a short per-ticker TTL cache coalesces the ~5s frontend
# poll across tabs/sessions (the Kalshi throttle is process-wide, so caching bounds upstream load), and a
# sliding window caps total orderbook fetches/sec. Depth is clamped 1..100. All process-local.
_ORDERBOOK_DEFAULT_DEPTH = 10
_ORDERBOOK_MAX_DEPTH = 100
_ORDERBOOK_CACHE_TTL_S = 2.0
_orderbook_cache: dict[str, tuple[float, dict[str, Any]]] = {}      # ticker -> (fetched_monotonic, parsed)
_orderbook_cache_lock = threading.Lock()
_orderbook_limiter = ratelimit.SlidingWindow(config.ORDERBOOK_HTTP_MAX_PER_WINDOW, config.ORDERBOOK_HTTP_WINDOW_SECONDS)


def _participant_rows(sport: str, player_key: str, tournament: str, db_path: str | None) -> list[dict[str, Any]]:
    """A participant's stored contracts SCOPED to one tournament — the engine groups ladders by
    (player_key, tournament) (data.tournament_of season-scopes the key), so detail/ladder MUST scope by
    tournament or they would merge a player's contracts across tournaments/seasons into a false ladder."""
    from webui import engine  # lazy: engine imports api (cycle)
    prows = engine.participant_contracts(sport, player_key, db_path=db_path)
    return [r for r in prows if (r.get("tournament") or "") == tournament]


@app.get("/api/terminal/detail", response_model=TerminalDetail)
def get_terminal_detail(sport: str, player_key: str, tournament: str,
                        db_path: str | None = Depends(db_path_dep)) -> TerminalDetail:
    """Read-only participant drill-down for the SPA Inspector. REQUIRES tournament (no silent cross-
    tournament merge → a false ladder). Honest-empty when the participant has no stored contracts."""
    if not (sport and player_key and tournament):
        raise HTTPException(status_code=400, detail="sport, player_key and tournament are all required")
    from webui import viewmodel as vm
    prows = _participant_rows(sport, player_key, tournament, db_path)
    chain = vm.detail_chain(prows, sport)
    rules = [{"contract": r.get("contract") or r.get("market_ticker") or "—",
              "text": str(r.get("rules_primary"))} for r in prows if r.get("rules_primary")]
    return TerminalDetail(
        chain=chain, indicators=vm.derived_indicators(chain, sport),
        spreads=vm.detail_spreads(prows), expected=vm.detail_expected(prows),
        contracts=vm.detail_contracts(prows), raw_fields=vm.raw_fields_rows(prows),
        link_audit=vm.link_audit_rows(prows), duplicates=vm.duplicate_rows(prows), rules=rules)


@app.get("/api/terminal/payoff", response_model=TerminalPayoff)
def get_terminal_payoff(opportunity_id: str, db_path: str | None = Depends(db_path_dep)) -> TerminalPayoff:
    """Per-state payoff for the SPA payoff chart. 404 when the id isn't in the latest snapshot; honest-empty
    scenarios for a non-containment / dutch-book opp (no fabricated curve). Reuses viz.payoff_chart_data."""
    import viz
    from webui import engine  # lazy (cycle)
    opp = next((r for r in _opps(db_path) if r.get("opportunity_id") == opportunity_id), None)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"opportunity '{opportunity_id}' not in the latest snapshot")
    pay = engine.payoff_for_opp(opp, db_path=db_path)
    return TerminalPayoff(scenarios=viz.payoff_chart_data(pay).to_dict("records"),
                          cost_c=_num((pay or {}).get("cost_c")))


@app.get("/api/terminal/ladder", response_model=TerminalLadder)
def get_terminal_ladder(sport: str, player_key: str, tournament: str,
                        db_path: str | None = Depends(db_path_dep)) -> TerminalLadder:
    """Containment-ladder price chart for the SPA. REQUIRES tournament (same scoping rule as /detail).
    Reuses viz.ladder_prices (inversion-flagged); display-only, never an edge."""
    if not (sport and player_key and tournament):
        raise HTTPException(status_code=400, detail="sport, player_key and tournament are all required")
    import viz
    from webui import viewmodel as vm
    prows = _participant_rows(sport, player_key, tournament, db_path)
    chain = vm.detail_chain(prows, sport)
    adapted = [{"Layer": r.get("layer", ""), "Display %": r.get("display_pct")} for r in chain]
    return TerminalLadder(layers=viz.ladder_prices(adapted).to_dict("records"))


@app.get("/api/terminal/diagnostics", response_model=TerminalDiagnostics)
def get_terminal_diagnostics(db_path: str | None = Depends(db_path_dep)) -> TerminalDiagnostics:
    """Deep diagnostics grids for the OPS surface (full check rows, all contracts, category honesty, scan
    failures). Rows capped at _DIAG_ROW_CAP with an explicit truncation count — NO silent truncation."""
    from webui import engine  # lazy (cycle)
    checks, contracts = engine.all_checks(db_path=db_path), engine.all_contracts(db_path=db_path)
    return TerminalDiagnostics(
        checks=checks[:_DIAG_ROW_CAP], contracts=contracts[:_DIAG_ROW_CAP],
        category=engine.category_breakdown(db_path=db_path), failures=engine.diagnostics(db_path=db_path),
        checks_truncated=max(0, len(checks) - _DIAG_ROW_CAP),
        contracts_truncated=max(0, len(contracts) - _DIAG_ROW_CAP))


@app.get("/api/terminal/telemetry", response_model=TerminalTelemetry)
def get_terminal_telemetry(db_path: str | None = Depends(db_path_dep)) -> TerminalTelemetry:
    """Read-only snapshot-context telemetry for the RES surface. Cached per snapshot_id (so it's not
    re-aggregated on every poll). Reuses viewmodel.liquidity_panel + volatility_leader; honest-empty when
    there's no snapshot or no two-sided books. Display-only — never an opportunity signal."""
    from webui import engine, viewmodel  # lazy (engine cycle); viewmodel is pure
    sid = store.latest_snapshot_id(db_path=db_path)
    if sid is None:
        return TerminalTelemetry(snapshot_id=None)
    # Hold the lock across check+compute+store so two concurrent polls on a NEW snapshot don't both run the
    # heavy liquidity_panel aggregation — the second waits, then sees the cache hit. Telemetry is a low-QPS
    # poll, so serializing here is cheap and is exactly the coalescing we want.
    with _telemetry_cache_lock:
        if _telemetry_cache["snapshot_id"] == sid and _telemetry_cache["data"] is not None:
            return _telemetry_cache["data"]
        liq = viewmodel.liquidity_panel(engine.all_contracts(db_path=db_path))
        vol = viewmodel.volatility_leader(engine.recent_contract_frames(_TELEMETRY_VOLATILITY_WINDOW_S, db_path=db_path))
        rows = lambda key: [list(t) for t in liq.get(key, [])]   # noqa: E731 — tuples → JSON arrays
        out = TerminalTelemetry(snapshot_id=sid, top_sports=rows("top_sports"), top_contracts=rows("top_contracts"),
                                tightest=rows("tightest"), most_traded=rows("most_traded"), volatility=vol)
        _telemetry_cache["snapshot_id"], _telemetry_cache["data"] = sid, out
        return out


@app.get("/api/terminal/orderbook", response_model=TerminalOrderbook)
def get_terminal_orderbook(ticker: str, depth: int = _ORDERBOOK_DEFAULT_DEPTH) -> TerminalOrderbook:
    """LIVE resting order book for one market — the SPA depth ladder (replaces the old synthetic book).
    Read-only market data, GATED by the auth middleware when AUTH_ENABLED (like every `/api/terminal/*`
    route — it is NOT public). Validates the ticker, clamps depth to 1..100, coalesces the
    frontend's ~5s poll via a short per-ticker TTL cache, and is sliding-window rate-limited. Degrades
    HONESTLY: an empty/closed book → empty sides; any upstream failure → ok=False + error (never a 500,
    never fabricated rungs). Display-only depth — never feeds classification/ranking."""
    tk = (ticker or "").strip().upper()
    if not (3 <= len(tk) <= 64) or not all(c.isalnum() or c in "-_." for c in tk):
        raise HTTPException(status_code=400, detail="invalid ticker")
    depth = max(1, min(_ORDERBOOK_MAX_DEPTH, int(depth)))

    now = time.monotonic()
    with _orderbook_cache_lock:                                  # serve a fresh cache hit (coalesce polls)
        hit = _orderbook_cache.get(tk)
        if hit and (now - hit[0]) < _ORDERBOOK_CACHE_TTL_S:
            ob = hit[1]
            return TerminalOrderbook(ticker=tk, yes=ob["yes"], no=ob["no"], age_s=round(now - hit[0], 2))

    if not _orderbook_limiter.allow(time.time()):
        return TerminalOrderbook(ticker=tk, ok=False, error="rate limited — try again shortly")
    try:
        ob = kalshi_client.get_orderbook(tk, depth=depth)
    except Exception as exc:                                     # network/4xx/5xx/closed → honest degrade
        return TerminalOrderbook(ticker=tk, ok=False, error=f"order book unavailable: {exc}")
    with _orderbook_cache_lock:
        _orderbook_cache[tk] = (now, ob)
    return TerminalOrderbook(ticker=tk, yes=ob["yes"], no=ob["no"], age_s=0.0)


@app.post("/api/terminal/export")
def post_terminal_export(req: ExportRequest, db_path: str | None = Depends(db_path_dep)) -> StreamingResponse:
    """Build the snapshot-export ZIP from EXACTLY the opportunity_ids the grid shows (so the export can
    never disagree with the visible rows); evidence frames stay whole-snapshot, as the old dashboard
    exported them. Read-only POST (computes a zip; mutates nothing). 409 when there's no snapshot."""
    from webui import engine, export  # lazy (engine cycle); export is pure
    snap = store.latest(db_path=db_path)
    if snap is None:
        raise HTTPException(status_code=409, detail="no snapshot to export")
    wanted = set(req.opportunity_ids)
    selected = [r for r in _opps(db_path) if r.get("opportunity_id") in wanted]
    backlog = lifecycle.recently_actionable(
        store.snapshots_since(config.BACKLOG_WINDOWS["1 hour"], db_path=db_path))
    blob = export.build_export_zip(
        snapshot_id=snap.get("snapshot_id"), fetched_at=snap.get("fetched_at"),
        opportunities=selected, coverage=snap.get("meta") or {}, frames=engine.frames(db_path=db_path),
        backlog=backlog, backlog_window="1 hour", filters={"opportunity_ids": len(wanted)})
    fname = f"kalshi-snapshot-{snap.get('snapshot_id')}.zip"
    return StreamingResponse(io.BytesIO(blob), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def _num(x: Any) -> float | None:
    """JSON-safe float (None for None/blank/NaN) — local mirror of feed._num for the payoff cost line."""
    try:
        if x is None or x == "":
            return None
        f = float(x)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


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


@app.get("/backlog/events", response_model=list[BacklogInterval])
def get_backlog_events(days: float = 7.0, category: str | None = None, include_open: bool = True,
                       db_path: str | None = Depends(db_path_dep)):
    """The DURABLE 7-day interval backlog (v4) — distinct from `/backlog` above (the short live
    `recently_actionable` view, unchanged). Each row is one open/closed lifecycle of an opportunity in a
    tracked category. `days` windows by activity (capped at the retention window); `category` narrows to
    one of `actionable` / `bounded_loss` (`statistical_arbitrage` reserved — no detector yet);
    `include_open=false` returns only closed intervals."""
    rows = store.backlog_intervals(category=category, include_open=include_open, days=days, db_path=db_path)
    return [BacklogInterval(**r) for r in rows]


@app.get("/coverage", response_model=Coverage)
def get_coverage(db_path: str | None = Depends(db_path_dep)):
    snap = store.latest(db_path=db_path)
    if snap is None:
        return Coverage(meta_present=False)
    age = data.data_age_seconds(snap["fetched_at"])
    stale = data.is_stale(age, config.STALE_AFTER_SECONDS)
    meta = snap.get("meta")
    if not meta:   # snapshot written without coverage metadata — never fake counts
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


@app.post("/scan", response_model=ScanStatus, status_code=202, dependencies=[Depends(require_scan_token)])
def post_scan(response: Response, force: bool = False, wait: bool = False,
              db_path: str | None = Depends(db_path_dep),
              fetch_fn: Callable[[str], tuple] = Depends(fetch_dep)):
    """Non-blocking (PR 21b): trigger a scan via the process-local singleflight and return 202 with the
    current status immediately. `?wait=true` blocks up to SCAN_WAIT_TIMEOUT_SECONDS for the scan to finish
    (still 202 past the bound). `?force=true` overrides the TTL/budget guards. Two triggers (or a button +
    this) collapse to one upstream fetch. Poll `GET /scan/status` for completion.

    Security (PR 26b): gated by `require_scan_token` (header required only when `SCAN_TOKEN` is set) and a
    per-process HTTP rate limit (429 when exceeded). The dashboard's own "Scan now" button calls the engine
    IN-PROCESS, not this endpoint, so it bypasses both guards; an external scheduler/curl must honour them."""
    if not _scan_limiter.allow(time.time()):
        logger.warning("Rate-limited POST /scan (>%d in %ds)",
                       config.SCAN_HTTP_MAX_PER_WINDOW, config.SCAN_HTTP_WINDOW_SECONDS)
        raise HTTPException(status_code=429, detail="Too many scan requests; slow down.")
    logger.info("Accepted POST /scan (force=%s, wait=%s)", force, wait)
    st = scan_manager.manager.trigger(
        run_fn=_scan_run_fn(fetch_fn), write_fn=_scan_write_fn, force=force,
        wait_timeout=(config.SCAN_WAIT_TIMEOUT_SECONDS if wait else 0.0), db_path=db_path)
    response.status_code = 202
    return ScanStatus(**st)


@app.get("/scan/status", response_model=ScanStatus)
def get_scan_status():
    return ScanStatus(**scan_manager.manager.status())
