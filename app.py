"""Streamlit UI for the French Open Kalshi viewer — trader-first arbitrage dashboard.

The default view answers a trader's questions fast: what's actionable now, what's blocked and why,
what's near the edge to watch. Full diagnostics (the complete comparison table), per-player detail,
and debug are kept but moved below and collapsed. Controls live in the left sidebar.

On-demand snapshot: by default only the core French Open series are fetched; an optional checkbox
enables a full dynamic scan. Data caches for 60s. The consistency/arbitrage math lives in
consistency.py and is unchanged here — this module only presents it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import DEFAULT_SERIES
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


@st.cache_data(ttl=60, show_spinner="Fetching French Open markets…")
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
        "Tournament", ["Women", "Men", "Both"], index=0,
        help="Filter by tour. Women = WTA markets, Men = ATP markets.",
    )
    selected_types = st.multiselect(
        "Contract type", ALL_CONTRACT_TYPES,
        default=["Tournament winner", "Stage advancement"],
        help="Tournament winner: win-the-tournament markets. Stage advancement: reach-a-round "
             "markets. Match result: head-to-head winner markets (adds match-alignment rows).",
    )
    with st.expander("Advanced — data scope"):
        full_scan = st.checkbox(
            "Scan all tennis series (slower)", value=False,
            help="Fetches all ~61 tennis series (~20 s). Default fetches only the 6 core series (~2 s).",
        )
        show_help = st.toggle(
            "Show explanations", value=True,
            help="Show plain-language captions in the player-detail section. Hover tooltips on "
                 "columns stay either way.",
        )

try:
    df_all, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all
checks = build_checks(df)

# ---- Sidebar controls (part 2: after the load — need df) -----------------------------
with st.sidebar:
    max_vol = int(df["volume"].fillna(0).max()) if not df.empty else 0
    min_vol = st.slider(
        "Minimum volume", 0, max_vol, 0,
        help="Show only contracts with at least this many contracts traded.",
    ) if max_vol > 0 else 0
    with st.expander("Advanced filters"):
        st.caption("These only filter **Full diagnostics** below — never the Actionable now table.")
        status_choice = st.selectbox(
            "Outcome status", STATUS_GROUPS, index=0,
            format_func=lambda g: STATUS_GROUP_LABELS.get(g, g),
            help="All = every comparison. Actionable gross edge = firm executable cross with size. "
                 "Watchlist signals = display inconsistencies or wide quotes. Incomplete data = no "
                 "firm quote, a missing layer, or unconfirmed size. Unverifiable = the relationship "
                 "can't be proved. Consistent = deeper price ≤ broader on firm and display quotes.",
        )
        quote_choice = st.selectbox(
            "Quote quality", ["All", "Tight/OK only", "Include wide"], index=0,
            help="Tight/OK only: spread ≤ 15¢. Include wide: any real spread. All: includes empty books.",
        )
        if not df.empty:
            uniq = df.drop_duplicates("player_key")[["player_key", "player"]]
            name_counts = uniq["player"].value_counts()
            label_to_key = {}
            for _, r in uniq.iterrows():
                label = r["player"] if name_counts[r["player"]] == 1 else f'{r["player"]} [{str(r["player_key"])[:6]}]'
                label_to_key[label] = r["player_key"]
            chosen_label = st.selectbox(
                "Player (for the detail section)", sorted(label_to_key),
                help="Drives the 'Selected player detail' section lower on the page.",
            )
            chosen_key = label_to_key[chosen_label]
        else:
            chosen_key, chosen_label = None, None

# ---- Dashboard base: BASIC filters only (contract type + min volume). Diagnostic -----
# filters (outcome status / quote quality) are applied ONLY to Full diagnostics, so the
# trader sections below are never hidden by them.
dash_base = checks.copy()
if not dash_base.empty:
    dash_base = dash_base[
        (dash_base["child_category"].isin(selected_types) | dash_base["child_category"].eq(""))
        & (dash_base["parent_category"].isin(selected_types) | dash_base["parent_category"].eq(""))
    ]
    dash_base = dash_base[dash_base["volume"].fillna(0) >= min_vol]
if not dash_base.empty:
    dash_base = dash_base.assign(
        bucket=dash_base.apply(bucket_of, axis=1),
        status_label=dash_base["status"].map(STATUS_LABELS).fillna(dash_base["status"]),
        tradable_disp=dash_base["tradable_now"].map(TRADABLE_DISP).fillna(dash_base["tradable_now"]),
    )
else:
    for _c in ("bucket", "status_label", "tradable_disp"):
        dash_base[_c] = pd.Series(dtype=object)


def bucket_df(name: str) -> pd.DataFrame:
    return dash_base[dash_base["bucket"] == name]


actionable = bucket_df("actionable")
blocked = bucket_df("blocked")
near = bucket_df("near_edge")
display_sig = bucket_df("display_signal")
wide_sig = bucket_df("wide_signal")
data_q = bucket_df("data_quality")

# Per-player frames (shared by the detail + debug sections).
if chosen_key is not None:
    prows = df[df["player_key"] == chosen_key].to_dict("records")
    chosen = prows[0]["player"] if prows else chosen_label
    pdf = df[df["player_key"] == chosen_key].copy().sort_values("stage_rank")
    pchecks = checks[checks["player_key"] == chosen_key] if "player_key" in checks.columns else checks.iloc[0:0]
else:
    prows, chosen, pdf, pchecks = [], None, df.iloc[0:0], checks.iloc[0:0]

# ====================================================================================
# 1. Header + metadata
# ====================================================================================
st.title("🎾 French Open — Arbitrage Dashboard")
scan_note = " · full scan" if full_scan else ""
st.caption(
    f"Last refreshed {fetched_at} · {tournament} · {len(df)} contracts · "
    f"{len(checks)} comparisons{scan_note}"
)

# ====================================================================================
# 2. Summary cards
# ====================================================================================
total_profit = float(actionable["exec_max_profit_dollars"].fillna(0).sum()) if not actionable.empty else 0.0
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Actionable now", len(actionable))
c2.metric("Gross quoted profit", f"${total_profit:,.2f}")
c3.metric("Blocked", len(blocked))
c4.metric("Near-edge", len(near))
c5.metric("Data-quality issues", len(data_q))
c6.metric("Last refreshed", fetched_at.split(" ", 1)[1] if " " in fetched_at else fetched_at)

# ====================================================================================
# 3. Actionable now — always visible, independent of diagnostic filters
# ====================================================================================
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
    st.caption("Gross, before fees, slippage, latency, and partial-fill risk.")

# ====================================================================================
# 4. Blocked opportunities
# ====================================================================================
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

# ====================================================================================
# 5. Near-edge watchlist
# ====================================================================================
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

# ====================================================================================
# 6. Watchlist signals (collapsed) — display inconsistencies + wide quotes
# ====================================================================================
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

# ====================================================================================
# 7. Selected player detail (collapsed)
# ====================================================================================
with st.expander("🔍 Selected player detail", expanded=False):
    if chosen_key is None:
        st.caption("Pick a player in the sidebar → Advanced filters to see their ladder, spreads, "
                   "and full contract list here.")
    else:
        st.markdown(f"**{chosen}**")
        nodes = build_player_nodes(prows)

        # ---- Progression chain / ladder view -----------------------------------------
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

        # ---- Firm executable inconsistencies (for the spread column + action cards) ---
        pviol = (
            checks[(checks["player_key"] == chosen_key) & (checks["status"] == "EXECUTABLE_VIOLATION")]
            if "player_key" in checks.columns else checks.iloc[0:0]
        )
        ev_gap_by_chain = {r["chain"]: r["exec_gap_c"] for _, r in pviol.iterrows()}

        # ---- Raw stage-ladder spreads ------------------------------------------------
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

        # ---- What to do: Buy YES / Buy NO for every flagged opportunity --------------
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

        # ---- Mapping confidence + expected-vs-found layers ---------------------------
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
        pdf = pdf.copy()
        pdf["time_dt"] = pd.to_datetime(pdf["time_value"], utc=True, errors="coerce")
        st.dataframe(
            pdf[["contract", "category", "stage", "opponent", "display_pct", "quote_quality",
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

        # ---- Exportable per-player snapshot ------------------------------------------
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
            "contracts": pdf.drop(columns=["time_dt"]).to_dict("records"),
            "consistency_comparisons": pchecks.to_dict("records"),
        }
        safe = "".join(c if c.isalnum() else "_" for c in chosen) or "player"
        ec1, ec2 = st.columns(2)
        ec1.download_button(
            "⬇ Export snapshot (JSON)", json.dumps(snapshot, indent=2, default=str),
            file_name=f"{safe}_snapshot.json", mime="application/json",
        )
        ec2.download_button(
            "⬇ Export contracts (CSV)", pdf.drop(columns=["time_dt"]).to_csv(index=False),
            file_name=f"{safe}_contracts.csv", mime="text/csv",
        )

# ====================================================================================
# 8. Full diagnostics: all comparisons (collapsed) — advanced filters apply HERE only
# ====================================================================================
with st.expander("🧪 Full diagnostics: all comparisons", expanded=False):
    view = dash_base.copy()
    if not view.empty:
        if status_choice != "All":
            view = view[view["status_group"] == status_choice]
        if quote_choice == "Tight/OK only":
            view = view[view["comp_quote_quality"].isin(("Tight", "OK"))]
        elif quote_choice == "Include wide":
            view = view[view["comp_quote_quality"].isin(("Tight", "OK", "Wide", "Very wide"))]
    if not view.empty:
        view = view.assign(_sort=view["status_group"].map(GROUP_SORT).fillna(9))
        view = view.sort_values(
            ["_sort", "executable_gap", "display_gap"], ascending=[True, False, False], na_position="last"
        ).drop(columns="_sort")
        st.caption(f"{len(view)} of {len(dash_base)} comparisons (after Advanced filters).")
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

# ====================================================================================
# 9. Debug (collapsed)
# ====================================================================================
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
