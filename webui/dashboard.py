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
import scan_scheduler
from webui import engine, export
from webui import viewmodel as vm

# Best-effort live viewer count (PR 25b): NiceGUI fires these on websocket connect/disconnect; the count
# feeds /metrics + the dashboard's own diagnostics heartbeat. Registered once at import (module load).
app.on_connect(lambda *_: presence.connect())
app.on_disconnect(lambda *_: presence.disconnect())

# Selected-row highlight (#14): make the clicked opportunity UNMISTAKABLE across every opportunity table.
# Targets Quasar QTable's `selected` row class, scoped to our `.opp-sel` tables. A translucent blue tint
# reads on BOTH the light and dark themes, and a solid left accent bar (`--q-primary`) is a non-colour cue
# (accessibility — colour is never the only signal). `!important` overrides Quasar's faint default. The
# visual result is a MANUAL browser check (the headless harness can't drive table row selection).
_SELECTED_ROW_CSS = (
    ".opp-sel tbody tr.selected > td { background-color: rgba(37, 99, 235, 0.22) !important; }\n"
    ".opp-sel tbody tr.selected > td:first-child { box-shadow: inset 4px 0 0 0 var(--q-primary); }"
)

# Accessibility (#10). Keyboard-focus visibility (a clear ring on whatever control is focused, in BOTH
# themes via --q-primary) + an opt-in "Larger text" mode scoped to `body.a11y-large` (NOT global `html`,
# so it's reversible and contained): bumps base text, the dense Quasar table cells/headers, and the small
# helper text. Paired with ARIA labels applied to every control/table (see _apply_aria below), and with
# colour cues that always carry text/icon companions elsewhere in the UI.
_A11Y_CSS = (
    "*:focus-visible { outline: 2px solid var(--q-primary) !important; outline-offset: 2px; }\n"
    "body.a11y-large { font-size: 112.5%; }\n"
    "body.a11y-large .q-table tbody td, body.a11y-large .q-table thead th { font-size: 1.05rem; }\n"
    "body.a11y-large .text-sm { font-size: 1rem; }\n"
    "body.a11y-large .text-xs { font-size: 0.9rem; }"
)


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
# "Beyond the strict rule" (PR 29). Risk-budget leads with the convex economics (max loss / max profit /
# upside:risk); worst-case ROC is a labelled secondary. Near-miss shows the overpay (= guaranteed loss).
_RISK_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center"},
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Participant / chain", "field": "name", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail"},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "sortable": True},
    {"name": "max_loss", "label": "Max loss ¢", "field": "max_loss", "sortable": True},
    {"name": "max_profit", "label": "Max profit ¢", "field": "max_profit", "sortable": True},
    {"name": "ratio", "label": "Upside:risk", "field": "ratio", "sortable": True},
    {"name": "roc", "label": "Worst-case ROC %", "field": "roc", "sortable": True},
    {"name": "tradable", "label": "Tradable", "field": "tradable"},
    {"name": "caveat", "label": "Caveat", "field": "caveat"},
]
_NEARMISS_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center"},
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Match", "field": "name", "sortable": True},
    {"name": "detail", "label": "Direction", "field": "detail"},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "sortable": True},
    {"name": "overpay", "label": "Overpay ¢", "field": "overpay", "sortable": True},
    {"name": "tradable", "label": "Tradable", "field": "tradable"},
    {"name": "note", "label": "Note", "field": "note"},
]
_BACKLOG_COLUMNS = [
    {"name": "sport", "label": "Sport", "field": "sport", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "sortable": True},
    {"name": "became", "label": "Became actionable", "field": "became"},
    {"name": "left", "label": "Left", "field": "left"},
    {"name": "mins", "label": "Lasted (min)", "field": "mins", "sortable": True},
    {"name": "reason", "label": "Why it left", "field": "reason"},
    {"name": "last_edge", "label": "Last edge ¢", "field": "last_edge"},
    {"name": "caveat", "label": "Settlement caveat", "field": "caveat"},
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
    # `opps` = id->opp (selection lookup); `opps_list` = the ranked list (for filtering/rerender);
    # `rendered_snapshot_id` = the snapshot the UI currently reflects (the poll's change-guard);
    # `new_ids`/`backlog`/`cov` are snapshot-scoped data the in-memory rerender reads without touching
    # the store. (P2: store reads happen in reload_data; rerender is pure in-memory.)
    state: dict[str, Any] = {"opps": {}, "opps_list": [], "seen_new": set(), "new_ids": set(),
                             "first": True, "options": {}, "cov": {}, "backlog": [],
                             "rendered_snapshot_id": "__unseeded__", "selected": None}

    ui.add_css(_SELECTED_ROW_CSS)        # selected-row highlight (#14) — see module note
    ui.add_css(_A11Y_CSS)                 # accessibility (#10): focus-visible ring + opt-in larger text
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
        rules_sw = ui.switch("Resolution criteria", value=False).tooltip(
            "Show each contract's settlement rules in the click panel and auto-open them in the detail view.")
        _darkmode = ui.dark_mode()
        dark_sw = ui.switch("Dark mode",
                            on_change=lambda e: _darkmode.enable() if e.value else _darkmode.disable()
                            ).tooltip("Toggle a dark theme.")
        larger_sw = ui.switch("Larger text").tooltip("Increase text size across the dashboard for readability.")
        larger_sw.on_value_change(
            lambda e: ui.query("body").classes(add="a11y-large") if e.value
            else ui.query("body").classes(remove="a11y-large"))
        scan_btn = ui.button("⟳ Scan now (core series)")
        export_btn = ui.button("⬇ Export (ZIP)")
        # Auto-refresh: drive the in-process scan scheduler (NON-force, TTL/budget-guarded). This control is
        # SERVER-WIDE shared state — one scheduler loop per process — so a change affects every viewer
        # (intended for a single-owner / small-LAN tool). The fetch cadence is the scan, not this widget.
        auto_sw = ui.switch("Auto-refresh", value=scan_scheduler.scheduler.enabled).tooltip(
            "Periodically re-scan in the background (server-wide). Off = manual 'Scan now' only.")
        interval_sel = ui.select(config.AUTO_SCAN_INTERVAL_OPTIONS,
                                  value=scan_scheduler.scheduler.interval_s, label="Every (s)").tooltip(
            "How often the background auto-scan runs.")
        auto_sw.on_value_change(lambda e: scan_scheduler.scheduler.set_enabled(bool(e.value)))
        interval_sel.on_value_change(lambda e: scan_scheduler.scheduler.set_interval(int(e.value)))

    # --- filters (narrow the STORED snapshot — NONE of these fetches) ---
    with ui.row().classes("items-end gap-4 flex-wrap"):
        sport_sel = ui.select({}, multiple=True, label="Sport").classes("min-w-[8rem]").props("dense")
        tour_sel = ui.select([], multiple=True, label="Tournament").classes("min-w-[10rem]").props("dense")
        participant_in = ui.input("Participant / match contains").classes("min-w-[12rem]")
        min_size_in = ui.number("Min size", min=0, format="%.0f").classes("w-28")
        active_sw = ui.switch("Active only").tooltip("Hide non-active (finalized/settled) markets.")
        show_review_sw = ui.switch("Review", value=True).tooltip(
            "Show the Review-signal section — settlement-caveated, never auto-tradable.")
        show_blocked_sw = ui.switch("Blocked", value=False).tooltip(   # hidden by default (PR S5)
            "Show the Blocked section — opportunities that exist but aren't currently tradable.")
        clear_btn = ui.button("Clear filters", on_click=lambda: _clear_filters())

    # --- "Beyond the strict rule" — two opt-in sections past the actionable line (PR 29) ---
    with ui.row().classes("items-end gap-4 flex-wrap"):
        ui.label("Beyond the strict rule:").classes("text-sm text-gray-500 self-center")
        rb_switch = ui.switch("Risk-budget candidates", value=False)
        rb_max_loss = ui.number("Max loss ¢", value=config.RISK_BUDGET_DEFAULT_MAX_LOSS_C,
                                min=1, max=config.RISK_BUDGET_MAX_LOSS_C, format="%.0f").classes("w-28")
        rb_min_ratio = ui.number("Min upside:risk", value=0, min=0, max=20, step=0.5,
                                 format="%.1f").classes("w-32")
        nm_switch = ui.switch("Near-miss books", value=False)
        nm_max_over = ui.number("Max overpay ¢", value=config.NEAR_MISS_DEFAULT_OVER_C,
                                min=1, max=config.NEAR_MISS_MAX_OVER_C, format="%.0f").classes("w-28")
    chips = ui.row().classes("gap-2 flex-wrap")

    freshness = ui.label().classes("text-sm")
    banner = ui.label().classes("text-sm font-medium")

    # --- explanation panel (row click) ---
    dialog = ui.dialog()

    def _leg_rules(opp: dict[str, Any]) -> list[tuple[str, str | None]]:
        """Per-leg (label, settlement-rules) for an opportunity, resolved by MARKET TICKER over the stored
        contracts (so it works for every shape — containment, dutch, soccer/field, synthetic — regardless
        of participant_key). A leg whose row / rules aren't in the snapshot yields None (truthful gap)."""
        sport = opp.get("sport") or None
        out: list[tuple[str, str | None]] = []
        for i, leg in enumerate(opp.get("legs") or [], start=1):
            tkr = leg.get("ticker") or ""
            label = leg.get("contract") or leg.get("text") or tkr or f"Leg {i}"
            row = engine.contract_by_ticker(tkr, sport=sport) if tkr else None
            rules = (row or {}).get("rules_primary")
            out.append((label, str(rules) if rules else None))
        return out

    def open_panel(opp: dict[str, Any]) -> None:
        dialog.clear()
        lines = vm.explanation_lines(opp, show_ids=show_ids.value)
        with dialog, ui.card().classes("w-[36rem]"):
            ui.label(lines[0]).classes("text-lg font-bold")
            ui.label(lines[1]).classes("text-sm text-gray-500")
            ui.separator()
            for line in lines[2:]:
                ui.label(line)
            if rules_sw.value:        # global "Resolution criteria" toggle — per-leg settlement rules
                ui.separator()
                ui.label("📜 Resolution criteria").classes("text-sm font-bold")
                legrules = _leg_rules(opp)
                if any(text for _, text in legrules):
                    for label, text in legrules:
                        ui.label(label).classes("text-sm font-medium")
                        ui.label(text or "— rules not captured in this snapshot —"
                                 ).classes("text-sm text-gray-600 mb-1")
                else:
                    ui.label("Resolution rules aren't captured in the latest snapshot."
                             ).classes("text-sm text-gray-500")
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
            # Resolution criteria / settlement rules per contract — a collapsible toggle (PR S5): trust
            # support for go-live, so a trader can read the rules without leaving the page.
            rules = [(r.get("contract") or r.get("market_ticker") or "—", str(r.get("rules_primary")))
                     for r in prows if r.get("rules_primary")]
            if rules:
                rules_exp = ui.expansion("📜 Resolution criteria (settlement rules)").classes("w-full mt-2")
                with rules_exp:
                    for contract, text in rules:
                        ui.label(contract).classes("text-sm font-medium")
                        ui.label(text).classes("text-sm text-gray-600 mb-2")
                if rules_sw.value:        # global toggle on → surface the rules without an extra click
                    rules_exp.open()
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

    _sel_tables: list[Any] = []   # all opportunity tables — keep exactly ONE row highlighted across them

    def _on_select(table):
        def handler(e: Any) -> None:
            sel = e.selection if hasattr(e, "selection") else None
            if sel:
                opp = state["opps"].get(sel[0].get("opportunity_id"))
                if opp:
                    state["selected"] = opp        # remember it so the rules toggle can re-render this view
                    open_panel(opp)
                    render_detail(opp)
                # Keep THIS row highlighted as a visible cue (PR S5), but clear the others so exactly one
                # opportunity is selected across all tables.
                for other in _sel_tables:
                    if other is not table:
                        other.selected = []
        return handler

    ui.separator()
    ui.label("Tip: click any row to open its full breakdown (resolution rules · ladder · contracts) below."
             ).classes("text-xs text-gray-500")
    ui.label("✅ Actionable now").classes("text-lg font-bold")
    # `overflow-x-auto` (PR 26a responsive pass): the wide opportunity tables scroll horizontally on a
    # narrow screen instead of overflowing the viewport. The control rows already wrap (flex-wrap).
    actionable = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                          selection="single", pagination=15).classes("w-full overflow-x-auto opp-sel")
    actionable.on_select(_on_select(actionable))

    # Risk-budget: containment near-misses (bounded loss, convex upside) — default hidden, toggled on.
    # Placed immediately AFTER Actionable (#2): when its switch is on, the risk-adjusted candidates sit
    # right below the actionable set (not below Review/Blocked). Visibility stays gated in rerender().
    rb_label = ui.label("🟡 Risk-budget candidates — cost slightly over 100¢ for a BOUNDED loss and a "
                        "CONVEX upside (broader-but-not-deeper pays +$1). GROSS of fees; NOT locked."
                        ).classes("text-lg font-bold")
    rb_table = ui.table(columns=_RISK_COLUMNS, rows=[], row_key="opportunity_id",
                        selection="single", pagination=10).classes("w-full overflow-x-auto opp-sel")
    rb_table.on_select(_on_select(rb_table))

    review_label = ui.label("🔎 Review signal (settlement-caveated — review the rules, never auto-tradable)"
                            ).classes("text-lg font-bold")
    review = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                      selection="single", pagination=10).classes("w-full overflow-x-auto opp-sel")
    review.on_select(_on_select(review))

    blocked_label = ui.label("⛔ Blocked").classes("text-lg font-bold")
    blocked = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id",
                       selection="single", pagination=10).classes("w-full overflow-x-auto opp-sel")
    blocked.on_select(_on_select(blocked))

    # Near-miss books: flat-payout watchlist (a guaranteed gross loss as a bundle) — default hidden.
    nm_label = ui.label("🔭 Near-miss books (watchlist) — sum just OVER the payout floor: FLAT payout, so a "
                        "guaranteed gross loss as a bundle. Watch for a mispriced leg; NOT an edge."
                        ).classes("text-lg font-bold")
    nm_table = ui.table(columns=_NEARMISS_COLUMNS, rows=[], row_key="opportunity_id",
                        selection="single", pagination=10).classes("w-full overflow-x-auto opp-sel")
    nm_table.on_select(_on_select(nm_table))
    _sel_tables.extend([actionable, review, blocked, rb_table, nm_table])

    with ui.expansion("📉 Recently actionable (left the actionable set)").classes("w-full"):
        backlog = ui.table(columns=_BACKLOG_COLUMNS, rows=[], row_key="name",
                           pagination=10).classes("w-full overflow-x-auto")

    # Participant/team detail (PR 24) — populated on opp row-click from the STORED frames (no fetch).
    detail_expansion = ui.expansion("🔬 Selected participant detail (click an opportunity)").classes("w-full")
    with detail_expansion:
        detail_box = ui.column().classes("w-full")

    # Diagnostics & debug (PR 25b) — observability over the STORED snapshot (no fetch); collapsed by default.
    diagnostics_expansion = ui.expansion("🔧 Diagnostics & debug").classes("w-full")
    with diagnostics_expansion:
        diagnostics_box = ui.column().classes("w-full")

    changed = ui.label().classes("text-sm text-orange-700")
    empty = ui.label().classes("text-gray-500")   # truthful empty state (PR 26a) — text set in refresh()

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
        rerender()        # membership filters are in-memory — no store read needed

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

    # --- data load vs render split (P2) -------------------------------------------------------------
    # reload_data(): the ONLY path that touches the store — offloaded via run.io_bound so it never blocks
    # the event loop; runs on a new snapshot (poll), a scan, first load, or a store-parameterized control.
    # rerender(): pure in-memory re-filter + push to the VISIBLE tables — no store access. poll(): a cheap
    # 1s tick that reloads ONLY when a new snapshot id lands. This makes filter changes instant (in-memory)
    # and a completed scan surface within ~1s, with idle ticks doing almost nothing.
    def _read_bundle(persist_s: float | None, win_s: float) -> dict[str, Any]:
        """All store reads for one render (snapshot + persistence-scoped alerts + windowed backlog),
        gathered off the event loop. Pure reads — NO UI here. (Engine reads share the P1 latest-snapshot
        cache, so concurrent clients deserialize a given snapshot once.)"""
        return {"cov": engine.coverage(), "opps": engine.latest_opportunities(),
                "alerts": engine.alerts(persist_s), "backlog": engine.backlog(win_s)}

    def _read_args() -> tuple:
        win_s = config.BACKLOG_WINDOWS[window_select.value]
        return (config.ALERT_PERSISTENCE_OPTIONS[persist_select.value],
                win_s if win_s is not None else config.SNAPSHOT_RETENTION_SECONDS)

    def _apply_bundle(bundle: dict[str, Any]) -> None:
        """Push a freshly-read store bundle into `state` + the snapshot-scoped UI (select options, alert
        banner), then rerender. A snapshot change forces a diagnostics rebuild (per-filter rerenders do
        not — that's the expensive path we keep off the hot loop). Sync, so the first paint (`_seed`) and
        the async `reload_data` share one code path."""
        cov, opps, al = bundle["cov"], bundle["opps"], bundle["alerts"]
        state["cov"] = cov
        state["opps_list"] = opps
        state["opps"] = {o.get("opportunity_id"): o for o in opps}
        state["options"] = vm.derive_options(opps)
        state["backlog"] = bundle["backlog"]
        sport_sel.options = state["options"]["sports"]
        tour_sel.options = state["options"]["tournaments"]
        sport_sel.update()
        tour_sel.update()
        # New-actionable toast + banner + blocked-change label (alerts are snapshot/persistence scoped).
        new_ids = {r.get("opportunity_id") for r in al["new_actionable"]}
        fresh = new_ids - state["seen_new"]
        if fresh and not state["first"]:
            ui.notify(f"🆕 {len(fresh)} newly actionable", type="positive")
        state["seen_new"] = new_ids
        state["new_ids"] = new_ids
        state["first"] = False
        banner.set_text(f"🆕 {len(new_ids)} newly actionable" if new_ids else "")
        n_ch = len(al["blocked_changes"])
        changed.set_text(f"🔁 {n_ch} changed while blocked" if n_ch else "")
        state["rendered_snapshot_id"] = cov.get("snapshot_id")
        rerender(force_diagnostics=True)

    async def reload_data() -> None:
        bundle = await run.io_bound(_read_bundle, *_read_args())   # store I/O off the event loop
        _apply_bundle(bundle)

    def rerender(force_diagnostics: bool = False) -> None:
        """Pure in-memory re-render from `state` — NO store access. Re-filter + push only the VISIBLE
        tables; refresh empty-state / chips / URL / freshness. Diagnostics (heavy store reads) rebuild
        ONLY on a snapshot change (`force_diagnostics`, set by `_apply_bundle`) or while its expander is
        open — never on an ordinary filter-change rerender."""
        tz = tz_select.value
        opps = state.get("opps_list") or []
        new_ids = state.get("new_ids") or set()
        cov = state.get("cov") or {}
        filters = _current_filters()
        view = vm.filter_opps(opps, **filters)
        # Truthful empty state by scope (PR 26a): no-scan / scanning / scan-failed / no-opportunities /
        # filter-hid-all — or hidden when there's content to show.
        msg = vm.empty_state(cov=cov, total_opps=len(opps), shown_opps=len(view),
                             scan_status=engine.scan_status())
        empty.set_text(msg or "")
        empty.set_visibility(msg is not None)

        actionable.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "actionable"]
        review.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "review_signal"]
        blocked.rows = [vm.opp_row(o, new_ids) for o in view if o.get("bucket") == "blocked"]
        for lbl, tbl, sw in ((review_label, review, show_review_sw), (blocked_label, blocked, show_blocked_sw)):
            lbl.set_visibility(sw.value)
            tbl.set_visibility(sw.value)

        # "Beyond the strict rule": filter the (already membership/threshold-filtered) view by the live
        # band controls; no rescan. Each section is hidden until its switch is on; its inputs disable too.
        if rb_switch.value:
            rbv = vm.risk_budget_view(view, max_loss_c=int(rb_max_loss.value or 0),
                                      min_ratio_tenths=round(float(rb_min_ratio.value or 0) * 10))
            rb_table.rows = [vm.risk_budget_row(o, new_ids) for o in rbv]
        rb_label.set_visibility(rb_switch.value)
        rb_table.set_visibility(rb_switch.value)
        rb_max_loss.set_enabled(rb_switch.value)
        rb_min_ratio.set_enabled(rb_switch.value)
        if nm_switch.value:
            nmv = vm.near_miss_view(view, max_over_c=int(nm_max_over.value or 0))
            nm_table.rows = [vm.near_miss_row(o, new_ids) for o in nmv]
        nm_label.set_visibility(nm_switch.value)
        nm_table.set_visibility(nm_switch.value)
        nm_max_over.set_enabled(nm_switch.value)

        backlog.rows = [vm.backlog_row(b, tz) for b in (state.get("backlog") or [])]

        # scope banner (with the PR 21a counters) + filter chips + URL state
        freshness.set_text(vm.scope_banner(cov, tz))
        chips.clear()
        with chips:
            for chip in vm.active_filter_chips(filters, state["options"]):
                ui.badge(chip).props("color=grey-7")
        _sync_url(filters)
        if force_diagnostics or diagnostics_expansion.value:   # heavy (store reads): snapshot change or open
            render_diagnostics(view)

    async def poll() -> None:
        """Cheap 1s tick: reload + rerender ONLY when a new snapshot id has landed. Otherwise this is a
        single indexed id query and nothing else — no deserialize, no WebSocket push (kills idle jank)."""
        if engine.latest_snapshot_id() != state.get("rendered_snapshot_id"):
            await reload_data()

    def _seed() -> None:
        """First load: seed the controls from the URL query (graceful reset of any sport/tournament absent
        from the snapshot), then do a SYNCHRONOUS first paint so the page renders immediately (no blank
        flash). Runs BEFORE the value-change handlers are bound, so setting these values fires no render."""
        options = vm.derive_options(engine.latest_opportunities())
        sport_sel.options = options["sports"]
        tour_sel.options = options["tournaments"]
        seeded = vm.state_from_query(query, options=options)
        sport_sel.value = seeded.get("sports", [])
        tour_sel.value = seeded.get("tournaments", [])
        participant_in.value = seeded.get("participant", "")
        min_size_in.value = seeded.get("min_size")
        active_sw.value = bool(seeded.get("active_only"))
        _apply_bundle(_read_bundle(*_read_args()))   # synchronous first paint (page-build thread)

    async def do_scan() -> None:
        scan_btn.disable()        # stale-while-scanning: only the Scan button is disabled; filters keep working
        n = ui.notification("Scanning (core series)…", spinner=True, timeout=None)
        try:
            st = await run.io_bound(engine.run_scan_now)    # NON-force (PR S3); network I/O off the event loop
            await reload_data()                              # surface the new snapshot immediately for this client
            status = st.get("status")
            if status == "done":
                cov = st.get("last_result") or {}
                n.message = f"Scan done · {cov.get('scanned')} series · {cov.get('failed')} failed"
                n.type = "positive"
            elif status == "in_progress":
                n.message = "A scan is already in progress — the latest data will appear when it finishes."
                n.type = "info"
            elif status == "skipped":
                reason = "data is already fresh" if st.get("reason") == "ttl" else (st.get("reason") or "skipped")
                n.message = f"Skipped — {reason}."
                n.type = "info"
            elif status == "error":
                cov = st.get("last_result") or {}
                n.message = f"Scan failed: {cov.get('error', 'unknown error')}"
                n.type = "negative"
            else:
                n.message = "Scan triggered."
                n.type = "info"
            n.spinner = False
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

    # Accessibility (#10): an explicit aria-label on every control + each data table + the key expansions,
    # so a screen reader announces a meaningful name (emoji/short labels and the unlabelled tables aren't
    # self-describing). Applied in one pass now that every element exists.
    for _el, _aria in (
        (tz_select, "Time zone"), (persist_select, "New-actionable banner persistence"),
        (window_select, "Backlog window"), (show_ids, "Show IDs and codes"),
        (rules_sw, "Show resolution criteria"), (dark_sw, "Dark mode"), (larger_sw, "Larger text"),
        (scan_btn, "Scan now (core series)"), (export_btn, "Export snapshot ZIP"),
        (auto_sw, "Auto-refresh in the background"), (interval_sel, "Auto-scan interval (seconds)"),
        (sport_sel, "Filter by sport"), (tour_sel, "Filter by tournament"),
        (participant_in, "Filter by participant or match"), (min_size_in, "Minimum tradable size"),
        (active_sw, "Active markets only"), (show_review_sw, "Show the Review-signal section"),
        (show_blocked_sw, "Show the Blocked section"), (clear_btn, "Clear all filters"),
        (rb_switch, "Show risk-budget candidates"), (rb_max_loss, "Risk-budget max loss in cents"),
        (rb_min_ratio, "Risk-budget minimum upside-to-risk ratio"),
        (nm_switch, "Show near-miss books"), (nm_max_over, "Near-miss max overpay in cents"),
        (actionable, "Actionable opportunities"), (review, "Review-signal opportunities"),
        (blocked, "Blocked opportunities"), (rb_table, "Risk-budget candidates"),
        (nm_table, "Near-miss books"), (backlog, "Recently-actionable backlog"),
        (detail_expansion, "Selected participant detail"), (diagnostics_expansion, "Diagnostics and debug"),
    ):
        _el.props(f'aria-label="{_aria}"')

    scan_btn.on_click(do_scan)
    export_btn.on_click(do_export)
    _seed()        # set control values from the URL BEFORE binding handlers (so seeding fires no render)

    # Filter / display controls re-render PURELY in-memory from the cached snapshot (no store, no fetch).
    for ctrl in (tz_select, show_ids, sport_sel, tour_sel, participant_in, min_size_in, active_sw,
                 show_review_sw, show_blocked_sw, rb_switch, rb_max_loss, rb_min_ratio,
                 nm_switch, nm_max_over):
        ctrl.on_value_change(lambda _=None: rerender())
    diagnostics_expansion.on_value_change(lambda _=None: rerender())   # render diagnostics when opened
    # Alert-persistence + backlog-window parameterize STORE reads, so they go through reload_data.
    for ctrl in (persist_select, window_select):
        ctrl.on_value_change(lambda _=None: reload_data())

    def _on_rules_toggle() -> None:
        # The global "Resolution criteria" switch re-renders only the views that are CURRENTLY open for the
        # selected opportunity — it never pops the dialog open on its own. Next row-click respects the toggle.
        sel = state.get("selected")
        if not sel:
            return
        if dialog.value:
            open_panel(sel)
        if detail_expansion.value:
            render_detail(sel)
    rules_sw.on_value_change(lambda _=None: _on_rules_toggle())

    def tick_age() -> None:
        # Re-render only the freshness/scope line each second (scope_banner recomputes the age live).
        freshness.set_text(vm.scope_banner(state.get("cov"), tz_select.value))

    ui.timer(config.UI_POLL_SECONDS, poll)        # snapshot-change watcher (cheap; reloads only on a new id)
    ui.timer(1.0, tick_age)
