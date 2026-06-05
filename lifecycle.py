"""Opportunity lifecycle — Stage 3 engine.

Pure snapshot-diff functions over the opportunity snapshots Stage 2 persists (`store.write_snapshot`):
new-actionable (§8), blocked-change "what changed" (§9), and the recently-actionable backlog (§10).
NO Streamlit, NO network, NO store import — the caller reads `store.latest_two()` /
`store.snapshots_since(window)` and passes the snapshot dicts in, so this module is side-effect-free and
unit-testable offline. State is DERIVED from the snapshot history (no extra persisted state): "first
seen" is just the earliest snapshot containing an id.

A snapshot dict is `{"fetched_at", "fetched_ts", "opportunities": [row, ...]}` (as returned by the
store); each `row` is a persisted unified opportunity carrying `opportunity_id`, `bucket`, `status`,
`blocked_reason`, `exec_gap_c`, `exec_min_size`, `tradable_now`, `market_status`, `rule_flag`, `sport`,
`name`, `url`, and the two action texts.
"""
from __future__ import annotations

from typing import Any

_NEG_INF = float("-inf")


def _ops(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list(snapshot.get("opportunities") or []) if snapshot else []


def _by_id(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {r.get("opportunity_id"): r for r in _ops(snapshot) if r.get("opportunity_id")}


def _actionable_ids(snapshot: dict[str, Any] | None) -> set[str]:
    return {r.get("opportunity_id") for r in _ops(snapshot) if r.get("bucket") == "actionable"}


def _num(x: Any) -> Any:
    """None for None or float NaN, so comparisons don't treat NaN != NaN as a spurious change."""
    return None if x is None or (isinstance(x, float) and x != x) else x


def _ordered(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Snapshots oldest→newest (defensive sort by numeric fetched_ts; the store already returns ascending)."""
    return sorted((s for s in (snapshots or []) if s), key=lambda s: s.get("fetched_ts") or _NEG_INF)


# --- §8: new-actionable -------------------------------------------------------------
def new_actionable(prev: dict[str, Any] | None, cur: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Rows actionable in `cur` but NOT in `prev`'s actionable set. `prev is None` (first load) → [] so a
    fresh start never floods false 'new' alerts (§8 'no-prev suppresses alerts')."""
    if cur is None or prev is None:
        return []
    prev_ids = _actionable_ids(prev)
    return [r for r in _ops(cur)
            if r.get("bucket") == "actionable" and r.get("opportunity_id") not in prev_ids]


def first_seen(snapshots: list[dict[str, Any]], opportunity_id: str,
               *, actionable_only: bool = False) -> float | None:
    """Numeric `fetched_ts` (epoch) of the earliest snapshot containing `opportunity_id` (or earliest
    while actionable, when `actionable_only`). Numeric so callers do window math without parsing text."""
    for snap in _ordered(snapshots):
        for r in _ops(snap):
            if r.get("opportunity_id") == opportunity_id and (
                    not actionable_only or r.get("bucket") == "actionable"):
                return snap.get("fetched_ts")
    return None


def persisting_new_actionable(history: list[dict[str, Any]], window_s: float | None,
                              *, now_ts: float | None = None) -> list[dict[str, Any]]:
    """Rows actionable in the LATEST snapshot whose first-actionable time is within `window_s` of
    `now_ts` — the banner-persistence set, so a still-actionable recent row keeps showing for the window.

    `history` MUST be the full retained/session history (not a `window_s` slice): first-actionable is
    computed over all of it, so an opportunity actionable LONGER than the window is correctly excluded
    rather than looking falsely 'new' once early snapshots are clipped. `window_s is None`
    ('until next refresh') → the single-transition `new_actionable` over the last two snapshots."""
    snaps = _ordered(history)
    if not snaps:
        return []
    if window_s is None:
        prev = snaps[-2] if len(snaps) >= 2 else None
        return new_actionable(prev, snaps[-1])
    cur = snaps[-1]
    ref = now_ts if now_ts is not None else (cur.get("fetched_ts") or 0.0)
    out: list[dict[str, Any]] = []
    for r in _ops(cur):
        if r.get("bucket") != "actionable":
            continue
        fs = first_seen(snaps, r.get("opportunity_id"), actionable_only=True)
        if fs is not None and (ref - fs) <= window_s:
            out.append(r)
    return out


# --- §9: blocked-change -------------------------------------------------------------
# (dimension label, accessor) — numeric fields compared NaN-safe so NaN!=NaN isn't a phantom change.
def _changes(prow: dict[str, Any], crow: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    if prow.get("blocked_reason") != crow.get("blocked_reason"):
        changes.append("blocker")
    if _num(prow.get("exec_gap_c")) != _num(crow.get("exec_gap_c")):
        changes.append("price")
    if _num(prow.get("exec_min_size")) != _num(crow.get("exec_min_size")):
        changes.append("liquidity")
    if prow.get("status") != crow.get("status"):
        changes.append("status")
    if prow.get("market_status") != crow.get("market_status"):
        changes.append("market_status")
    if prow.get("tradable_now") != crow.get("tradable_now"):
        changes.append("tradable_now")
    if (prow.get("rule_flag") or "") != (crow.get("rule_flag") or ""):
        changes.append("rule_flag_changed")
    return changes


def blocked_change(prev: dict[str, Any] | None, cur: dict[str, Any] | None) -> list[dict[str, Any]]:
    """For ids present in BOTH snapshots, emit when the row enters/leaves `blocked` or changes while
    blocked. `changes` is the §9 'what changed' set; nothing changed and no bucket transition → not
    emitted (§9 'No alert when nothing changed')."""
    if prev is None or cur is None:
        return []
    prev_by, cur_by = _by_id(prev), _by_id(cur)
    out: list[dict[str, Any]] = []
    for oid, crow in cur_by.items():
        prow = prev_by.get(oid)
        if prow is None:
            continue
        prev_blocked = prow.get("bucket") == "blocked"
        cur_blocked = crow.get("bucket") == "blocked"
        if not (prev_blocked or cur_blocked):
            continue                              # neither side blocked → not a blocked-change
        transitioned = prev_blocked != cur_blocked
        changes = _changes(prow, crow)
        if not changes and not transitioned:
            continue                              # blocked in both, nothing changed → no alert
        out.append({
            "opportunity_id": oid,
            "prev_bucket": prow.get("bucket"), "cur_bucket": crow.get("bucket"),
            "transitioned": transitioned, "changes": changes, "row": crow,
        })
    return out


# --- §10: recently-actionable backlog -----------------------------------------------
def _reason_left(cur_row: dict[str, Any] | None) -> str:
    """Why an opportunity is no longer actionable, in precedence order."""
    if cur_row is None:
        return "disappeared"
    if cur_row.get("market_status") == "inactive":
        return "leg inactive"
    if cur_row.get("bucket") == "blocked":
        return "went blocked"
    return "went clean"


def recently_actionable(snapshots: list[dict[str, Any]], *, now_ts: float | None = None
                        ) -> list[dict[str, Any]]:
    """Opportunities actionable in SOME snapshot in the given window but NOT in the latest. `snapshots`
    is the windowed history the caller fetched (`store.snapshots_since(window)`), oldest→newest. Returns
    §10 fields with numeric became/left timestamps, ordered most-recently-left first."""
    snaps = _ordered(snapshots)
    if not snaps:
        return []
    latest = snaps[-1]
    latest_by = _by_id(latest)
    latest_actionable = _actionable_ids(latest)

    actionable_snaps: dict[str, list[dict[str, Any]]] = {}
    for snap in snaps:
        for r in _ops(snap):
            if r.get("bucket") == "actionable" and r.get("opportunity_id"):
                actionable_snaps.setdefault(r["opportunity_id"], []).append(snap)

    out: list[dict[str, Any]] = []
    for oid, active in actionable_snaps.items():
        if oid in latest_actionable:
            continue                              # still actionable now → it's current, not "recently"
        became_ts = active[0].get("fetched_ts")
        last_active = active[-1]
        last_active_ts = last_active.get("fetched_ts")
        # left_ts = first snapshot strictly after the last actionable one (else the last-active time).
        left_ts = next((s.get("fetched_ts") for s in snaps
                        if (s.get("fetched_ts") or _NEG_INF) > (last_active_ts or _NEG_INF)), last_active_ts)
        duration_s = (last_active_ts - became_ts) if (became_ts is not None and last_active_ts is not None) else None
        last_row = _by_id(last_active).get(oid, {})
        cur_row = latest_by.get(oid)
        out.append({
            "opportunity_id": oid,
            "sport": last_row.get("sport"), "name": last_row.get("name"),
            "became_ts": became_ts, "left_ts": left_ts, "duration_s": duration_s,
            "reason_left": _reason_left(cur_row),
            "last_edge_c": _num(last_row.get("exec_gap_c")),
            "last_action_1_text": last_row.get("action_1_text"),
            "last_action_2_text": last_row.get("action_2_text"),
            # The full N-leg plan as it last looked actionable (PR 13); keep the 2 positional texts for
            # back-compat. None when the snapshot predates the `legs` column.
            "last_legs": last_row.get("legs"),
            "payout_floor_c": _num(last_row.get("payout_floor_c")),
            "roi_pct": _num(last_row.get("roi_pct")),
            # Non-blocking per-game settlement caveat as it last looked actionable (e.g. a postponed/
            # suspended game can settle differently). Carried so the backlog doesn't drop it.
            "last_settlement_caveat": last_row.get("settlement_caveat") or "",
            "current_status": (cur_row or {}).get("status"),
            "current_bucket": (cur_row or {}).get("bucket"),
            "url": last_row.get("url"),
        })
    out.sort(key=lambda d: d["left_ts"] if d["left_ts"] is not None else _NEG_INF, reverse=True)
    return out
