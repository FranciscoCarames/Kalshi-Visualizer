"""Pure presentation viewmodel for the NiceGUI dashboard (PR 22) — NiceGUI-/Streamlit-free, unit-testable.

Input (the stored opportunity rows + coverage + control values) → display rows / filtered rows / scope
text / URL state. `webui/dashboard.py` is the thin NiceGUI shell that calls these builders; keeping the
logic here means the filtering, scope, and URL round-trip can be tested without a browser.

Filtering mirrors the Streamlit two-pass rule (see `filters.py`): MEMBERSHIP (sport / tournament /
participant) narrows EVERY row; THRESHOLDS (min size / active-only) narrow everything EXCEPT the
Actionable bucket and dutch-book rows (spared, like "Actionable now" in the Streamlit app). The unified
opportunity rows carry only a subset of fields, so the webui filters on those (sport / tournament / name /
exec_min_size / market_status); richer quote/layer filters need the persisted *checks* frame (PR 24/25).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import config
import data


# --- display-row builders (moved from dashboard.py; the canonical, testable home) -----
def ts_disp(ts: Any, tz: str) -> str:
    return data.fmt_time(datetime.fromtimestamp(ts, timezone.utc), tz, fmt="%H:%M:%S %Z") if ts else "—"


def opp_row(o: dict[str, Any], new_ids: set[str]) -> dict[str, Any]:
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "edge": o.get("exec_gap_c"), "roi": o.get("roi_pct"), "units": o.get("exec_min_size"),
        "profit": o.get("exec_max_profit_dollars"),
        "tradable": o.get("tradable_now") or "",
        # The non-blocking per-game settlement caveat (PR 6) shows alongside any blocked_reason, so an
        # actionable game book still surfaces its postponement risk.
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }


def backlog_row(b: dict[str, Any], tz: str) -> dict[str, Any]:
    dur = b.get("duration_s")
    return {
        "sport": b.get("sport") or "", "name": b.get("name") or "",
        "became": ts_disp(b.get("became_ts"), tz), "left": ts_disp(b.get("left_ts"), tz),
        "mins": round(dur / 60, 1) if isinstance(dur, (int, float)) else None,
        "reason": b.get("reason_left") or "", "last_edge": b.get("last_edge_c"),
        "current": b.get("current_status") or b.get("current_bucket") or "gone",
    }


def explanation_lines(opp: dict[str, Any], *, show_ids: bool = False) -> list[str]:
    """The text content of the explanation panel for one opportunity (pure → unit-testable)."""
    lines = [
        f"{opp.get('sport_label') or opp.get('sport')} · {opp.get('name')}",
        f"{opp.get('source')} · {opp.get('detail')} · {opp.get('tournament')}",
    ]
    legs = opp.get("legs")
    if isinstance(legs, list) and legs:                      # N-leg (synthetic bundle): list every leg
        lines += [f"Leg {i + 1}: {leg.get('text') or '—'}" for i, leg in enumerate(legs)]
    else:                                                     # 2-leg shapes use the positional fields
        lines += [f"Leg 1: {opp.get('action_1_text') or '—'}", f"Leg 2: {opp.get('action_2_text') or '—'}"]
    _roi = opp.get("roi_pct")
    _floor = opp.get("payout_floor_c")
    lines += [
        f"Cost: {opp.get('cost_c')}¢   ·   Floor: {_floor}¢   ·   Gross edge: {opp.get('exec_gap_c')}¢"
        + (f"   ·   ROI: {_roi}%" if _roi is not None else "")
        + f"   ·   Max units: {opp.get('exec_min_size')}   ·   Gross profit: ${opp.get('exec_max_profit_dollars')}",
        f"Tradable now: {opp.get('tradable_now')}   ·   Relationship: {opp.get('relationship_type')}"
        f"   ·   Market: {opp.get('market_status')}",
    ]
    if opp.get("settlement_caveat"):
        lines.append(f"Settlement caveat: {opp.get('settlement_caveat')}")
    if opp.get("blocked_reason"):
        lines.append(f"Caveat: {opp.get('blocked_reason')}")
    if show_ids:
        lines.append(f"id {opp.get('opportunity_id')} · {opp.get('ticker_1')} / {opp.get('ticker_2')}")
    return lines


# --- filtering (shape-branched; no fetch — narrows the STORED snapshot only) ----------
def _isna(x: Any) -> bool:
    return x is None or (isinstance(x, float) and x != x)


def _spared(o: dict[str, Any]) -> bool:
    """Thresholds spare the Actionable bucket and dutch-book rows (mirrors the Streamlit split)."""
    return o.get("bucket") == "actionable" or o.get("source") == "dutch_book"


def filter_opps(opps: Iterable[dict[str, Any]], *, sports: Iterable[str] | None = None,
                tournaments: Iterable[str] | None = None, participant: str = "",
                min_size: float | None = None, active_only: bool = False) -> list[dict[str, Any]]:
    """Apply the membership + threshold filters to the unified opportunity rows. Membership narrows every
    row; thresholds narrow everything except `_spared` rows. Empty/None selection = no filter; NaN-safe."""
    rows = list(opps or [])
    if sports:
        sset = set(sports)
        rows = [o for o in rows if o.get("sport") in sset]
    if tournaments:
        tset = set(tournaments)
        rows = [o for o in rows if o.get("tournament") in tset]
    if participant:
        needle = participant.strip().lower()
        rows = [o for o in rows if needle in str(o.get("name") or "").lower()]
    if min_size:
        rows = [o for o in rows
                if _spared(o) or (not _isna(o.get("exec_min_size")) and o.get("exec_min_size") >= min_size)]
    if active_only:
        rows = [o for o in rows if _spared(o) or str(o.get("market_status") or "") == "active"]
    return rows


def derive_options(opps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Select options sourced from the loaded snapshot, so a dropdown only offers what's present.
    `sports` is an ``{id: label}`` map (the filter matches the id); `tournaments` a sorted list."""
    sports: dict[str, str] = {}
    tournaments: set[str] = set()
    for o in opps or []:
        if o.get("sport"):
            sports[o["sport"]] = o.get("sport_label") or o["sport"]
        if o.get("tournament"):
            tournaments.add(o["tournament"])
    return {"sports": dict(sorted(sports.items())), "tournaments": sorted(tournaments)}


# --- scope banner (honest; surfaces the PR 21a counters) ------------------------------
def scope_banner(cov: dict[str, Any] | None, tz: str = "UTC", *, stale_after: float | None = None) -> str:
    """The data-scope line from the scan's own coverage meta (incl. contracts_scanned / checks_tested /
    kalshi_requests, distinct from the opportunity count). The data AGE is recomputed live from
    `fetched_at` (so a per-second timer keeps it current). Honest when there's no scan / no meta."""
    if not cov or cov.get("fetched_at") is None:
        return "No scan yet — press “Scan now”."
    when = data.fmt_time(cov["fetched_at"], tz, fmt="%H:%M:%S %Z")
    age = data.data_age_seconds(cov["fetched_at"])
    threshold = config.STALE_AFTER_SECONDS if stale_after is None else stale_after
    stale = "  ⚠ STALE" if data.is_stale(age, threshold) else ""
    parts = [f"Data {when} · age {int(age) if isinstance(age, (int, float)) else '—'}s{stale}",
             f"{cov.get('opportunities', 0)} opportunities"]
    if cov.get("meta_present"):
        parts.append(f"{cov.get('scanned', 0)} series · {cov.get('failed', 0)} failed")
        cs, ct = cov.get("contracts_scanned"), cov.get("checks_tested")
        parts.append(f"{cs or 0} contracts scanned · {ct or 0} checks tested")
        if cov.get("kalshi_requests") is not None:
            parts.append(f"{cov['kalshi_requests']} Kalshi requests")
    else:
        parts.append("no coverage meta")
    return " · ".join(parts)


# --- URL state (compact, graceful reset of unknown sport/tournament) ------------------
def state_from_query(params: dict[str, Any], *, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse compact query params into control values. A `sport`/`tournament` not present in the snapshot
    (`options`) is DROPPED, not errored (graceful reset of a stale link). `participant` is free text."""
    state: dict[str, Any] = {}
    valid_sports = set((options or {}).get("sports") or {})
    valid_tours = set((options or {}).get("tournaments") or [])
    if params.get("sport"):
        sel = [s for s in str(params["sport"]).split(",") if s and (options is None or s in valid_sports)]
        if sel:
            state["sports"] = sel
    if params.get("tournament"):
        sel = [t for t in str(params["tournament"]).split(",") if t and (options is None or t in valid_tours)]
        if sel:
            state["tournaments"] = sel
    if params.get("participant"):
        state["participant"] = str(params["participant"])
    if params.get("min_size"):
        try:
            state["min_size"] = float(params["min_size"])
        except (ValueError, TypeError):
            pass
    if str(params.get("active") or "").lower() in ("1", "true"):
        state["active_only"] = True
    return state


def query_from_state(state: dict[str, Any]) -> dict[str, str]:
    """The compact query string params for the current control state (empties omitted)."""
    q: dict[str, str] = {}
    if state.get("sports"):
        q["sport"] = ",".join(state["sports"])
    if state.get("tournaments"):
        q["tournament"] = ",".join(state["tournaments"])
    if state.get("participant"):
        q["participant"] = str(state["participant"])
    if state.get("min_size"):
        q["min_size"] = str(state["min_size"])
    if state.get("active_only"):
        q["active"] = "1"
    return q


def active_filter_chips(state: dict[str, Any], options: dict[str, Any] | None = None) -> list[str]:
    """Short human labels for the currently-active filters (for the filter-chips row)."""
    chips: list[str] = []
    smap = (options or {}).get("sports") or {}
    if state.get("sports"):
        chips.append("sport: " + ", ".join(smap.get(s, s) for s in state["sports"]))
    if state.get("tournaments"):
        chips.append("tournament: " + ", ".join(state["tournaments"]))
    if state.get("participant"):
        chips.append(f"participant: “{state['participant']}”")
    if state.get("min_size"):
        chips.append(f"min size ≥ {state['min_size']:g}")
    if state.get("active_only"):
        chips.append("active only")
    return chips
