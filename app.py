"""Streamlit UI for the French Open Kalshi viewer — trader-first arbitrage dashboard.

The default view answers a trader's questions fast: what's actionable now, what's blocked and why,
what's near the edge to watch. Full diagnostics (the complete comparison table), per-player detail,
and debug are kept but moved below and collapsed. Controls live in the left sidebar.

Filtering: *membership* filters (tour, competition, contract family, stage/layer, event, player, min
volume) narrow EVERY section incl. Actionable now; *threshold* filters (min gross edge, min tradable
size, quote quality, market status) narrow everything EXCEPT Actionable now — which always shows every
executable edge in the membership universe (see filters.py).

The dashboard auto-refreshes on a timer (native st.fragment(run_every=...)), gated by the
load_contracts cache TTL; request rate is bounded by the process-wide throttle in kalshi_client. The
consistency/arbitrage math lives in consistency.py and is unchanged here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import (
    DEFAULT_SERIES,
    FULL_SCAN_MIN_INTERVAL,
    REFRESH_DEFAULT_SECONDS,
    REFRESH_OPTIONS,
    REFRESH_TTL,
)
from consistency import (
    ACTION_STATUSES,
    MATCH_STAGE_TO_NODE,
    NODE_ORDER,
    bucket_of,
    build_checks,
    build_player_nodes,
    duplicate_node_sources,
    expected_nodes,
    layer_spreads,
    representative,
)
from data import build_contracts, link_audit
from filters import QUOTE_MODES, STATUS_MODES, apply_membership, apply_thresholds
from glossary import help_for
from kalshi_client import (
    KalshiError,
    discover_tennis_series,
    get_events_for_series,
    get_series_titles,
)

st.set_page_config(page_title="French Open Kalshi Dashboard", page_icon="🎾", layout="wide")

TOUR_FILTER = {"Women": ["WTA"], "Men": ["ATP"], "Both": ["ATP", "WTA"]}
STATUS_GROUPS = ["All", "Clean", "Broken", "Warning", "Missing data", "Unknown relationship"]
GROUP_SORT = {"Broken": 0, "Warning": 1, "Missing data": 2, "Unknown relationship": 3, "Clean": 4}
ALL_CONTRACT_TYPES = ["Tournament winner", "Stage advancement", "Match result"]

# Display labels for the diagnostic status groups (Outcome-status filter + Full diagnostics).
# "edge" is reserved for a positive executable gap; the old confusing potential-edge wording is gone.
STATUS_GROUP_LABELS = {
    "All": "All",
    "Clean": "Consistent",
    "Broken": "Actionable gross edge",
    "Warning": "Watchlist signals",
    "Missing data": "Incomplete data",
    "Unknown relationship": "Unverifiable",
}
STATUS_LABELS = {
    "CLEAN": "Consistent",
    "EXECUTABLE_VIOLATION": "Actionable gross edge",
    "DISPLAY_VIOLATION": "Display inconsistency",
    "WIDE_QUOTE": "Wide quote / watchlist",
    "MISSING_QUOTE": "Missing firm quote",
    "MISSING_LAYER": "Missing layer",
    "QUOTE_SIZE_MISSING": "Blocked: no size",
    "UNKNOWN_RELATIONSHIP": "Unverifiable",
}
# Scannable "can I act right now?" badge.
TRADABLE_DISP = {
    "Yes": "✅ Yes",
    "Yes — rule-dependent": "⚠ Yes (verify rules)",
    "No": "❌ No",
}


@st.cache_data(ttl=3600, show_spinner=False)
def discover() -> list[str]:
    return discover_tennis_series()


@st.cache_data(ttl=REFRESH_TTL, show_spinner="Fetching French Open markets…")
def load_contracts(full_scan: bool) -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int]:
    tickers = discover() if full_scan else DEFAULT_SERIES
    results, errors = get_events_for_series(tickers)
    # Series titles drive the slugged Kalshi deep links; missing titles fall back to the series page.
    titles = get_series_titles([t for t, _ in results])
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events, series_title=titles.get(ticker, "")))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at, errors, len(tickers), len(results)


def _buy_disp(contract: str, price_c) -> str:
    """Compact buy cell, e.g. 'Reach Final @ 46¢' (the column header carries Buy YES / Buy NO)."""
    if not contract:
        return ""
    price = f"{int(price_c)}¢" if pd.notna(price_c) else "—"
    return f"{contract} @ {price}"


# ---- Sidebar controls (part 1: before the data load) --------------------------------
with st.sidebar:
    st.header("Controls")
    if st.button("🔄 Refresh data"):
        discover.clear()
        load_contracts.clear()
        st.rerun()
    tournament = st.radio(
        "Tour", ["Women", "Men", "Both"], index=0,
        help="WTA (Women) / ATP (Men) / both.",
    )
    selected_types = st.multiselect(
        "Contract family", ALL_CONTRACT_TYPES,
        default=["Tournament winner", "Stage advancement"],
        help="Tournament winner: win-the-tournament markets. Stage advancement: reach-a-round "
             "markets. Match result: head-to-head winner markets (adds match-alignment rows).",
    )
    auto_refresh = st.toggle(
        "Auto-refresh", value=True,
        help="Periodically re-fetch market data on a timer. Request rate stays well under Kalshi's "
             "free-tier limit (throttled in the client).",
    )
    interval = st.selectbox(
        "Refresh interval (seconds)", REFRESH_OPTIONS,
        index=REFRESH_OPTIONS.index(REFRESH_DEFAULT_SECONDS),
        help="How often to re-fetch when auto-refresh is on.",
    )
    with st.expander("Advanced — data scope"):
        full_scan = st.checkbox(
            "Scan all tennis series (slower)", value=False,
            help="Fetches all ~61 tennis series. Default fetches only the 6 core series.",
        )
        show_help = st.toggle(
            "Show explanations", value=True,
            help="Show plain-language captions in the player-detail section.",
        )

    if full_scan:
        effective_interval = max(interval, FULL_SCAN_MIN_INTERVAL)
        if auto_refresh and interval < FULL_SCAN_MIN_INTERVAL:
            st.warning(
                f"⚠ Full scan is heavy (~120+ requests per refresh). Auto-refresh interval raised to "
                f"{FULL_SCAN_MIN_INTERVAL}s (you selected {interval}s)."
            )
        else:
            st.warning("⚠ Full scan is heavy (~120+ requests per refresh); each tick is slower.")
    else:
        effective_interval = interval
    run_every = effective_interval if auto_refresh else None

# Initial load (feeds the sidebar widgets that need data: filter options + player list).
try:
    df_all, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all

# ---- Sidebar controls (part 2: after the load — options derived from df) -------------
with st.sidebar:
    max_vol = int(df["volume"].fillna(0).max()) if not df.empty else 0
    min_vol = st.slider(
        "Minimum volume", 0, max_vol, 0,
        help="Universe filter: drop contracts below this traded volume (narrows all sections).",
    ) if max_vol > 0 else 0

    with st.expander("Market universe"):
        comp_opts = sorted(df["competition"].dropna().unique().tolist()) if not df.empty else []
        sel_comps = st.multiselect("Competition", comp_opts, default=[],
                                   help="Single-tournament today (French Open); broadens with more data.")
        match_stages = (
            sorted({s for s in df.loc[df["kind"] == "match", "stage"].dropna().unique().tolist() if s})
            if not df.empty else []
        )
        layer_opts = list(NODE_ORDER) + match_stages
        sel_layers = st.multiselect("Stage / layer", layer_opts, default=[],
                                    help="Containment layers (Reach SF/Final, Win Tournament) and match rounds.")
        event_q = st.text_input("Event / game search", "", help="Substring match on the event ticker.")
        player_q = st.text_input("Player / participant search", "", help="Substring match on player name.")

    with st.expander("Thresholds"):
        st.caption("These narrow every section **except Actionable now**.")
        min_edge = st.number_input("Min gross edge (¢)", min_value=0, value=0, step=1)
        min_size = st.number_input("Min tradable size", min_value=0, value=0, step=1)
        quote_choice = st.selectbox("Quote quality", QUOTE_MODES, index=0,
                                    help="Tight/OK only: spread ≤ 15¢. Include wide: any real spread.")
        status_mode = st.selectbox("Market status", STATUS_MODES, index=0,
                                   help="Active only = both legs currently open for trading.")

    with st.expander("Sections"):
        show_blocked = st.toggle("Show blocked opportunities", value=True)
        show_near = st.toggle("Show near-edge watchlist", value=True)
        show_signals = st.toggle("Show watchlist signals", value=False)
        show_dataq = st.toggle("Show data-quality issues", value=False)

    with st.expander("Full-diagnostics filter"):
        status_choice = st.selectbox(
            "Outcome status", STATUS_GROUPS, index=0,
            format_func=lambda g: STATUS_GROUP_LABELS.get(g, g),
            help="Diagnostic filter applied only to the Full diagnostics table below.",
        )

    with st.expander("Player detail"):
        if not df.empty:
            uniq = df.drop_duplicates("player_key")[["player_key", "player"]]
            name_counts = uniq["player"].value_counts()
            label_to_key = {}
            for _, r in uniq.iterrows():
                label = r["player"] if name_counts[r["player"]] == 1 else f'{r["player"]} [{str(r["player_key"])[:6]}]'
                label_to_key[label] = r["player_key"]
            chosen_label = st.selectbox("Player", sorted(label_to_key),
                                        help="Drives the 'Selected player detail' section.")
            chosen_key = label_to_key[chosen_label]
        else:
            chosen_key, chosen_label = None, None

st.title("🎾 French Open — Arbitrage Dashboard")


@st.fragment(run_every=run_every)
def render_dashboard() -> None:
    # Re-load INSIDE the fragment so periodic auto-refresh ticks fetch fresh data (cache-gated,
    # rate-throttled — safe to repeat).
    try:
        df_all, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)
    except KalshiError as exc:
        st.error(f"Couldn't refresh Kalshi data: {exc}")
        return
    df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all
    checks = build_checks(df)

    # Bucket every comparison, then split filtering into the two passes (see filters.py):
    #   universe    = membership filters  -> feeds Actionable now (+ all sections)
    #   thresholded = + threshold filters -> feeds every section EXCEPT Actionable now
    dash_base = checks.copy()
    if not dash_base.empty:
        dash_base = dash_base.assign(
            bucket=dash_base.apply(bucket_of, axis=1),
            status_label=dash_base["status"].map(STATUS_LABELS).fillna(dash_base["status"]),
            tradable_disp=dash_base["tradable_now"].map(TRADABLE_DISP).fillna(dash_base["tradable_now"]),
        )
    else:
        for _c in ("bucket", "status_label", "tradable_disp"):
            dash_base[_c] = pd.Series(dtype=object)

    universe = apply_membership(
        dash_base, competitions=sel_comps, categories=selected_types, layers=sel_layers,
        event_query=event_q, player_query=player_q, min_volume=min_vol,
    )
    thresholded = apply_thresholds(
        universe, min_edge_c=min_edge, min_size=min_size, quote_mode=quote_choice, status_mode=status_mode,
    )

    def in_bucket(frame: pd.DataFrame, name: str) -> pd.DataFrame:
        return frame[frame["bucket"] == name] if "bucket" in frame.columns and not frame.empty else frame.iloc[0:0]

    actionable = in_bucket(universe, "actionable")           # membership only
    blocked = in_bucket(thresholded, "blocked")
    near = in_bucket(thresholded, "near_edge")
    display_sig = in_bucket(thresholded, "display_signal")
    wide_sig = in_bucket(thresholded, "wide_signal")
    data_q = in_bucket(thresholded, "data_quality")

    # Full-diagnostics view: thresholded + the diagnostic outcome-status select, sorted.
    view = thresholded.copy()
    if not view.empty and status_choice != "All":
        view = view[view["status_group"] == status_choice]
    if not view.empty:
        view = view.assign(_sort=view["status_group"].map(GROUP_SORT).fillna(9))
        view = view.sort_values(
            ["_sort", "executable_gap", "display_gap"], ascending=[True, False, False], na_position="last"
        ).drop(columns="_sort")

    # Per-player frames (shared by the detail + debug sections).
    if chosen_key is not None:
        prows = df[df["player_key"] == chosen_key].to_dict("records")
        chosen = prows[0]["player"] if prows else chosen_label
        pdf = df[df["player_key"] == chosen_key].copy().sort_values("stage_rank")
        pchecks = checks[checks["player_key"] == chosen_key] if "player_key" in checks.columns else checks.iloc[0:0]
    else:
        prows, chosen, pdf, pchecks = [], None, df.iloc[0:0], checks.iloc[0:0]

    # ================================================================================
    # 1. Header + metadata
    # ================================================================================
    scan_note = " · full scan" if full_scan else ""
    refresh_note = f" · auto-refresh every {effective_interval}s" if auto_refresh else " · auto-refresh off"
    st.caption(
        f"Last refreshed {fetched_at} · {tournament} · {len(df)} contracts · "
        f"{len(checks)} comparisons{scan_note}{refresh_note}"
    )

    # ================================================================================
    # 2. Summary cards
    # ================================================================================
    total_profit = float(actionable["exec_max_profit_dollars"].fillna(0).sum()) if not actionable.empty else 0.0
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Actionable now", len(actionable))
    c2.metric("Gross quoted profit", f"${total_profit:,.2f}")
    c3.metric("Blocked", len(blocked))
    c4.metric("Near-edge", len(near))
    c5.metric("Data-quality issues", len(data_q))
    c6.metric("Last refreshed", fetched_at.split(" ", 1)[1] if " " in fetched_at else fetched_at)

    # ---- Exports (collapsed) -------------------------------------------------------
    with st.expander("⬇ Export"):
        e1, e2, e3 = st.columns(3)
        e1.download_button("Current dashboard (CSV)", universe.to_csv(index=False),
                           file_name="dashboard.csv", mime="text/csv")
        e2.download_button("Full diagnostics (CSV)", view.to_csv(index=False),
                           file_name="full_diagnostics.csv", mime="text/csv")
        e3.download_button("Raw contracts (CSV)", df.to_csv(index=False),
                           file_name="contracts.csv", mime="text/csv")
        st.caption("Current dashboard = the filtered comparison universe. Selected-player snapshot is in "
                   "the player-detail section.")

    # ================================================================================
    # 3. Actionable now — always visible, membership universe only (thresholds spare it)
    # ================================================================================
    st.subheader("✅ Actionable now")
    if actionable.empty:
        st.success("No actionable gross edges right now.")
    else:
        a = actionable.copy()
        a["buy_yes_disp"] = [_buy_disp(c, p) for c, p in zip(a["action_1_contract"], a["action_1_price_c"])]
        a["buy_no_disp"] = [_buy_disp(c, p) for c, p in zip(a["action_2_contract"], a["action_2_price_c"])]
        a["caveat_disp"] = a["blockers"].replace("", "—").fillna("—")
        st.dataframe(
            a[["player", "chain", "buy_yes_disp", "buy_no_disp", "exec_gap_c", "exec_min_size",
               "exec_max_profit_dollars", "tradable_disp", "caveat_disp", "child_url", "parent_url"]],
            hide_index=True, width="stretch",
            column_config={
                "player": "Player",
                "chain": "Chain",
                "buy_yes_disp": st.column_config.TextColumn("Buy YES", help="Buy YES on the broader contract @ its ask."),
                "buy_no_disp": st.column_config.TextColumn("Buy NO", help="Buy NO on the deeper contract @ the NO ask."),
                "exec_gap_c": st.column_config.NumberColumn("Gross edge (¢)", format="%.0f", help=help_for("Executable gap (¢)")),
                "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f", help="Smaller of the two legs' quoted sizes."),
                "exec_max_profit_dollars": st.column_config.NumberColumn("Gross quoted profit ($)", format="$%.2f", help=help_for("Gross quoted profit ($)")),
                "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                "caveat_disp": st.column_config.TextColumn("Caveat"),
                "child_url": st.column_config.LinkColumn("Deeper link", display_text="open ↗"),
                "parent_url": st.column_config.LinkColumn("Broader link", display_text="open ↗"),
            },
        )
        st.caption("Gross, before fees, slippage, latency, and partial-fill risk. (Thresholds do not filter this table.)")

    # ================================================================================
    # 4. Blocked opportunities
    # ================================================================================
    if show_blocked:
        st.subheader("⛔ Blocked opportunities")
        if blocked.empty:
            st.caption("None — no firm crosses are currently blocked.")
        else:
            b = blocked.copy()
            b["buy_yes_disp"] = [_buy_disp(c, p) for c, p in zip(b["action_1_contract"], b["action_1_price_c"])]
            b["buy_no_disp"] = [_buy_disp(c, p) for c, p in zip(b["action_2_contract"], b["action_2_price_c"])]
            st.caption("These look interesting but **cannot be traded now** — the buy prices are indicative only.")
            st.dataframe(
                b[["player", "chain", "buy_yes_disp", "buy_no_disp", "blockers", "tradable_disp",
                   "child_url", "parent_url"]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player",
                    "chain": "Chain",
                    "buy_yes_disp": st.column_config.TextColumn("Buy YES (indicative)"),
                    "buy_no_disp": st.column_config.TextColumn("Buy NO (indicative)"),
                    "blockers": st.column_config.TextColumn("Why blocked"),
                    "tradable_disp": st.column_config.TextColumn("Tradable now"),
                    "child_url": st.column_config.LinkColumn("Deeper link", display_text="open ↗"),
                    "parent_url": st.column_config.LinkColumn("Broader link", display_text="open ↗"),
                },
            )

    # ================================================================================
    # 5. Near-edge watchlist
    # ================================================================================
    if show_near:
        st.subheader("📈 Near-edge watchlist")
        if near.empty:
            st.caption("Nothing within 5¢ of an edge (on Tight/OK quotes).")
        else:
            st.caption("Within 5¢ of crossing, on firm Tight/OK quotes — **close to executable, not actionable.** "
                       "No buy instruction shown.")
            st.dataframe(
                near[["player", "chain", "child_bid_pct", "parent_ask_pct", "executable_gap", "comp_quote_quality"]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player",
                    "chain": "Chain",
                    "child_bid_pct": st.column_config.NumberColumn("Deeper bid %", format="%.1f%%"),
                    "parent_ask_pct": st.column_config.NumberColumn("Broader ask %", format="%.1f%%"),
                    "executable_gap": st.column_config.NumberColumn("Gap (¢)", format="%.0f", help="Deeper bid − broader ask, in cents. Negative = below the edge."),
                    "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                },
            )

    # ================================================================================
    # 6. Watchlist signals (collapsed) — display inconsistencies + wide quotes
    # ================================================================================
    if show_signals:
        sig = pd.concat([display_sig, wide_sig]) if not (display_sig.empty and wide_sig.empty) else display_sig
        with st.expander(f"👀 Watchlist signals — display & wide ({len(sig)})", expanded=False):
            st.caption("Monitoring signals, **not trade instructions**: display-only inconsistencies and "
                       "wide quotes where the ordering is still consistent.")
            if sig.empty:
                st.caption("No display or wide-quote signals.")
            else:
                st.dataframe(
                    sig[["player", "chain", "status_label", "display_gap", "comp_quote_quality", "reason"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "player": "Player",
                        "chain": "Chain",
                        "status_label": st.column_config.TextColumn("Signal"),
                        "display_gap": st.column_config.NumberColumn("Display gap ¢", format="%.0f"),
                        "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                        "reason": "Reason",
                    },
                )

    # ================================================================================
    # 6b. Data-quality issues (collapsed) — missing quotes/layers, unverifiable
    # ================================================================================
    if show_dataq:
        with st.expander(f"🧹 Data-quality issues ({len(data_q)})", expanded=False):
            st.caption("Incomplete or unverifiable comparisons — not opportunities.")
            if data_q.empty:
                st.caption("None.")
            else:
                st.dataframe(
                    data_q[["player", "chain", "status_label", "comp_quote_quality", "reason"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "player": "Player",
                        "chain": "Chain",
                        "status_label": st.column_config.TextColumn("Issue"),
                        "comp_quote_quality": st.column_config.TextColumn("Quote quality"),
                        "reason": "Reason",
                    },
                )

    # ================================================================================
    # 7. Selected player detail (collapsed)
    # ================================================================================
    with st.expander("🔍 Selected player detail", expanded=False):
        if chosen_key is None:
            st.caption("Pick a player in the sidebar → Player detail to see their ladder, spreads, "
                       "and full contract list here.")
        else:
            st.markdown(f"**{chosen}**")
            nodes = build_player_nodes(prows)

            chain_rows = []
            for node in NODE_ORDER:
                src = nodes.get(node, {})
                primary = representative(src)
                if primary is None:
                    chain_rows.append({"Layer": node, "Source": "— missing —", "Display %": None,
                                       "Bid %": None, "Ask %": None, "Quote": ""})
                else:
                    chain_rows.append({
                        "Layer": node,
                        "Source": "advance/winner" if "market" in src else "match-implied",
                        "Display %": primary.get("display_pct"),
                        "Bid %": primary.get("yes_bid_pct"),
                        "Ask %": primary.get("yes_ask_pct"),
                        "Quote": primary.get("quote_quality", ""),
                    })
            st.caption("Progression chain (broad → deep):")
            st.dataframe(
                pd.DataFrame(chain_rows), hide_index=True, width="stretch",
                column_config={
                    "Display %": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                    "Bid %": st.column_config.NumberColumn("Bid %", format="%.1f%%"),
                    "Ask %": st.column_config.NumberColumn("Ask %", format="%.1f%%"),
                },
            )

            pviol = (
                checks[(checks["player_key"] == chosen_key) & (checks["status"] == "EXECUTABLE_VIOLATION")]
                if "player_key" in checks.columns else checks.iloc[0:0]
            )
            ev_gap_by_chain = {r["chain"]: r["exec_gap_c"] for _, r in pviol.iterrows()}

            spread_rows = layer_spreads(prows)
            spread_df = pd.DataFrame(spread_rows)

            def _profit_per_unit(r) -> str:
                if not r["inverted"]:
                    return ""
                gap = ev_gap_by_chain.get(f"{r['to_layer']} ≤ {r['from_layer']}")
                return f"{int(gap)}¢" if gap is not None else "Display only"

            spread_df["profit_per_unit"] = spread_df.apply(_profit_per_unit, axis=1)
            st.caption("Raw stage-ladder spreads (adjacent layers) — broader minus deeper:")
            st.dataframe(
                spread_df[
                    ["from_layer", "to_layer", "from_pct", "to_pct", "spread_pct", "spread_cents",
                     "quote", "status", "inverted", "profit_per_unit"]
                ],
                hide_index=True, width="stretch",
                column_config={
                    "from_layer": "From layer", "to_layer": "To layer",
                    "from_pct": st.column_config.NumberColumn("From %", format="%.1f%%"),
                    "to_pct": st.column_config.NumberColumn("To %", format="%.1f%%"),
                    "spread_pct": st.column_config.NumberColumn("Spread (pp)", format="%.1f pp"),
                    "spread_cents": st.column_config.NumberColumn("Spread (¢)", format="%.1f"),
                    "quote": st.column_config.TextColumn("Quote", help="Worst quote quality of the two layers."),
                    "status": "Status",
                    "inverted": st.column_config.CheckboxColumn("Inverted"),
                    "profit_per_unit": st.column_config.TextColumn("Profit/unit", help="On an inverted row: the firm executable gap (¢) if backed by an actionable edge, else 'Display only'."),
                },
            )

            pchecks_all = (
                checks[checks["player_key"] == chosen_key]
                if "player_key" in checks.columns else checks.iloc[0:0]
            )
            pedge = pchecks_all[pchecks_all["status"].isin(ACTION_STATUSES | {"WIDE_QUOTE"})]
            if not pedge.empty:
                st.caption("What to do — every flagged opportunity for this player:")
                for _, r in pedge.iterrows():
                    if r["status"] == "WIDE_QUOTE":
                        st.markdown(f"**{r['chain']}** — 👀 {r['watchlist_note']}")
                        continue
                    badge = TRADABLE_DISP.get(r["tradable_now"], r["tradable_now"])
                    lines = [
                        f"**{r['chain']}**",
                        f"1. {r['action_1_text']}",
                        f"2. {r['action_2_text']}",
                        f"- **Tradable right now?** {badge}",
                    ]
                    if r["status"] == "EXECUTABLE_VIOLATION" and pd.notna(r["exec_max_profit_dollars"]):
                        units = r["exec_min_size"]
                        lines.append(
                            f"- Max units {units:g} · Gross quoted profit "
                            f"${r['exec_max_profit_dollars']:.2f} — gross, before fees, slippage, "
                            "latency, and partial-fill risk."
                        )
                    if r["blockers"]:
                        lines.append(f"- **Why not:** {r['blockers']}")
                    st.markdown("\n".join(lines))
                if show_help:
                    st.caption(
                        "Every opportunity is two BUYS: **Buy YES** on the broader outcome and **Buy NO** "
                        "on the deeper one. ✅ = executable now; ⚠/❌ = see **Why not**. 👀 = watchlist only."
                    )

            sample = prows[0] if prows else {}
            if show_help:
                st.caption(
                    f"Mapping: **{sample.get('mapping_confidence', '?')}** confidence "
                    f"(key source: `{sample.get('player_key_source', '?')}`) — {sample.get('mapping_reason', '')}"
                )
            exp = expected_nodes(prows)
            exp_df = pd.DataFrame(exp)
            exp_df["found"] = exp_df["found"].map({True: "✅ found", False: "❌ MISSING"})
            st.caption("Expected progression layers (found vs missing):")
            st.dataframe(
                exp_df[["layer", "found", "source"]],
                hide_index=True, width="stretch",
                column_config={"layer": "Layer", "found": "Status", "source": "Source"},
            )

            match_rows = [r for r in prows if r.get("kind") == "match" and r.get("stage") in MATCH_STAGE_TO_NODE]
            if match_rows:
                st.caption("Match contracts with a confident stage mapping:")
                st.dataframe(
                    pd.DataFrame(match_rows)[["contract", "stage", "opponent", "display_pct", "yes_bid_pct", "yes_ask_pct", "quote_quality"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "contract": "Contract", "stage": "Stage", "opponent": "Opponent",
                        "display_pct": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                        "yes_bid_pct": st.column_config.NumberColumn("Bid", format="%.1f%%"),
                        "yes_ask_pct": st.column_config.NumberColumn("Ask", format="%.1f%%"),
                        "quote_quality": "Quote",
                    },
                )

            st.caption("All contracts for this player:")
            pdf2 = pdf.copy()
            pdf2["time_dt"] = pd.to_datetime(pdf2["time_value"], utc=True, errors="coerce")
            st.dataframe(
                pdf2[["contract", "category", "stage", "opponent", "display_pct", "quote_quality",
                      "mapping_confidence", "yes_bid_pct", "yes_ask_pct", "no_bid_pct", "no_ask_pct",
                      "spread_cents", "volume", "status", "time_dt", "time_kind", "kalshi_url"]],
                hide_index=True, width="stretch",
                column_config={
                    "contract": "Contract", "category": "Type", "stage": "Stage", "opponent": "Opponent",
                    "display_pct": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                    "quote_quality": "Quote",
                    "mapping_confidence": "Mapping",
                    "yes_bid_pct": st.column_config.NumberColumn("YES bid %", format="%.1f%%", help="Sell-YES price."),
                    "yes_ask_pct": st.column_config.NumberColumn("Buy YES %", format="%.1f%%", help="Price to BUY YES (the YES ask)."),
                    "no_bid_pct": st.column_config.NumberColumn("NO bid %", format="%.1f%%"),
                    "no_ask_pct": st.column_config.NumberColumn("Buy NO %", format="%.1f%%", help="Price to BUY NO (the NO ask)."),
                    "spread_cents": st.column_config.NumberColumn("Spread ¢", format="%.1f"),
                    "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                    "status": "Status",
                    "time_dt": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
                    "time_kind": "Time basis",
                    "kalshi_url": st.column_config.LinkColumn("Kalshi", display_text="open ↗"),
                },
            )

            snapshot = {
                "player": chosen,
                "fetched_at": fetched_at,
                "tour": sample.get("tour"),
                "mapping": {
                    "player_key": sample.get("player_key"),
                    "player_key_source": sample.get("player_key_source"),
                    "mapping_confidence": sample.get("mapping_confidence"),
                    "mapping_reason": sample.get("mapping_reason"),
                },
                "expected_layers": exp,
                "ladder_spreads": spread_rows,
                "contracts": pdf2.drop(columns=["time_dt"]).to_dict("records"),
                "consistency_comparisons": pchecks.to_dict("records"),
            }
            safe = "".join(c if c.isalnum() else "_" for c in chosen) or "player"
            ec1, ec2 = st.columns(2)
            ec1.download_button(
                "⬇ Export snapshot (JSON)", json.dumps(snapshot, indent=2, default=str),
                file_name=f"{safe}_snapshot.json", mime="application/json",
            )
            ec2.download_button(
                "⬇ Export contracts (CSV)", pdf2.drop(columns=["time_dt"]).to_csv(index=False),
                file_name=f"{safe}_contracts.csv", mime="text/csv",
            )

    # ================================================================================
    # 8. Full diagnostics: all comparisons (collapsed) — threshold + outcome-status applied
    # ================================================================================
    with st.expander("🧪 Full diagnostics: all comparisons", expanded=False):
        if not view.empty:
            st.caption(f"{len(view)} of {len(universe)} comparisons (after Thresholds + Outcome status).")
            st.dataframe(
                view[[
                    "player", "chain", "child_contract", "parent_contract", "child_display_pct",
                    "parent_display_pct", "child_bid_pct", "parent_ask_pct", "executable_gap",
                    "exec_min_size", "exec_max_profit_dollars", "display_gap", "status_label",
                    "tradable_disp", "rule_flag", "reason", "volume", "comp_quote_quality",
                    "child_ticker", "parent_ticker", "child_url", "parent_url",
                ]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player",
                    "chain": "Chain",
                    "child_contract": "Deeper contract",
                    "parent_contract": "Broader contract",
                    "child_display_pct": st.column_config.NumberColumn("Deeper %", format="%.1f%%"),
                    "parent_display_pct": st.column_config.NumberColumn("Broader %", format="%.1f%%"),
                    "child_bid_pct": st.column_config.NumberColumn("Deeper bid", format="%.1f%%"),
                    "parent_ask_pct": st.column_config.NumberColumn("Broader ask", format="%.1f%%"),
                    "executable_gap": st.column_config.NumberColumn("Executable gap (¢)", format="%.0f", help=help_for("Executable gap (¢)")),
                    "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f"),
                    "exec_max_profit_dollars": st.column_config.NumberColumn("Gross quoted profit ($)", format="$%.2f", help=help_for("Gross quoted profit ($)")),
                    "display_gap": st.column_config.NumberColumn("Display gap ¢", format="%.0f"),
                    "status_label": st.column_config.TextColumn("Status"),
                    "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                    "rule_flag": st.column_config.TextColumn("Rule caveat", help=help_for("Rule caveat")),
                    "reason": "Reason",
                    "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                    "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                    "child_ticker": "Deeper ticker",
                    "parent_ticker": "Broader ticker",
                    "child_url": st.column_config.LinkColumn("Deeper link", display_text="open ↗"),
                    "parent_url": st.column_config.LinkColumn("Broader link", display_text="open ↗"),
                },
            )
        else:
            st.info("No comparisons match the current filters.")
            if not checks.empty:
                avail = checks["status_group"].value_counts()
                breakdown = " · ".join(f"{STATUS_GROUP_LABELS.get(g, g)} {n}" for g, n in avail.items())
                st.caption(f"Available now for {tournament} (before filters): {breakdown}.")

    # ================================================================================
    # 9. Debug (collapsed)
    # ================================================================================
    with st.expander(f"🔧 Debug — {n_loaded}/{n_scanned} series loaded, {len(errors)} failed", expanded=False):
        if errors:
            st.warning("Series that failed to load (NOT silently skipped):")
            st.dataframe(pd.DataFrame(errors, columns=["series", "error"]), hide_index=True, width="stretch")
        else:
            st.success("All scanned series loaded successfully.")

        if chosen_key is None:
            st.caption("Select a player in the sidebar to see per-player raw fields and the link audit.")
        else:
            st.caption("Raw contract fields for this player:")
            st.dataframe(
                pdf[["series", "event_ticker", "market_ticker", "event_title", "market_title",
                     "kind", "stage", "player_key", "player_key_source", "player_name_raw",
                     "player_name_normalized", "competitor_uuid", "mapping_confidence",
                     "mapping_reason", "raw_yes_bid", "raw_yes_ask", "raw_no_bid", "raw_no_ask",
                     "raw_last"]],
                hide_index=True, width="stretch",
            )
            st.caption("Comparison status + reason for this player:")
            st.dataframe(
                pchecks[["chain", "status", "status_group", "rule_flag", "executable_gap", "display_gap", "reason"]],
                hide_index=True, width="stretch",
            )
            st.caption("Link audit — each URL and the contract identifiers it encodes:")
            st.dataframe(pd.DataFrame(link_audit(prows)), hide_index=True, width="stretch")

            dups = duplicate_node_sources(prows)
            if dups:
                st.caption("Duplicate node/source rows (a representative was chosen deterministically):")
                st.dataframe(pd.DataFrame(dups), hide_index=True, width="stretch")


render_dashboard()
