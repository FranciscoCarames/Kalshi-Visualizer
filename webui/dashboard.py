"""Opportunity-first cross-sport dashboard (Stage 5) — NiceGUI, mounted on the FastAPI app.

A single `@ui.page('/')` that reads the engine in-process (via `webui.engine`) and renders it through the
pure `webui.viewmodel` builders: a scope/freshness banner, **membership + threshold filters** that narrow
the STORED snapshot (no control ever triggers a fetch), sortable Actionable / Review / Blocked tables, a
recently-actionable backlog, a clickable explanation panel, new-actionable + blocked-change alerts
(polling), filter chips + URL state, and a manual "Scan now" button. Detection + filtering logic live in
the engine / `viewmodel`; this module is the thin NiceGUI shell.
"""
from __future__ import annotations

from typing import Any

from nicegui import app, run, ui

import config
import presence
from webui import engine, export
from webui import viewmodel as vm

# Best-effort live viewer count (PR 25b): NiceGUI fires these on websocket connect/disconnect; the count
# feeds /metrics + the dashboard's own diagnostics heartbeat. Registered once at import (module load).
app.on_connect(lambda *_: presence.connect())
app.on_disconnect(lambda *_: presence.disconnect())


def _aggrid_options(rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> dict[str, Any]:
    """Client-side AG-Grid options (pagination + per-column filter/sort) over already-in-memory rows.
    `fields` is a list of (field, header) pairs. The grid does the paging/filtering/sorting in the browser,
    so this is just a column spec + the row data."""
    return {
        "columnDefs": [{"headerName": h, "field": f, "filter": True, "sortable": True, "resizable": True}
                       for f, h in fields],
        "rowData": rows,
        "pagination": True,
        "paginationPageSize": 20,
    }

_OPP_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center"},
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail"},
    {"name": "edge", "label": "Edge ¢", "field": "edge", "sortable": True},
    {"name": "roi", "label": "ROI %", "field": "roi", "sortable": True},
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
# Participant-detail tables (PR 24) — built by the pure viewmodel detail builders.
_CHAIN_COLUMNS = [
    {"name": "layer", "label": "Layer (broad → deep)", "field": "layer"},
    {"name": "source", "label": "Source", "field": "source"},
    {"name": "display_pct", "label": "Display %", "field": "display_pct", "sortable": True},
    {"name": "bid_pct", "label": "Bid %", "field": "bid_pct"},
    {"name": "ask_pct", "label": "Ask %", "field": "ask_pct"},
    {"name": "quote", "label": "Quote", "field": "quote"},
]
_SPREAD_COLUMNS = [
    {"name": "from_layer", "label": "Broader", "field": "from_layer"},
    {"name": "to_layer", "label": "Deeper", "field": "to_layer"},
    {"name": "spread_pct", "label": "Spread (pp)", "field": "spread_pct", "sortable": True},
    {"name": "spread_cents", "label": "Spread ¢", "field": "spread_cents"},
    {"name": "status", "label": "Status", "field": "status"},
    {"name": "quote", "label": "Quote", "field": "quote"},
]
_EXPECTED_COLUMNS = [
    {"name": "layer", "label": "Layer", "field": "layer"},
    {"name": "found", "label": "Found", "field": "found"},
    {"name": "source", "label": "Source", "field": "source"},
]
_DETAIL_CONTRACT_COLUMNS = [
    {"name": "contract", "label": "Contract", "field": "contract"},
    {"name": "category", "label": "Category", "field": "category"},
    {"name": "stage", "label": "Stage", "field": "stage"},
    {"name": "opponent", "label": "Opponent", "field": "opponent"},
    {"name": "display_pct", "label": "Display %", "field": "display_pct", "sortable": True},
    {"name": "quote", "label": "Quote", "field": "quote"},
    {"name": "volume", "label": "Volume", "field": "volume", "sortable": True},
    {"name": "status", "label": "Status", "field": "status"},
]


@ui.page("/")
def dashboard(sport: str = "", tournament: str = "", participant: str = "",
              min_size: str = "", active: str = "") -> None:
    # Compact URL state -> initial control values (validated against the snapshot in `_seed`).
    query = {"sport": sport, "tournament": tournament, "participant": participant,
             "min_size": min_size, "active": active}
    state: dict[str, Any] = {"opps": {}, "seen_new": set(), "first": True, "options": {}}

    ui.label("🎯 Kalshi opportunity engine — cross-sport").classes("text-2xl font-bold")
    ui.label("Opportunities across all sports, ranked best→worst. Core series, gross of fees — "
             "NOT all of Kalshi.").classes("text-sm text-gray-500")

    # --- display + scan controls ---
    with ui.row().classes("items-end gap-4 flex-wrap"):
        tz_select = ui.select(config.TIMEZONE_OPTIONS, value=config.TIMEZONE_DEFAULT, label="Time zone")
        persist_select = ui.select(list(config.ALERT_PERSISTENCE_OPTIONS), label="New-actionable banner",
                                   value=next(iter(config.ALERT_PERSISTENCE_OPTIONS)))
        window_select = ui.select(list(config.BACKLOG_WINDOWS), value=config.BACKLOG_DEFAULT,
                                   label="Backlog window")
        show_ids = ui.switch("Show IDs & codes", value=False)
        scan_btn = ui.button("⟳ Scan now (core series)")
        export_btn = ui.button("⬇ Export (ZIP)")

    # --- filters (narrow the STORED snapshot — NONE of these fetches) ---
    with ui.row().classes("items-end gap-4 flex-wrap"):
        sport_sel = ui.select({}, multiple=True, label="Sport").classes("min-w-[8rem]").props("dense")
        tour_sel = ui.select([], multiple=True, label="Tournament").classes("min-w-[10rem]").props("dense")
        participant_in = ui.input("Participant / match contains").classes("min-w-[12rem]")
        min_size_in = ui.number("Min size", min=0, format="%.0f").classes("w-28")
        active_sw = ui.switch("Active only")
        show_review_sw = ui.switch("Review", value=True)
        show_blocked_sw = ui.switch("Blocked", value=True)
        ui.button("Clear filters", on_click=lambda: _clear_filters())
    chips = ui.row().classes("gap-2 flex-wrap")

    freshness = ui.label().classes("text-sm")
    banner = ui.label().classes("text-sm font-medium")

    # --- explanation panel (row click) ---
    dialog = ui.dialog()

    def open_panel(opp: dict[str, Any]) -> None:
        dialog.clear()
        lines = vm.explanation_lines(opp, show_ids=show_ids.value)
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

    def render_detail(opp: dict[str, Any]) -> None:
        """Populate the '🔬 Selected participant detail' section from the STORED frames (no fetch): lead with
        the dense 2-leg action summary + relationship explanation, then chain / spreads / expected /
        all-contracts tables, then the optional/last guarded charts."""
        detail_box.clear()
        sport = opp.get("sport") or ""
        pkey = opp.get("participant_key") or ""
        with detail_box:
            ui.label(f"{opp.get('sport_label') or sport} · {opp.get('name')}").classes("text-lg font-bold")
            ui.label(vm.relationship_explanation(opp)).classes("text-sm text-gray-600")
            for line in vm.explanation_lines(opp, show_ids=show_ids.value)[2:]:
                ui.label(line).classes("text-sm")
            avail = engine.frame_availability()
            if avail != "present" or not pkey:
                ui.label("Evidence frames not captured for this snapshot — detail tables unavailable."
                         if avail != "present" else
                         "No participant key on this opportunity — detail tables unavailable."
                         ).classes("text-orange-700 mt-2")
                detail_expansion.open()
                return
            prows = engine.participant_contracts(sport, pkey)
            chain = vm.detail_chain(prows, sport)
            if chain:
                ui.label("Containment chain (broad → deep)").classes("font-medium mt-3")
                ui.table(columns=_CHAIN_COLUMNS, rows=chain, row_key="layer").classes("w-full")
            spreads = vm.detail_spreads(prows)
            if spreads:
                ui.label("Raw stage-ladder spreads").classes("font-medium mt-3")
                ui.table(columns=_SPREAD_COLUMNS, rows=spreads, row_key="to_layer").classes("w-full")
            expected = vm.detail_expected(prows)
            if expected:
                ui.label("Expected vs found").classes("font-medium mt-3")
                ui.table(columns=_EXPECTED_COLUMNS, rows=expected, row_key="layer").classes("w-full")
            contracts = vm.detail_contracts(prows)
            if contracts:
                ui.label(f"All contracts ({len(contracts)})").classes("font-medium mt-3")
                ui.table(columns=_DETAIL_CONTRACT_COLUMNS, rows=contracts, row_key="contract",
                         pagination=15).classes("w-full")
            if not (chain or spreads or expected or contracts):
                ui.label("No stored contracts for this participant in the latest snapshot."
                         ).classes("text-gray-500 mt-2")
            # Raw fields / link audit / duplicate sources — debug detail, only when "Show IDs & codes" is on.
            if show_ids.value and prows:
                with ui.expansion("🔧 Raw fields · link audit · duplicates").classes("w-full mt-2"):
                    raw = vm.raw_fields_rows(prows)
                    if raw:
                        ui.label("Raw contract fields (incl. tournament source + mapping confidence)"
                                 ).classes("text-sm font-medium")
                        ui.aggrid(_aggrid_options(raw, [
                            ("series", "Series"), ("event_ticker", "Event"), ("tournament", "Tournament"),
                            ("tournament_source", "T-source"), ("kind", "Kind"), ("stage", "Stage"),
                            ("player_key", "Player key"), ("player_key_source", "Key source"),
                            ("mapping_confidence", "Map conf"), ("raw_yes_bid", "y-bid"),
                            ("raw_yes_ask", "y-ask"), ("raw_no_bid", "n-bid"), ("raw_no_ask", "n-ask"),
                        ])).classes("w-full h-72")
                    audit = vm.link_audit_rows(prows)
                    if audit:
                        ui.label("Link audit — each URL vs the contract identifiers it encodes"
                                 ).classes("text-sm font-medium mt-2")
                        ui.aggrid(_aggrid_options(audit, [(k, k) for k in audit[0]])).classes("w-full h-60")
                    dups = vm.duplicate_rows(prows)
                    if dups:
                        ui.label("Duplicate node/source rows (representative chosen deterministically)"
                                 ).classes("text-sm font-medium mt-2")
                        ui.table(columns=[{"name": k, "label": k, "field": k} for k in dups[0]],
                                 rows=dups).classes("w-full")
            # Charts are optional/last — guarded to render only when the builder returns a non-None option
            # (containment shape only; dutch-book / game / missing-price rows yield None → skipped).
            ladder_opt = vm.ladder_chart_option(chain)
            payoff_opt = vm.payoff_chart_option(engine.payoff_for_opp(opp))
            if ladder_opt:
                ui.label("Ladder prices").classes("font-medium mt-3")
                ui.echart(ladder_opt).classes("w-full h-64")
            if payoff_opt:
                ui.label("Per-unit payoff by settlement scenario").classes("font-medium mt-3")
                ui.echart(payoff_opt).classes("w-full h-64")
        detail_expansion.open()

    def _on_select(table):
        def handler(e: Any) -> None:
            sel = e.selection if hasattr(e, "selection") else None
            if sel:
                opp = state["opps"].get(sel[0].get("opportunity_id"))
                if opp:
                    open_panel(opp)
                    render_detail(opp)
                table.selected = []   # allow re-selecting the same row
        return handler

    ui.separator()
    ui.label("✅ Actionable now").classes("text-lg font-bold")
    actionable = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                          selection="single", pagination=15).classes("w-full")
    actionable.on_select(_on_select(actionable))

    review_label = ui.label("🔎 Review signal (settlement-caveated — review the rules, never auto-tradable)"
                            ).classes("text-lg font-bold")
    review = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                      selection="single", pagination=10).classes("w-full")
    review.on_select(_on_select(review))

    blocked_label = ui.label("⛔ Blocked").classes("text-lg font-bold")
    blocked = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                       selection="single", pagination=10).classes("w-full")
    blocked.on_select(_on_select(blocked))

    with ui.expansion("📉 Recently actionable (left the actionable set)").classes("w-full"):
        backlog = ui.table(columns=_BACKLOG_COLUMNS, rows=[], row_key="name", pagination=10).classes("w-full")

    # Participant/team detail (PR 24) — populated on opp row-click from the STORED frames (no fetch).
    detail_expansion = ui.expansion("🔬 Selected participant detail (click an opportunity)").classes("w-full")
    with detail_expansion:
        detail_box = ui.column().classes("w-full")

    # Diagnostics & debug (PR 25b) — observability over the STORED snapshot (no fetch); collapsed by default.
    with ui.expansion("🔧 Diagnostics & debug").classes("w-full"):
        diagnostics_box = ui.column().classes("w-full")

    changed = ui.label().classes("text-sm text-orange-700")
    empty = ui.label("No scan yet — press “Scan now (core series)”.").classes("text-gray-500")

    # --- filter state plumbing ---
    def _current_filters() -> dict[str, Any]:
        s: dict[str, Any] = {}
        if sport_sel.value:
            s["sports"] = list(sport_sel.value)
        if tour_sel.value:
            s["tournaments"] = list(tour_sel.value)
        if (participant_in.value or "").strip():
            s["participant"] = participant_in.value.strip()
        if min_size_in.value:
            s["min_size"] = float(min_size_in.value)
        if active_sw.value:
            s["active_only"] = True
        return s

    def _clear_filters() -> None:
        sport_sel.value, tour_sel.value, participant_in.value = [], [], ""
        min_size_in.value, active_sw.value = None, False
        refresh()

    def _sync_url(filters: dict[str, Any]) -> None:
        q = vm.query_from_state(filters)
        qs = "?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else ""
        ui.run_javascript(f"history.replaceState(null, '', location.pathname + {qs!r})")

    def render_diagnostics(view: list[dict[str, Any]]) -> None:
        """Rebuild the Diagnostics & debug section from the STORED snapshot (no fetch): heartbeat + the
        honest 'Sum of independent row maxima' + category honesty + scan failures + the full-diagnostics
        and non-laddered AG-Grids. `view` is the already-filtered opportunity list (for the sum)."""
        diagnostics_box.clear()
        with diagnostics_box:
            m = engine.metrics()
            ui.label(
                f"scan: {m['scan_status']} · age {m['snapshot_age_seconds'] if m['snapshot_age_seconds'] is None else int(m['snapshot_age_seconds'])}s"
                f" · {m['kalshi_requests']} Kalshi req · {m['opportunities']} opps · viewers {m['viewer_count']}"
            ).classes("text-sm font-mono")
            ui.label(f"Sum of independent row maxima (actionable): ${vm.sum_row_maxima(view):,.2f}"
                     ).classes("text-sm font-medium mt-1")
            ui.label("Independent per-opportunity maxima — NOT a guaranteed simultaneous total (you can't "
                     "necessarily capture every maximum at once). Gross, before fees.").classes(
                "text-xs text-gray-500")

            cb = engine.category_breakdown()
            ui.label("Category honesty").classes("text-sm font-medium mt-3")
            ui.table(columns=[{"name": "k", "label": "Axis", "field": "k"},
                              {"name": "v", "label": "Count", "field": "v"}],
                     rows=[{"k": k, "v": cb[k]} for k in ("total", "laddered", "non_laddered",
                                                          "low_confidence", "unsupported")]).classes("w-full")
            ui.label("Non-laddered counts are transparency, not failures; low-confidence = name-fallback "
                     "identity; unsupported = no SportConfig owns the series.").classes("text-xs text-gray-500")

            failures = engine.diagnostics()
            ui.label("Scan failures").classes("text-sm font-medium mt-3")
            if failures["sport_errors"] or failures["series_errors"]:
                if failures["series_errors"]:
                    ui.aggrid(_aggrid_options(failures["series_errors"],
                                              [("sport", "Sport"), ("series", "Series"), ("error", "Error")]
                                              )).classes("w-full h-60")
                if failures["sport_errors"]:
                    ui.aggrid(_aggrid_options(failures["sport_errors"],
                                              [("sport", "Sport"), ("error", "Error")])).classes("w-full h-40")
            else:
                ui.label("All requested series loaded — no failures.").classes("text-sm text-green-700")

            checks = vm.diagnostics_rows(engine.all_checks())
            ui.label(f"Full diagnostics — all comparisons ({len(checks)})").classes("text-sm font-medium mt-3")
            if checks:
                ui.aggrid(_aggrid_options(checks, [
                    ("player", "Participant"), ("chain", "Chain"), ("tournament", "Tournament"),
                    ("status", "Status"), ("status_group", "Group"), ("rule_flag", "Rule"),
                    ("executable_gap", "Exec gap ¢"), ("display_gap", "Disp gap ¢"), ("reason", "Reason"),
                ])).classes("w-full h-96")
            else:
                ui.label("No comparisons in the latest snapshot.").classes("text-sm text-gray-500")

            unmapped = vm.non_laddered_rows(engine.all_contracts())
            ui.label(f"Non-laddered / unmapped contracts ({len(unmapped)})").classes("text-sm font-medium mt-3")
            if unmapped:
                ui.aggrid(_aggrid_options(unmapped, [
                    ("player", "Participant"), ("contract", "Contract"), ("market_family", "Family"),
                    ("category", "Type"), ("classification_reason", "Why not laddered"),
                    ("display_pct", "Display %"), ("volume", "Volume"), ("status", "Status"),
                ])).classes("w-full h-96")
            else:
                ui.label("Every loaded contract maps to a ladder.").classes("text-sm text-gray-500")

    # --- refresh (poll the store; re-render only — NEVER fetches) ---
    def refresh() -> None:
        tz = tz_select.value
        cov = engine.coverage()
        opps = engine.latest_opportunities()
        state["opps"] = {o.get("opportunity_id"): o for o in opps}
        state["options"] = vm.derive_options(opps)
        sport_sel.options = state["options"]["sports"]
        tour_sel.options = state["options"]["tournaments"]
        sport_sel.update()
        tour_sel.update()

        empty.set_visibility(cov["fetched_at"] is None)
        filters = _current_filters()
        view = vm.filter_opps(opps, **filters)

        al = engine.alerts(config.ALERT_PERSISTENCE_OPTIONS[persist_select.value])
        new_ids = {r.get("opportunity_id") for r in al["new_actionable"]}
        fresh = new_ids - state["seen_new"]
        if fresh and not state["first"]:
            ui.notify(f"🆕 {len(fresh)} newly actionable", type="positive")
        state["seen_new"] = new_ids
        state["first"] = False
        banner.set_text(f"🆕 {len(new_ids)} newly actionable" if new_ids else "")
        n_ch = len(al["blocked_changes"])
        changed.set_text(f"🔁 {n_ch} changed while blocked" if n_ch else "")

        actionable.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "actionable"]
        review.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "review_signal"]
        blocked.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "blocked"]
        for lbl, tbl, sw in ((review_label, review, show_review_sw), (blocked_label, blocked, show_blocked_sw)):
            lbl.set_visibility(sw.value)
            tbl.set_visibility(sw.value)

        win_s = config.BACKLOG_WINDOWS[window_select.value]
        bl = engine.backlog(win_s if win_s is not None else config.SNAPSHOT_RETENTION_SECONDS)
        backlog.rows = [vm.backlog_row(b, tz) for b in bl]

        # scope banner (with the PR 21a counters) + filter chips + URL state
        freshness.set_text(vm.scope_banner(cov, tz))
        chips.clear()
        with chips:
            for chip in vm.active_filter_chips(filters, state["options"]):
                ui.badge(chip).props("color=grey-7")
        _sync_url(filters)
        render_diagnostics(view)
        state["cov"] = cov

    def _seed() -> None:
        """First load: derive options from the snapshot, then seed the controls from the URL query with a
        graceful reset of any sport/tournament not present in the current snapshot."""
        opps = engine.latest_opportunities()
        options = vm.derive_options(opps)
        sport_sel.options = options["sports"]
        tour_sel.options = options["tournaments"]
        seeded = vm.state_from_query(query, options=options)
        sport_sel.value = seeded.get("sports", [])
        tour_sel.value = seeded.get("tournaments", [])
        participant_in.value = seeded.get("participant", "")
        min_size_in.value = seeded.get("min_size")
        active_sw.value = bool(seeded.get("active_only"))
        refresh()

    async def do_scan() -> None:
        scan_btn.disable()        # stale-while-scanning: only the Scan button is disabled; filters keep working
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

    def do_export() -> None:
        """Build the snapshot ZIP (filtered opportunities + persisted frames + backlog + manifest) and hand
        it to the browser. Reads the STORED snapshot only — no fetch."""
        cov = engine.coverage()
        if cov.get("snapshot_id") is None:
            ui.notify("Nothing to export yet — run a scan first.", type="warning")
            return
        filters = _current_filters()
        view = vm.filter_opps(engine.latest_opportunities(), **filters)
        win_label = window_select.value
        win_s = config.BACKLOG_WINDOWS[win_label]
        backlog = engine.backlog(win_s if win_s is not None else config.SNAPSHOT_RETENTION_SECONDS)
        blob = export.build_export_zip(
            snapshot_id=cov["snapshot_id"], fetched_at=cov.get("fetched_at"), opportunities=view,
            coverage=cov, frames=engine.frames(), backlog=backlog, backlog_window=win_label, filters=filters)
        ui.download.content(blob, f"kalshi-snapshot-{cov['snapshot_id']}.zip", "application/zip")
        ui.notify(f"Exported snapshot {cov['snapshot_id']} · {len(view)} opportunities", type="positive")

    scan_btn.on_click(do_scan)
    export_btn.on_click(do_export)
    # Every control re-renders from the stored snapshot — none of them fetches.
    for ctrl in (tz_select, persist_select, window_select, show_ids, sport_sel, tour_sel,
                 participant_in, min_size_in, active_sw, show_review_sw, show_blocked_sw):
        ctrl.on_value_change(lambda _=None: refresh())

    def tick_age() -> None:
        # Re-render only the freshness/scope line each second (scope_banner recomputes the age live).
        freshness.set_text(vm.scope_banner(state.get("cov"), tz_select.value))

    _seed()
    ui.timer(config.UI_REFRESH_SECONDS, refresh)
    ui.timer(1.0, tick_age)
