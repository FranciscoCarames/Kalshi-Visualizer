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

import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

import config
import consistency
import data
import scanner
import sports
import viz


# --- display-row builders (moved from dashboard.py; the canonical, testable home) -----
def ts_disp(ts: Any, tz: str) -> str:
    return data.fmt_time(datetime.fromtimestamp(ts, timezone.utc), tz, fmt="%H:%M:%S %Z") if ts else "—"


def classify_changes(prev: dict[str, dict], cur: dict[str, dict], ever_seen: set[str],
                     *, metric: str = "exec_gap_c") -> dict[str, str]:
    """Per-opportunity change vs the PREVIOUS snapshot, keyed by opportunity_id:
    'up'/'down' (the headline `metric` — gross edge — moved), 'new' (id never seen before),
    'returned' (seen before but absent in the previous snapshot), '' (unchanged). Pure; no UI. Computed
    once per new snapshot (see dashboard.reload_data) and persisted, so a plain filter re-render never
    re-derives or "replays" it."""
    out: dict[str, str] = {}
    for oid, o in cur.items():
        if oid in prev:
            a, b = _num_or_none(prev[oid].get(metric)), _num_or_none(o.get(metric))
            out[oid] = "" if (a is None or b is None or a == b) else ("up" if b > a else "down")
        else:
            out[oid] = "returned" if oid in ever_seen else "new"
    return out


def opp_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
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


# --- "Beyond the strict rule" (PR 29) — risk-budget candidates + near-miss books -----
# Pure band-filters + display-row builders for the two opt-in sections. They run over the already
# membership/threshold-filtered `view`, so sport/tournament/participant filters still apply; the band
# controls (max-loss ¢ + min upside:risk for risk-budget; max-overpay ¢ for near-miss) are the extra
# narrowing. Integer cents throughout; min upside:risk is compared as integer tenths (no float ratio).
def risk_budget_view(opps: Iterable[dict[str, Any]] | None, *, max_loss_c: float,
                     min_ratio_tenths: int = 0) -> list[dict[str, Any]]:
    """Risk-budget candidates whose worst-case loss ≤ `max_loss_c` ¢ and (optionally) whose upside:risk ≥
    `min_ratio_tenths`/10. A worst-case loss of 0 (cost exactly 100¢ — zero downside, convex upside) is the
    premium case and always passes the ratio gate."""
    out: list[dict[str, Any]] = []
    for o in (opps or []):
        if o.get("bucket") != "risk_budget":
            continue
        wc = o.get("worst_case_profit_c")
        if _isna(wc):
            continue
        risk = -wc                                    # worst-case loss ¢ (≥ 0)
        if risk > max_loss_c:
            continue
        bc = o.get("best_case_profit_c")
        if min_ratio_tenths and risk > 0 and not _isna(bc):
            if bc * 10 < min_ratio_tenths * risk:     # exact integer compare: best/risk ≥ ratio
                continue
        out.append(o)
    return out


def near_miss_view(opps: Iterable[dict[str, Any]] | None, *, max_over_c: float) -> list[dict[str, Any]]:
    """Near-miss dutch books overpriced by 1..`max_over_c` ¢ over their payout floor (a flat-payout
    guaranteed loss as a bundle — watchlist only)."""
    out: list[dict[str, Any]] = []
    for o in (opps or []):
        if o.get("bucket") != "near_miss":
            continue
        g = o.get("exec_gap_c")
        if _isna(g):
            continue
        if 1 <= -g <= max_over_c:                      # overpay = −gap
            out.append(o)
    return out


def _upside_risk(worst: Any, best: Any) -> Any:
    """Upside:risk ratio for display. '∞' when there's zero downside (risk 0 = the premium case);
    None when either side is missing."""
    if _isna(worst):
        return None
    risk = -worst
    if risk == 0:
        return "∞"
    return None if _isna(best) else round(best / risk, 1)


def risk_budget_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None) -> dict[str, Any]:
    """Display row for the risk-budget table: leads with the convex economics (max loss / max profit /
    upside:risk); worst-case ROC is a labelled secondary, never the headline (it's honestly negative)."""
    wc, bc = o.get("worst_case_profit_c"), o.get("best_case_profit_c")
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "max_loss": None if _isna(wc) else -wc,
        "max_profit": None if _isna(bc) else bc,
        "ratio": _upside_risk(wc, bc),
        "roc": o.get("roi_pct"),                       # worst-case ROC (gross, negative) — labelled, secondary
        "tradable": o.get("tradable_now") or "",
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }


def near_miss_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None) -> dict[str, Any]:
    """Display row for the near-miss watchlist: the cost, the overpay (= guaranteed bundle loss), and the
    flat-loss note. Never frames it as an edge."""
    g = o.get("exec_gap_c")
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "overpay": None if _isna(g) else -g,
        "tradable": o.get("tradable_now") or "",
        "note": o.get("settlement_caveat") or "",
    }


def backlog_row(b: dict[str, Any], tz: str) -> dict[str, Any]:
    dur = b.get("duration_s")
    return {
        "sport": b.get("sport") or "", "name": b.get("name") or "",
        "became": ts_disp(b.get("became_ts"), tz), "left": ts_disp(b.get("left_ts"), tz),
        "mins": round(dur / 60, 1) if isinstance(dur, (int, float)) else None,
        "reason": b.get("reason_left") or "", "last_edge": b.get("last_edge_c"),
        "caveat": b.get("last_settlement_caveat") or "",
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
    if opp.get("bucket") == "risk_budget":
        wc, bc = opp.get("worst_case_profit_c"), opp.get("best_case_profit_c")
        loss = "—" if _isna(wc) else -wc
        lines.append(f"Risk-budget (bounded loss, convex upside): max loss {loss}¢   ·   "
                     f"max profit {'—' if _isna(bc) else bc}¢   ·   upside:risk {_upside_risk(wc, bc)}   ·   "
                     "GROSS of fees — NOT locked.")
    elif opp.get("bucket") == "near_miss":
        g = opp.get("exec_gap_c")
        lines.append(f"Near-miss watchlist: overpay {'—' if _isna(g) else -g}¢ over the "
                     f"{opp.get('payout_floor_c')}¢ floor — a guaranteed gross loss as a bundle, NOT an edge.")
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
                tournaments: Iterable[str] | None = None, participant: Any = "",
                min_size: float | None = None, active_only: bool = False) -> list[dict[str, Any]]:
    """Apply the membership + threshold filters to the unified opportunity rows. Membership narrows every
    row; thresholds narrow everything except `_spared` rows. Empty/None selection = no filter; NaN-safe.

    `participant` is a LIST of participant keys (the multi-select, PR6) — a row matches if ANY selected key
    is among its `participant_keys` (so both sides of a match / every named leg are reachable). A plain
    string is still accepted as a legacy case-insensitive substring match on the opportunity name."""
    rows = list(opps or [])
    if sports:
        sset = set(sports)
        rows = [o for o in rows if o.get("sport") in sset]
    if tournaments:
        tset = set(tournaments)
        rows = [o for o in rows if o.get("tournament") in tset]
    if participant:
        if isinstance(participant, (list, tuple, set)):
            keyset = {str(k) for k in participant}
            rows = [o for o in rows if keyset.intersection(o.get("participant_keys") or [])]
        else:
            needle = str(participant).strip().lower()
            rows = [o for o in rows if needle in str(o.get("name") or "").lower()]
    if min_size:
        rows = [o for o in rows
                if _spared(o) or (not _isna(o.get("exec_min_size")) and o.get("exec_min_size") >= min_size)]
    if active_only:
        rows = [o for o in rows if _spared(o) or str(o.get("market_status") or "") == "active"]
    return rows


# --- ranking modes (#1/#9) — payoff GEOMETRY, no probability / no expected-value ---------------------
# Three display-time orderings over the already-filtered rows; buckets ALWAYS group first (Actionable
# before Review before Blocked …), and a mode only re-orders WITHIN a bucket. Pure in-memory re-sort of
# the cached opportunities — no rescan, no store read. Risk-budget geometry comes from the existing PR29
# payoff fields (worst/best_case_profit_c); a row missing them simply sorts last within its bucket.
RANK_MODES = {"blended": "Blended", "edge": "Per-unit edge ¢", "spread_upside": "Spread upside"}
RANK_MODE_DEFAULT = "blended"
# Within-bucket Blended weights (renormalized over the components a row actually has). ROI is weighted a
# touch above absolute edge so the owner's "a 2¢→3¢ gap is a 50% improvement just like 20¢→30¢" shows up —
# a small-edge/high-ROI row can out-rank a big-edge/low-ROI one. Pure-absolute lives in the "edge" mode.
_BLEND_W = {"edge": 0.35, "roi": 0.45, "geom": 0.2}


def _num_or_none(x: Any) -> float | None:
    return x if isinstance(x, (int, float)) and x == x else None


def _edge(o: dict[str, Any]) -> float:
    g = _num_or_none(o.get("exec_gap_c"))
    return g if g is not None else float("-inf")


def _geometry(o: dict[str, Any]) -> tuple[float, float, float] | None:
    """(max_loss_c, spread_upside_c, upside_risk_ratio) from the convex payoff bounds, or None when they
    aren't present. ratio = +inf when there's upside but zero downside (a bounded-loss-of-0 row)."""
    wc, bc = _num_or_none(o.get("worst_case_profit_c")), _num_or_none(o.get("best_case_profit_c"))
    if wc is None or bc is None:
        return None
    max_loss = max(0.0, -wc)
    if max_loss == 0:
        ratio = float("inf") if bc > 0 else 0.0
    else:
        ratio = bc / max_loss
    return (max_loss, bc, ratio)


def _norm(vals: list[float | None]) -> list[float | None]:
    """Min-max normalize the present (non-None) values to 0..1; a constant set -> all 0; absent -> None."""
    present = [v for v in vals if v is not None]
    if not present:
        return [None] * len(vals)
    lo, hi = min(present), max(present)
    if hi <= lo:
        return [0.0 if v is not None else None for v in vals]
    return [((v - lo) / (hi - lo)) if v is not None else None for v in vals]


def _blended_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    n = len(group)
    edges = _norm([_num_or_none(o.get("exec_gap_c")) for o in group])
    rois = _norm([_num_or_none(o.get("roi_pct")) for o in group])
    geo_raw: list[float | None] = [None] * n
    if is_risk:
        geos = [_geometry(o) for o in group]
        finite = [g[2] for g in geos if g and g[2] != float("inf")]
        cap = (max(finite) + 1) if finite else 1.0     # map an infinite ratio to one step above the max finite
        geo_raw = [None if g is None else (cap if g[2] == float("inf") else g[2]) for g in geos]
    geos_n = _norm(geo_raw)

    scored: list[tuple[float | None, dict[str, Any]]] = []
    for i, o in enumerate(group):
        parts = [(w, v) for w, v in ((_BLEND_W["edge"], edges[i]), (_BLEND_W["roi"], rois[i]),
                                     (_BLEND_W["geom"], geos_n[i])) if v is not None]
        score = (sum(w * v for w, v in parts) / sum(w for w, _ in parts)) if parts else None
        scored.append((score, o))
    # known scores first (descending); rows with no usable inputs last; edge/id break ties deterministically.
    return [o for _, o in sorted(
        scored, key=lambda sv: (0 if sv[0] is not None else 1, -(sv[0] or 0.0),
                                -_edge(sv[1]), sv[1].get("opportunity_id") or ""))]


def _spread_upside_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    if not is_risk:                                     # no convex payoff here -> fall back to edge
        return sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or ""))

    def key(o: dict[str, Any]) -> tuple:
        g = _geometry(o)
        if g is None:                                   # unknown geometry sorts AFTER known, by edge
            return (1, -_edge(o), 0.0, 0.0, o.get("opportunity_id") or "")
        max_loss, upside, ratio = g
        return (0, -ratio, -upside, max_loss, o.get("opportunity_id") or "")   # +inf ratio -> top
    return sorted(group, key=key)


def rank_opps(opps: Iterable[dict[str, Any]] | None, mode: str = RANK_MODE_DEFAULT) -> list[dict[str, Any]]:
    """Re-order opportunities by `mode` (see RANK_MODES). Buckets group first; the mode re-orders within a
    bucket only. Pure in-memory — switching modes never rescans or reads the store."""
    rows = list(opps or [])
    by_bucket: dict[Any, list[dict[str, Any]]] = {}
    for o in rows:
        by_bucket.setdefault(o.get("bucket"), []).append(o)
    out: list[dict[str, Any]] = []
    for bucket in sorted(by_bucket, key=lambda b: scanner.BUCKET_PRIORITY.get(b, 99)):
        group = by_bucket[bucket]
        is_risk = bucket == "risk_budget"
        if mode == "spread_upside":
            out.extend(_spread_upside_order(group, is_risk))
        elif mode == "blended":
            out.extend(_blended_order(group, is_risk))
        else:                                           # "edge" (and any unknown mode) -> per-unit edge ¢
            out.extend(sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or "")))
    return out


def derive_options(opps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Select options sourced from the loaded snapshot, so a dropdown only offers what's present.
    `sports` is an ``{id: label}`` map (the filter matches the id); `tournaments` a sorted list."""
    sports: dict[str, str] = {}
    tournaments: set[str] = set()
    pmap: dict[str, str] = {}        # participant_key -> display label (first label wins; stable across opps)
    for o in opps or []:
        if o.get("sport"):
            sports[o["sport"]] = o.get("sport_label") or o["sport"]
        if o.get("tournament"):
            tournaments.add(o["tournament"])
        for k, lab in zip(o.get("participant_keys") or [], o.get("participant_labels") or []):
            if k and k not in pmap:
                pmap[k] = lab or k
    # Key-based options (two same-named players never merge). Disambiguate a label shared by >1 key with a
    # short key suffix, mirroring the Streamlit "Name [key6]" convention.
    label_counts = Counter(pmap.values())
    participants = [{"value": k, "label": (f"{lab} [{k[:6]}]" if label_counts[lab] > 1 else lab)}
                    for k, lab in sorted(pmap.items(), key=lambda kv: (kv[1].lower(), kv[0]))]
    return {"sports": dict(sorted(sports.items())), "tournaments": sorted(tournaments),
            "participants": participants}


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
    """Parse compact query params into control values. A `sport`/`tournament`/`participant` not present in
    the snapshot (`options`) is DROPPED, not errored (graceful reset of a stale link). `participant` is a
    comma-separated, URL-encoded list of participant KEYS (PR6)."""
    state: dict[str, Any] = {}
    valid_sports = set((options or {}).get("sports") or {})
    valid_tours = set((options or {}).get("tournaments") or [])
    valid_participants = {p["value"] for p in (options or {}).get("participants") or []}
    if params.get("sport"):
        sel = [s for s in str(params["sport"]).split(",") if s and (options is None or s in valid_sports)]
        if sel:
            state["sports"] = sel
    if params.get("tournament"):
        sel = [t for t in str(params["tournament"]).split(",") if t and (options is None or t in valid_tours)]
        if sel:
            state["tournaments"] = sel
    if params.get("participant"):
        sel = [urllib.parse.unquote(p) for p in str(params["participant"]).split(",") if p]
        # validate against the snapshot's participants when options are supplied (stale-link reset)
        sel = [k for k in sel if not valid_participants or k in valid_participants]
        if sel:
            state["participant"] = sel
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
        q["participant"] = ",".join(urllib.parse.quote(str(k), safe="") for k in state["participant"])
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
        pmap = {p["value"]: p["label"] for p in (options or {}).get("participants") or []}
        chips.append("participant: " + ", ".join(pmap.get(k, k) for k in state["participant"]))
    if state.get("min_size"):
        chips.append(f"min size ≥ {state['min_size']:g}")
    if state.get("active_only"):
        chips.append("active only")
    return chips


# --- participant detail (PR 24) — pure builders over a participant's STORED contract rows ----------
def _num(v: Any) -> Any:
    return None if v is None or (isinstance(v, float) and v != v) else v


def detail_chain(prows: list[dict[str, Any]], sport: str) -> list[dict[str, Any]]:
    """The containment progression chain (broad → deep) for one participant, mirroring the Streamlit
    detail (app.py): one row per ladder node with its representative price. [] for a sport with no
    ladder (e.g. golf-less / unknown). Reuses consistency.build_player_nodes + representative."""
    cfg = sports.get_sport(sport)
    order = getattr(cfg.ladder, "node_order", ()) if cfg.ladder else ()
    if not order:
        return []
    nodes = consistency.build_player_nodes(list(prows or []))
    out: list[dict[str, Any]] = []
    for node in order:
        src = nodes.get(node, {})
        primary = consistency.representative(src)
        if primary is None:
            out.append({"layer": node, "source": "— missing —", "display_pct": None,
                        "bid_pct": None, "ask_pct": None, "quote": ""})
        else:
            out.append({"layer": node,
                        "source": "advance/winner" if "market" in src else "match-implied",
                        "display_pct": _num(primary.get("display_pct")),
                        "bid_pct": _num(primary.get("yes_bid_pct")), "ask_pct": _num(primary.get("yes_ask_pct")),
                        "quote": primary.get("quote_quality") or ""})
    return out


def detail_spreads(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Raw adjacent-layer stage-ladder spreads (broader − deeper). Reuses consistency.layer_spreads."""
    return consistency.layer_spreads(list(prows or []))


def detail_expected(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expected-vs-found ladder checklist (Layer / found / source). Reuses consistency.expected_nodes."""
    return consistency.expected_nodes(list(prows or []))


def detail_contracts(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All of a participant's contracts, sorted by stage_rank, with the display columns."""
    def _rank(r: dict[str, Any]) -> float:
        v = r.get("stage_rank")
        return v if isinstance(v, (int, float)) and v == v else 1e9
    return [{
        "contract": r.get("contract") or "", "category": r.get("category") or "",
        "stage": r.get("stage") or "", "opponent": r.get("opponent") or "",
        "display_pct": _num(r.get("display_pct")), "quote": r.get("quote_quality") or "",
        "bid_pct": _num(r.get("yes_bid_pct")), "ask_pct": _num(r.get("yes_ask_pct")),
        "volume": _num(r.get("volume")), "status": r.get("status") or "", "url": r.get("kalshi_url") or "",
    } for r in sorted(list(prows or []), key=_rank)]


_REL_EXPLAIN = {
    "containment": "Containment ladder: a deeper outcome (e.g. Win Tournament) is contained in a broader "
                   "one (e.g. Reach Final), so it must never price higher. The trade is Buy YES the broader "
                   "leg + Buy NO the deeper leg.",
    "dutch_book": "Dutch book: cover every (covered) outcome of a mutually-exclusive set for under the "
                  "payout floor — a gross pricing discrepancy under normal one-winner settlement. Covers "
                  "2-way match/game books, 3-way soccer games, and tournament-winner fields (overround on "
                  "the priceable subset). A per-game book carries a postponement caveat.",
    "synthetic_bundle": "Synthetic bundle: a player's exact-set-score contracts together replicate 'they "
                        "win', priced against their match-winner — settlement-caveated, shown review-only.",
}


def relationship_explanation(opp: dict[str, Any]) -> str:
    """Plain-English meaning of an opportunity's relationship type, with a SAFE fallback for an unknown
    type (never raises on a future relationship)."""
    rel = str(opp.get("relationship_type") or opp.get("source") or "")
    if opp.get("rule_flag") and rel.startswith("containment"):
        return ("Match-alignment equivalence: two DIFFERENT markets that should settle the same — "
                "rule-dependent, so it isn't guaranteed arbitrage (review the settlement rules).")
    return _REL_EXPLAIN.get(rel, f"Relationship: {rel or 'unknown'} — see the legs above.")


def ladder_chart_option(chain_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """An ECharts horizontal-bar `option` for the containment ladder (red bar = inverted), or None when
    fewer than 2 layers are priced (nothing to plot / non-containment)."""
    # viz.ladder_prices wants the Streamlit-style "Layer"/"Display %" keys; adapt the detail_chain rows.
    adapted = [{"Layer": r.get("layer", ""), "Display %": r.get("display_pct")} for r in (chain_rows or [])]
    recs = [r for r in viz.ladder_prices(adapted).to_dict("records") if r["display_pct"] is not None]
    if len(recs) < 2:
        return None
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "name": "Display %", "max": 100},
        "yAxis": {"type": "category", "data": [r["layer"] for r in recs]},
        "series": [{"type": "bar", "data": [
            {"value": r["display_pct"], "itemStyle": {"color": "#c62828" if r["inverted"] else "#1565c0"}}
            for r in recs]}],
    }


def payoff_chart_option(pay: dict[str, Any] | None) -> dict[str, Any] | None:
    """An ECharts bar `option` for the per-unit payoff (Floor/Bonus bars + a dashed cost line), or None
    for a None / non-containment payoff (the 'Risk' rows carry no payout and are dropped)."""
    recs = [r for r in viz.payoff_chart_data(pay).to_dict("records")
            if r["role"] != "Risk" and r["payout_c"] is not None]
    if not recs:
        return None
    colors = {"Floor": "#2e7d32", "Bonus": "#1565c0"}
    series: dict[str, Any] = {"type": "bar", "data": [
        {"value": r["payout_c"], "itemStyle": {"color": colors.get(r["role"], "#888")}} for r in recs]}
    cost = (pay or {}).get("cost_c")
    if cost is not None:
        series["markLine"] = {"symbol": "none", "lineStyle": {"color": "#c62828", "type": "dashed"},
                              "data": [{"yAxis": cost, "name": "cost"}]}
    return {"tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [r["scenario"] for r in recs]},
            "yAxis": {"type": "value", "name": "Payout ¢"}, "series": [series]}


# --- diagnostics / debug display builders (PR 25b) — pure projections over STORED frames ----------
def diagnostics_rows(check_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Project the stored consistency-check rows (all sports) to the full-diagnostics grid columns. The
    grid pages/filters/sorts client-side, so this is just a NaN-safe column projection."""
    return [{
        "player": r.get("player") or "", "chain": r.get("chain") or "",
        "tournament": r.get("tournament") or "", "status": r.get("status") or "",
        "status_group": r.get("status_group") or "", "rule_flag": r.get("rule_flag") or "",
        "executable_gap": _num(r.get("executable_gap")), "display_gap": _num(r.get("display_gap")),
        "reason": r.get("reason") or "",
    } for r in (check_rows or [])]


def non_laddered_rows(contract_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The contracts that aren't part of a containment ladder (per-game, props, awards, …) — shown for
    transparency, never silently dropped. Sorted by family then volume desc (mirrors the Streamlit app)."""
    out = [{
        "player": r.get("player") or "", "contract": r.get("contract") or "",
        "market_family": r.get("market_family") or "—", "category": r.get("category") or "",
        "classification_reason": r.get("classification_reason") or "",
        "display_pct": _num(r.get("display_pct")), "volume": _num(r.get("volume")),
        "status": r.get("status") or "", "url": r.get("kalshi_url") or "",
    } for r in (contract_rows or []) if not r.get("ladder_eligible")]
    out.sort(key=lambda r: (r["market_family"], -(r["volume"] or 0)))
    return out


def raw_fields_rows(contract_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Per-participant raw contract fields (incl. the tournament grouping source + mapping confidence) for
    the debug sub-panel — the NiceGUI twin of the Streamlit raw-fields table."""
    return [{
        "series": r.get("series") or "", "event_ticker": r.get("event_ticker") or "",
        "event_title": r.get("event_title") or "", "tournament": r.get("tournament") or "",
        "tournament_source": r.get("tournament_source") or "", "kind": r.get("kind") or "",
        "stage": r.get("stage") or "", "player_key": r.get("player_key") or "",
        "player_key_source": r.get("player_key_source") or "",
        "mapping_confidence": r.get("mapping_confidence") or "",
        "raw_yes_bid": r.get("raw_yes_bid"), "raw_yes_ask": r.get("raw_yes_ask"),
        "raw_no_bid": r.get("raw_no_bid"), "raw_no_ask": r.get("raw_no_ask"),
    } for r in (contract_rows or [])]


def sum_row_maxima(opps: Iterable[dict[str, Any]] | None) -> float:
    """The sum of per-opportunity max gross profit over the ACTIONABLE rows. Labelled "Sum of independent
    row maxima" in the UI, NOT "gross profit": each opportunity's max is independent, so the sum is not a
    guaranteed simultaneous total (you can't necessarily capture every maximum at once). NaN-safe."""
    total = 0.0
    for o in (opps or []):
        if o.get("bucket") == "actionable":
            v = o.get("exec_max_profit_dollars")
            if not _isna(v):
                total += float(v)
    return round(total, 2)


def link_audit_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Thin pass-through to data.link_audit (URL ↔ contract-identifier correctness), so the dashboard keeps
    importing only the viewmodel."""
    return data.link_audit(list(rows or []))


def duplicate_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Thin pass-through to consistency.duplicate_node_sources (where a representative was chosen among
    duplicates), for the debug sub-panel."""
    return consistency.duplicate_node_sources(list(rows or []))


# --- truthful empty states (PR 26a) — one honest message per empty scope, or None when there's content ---
def empty_state(*, cov: dict[str, Any] | None, total_opps: int, shown_opps: int,
                scan_status: dict[str, Any] | None = None) -> str | None:
    """The honest message to show when the opportunity area is empty, distinguishing WHY it's empty — or
    None when there is content (`shown_opps > 0`). Scopes: no-scan / scanning / scan-failed /
    no-opportunities / filter-hid-all. Never raises on missing keys (NaN/None-safe)."""
    if shown_opps > 0:
        return None
    status = (scan_status or {}).get("status")
    err = ((scan_status or {}).get("last_result") or {}).get("error")
    if not cov or cov.get("fetched_at") is None:
        if status == "in_progress":
            return "Scanning… results will appear here."
        return "No scan yet — press “Scan now (core series)”."
    if total_opps == 0:
        if status == "error" and err:
            return f"Last scan failed: {err}. Showing the last good snapshot (no opportunities)."
        return "Scan complete — no opportunities right now (between rounds, this is normal)."
    return f"All {total_opps} opportunities are hidden by the current filters — clear filters to see them."
