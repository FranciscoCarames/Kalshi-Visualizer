"""Terminal Pro UI — the redesigned NiceGUI workstation (P1 shell, route `/terminal`).

This is the first phased slice of the owner-approved "Terminal Pro" rebuild (spike
`.kss/spikes/20260611-terminal-pro-mockup/README.md`, mockup `ui-mockup-7-terminal-pro.html`):
a Bloomberg-identity, docked trading-desk layout over the SAME read-only engine the legacy
dashboard uses. It is mounted ALONGSIDE the legacy `@ui.page('/')` dashboard (which stays the
default at `/`) so nothing regresses and the owner can compare looks before it is promoted.

P1 scope (this file): the terminal SHELL from the real engine —
  • command bar (function-code tabs OPP/RES/OPS + search accelerator + live clock),
  • always-on status/trust strip (scan age/coverage) + the gross/read-only disclaimer,
  • landing tiles (Act-now / Review / Blocked / Speculative / Cheap-NO) wired to real counts,
  • the BLOTTER: one ranked grid with a bucket switch + a LENS switcher (the 5 real RANK_MODES),
    fed by `engine.latest_opportunities` → `viewmodel.filter_opps` → `viewmodel.rank_opps`,
  • a lightweight DES trade-card on row-select (legs / quote / tradable / caveat).

Deferred to later phases (kept out of P1 on purpose): the full 9-dim DES confidence matrix &
EvidencePack (P2), the MD depth ladder (P3 — gated on the orderbook-depth probe R1), and the
RES/OPS surfaces + alerts (P4). Every model/EV number stays DISPLAY-ONLY — this page never
classifies, buckets, or ranks on anything the engine didn't already decide; it only re-presents
`scanner.unified_opportunities`. Pure cores are reused, never reimplemented:
`webui.viewmodel` (filter/rank/rows/legs) and `webui.engine` (in-process store reads).
"""
from __future__ import annotations

import time
from typing import Any

from nicegui import ui

import config
from webui import engine, viewmodel

# --- the amber-CRT terminal skin (R2 feasibility: prove NiceGUI/Quasar can carry the aesthetic) --------
# Scoped under `.tp-root` so it never bleeds into the legacy dashboard at `/`. Quasar dark mode supplies
# the base; this layers the Bloomberg amber-on-black identity, a monospace grid, and the bucket accents.
_TP_CSS = """
.tp-root { background:#070707; color:#ffb000; font-family:"Cascadia Mono","Consolas",ui-monospace,monospace;
           min-height:100vh; letter-spacing:.2px; }
.tp-root .tp-bar { background:#101008; border-bottom:1px solid #3a2e00; }
.tp-root .tp-fkey { color:#070707; background:#ffb000; font-weight:700; padding:1px 8px; border-radius:2px; }
.tp-root .tp-fkey-off { color:#7a6200; border:1px solid #3a2e00; padding:1px 8px; border-radius:2px; }
.tp-root .tp-strip { background:#0c0c08; border-top:1px solid #2a2200; border-bottom:1px solid #2a2200;
                     font-size:12px; }
.tp-root .tp-disc { color:#8a6d00; font-size:11px; letter-spacing:1px; }
.tp-root .tp-tile { background:#0e0e0a; border:1px solid #2a2200; border-radius:3px; min-width:96px;
                    cursor:pointer; transition:border-color .12s,background .12s; }
.tp-root .tp-tile:hover { border-color:#ffb000; background:#13130c; }
.tp-root .tp-tile.sel { border-color:#ffb000; background:#1a1408; }
.tp-root .tp-tile .v { font-size:22px; font-weight:700; line-height:1; }
.tp-root .tp-tile .k { font-size:10px; color:#8a6d00; letter-spacing:1px; }
.tp-root .tp-amber { color:#ffb000; } .tp-root .tp-green { color:#33ff66; }
.tp-root .tp-red { color:#ff4040; } .tp-root .tp-dim { color:#7a6200; }
.tp-root .tp-card { background:#0c0c08; border:1px solid #3a2e00; border-radius:3px; }
.tp-root .q-table__container { background:transparent; }
.tp-root .q-table tbody td, .tp-root .q-table thead th { font-family:inherit; font-size:12px; }
.tp-root .q-table thead th { color:#8a6d00; text-transform:uppercase; letter-spacing:1px; }
.tp-root .tp-blotter tbody tr.selected { background:#1a1408 !important; }
.tp-root .tp-blotter tbody tr.selected td:first-child { box-shadow:inset 3px 0 0 0 #ffb000; }
.tp-root input { color:#ffb000 !important; }
.tp-root .tp-chip { border:1px solid #3a2e00; border-radius:2px; padding:1px 6px; }
.tp-root .tp-klabel { font-size:9px; letter-spacing:1px; color:#7a6200; }
.tp-root .tp-violet { color:#c084fc; }
.tp-root .tp-ladder { border:1px solid #2a2200; border-radius:2px; padding:3px 6px; }
.tp-root .tp-ladder .ask { background:rgba(255,64,64,.06); }
.tp-root .tp-ladder .bid { background:rgba(51,255,102,.06); }
.tp-root .tp-mono-c { font-variant-numeric:tabular-nums; }
"""

# Blotter columns — a focused subset of the legacy `_OPP_COLUMNS`, fed by the same `viewmodel.opp_row`
# fields (no net-of-fees columns here; those live behind the DES card). "new" is a NEW-this-scan badge.
_BLOTTER_COLUMNS = [
    {"name": "new", "label": "", "field": "new", "align": "center"},
    {"name": "sport", "label": "Sport", "field": "sport", "align": "center", "sortable": True},
    {"name": "name", "label": "Participant / match", "field": "name", "align": "left", "sortable": True},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
    {"name": "action", "label": "Action plan", "field": "action", "align": "left"},
    {"name": "edge", "label": "Edge ¢", "field": "edge", "align": "right", "sortable": True},
    {"name": "roi", "label": "ROI %", "field": "roi", "align": "right", "sortable": True},
    {"name": "units", "label": "Units", "field": "units", "align": "right", "sortable": True},
    {"name": "profit", "label": "Max $", "field": "profit", "align": "right", "sortable": True},
    {"name": "tradable", "label": "Tradable", "field": "tradable", "align": "center"},
]

_LEG_COLUMNS = [
    {"name": "leg", "label": "Leg", "field": "leg", "align": "left"},
    {"name": "side", "label": "Side", "field": "side", "align": "left"},
    {"name": "market", "label": "Market", "field": "market", "align": "left"},
    {"name": "price", "label": "Price", "field": "price", "align": "right"},
    {"name": "size", "label": "Size", "field": "size", "align": "right"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "quote_quality", "label": "Quote", "field": "quote_quality", "align": "center"},
]

# The blotter buckets, in display order, with their tile label + accent. Each maps 1:1 to a `bucket`
# the scanner already assigned — this page never re-buckets, it only routes rows the engine decided.
_BUCKETS = [
    ("actionable", "ACT-NOW", "tp-green"),
    ("review_signal", "REVIEW", "tp-amber"),
    ("blocked", "BLOCKED", "tp-red"),
    ("risk_budget", "SPEC", "tp-amber"),
    ("no_structure", "CHEAP-NO", "tp-amber"),
]
_DISCLAIMER = "GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS"
_BUCKET_LABEL = {b: lbl for b, lbl, _ in _BUCKETS}
# Severity → accent for the DES caveat badges (mirrors viewmodel.severity_badges' severity keys).
_SEV_CLASS = {"blocker": "tp-red", "review_required": "tp-amber", "advisory": "tp-dim", "info": "tp-dim"}


def _num(x: Any) -> float | None:
    """The value as a float, or None for None/NaN/non-numeric — so a missing field renders '—', never a crash."""
    return x if isinstance(x, (int, float)) and x == x else None


def _quote_css(qq: str) -> str:
    if qq in ("Tight", "OK"):
        return "tp-green"
    if qq in ("No quote", "Crossed", "One-sided"):
        return "tp-red"
    return "tp-amber"


def _fail_line(e: Any) -> str:
    """One concise red line per scan failure for the OPS surface. build_failures emits dicts
    ({sport, series, error}); the raw error carries a multi-line traceback, so show the location + a
    truncated single-line reason, not the dump. A plain string passes through unchanged."""
    if isinstance(e, dict):
        loc = " · ".join(str(e[k]) for k in ("series", "sport") if e.get(k)) or "?"
        err = str(e.get("error") or "").replace("\n", " ")
        return f"{loc}: {err[:120] + '…' if len(err) > 120 else err}"
    return str(e)


def _contract_lookup(opp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """ticker -> stored contract row for the selected opportunity's legs, so `leg_rows` can stamp each
    leg's real status + quote_quality (P2 quote evidence). Reuses `engine.contract_by_ticker` against the
    latest snapshot — no live fetch. Market tickers are globally unique, so the sport is only a hint."""
    sport = opp.get("sport") or None
    tickers = {str(leg.get("ticker")) for leg in (opp.get("legs") or []) if leg.get("ticker")}
    tickers |= {str(opp.get(k)) for k in ("ticker_1", "ticker_2") if opp.get(k)}
    out: dict[str, dict[str, Any]] = {}
    for t in tickers:
        row = engine.contract_by_ticker(t, sport)
        if row:
            out[t] = row
    return out


def _depth_preview(opp: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-leg TOP-OF-BOOK depth preview (P3) — the single firm level each side from the stored contract
    row. This is DELIBERATELY not a full DOM: Kalshi orderbook depth is an unproven data source (spike
    R1), so the page shows only the firm touch and says so. Pure (no engine/UI) → unit-testable.

    Each entry: market label, whether the YES book is genuinely two-sided (firm bid>0 & ask<100 & bid<=ask
    — never the empty 0/100 book), the YES bid/ask + sizes, the Buy-NO ask (the real `no_ask_c`, else the
    documented `100 − yes_bid_c` fallback) whose tradable size is `yes_bid_size` (Kalshi exposes no NO-side
    size), and last / spread / volume / open-interest / quote-quality."""
    legs = opp.get("legs") or []
    tickers = [str(leg.get("ticker")) for leg in legs if leg.get("ticker")] or \
              [str(opp.get(k)) for k in ("ticker_1", "ticker_2") if opp.get(k)]
    out: list[dict[str, Any]] = []
    for tkr in tickers:
        c = lookup.get(tkr)
        if not c:
            out.append({"market": tkr, "two_sided": False, "unavailable": True})
            continue
        bid_c, ask_c = _num(c.get("yes_bid_c")), _num(c.get("yes_ask_c"))
        no_ask = _num(c.get("no_ask_c"))
        if no_ask is None and bid_c is not None:
            no_ask = 100 - bid_c                          # documented Buy-NO fallback (no NO-side ask)
        two_sided = (bid_c is not None and ask_c is not None and bid_c > 0 and ask_c < 100 and bid_c <= ask_c)
        out.append({
            "market": c.get("contract") or c.get("market_ticker") or tkr,
            "two_sided": two_sided, "unavailable": False,
            "bid_c": bid_c, "ask_c": ask_c,
            "bid_size": _num(c.get("yes_bid_size")), "ask_size": _num(c.get("yes_ask_size")),
            "no_ask_c": no_ask, "no_size": _num(c.get("yes_bid_size")),  # Buy-NO size = yes_bid_size
            "spread_c": _num(c.get("spread_cents")), "last_c": _num(c.get("last_c")),
            "volume": _num(c.get("volume")), "open_interest": _num(c.get("open_interest")),
            "quote_quality": c.get("quote_quality") or "",
        })
    return out


def _confidence_signals(opp: dict[str, Any],
                        lookup: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    """REAL trust signals from fields that actually exist — (label, value, css). This is DELIBERATELY not
    the mockup's fabricated 9-dim 0-100 confidence matrix (roadmap-future): the page only surfaces signals
    the engine genuinely produces — quote quality, identity-mapping confidence, tradability, settlement."""
    sig: list[tuple[str, str, str]] = []
    qq = opp.get("quote_quality")
    if qq:
        sig.append(("QUOTE", str(qq), _quote_css(str(qq))))
    mc = opp.get("mapping_confidence") or next(
        (r.get("mapping_confidence") for r in lookup.values() if r.get("mapping_confidence")), None)
    if mc:
        sig.append(("IDENTITY", str(mc), "tp-green" if mc == "high" else "tp-amber"))
    tn = opp.get("tradable_now")
    if tn:
        sig.append(("TRADABLE", str(tn), "tp-green" if str(tn) == "Yes" else "tp-amber"))
    rf = str(opp.get("rule_flag") or "")
    if rf in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH") or str(tn) == "Review rules":
        sig.append(("SETTLEMENT", "review", "tp-amber"))
    return sig


def _rows_for(opps: list[dict[str, Any]], bucket: str, new_ids: set[str],
              lens: str) -> list[dict[str, Any]]:
    """Ranked display rows for one bucket: select by the scanner's own `bucket`, rank by `lens`
    (a real `RANK_MODES` key), then map through the shared `viewmodel.opp_row`. Pure re-presentation."""
    in_bucket = [o for o in opps if o.get("bucket") == bucket]
    ranked = viewmodel.rank_opps(in_bucket, lens)
    rows = []
    for o in ranked:
        row = viewmodel.opp_row(o, new_ids)
        row["new"] = "● NEW" if row.get("new") else ""   # raw bool would render as the literal "false"
        rows.append(row)
    return rows


@ui.page("/terminal")
def terminal() -> None:
    ui.add_head_html(f"<style>{_TP_CSS}</style>")
    ui.dark_mode(value=True)            # terminal is dark-only; amber skin assumes a black base
    state: dict[str, Any] = {"opps": [], "by_id": {}, "new_ids": set(), "bucket": "actionable",
                             "lens": viewmodel.RANK_MODE_DEFAULT, "search": "",
                             "rendered_snapshot_id": "__unseeded__", "tiles": {},
                             # DES card: $1 (per-contract ¢, canonical) ⇄ $100 (dollars per 100-contract
                             # lot) basis toggle, and the currently-inspected opp (so the toggle re-renders).
                             "basis": 1, "sel_opp": None,
                             # P4: the active function-code surface — OPP (opportunities) / RES (research) /
                             # OPS (operations & data health) / ALRT (trusted-state alerts).
                             "surface": "OPP"}

    root = ui.column().classes("tp-root w-full gap-0 p-0")
    with root:
        # --- command bar: brand · clickable function-code surface tabs · search · live clock -------------
        fkeys: dict[str, Any] = {}
        with ui.row().classes("tp-bar w-full items-center px-3 py-1 gap-4"):
            ui.label("KALSHI TERMINAL PRO").classes("tp-amber font-bold")
            with ui.row().classes("items-center gap-1"):
                for _name in ("OPP", "RES", "OPS", "ALRT"):
                    fk = ui.label(_name).classes("tp-fkey-off cursor-pointer")
                    fk.on("click", lambda n=_name: set_surface(n))
                    fkeys[_name] = fk
            search = ui.input(placeholder="> filter participant / match").props(
                "dense dark borderless").classes("flex-grow")
            clock = ui.label("").classes("tp-green")

        # --- status / trust strip + disclaimer (always visible across every surface) ---------------------
        with ui.column().classes("tp-strip w-full px-3 py-1 gap-0"):
            status = ui.label("").classes("tp-dim")
            ui.label(_DISCLAIMER).classes("tp-disc")

        # --- OPP surface: landing tiles + blotter/DES workspace ------------------------------------------
        opp_surface = ui.column().classes("w-full gap-0 p-0")
        with opp_surface:
            tiles_row = ui.row().classes("w-full px-3 py-2 gap-2")   # clickable bucket switch
            with ui.row().classes("w-full px-3 pb-3 gap-3 no-wrap items-start"):
                with ui.column().classes("gap-2").style("flex:1 1 0; min-width:0"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label("BLOTTER").classes("tp-dim text-xs")
                        lens = ui.toggle(viewmodel.RANK_MODES, value=state["lens"]).props(
                            "dense no-caps").classes("tp-amber")
                        ui.label("lens").classes("tp-dim text-xs")
                    blotter = ui.table(columns=_BLOTTER_COLUMNS, rows=[], row_key="opportunity_id",
                                       selection="single", pagination=20).props(
                        "dense flat dark").classes("w-full tp-blotter")
                card = ui.card().classes("tp-card p-3").style("flex:0 0 380px; min-width:340px")

        # --- RES / OPS / ALRT surfaces — rebuilt on demand from the real engine (hidden until selected) --
        res_surface = ui.column().classes("w-full px-3 py-2 gap-2")
        ops_surface = ui.column().classes("w-full px-3 py-2 gap-2")
        alrt_surface = ui.column().classes("w-full px-3 py-2 gap-2")

    # ---- rendering -----------------------------------------------------------------------------------
    def _render_book(bk: dict[str, Any]) -> None:
        """One leg's top-of-book ladder: ask above bid (DOM-style) but a SINGLE firm level each side — the
        honest top-of-book preview, never a synthesised multi-level depth (spike R1). Prices stay in ¢
        (market prices, not subject to the $1/$100 basis toggle)."""
        def c(v: Any) -> str:
            n = _num(v)
            return "—" if n is None else f"{int(round(n))}¢"

        def sz(v: Any) -> str:
            n = _num(v)
            return "—" if n is None else str(int(n))

        def cnt(v: Any) -> str:
            n = _num(v)
            return "—" if n is None else f"{int(n):,}"

        with ui.column().classes("tp-ladder w-full gap-0 mt-1"):
            with ui.row().classes("w-full justify-between no-wrap"):
                ui.label(bk.get("market") or "—").classes("tp-amber text-xs")
                ui.label(bk.get("quote_quality") or "").classes("tp-dim text-xs")
            if bk.get("unavailable"):
                ui.label("Not in snapshot — no book.").classes("tp-dim text-xs")
                return
            if bk.get("two_sided"):
                with ui.row().classes("ask w-full justify-between no-wrap px-1"):
                    ui.label("ASK").classes("tp-dim text-xs")
                    ui.label(c(bk.get("ask_c"))).classes("tp-red text-xs tp-mono-c")
                    ui.label(f"×{sz(bk.get('ask_size'))}").classes("tp-dim text-xs")
                ui.label(f"spread {c(bk.get('spread_c'))}").classes("tp-dim text-xs w-full text-center")
                with ui.row().classes("bid w-full justify-between no-wrap px-1"):
                    ui.label("BID").classes("tp-dim text-xs")
                    ui.label(c(bk.get("bid_c"))).classes("tp-green text-xs tp-mono-c")
                    ui.label(f"×{sz(bk.get('bid_size'))}").classes("tp-dim text-xs")
            else:
                ui.label("No firm two-sided quote (empty / one-sided book).").classes("tp-amber text-xs")
            ui.label(f"Buy NO {c(bk.get('no_ask_c'))} ×{sz(bk.get('no_size'))}  ·  "
                     f"last {c(bk.get('last_c'))} · vol {cnt(bk.get('volume'))} · "
                     f"OI {cnt(bk.get('open_interest'))}").classes("tp-dim text-xs")

    def on_basis(e: Any) -> None:
        state["basis"] = e.value or 1
        render_des(state["sel_opp"])

    def render_des(opp: dict[str, Any] | None) -> None:
        card.clear()
        state["sel_opp"] = opp
        with card:
            if not opp:
                ui.label("DES — select a row").classes("tp-dim text-xs")
                ui.label("Trade card: legs · quote · confidence · evidence").classes("tp-dim text-xs")
                return
            m = state["basis"]

            def cv(c: Any) -> str:                       # per-contract ¢ ($1) ⇄ $/100-lot ($100), see mockup
                n = _num(c)
                return "—" if n is None else (f"${n:.2f}" if m == 100 else f"{int(round(n))}¢")

            lookup = _contract_lookup(opp)
            # header: bucket badge + name + the $1/$100 basis toggle
            with ui.row().classes("items-center justify-between w-full no-wrap"):
                with ui.row().classes("items-center gap-2 min-w-0"):
                    ui.label(_BUCKET_LABEL.get(opp.get("bucket"), str(opp.get("bucket") or "").upper())).classes(
                        "tp-fkey text-xs")
                    ui.label(opp.get("name") or "—").classes("tp-amber font-bold")
                ui.toggle({1: "$1", 100: "$100"}, value=m, on_change=on_basis).props(
                    "dense no-caps").classes("text-xs")
            ui.label(" · ".join(p for p in (opp.get("detail"), opp.get("relationship_type")) if p)).classes(
                "tp-dim text-xs")
            ui.label(viewmodel.action_plan_summary(opp).get("summary") or "").classes("tp-green text-xs mt-1")

            # economics — basis-aware KV grid (cents fields go through cv; ROI/units/$ profit are fixed-unit)
            kv = [("COST", cv(opp.get("cost_c"))), ("FLOOR", cv(opp.get("payout_floor_c"))),
                  ("EDGE", cv(opp.get("exec_gap_c"))),
                  ("ROI", "—" if _num(opp.get("roi_pct")) is None else f"{opp.get('roi_pct')}%"),
                  ("UNITS", "—" if _num(opp.get("exec_min_size")) is None else str(int(opp.get("exec_min_size")))),
                  ("MAX $", "—" if _num(opp.get("exec_max_profit_dollars")) is None
                   else f"${opp.get('exec_max_profit_dollars')}")]
            if opp.get("bucket") == "risk_budget":
                wc, bc = _num(opp.get("worst_case_profit_c")), _num(opp.get("best_case_profit_c"))
                kv += [("MAX LOSS", cv(None if wc is None else -wc)), ("MAX GAIN", cv(bc))]
            with ui.row().classes("w-full flex-wrap gap-x-5 gap-y-1 mt-2"):
                for k, v in kv:
                    with ui.column().classes("gap-0"):
                        ui.label(k).classes("tp-klabel")
                        ui.label(v).classes("tp-amber text-xs")

            # confidence signals — REAL fields only (no fabricated 9-dim matrix)
            sig = _confidence_signals(opp, lookup)
            if sig:
                with ui.row().classes("w-full flex-wrap gap-2 mt-2"):
                    for label, val, css in sig:
                        with ui.row().classes("tp-chip items-center gap-1"):
                            ui.label(label).classes("tp-klabel")
                            ui.label(val).classes(f"{css} text-xs")

            # legs with real per-leg quote evidence (status + quote_quality from the contract lookup)
            legs = viewmodel.leg_rows(opp, lookup)
            if legs:
                ui.label("LEGS").classes("tp-klabel mt-2")
                ui.table(columns=_LEG_COLUMNS, rows=legs, row_key="leg").props(
                    "dense flat dark").classes("w-full")

            # MD — top-of-book depth PREVIEW (P3). Read-only, single firm level each side, not a full DOM.
            books = _depth_preview(opp, lookup)
            if books:
                ui.label("MD — TOP-OF-BOOK DEPTH PREVIEW").classes("tp-klabel mt-2")
                ui.label("READ-ONLY DEPTH VIEW — NO ORDERS · single firm level each side, "
                         "not full orderbook depth").classes("tp-disc")
                for bk in books:
                    _render_book(bk)

            # caveat badges (severity-coloured)
            for b in viewmodel.severity_badges(opp):
                ui.label(f"{b['label']}: {b['tooltip']}").classes(
                    f"{_SEV_CLASS.get(b['severity'], 'tp-dim')} text-xs mt-1")

            # the EvidencePack — the full pure explanation (skip line 0, the sport·name header already shown)
            with ui.expansion("EVIDENCE").props("dense dark").classes("w-full mt-1"):
                for line in viewmodel.explanation_lines(opp)[1:]:
                    ui.label(line).classes("tp-dim text-xs")

    def render_blotter() -> None:
        opps = viewmodel.filter_opps(state["opps"], participant=state["search"]) \
            if state["search"] else state["opps"]
        blotter.rows = _rows_for(opps, state["bucket"], state["new_ids"], state["lens"])
        blotter.update()
        render_des(None)

    def render_tiles() -> None:
        tiles_row.clear()
        counts = viewmodel.bucket_counts(state["opps"])
        with tiles_row:
            for bucket, label, accent in _BUCKETS:
                shown = counts.get(bucket, {}).get("total", 0)
                sel = "sel" if bucket == state["bucket"] else ""
                tile = ui.column().classes(f"tp-tile {sel} items-center justify-center px-3 py-2")
                with tile:
                    ui.label(str(shown)).classes(f"v {accent}")
                    ui.label(label).classes("k")
                tile.on("click", lambda b=bucket: set_bucket(b))

    def set_bucket(bucket: str) -> None:
        state["bucket"] = bucket
        render_tiles()
        render_blotter()

    def on_lens(e: Any) -> None:
        state["lens"] = e.value or viewmodel.RANK_MODE_DEFAULT
        render_blotter()

    def on_search(e: Any) -> None:
        state["search"] = (e.value or "").strip()
        render_blotter()

    def on_select(e: Any) -> None:
        sel = blotter.selected
        opp = state["by_id"].get(sel[0]["opportunity_id"]) if sel else None
        render_des(opp)

    def on_row_click(e: Any) -> None:
        # Quasar @row-click emits (evt, row, index) — terminals expect click-anywhere-to-inspect, so
        # populate the DES card straight from the clicked row without waiting on the checkbox.
        row = e.args[1] if isinstance(e.args, list) and len(e.args) > 1 else None
        opp = state["by_id"].get(row.get("opportunity_id")) if isinstance(row, dict) else None
        if opp:
            render_des(opp)

    lens.on_value_change(on_lens)
    search.on_value_change(on_search)
    blotter.on_select(on_select)
    blotter.on("rowClick", on_row_click)

    # ---- P4 surfaces: RES (research) / OPS (operations) / ALRT (alerts) ------------------------------
    def _kv_block(title: str, pairs: list[tuple[str, Any]]) -> None:
        with ui.column().classes("gap-1").style("min-width:230px"):
            ui.label(title).classes("tp-klabel")
            for k, v in pairs:
                with ui.row().classes("gap-2 text-xs no-wrap"):
                    ui.label(k).classes("tp-dim").style("min-width:160px")
                    ui.label("—" if v is None else str(v)).classes("tp-amber")

    def _list_block(title: str, items: list[str]) -> None:
        with ui.column().classes("gap-1").style("min-width:240px"):
            ui.label(title).classes("tp-klabel")
            if not items:
                ui.label("—").classes("tp-dim text-xs")
            for it in items:
                ui.label(it).classes("tp-amber text-xs")

    def render_ops() -> None:
        """Operations & data-health surface — the §9.1 Operations/Diagnostics surface, straight from the
        real observability accessors (coverage / metrics / failure lists / category breakdown). No fetch."""
        ops_surface.clear()
        cov, met, fail = engine.coverage(), engine.metrics(), engine.diagnostics()
        cat, frames = engine.category_breakdown(), engine.frame_availability()
        with ops_surface:
            ui.label("OPS — operations & data health").classes("tp-amber font-bold")
            with ui.row().classes("w-full flex-wrap gap-8 items-start mt-1"):
                _kv_block("SCAN HEALTH", [
                    ("Snapshot id", cov.get("snapshot_id")), ("Data age (s)", cov.get("data_age_seconds")),
                    ("Stale", cov.get("stale")), ("Scan status", met.get("scan_status")),
                    ("Last scan error", met.get("last_scan_error") or "—"),
                    ("Live viewers", met.get("viewer_count")), ("Evidence frames", frames)])
                _kv_block("COVERAGE", [
                    ("Series scanned", cov.get("scanned")), ("Series loaded", cov.get("loaded")),
                    ("Series failed", cov.get("failed")), ("Excluded", cov.get("excluded")),
                    ("Contracts scanned", cov.get("contracts_scanned")),
                    ("Checks tested", cov.get("checks_tested")),
                    ("Kalshi requests", cov.get("kalshi_requests")),
                    ("Retry backoffs", cov.get("retry_count")),
                    ("Backoff seconds", cov.get("backoff_seconds_total"))])
                _kv_block("CONTRACT UNIVERSE", [
                    ("Contracts total", cat.get("total")), ("Laddered", cat.get("laddered")),
                    ("Non-laddered", cat.get("non_laddered")),
                    ("Low-confidence id", cat.get("low_confidence")),
                    ("Unsupported (UNKNOWN)", cat.get("unsupported"))])
            se, ser = fail.get("sport_errors") or [], fail.get("series_errors") or []
            ui.label("FAILURES").classes("tp-klabel mt-2")
            if not se and not ser:
                ui.label("No sport/series errors in the latest scan.").classes("tp-green text-xs")
            for e in se + ser:
                ui.label(_fail_line(e)).classes("tp-red text-xs")

    def render_research() -> None:
        """Research surface — DISPLAY-ONLY market telemetry + contract-universe composition, kept strictly
        OFF the executable blotter (spike G3). Violet + a "research — not a trade" banner. Deeper §5
        analytics (distributions / calibration / backtests / model lenses) are roadmap-future, stated as such
        rather than faked."""
        res_surface.clear()
        liq, cat = viewmodel.liquidity_panel(engine.all_contracts()), engine.category_breakdown()
        with res_surface:
            with ui.row().classes("items-center gap-2"):
                ui.label("RES — research lab").classes("tp-violet font-bold")
                ui.label("research — not a trade").classes("tp-violet text-xs tp-chip")
            ui.label("Display-only market telemetry & contract-universe composition — NOT an opportunity "
                     "signal. Deeper §5 analytics (distributions, calibration, backtests, model lenses) "
                     "are roadmap-future.").classes("tp-dim text-xs")
            with ui.row().classes("w-full flex-wrap gap-8 items-start mt-2"):
                _list_block("MOST LIQUID SPORTS",
                            [f"{lab} · depth {d}" for lab, d, *_ in liq.get("top_sports", [])])
                _list_block("MOST LIQUID CONTRACTS",
                            [f"{lab} · depth {d} · {s}¢" for lab, d, s in liq.get("top_contracts", [])])
                _list_block("TIGHTEST",
                            [f"{lab} · {s}¢ · depth {d}" for lab, s, d in liq.get("tightest", [])])
                _list_block("MOST TRADED", [f"{lab} · vol {v}" for lab, v in liq.get("most_traded", [])])
            _list_block("CONTRACTS BY FAMILY",
                        [f"{k} · {v}" for k, v in (cat.get("by_family") or {}).items()])

    def render_alerts() -> None:
        """Trusted-state alerts surface (§10 Phase 1) — new-actionable + blocked-change, diffed over the two
        most recent snapshots via engine.alerts(). No user rules yet (Phase 2)."""
        alrt_surface.clear()
        al = engine.alerts()
        new_a, blk = al.get("new_actionable") or [], al.get("blocked_changes") or []
        with alrt_surface:
            ui.label("ALRT — trusted-state alerts").classes("tp-amber font-bold")
            ui.label("New-actionable + blocked-change, diffed over the two most recent scans.").classes(
                "tp-dim text-xs")
            ui.label(f"NEW ACTIONABLE ({len(new_a)})").classes("tp-klabel mt-2")
            if not new_a:
                ui.label("None since the previous scan.").classes("tp-dim text-xs")
            for o in new_a:
                ui.label(f"● {o.get('sport_label') or o.get('sport')} · {o.get('name')} · "
                         f"edge {o.get('exec_gap_c')}¢").classes("tp-green text-xs")
            ui.label(f"BLOCKED CHANGES ({len(blk)})").classes("tp-klabel mt-2")
            if not blk:
                ui.label("None since the previous scan.").classes("tp-dim text-xs")
            for o in blk:
                ch = o.get("changes")
                ui.label(f"● {o.get('name')} · {ch if ch else 'blocked state changed'}").classes(
                    "tp-amber text-xs")

    def set_surface(name: str) -> None:
        state["surface"] = name
        for n, fk in fkeys.items():
            fk.classes(replace=("tp-fkey cursor-pointer" if n == name else "tp-fkey-off cursor-pointer"))
        opp_surface.set_visibility(name == "OPP")
        res_surface.set_visibility(name == "RES")
        ops_surface.set_visibility(name == "OPS")
        alrt_surface.set_visibility(name == "ALRT")
        if name == "RES":
            render_research()
        elif name == "OPS":
            render_ops()
        elif name == "ALRT":
            render_alerts()

    # ---- data load + status -------------------------------------------------------------------------
    def reload() -> None:
        """Pull the latest snapshot's opportunities + coverage (in-process, no self-HTTP) and re-present.
        Cheap-guarded by the snapshot id so the poll only rebuilds when a new scan has landed."""
        sid = engine.latest_snapshot_id()
        if sid == state["rendered_snapshot_id"]:
            update_status()
            return
        state["rendered_snapshot_id"] = sid
        opps = engine.latest_opportunities()
        state["opps"] = opps
        state["by_id"] = {o.get("opportunity_id"): o for o in opps}
        render_tiles()
        render_blotter()
        update_status()
        # Refresh whichever non-OPP surface is currently open so it reflects the new scan.
        if state["surface"] == "RES":
            render_research()
        elif state["surface"] == "OPS":
            render_ops()
        elif state["surface"] == "ALRT":
            render_alerts()

    def update_status() -> None:
        status.text = viewmodel.scope_banner(engine.coverage(), tz="UTC")

    def tick_clock() -> None:
        clock.text = time.strftime("%H:%M:%S UTC", time.gmtime())

    render_des(None)
    set_surface("OPP")          # highlight the OPP tab + show the workspace, hide the others
    reload()
    tick_clock()
    ui.timer(1.0, tick_clock)
    ui.timer(config.UI_POLL_SECONDS if hasattr(config, "UI_POLL_SECONDS") else 1.0, reload)
