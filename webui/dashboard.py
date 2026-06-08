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

# Green flash on new rows (PR B) — a one-shot fade applied to the indicator cell of a row that is new or
# newly-actionable THIS snapshot (driven by `_flash`, set only on the snapshot-change rerender and cleared
# right after, so filter re-renders never replay it). `animation: … 1` runs once; honoured-down for users
# who prefer reduced motion. Green works on both themes (semi-transparent over the cell).
_FLASH_CSS = (
    "@keyframes oppFlash { from { background-color: rgba(34, 197, 94, 0.55); } "
    "to { background-color: transparent; } }\n"
    ".opp-flash { animation: oppFlash 1.8s ease-out 1; }\n"
    "@media (prefers-reduced-motion: reduce) { .opp-flash { animation: none; } }"
)

# Change-signal (#3) — a Quasar body-cell slot on the indicator column: a coloured, shaped marker of how
# each opportunity moved since the last scan. Newly-actionable shows a green "NEW" badge (top priority);
# otherwise an edge that moved up (green up-arrow) / down (red down-arrow), returned (amber undo), or a
# newly-appeared opp (blue fiber_new icon) — colour AND icon/text, never colour alone. The cell also carries
# the one-shot `opp-flash` class (PR B) when `props.row._flash` is set.
_CHANGE_CELL_SLOT = (
    '<q-td :props="props" class="text-center" :class="props.row._flash ? \'opp-flash\' : \'\'">'
    '<q-badge v-if="props.row.new" color="positive">NEW</q-badge>'
    '<q-icon v-else-if="props.row._change==\'up\'" name="arrow_upward" color="positive" size="sm">'
    '<q-tooltip>edge up since the last scan</q-tooltip></q-icon>'
    '<q-icon v-else-if="props.row._change==\'down\'" name="arrow_downward" color="negative" size="sm">'
    '<q-tooltip>edge down since the last scan</q-tooltip></q-icon>'
    '<q-icon v-else-if="props.row._change==\'returned\'" name="undo" color="amber-8" size="sm">'
    '<q-tooltip>returned this scan</q-tooltip></q-icon>'
    '<q-icon v-else-if="props.row._change==\'new\'" name="fiber_new" color="primary" size="sm">'
    '<q-tooltip>new this scan</q-tooltip></q-icon>'
    '</q-td>'
)

# Numeric-cell slot — DISPLAY-ONLY thousands separators (the slot changes display only; Quasar still sorts
# on the raw numeric `field`, so sorting is preserved). Finite numbers render with `toLocaleString` (commas,
# ≤2 decimals); a null/blank/non-finite value (e.g. ratio "∞") passes through untouched. `colored=True`
# additionally tints the value green/red when the row's edge moved up/down (used for the gross-edge cell).
def _num_cell_slot(field: str, *, colored: bool = False) -> str:
    inner = ('<span v-if="props.row.%s != null && isFinite(props.row.%s)">'
             "{{ Number(props.row.%s).toLocaleString('en-US', {maximumFractionDigits: 2}) }}</span>"
             '<span v-else>{{ props.row.%s }}</span>') % (field, field, field, field)
    if colored:
        cls = ('props.row._change==="up" ? "text-positive text-weight-bold" : '
               'props.row._change==="down" ? "text-negative text-weight-bold" : ""')
        return '<q-td :props="props" class="text-center"><span :class=\'%s\'>%s</span></q-td>' % (cls, inner)
    return '<q-td :props="props" class="text-center">%s</q-td>' % inner


_EDGE_CELL_SLOT = _num_cell_slot("edge", colored=True)   # gross edge: commas + green/red on change

# Caveat-cell slot (PR A compaction): a COMPACT, content-descriptive severity chip (COLOUR + TEXT —
# blocker=red, review=amber, advisory=grey) instead of full prose. Full text is on the chip tooltip and in
# the click→detail panel. Left-aligned with the other text columns.
_CAVEAT_CELL_SLOT = (
    '<q-td :props="props" class="text-left">'
    '<q-badge v-if="props.row._sev" '
    ':color="props.row._sev===\'blocker\' ? \'negative\' : '
    'props.row._sev===\'review_required\' ? \'warning\' : \'grey-7\'">{{ props.row._caveat_tag }}'
    '<q-tooltip max-width="22rem">{{ props.row.caveat }}</q-tooltip></q-badge></q-td>'
)

# Long free-text cells — LEFT-aligned with a comfortable width so the text flows as full sentences instead
# of collapsing to one word per line (the action legs and the near-miss note).
_ACTION_CELL_SLOT = (
    '<q-td :props="props" class="text-left" '
    'style="white-space: normal; min-width: 14rem; max-width: 26rem;">{{ props.row.action }}</q-td>'
)
_NOTE_CELL_SLOT = (
    '<q-td :props="props" class="text-left" '
    'style="white-space: normal; min-width: 18rem; max-width: 32rem;">{{ props.row.note }}</q-td>'
)


def _notify(message: str, *, type: str = "info", position: str = "top-right") -> None:
    """Single entry point for transient toasts (PR A2). Defaults to the top-right corner so toasts don't
    cover the controls/rows the user is reading. Call within a page context (like ui.notify itself)."""
    ui.notify(message, type=type, position=position)


def build_column_menu(table: Any, columns: list[dict[str, Any]], *,
                      default_hidden: tuple[str, ...] = ()) -> dict[str, Any]:
    """Per-table column show/hide (redesigned): a compact "Columns" button that opens a tidy menu of labeled
    checkboxes (ticked = shown), one per non-`required` column. The leading `new` marker is `required` so it
    is never offered and always shown. Toggling a box drives Quasar's `visible-columns` (`_props` is the
    supported path for a list prop) + `table.update()`. Must be called within a UI container so the button
    lands where you want it. Returns a controller with `set(name, show)` so the net-of-fees switch can drive
    the net columns externally and keep the checkboxes in sync."""
    required = [c["name"] for c in columns if c.get("required")]
    hideable = [c for c in columns if not c.get("required")]
    order = [c["name"] for c in hideable]
    visible = {c["name"] for c in hideable if c["name"] not in default_hidden}
    checkboxes: dict[str, Any] = {}

    def _apply() -> None:
        table._props["visible-columns"] = required + [n for n in order if n in visible]
        table.update()

    def _set(name: str, show: bool) -> None:
        visible.add(name) if show else visible.discard(name)
        if name in checkboxes and checkboxes[name].value != show:
            checkboxes[name].value = show
        _apply()

    btn = ui.button(icon="view_column").props("flat dense round size=sm color=grey").tooltip("Show / hide columns")
    btn.on("click.stop", lambda: None)   # when placed in an expansion header, don't toggle the expansion
    with btn, ui.menu(), ui.column().classes("q-pa-sm gap-1"):
        ui.label("Show columns").classes("text-xs text-weight-bold q-mb-xs")
        for c in hideable:
            cb = ui.checkbox(c["label"] or c["name"], value=(c["name"] in visible)).props("dense")
            cb.on_value_change(lambda e, n=c["name"]: _set(n, bool(e.value)))
            checkboxes[c["name"]] = cb
    _apply()                                                           # set the initial visible-columns
    return {"set": _set, "button": btn}


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

# Column alignment convention (professional pass): short numeric / status / marker columns are CENTRED
# (header + cell); long free-text columns (name, detail, action, caveat, note) are LEFT-aligned so prose
# reads naturally. Centred headers read as centred titles on the short columns.
_OPP_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},  # never hideable
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "align": "left", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
    {"name": "action", "label": "Action plan", "field": "action", "align": "left"},   # legs only (PR compact)
    {"name": "edge", "label": "Gross edge ¢", "field": "edge", "align": "center", "sortable": True},
    {"name": "roi", "label": "ROI %", "field": "roi", "align": "center", "sortable": True},
    {"name": "units", "label": "Max units", "field": "units", "align": "center", "sortable": True},
    {"name": "profit", "label": "Max gross profit", "field": "profit", "align": "center", "sortable": True},
    # Net-of-fees ESTIMATE (PR E) — DEFAULT-HIDDEN; the "Show net of fees" switch + the column menu reveal
    # them. "Est." labels (a general taker-fee estimate, display only — never affects ranking).
    {"name": "net_edge", "label": "Est. net edge ¢", "field": "net_edge", "align": "center", "sortable": True},
    {"name": "net_profit", "label": "Est. net max profit", "field": "net_profit", "align": "center", "sortable": True},
    {"name": "fees", "label": "Est. fees ¢", "field": "fees", "align": "center", "sortable": True},
    {"name": "tradable", "label": "Tradable", "field": "tradable", "align": "center"},
    {"name": "caveat", "label": "Caveat", "field": "caveat", "align": "left"},
]
# Net-of-fees columns (PR E) — default-hidden in the opp tables; toggled by the "Show net of fees" switch.
_NET_COLUMNS = ("net_edge", "net_profit", "fees")
# Bounded-Loss Bets table (split from the old merged watchlist): convex economics up front; spread÷parent
# and spread÷child are VISIBLE BY DEFAULT (owner); the outright/display-spread context starts hidden.
_RISK_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / chain", "field": "name", "align": "left", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "align": "center", "sortable": True},
    {"name": "max_loss", "label": "Max loss ¢", "field": "max_loss", "align": "center", "sortable": True},
    {"name": "max_profit", "label": "Max profit ¢", "field": "max_profit", "align": "center", "sortable": True},
    {"name": "ratio", "label": "Upside:risk", "field": "ratio", "align": "center", "sortable": True},
    {"name": "roc", "label": "Worst-case ROC %", "field": "roc", "align": "center", "sortable": True},
    {"name": "spread_over_parent", "label": "Spread÷parent", "field": "spread_over_parent", "align": "center", "sortable": True},
    {"name": "spread_over_child", "label": "Spread÷child", "field": "spread_over_child", "align": "center", "sortable": True},
    {"name": "parent_outright", "label": "Parent outright ¢", "field": "parent_outright", "align": "center", "sortable": True},
    {"name": "child_outright", "label": "Child outright ¢", "field": "child_outright", "align": "center", "sortable": True},
    {"name": "display_spread", "label": "Display spread ¢", "field": "display_spread", "align": "center", "sortable": True},
    {"name": "caveat", "label": "Caveat", "field": "caveat", "align": "left"},
]
# Outright/display-spread context starts hidden (spread÷parent/child stay visible per owner).
_RISK_HIDDEN = ("parent_outright", "child_outright", "display_spread")
# Overpriced Books (near-miss) table — cost, overpay (= the flat guaranteed loss), and the watchlist note.
_NEARMISS_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Match", "field": "name", "align": "left", "sortable": True},
    {"name": "detail", "label": "Direction", "field": "detail", "align": "left"},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "align": "center", "sortable": True},
    {"name": "overpay", "label": "Overpay ¢", "field": "overpay", "align": "center", "sortable": True},
    {"name": "note", "label": "Note", "field": "note", "align": "left"},
]
_BACKLOG_COLUMNS = [
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "align": "left", "sortable": True},
    {"name": "became", "label": "Became actionable", "field": "became", "align": "center"},
    {"name": "left", "label": "Left", "field": "left", "align": "center"},
    {"name": "mins", "label": "Lasted (min)", "field": "mins", "align": "center", "sortable": True},
    {"name": "reason", "label": "Why it left", "field": "reason", "align": "left"},
    {"name": "last_edge", "label": "Last edge ¢", "field": "last_edge", "align": "center"},
    {"name": "caveat", "label": "Settlement caveat", "field": "caveat", "align": "left"},
    {"name": "current", "label": "Now", "field": "current", "align": "center"},
]
# Durable 7-day interval backlog (v4) — one row per opportunity lifecycle in a tracked category. Distinct
# from the live "recently actionable" table above (which is bounded by the 30h snapshot store).
_BACKLOG_EVENTS_COLUMNS = [
    {"name": "category", "label": "Category", "field": "category", "align": "center", "sortable": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "align": "left", "sortable": True},
    {"name": "first_seen", "label": "First seen", "field": "first_seen", "align": "center"},
    {"name": "left", "label": "Left", "field": "left", "align": "center"},
    {"name": "mins", "label": "Lasted (min)", "field": "mins", "align": "center", "sortable": True},
    {"name": "peak_roi", "label": "Peak ROI %", "field": "peak_roi", "align": "center", "sortable": True},
    {"name": "last_status", "label": "Last status", "field": "last_status", "align": "left"},
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
# Structured per-leg evidence (PR 3) — shown in the explanation dialog. status / quote come from the stored
# contracts via contract_lookup; blank cells mean "unavailable in snapshot" (never inferred).
_LEG_COLUMNS = [
    {"name": "leg", "label": "Leg", "field": "leg"},
    {"name": "side", "label": "Side", "field": "side"},
    {"name": "market", "label": "Market", "field": "market"},
    {"name": "price", "label": "Price", "field": "price"},
    {"name": "size", "label": "Size", "field": "size"},
    {"name": "status", "label": "Status", "field": "status"},
    {"name": "quote_quality", "label": "Quote", "field": "quote_quality"},
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
                             # PR C: ids already seen in the watchlist buckets, so the toast only fires for
                             # genuinely NEW candidates (seeded on the first snapshot — no toast on load).
                             "seen_watchlist": set(),
                             "first": True, "options": {}, "cov": {}, "backlog": [], "backlog_events": [],
                             "rendered_snapshot_id": "__unseeded__", "selected": None,
                             # change-signal (#3): per-opp up/down/new/returned vs the PREVIOUS snapshot,
                             # recomputed once per new snapshot; `ever_seen` distinguishes new from returned.
                             "changes": {}, "ever_seen": set(),
                             # PR B: ids to flash green ONCE on the snapshot-change rerender; reset to empty
                             # immediately after, so ordinary filter rerenders never replay the animation.
                             "flash_now": set(),
                             "liquidity_panel": None,  # "most liquid now" panel (PR F), recomputed per snapshot
                             "volatility_msg": None,   # "most volatile now" (#12b), recomputed per snapshot
                             # Cascading filters: a re-entrancy guard so the programmatic option/value prune
                             # in _refresh_cascade (which fires the selects' on_value_change) never re-renders
                             # mid-cascade or recurses. Handlers no-op while it's True.
                             "_suppress_cascade": False}

    ui.add_css(_SELECTED_ROW_CSS)        # selected-row highlight (#14) — see module note
    ui.add_css(_A11Y_CSS)                 # accessibility (#10): focus-visible ring + opt-in larger text
    ui.add_css(_FLASH_CSS)                # green flash on new rows (PR B), one-shot per snapshot
    # Dark theme is the default (PR A2). The dark_mode element MUST live at page top-level, not inside the
    # settings dialog: a QDialog mounts its children lazily, so a value=True nested there wouldn't apply
    # until the dialog is first opened. The toggle switch (in the dialog) drives this element by reference.
    _darkmode = ui.dark_mode(value=True)
    ui.label("Kalshi Opportunity Engine — Cross-Sport").classes("text-2xl font-bold")
    ui.label("Opportunities across all sports, ranked best→worst. Core series, gross of fees — "
             "NOT all of Kalshi.").classes("text-sm text-gray-500")

    # --- primary controls (ALWAYS on the page) — the decision-critical filters + refresh + a gear that opens
    # everything else. Safety/freshness (below) and these primary filters never hide behind settings (PR 5).
    with ui.row().classes("items-end gap-4 flex-wrap"):
        sport_sel = ui.select({}, multiple=True, label="Sport").classes("min-w-[8rem]").props("dense")
        tour_sel = ui.select([], multiple=True, label="Tournament").classes("min-w-[10rem]").props("dense")
        # Searchable, key-based multi-select (PR6 / #13): two same-named players never merge, and picking
        # several players/teams ORs them. Options ({key: label}) are filled from the snapshot in _seed/reload.
        participant_sel = ui.select({}, multiple=True, with_input=True, label="Players / matches"
                                    ).classes("min-w-[14rem]").props("dense use-chips")
        min_size_in = ui.number("Min size", min=0, format="%.0f").classes("w-28")
        scan_btn = ui.button("Refresh snapshot")
        clear_btn = ui.button("Clear filters", on_click=lambda: _clear_filters())
        settings_btn = ui.button(icon="settings").props("flat round").tooltip(
            "Settings — display, sections, thresholds, time & refresh")

    # --- settings panel (gear) — SECONDARY/preference controls only (PR 5). A modal dialog (not a permanent
    # drawer) so it never pushes the opportunity rows down. EVERY control below is the SAME object referenced
    # elsewhere (handlers/bindings/_seed/aria unchanged) — only its parent container moved into the dialog.
    # State persists across rerender/poll (in-memory); browser-reload persistence is intentionally NOT added.
    settings_dialog = ui.dialog()
    with settings_dialog, ui.card().classes("w-[36rem]"):
        ui.label("Settings").classes("text-lg font-bold")
        ui.label("Display").classes("text-sm font-bold mt-2")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            # `_darkmode` is created at page top-level (above) so dark applies on load; this switch toggles it.
            dark_sw = ui.switch("Dark mode", value=True,
                                on_change=lambda e: _darkmode.enable() if e.value else _darkmode.disable()
                                ).tooltip("Toggle a dark theme.")
            larger_sw = ui.switch("Larger text").tooltip(
                "Increase text size across the dashboard for readability.")
            larger_sw.on_value_change(
                lambda e: ui.query("body").classes(add="a11y-large") if e.value
                else ui.query("body").classes(remove="a11y-large"))
            show_ids = ui.switch("Show IDs & codes", value=False)
            rules_sw = ui.switch("Resolution criteria", value=False).tooltip(
                "Show each contract's settlement rules in the click panel and auto-open them in the detail view.")
            # Position framing (display only) — re-word the buy plan as Long YES / Short YES instead of the
            # canonical Buy YES / Buy NO (buying NO is economically a short on YES). Default OFF keeps the
            # buy-only wording; never changes detection, pricing, ranking, or the stored fields.
            pos_framing_sw = ui.switch("Long / short wording", value=False).tooltip(
                "Show the plan as Long YES / Short YES instead of Buy YES / Buy NO (buying NO is economically "
                "short YES). Display only — never changes detection, pricing, or ranking.")
            # Net-of-fees ESTIMATE (PR E) — reveal the default-hidden net columns on the opp tables. Wired
            # below (after the column choosers exist). Display only; an estimate; never affects ranking.
            show_net_sw = ui.switch("Show net of fees", value=False).tooltip(
                "Reveal estimated net-of-fees columns (general taker-fee estimate). Display only — does not "
                "affect ranking, bucketing, or actionability.")
        ui.label("Sections").classes("text-sm font-bold mt-2")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            show_review_sw = ui.switch("Review", value=True).tooltip(
                "Show the Review-signal section — settlement-caveated, never auto-tradable.")
            show_blocked_sw = ui.switch("Blocked", value=False).tooltip(   # hidden by default (PR S5)
                "Show the Blocked section — opportunities that exist but aren't currently tradable.")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            rb_switch = ui.switch("Speculative bounded-loss structures", value=True)  # PR A2: on (collapsed in PR C)
            rb_max_loss = ui.number("Max loss ¢", value=config.RISK_BUDGET_DEFAULT_MAX_LOSS_C,
                                    min=1, max=config.RISK_BUDGET_MAX_LOSS_C, format="%.0f").classes("w-28")
            rb_min_ratio = ui.number("Min upside:risk", value=0, min=0, max=20, step=0.5,
                                     format="%.1f").classes("w-32")
            # Probability-context filters (display outright, not executable). Min child outright removes
            # longshots; max spread÷outright caps relative risk. Both 0 = off.
            rb_min_outright = ui.number("Min child outright ¢",
                                        value=config.RISK_BUDGET_DEFAULT_MIN_OUTRIGHT_C, min=0, max=100,
                                        step=1, format="%.0f").classes("w-36").tooltip(
                "Hide speculative rows whose deeper (child) display outright is below this ¢. 0 = off. "
                "Removes near-impossible longshots.")
            rb_max_ratio = ui.number("Max spread÷outright",
                                     value=config.RISK_BUDGET_DEFAULT_MAX_SPREAD_RATIO_HUNDREDTHS / 100,
                                     min=0, max=10, step=0.05, format="%.2f").classes("w-36").tooltip(
                "Hide speculative rows whose deeper display spread÷outright exceeds this. 0 = off. "
                "Caps relative risk (scale-invariant — does not remove longshots on its own).")
            nm_switch = ui.switch("Near-miss books", value=True)  # PR A2: on (collapsed in PR C)
            nm_max_over = ui.number("Max overpay ¢", value=config.NEAR_MISS_DEFAULT_OVER_C,
                                    min=1, max=config.NEAR_MISS_MAX_OVER_C, format="%.0f").classes("w-28")
        ui.label("Filters & thresholds").classes("text-sm font-bold mt-2")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            active_sw = ui.switch("Active only").tooltip("Hide non-active (finalized/settled) markets.")
            rank_sel = ui.select(vm.RANK_MODES, value=vm.RANK_MODE_DEFAULT, label="Rank by").tooltip(
                "Within each section: Per-unit edge ¢, Spread upside (speculative bounded-loss geometry: "
                "upside:risk, then spread, then lower max loss), Outright + spread (speculative: highest deeper "
                "display outright first, then lowest display spread÷outright), or Blended (edge + ROI % + "
                "geometry). Gross — not a probability model.")
            window_select = ui.select(list(config.BACKLOG_WINDOWS), value=config.BACKLOG_DEFAULT,
                                       label="Backlog window").props("stack-label").classes("min-w-[11rem]")
        ui.label("Time & refresh").classes("text-sm font-bold mt-2")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            tz_select = ui.select(config.TIMEZONE_OPTIONS, value=config.TIMEZONE_DEFAULT, label="Time zone")
            persist_select = ui.select(list(config.ALERT_PERSISTENCE_OPTIONS), label="New-actionable banner",
                                       value=next(iter(config.ALERT_PERSISTENCE_OPTIONS))
                                       ).props("stack-label").classes("min-w-[13rem]")
            # Auto-refresh: drive the in-process scan scheduler (NON-force, TTL/budget-guarded). SERVER-WIDE
            # shared state — one scheduler loop per process — so a change affects every viewer.
            auto_sw = ui.switch("Auto-refresh", value=scan_scheduler.scheduler.enabled).tooltip(
                "Periodically re-scan in the background (server-wide). Off = manual 'Refresh snapshot' only.")
            interval_sel = ui.select(config.AUTO_SCAN_INTERVAL_OPTIONS,
                                      value=scan_scheduler.scheduler.interval_s, label="Every (s)"
                                      ).props("stack-label").classes("min-w-[8rem]").tooltip(
                "How often the background auto-scan runs.")
            auto_sw.on_value_change(lambda e: scan_scheduler.scheduler.set_enabled(bool(e.value)))
            interval_sel.on_value_change(lambda e: scan_scheduler.scheduler.set_interval(int(e.value)))
        # Column show/hide now lives on a per-table "Columns" button next to each table (see below) — clearer
        # and more discoverable than a buried multi-select, so no "Columns" group in this dialog.
        with ui.row().classes("gap-2 mt-2"):
            export_btn = ui.button("Export (ZIP)")
            ui.button("Close", on_click=settings_dialog.close)
    settings_btn.on_click(settings_dialog.open)
    chips = ui.row().classes("gap-2 flex-wrap")

    # `tabular-nums` keeps the live age digits a constant width so the per-second tick doesn't reflow (PR 4).
    freshness = ui.label().classes("text-sm").style("font-variant-numeric: tabular-nums")
    # Per-bucket counts status line (PR 4): shown vs in-scope per bucket, hidden-by-toggle made explicit.
    counts_line = ui.label().classes("text-sm text-gray-600").style("font-variant-numeric: tabular-nums")
    banner = ui.label().classes("text-sm font-medium")
    # The "most liquid now" panel (PR F, visible) and the `volatility` telemetry label (collapsed) are
    # created LOWER, both clearly labelled "not an opportunity signal" so they sit out of the opportunity flow.

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

    def _contract_lookup_for(opp: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Build a ticker -> stored-contract map for an opportunity's legs (no fetch), so leg_rows can
        enrich per-leg status / quote quality. Unresolved tickers are simply absent (leg_rows blanks them)."""
        sport = opp.get("sport") or None
        lk: dict[str, dict[str, Any]] = {}
        for leg in (opp.get("legs") or []):
            tkr = leg.get("ticker") or ""
            if tkr and tkr not in lk:
                row = engine.contract_by_ticker(tkr, sport=sport)
                if row:
                    lk[tkr] = row
        return lk

    def open_panel(opp: dict[str, Any]) -> None:
        dialog.clear()
        lines = vm.explanation_lines(opp, show_ids=show_ids.value, long_short=pos_framing_sw.value)
        with dialog, ui.card().classes("w-[36rem]"):
            ui.label(lines[0]).classes("text-lg font-bold")
            ui.label(lines[1]).classes("text-sm text-gray-500")
            # Row-specific severity badges (PR 2b) — colour + text + the full caveat as accessible body text
            # (not a tooltip), highest severity first. Universal limits live in the page-level strip.
            badges = vm.severity_badges(opp)
            if badges:
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    for b in badges:
                        _color = {"blocker": "negative", "review_required": "warning"}.get(
                            b["severity"], "grey-7")
                        ui.badge(b["label"]).props(f"color={_color}")
                for b in badges:
                    ui.label(f"{b['label']}: {b['tooltip']}").classes("text-xs text-gray-600")
            ui.separator()
            for line in lines[2:]:
                ui.label(line)
            # Structured buy plan (PR 3): the exact legs with per-leg status / quote from the stored
            # contracts (blank = unavailable in snapshot, never inferred).
            legrows = vm.leg_rows(opp, _contract_lookup_for(opp), long_short=pos_framing_sw.value)
            if legrows:
                ui.label("Buy plan (legs)").classes("text-sm font-bold mt-2")
                ui.table(columns=_LEG_COLUMNS, rows=legrows, row_key="leg").classes("w-full")
            if rules_sw.value:        # global "Resolution criteria" toggle — per-leg settlement rules
                ui.separator()
                ui.label("Resolution criteria").classes("text-sm font-bold")
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
            for line in vm.explanation_lines(opp, show_ids=show_ids.value, long_short=pos_framing_sw.value)[2:]:
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
                rules_exp = ui.expansion("Resolution criteria (settlement rules)").classes("w-full mt-2")
                with rules_exp:
                    for contract, text in rules:
                        ui.label(contract).classes("text-sm font-medium")
                        ui.label(text).classes("text-sm text-gray-600 mb-2")
                if rules_sw.value:        # global toggle on → surface the rules without an extra click
                    rules_exp.open()
            # Raw fields / link audit / duplicate sources — debug detail, only when "Show IDs & codes" is on.
            if show_ids.value and prows:
                with ui.expansion("Raw fields · link audit · duplicates").classes("w-full mt-2"):
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

    def _section_header(title: str, subtitle: str | None = None) -> Any:
        """A section title row (the per-table 'Columns' button is added into it after the table exists) plus
        an optional one-line plain-English description so a trader instantly understands the section."""
        hdr = ui.row().classes("items-center gap-2 mt-2")
        with hdr:
            ui.label(title).classes("text-lg font-bold")
        if subtitle:
            ui.label(subtitle).classes("text-xs text-gray-500")
        return hdr

    # `dense` tables + `overflow-x-auto` so many rows fit and wide tables scroll instead of overflowing.
    act_hdr = _section_header("Actionable — executable gross edges",
                              "Firm, sized, currently-tradable gross pricing discrepancies. Gross of fees.")
    actionable = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                          pagination=15).props("dense").classes("w-full overflow-x-auto opp-sel")
    actionable.on_select(_on_select(actionable))

    review_hdr = _section_header(
        "Review Required — settlement-dependent",
        "Real, executable-looking edges whose legs may not settle together (e.g. an exact-score bundle vs the "
        "match winner) — verify the settlement rules first; never auto-tradable.")
    review = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                      pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    review.on_select(_on_select(review))

    blocked_hdr = _section_header("Blocked — not currently executable",
                                  "Discrepancies that exist but aren't tradable now (no firm size / an inactive leg).")
    blocked = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                       pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    blocked.on_select(_on_select(blocked))

    # TWO distinct, collapsed watchlist sections — opposite shapes, kept separate. Each uses a custom header
    # slot so the "Columns" button sits beside the title (added after the table exists); the title label is
    # kept in a ref so rerender can update its live count. A bet with capped loss vs a flat guaranteed loss.
    def _expansion_header(title: str) -> tuple[Any, Any, Any]:
        exp = ui.expansion(value=False).classes("w-full mt-2")
        with exp.add_slot("header"), ui.row().classes("items-center w-full gap-2"):
            ui.icon("unfold_more").classes("text-grey")
            title_label = ui.label(title).classes("text-lg font-bold")
            ui.space()
            cols_holder = ui.row().classes("items-center")     # Columns button dropped in here later
        return exp, title_label, cols_holder

    rb_expansion, rb_title, rb_cols_row = _expansion_header("Bounded-Loss Bets — capped downside, convex upside")
    with rb_expansion:
        ui.label("Buy the broader YES + the deeper NO for just over 100¢: your loss is capped at the small "
                 "overpay, with convex upside (the broader-but-not-deeper outcome pays about +$1). A bet, NOT "
                 "an edge — gross of fees.").classes("text-xs text-gray-500")
        rb_table = ui.table(columns=_RISK_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                            pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    rb_table.on_select(_on_select(rb_table))

    nm_expansion, nm_title, nm_cols_row = _expansion_header("Overpriced Books — flat guaranteed loss (watch-only)")
    with nm_expansion:
        ui.label("A complete (MECE) book priced just OVER its payout floor: it pays the floor in every "
                 "outcome, so buying the whole bundle is a flat, guaranteed gross loss. Watch-only, in case a "
                 "leg gets mispriced.").classes("text-xs text-gray-500")
        nm_table = ui.table(columns=_NEARMISS_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                            pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    nm_table.on_select(_on_select(nm_table))

    _sel_tables.extend([actionable, review, blocked, rb_table, nm_table])
    for _t in _sel_tables:                 # the change-signal / NEW-badge indicator column on every table
        _t.add_slot("body-cell-new", _CHANGE_CELL_SLOT)
    for _t in (actionable, review, blocked):
        _t.add_slot("body-cell-edge", _EDGE_CELL_SLOT)      # colour the edge value on change
        _t.add_slot("body-cell-action", _ACTION_CELL_SLOT)  # left-aligned legs
        _t.add_slot("body-cell-caveat", _CAVEAT_CELL_SLOT)  # compact severity chip
    rb_table.add_slot("body-cell-caveat", _CAVEAT_CELL_SLOT)
    nm_table.add_slot("body-cell-note", _NOTE_CELL_SLOT)    # readable wrapping note
    # Thousands-separated numeric cells (display only; numeric sort preserved). 'edge' is handled above.
    for _t in (actionable, review, blocked):
        for _f in ("roi", "units", "profit", "net_edge", "net_profit", "fees"):
            _t.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _f in ("cost", "max_loss", "max_profit", "ratio", "roc", "spread_over_parent",
               "spread_over_child", "parent_outright", "child_outright", "display_spread"):
        rb_table.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _f in ("cost", "overpay"):
        nm_table.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    # Compact empty states: a shown-but-empty section renders a small message row, not a bare grid.
    for _t, _msg in ((actionable, "No actionable opportunities in the current filters."),
                     (review, "No review-required opportunities in the current filters."),
                     (blocked, "No blocked opportunities in the current filters."),
                     (rb_table, "No bounded-loss bets in the current filters."),
                     (nm_table, "No overpriced books in the current filters.")):
        _t.props(f'no-data-label="{_msg}"')

    # Per-table column menus (redesigned) — a "Columns" button by each table opening labeled checkboxes.
    # Opp tables hide the net-of-fees columns by default; Bounded-Loss hides the outright/display-spread
    # context (spread÷parent/child stay visible). Buttons are placed into each section's header / row.
    opp_menus = []
    for _hdr, _tbl in ((act_hdr, actionable), (review_hdr, review), (blocked_hdr, blocked)):
        with _hdr:
            opp_menus.append(build_column_menu(_tbl, _OPP_COLUMNS, default_hidden=_NET_COLUMNS))
    with rb_cols_row:
        build_column_menu(rb_table, _RISK_COLUMNS, default_hidden=_RISK_HIDDEN)
    with nm_cols_row:
        build_column_menu(nm_table, _NEARMISS_COLUMNS)

    # "Show net of fees" — reveal/hide the net columns across the opp tables at once (drives their menus).
    def _toggle_net(show: bool) -> None:
        for m in opp_menus:
            for n in _NET_COLUMNS:
                m["set"](n, show)
    show_net_sw.on_value_change(lambda e: _toggle_net(bool(e.value)))

    with ui.expansion("Recently Actionable — recently left the set").classes("w-full"):
        backlog = ui.table(columns=_BACKLOG_COLUMNS, rows=[], row_key="name",
                           pagination=10).props("dense").classes("w-full overflow-x-auto")
    for _f in ("mins", "last_edge"):
        backlog.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))

    # Durable 7-day backlog (v4): survives restarts, independent of the 30h snapshot store. Category filter
    # is Actionable / Bounded-loss only — statistical arbitrage is reserved (no detector yet), so no tab.
    with ui.expansion("Durable backlog (last 7 days) — survives restarts").classes("w-full"):
        with ui.row().classes("items-center gap-3"):
            backlog_events_cat = ui.select(
                {"": "All categories", "actionable": "Actionable", "bounded_loss": "Bounded-loss"},
                value="", label="Category").props("dense outlined").classes("min-w-[160px]")
        backlog_events_table = ui.table(columns=_BACKLOG_EVENTS_COLUMNS, rows=[], row_key="name",
                                        pagination=10).props("dense").classes("w-full overflow-x-auto")
    for _f in ("mins", "peak_roi"):
        backlog_events_table.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))

    # Market telemetry — snapshot CONTEXT (depth, tightness, activity, volatility), NOT opportunity signals.
    # Collapsed, neutral grey; liquidity lives here now. Populated in rerender (snapshot-scoped).
    with ui.expansion("Market Telemetry — Liquidity & Volatility (context, not signals)").classes("w-full"):
        ui.label("Snapshot context — depth, tightness, activity. NOT opportunity signals.").classes(
            "text-xs text-gray-500")
        with ui.row().classes("gap-12 flex-wrap mt-1"):
            with ui.column().classes("gap-0"):
                ui.label("Most liquid — top sports (depth)").classes("text-xs text-weight-bold")
                liq_sports = ui.column().classes("gap-0")
            with ui.column().classes("gap-0"):
                ui.label("Most liquid — top contracts (depth · spread)").classes("text-xs text-weight-bold")
                liq_contracts = ui.column().classes("gap-0")
            with ui.column().classes("gap-0"):
                ui.label("Tightest markets (spread)").classes("text-xs text-weight-bold")
                liq_tightest = ui.column().classes("gap-0")
            with ui.column().classes("gap-0"):
                ui.label("Most traded (volume)").classes("text-xs text-weight-bold")
                liq_traded = ui.column().classes("gap-0")
        volatility = ui.label().classes("text-sm text-gray-600 mt-2")

    # Participant/team detail (PR 24) — populated on opp row-click from the STORED frames (no fetch).
    detail_expansion = ui.expansion("Selected Detail — click a row").classes("w-full")
    with detail_expansion:
        detail_box = ui.column().classes("w-full")

    # Diagnostics & debug (PR 25b) — observability over the STORED snapshot (no fetch); collapsed by default.
    diagnostics_expansion = ui.expansion("Diagnostics & Debug").classes("w-full")
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
        if participant_sel.value:
            s["participant"] = list(participant_sel.value)
        if min_size_in.value:
            s["min_size"] = float(min_size_in.value)
        if active_sw.value:
            s["active_only"] = True
        return s

    def _refresh_cascade() -> None:
        """Cascade the filter option lists: Tournament options narrow to the selected SPORTS; Participant
        options narrow to the selected sports AND tournaments. Any now-invalid selected tournament /
        participant value is pruned. Pure in-memory over the cached snapshot — no store read. Self-guarded
        with `_suppress_cascade` so the programmatic value assignments (which fire on_value_change) don't
        re-render or recurse; callers run their own single rerender() afterward."""
        opps = state.get("opps_list") or []
        sports = list(sport_sel.value or [])
        opts = vm.cascaded_options(opps, sports=sports, tournaments=list(tour_sel.value or []))
        state["_suppress_cascade"] = True
        try:
            tour_sel.options = opts["tournaments"]
            valid_t = set(opts["tournaments"])
            kept_t = [t for t in (tour_sel.value or []) if t in valid_t]
            if kept_t != list(tour_sel.value or []):
                tour_sel.value = kept_t                       # drop tournaments no longer in scope
            # Participants narrowed by sport + the PRUNED tournaments (so a dropped tournament can't keep
            # its players in scope).
            popts = vm.cascaded_options(opps, sports=sports, tournaments=kept_t)["participants"]
            participant_sel.options = {p["value"]: p["label"] for p in popts}
            valid_p = {p["value"] for p in popts}
            kept_p = [k for k in (participant_sel.value or []) if k in valid_p]
            if kept_p != list(participant_sel.value or []):
                participant_sel.value = kept_p
            tour_sel.update()
            participant_sel.update()
        finally:
            state["_suppress_cascade"] = False

    def _clear_filters() -> None:
        state["_suppress_cascade"] = True       # batch the resets; one rerender below (no mid-reset renders)
        try:
            sport_sel.value, tour_sel.value, participant_sel.value = [], [], []
            min_size_in.value, active_sw.value = None, False
        finally:
            state["_suppress_cascade"] = False
        _refresh_cascade()                       # widen the option lists back to the full set
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

            contracts = engine.all_contracts()        # ONE snapshot read; reused by inventory + non-laddered

            cb = engine.category_breakdown()
            ui.label("Category honesty").classes("text-sm font-medium mt-3")
            ui.table(columns=[{"name": "k", "label": "Axis", "field": "k"},
                              {"name": "v", "label": "Count", "field": "v"}],
                     rows=[{"k": k, "v": cb[k]} for k in ("total", "laddered", "non_laddered",
                                                          "low_confidence", "unsupported")]).classes("w-full")
            ui.label("Non-laddered counts are transparency, not failures; low-confidence = name-fallback "
                     "identity; unsupported = no SportConfig owns the series.").classes("text-xs text-gray-500")

            # "Currently considered — snapshot inventory": every tournament / participant / kind of contract
            # the app LOADED this snapshot (the full fetched universe, NOT tradable coverage). Filterable
            # AG-grids over the same stored contracts; one row never silently wins (joined distinct values).
            inv = vm.considered_inventory(contracts)
            ui.label("Currently considered — snapshot inventory").classes("text-sm font-medium mt-3")
            ui.label("Everything LOADED in the latest snapshot — the fetched contracts the app is "
                     "considering. NOT tradable/actionable coverage; many of these never become "
                     "opportunities.").classes("text-xs text-gray-500")
            if contracts:
                ui.table(columns=[{"name": c, "label": lbl, "field": c} for c, lbl in (
                    ("sport", "Sport"), ("tournaments", "Tournaments"), ("participants", "Participants"),
                    ("contracts", "Contracts"), ("kinds", "Kinds"))],
                    rows=inv["sports"]).classes("w-full")
                ui.label(f"Tournaments considered ({len(inv['tournaments'])})").classes(
                    "text-sm font-medium mt-2")
                ui.aggrid(_aggrid_options(inv["tournaments"], [
                    ("sport", "Sport"), ("tournament", "Tournament"), ("sources", "Source(s)"),
                    ("participants", "Participants"), ("contracts", "Contracts"), ("kinds", "Kinds"),
                ])).classes("w-full h-72")
                ui.label(f"Participants considered ({len(inv['participants'])})").classes(
                    "text-sm font-medium mt-2")
                ui.aggrid(_aggrid_options(inv["participants"], [
                    ("sport", "Sport"), ("tournament", "Tournament"), ("participant", "Participant"),
                    ("confidence", "ID confidence"), ("contracts", "Contracts"),
                ])).classes("w-full h-96")
                ui.label(f"Kinds of contracts considered ({len(inv['kinds'])})").classes(
                    "text-sm font-medium mt-2")
                ui.aggrid(_aggrid_options(inv["kinds"], [
                    ("sport", "Sport"), ("kind", "Kind"), ("category", "Category"),
                    ("contracts", "Contracts"), ("laddered", "Ladder-eligible"),
                ])).classes("w-full h-72")
            else:
                ui.label("No contracts loaded in the latest snapshot.").classes("text-sm text-gray-500")

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

            unmapped = vm.non_laddered_rows(contracts)        # reuse the hoisted read (no second all_contracts())
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
    def _read_bundle(persist_s: float | None, win_s: float, events_cat: str) -> dict[str, Any]:
        """All store reads for one render (snapshot + persistence-scoped alerts + windowed backlog +
        durable 7-day interval backlog), gathered off the event loop. Pure reads — NO UI here. (Engine
        reads share the P1 latest-snapshot cache, so concurrent clients deserialize a given snapshot once.)"""
        return {"cov": engine.coverage(), "opps": engine.latest_opportunities(),
                "alerts": engine.alerts(persist_s), "backlog": engine.backlog(win_s),
                "backlog_events": engine.backlog_events(days=7.0, category=events_cat or None),
                "contracts": engine.all_contracts(),     # for the "most liquid now" line (#12a)
                "vol_frames": engine.recent_contract_frames(config.VOLATILITY_WINDOW_SECONDS)}  # #12b

    def _read_args() -> tuple:
        win_s = config.BACKLOG_WINDOWS[window_select.value]
        return (config.ALERT_PERSISTENCE_OPTIONS[persist_select.value],
                win_s if win_s is not None else config.SNAPSHOT_RETENTION_SECONDS,
                backlog_events_cat.value)

    def _apply_bundle(bundle: dict[str, Any]) -> None:
        """Push a freshly-read store bundle into `state` + the snapshot-scoped UI (select options, alert
        banner), then rerender. A snapshot change forces a diagnostics rebuild (per-filter rerenders do
        not — that's the expensive path we keep off the hot loop). Sync, so the first paint (`_seed`) and
        the async `reload_data` share one code path."""
        cov, opps, al = bundle["cov"], bundle["opps"], bundle["alerts"]
        # Change-signal (#3): diff against the PREVIOUS snapshot's opps, captured BEFORE we overwrite them,
        # and ONLY when the snapshot id advanced (a persist/window control reload re-reads the same snapshot
        # -> no phantom deltas). First paint shows none. Computed once here; rerender just re-displays it.
        prev_opps, was_first = state["opps"], state["first"]
        new_id = cov.get("snapshot_id")
        # The snapshot actually ADVANCED (not the first paint, not a same-snapshot poll/control reload). Drives
        # both the change-signal and the PR B flash, so neither fires on a phantom re-read of the same snapshot.
        advanced = not was_first and new_id != state.get("rendered_snapshot_id")
        if not advanced:
            state["changes"] = {}
        else:
            state["changes"] = vm.classify_changes(prev_opps, {o.get("opportunity_id"): o for o in opps},
                                                   state["ever_seen"])
        state["cov"] = cov
        state["opps_list"] = opps
        state["opps"] = {o.get("opportunity_id"): o for o in opps}
        state["ever_seen"].update(state["opps"].keys())     # after classify, so 'returned' detection works
        state["options"] = vm.derive_options(opps)
        state["backlog"] = bundle["backlog"]
        state["backlog_events"] = bundle["backlog_events"]
        state["liquidity_panel"] = vm.liquidity_panel(bundle["contracts"])  # PR F (snapshot-scoped panel)
        state["volatility_msg"] = vm.volatility_leader(bundle["vol_frames"])   # #12b (snapshot-scoped)
        # Sport is the top of the cascade (never narrowed); Tournament/Participant options + any now-stale
        # selections are derived by _refresh_cascade from the current sport/tournament picks. This preserves
        # the viewer's selections across a poll/snapshot change while re-narrowing the downstream lists.
        sport_sel.options = state["options"]["sports"]
        sport_sel.update()
        _refresh_cascade()
        # New-actionable toast + banner + blocked-change label (alerts are snapshot/persistence scoped).
        new_ids = {r.get("opportunity_id") for r in al["new_actionable"]}
        fresh = new_ids - state["seen_new"]
        if fresh and not state["first"]:
            _notify(f"{len(fresh)} newly actionable", type="positive")
        state["seen_new"] = new_ids
        state["new_ids"] = new_ids
        # New-watchlist toast (PR C) — rate-limited: seeded on the first snapshot (no toast for the ~300 rows
        # on load), then one neutral, summarized toast per snapshot for genuinely new bounded-loss/overpriced
        # candidates. Skipped when both watchlist switches are off (don't ping about a hidden section).
        wl_ids = {o.get("opportunity_id") for o in opps if o.get("bucket") in ("risk_budget", "near_miss")}
        fresh_wl = wl_ids - state["seen_watchlist"]
        if fresh_wl and not was_first and (rb_switch.value or nm_switch.value):
            _notify(f"{len(fresh_wl)} new watchlist candidate(s)", type="info")
        state["seen_watchlist"] = wl_ids
        state["first"] = False
        banner.set_text(f"{len(new_ids)} newly actionable" if new_ids else "")
        n_ch = len(al["blocked_changes"])
        changed.set_text(f"{n_ch} changed while blocked" if n_ch else "")
        state["rendered_snapshot_id"] = cov.get("snapshot_id")
        # PR B green flash: highlight rows that are NEW this snapshot (change=='new') or newly-actionable.
        # Only when the snapshot advanced (never first paint or a same-snapshot poll). One-shot: set, render,
        # then clear so subsequent filter rerenders within this snapshot don't replay the animation.
        state["flash_now"] = ({oid for oid, c in state["changes"].items() if c == "new"} | new_ids
                              if advanced else set())
        rerender(force_diagnostics=True)
        state["flash_now"] = set()

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
        chg = state.get("changes") or {}      # per-snapshot change-signal; re-displayed, never re-derived here
        flash = state.get("flash_now") or set()   # PR B: non-empty only on the snapshot-change rerender
        cov = state.get("cov") or {}
        filters = _current_filters()
        view = vm.rank_opps(vm.filter_opps(opps, **filters), rank_sel.value)   # display-time re-sort, no rescan
        # Truthful empty state by scope (PR 26a): no-scan / scanning / scan-failed / no-opportunities /
        # filter-hid-all — or hidden when there's content to show.
        msg = vm.empty_state(cov=cov, total_opps=len(opps), shown_opps=len(view),
                             scan_status=engine.scan_status())
        empty.set_text(msg or "")
        empty.set_visibility(msg is not None)

        ls = pos_framing_sw.value      # Long/Short YES display wording (default off → Buy YES/Buy NO)
        actionable.rows = [vm.opp_row(o, new_ids, chg, flash, long_short=ls) for o in view if o.get("bucket") == "actionable"]
        review.rows = [vm.opp_row(o, new_ids, chg, flash, long_short=ls) for o in view if o.get("bucket") == "review_signal"]
        blocked.rows = [vm.opp_row(o, new_ids, chg, flash, long_short=ls) for o in view if o.get("bucket") == "blocked"]
        for hdr, tbl, sw in ((review_hdr, review, show_review_sw), (blocked_hdr, blocked, show_blocked_sw)):
            hdr.set_visibility(sw.value)
            tbl.set_visibility(sw.value)

        # Two watchlist sections (split): each filtered from the membership/threshold-filtered view by its
        # band controls; no rescan. Each collapsed section shows only when its switch is on; its title carries
        # the live count; its band inputs disable when off.
        include_rb, include_nm = rb_switch.value, nm_switch.value
        rbv = vm.risk_budget_view(
            view, max_loss_c=int(rb_max_loss.value or 0),
            min_ratio_tenths=round(float(rb_min_ratio.value or 0) * 10),
            min_outright_c=int(rb_min_outright.value or 0),
            max_spread_ratio_hundredths=round(float(rb_max_ratio.value or 0) * 100)) if include_rb else []
        nmv = vm.near_miss_view(view, max_over_c=int(nm_max_over.value or 0)) if include_nm else []
        rb_table.rows = [vm.risk_budget_row(o, new_ids, chg, flash) for o in rbv]
        nm_table.rows = [vm.near_miss_row(o, new_ids, chg, flash) for o in nmv]
        rb_title.set_text(f"Bounded-Loss Bets — capped downside, convex upside ({len(rbv):,})")
        nm_title.set_text(f"Overpriced Books — flat guaranteed loss, watch-only ({len(nmv):,})")
        rb_expansion.set_visibility(include_rb)
        nm_expansion.set_visibility(include_nm)
        rb_max_loss.set_enabled(include_rb)
        rb_min_ratio.set_enabled(include_rb)
        rb_min_outright.set_enabled(include_rb)
        rb_max_ratio.set_enabled(include_rb)
        nm_max_over.set_enabled(include_nm)

        backlog.rows = [vm.backlog_row(b, tz) for b in (state.get("backlog") or [])]
        backlog_events_table.rows = [vm.backlog_event_row(b, tz) for b in (state.get("backlog_events") or [])]

        # scope banner (with the PR 21a counters) + per-bucket counts + filter chips + URL state
        freshness.set_text(vm.scope_banner(cov, tz))
        # Per-bucket counts (PR 4): computed from the FULL snapshot + current filters (in-memory; no store
        # read), reusing filter_opps so the numbers match the rendered tables. Toggle state -> "hidden by
        # settings" wording. `opps` is the full snapshot list; `filters` are the membership+threshold values.
        counts_line.set_text(vm.bucket_counts_line(
            vm.bucket_counts(opps, filters),
            {"review_signal": show_review_sw.value, "blocked": show_blocked_sw.value,
             "risk_budget": rb_switch.value, "near_miss": nm_switch.value}))
        # Market telemetry — fill the four liquidity columns (depth / contracts / tightest / most-traded).
        panel = state.get("liquidity_panel") or {}
        for _col in (liq_sports, liq_contracts, liq_tightest, liq_traded):
            _col.clear()
        with liq_sports:
            for _lbl, _depth, _buy, _sell, _dm in panel.get("top_sports", []):
                ui.label(f"{_lbl} — {_depth:,} contracts · buy ${_buy:,} · sell ${_sell:,} · "
                         f"depth×mid ${_dm:,}").classes("text-sm text-gray-600")
        with liq_contracts:
            for _lbl, _size, _spread in panel.get("top_contracts", []):
                ui.label(f"{_lbl} — {_size:,} @ touch · {_spread:,}¢").classes("text-sm text-gray-600")
        with liq_tightest:
            for _lbl, _spread, _depth in panel.get("tightest", []):
                ui.label(f"{_lbl} — {_spread:,}¢ spread · {_depth:,} deep").classes("text-sm text-gray-600")
        with liq_traded:
            for _lbl, _vol in panel.get("most_traded", []):
                ui.label(f"{_lbl} — {_vol:,} vol").classes("text-sm text-gray-600")
        vol = state.get("volatility_msg")         # "most volatile now" (#12b) — snapshot-scoped, display only
        volatility.set_text(vol or "")
        volatility.set_visibility(bool(vol))
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
        participant_sel.options = {p["value"]: p["label"] for p in options["participants"]}
        seeded = vm.state_from_query(query, options=options)
        sport_sel.value = seeded.get("sports", [])
        tour_sel.value = seeded.get("tournaments", [])
        participant_sel.value = seeded.get("participant", [])
        min_size_in.value = seeded.get("min_size")
        active_sw.value = bool(seeded.get("active_only"))
        _apply_bundle(_read_bundle(*_read_args()))   # synchronous first paint (page-build thread)

    async def do_scan() -> None:
        scan_btn.disable()        # stale-while-scanning: only the Scan button is disabled; filters keep working
        n = ui.notification("Scanning (core series)…", spinner=True, timeout=None, position="top-right")
        try:
            # Normally NON-force (respects the TTL/budget-cooldown anti-hammer guards). BUT if the snapshot is
            # already STALE, a non-force click would be skipped during cooldown and leave it stale — so a
            # stale refresh FORCES a fresh fetch (owner-requested; scoped exception to the non-force default).
            force = bool((engine.coverage() or {}).get("stale"))
            st = await run.io_bound(engine.run_scan_now, force=force)   # network I/O off the event loop
            await reload_data()                              # surface the new snapshot immediately for this client
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
            _notify("Nothing to export yet — run a scan first.", type="warning")
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
        _notify(f"Exported snapshot {cov['snapshot_id']} · {len(view)} opportunities", type="positive")

    # Accessibility (#10): an explicit aria-label on every control + each data table + the key expansions,
    # so a screen reader announces a meaningful name (emoji/short labels and the unlabelled tables aren't
    # self-describing). Applied in one pass now that every element exists.
    for _el, _aria in (
        (tz_select, "Time zone"), (persist_select, "New-actionable banner persistence"),
        (window_select, "Backlog window"), (show_ids, "Show IDs and codes"),
        (rules_sw, "Show resolution criteria"), (dark_sw, "Dark mode"), (larger_sw, "Larger text"),
        (pos_framing_sw, "Long / short position wording"),
        (scan_btn, "Refresh snapshot"), (export_btn, "Export snapshot ZIP"),
        (settings_btn, "Open settings"),
        (auto_sw, "Auto-refresh in the background"), (interval_sel, "Auto-scan interval (seconds)"),
        (sport_sel, "Filter by sport"), (tour_sel, "Filter by tournament"),
        (rank_sel, "Rank opportunities by"),
        (participant_sel, "Filter by players or matches"), (min_size_in, "Minimum tradable size"),
        (active_sw, "Active markets only"), (show_review_sw, "Show the Review-signal section"),
        (show_blocked_sw, "Show the Blocked section"), (clear_btn, "Clear all filters"),
        (rb_switch, "Show speculative bounded-loss structures"),
        (rb_max_loss, "Speculative max loss in cents"),
        (rb_min_ratio, "Speculative minimum upside-to-risk ratio"),
        (rb_min_outright, "Speculative minimum child display outright in cents"),
        (rb_max_ratio, "Speculative maximum child display spread-to-outright ratio"),
        (nm_switch, "Show overpriced books (near-miss)"), (nm_max_over, "Near-miss max overpay in cents"),
        (show_net_sw, "Show estimated net-of-fees columns"),
        (actionable, "Actionable opportunities"), (review, "Review-required opportunities"),
        (blocked, "Blocked opportunities"),
        (rb_table, "Bounded-loss bets"), (rb_expansion, "Bounded-loss bets section"),
        (nm_table, "Overpriced books"), (nm_expansion, "Overpriced books section"),
        (backlog, "Recently-actionable backlog"),
        (backlog_events_table, "Durable 7-day backlog"), (backlog_events_cat, "Durable backlog category"),
        (detail_expansion, "Selected detail"), (diagnostics_expansion, "Diagnostics and debug"),
    ):
        _el.props(f'aria-label="{_aria}"')

    scan_btn.on_click(do_scan)
    export_btn.on_click(do_export)
    _seed()        # set control values from the URL BEFORE binding handlers (so seeding fires no render)

    # Filter / display controls re-render PURELY in-memory from the cached snapshot (no store, no fetch).
    # The lambda no-ops while `_suppress_cascade` is set, so the programmatic option/value prune inside
    # _refresh_cascade (which fires participant_sel.on_value_change) never re-renders mid-cascade.
    for ctrl in (tz_select, rank_sel, show_ids, participant_sel, min_size_in, active_sw,
                 show_review_sw, show_blocked_sw, rb_switch, rb_max_loss, rb_min_ratio,
                 rb_min_outright, rb_max_ratio, nm_switch, nm_max_over):
        ctrl.on_value_change(lambda _=None: None if state.get("_suppress_cascade") else rerender())

    # Sport / Tournament are the cascade drivers: changing one re-narrows the downstream option lists
    # (and prunes now-invalid picks) BEFORE a single rerender. participant_sel (the leaf) drives no
    # further cascade, so it stays in the generic loop above.
    def _on_membership_change() -> None:
        if state.get("_suppress_cascade"):
            return
        _refresh_cascade()
        rerender()
    sport_sel.on_value_change(lambda _=None: _on_membership_change())
    tour_sel.on_value_change(lambda _=None: _on_membership_change())
    diagnostics_expansion.on_value_change(lambda _=None: rerender())   # render diagnostics when opened
    # Alert-persistence + backlog-window + durable-backlog category parameterize STORE reads, so they go
    # through reload_data.
    for ctrl in (persist_select, window_select, backlog_events_cat):
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

    def _on_position_framing_toggle() -> None:
        # Single handler (NOT also in the generic rerender loop, which would double-render): re-render the
        # tables AND refresh any open click-panel / detail for the selected opp, so an already-open dialog
        # flips wording without a re-click. Display only — no store read.
        rerender()
        sel = state.get("selected")
        if sel and dialog.value:
            open_panel(sel)
        if sel and detail_expansion.value:
            render_detail(sel)
    pos_framing_sw.on_value_change(lambda _=None: _on_position_framing_toggle())

    def tick_age() -> None:
        # Re-render only the freshness/scope line each second (scope_banner recomputes the age live).
        freshness.set_text(vm.scope_banner(state.get("cov"), tz_select.value))

    ui.timer(config.UI_POLL_SECONDS, poll)        # snapshot-change watcher (cheap; reloads only on a new id)
    ui.timer(1.0, tick_age)
