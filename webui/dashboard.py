"""Opportunity-first cross-sport dashboard (Stage 5) — NiceGUI, mounted on the FastAPI app.

A single `@ui.page('/')` that reads the engine in-process (via `webui.engine`): a per-second
data-freshness strip, sortable Actionable/Blocked tables, a recently-actionable backlog, a clickable
explanation panel, new-actionable + blocked-change alerts (polling), and a manual "Scan now" button
(core series — labelled honestly). Detection lives in the engine; this module is presentation only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nicegui import run, ui

import config
import data
from webui import engine

_OPP_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center"},
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail"},
    {"name": "edge", "label": "Edge ¢", "field": "edge", "sortable": True},
    {"name": "units", "label": "Max units", "field": "units", "sortable": True},
    {"name": "profit", "label": "Gross $", "field": "profit", "sortable": True},
    {"name": "tradable", "label": "Tradable", "field": "tradable"},
    {"name": "caveat", "label": "Caveat", "field": "caveat"},
]
_BACKLOG_COLUMNS = [
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "sortable": True},
    {"name": "became", "label": "Became actionable", "field": "became"},
    {"name": "left", "label": "Left", "field": "left"},
    {"name": "mins", "label": "Lasted (min)", "field": "mins", "sortable": True},
    {"name": "reason", "label": "Why it left", "field": "reason"},
    {"name": "last_edge", "label": "Last edge ¢", "field": "last_edge"},
    {"name": "current", "label": "Now", "field": "current"},
]


def _opp_row(o: dict[str, Any], new_ids: set[str]) -> dict[str, Any]:
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "edge": o.get("exec_gap_c"), "units": o.get("exec_min_size"),
        "profit": o.get("exec_max_profit_dollars"),
        "tradable": o.get("tradable_now") or "",
        # The non-blocking per-game settlement caveat (PR 6) shows alongside any blocked_reason, so an
        # actionable game book still surfaces its postponement risk.
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }


def _ts_disp(ts: Any, tz: str) -> str:
    return data.fmt_time(datetime.fromtimestamp(ts, timezone.utc), tz, fmt="%H:%M:%S %Z") if ts else "—"


def explanation_lines(opp: dict[str, Any], *, show_ids: bool = False) -> list[str]:
    """The text content of the explanation panel for one opportunity (pure → unit-testable).
    open_panel() renders these as labels and adds the leg links separately."""
    lines = [
        f"{opp.get('sport_label') or opp.get('sport')} · {opp.get('name')}",
        f"{opp.get('source')} · {opp.get('detail')} · {opp.get('tournament')}",
    ]
    legs = opp.get("legs")
    if isinstance(legs, list) and legs:                      # N-leg (synthetic bundle): list every leg
        lines += [f"Leg {i + 1}: {leg.get('text') or '—'}" for i, leg in enumerate(legs)]
    else:                                                     # 2-leg shapes use the positional fields
        lines += [f"Leg 1: {opp.get('action_1_text') or '—'}", f"Leg 2: {opp.get('action_2_text') or '—'}"]
    lines += [
        f"Cost: {opp.get('cost_c')}¢   ·   Gross edge: {opp.get('exec_gap_c')}¢   ·   "
        f"Max units: {opp.get('exec_min_size')}   ·   Gross profit: ${opp.get('exec_max_profit_dollars')}",
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


def _backlog_row(b: dict[str, Any], tz: str) -> dict[str, Any]:
    dur = b.get("duration_s")
    return {
        "sport": b.get("sport") or "", "name": b.get("name") or "",
        "became": _ts_disp(b.get("became_ts"), tz), "left": _ts_disp(b.get("left_ts"), tz),
        "mins": round(dur / 60, 1) if isinstance(dur, (int, float)) else None,
        "reason": b.get("reason_left") or "", "last_edge": b.get("last_edge_c"),
        "current": b.get("current_status") or b.get("current_bucket") or "gone",
    }


@ui.page("/")
def dashboard() -> None:
    state: dict[str, Any] = {"opps": {}, "seen_new": set(), "first": True}

    ui.label("🎯 Kalshi opportunity engine — cross-sport").classes("text-2xl font-bold")
    ui.label("Opportunities across all sports, ranked best→worst. Core series, gross of fees — "
             "NOT all of Kalshi.").classes("text-sm text-gray-500")

    # --- controls ---
    with ui.row().classes("items-end gap-4 flex-wrap"):
        tz_select = ui.select(config.TIMEZONE_OPTIONS, value=config.TIMEZONE_DEFAULT, label="Time zone")
        persist_select = ui.select(list(config.ALERT_PERSISTENCE_OPTIONS), label="New-actionable banner",
                                   value=next(iter(config.ALERT_PERSISTENCE_OPTIONS)))
        window_select = ui.select(list(config.BACKLOG_WINDOWS), value=config.BACKLOG_DEFAULT,
                                   label="Backlog window")
        show_ids = ui.switch("Show IDs & codes", value=False)
        scan_btn = ui.button("⟳ Scan now (core series)")

    freshness = ui.label().classes("text-sm")
    banner = ui.label().classes("text-sm font-medium")

    # --- explanation panel (row click) ---
    dialog = ui.dialog()

    def open_panel(opp: dict[str, Any]) -> None:
        dialog.clear()
        lines = explanation_lines(opp, show_ids=show_ids.value)
        with dialog, ui.card().classes("w-[36rem]"):
            ui.label(lines[0]).classes("text-lg font-bold")
            ui.label(lines[1]).classes("text-sm text-gray-500")
            ui.separator()
            for line in lines[2:]:
                ui.label(line)
            with ui.row():
                legs = opp.get("legs")
                if isinstance(legs, list) and legs:           # N-leg: one link per leg with a url
                    for i, leg in enumerate(legs):
                        if leg.get("url"):
                            ui.link(f"Leg {i + 1} market ↗", leg["url"], new_tab=True)
                else:
                    if opp.get("url"):
                        ui.link("Leg 1 market ↗", opp["url"], new_tab=True)
                    if opp.get("url_2"):
                        ui.link("Leg 2 market ↗", opp["url_2"], new_tab=True)
            ui.button("Close", on_click=dialog.close)
        dialog.open()

    def _on_select(table):
        def handler(e: Any) -> None:
            sel = e.selection if hasattr(e, "selection") else None
            if sel:
                opp = state["opps"].get(sel[0].get("opportunity_id"))
                if opp:
                    open_panel(opp)
                table.selected = []   # allow re-selecting the same row
        return handler

    ui.separator()
    ui.label("✅ Actionable now").classes("text-lg font-bold")
    actionable = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                          selection="single", pagination=15).classes("w-full")
    actionable.on_select(_on_select(actionable))

    ui.label("⛔ Blocked").classes("text-lg font-bold")
    blocked = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                       selection="single", pagination=10).classes("w-full")
    blocked.on_select(_on_select(blocked))

    with ui.expansion("📉 Recently actionable (left the actionable set)").classes("w-full"):
        backlog = ui.table(columns=_BACKLOG_COLUMNS, rows=[], row_key="name", pagination=10).classes("w-full")

    changed = ui.label().classes("text-sm text-orange-700")
    empty = ui.label("No scan yet — press “Scan now (core series)”.").classes("text-gray-500")

    # --- refresh (poll the store) ---
    def refresh() -> None:
        tz = tz_select.value
        cov = engine.coverage()
        if not cov["meta_present"] and cov["opportunities"] == 0 and cov["fetched_at"] is None:
            empty.set_visibility(True)
        else:
            empty.set_visibility(False)
        opps = engine.latest_opportunities()
        state["opps"] = {o.get("opportunity_id"): o for o in opps}

        al = engine.alerts(config.ALERT_PERSISTENCE_OPTIONS[persist_select.value])
        new_ids = {r.get("opportunity_id") for r in al["new_actionable"]}
        # toast only on genuinely-new ids since last poll (suppress the very first load)
        fresh = new_ids - state["seen_new"]
        if fresh and not state["first"]:
            ui.notify(f"🆕 {len(fresh)} newly actionable", type="positive")
        state["seen_new"] = new_ids
        state["first"] = False
        banner.set_text(f"🆕 {len(new_ids)} newly actionable" if new_ids else "")
        n_ch = len(al["blocked_changes"])
        changed.set_text(f"🔁 {n_ch} changed while blocked" if n_ch else "")

        actionable.rows = [_opp_row(o, new_ids) for o in opps if o.get("bucket") == "actionable"]
        blocked.rows = [_opp_row(o, new_ids) for o in opps if o.get("bucket") == "blocked"]
        win_s = config.BACKLOG_WINDOWS[window_select.value]
        bl = engine.backlog(win_s if win_s is not None else config.SNAPSHOT_RETENTION_SECONDS)
        backlog.rows = [_backlog_row(b, tz) for b in bl]
        state["cov"] = cov

    def tick_age() -> None:
        cov = state.get("cov")
        if not cov or cov.get("fetched_at") is None:
            freshness.set_text("No data yet.")
            return
        age = data.data_age_seconds(cov["fetched_at"])
        stale = "  ⚠ STALE" if data.is_stale(age, config.STALE_AFTER_SECONDS) else ""
        when = data.fmt_time(cov["fetched_at"], tz_select.value, fmt="%H:%M:%S %Z")
        scope = f"{cov['scanned']} series · {cov['failed']} failed" if cov["meta_present"] else "no coverage meta"
        freshness.set_text(f"Data {when} · age {int(age) if age is not None else '—'}s{stale} · "
                           f"{cov['opportunities']} opportunities · {scope}")

    async def do_scan() -> None:
        scan_btn.disable()
        n = ui.notification("Scanning (core series)…", spinner=True, timeout=None)
        try:
            cov = await run.io_bound(engine.run_scan_now)   # network I/O off the event loop
            refresh()
            n.message = f"Scan done · {cov.get('scanned')} series · {cov.get('failed')} failed"
            n.spinner = False
            n.type = "positive"
        finally:
            n.dismiss()
            scan_btn.enable()

    scan_btn.on_click(do_scan)
    for ctrl in (tz_select, persist_select, window_select, show_ids):
        ctrl.on_value_change(lambda _=None: refresh())

    refresh()
    ui.timer(config.UI_REFRESH_SECONDS, refresh)
    ui.timer(1.0, tick_age)
