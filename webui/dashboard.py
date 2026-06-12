"""Opportunity-first cross-sport dashboard (Stage 5) — NiceGUI, mounted on the FastAPI app.

A single `@ui.page('/')` that reads the engine in-process (via `webui.engine`) and renders it through the
pure `webui.viewmodel` builders: a scope/freshness banner, **membership + threshold filters** that narrow
the STORED snapshot (no control ever triggers a fetch), sortable Actionable / Review / Blocked tables, a
recently-actionable backlog, a clickable explanation panel, new-actionable + blocked-change alerts
(polling), filter chips + URL state, and a manual "Scan now" button. Detection + filtering logic live in
the engine / `viewmodel`; this module is the thin NiceGUI shell.
"""
from __future__ import annotations

import time
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

# Qualifier-minus-top-two-cost cell: sign-aware TEXT (cheaper / more expensive) while Quasar still sorts
# on the raw numeric `premium` field. Blank when absent (game-support rows carry no premium).
_PREMIUM_CELL_SLOT = (
    '<q-td :props="props" class="text-center">'
    '<span v-if="props.row.premium_display">{{ props.row.premium_display }}'
    '<q-tooltip>qualifier YES − top-two bundle cost (¢); positive = bundle cheaper</q-tooltip></span>'
    '<span v-else>{{ props.row.premium }}</span></q-td>'
)

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


def _wrap_cell_slot(field: str) -> str:
    """A left-aligned, wrapping free-text cell for an arbitrary row field (e.g. the full caveat prose)."""
    return ('<q-td :props="props" class="text-left" '
            'style="white-space: normal; min-width: 18rem; max-width: 32rem;">'
            "{{ props.row.%s }}</q-td>") % field


def _label_cell_slot(label_field: str) -> str:
    """Display the `*_label` string for a quote-quality column whose `field` is the numeric `*_rank` (so
    the column SORTS by rank Tight→Crossed→Unknown but SHOWS the human label)."""
    return '<q-td :props="props" class="text-center">{{ props.row.%s }}</q-td>' % label_field


# Qualifier caveat cell (PR — top-two parity): compact structural / settlement chips (each with a tooltip)
# replacing the old long prose Note. The full prose lives in the hidden "Full caveat" column + the detail
# panel. Neutral grey — these are advisory/structural, not blockers.
_QS_CAVEAT_CELL_SLOT = (
    '<q-td :props="props" class="text-left" style="white-space: normal; max-width: 22rem;">'
    '<q-badge v-for="b in props.row.caveat_badges" :key="b.label" color="grey-7" '
    'class="q-mr-xs q-mb-xs">{{ b.label }}'
    '<q-tooltip max-width="22rem">{{ b.tooltip }}</q-tooltip></q-badge></q-td>'
)


# Bounded-Loss honesty badges (Phase 1, display-only): "Midpoint-only" (amber — display positive but the
# firm bid/ask basis doesn't confirm) / "Wide basis" (grey — a leg quote is Wide/Very-wide). Each with a
# tooltip. Pure trader-caution chips; drive nothing executable. Mirrors the qualifier caveat-badge pattern.
_RB_FLAGS_CELL_SLOT = (
    '<q-td :props="props" class="text-left" style="white-space: normal; max-width: 16rem;">'
    '<q-badge v-for="b in props.row.flags" :key="b.label" :color="b.color" '
    'class="q-mr-xs q-mb-xs">{{ b.label }}'
    '<q-tooltip max-width="22rem">{{ b.tooltip }}</q-tooltip></q-badge></q-td>'
)


def _num_tip_cell_slot(field: str, tip: str, suffix: str = "") -> str:
    """Numeric cell (Quasar still SORTS on the raw numeric `field`) with a fixed basis tooltip + an optional
    unit suffix; renders "—" for a null/non-finite value (distinct from a real 0). Display-only."""
    return ('<q-td :props="props" class="text-center">'
            '<span v-if="props.row.%s != null && isFinite(props.row.%s)">'
            "{{ Number(props.row.%s).toLocaleString('en-US', {maximumFractionDigits: 2}) }}%s"
            '<q-tooltip max-width="22rem">%s</q-tooltip></span>'
            '<span v-else>—</span></q-td>') % (field, field, field, suffix, tip)


# Firm success gap (¢): the conservative tradable-side gap, with the firm conditional % surfaced in the
# tooltip ONLY when positive (a firm gap can be ≤0; a negative "chance" is never shown as a number).
_RB_FIRM_GAP_CELL_SLOT = (
    '<q-td :props="props" class="text-center">'
    '<span v-if="props.row.firm_gap != null && isFinite(props.row.firm_gap)">'
    "{{ Number(props.row.firm_gap).toLocaleString('en-US', {maximumFractionDigits: 2}) }}¢"
    '<q-tooltip max-width="22rem">Conservative firm-side gap: parent YES bid − child YES ask. '
    '<span v-if="props.row.firm_pct != null">Firm chance if reached ≈ {{ props.row.firm_pct }}%. </span>'
    '≤ 0 ⇒ the display (midpoint) positive is not confirmed by firm quotes.</q-tooltip></span>'
    '<span v-else>—</span></q-td>'
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
# Bounded-Loss Bets table (split from the old merged watchlist): convex economics up front. The implied
# payoff CHANCE (parent−child display gap) and IMPLIED EV (chance − overpay) lead the cross-sport
# comparison; spread÷parent/child stay visible; the raw outright context starts hidden.
_RISK_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},
    # Descriptive class (PR M): Candidate / Breakeven / Negative proxy / Inverted / Data quality — near the
    # left so junk rows are obvious at a glance.
    {"name": "signal", "label": "Signal", "field": "signal", "align": "left", "sortable": True},
    # Phase 1 honesty badges (display-only): Midpoint-only / Wide basis. Near the left so a row whose
    # display positive isn't confirmed by firm quotes is obvious at a glance.
    {"name": "flags", "label": "Flags", "field": "flags", "align": "left"},
    # PR E — Kind (Vertical/Calendar) shown in the combined "All" table; redundant (constant) in the splits.
    {"name": "kind", "label": "Kind", "field": "resolution", "align": "center", "sortable": True},
    # PR F — cheap vs same-sport peers at a similar implied chance ("cost" / "ratio" / both); blank otherwise.
    {"name": "cheap", "label": "Cheap vs peers", "field": "cheap", "align": "center", "sortable": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / chain", "field": "name", "align": "left", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
    # PR E — trader columns: the payoff zone in words, then top-of-book size + a $100 gross-allocation sizing.
    {"name": "wins_if", "label": "Wins if…", "field": "wins_if", "align": "left", "sortable": True},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "align": "center", "sortable": True},
    {"name": "max_loss", "label": "Max loss ¢", "field": "max_loss", "align": "center", "sortable": True},
    {"name": "max_profit", "label": "Max profit ¢", "field": "max_profit", "align": "center", "sortable": True},
    {"name": "max_units", "label": "Max units", "field": "max_units", "align": "center", "sortable": True},
    {"name": "loss_100", "label": "Max loss @ $100 ($)", "field": "loss_100", "align": "center", "sortable": True},
    {"name": "upside_100", "label": "Best upside @ $100 ($)", "field": "upside_100", "align": "center", "sortable": True},
    {"name": "quote_health", "label": "Quote health", "field": "quote_health", "align": "center", "sortable": True},
    {"name": "ratio", "label": "Upside:risk", "field": "ratio", "align": "center", "sortable": True},
    # Likelihood block (gross, top-of-book display aids; never an edge). Market gap (pp) = the UNCONDITIONAL
    # parent−child display gap. (Breakeven % and Implied EV ¢ were removed — redundant with Max loss / Gap
    # vs breakeven.)
    {"name": "display_spread", "label": "Market gap (pp)", "field": "display_spread", "align": "center", "sortable": True},
    # Phase 1 likelihood (display-only): a COMPLEMENTARY conditional pair, given the broader outcome is
    # reached — Success given reached % = 1 − child/parent, Deeper given reached % = child/parent (they sum
    # to 100). Market-implied / uncalibrated, less sensitive to a common overround but NOT de-vigged and NOT
    # fair value. Plus the conservative FIRM-side gap in ¢ (a sanity check, never a tradable %; firm % is
    # tooltip-only).
    {"name": "cond_success", "label": "Success given reached %", "field": "cond_success", "align": "center", "sortable": True},
    {"name": "cond_child", "label": "Deeper given reached %", "field": "cond_child", "align": "center", "sortable": True},
    {"name": "firm_gap", "label": "Firm success gap ¢", "field": "firm_gap", "align": "center", "sortable": True},
    {"name": "gap_vs_be", "label": "Gap vs breakeven (pp)", "field": "gap_vs_be", "align": "center", "sortable": True},
    # Phase 1 comparability (display-only): the parent's in-the-money probability per cent of MAX LOSS
    # (parent_display_c / (cost_c − 100), the at-risk overpay). HIGHER = better (more likely-to-reach per
    # cent at risk); deep-longshot parents sink. (Breakeven % ≈ Max loss and Implied EV ¢ ≡ Gap vs breakeven
    # were removed as redundant; the earlier "Cost per implied pp" was degenerate.)
    {"name": "parent_over_maxloss", "label": "Parent ÷ max loss", "field": "parent_over_maxloss", "align": "center", "sortable": True},
    {"name": "roc", "label": "Worst-case ROC %", "field": "roc", "align": "center", "sortable": True},
    {"name": "spread_over_parent", "label": "Spread÷parent", "field": "spread_over_parent", "align": "center", "sortable": True},
    {"name": "spread_over_child", "label": "Spread÷child", "field": "spread_over_child", "align": "center", "sortable": True},
    {"name": "parent_outright", "label": "Parent outright ¢", "field": "parent_outright", "align": "center", "sortable": True},
    {"name": "child_outright", "label": "Child outright ¢", "field": "child_outright", "align": "center", "sortable": True},
    {"name": "caveat", "label": "Caveat", "field": "caveat", "align": "left"},
]
# Default-hidden advanced context: diagnostic ratios + worst-case ROC + raw outrights + gross entry cost
# (secondary to max loss). The decision columns — signal / kind / wins-if / max loss / $100 sizing / max
# units / quote health / market gap / implied EV — lead.
_RISK_HIDDEN = ("cost", "roc", "spread_over_parent", "spread_over_child", "parent_outright", "child_outright")
# In the Vertical/Calendar split tables the Kind column is constant → hide it there (shown only in "All").
_RISK_HIDDEN_SPLIT = _RISK_HIDDEN + ("kind",)
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

# Cheap NO fades (NO-anchored structures) table — leads with the Buy-NO anchor cost + bounded max-loss +
# breakeven chance; convexity is a visible-but-secondary column (it overranks tiny longshots if it leads).
# A speculative, opt-in, never-actionable fade — NOT an edge.
_NO_STRUCTURE_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},
    {"name": "kind", "label": "Kind", "field": "kind", "align": "center", "sortable": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant", "field": "name", "align": "left", "sortable": True},
    {"name": "wins_if", "label": "Wins if…", "field": "wins_if", "align": "left", "sortable": True},
    {"name": "buy_no", "label": "Buy NO ¢", "field": "buy_no", "align": "center", "sortable": True},
    {"name": "cost", "label": "Cost ¢", "field": "cost", "align": "center", "sortable": True},
    {"name": "max_loss", "label": "Max loss ¢", "field": "max_loss", "align": "center", "sortable": True},
    {"name": "breakeven", "label": "Breakeven %", "field": "breakeven", "align": "center", "sortable": True},
    {"name": "bonus_profit", "label": "Win profit ¢", "field": "bonus_profit", "align": "center", "sortable": True},
    {"name": "convexity", "label": "Payout÷cost", "field": "convexity", "align": "center", "sortable": True},
    {"name": "quote_health", "label": "Quote health", "field": "quote_health", "align": "center", "sortable": True},
    {"name": "caveat", "label": "Caveat", "field": "caveat", "align": "left"},
    # --- default-hidden context ---
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
    {"name": "parent_yes", "label": "Buy YES (bound) ¢", "field": "parent_yes", "align": "center", "sortable": True},
    {"name": "max_units", "label": "Max units", "field": "max_units", "align": "center", "sortable": True},
    {"name": "loss_100", "label": "Max loss @ $100 ($)", "field": "loss_100", "align": "center", "sortable": True},
    {"name": "upside_100", "label": "Best upside @ $100 ($)", "field": "upside_100", "align": "center", "sortable": True},
]
_NO_STRUCTURE_HIDDEN = ("detail", "parent_yes", "max_units", "loss_100", "upside_100")
_NO_STRUCTURE_NUMS = ("buy_no", "parent_yes", "cost", "max_loss", "breakeven", "bonus_profit",
                      "convexity", "max_units", "loss_100", "upside_100")
# Kind filter options for the Cheap-NO-fades section.
_NO_STRUCTURE_KINDS = {"all": "All", "band": "Bounded bands", "outright": "Single NO"}
# Per-participant NO-fade LADDER (grouped view): one row per rung, broad→deep. "Cascade score" is an
# ORDINAL longshot-upside score (max-win÷cost × deeper rungs dominated) — never EV/probability/fair value.
_NO_FADE_LADDER_COLUMNS = [
    {"name": "rung", "label": "Rung (broad → deep)", "field": "rung", "align": "left"},
    {"name": "reach_pct", "label": "Reach %", "field": "reach_pct", "align": "right"},
    {"name": "buy_no", "label": "Buy NO ¢", "field": "buy_no", "align": "right"},
    {"name": "max_win", "label": "Max win ¢", "field": "max_win", "align": "right"},
    {"name": "leverage", "label": "Leverage ×", "field": "leverage", "align": "right"},
    {"name": "dominated", "label": "Dominates (deeper)", "field": "dominated", "align": "right"},
    {"name": "cascade", "label": "Cascade score", "field": "cascade", "align": "right", "sortable": True},
    {"name": "quote", "label": "Quote", "field": "quote", "align": "center"},
    {"name": "size", "label": "Size", "field": "size", "align": "right"},
    {"name": "tag", "label": "", "field": "tag", "align": "left"},
]
_NO_FADE_SORTS = {"safe": "Safest first", "cascade": "Cascade upside (longshot)"}
_NO_FADE_LADDER_MAX_CARDS = 50          # cap rebuilt expansion cards per refresh (no silent truncation)

# Series + Match·Game tables are OUTRIGHT-only (no bounding Buy-YES), so the band-only "Buy YES (bound)"
# column is dropped; everything else matches the Championship table (kept in sync by filtering).
_NO_OUTRIGHT_COLUMNS = [c for c in _NO_STRUCTURE_COLUMNS if c["name"] != "parent_yes"]
_NO_OUTRIGHT_HIDDEN = tuple(n for n in _NO_STRUCTURE_HIDDEN if n != "parent_yes")
# Championship table adds per-LADDER shape metrics as columns (display-only; descriptive, NOT EV/edge —
# the same numbers as the grouped ladder summary, annotated onto each row of that participant's ladder).
# `depth` = how deep the ladder is (rungs); see viewmodel._ladder_metrics. Frame-backed → blank ("—") when
# evidence frames aren't captured. depth/avg/deepest÷steps/gradient lead; the rest start hidden.
_LADDER_METRIC_COLS = [
    {"name": "depth", "label": "Ladder depth", "field": "depth", "align": "right", "sortable": True},
    {"name": "avg_no", "label": "Avg NO ¢", "field": "avg_no", "align": "right", "sortable": True},
    {"name": "deepest_step", "label": "Deepest ÷ steps", "field": "deepest_step", "align": "right", "sortable": True},
    {"name": "gradient", "label": "Gradient ¢/step", "field": "gradient", "align": "right", "sortable": True},
    {"name": "deepest_no", "label": "Deepest NO ¢", "field": "deepest_no", "align": "right", "sortable": True},
    {"name": "total_fade", "label": "Cost to NO every rung ¢", "field": "total_fade", "align": "right", "sortable": True},
    {"name": "cheapest_no", "label": "Cheapest NO ¢", "field": "cheapest_no", "align": "right", "sortable": True},
    {"name": "n_cheap", "label": "# cheap rungs", "field": "n_cheap", "align": "right", "sortable": True},
    {"name": "span", "label": "Span ¢", "field": "span", "align": "right", "sortable": True},
]
# Championship title-path columns (display-only; CANONICAL longest path, sport constant). "Title-path
# events" displays the "min–max" label but sorts on the numeric `title_events_max`. Shown by default ONLY on
# the Championship table; populated only on championship-scope rows (blank everywhere else).
_TITLE_PATH_COLS = [
    {"name": "title_tournaments", "label": "Title-path tournaments", "field": "title_tournaments",
     "align": "right", "sortable": True},
    {"name": "title_events", "label": "Title-path events", "field": "title_events_max",
     "align": "right", "sortable": True},
]
_NO_CHAMP_COLUMNS = _NO_STRUCTURE_COLUMNS + _LADDER_METRIC_COLS + _TITLE_PATH_COLS
_NO_CHAMP_HIDDEN = _NO_STRUCTURE_HIDDEN + ("deepest_no", "total_fade", "cheapest_no", "n_cheap", "span")
_NO_CHAMP_NUMS = _NO_STRUCTURE_NUMS + tuple(c["name"] for c in _LADDER_METRIC_COLS)
_TITLE_PATH_COL_NAMES = tuple(c["name"] for c in _TITLE_PATH_COLS)
# The Event table is dominated by non-laddered games/matches → start ALL ladder-metric columns hidden so
# it isn't a wall of blank cells (the Columns button still reveals them for golf/motorsport field ladders).
# Title-path columns are championship-only, so hide them on Event/Tournament/All by default.
_NO_EVENT_HIDDEN = _NO_STRUCTURE_HIDDEN + tuple(c["name"] for c in _LADDER_METRIC_COLS) + _TITLE_PATH_COL_NAMES
_NO_NONCHAMP_HIDDEN = _NO_CHAMP_HIDDEN + _TITLE_PATH_COL_NAMES   # Tournament + All hide title-path by default
# Per-participant ladder SUMMARY (grouped Championship view): descriptive ladder-shape diagnostics, one
# row per participant ladder, numeric columns sortable. NOT EV / probability / edge (see table caption).
_LADDER_SUMMARY_COLUMNS = [
    {"name": "player", "label": "Participant", "field": "player", "align": "left", "sortable": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "depth", "label": "Depth (rungs)", "field": "depth", "align": "right", "sortable": True},
    {"name": "avg_no", "label": "Avg NO ¢", "field": "avg_no", "align": "right", "sortable": True},
    {"name": "deepest_no", "label": "Deepest NO ¢", "field": "deepest_no", "align": "right", "sortable": True},
    {"name": "deepest_per_step", "label": "Deepest ÷ steps", "field": "deepest_per_step", "align": "right", "sortable": True},
    {"name": "total_fade", "label": "Cost to NO every rung ¢", "field": "total_fade", "align": "right", "sortable": True},
    {"name": "gradient", "label": "Gradient ¢/step", "field": "gradient", "align": "right", "sortable": True},
    {"name": "cheapest_no", "label": "Cheapest NO ¢", "field": "cheapest_no", "align": "right", "sortable": True},
    {"name": "cheapest_rung", "label": "Cheapest rung", "field": "cheapest_rung", "align": "left"},
    {"name": "n_cheap", "label": "# cheap", "field": "n_cheap", "align": "right", "sortable": True},
    {"name": "span", "label": "Span ¢", "field": "span", "align": "right", "sortable": True},
    {"name": "max_cascade", "label": "Max cascade", "field": "max_cascade", "align": "right", "sortable": True},
    {"name": "implied_yes", "label": "Market-implied YES %", "field": "implied_yes", "align": "right", "sortable": True},
    {"name": "inverted", "label": "Inv", "field": "inverted", "align": "center"},
]

# Qualifier-setups table (#4/#5). NO gross-edge / ROI / size / profit columns (those are blank for a
# non-Actionable signal and would imply tradability). Default-visible columns are the exact-order top-two
# economics; the rest start hidden behind the column chooser. Numeric columns hold RAW numbers (cell slots
# format display only, so numeric sort is preserved); the two quote columns sort on a numeric `*_rank`
# field while DISPLAYING the `*_label` string (custom Tight→Crossed order). The hidden Support score ¢ is
# the only meaningful column for game-support rows (a heuristic — see its tooltip). Group / Event ticker
# are intentionally absent (not in the unified schema; deferred to a separate schema PR).
_QS_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center", "required": True},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Team", "field": "name", "align": "left", "sortable": True},
    {"name": "setup", "label": "Setup", "field": "setup", "align": "left", "sortable": True},
    {"name": "qualifier", "label": "Qualifier YES ask ¢", "field": "qualifier", "align": "center", "sortable": True},
    {"name": "cost", "label": "Top-two bundle cost ¢", "field": "cost", "align": "center", "sortable": True},
    {"name": "premium", "label": "Cheaper vs qualifier ¢", "field": "premium", "align": "center", "sortable": True},
    {"name": "if_top2", "label": "If top two ¢", "field": "if_top2", "align": "center", "sortable": True},
    {"name": "if_not_top2", "label": "If not top two ¢", "field": "if_not_top2", "align": "center", "sortable": True},
    {"name": "max_units", "label": "Max units", "field": "max_units", "align": "center", "sortable": True},
    {"name": "worst_leg_quote", "label": "Worst leg quote", "field": "worst_leg_quote_rank", "align": "center", "sortable": True},
    {"name": "comparator_quote", "label": "Comparator quote", "field": "comparator_quote_rank", "align": "center", "sortable": True},
    {"name": "legs", "label": "Legs", "field": "legs", "align": "center", "sortable": True},
    {"name": "review_status", "label": "Review status", "field": "review_status", "align": "center", "sortable": True},
    {"name": "caveat", "label": "Caveat", "field": "caveat", "align": "left"},
    # --- hidden optional (default-hidden via _QS_HIDDEN) ---
    {"name": "support", "label": "Support score ¢", "field": "support", "align": "center", "sortable": True},
    {"name": "highest_leg", "label": "Highest leg ask ¢", "field": "highest_leg", "align": "center", "sortable": True},
    {"name": "median_leg", "label": "Median leg price ¢", "field": "median_leg", "align": "center", "sortable": True},
    {"name": "range_leg", "label": "Leg price range ¢", "field": "range_leg", "align": "center", "sortable": True},
    {"name": "inactive_legs", "label": "Inactive legs", "field": "inactive_legs", "align": "center", "sortable": True},
    {"name": "no_quote_legs", "label": "No-quote legs", "field": "no_quote_legs", "align": "center", "sortable": True},
    {"name": "wide_legs", "label": "Wide legs", "field": "wide_legs", "align": "center", "sortable": True},
    {"name": "comparator_spread", "label": "Comparator spread ¢", "field": "comparator_spread", "align": "center", "sortable": True},
    {"name": "worst_leg_spread", "label": "Worst leg spread ¢", "field": "worst_leg_spread", "align": "center", "sortable": True},
    {"name": "qualifier_market_status", "label": "Qualifier market status", "field": "qualifier_market_status", "align": "center", "sortable": True},
    {"name": "all_legs_active", "label": "All legs active", "field": "all_legs_active", "align": "center", "sortable": True},
    {"name": "opp_id", "label": "Opportunity ID", "field": "opportunity_id", "align": "left", "sortable": True},
    {"name": "market_tickers", "label": "Market tickers", "field": "market_tickers", "align": "left"},
    {"name": "comparator_ticker", "label": "Comparator ticker", "field": "comparator_ticker", "align": "left", "sortable": True},
    {"name": "tournament_key", "label": "Tournament key", "field": "tournament_key", "align": "left", "sortable": True},
    {"name": "full_caveat", "label": "Full caveat", "field": "caveat", "align": "left"},
]
# Default-hidden qualifier columns (everything past the focused default-visible set). The leading `new`
# marker is `required` and never offered.
_QS_HIDDEN = ("support", "highest_leg", "median_leg", "range_leg", "inactive_legs", "no_quote_legs",
              "wide_legs", "comparator_spread", "worst_leg_spread", "qualifier_market_status",
              "all_legs_active", "opp_id", "market_tickers", "comparator_ticker", "tournament_key",
              "full_caveat")
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
# Conditional-probability panel (DISPLAY-ONLY): P(deeper | parent) = price(deeper) / price(parent), shown
# raw AND field-implied (de-vig). De-vig headers say "field-impl. est." — never "probability"/"fair".
_COND_COLUMNS = [
    {"name": "parent", "label": "Parent stage", "field": "parent", "align": "left"},
    {"name": "parent_pct", "label": "Stage %", "field": "parent_pct", "align": "right"},
    {"name": "win_raw", "label": "Win | stage (raw)", "field": "win_raw", "align": "right"},
    {"name": "win_dv", "label": "Win | stage (field-impl. est.)", "field": "win_dv", "align": "right"},
    {"name": "next_node", "label": "Next rung", "field": "next_node", "align": "left"},
    {"name": "next_raw", "label": "Next | stage (raw)", "field": "next_raw", "align": "right"},
    {"name": "next_dv", "label": "Next | stage (field-impl. est.)", "field": "next_dv", "align": "right"},
    {"name": "flag", "label": "", "field": "flag", "align": "left"},
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
                             "_suppress_cascade": False,
                             # PR R — responsiveness. `view` = the ranked+filtered opp list, cached so a
                             # bounded-loss/near-miss control change re-slices it WITHOUT re-filtering or
                             # rebuilding the other tables. `scan_status` cached so the hot path never reads
                             # the store. `pending_refresh` = (kind, monotonic deadline) for the debounce.
                             "view": [], "scan_status": None, "pending_refresh": None,
                             # Branch 2 render telemetry (shown in Diagnostics): the last rerender's phase
                             # durations, so any further UI tuning (e.g. PR1b table-row diffing) is gated on
                             # measurement, not guesswork. `freshness_text` caches the last banner string so
                             # the 1s tick only pushes when it actually changed.
                             "rerender_count": 0, "last_total_rerender_ms": None, "last_filter_ms": None,
                             "last_cascade_ms": None, "last_row_build_ms": None,
                             "last_table_update_ms": None, "freshness_text": None,
                             # Last-pushed scan-indicator state (bool) — the 1s tick only pushes a label
                             # change on an idle<->in_progress transition, mirroring the freshness guard.
                             "scan_indicator": None}

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
            qs_switch = ui.switch("Qualifier setups", value=True).tooltip(  # opt-in (default-on)
                "Show the World Cup Qualifier setups section — speculative top-two ideas (review-only) + "
                "diagnostic reference bundles + game-support signals. Gross, top-of-book, settlement-"
                "unverified; NOT arbitrage and never Actionable.")
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
            ns_switch = ui.switch("Cheap NO fades", value=True).tooltip(  # on by default (promoted below Bounded-Loss)
                "A speculative, opt-in fade: the cheapest Buy-NO you can take, optionally bounded by a Buy-YES "
                "on the broader rung that contains it (a defined band). NOT an edge — a cheap NO is cheap "
                "because the market thinks the YES is likely. Gross, top-of-book, uncalibrated.")
            ns_kind = ui.select(_NO_STRUCTURE_KINDS, value="all", label="NO-fade kind").props(
                "stack-label").classes("min-w-[9rem]")
            ns_max_loss = ui.number("Max loss ¢", value=config.NO_STRUCTURE_DEFAULT_MAX_LOSS_C,
                                    min=0, max=config.NO_STRUCTURE_BAND_MAX_LOSS_C, format="%.0f").classes("w-28")
            ns_max_buy_no = ui.number("Max Buy-NO ¢", value=config.NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C,
                                      min=0, max=config.NO_STRUCTURE_OUTRIGHT_MAX_C, format="%.0f").classes(
                "w-32").tooltip("Cap the Buy-NO cost for single-NO (outright) fades only. 0 = off. "
                                "Bands use 'Max loss ¢' plus the normal quote/status filters.")
            ns_group = ui.switch("Group by participant (ladder)", value=False).tooltip(
                "Group the cheap NOs into each participant's containment ladder (broad → deep). A single NO "
                "anywhere cascades — one elimination = no-win — so a cheap NO at a broad rung is a "
                "maximally-leveraged longshot fade.")
            ns_sort = ui.select(_NO_FADE_SORTS, value="safe", label="Ladder sort").props(
                "stack-label").classes("min-w-[12rem]").tooltip(
                "Cascade score is an ORDINAL longshot-upside score — NOT EV, probability, fair value, or "
                "mispricing. A higher score usually means a LOWER implied chance.")
            ns_wide = ui.switch("Include wide quotes", value=False).tooltip(
                "Off (default) keeps only Tight/OK books — a cheap NO on a wide/one-sided book is usually a "
                "stale quote, not a real fade. On widens the tables to every stored NO fade.")
        ui.label("Filters & thresholds").classes("text-sm font-bold mt-2")
        with ui.row().classes("items-end gap-4 flex-wrap"):
            active_sw = ui.switch("Active only").tooltip("Hide non-active (finalized/settled) markets.")
            rank_sel = ui.select(vm.RANK_MODES, value=vm.RANK_MODE_DEFAULT, label="Rank by").tooltip(
                "Within each section: Per-unit edge ¢, Spread upside (speculative bounded-loss geometry: "
                "upside:risk, then spread, then lower max loss), Outright + spread (speculative: highest deeper "
                "display outright first, then lowest display spread÷outright), Implied EV (bounded-loss only: "
                "implied payoff chance − overpay — chance-weighted, so a high ratio at near-zero chance ranks "
                "below a lower ratio that is far likelier to pay; a market-implied ranking AID, not a guarantee), "
                "or Blended (edge + ROI % + geometry). Gross, top-of-book — not a probability model.")
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
    # The scan indicator sits NEXT to the freshness banner: during a 3-4s scan the dashboard otherwise
    # silently shows the previous snapshot — the label makes "old data, refresh in flight" visible. It covers
    # every scan source (scheduler, another LAN viewer, POST /scan), not just this client's "Scan now".
    with ui.row().classes("items-center gap-3"):
        freshness = ui.label().classes("text-sm").style("font-variant-numeric: tabular-nums")
        scanning_lbl = ui.label().classes("text-sm text-primary font-medium")
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

    def _comparator_contract_for(opp: dict[str, Any]) -> dict[str, Any] | None:
        """The qualifier COMPARATOR's stored contract row (its `ticker_2`), for the comparator spread /
        market-status columns. The comparator is NOT in the legs list, so `_contract_lookup_for` never
        indexes it. None when the ticker is blank or unresolved (the columns then blank out)."""
        tkr = opp.get("ticker_2") or ""
        return engine.contract_by_ticker(tkr, sport=opp.get("sport") or None) if tkr else None

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
            _is_top2 = vm._is_exact_order_bundle(opp)
            if legrows:
                ui.label("Top-two bundle (12 legs)" if _is_top2 else "Buy plan (legs)"
                         ).classes("text-sm font-bold mt-2")
                ui.table(columns=_LEG_COLUMNS, rows=legrows, row_key="leg").classes("w-full")
                if _is_top2:
                    ui.label(f"Comparator (not a leg): {opp.get('name')} qualify YES "
                             f"@ {opp.get('qualifier_yes_ask_c')}¢").classes("text-sm text-gray-600")
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
                if _is_top2:
                    # Filtered bundle legs (no legacy comparator leg) + the qualifier comparator link.
                    for lr in legrows:
                        if lr.get("url"):
                            ui.link(f"{lr['leg']} market ↗", lr["url"], new_tab=True)
                    if opp.get("url"):
                        ui.link("Comparator: qualifier market ↗", opp["url"], new_tab=True)
                else:
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
            # PR E — bounded-loss decision block (Can I lose money? / Wins big if / Why ranked / Why skip).
            for _lbl, _txt in vm.speculative_explainer(opp):
                ui.label(f"{_lbl}: {_txt}").classes("text-sm text-gray-700")
            # Cheap-NO-fade decision block (what is this / can I lose money / wins if / breakeven / payoff).
            for _lbl, _txt in vm.no_structure_explainer(opp):
                ui.label(f"{_lbl}: {_txt}").classes("text-sm text-gray-700")
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
            # Derived market-implied indicators (DISPLAY-ONLY bounds, e.g. golf "make the cut" ≥ Top-20 price).
            # Not a traded market and never an edge — a labeled bound read off the ladder's display prices.
            for ind in vm.derived_indicators(chain, sport):
                v = ind.get("value_pct")
                shown = "—" if v is None else f"{ind.get('comparator', '')} {v:.0f}%".strip()
                ui.label(f"Implied: {ind.get('label')} {shown}").classes("text-sm mt-3")
                ui.label(ind.get("note") or "").classes("text-xs text-gray-500")
            # Conditional probability (PDF "core logic"): P(deeper | parent) = price(deeper)/price(parent),
            # shown raw AND field-implied (de-vig over the whole tournament field). DISPLAY-ONLY — never an
            # edge, never fed to detection. Field-de-vig needs the whole field, so load it once here.
            cond = vm.conditional_probabilities(
                prows, engine.tournament_field(sport, opp.get("tournament") or ""), sport)
            if cond and any(r.get("win_cond_raw") is not None or r.get("next_cond_raw") is not None
                            for r in cond):
                def _pf(v: float | None) -> str:
                    return "—" if v is None else f"{v:.0f}%"
                any_partial = any(r.get("partial") for r in cond)
                crows = [{
                    "parent": r.get("parent"),
                    "parent_pct": _pf(r.get("parent_pct")),
                    "win_raw": _pf(r.get("win_cond_raw")),
                    "win_dv": _pf(r.get("win_cond_dv")),
                    "next_node": r.get("next_node"),
                    "next_raw": _pf(r.get("next_cond_raw")),
                    "next_dv": _pf(r.get("next_cond_dv")),
                    "flag": "⚠ ladder inverted" if r.get("ladder_inverted") else
                            ("· field-implied = floor" if r.get("partial") else ""),
                } for r in cond]
                ui.label("Conditional probability — chance of converting from a stage").classes(
                    "font-medium mt-3")
                ui.table(columns=_COND_COLUMNS, rows=crows, row_key="parent").classes(
                    "w-full overflow-x-auto")
                ui.label("P(deeper | parent) = price(deeper) ÷ price(parent). Market-implied; gross, "
                         "top-of-book, Uncalibrated — NOT a fair value or true probability.").classes(
                    "text-xs text-gray-500")
                if any_partial:
                    ui.label("⚠ Partial field — the field-implied (de-vig) estimate is a FLOOR (lower "
                             "bound), not a full probability; thinly-priced fields are not inflated.").classes(
                        "text-xs text-amber-700")
                if sport == "golf":
                    ui.label("Golf Top-N can settle for more than N players on a tie (dead heat), so the "
                             "field-implied estimate is floor-leaning.").classes("text-xs text-gray-500")
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

    # Watchlist-style section header helper — a custom expansion header slot so the "Columns" button sits
    # beside the title (added after the table exists); the title label is kept in a ref so rerender can
    # update its live count. `expanded` opens the section on load (Bounded-Loss is promoted + default-open).
    def _expansion_header(title: str, *, expanded: bool = False) -> tuple[Any, Any, Any]:
        exp = ui.expansion(value=expanded).classes("w-full mt-2")
        with exp.add_slot("header"), ui.row().classes("items-center w-full gap-2"):
            ui.icon("unfold_more").classes("text-grey")
            title_label = ui.label(title).classes("text-lg font-bold")
            ui.space()
            cols_holder = ui.row().classes("items-center")     # Columns button dropped in here later
        return exp, title_label, cols_holder

    # `dense` tables + `overflow-x-auto` so many rows fit and wide tables scroll instead of overflowing.
    # Actionable + Review Required are collapsible (open by default), matching the watch-only sections: the
    # title carries a live count and the "Columns" button sits in the expansion header slot.
    act_expansion, act_title, act_cols_row = _expansion_header(
        "Actionable — executable gross edges", expanded=True)
    with act_expansion:
        ui.label("Firm, sized, currently-tradable gross pricing discrepancies. Gross of fees.").classes(
            "text-xs text-gray-500")
        actionable = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                              pagination=15).props("dense").classes("w-full overflow-x-auto opp-sel")
    actionable.on_select(_on_select(actionable))

    review_expansion, review_title, review_cols_row = _expansion_header(
        "Review Required — settlement-dependent", expanded=True)
    with review_expansion:
        ui.label("Real, executable-looking edges whose legs may not settle together (e.g. an exact-score "
                 "bundle vs the match winner) — verify the settlement rules first; never "
                 "auto-tradable.").classes("text-xs text-gray-500")
        review = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                          pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    review.on_select(_on_select(review))

    blocked_hdr = _section_header("Blocked — not currently executable",
                                  "Discrepancies that exist but aren't tradable now (no firm size / an inactive leg).")
    blocked = ui.table(columns=_OPP_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                       pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    blocked.on_select(_on_select(blocked))

    # Bounded-Loss Bets — promoted ABOVE the Qualifier setups section and OPEN by default: a real placeable
    # bet (capped loss, convex upside) and the trader's primary cross-sport comparison surface. A bet, NOT
    # an edge. Its opposite-shape sibling "Overpriced Books" stays below, after the qualifier section.
    rb_expansion, rb_title, rb_cols_row = _expansion_header(
        "Bounded-Loss Bets — capped downside, convex upside", expanded=True)
    with rb_expansion:
        ui.label("Buy the broader YES + the deeper NO for just over 100¢: your loss is capped at the small "
                 "overpay, with convex upside (the broader-but-not-deeper outcome pays about +$1). A bet, NOT "
                 "an edge — gross of fees.").classes("text-xs text-gray-500")
        ui.label("Market gap (pp) = parent−child display-price gap (the UNCONDITIONAL implied chance of the "
                 "payoff zone). Success given reached % = the CONDITIONAL chance the payoff zone hits given "
                 "the broader outcome happens (1 − child/parent); Deeper given reached % = its complement "
                 "child/parent (the chance the deeper outcome also occurs) — a market-implied / uncalibrated "
                 "pair, less sensitive to a common overround but NOT de-vigged. Firm success gap ¢ = the "
                 "conservative parent-bid − child-ask gap; ≤ 0 "
                 "(the 'Midpoint-only' flag) means the display positive isn't confirmed by firm quotes. Gap "
                 "vs breakeven (pp) = implied chance minus the chance needed to clear the overpay. Parent ÷ "
                 "max loss = the parent's in-the-money probability per cent of max loss (cost − 100, the "
                 "at-risk overpay); higher = more likely-to-reach per cent at risk; deep longshots sink.").classes(
                     "text-xs text-gray-500")
        ui.label("All gross, top-of-book, display-implied — comparison aids, NOT a guarantee or a calibrated "
                 "probability model. Fees, slippage, full-depth fill, latency, and settlement-rule edge "
                 "cases are not modeled. A negative gap means an inverted ladder (flagged 'Inverted / "
                 "diagnostic'), never a chance.").classes("text-xs text-gray-500")

        # Split by resolution shape (PR B): Vertical = both legs settle at one event (golf Top-N, a
        # match-alignment equivalence) so there's no carry between them; Calendar = the legs settle on
        # different days, so you hold staged exposure across the gap. Same capped max loss either way.
        def _rb_subsection(heading: str, tip: str):
            with ui.row().classes("items-center w-full gap-2 mt-3"):
                _title = ui.label(heading).classes("text-base font-bold")
                ui.icon("info").classes("text-grey text-sm").tooltip(tip)
                ui.space()
                _cols = ui.row().classes("items-center")
            _tbl = ui.table(columns=_RISK_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                            pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
            return _title, _cols, _tbl

        # PR E — combined "All" table FIRST (every bounded-loss bet, ranked together, with a Kind column),
        # then the Vertical / Calendar split below for focus.
        rb_all_title, rb_all_cols, rb_all = _rb_subsection(
            "All bounded-loss bets",
            "Every bounded-loss bet ranked together (Vertical + Calendar). The Kind column marks which is "
            "which; the two sections below split them out for focus.")
        rb_vert_title, rb_vert_cols, rb_vertical = _rb_subsection(
            "Vertical — both legs resolve together",
            "Both legs settle at one event's outcome (e.g. golf Top-10 vs Top-5, or a match-win ≡ "
            "reach-next-stage equivalence). No window where one leg is settled and the other is still open.")
        rb_cal_title, rb_cal_cols, rb_calendar = _rb_subsection(
            "Calendar — legs resolve on different days",
            "The legs settle in sequence across rounds (e.g. reach the final, then win it), so you hold "
            "staged exposure across the gap. Same capped max loss as a vertical bet — just a longer hold.")
    rb_all.on_select(_on_select(rb_all))
    rb_vertical.on_select(_on_select(rb_vertical))
    rb_calendar.on_select(_on_select(rb_calendar))

    # Cheap NO fades (NO-anchored structures): promoted directly BELOW Bounded-Loss Bets and ON by default —
    # it's the closest sibling (a cheap convex fade anchored on a Buy-NO leg). Collapsible + switch-gated like
    # the other watch-only sections. A speculative watch-only fade, NOT an edge.
    ns_expansion, ns_title, ns_cols_row = _expansion_header("Cheap NO fades — bounded-loss NO anchor (watch-only)")
    with ns_expansion:
        ui.label("The cheapest Buy-NO you can take. A 'band' bounds it with a Buy-YES on the broader rung "
                 "that contains it, so loss is capped at the small overpay (cost − 100¢) and the "
                 "'reaches broader, not deeper' window pays about +$1; a 'single NO' is an unbounded "
                 "directional fade watchlist. A cheap NO is cheap because the market thinks the YES is "
                 "likely — this is NOT an edge. Gross, top-of-book, uncalibrated.").classes(
                     "text-xs text-gray-500")
        ui.label("Split by SETTLEMENT LEVEL — how the contract settles, NOT the sport's naming. "
                 "Event = a single contest (game/match/race; incl. a golf or motorsport field result — a "
                 "single field outcome, not a bracket above another contest). Tournament = one level up "
                 "(a best-of-7 series, win the French Open / World Cup / Super Bowl, an F1 season). "
                 "Championship = two levels up (NBA/NHL/MLB titles, which sit above a best-of-7 series "
                 "layer; the tennis Grand Slam). So 'win the NBA title' is Championship, but 'win the "
                 "World Cup' is Tournament.").classes("text-xs text-gray-500")
        ui.label("Championship 'Title-path tournaments / events' columns = the sport's CANONICAL longest "
                 "path to the title (the constituent series/majors and possible games; byes/play-in shorten "
                 "it for top seeds). Display-only — not this row's remaining path, not a probability or EV.").classes(
                     "text-xs text-gray-500")
        ns_legacy_label = ui.label().classes("text-sm text-amber-700")
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.label("View:").classes("text-xs text-gray-500")
            ns_view = ui.toggle({"by_level": "By level", "all": "All"}, value="by_level").props("dense")
        # Four flat tables (Event → Tournament → Championship, then a combined All). All share the full
        # column set incl. ladder-metric columns; a band's level = its child rung's level, so bands can
        # appear in any table. Each gets its own inline "Columns" button — Event starts with the metric
        # columns hidden (mostly non-laddered games), the rest start with them visible.
        def _ns_level_table(default_hidden: tuple[str, ...]) -> tuple[Any, Any]:
            hdr = ui.row().classes("items-center gap-3 mt-1")
            with hdr:
                lbl = ui.label().classes("text-sm font-medium")
            tbl = ui.table(columns=_NO_CHAMP_COLUMNS, rows=[], row_key="opportunity_id",
                           selection="single", pagination=10).props("dense").classes(
                               "w-full overflow-x-auto opp-sel")
            with hdr:
                build_column_menu(tbl, _NO_CHAMP_COLUMNS, default_hidden=default_hidden)
            return lbl, tbl

        ns_event_label, ns_event_table = _ns_level_table(_NO_EVENT_HIDDEN)
        ns_tournament_label, ns_tournament_table = _ns_level_table(_NO_NONCHAMP_HIDDEN)
        ns_championship_label, ns_championship_table = _ns_level_table(_NO_CHAMP_HIDDEN)
        ns_all_label, ns_all_table = _ns_level_table(_NO_NONCHAMP_HIDDEN)
        # Grouped view (participant-ladder, level-agnostic): a sortable summary table + cascade cards.
        ns_summary_label = ui.label().classes("text-sm font-medium mt-1")
        ns_summary_table = ui.table(columns=_LADDER_SUMMARY_COLUMNS, rows=[], row_key="player_key",
                                    pagination=10).props("dense").classes("w-full overflow-x-auto")
        ns_summary_cap = ui.label("These are ladder-shape diagnostics from top-of-book prices — NOT EV, "
                                  "model probability, net of fees, or an actionability score.").classes(
                                      "text-xs text-gray-500")
        ns_cards = ui.column().classes("w-full gap-2")
        ns_excluded_label = ui.label().classes("text-xs text-gray-500")
    # Event / Tournament / Championship (in display order) + the combined All table.
    ns_scope_tables = {"event": ns_event_table, "tournament": ns_tournament_table,
                       "championship": ns_championship_table}
    ns_scope_labels = {"event": ns_event_label, "tournament": ns_tournament_label,
                       "championship": ns_championship_label}
    _ns_tables = (*ns_scope_tables.values(), ns_all_table)
    for _t in _ns_tables:
        _t.on_select(_on_select(_t))

    # World Cup Qualifier Setups (PR3): a separate, default-on, opt-in DIAGNOSTIC section — kept out of the
    # strict Actionable/Review/Blocked sections. Populated by the exact-order (#4) top-two bundles + game-
    # support (#5) signals; the flagged baskets/spreads still live in their own sections (PR1 badge).
    # Collapsible like the other watch-only sections (switch-gated via qs_switch).
    qs_expansion, qs_title, qs_cols_row = _expansion_header(
        "Qualifier setups — World Cup group-stage ideas & signals")
    with qs_expansion:
        ui.label("Speculative top-two ideas (review-only) + diagnostic reference bundles + game-support "
                 "signals — gross, top-of-book, settlement-unverified; NOT arbitrage and never "
                 "Actionable.").classes("text-xs text-gray-500")
        qs_table = ui.table(columns=_QS_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                            pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    qs_table.on_select(_on_select(qs_table))

    nm_expansion, nm_title, nm_cols_row = _expansion_header("Overpriced Books — flat guaranteed loss (watch-only)")
    with nm_expansion:
        ui.label("A complete (MECE) book priced just OVER its payout floor: it pays the floor in every "
                 "outcome, so buying the whole bundle is a flat, guaranteed gross loss. Watch-only, in case a "
                 "leg gets mispriced.").classes("text-xs text-gray-500")
        nm_table = ui.table(columns=_NEARMISS_COLUMNS, rows=[], row_key="opportunity_id", selection="single",
                            pagination=10).props("dense").classes("w-full overflow-x-auto opp-sel")
    nm_table.on_select(_on_select(nm_table))

    _sel_tables.extend([actionable, review, blocked, qs_table, rb_all, rb_vertical, rb_calendar, nm_table,
                        *_ns_tables])
    for _t in _sel_tables:                 # the change-signal / NEW-badge indicator column on every table
        _t.add_slot("body-cell-new", _CHANGE_CELL_SLOT)
    for _t in (actionable, review, blocked):
        _t.add_slot("body-cell-edge", _EDGE_CELL_SLOT)      # colour the edge value on change
        _t.add_slot("body-cell-action", _ACTION_CELL_SLOT)  # left-aligned legs
        _t.add_slot("body-cell-caveat", _CAVEAT_CELL_SLOT)  # compact severity chip
    for _rb in (rb_all, rb_vertical, rb_calendar):
        _rb.add_slot("body-cell-caveat", _CAVEAT_CELL_SLOT)
        # Phase 1 likelihood/comparability cells (display-only): honesty badges, the conservative firm gap
        # (¢, firm % in tooltip), and the two tooltip'd metrics. Numeric sort is preserved on the raw fields.
        _rb.add_slot("body-cell-flags", _RB_FLAGS_CELL_SLOT)
        _rb.add_slot("body-cell-firm_gap", _RB_FIRM_GAP_CELL_SLOT)
        _rb.add_slot("body-cell-cond_success", _num_tip_cell_slot(
            "cond_success",
            "Conditional chance the success zone happens GIVEN the broader outcome is reached "
            "(1 − child/parent), display-implied. Less sensitive to a common overround; still "
            "quote-dependent, top-of-book, and uncalibrated — NOT de-vigged or fair value.", "%"))
        _rb.add_slot("body-cell-cond_child", _num_tip_cell_slot(
            "cond_child",
            "Conditional chance the DEEPER outcome ALSO occurs GIVEN the broader is reached (child/parent) "
            "— the complement of 'Success given reached %' (the two sum to 100). Market-implied / "
            "uncalibrated, display-price based; less sensitive to a common overround but NOT de-vigged or "
            "fair value.", "%"))
        _rb.add_slot("body-cell-parent_over_maxloss", _num_tip_cell_slot(
            "parent_over_maxloss",
            "The parent's implied probability (the chance the broader, in-the-money outcome happens, in ¢ = "
            "pp) divided by the MAX LOSS (cost − 100, the at-risk overpay): parent_outright / (cost_c − 100). "
            "HIGHER = better — more in-the-money probability per cent actually at risk; deep-longshot parents "
            "sink. Gross, top-of-book, uncalibrated.", ""))
    nm_table.add_slot("body-cell-note", _NOTE_CELL_SLOT)    # readable wrapping note
    for _t in _ns_tables:                                   # compact severity chip (same as the rb tables)
        _t.add_slot("body-cell-caveat", _CAVEAT_CELL_SLOT)
    # Qualifier-setups: compact caveat chips + the full prose (hidden col); the two quote columns show the
    # label while sorting on their numeric rank.
    qs_table.add_slot("body-cell-caveat", _QS_CAVEAT_CELL_SLOT)
    qs_table.add_slot("body-cell-full_caveat", _wrap_cell_slot("caveat"))
    qs_table.add_slot("body-cell-worst_leg_quote", _label_cell_slot("worst_leg_quote_label"))
    qs_table.add_slot("body-cell-comparator_quote", _label_cell_slot("comparator_quote_label"))
    # Thousands-separated numeric cells (display only; numeric sort preserved). 'edge' is handled above.
    for _t in (actionable, review, blocked):
        for _f in ("roi", "units", "profit", "net_edge", "net_profit", "fees"):
            _t.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _f in ("cost", "max_loss", "max_profit", "max_units", "loss_100", "upside_100", "ratio",
               "gap_vs_be", "roc", "spread_over_parent", "spread_over_child",
               "parent_outright", "child_outright", "display_spread"):
        for _rb in (rb_all, rb_vertical, rb_calendar):
            _rb.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _f in ("cost", "overpay"):
        nm_table.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _f in _NO_CHAMP_NUMS:                               # all four NO-fade tables: per-structure + metric nums
        for _t in _ns_tables:
            _t.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    for _t in _ns_tables:                                  # title-path events: show "min–max" label, sort on max
        _t.add_slot("body-cell-title_events", _label_cell_slot("title_events_label"))
    for _f in ("qualifier", "cost", "if_top2", "if_not_top2", "max_units", "support", "legs",
               "highest_leg", "median_leg", "range_leg", "inactive_legs", "no_quote_legs", "wide_legs",
               "comparator_spread", "worst_leg_spread"):
        qs_table.add_slot(f"body-cell-{_f}", _num_cell_slot(_f))
    qs_table.add_slot("body-cell-premium", _PREMIUM_CELL_SLOT)   # sign-aware text, numeric sort preserved
    # Compact empty states: a shown-but-empty section renders a small message row, not a bare grid.
    for _t, _msg in ((actionable, "No actionable opportunities in the current filters."),
                     (review, "No review-required opportunities in the current filters."),
                     (blocked, "No blocked opportunities in the current filters."),
                     (qs_table, "No qualifier setups in the current filters."),
                     (rb_all, "No bounded-loss bets in the current filters."),
                     (rb_vertical, "No vertical (same-event) bounded-loss bets in the current filters."),
                     (rb_calendar, "No calendar (multi-day) bounded-loss bets in the current filters."),
                     (nm_table, "No overpriced books in the current filters."),
                     (ns_event_table, "No Event cheap NO fades in the current filters."),
                     (ns_tournament_table, "No Tournament cheap NO fades in the current filters."),
                     (ns_championship_table, "No Championship cheap NO fades in the current filters."),
                     (ns_all_table, "No cheap NO fades in the current filters.")):
        _t.props(f'no-data-label="{_msg}"')

    # Per-table column menus (redesigned) — a "Columns" button by each table opening labeled checkboxes.
    # Opp tables hide the net-of-fees columns by default; Bounded-Loss hides the outright/display-spread
    # context (spread÷parent/child stay visible). Buttons are placed into each section's header / row.
    opp_menus = []
    for _hdr, _tbl in ((act_cols_row, actionable), (review_cols_row, review), (blocked_hdr, blocked)):
        with _hdr:
            opp_menus.append(build_column_menu(_tbl, _OPP_COLUMNS, default_hidden=_NET_COLUMNS))
    with qs_cols_row:
        build_column_menu(qs_table, _QS_COLUMNS, default_hidden=_QS_HIDDEN)
    with rb_all_cols:
        build_column_menu(rb_all, _RISK_COLUMNS, default_hidden=_RISK_HIDDEN)            # combined: show Kind
    with rb_vert_cols:
        build_column_menu(rb_vertical, _RISK_COLUMNS, default_hidden=_RISK_HIDDEN_SPLIT)  # split: hide Kind
    with rb_cal_cols:
        build_column_menu(rb_calendar, _RISK_COLUMNS, default_hidden=_RISK_HIDDEN_SPLIT)
    with nm_cols_row:
        build_column_menu(nm_table, _NEARMISS_COLUMNS)
    # (NO-fade column menus are created inline per table in `_ns_level_table` above.)

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
            # Branch 2 render telemetry: last rerender's phase durations (ms). Gates any further UI tuning
            # (e.g. PR1b row-diffing if `apply` dominates). `write_ms` is the last scan's snapshot write.
            ui.label(
                f"render #{state.get('rerender_count') or 0} · total {state.get('last_total_rerender_ms')}ms"
                f" (filter {state.get('last_filter_ms')} · cascade {state.get('last_cascade_ms')}"
                f" · build {state.get('last_row_build_ms')} · apply {state.get('last_table_update_ms')}"
                f" · diag {state.get('last_diagnostics_ms')})"
                f" · write {((state.get('scan_status') or {}).get('last_result') or {}).get('write_fn_ms')}ms"
            ).classes("text-xs text-gray-500 font-mono")
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
        # PR R: cache the scan status here (once per snapshot apply) so the hot-path rerender never reads the
        # store; cancel any pending debounced control refresh — this full rebuild is authoritative.
        state["scan_status"] = engine.scan_status()
        state["pending_refresh"] = None
        rerender(force_diagnostics=True)
        state["flash_now"] = set()

    async def reload_data() -> None:
        bundle = await run.io_bound(_read_bundle, *_read_args())   # store I/O off the event loop
        _apply_bundle(bundle)

    def refresh_bounded_loss() -> None:
        """PR R scoped path: rebuild ONLY the bounded-loss tables from the cached `state["view"]` — re-slice
        by the rb band controls; no re-filter/re-rank of the full set, no store read, the other tables
        untouched. Used by the debounced rb-control handler and by the full rerender."""
        view = state.get("view") or []
        new_ids, chg = state.get("new_ids") or set(), state.get("changes") or {}
        flash = state.get("flash_now") or set()
        include_rb = rb_switch.value
        rbv = vm.risk_budget_view(
            view, max_loss_c=int(rb_max_loss.value or 0),
            min_ratio_tenths=round(float(rb_min_ratio.value or 0) * 10),
            min_outright_c=int(rb_min_outright.value or 0),
            max_spread_ratio_hundredths=round(float(rb_max_ratio.value or 0) * 100)) if include_rb else []
        vm.flag_peer_cheapness(rbv)        # PR F: stamp cheap_cost/cheap_ratio (same-sport peers); display-only
        rb_vert, rb_cal = vm.split_by_resolution(rbv)
        # PR E: the combined "All" table shows the full ranked set; the splits show each kind.
        rb_all.rows = [vm.risk_budget_row(o, new_ids, chg, flash) for o in rbv]
        rb_vertical.rows = [vm.risk_budget_row(o, new_ids, chg, flash) for o in rb_vert]
        rb_calendar.rows = [vm.risk_budget_row(o, new_ids, chg, flash) for o in rb_cal]
        rb_title.set_text(f"Bounded-Loss Bets — capped downside, convex upside ({len(rbv):,})")
        rb_all_title.set_text(f"All bounded-loss bets ({len(rbv):,})")
        rb_vert_title.set_text(f"Vertical — both legs resolve together ({len(rb_vert):,})")
        rb_cal_title.set_text(f"Calendar — legs resolve on different days ({len(rb_cal):,})")
        rb_expansion.set_visibility(include_rb)
        for _c in (rb_max_loss, rb_min_ratio, rb_min_outright, rb_max_ratio):
            _c.set_enabled(include_rb)

    def refresh_near_miss() -> None:
        """PR R scoped path: rebuild ONLY the overpriced-books (near-miss) table from the cached view."""
        view = state.get("view") or []
        new_ids, chg = state.get("new_ids") or set(), state.get("changes") or {}
        flash = state.get("flash_now") or set()
        include_nm = nm_switch.value
        nmv = vm.near_miss_view(view, max_over_c=int(nm_max_over.value or 0)) if include_nm else []
        nm_table.rows = [vm.near_miss_row(o, new_ids, chg, flash) for o in nmv]
        nm_title.set_text(f"Overpriced Books — flat guaranteed loss, watch-only ({len(nmv):,})")
        nm_expansion.set_visibility(include_nm)
        nm_max_over.set_enabled(include_nm)

    def refresh_no_structure() -> None:
        """Scoped path: rebuild ONLY the Cheap-NO-fades section from the cached view. Three settlement-LEVEL
        tables (Event / Tournament / Championship) or one combined 'All' table (the View toggle). 'Group by
        participant' overrides both → a level-agnostic ladder-summary table + cascade cards."""
        view = state.get("view") or []
        new_ids, chg = state.get("new_ids") or set(), state.get("changes") or {}
        flash = state.get("flash_now") or set()
        include_ns = ns_switch.value
        grouped = include_ns and ns_group.value
        ns_expansion.set_visibility(include_ns)
        for _c in (ns_kind, ns_max_loss, ns_max_buy_no, ns_group, ns_wide, ns_view):
            _c.set_enabled(include_ns)
        ns_sort.set_enabled(grouped)
        _grouped_only = (ns_summary_label, ns_summary_table, ns_summary_cap)
        _all_labels = (*ns_scope_labels.values(), ns_all_label, ns_excluded_label, ns_legacy_label, *_grouped_only)

        def _hide_all() -> None:
            for _t in (*_ns_tables, ns_summary_table):
                _t.rows = []
                _t.set_visibility(False)
            ns_cards.clear()
            for _l in _all_labels:
                _l.set_visibility(False)

        if not include_ns:
            _hide_all()
            ns_title.set_text("Cheap NO fades — bounded-loss NO anchor, watch-only (0)")
            return

        # Legacy snapshot (pre settlement-level taxonomy) → don't trust stale rows; prompt a rescan.
        if vm.no_scope_taxonomy_is_legacy(view):
            _hide_all()
            ns_legacy_label.set_text("This snapshot predates the Event / Tournament / Championship update "
                                     "— rescan (Scan now) to recategorise the cheap NO fades.")
            ns_legacy_label.set_visibility(True)
            ns_title.set_text("Cheap NO fades — rescan needed")
            return

        scoped = vm.no_structure_scoped_views(view, max_loss_c=int(ns_max_loss.value or 0),
                                              max_buy_no_c=int(ns_max_buy_no.value or 0), kind=ns_kind.value,
                                              good_quote_only=not ns_wide.value)
        excluded = int(scoped.get("_excluded_count") or 0)
        total = sum(len(scoped[s]) for s in ns_scope_tables)
        ns_title.set_text(f"Cheap NO fades — bounded-loss NO anchor, watch-only ({total:,})")
        frames_present = engine.frame_availability() == "present"

        def _prows_for(sport: str, pkey: str, tournament: str) -> list[dict[str, Any]]:
            return [r for r in engine.participant_contracts(sport, pkey)
                    if str(r.get("tournament") or "") == tournament]

        # Ladder-shape metric cells, merged onto each row by its (sport, participant_key, tournament) ladder.
        all_rows = [o for s in ns_scope_tables for o in scoped[s]]
        metrics_by_group = vm.ladder_metrics_view(all_rows, _prows_for) if frames_present else {}

        def _row(o: dict[str, Any]) -> dict[str, Any]:
            return {**vm.no_structure_row(o, new_ids, chg, flash),
                    **vm.ladder_metric_cells(metrics_by_group.get(vm.group_key_of(o))),
                    **vm.title_path_cells_for(o)}            # championship title-path (blank otherwise)

        ns_legacy_label.set_visibility(False)
        ns_cards.clear()
        if grouped:
            # Grouping overrides the level/All split → one participant-ladder summary + cascade cards.
            for _t in _ns_tables:
                _t.rows = []
                _t.set_visibility(False)
            for _l in (*ns_scope_labels.values(), ns_all_label):
                _l.set_visibility(False)
            ns_cards.set_visibility(True)
            for _x in _grouped_only:
                _x.set_visibility(True)
            if not frames_present:                            # fail-closed: no frames → no partial ladders
                ns_summary_table.rows = []
                ns_summary_table.set_visibility(False)
                ns_summary_cap.set_visibility(False)
                ns_summary_label.set_text("Grouped ladder — evidence frames not captured for this snapshot. "
                                          "Use a flat view (toggle off) or Scan now.")
                with ns_cards:
                    ui.label("Grouped ladder unavailable (no evidence frames).").classes("text-orange-700")
            else:
                cards = vm.no_fade_ladder_view(view, _prows_for, max_loss_c=int(ns_max_loss.value or 0),
                                               max_buy_no_c=int(ns_max_buy_no.value or 0), kind=ns_kind.value,
                                               good_quote_only=not ns_wide.value, sort=ns_sort.value)
                ns_summary_table.rows = [vm.ladder_summary_row(c) for c in cards]
                ns_summary_table.set_visibility(bool(cards))
                ns_summary_cap.set_visibility(bool(cards))
                ns_summary_label.set_text(f"Participant ladders · {len(cards):,} (sortable summary)")
                shown = cards[:_NO_FADE_LADDER_MAX_CARDS]
                with ns_cards:
                    if not shown:
                        ui.label("No cheap NO fades with a ladder rung in the current filters.").classes(
                            "text-gray-500")
                    for card in shown:
                        _render_fade_card(card)
                    if len(cards) > len(shown):
                        ui.label(f"Showing top {len(shown)} of {len(cards):,} ladders by "
                                 f"{('cascade upside' if ns_sort.value == 'cascade' else 'safest')} — narrow "
                                 "filters to see more.").classes("text-xs text-amber-700")
        else:
            # Flat: either the three level tables, or one combined All table.
            for _x in _grouped_only:
                _x.set_visibility(False)
            ns_summary_table.set_visibility(False)
            ns_cards.set_visibility(False)
            show_all = ns_view.value == "all"
            for scope, table in ns_scope_tables.items():
                label = ns_scope_labels[scope]
                if show_all:
                    table.rows = []
                    table.set_visibility(False)
                    label.set_visibility(False)
                else:
                    rows = scoped[scope]
                    table.rows = [_row(o) for o in rows]
                    table.set_visibility(bool(rows))
                    label.set_text(f"{scope.capitalize()} · {len(rows):,}" if rows
                                   else f"{scope.capitalize()} — none right now")
                    label.set_visibility(True)
            if show_all:
                ns_all_table.rows = [_row(o) for o in all_rows]
                ns_all_table.set_visibility(bool(all_rows))
                ns_all_label.set_text(f"All NO fades · {len(all_rows):,}" if all_rows
                                      else "All NO fades — none right now")
                ns_all_label.set_visibility(True)
            else:
                ns_all_table.rows = []
                ns_all_table.set_visibility(False)
                ns_all_label.set_visibility(False)

        ns_excluded_label.set_text(
            f"{excluded:,} NO-fade row(s) excluded from these tables because their settlement scope is "
            "legacy, unsupported, or unmapped." if excluded else "")
        ns_excluded_label.set_visibility(bool(excluded))

    def _render_fade_card(card: dict[str, Any]) -> None:
        """One participant's NO-fade ladder as a collapsible card (rungs broad→deep, components + score)."""
        def _f(v: Any) -> str:
            return "—" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))
        crows = []
        for r in card["rungs"]:
            crows.append({
                "rung": r["rung"], "reach_pct": _f(r["reach_pct"]),
                "buy_no": "0¢ — inspect quote" if r["zero_cost"] else _f(r["no_c"]),
                "max_win": _f(r["max_win"]),
                "leverage": "—" if r["leverage"] is None else f"{r['leverage']:g}×",
                "dominated": r["dominated"],
                "cascade": _f(r["cascade_score"]),
                "quote": r["quote"], "size": _f(r["size"]),
                "tag": "● cheap" if r["cheap"] else "",
            })
        title = f"{card['sport_label']} · {card['player'] or card['player_key']} — cascade {card['card_score']:g}"
        if card.get("implied_win_pct") is not None:
            title += f" · implied win {card['implied_win_pct']:g}%"
        if card.get("inverted"):
            title += " · ⚠ inverted ladder"
        with ui.expansion(title).classes("w-full border rounded"):
            ui.table(columns=_NO_FADE_LADDER_COLUMNS, rows=crows, row_key="rung").props(
                "dense").classes("w-full overflow-x-auto")
            ui.label("Cascade score is an ordinal longshot-upside score — NOT EV, probability, fair "
                     "value, or mispricing; a higher score usually means a LOWER implied chance. A single "
                     "NO collapses the whole ladder to no-win. Gross, top-of-book, uncalibrated; not an "
                     "edge.").classes("text-xs text-gray-500")

    def _set_freshness(text: str) -> None:
        """Set the freshness/scope banner only when its text actually changed — the 1s tick and every
        rerender call this, so the guard avoids a needless text push (Branch 2)."""
        if state.get("freshness_text") != text:
            freshness.set_text(text)
            state["freshness_text"] = text

    def _clear_selection() -> None:
        """A filter change removed the selected opportunity from the view: drop the highlight in every
        table and clear the now-stale detail surfaces (click-panel dialog only if it is open; the
        persistent Selected Detail section gets a truthful placeholder instead of yesterday's evidence)."""
        state["selected"] = None
        for t in _sel_tables:
            t.selected = []                      # same idiom as _on_select
        if dialog.value:
            dialog.close()
        detail_box.clear()
        with detail_box:
            ui.label("Selection cleared — the selected opportunity is no longer in the current view."
                     ).classes("text-sm text-gray-500")
        detail_expansion.close()

    def _apply_gated_sections() -> None:
        """Build + assign the toggle-gated tables (review / blocked / qualifier) from the cached view,
        SKIPPING hidden sections (Phase 1a). The default view shows only Actionable, so this avoids
        building the review/blocked/qualifier row-models (the bulk of the ~2k-row, ~5s build) that are
        never seen. Sets each section's header+table visibility. Reused by rerender() and the
        visibility-only section-toggle handler (Phase 1c)."""
        view = state.get("view") or []
        new_ids = state.get("new_ids") or set()
        chg = state.get("changes") or {}
        flash = state.get("flash_now") or set()
        ls = pos_framing_sw.value
        review.rows = ([vm.opp_row(o, new_ids, chg, flash, long_short=ls)
                        for o in view if o.get("bucket") == "review_signal"] if show_review_sw.value else [])
        blocked.rows = ([vm.opp_row(o, new_ids, chg, flash, long_short=ls)
                         for o in view if o.get("bucket") == "blocked"] if show_blocked_sw.value else [])
        if qs_switch.value:
            qs_opps = [o for o in view if o.get("bucket") == "qualifier_setup"]
            qs_table.rows = [vm.qualifier_row(o, new_ids, chg, flash,
                                              leg_lookup=_contract_lookup_for(o),
                                              comparator_contract=_comparator_contract_for(o))
                             for o in vm.order_qualifier_rows(qs_opps)]
        else:
            qs_table.rows = []
        for hdr, tbl, sw in ((blocked_hdr, blocked, show_blocked_sw),):
            hdr.set_visibility(sw.value)
            tbl.set_visibility(sw.value)
        # Review Required is now a collapsible expansion (switch-gated): toggle the whole expansion + count.
        review_expansion.set_visibility(show_review_sw.value)
        review_title.set_text(f"Review Required — settlement-dependent ({len(review.rows):,})")
        # Qualifier setups is now a collapsible expansion (switch-gated): toggle the whole expansion + count.
        qs_expansion.set_visibility(qs_switch.value)
        qs_title.set_text(
            f"Qualifier setups — World Cup group-stage ideas & signals ({len(qs_table.rows):,})")

    def _refresh_counts() -> None:
        """Update the per-bucket counts line from the full snapshot + current filters. Cheap O(n) filter —
        the expensive ~5s part was the row-model build, which a section toggle now skips (Phase 1c)."""
        opps = state.get("opps_list") or []
        counts_line.set_text(vm.bucket_counts_line(
            vm.bucket_counts(opps, _current_filters()),
            {"review_signal": show_review_sw.value, "blocked": show_blocked_sw.value,
             "risk_budget": rb_switch.value, "near_miss": nm_switch.value,
             "qualifier_setup": qs_switch.value, "no_structure": ns_switch.value}))

    def _on_section_toggle() -> None:
        """Phase 1c: a section show/hide toggle rebuilds ONLY the affected sections + counts from the cached
        view — no re-filter/re-rank and no actionable/liquidity/chips/diagnostics rebuild (the full
        rerender). Skips the ~5s build that made these toggles feel frozen."""
        if state.get("_suppress_cascade"):
            return
        _apply_gated_sections()        # review/blocked/qualifier: visibility + on-demand build
        refresh_bounded_loss()         # rb/nm/ns are scoped + self-gating (set their own visibility)
        refresh_near_miss()
        refresh_no_structure()
        _refresh_counts()

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
        _t_start = time.monotonic()                       # Branch 2: phase timing for Diagnostics
        filters = _current_filters()
        _t_filter = time.monotonic()
        view = vm.rank_opps(vm.filter_opps(opps, **filters), rank_sel.value)   # display-time re-sort, no rescan
        state["view"] = view      # PR R: cache so the scoped bounded-loss / near-miss refreshers can reuse it
        # Stale-selection guard: clear the highlight + detail surfaces when the selected opp left the
        # MEMBERSHIP-filtered view. Bucket-visibility toggles and rb/nm band thresholds do NOT clear —
        # the opp is still in scope, just in a hidden/narrowed section, so its detail stays valid.
        if vm.selection_left_view(state.get("selected"), view):
            _clear_selection()
        elif state.get("selected"):
            # Same opp still in view: re-point at the freshest dict so the rules/wording toggles
            # re-render current data after a snapshot advance (no UI push here).
            sid = state["selected"].get("opportunity_id")
            state["selected"] = state["opps"].get(sid, state["selected"])
        state["last_filter_ms"] = round((time.monotonic() - _t_filter) * 1000, 1)
        # Truthful empty state by scope (PR 26a): no-scan / scanning / scan-failed / no-opportunities /
        # filter-hid-all — or hidden when there's content to show. scan_status is cached (no hot-path store read).
        msg = vm.empty_state(cov=cov, total_opps=len(opps), shown_opps=len(view),
                             scan_status=state.get("scan_status"))
        empty.set_text(msg or "")
        empty.set_visibility(msg is not None)

        ls = pos_framing_sw.value      # Long/Short YES display wording (default off → Buy YES/Buy NO)
        _t_build = time.monotonic()    # build the always-visible row-models (Actionable + backlog)
        act_rows = [vm.opp_row(o, new_ids, chg, flash, long_short=ls) for o in view if o.get("bucket") == "actionable"]
        bl_rows = [vm.backlog_row(b, tz) for b in (state.get("backlog") or [])]
        ble_rows = [vm.backlog_event_row(b, tz) for b in (state.get("backlog_events") or [])]
        state["last_row_build_ms"] = round((time.monotonic() - _t_build) * 1000, 1)

        # Assign the built models to the Quasar tables. Gated sections (review/blocked/qualifier) are built
        # ONLY when their switch is on (Phase 1a, via _apply_gated_sections); the watchlist sections
        # (rb/nm/ns) are rebuilt via their scoped, self-gating refreshers.
        _t_apply = time.monotonic()
        actionable.rows = act_rows
        act_title.set_text(f"Actionable — executable gross edges ({len(act_rows):,})")
        _apply_gated_sections()
        refresh_bounded_loss()
        refresh_near_miss()
        refresh_no_structure()

        backlog.rows = bl_rows
        backlog_events_table.rows = ble_rows
        state["last_table_update_ms"] = round((time.monotonic() - _t_apply) * 1000, 1)

        # scope banner (with the PR 21a counters) + per-bucket counts + filter chips + URL state
        _set_freshness(vm.scope_banner(cov, tz))
        # Per-bucket counts (PR 4): computed from the FULL snapshot + current filters (in-memory; no store
        # read) so the numbers match the rendered tables + reflect "hidden by settings". Shared with the
        # Phase 1c section-toggle path via _refresh_counts.
        _refresh_counts()
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
        # Phase 0: stamp the render counters BEFORE the (heavy, optional) diagnostics build so the
        # Diagnostics panel reads THIS render's total — not the previous render's (the build>total mix that
        # made the old timings untrustworthy). Diagnostics is timed separately as `last_diagnostics_ms`.
        state["rerender_count"] = (state.get("rerender_count") or 0) + 1
        state["last_total_rerender_ms"] = round((time.monotonic() - _t_start) * 1000, 1)
        if force_diagnostics or diagnostics_expansion.value:   # heavy (store reads): snapshot change or open
            _t_diag = time.monotonic()
            render_diagnostics(view)
            state["last_diagnostics_ms"] = round((time.monotonic() - _t_diag) * 1000, 1)

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
        (show_blocked_sw, "Show the Blocked section"),
        (qs_switch, "Show the Qualifier setups section"), (clear_btn, "Clear all filters"),
        (rb_switch, "Show speculative bounded-loss structures"),
        (rb_max_loss, "Speculative max loss in cents"),
        (rb_min_ratio, "Speculative minimum upside-to-risk ratio"),
        (rb_min_outright, "Speculative minimum child display outright in cents"),
        (rb_max_ratio, "Speculative maximum child display spread-to-outright ratio"),
        (nm_switch, "Show overpriced books (near-miss)"), (nm_max_over, "Near-miss max overpay in cents"),
        (ns_switch, "Show cheap NO fades"), (ns_kind, "Cheap NO fade kind"),
        (ns_max_loss, "Cheap NO fade max loss in cents"), (ns_max_buy_no, "Cheap NO fade max Buy-NO cost in cents"),
        (ns_event_table, "Event cheap NO fades"), (ns_tournament_table, "Tournament cheap NO fades"),
        (ns_championship_table, "Championship cheap NO fades"), (ns_all_table, "All cheap NO fades"),
        (ns_view, "Cheap NO fades view (by level / all)"), (ns_summary_table, "NO-fade ladder summary"),
        (ns_expansion, "Cheap NO fades section"),
        (ns_group, "Group cheap NO fades by participant ladder"), (ns_sort, "NO-fade ladder sort"),
        (ns_wide, "Include wide-quote cheap NO fades"), (ns_cards, "NO-fade ladder cards"),
        (show_net_sw, "Show estimated net-of-fees columns"),
        (actionable, "Actionable opportunities"), (review, "Review-required opportunities"),
        (blocked, "Blocked opportunities"), (qs_table, "Qualifier setups"),
        (rb_all, "Bounded-loss bets (all)"),
        (rb_vertical, "Bounded-loss bets (vertical)"), (rb_calendar, "Bounded-loss bets (calendar)"),
        (rb_expansion, "Bounded-loss bets section"),
        (nm_table, "Overpriced books"), (nm_expansion, "Overpriced books section"),
        (backlog, "Recently-actionable backlog"),
        (backlog_events_table, "Durable 7-day backlog"), (backlog_events_cat, "Durable backlog category"),
        (detail_expansion, "Selected detail"), (diagnostics_expansion, "Diagnostics and debug"),
        (scanning_lbl, "Scan in progress indicator"),
    ):
        _el.props(f'aria-label="{_aria}"')

    scan_btn.on_click(do_scan)
    export_btn.on_click(do_export)
    _seed()        # set control values from the URL BEFORE binding handlers (so seeding fires no render)

    # PR R — coalesce a burst of control changes into ONE re-render after a short idle, and SCOPE the work so
    # a bounded-loss / near-miss control rebuilds only its own tables (reusing the cached view), never the
    # whole page. A single recurring tick timer (created below) fires the pending refresh past its deadline.
    def _request_refresh(kind: str) -> None:
        if state.get("_suppress_cascade"):
            return
        prev = state.get("pending_refresh")
        if prev is not None and prev[0] != kind:
            kind = "full"        # mixed scopes pending within one idle window -> just do a full refresh
        state["pending_refresh"] = (kind, time.monotonic() + config.UI_DEBOUNCE_SECONDS)

    def _debounce_tick() -> None:
        pending = state.get("pending_refresh")
        if not pending:
            return
        kind, deadline = pending
        if time.monotonic() < deadline:
            return               # still settling — wait for the idle window to elapse
        state["pending_refresh"] = None
        if kind == "bounded_loss":
            refresh_bounded_loss()
        elif kind == "near_miss":
            refresh_near_miss()
        elif kind == "no_structure":
            refresh_no_structure()
        else:
            rerender()

    # Filter / display controls re-render PURELY in-memory from the cached snapshot (no store, no fetch). The
    # handler no-ops while `_suppress_cascade` is set, so the programmatic prune inside _refresh_cascade never
    # re-renders mid-cascade. Single-interaction controls (selects/switches) fire once → full re-render now.
    # The NUMBER inputs fire per keystroke/spin → DEBOUNCED, and the bounded-loss/near-miss bands are SCOPED
    # to their own tables (a Max-loss change no longer rebuilds the other tables or reads the store).
    for ctrl in (tz_select, rank_sel, show_ids, participant_sel, active_sw):
        ctrl.on_value_change(lambda _=None: None if state.get("_suppress_cascade") else rerender())
    # Phase 1c: section show/hide toggles rebuild ONLY their own section + counts from the cached view
    # (cheap), never the full rerender — so toggling Review/Blocked/Qualifier/RB/NM/NO no longer pays the
    # multi-second row-model build.
    for ctrl in (show_review_sw, show_blocked_sw, qs_switch, rb_switch, nm_switch, ns_switch):
        ctrl.on_value_change(lambda _=None: _on_section_toggle())
    min_size_in.on_value_change(lambda _=None: _request_refresh("full"))        # membership filter → view
    for ctrl in (rb_max_loss, rb_min_ratio, rb_min_outright, rb_max_ratio):
        ctrl.on_value_change(lambda _=None: _request_refresh("bounded_loss"))    # only the bounded-loss tables
    nm_max_over.on_value_change(lambda _=None: _request_refresh("near_miss"))     # only the near-miss table
    for ctrl in (ns_kind, ns_max_loss, ns_max_buy_no, ns_group, ns_sort, ns_wide, ns_view):
        ctrl.on_value_change(lambda _=None: _request_refresh("no_structure"))     # only the cheap-NO-fades section

    # Sport / Tournament are the cascade drivers: changing one re-narrows the downstream option lists
    # (and prunes now-invalid picks) BEFORE a single rerender. participant_sel (the leaf) drives no
    # further cascade, so it stays in the generic loop above.
    def _on_membership_change() -> None:
        if state.get("_suppress_cascade"):
            return
        _t = time.monotonic()
        _refresh_cascade()
        state["last_cascade_ms"] = round((time.monotonic() - _t) * 1000, 1)
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
        # Guarded so an unchanged string pushes nothing (Branch 2).
        _set_freshness(vm.scope_banner(state.get("cov"), tz_select.value))
        # Scan-in-progress indicator: engine.scan_status() is an in-process dict copy (no store/network),
        # safe at 1 Hz. Push only on transition; refresh the cached scan_status on transition too, so the
        # empty-state "Scanning..." branch (vm.empty_state) is live instead of one-snapshot stale.
        st = engine.scan_status()
        in_prog = (st or {}).get("status") == "in_progress"
        # Phase 2: show a live budget-cooldown countdown so a stalled auto-scan is legible, not a silently
        # stale snapshot. Scanning takes priority; then a cooling-down countdown; else blank.
        cooldown = round((st or {}).get("cooldown_seconds_left") or 0.0)
        if in_prog:
            label = "Scanning — new data shortly…"
        elif cooldown > 0:
            label = f"Auto-scan cooling down ({cooldown}s) — data may be stale; use Scan now to force."
        else:
            label = ""
        if label != state.get("scan_indicator_text"):   # push on any text change (incl. each countdown tick)
            state["scan_indicator_text"] = label
            scanning_lbl.set_text(label)
        if in_prog != state.get("scan_indicator"):       # refresh cached scan_status on a scan-state change
            state["scan_indicator"] = in_prog
            state["scan_status"] = st

    tick_age()     # paint the scan indicator on first load if a scan is already in flight (scheduler / other viewer)
    ui.timer(config.UI_POLL_SECONDS, poll)        # snapshot-change watcher (cheap; reloads only on a new id)
    ui.timer(1.0, tick_age)
    ui.timer(config.UI_DEBOUNCE_TICK_SECONDS, _debounce_tick)   # PR R: fire coalesced/scoped control refreshes
