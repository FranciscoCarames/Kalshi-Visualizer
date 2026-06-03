"""Streamlit UI for the Kalshi tennis viewer — trader-first executable-inconsistency dashboard.

Default view: what's actionable now, what's blocked and why, what's near the edge. Diagnostics,
per-player detail, and debug are collapsed below. Controls live in the left sidebar.

Filtering model:
  - Contract-family toggles change what is FETCHED from Kalshi (fewer families → fewer requests).
  - Tournament / Event / Participant / Stage / Min-volume are MEMBERSHIP filters — client-side, they
    narrow EVERY section (incl. Actionable now) but do not change fetching.
  - Min-size / Quote / Market-status are THRESHOLD filters — they narrow every section EXCEPT
    Actionable now (which always shows every executable edge in the membership universe).
  - Full diagnostics is built from the membership universe (NOT thresholds), so finalized markets stay
    visible there even though "Active only" is the default elsewhere.

Auto-refreshes via st.fragment(run_every); request rate is bounded by the kalshi_client throttle.
Consistency/arbitrage math lives in consistency.py and is unchanged here (grouping is per
player+tournament).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import altair as alt
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
    NODE_ORDER,
    bucket_of,
    build_checks,
    build_player_nodes,
    duplicate_node_sources,
    expected_nodes,
    layer_spreads,
    representative,
    scenario_payoffs,
)
from data import CATEGORY, build_contracts, classify_kind, link_audit, series_for_families
from filters import QUOTE_MODES, STATUS_MODES, apply_membership, apply_thresholds
from glossary import help_for
from kalshi_client import (
    KalshiError,
    discover_tennis_series,
    get_events_for_series,
    get_series_titles,
)
from viz import ladder_prices, opportunity_ranking, payoff_chart_data

st.set_page_config(page_title="Kalshi Tennis Dashboard", page_icon="🎾", layout="wide")

TOUR_FILTER = {"Women": ["WTA"], "Men": ["ATP"], "Both": ["ATP", "WTA"]}
STATUS_GROUPS = ["All", "Clean", "Broken", "Warning", "Missing data", "Unknown relationship"]
GROUP_SORT = {"Broken": 0, "Warning": 1, "Missing data": 2, "Unknown relationship": 3, "Clean": 4}
# All recognized contract families (drop the catch-all "Other"); default all ON.
ALL_CONTRACT_TYPES = [v for k, v in CATEGORY.items() if k != "other"]

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
TRADABLE_DISP = {
    "Yes": "✅ Yes",
    "Yes — rule-dependent": "⚠ Yes (verify rules)",
    "No": "❌ No",
}


@st.cache_data(ttl=3600, show_spinner=False)
def discover() -> list[str]:
    return discover_tennis_series()


@st.cache_data(ttl=REFRESH_TTL, show_spinner="Fetching tennis markets…")
def load_contracts(families: tuple, scan_all: bool) -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int, int, int]:
    # Fetch ONLY the series for the enabled contract families (family toggles reduce API requests).
    # Tournament/event/participant filters are client-side and do NOT change what's fetched.
    all_series = discover() if scan_all else DEFAULT_SERIES
    tickers = series_for_families(all_series, families)
    # Count discovered series excluded because their kind is unrecognised (never in any family list).
    n_excluded_unknown = sum(
        1 for s in all_series if CATEGORY.get(classify_kind(s), "Other") == "Other"
    )
    results, errors = get_events_for_series(tickers)
    titles = get_series_titles([t for t, _ in results])
    rows: list[dict] = []
    diag: dict = {}
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events, series_title=titles.get(ticker, ""), _diag=diag))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at, errors, len(tickers), len(results), diag.get("skipped_no_name", 0), n_excluded_unknown


def _buy_disp(contract: str, price_c) -> str:
    """Compact buy cell, e.g. 'Reach Final @ 46¢' (the column header carries Buy YES / Buy NO)."""
    if not contract:
        return ""
    price = f"{int(price_c)}¢" if pd.notna(price_c) else "—"
    return f"{contract} @ {price}"


def _payoff_block(check_row: dict, units=None) -> None:
    """Render one opportunity's settlement-scenario payoff table + cost/floor/ROC/capital.

    Pure presentation: all arithmetic lives in consistency.scenario_payoffs. Shows the P&L per
    single unit (one Buy YES + one Buy NO) in every terminal state, so the edge is concrete and the
    worst row is visibly the guaranteed floor."""
    pay = scenario_payoffs(check_row, units=units)
    if pay is None:
        return
    sdf = pd.DataFrame([
        {
            "Scenario": s["label"],
            "Buy YES leg": s["yes_leg_payout_c"],
            "Buy NO leg": s["no_leg_payout_c"],
            "Payout/unit": s["payout_c"],
            "Profit/unit": s["profit_c"],
        }
        for s in pay["scenarios"]
    ])
    st.dataframe(
        sdf, hide_index=True, width="stretch",
        column_config={
            "Scenario": st.column_config.TextColumn("Scenario"),
            "Buy YES leg": st.column_config.NumberColumn("Buy YES leg", format="%.0f¢", help="What the Buy YES leg settles to in this state."),
            "Buy NO leg": st.column_config.NumberColumn("Buy NO leg", format="%.0f¢", help="What the Buy NO leg settles to in this state."),
            "Payout/unit": st.column_config.NumberColumn("Payout/unit", format="%.0f¢"),
            "Profit/unit": st.column_config.NumberColumn("Profit/unit", format="%.0f¢", help="Payout − cost. The smallest is the guaranteed floor."),
        },
    )
    bits = []
    if pay["cost_c"] is not None:
        bits.append(f"Cost **{pay['cost_c']:.0f}¢/unit**")
    if pay["worst_case_profit_c"] is not None:
        roc = pay["roc_pct"]
        roc_txt = f" ({roc:g}% on capital)" if roc is not None else ""
        bits.append(f"guaranteed floor **+{pay['worst_case_profit_c']:.0f}¢/unit**{roc_txt}")
    if pay["capital_c"] is not None:
        bits.append(
            f"at {pay['units']:g} units → stake **${pay['capital_c'] / 100:,.2f}**, "
            f"lock **≥ ${pay['total_floor_profit_c'] / 100:,.2f}**"
        )
    if bits:
        st.caption(" · ".join(bits))
    if pay["has_rule_risk"]:
        st.caption("⚠ Equivalence pair: the **rules-diverge** row is a real risk — the two legs may "
                   "settle differently (walkover/retire nuance). The floor holds only if the rules match.")
    elif pay["kind"] == "containment":
        st.caption("The middle row is a **+$1/unit directional bonus**, not the edge — the floor is "
                   "guaranteed in every state. Gross, before fees/slippage.")

    # Payoff bar chart — the visual twin of the table: payout per state vs the cost line.
    cdf = payoff_chart_data(pay).dropna(subset=["payout_c"])
    if not cdf.empty:
        bars = alt.Chart(cdf).mark_bar().encode(
            x=alt.X("payout_c:Q", title="Payout / unit (¢)"),
            y=alt.Y("scenario:N", sort=None, title=None),
            color=alt.Color("role:N", title="",
                            scale=alt.Scale(domain=["Floor", "Bonus", "Risk"],
                                            range=["#2e7d32", "#1565c0", "#9e9e9e"])),
            tooltip=[alt.Tooltip("scenario:N", title="Scenario"),
                     alt.Tooltip("payout_c:Q", title="Payout ¢"),
                     alt.Tooltip("profit_c:Q", title="Profit ¢")],
        )
        chart = bars
        if pay["cost_c"] is not None:
            rule = (alt.Chart(pd.DataFrame({"cost": [pay["cost_c"]]}))
                    .mark_rule(color="#c62828", strokeDash=[4, 4])
                    .encode(x="cost:Q"))
            chart = bars + rule
        st.altair_chart(chart, width="stretch")
        if pay["cost_c"] is not None:
            st.caption("Bars = payout per unit · dashed line = cost. Every bar clears the line → "
                       "profit in **every** state.")


# scan_all must be known BEFORE the fetch, but its toggle lives in the Advanced expander at the END of
# the sidebar — so back it with session_state and read it ahead (default ON).
st.session_state.setdefault("scan_all_toggle", True)
scan_all = st.session_state["scan_all_toggle"]

# ---- Sidebar (part 1: before the fetch — only family + scan_all affect what's fetched) -----
with st.sidebar:
    st.header("Controls")
    if st.button("🔄 Refresh data"):
        discover.clear()
        load_contracts.clear()
        st.rerun()
    selected_types = st.multiselect(
        "Contract family", ALL_CONTRACT_TYPES, default=ALL_CONTRACT_TYPES,
        help="Which contract types to FETCH. Fewer families → fewer API requests.",
    )
    st.caption("ℹ️ Only contract-family toggles change what's **fetched**. Tournament, event and "
               "participant filters are **client-side** (no extra API requests).")

try:
    df_all, fetched_at, errors, n_scanned, n_loaded, _skipped, _excl = load_contracts(tuple(selected_types), scan_all)
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

# ---- Sidebar (part 2: after the fetch — options derived from the loaded data) --------------
with st.sidebar:
    tournament = st.radio(
        "Tour", ["Women", "Men", "Both"], index=2,
        help="WTA (Women) / ATP (Men) / both.",
    )
    df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all

    t_opts = sorted(df["tournament"].dropna().unique().tolist()) if not df.empty else []
    sel_tournaments = st.multiselect(
        "Tournament", t_opts, default=t_opts,
        help="Client-side filter. Each tournament's ladders are grouped separately.",
    )

    auto_refresh = st.toggle("Auto-refresh", value=True,
                             help="Re-fetch on a timer; rate stays under the free-tier limit.")
    interval = st.selectbox("Refresh interval (seconds)", REFRESH_OPTIONS,
                            index=REFRESH_OPTIONS.index(REFRESH_DEFAULT_SECONDS))

    # Participant + event option maps (from the tour-filtered data).
    if not df.empty:
        uniq = df.drop_duplicates("player_key")[["player_key", "player"]]
        name_counts = uniq["player"].value_counts()
        label_to_key = {}
        for _, r in uniq.iterrows():
            lab = r["player"] if name_counts[r["player"]] == 1 else f'{r["player"]} [{str(r["player_key"])[:6]}]'
            label_to_key[lab] = r["player_key"]
        ev_label_to_tickers: dict[str, set] = {}
        for _, r in df.iterrows():
            lab = (r.get("event_title") or r.get("event_ticker") or "").strip() or "(event)"
            ev_label_to_tickers.setdefault(lab, set()).add(r.get("event_ticker", ""))
        match_stages = sorted({s for s in df.loc[df["kind"] == "match", "stage"].dropna().unique().tolist() if s})
    else:
        label_to_key, ev_label_to_tickers, match_stages = {}, {}, []

    with st.expander("Market universe"):
        # ONE participant control: "All" = no filter + no detail; a name = filter to them + drive detail.
        participant = st.selectbox("Participant", ["All"] + sorted(label_to_key),
                                   help="Pick a participant to filter the whole dashboard to them and "
                                        "show their detail below. 'All' = no filter.")
        chosen_key = label_to_key.get(participant) if participant != "All" else None
        sel_event_labels = st.multiselect("Event / game", sorted(ev_label_to_tickers), default=[])
        sel_events = set().union(*[ev_label_to_tickers[lbl] for lbl in sel_event_labels]) if sel_event_labels else set()
        sel_layers = st.multiselect("Stage / layer", list(NODE_ORDER) + match_stages, default=[],
                                    help="Containment layers and match rounds.")

    with st.expander("Thresholds"):
        st.caption("These narrow every section **except Actionable now**.")
        min_size = st.number_input("Min available size", min_value=0, value=0, step=1,
                                   help="Current resting size you could fill now (≠ traded volume).")
        quote_choice = st.selectbox("Quote quality", QUOTE_MODES, index=0)
        status_mode = st.selectbox("Market status", STATUS_MODES,
                                   index=STATUS_MODES.index("Active only"),
                                   help="Active only (default) hides finished markets — except in "
                                        "Full diagnostics, which always shows everything.")

    with st.expander("Sections"):
        show_blocked = st.toggle("Show blocked opportunities", value=True)
        show_near = st.toggle("Show near-edge watchlist", value=True)
        show_signals = st.toggle("Show watchlist signals", value=False)
        show_dataq = st.toggle("Show data-quality issues", value=False)

    with st.expander("Advanced — data scope"):
        st.toggle("Scan all tennis tournaments", key="scan_all_toggle",
                  help="ON (default): discover & fetch all tennis series for the enabled families. "
                       "OFF: only the six default core series (match/advance/winner for ATP + WTA).")
        max_vol = int(df["volume"].fillna(0).max()) if not df.empty else 0
        min_vol = st.slider("Min traded volume (history)", 0, max_vol, 0,
                            help="Historical traded volume — distinct from 'Min available size'.") if max_vol > 0 else 0
        show_help = st.toggle("Show explanations", value=True)

    # Full scan is heavy: warn and never auto-refresh faster than FULL_SCAN_MIN_INTERVAL.
    if scan_all:
        effective_interval = max(interval, FULL_SCAN_MIN_INTERVAL)
        if auto_refresh and interval < FULL_SCAN_MIN_INTERVAL:
            st.warning(f"⚠ Scan-all is heavy; auto-refresh raised to {FULL_SCAN_MIN_INTERVAL}s "
                       f"(you selected {interval}s).")
    else:
        effective_interval = interval
    run_every = effective_interval if auto_refresh else None

players_filter = [chosen_key] if chosen_key else None

st.title("🎾 Kalshi Tennis — Executable Inconsistency Dashboard")


@st.fragment(run_every=run_every)
def render_dashboard() -> None:
    try:
        df_all, fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown = load_contracts(tuple(selected_types), scan_all)
    except KalshiError as exc:
        st.error(f"Couldn't refresh Kalshi data: {exc}")
        return
    df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all
    checks = build_checks(df)

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

    # MEMBERSHIP universe (feeds Actionable + all sections); THRESHOLDED (spares Actionable).
    universe = apply_membership(
        dash_base, tournaments=sel_tournaments, categories=selected_types, layers=sel_layers,
        events=sel_events, players=players_filter, min_volume=min_vol,
    )
    thresholded = apply_thresholds(
        universe, min_size=min_size, quote_mode=quote_choice, status_mode=status_mode,
    )

    def in_bucket(frame: pd.DataFrame, name: str) -> pd.DataFrame:
        return frame[frame["bucket"] == name] if "bucket" in frame.columns and not frame.empty else frame.iloc[0:0]

    actionable = in_bucket(universe, "actionable")
    blocked = in_bucket(thresholded, "blocked")
    near = in_bucket(thresholded, "near_edge")
    display_sig = in_bucket(thresholded, "display_signal")
    wide_sig = in_bucket(thresholded, "wide_signal")
    data_q = in_bucket(thresholded, "data_quality")

    # Per-player frames for the detail/debug sections (driven by the Participant control).
    if chosen_key is not None:
        prows = df[df["player_key"] == chosen_key].to_dict("records")
        chosen = prows[0]["player"] if prows else participant
        pdf = df[df["player_key"] == chosen_key].copy().sort_values("stage_rank")
        pchecks = checks[checks["player_key"] == chosen_key] if "player_key" in checks.columns else checks.iloc[0:0]
    else:
        prows, chosen, pdf, pchecks = [], None, df.iloc[0:0], checks.iloc[0:0]

    # ================================================================================
    # 1. Header + metadata
    # ================================================================================
    scan_note = " · all tennis" if scan_all else " · core series"
    refresh_note = f" · auto-refresh {effective_interval}s" if auto_refresh else " · auto-refresh off"
    st.caption(
        f"Last refreshed {fetched_at} · {tournament} · {len(df)} contracts · "
        f"{len(checks)} comparisons{scan_note}{refresh_note}"
    )

    # ================================================================================
    # 2. Summary cards + Export
    # ================================================================================
    total_profit = float(actionable["exec_max_profit_dollars"].fillna(0).sum()) if not actionable.empty else 0.0
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Actionable now", len(actionable))
    c2.metric("Gross quoted profit", f"${total_profit:,.2f}")
    c3.metric("Blocked", len(blocked))
    c4.metric("Near-edge", len(near))
    c5.metric("Data-quality issues", len(data_q))
    c6.metric("Last refreshed", fetched_at.split(" ", 1)[1] if " " in fetched_at else fetched_at)

    with st.expander("⬇ Export"):
        ex1, ex2 = st.columns(2)
        ex1.download_button("Comparisons — current filters (CSV)", universe.to_csv(index=False),
                            file_name="comparisons.csv", mime="text/csv", key="dl_universe")
        ex2.download_button("Raw contracts (CSV)", df.to_csv(index=False),
                            file_name="contracts.csv", mime="text/csv", key="dl_contracts")
        st.caption("Full-diagnostics and the selected-player snapshot have their own download buttons "
                   "in those sections.")

    if errors:
        st.warning(
            f"⚠ {len(errors)} series failed to load — results may be incomplete. "
            "See the Debug expander below for details."
        )

    # ================================================================================
    # 3. Actionable now — membership universe only (thresholds spare it)
    # ================================================================================
    st.subheader("✅ Actionable now")
    if actionable.empty:
        st.success("No actionable gross edges right now.")
    else:
        # Rank by gross edge (tiebreak gross profit) — any positive edge is good; all stay visible.
        a = actionable.assign(
            _g=pd.to_numeric(actionable["exec_gap_c"], errors="coerce"),
            _p=pd.to_numeric(actionable["exec_max_profit_dollars"], errors="coerce"),
        ).sort_values(["_g", "_p"], ascending=False, na_position="last").drop(columns=["_g", "_p"])
        a["buy_yes_disp"] = [_buy_disp(c, p) for c, p in zip(a["action_1_contract"], a["action_1_price_c"])]
        a["buy_no_disp"] = [_buy_disp(c, p) for c, p in zip(a["action_2_contract"], a["action_2_price_c"])]
        a["caveat_disp"] = a["blockers"].replace("", "—").fillna("—")
        # Time-to-resolution: hours until the soonest leg settles (sortable; "—" when unknown).
        _now = pd.Timestamp.now(tz="UTC")
        a["resolve_hrs"] = (pd.to_datetime(a["resolve_time"], utc=True, errors="coerce") - _now).dt.total_seconds() / 3600
        st.dataframe(
            a[["player", "tournament", "chain", "buy_yes_disp", "buy_no_disp", "exec_gap_c", "exec_min_size",
               "exec_max_profit_dollars", "resolve_hrs", "tradable_disp", "caveat_disp", "child_url", "parent_url"]],
            hide_index=True, width="stretch",
            column_config={
                "player": "Player",
                "tournament": "Tournament",
                "chain": "Chain",
                "buy_yes_disp": st.column_config.TextColumn("Buy YES", help="Buy YES on the broader contract @ its ask."),
                "buy_no_disp": st.column_config.TextColumn("Buy NO", help="Buy NO on the deeper contract @ the NO ask."),
                "exec_gap_c": st.column_config.NumberColumn("Gross edge (¢)", format="%.0f", help=help_for("Executable gap (¢)")),
                "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f"),
                "exec_max_profit_dollars": st.column_config.NumberColumn("Gross quoted profit ($)", format="$%.2f", help=help_for("Gross quoted profit ($)")),
                "resolve_hrs": st.column_config.NumberColumn("Resolves in (h)", format="%.0f", help="Hours until the soonest leg settles — how long capital is tied up. Lower = more urgent. Sort by this column."),
                "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                "caveat_disp": st.column_config.TextColumn("Caveat"),
                "child_url": st.column_config.LinkColumn("Deeper link", display_text="open ↗"),
                "parent_url": st.column_config.LinkColumn("Broader link", display_text="open ↗"),
            },
        )
        st.caption("Gross, before fees, slippage, latency, and partial-fill risk. (Thresholds do not filter this table.)")

        # Per-opportunity payoff detail: the money in every settlement state, with the floor visible.
        st.caption("Payoff by scenario — expand an opportunity to see the profit in every outcome:")
        for _, r in a.iterrows():
            floor = r.get("exec_gap_c")
            ftxt = f" — floor +{int(floor)}¢/unit" if pd.notna(floor) else ""
            with st.expander(f"💵 {r['player']} · {r['chain']}{ftxt}"):
                _payoff_block(r.to_dict(), units=r.get("exec_min_size"))

    # ---- Opportunity ranking chart (Actionable + Near-edge by gross edge) ----------
    rank = opportunity_ranking(actionable, near)
    if not rank.empty:
        st.caption("Opportunity ranking — gross edge in ¢ (Actionable in green, Near-edge in amber):")
        chart = (
            alt.Chart(rank).mark_bar().encode(
                x=alt.X("edge_c:Q", title="Gross edge (¢)"),
                y=alt.Y("label:N", sort="-x", title=None),
                color=alt.Color("kind:N", title="",
                                scale=alt.Scale(domain=["Actionable", "Near-edge"],
                                                range=["#2e7d32", "#f9a825"])),
                tooltip=[alt.Tooltip("label:N", title="Opportunity"),
                         alt.Tooltip("kind:N", title="Kind"),
                         alt.Tooltip("edge_c:Q", title="Edge (¢)")],
            )
        )
        st.altair_chart(chart, width="stretch")

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
            st.caption("These look interesting but **cannot be traded now** — buy prices are indicative only.")
            st.dataframe(
                b[["player", "tournament", "chain", "buy_yes_disp", "buy_no_disp", "blockers",
                   "tradable_disp", "child_url", "parent_url"]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player", "tournament": "Tournament", "chain": "Chain",
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
            st.caption("Within 5¢ of crossing, on firm Tight/OK quotes — **close to executable, not actionable.**")
            st.dataframe(
                near[["player", "tournament", "chain", "child_bid_pct", "parent_ask_pct", "executable_gap", "comp_quote_quality"]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player", "tournament": "Tournament", "chain": "Chain",
                    "child_bid_pct": st.column_config.NumberColumn("Deeper bid %", format="%.1f%%"),
                    "parent_ask_pct": st.column_config.NumberColumn("Broader ask %", format="%.1f%%"),
                    "executable_gap": st.column_config.NumberColumn("Gap (¢)", format="%.0f", help="Deeper bid − broader ask, in cents."),
                    "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                },
            )

    # ================================================================================
    # 6. Watchlist signals (toggle) — display inconsistencies + wide quotes
    # ================================================================================
    if show_signals:
        sig = pd.concat([display_sig, wide_sig]) if not (display_sig.empty and wide_sig.empty) else display_sig
        with st.expander(f"👀 Watchlist signals — display & wide ({len(sig)})", expanded=False):
            st.caption("Monitoring signals, **not trade instructions**.")
            if sig.empty:
                st.caption("No display or wide-quote signals.")
            else:
                st.dataframe(
                    sig[["player", "tournament", "chain", "status_label", "display_gap", "comp_quote_quality", "reason"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "player": "Player", "tournament": "Tournament", "chain": "Chain",
                        "status_label": st.column_config.TextColumn("Signal"),
                        "display_gap": st.column_config.NumberColumn("Display gap ¢", format="%.0f"),
                        "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                        "reason": "Reason",
                    },
                )

    # ================================================================================
    # 6b. Data-quality issues (toggle)
    # ================================================================================
    if show_dataq:
        with st.expander(f"🧹 Data-quality issues ({len(data_q)})", expanded=False):
            st.caption("Incomplete or unverifiable comparisons — not opportunities.")
            if data_q.empty:
                st.caption("None.")
            else:
                st.dataframe(
                    data_q[["player", "tournament", "chain", "status_label", "comp_quote_quality", "reason"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "player": "Player", "tournament": "Tournament", "chain": "Chain",
                        "status_label": st.column_config.TextColumn("Issue"),
                        "comp_quote_quality": st.column_config.TextColumn("Quote quality"),
                        "reason": "Reason",
                    },
                )

    # ================================================================================
    # 7. Selected player detail (collapsed) — driven by the Participant control
    # ================================================================================
    with st.expander("🔍 Selected player detail", expanded=False):
        if chosen_key is None:
            st.caption("Pick a **Participant** in the sidebar (Market universe) to see their ladder, "
                       "spreads, and contracts here.")
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

            # Price-ladder chart: bars should step DOWN broad→deep; a longer deeper (red) bar is an inversion.
            lplot = ladder_prices(chain_rows).dropna(subset=["display_pct"])
            if len(lplot) >= 2:
                ladder_chart = alt.Chart(lplot).mark_bar().encode(
                    x=alt.X("display_pct:Q", title="Display probability (%)"),
                    y=alt.Y("layer:N", sort=list(NODE_ORDER), title=None),
                    color=alt.Color("inverted:N", title="Inverted",
                                    scale=alt.Scale(domain=[False, True], range=["#1565c0", "#c62828"])),
                    tooltip=[alt.Tooltip("layer:N", title="Layer"),
                             alt.Tooltip("display_pct:Q", title="Display %", format=".1f"),
                             alt.Tooltip("inverted:N", title="Inverted")],
                )
                st.altair_chart(ladder_chart, width="stretch")
                st.caption("Containment ladder — prices should step **down** broad→deep. A longer **deeper** "
                           "bar (red) prices above its prerequisite: the visual signature of a violation.")

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
                    "quote": st.column_config.TextColumn("Quote"),
                    "status": "Status",
                    "inverted": st.column_config.CheckboxColumn("Inverted"),
                    "profit_per_unit": st.column_config.TextColumn("Profit/unit"),
                },
            )

            pchecks_all = (
                checks[checks["player_key"] == chosen_key]
                if "player_key" in checks.columns else checks.iloc[0:0]
            )
            pedge = pchecks_all[pchecks_all["status"].isin(ACTION_STATUSES | {"WIDE_QUOTE"})]
            if not pedge.empty:
                st.caption(
                    "What to do — ✅ executable rows: place both buys now. "
                    "⚠ display-only and size-missing rows: monitor only, no real order to execute against."
                )
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
                            f"${r['exec_max_profit_dollars']:.2f} — gross, before fees/slippage/latency."
                        )
                    if r["blockers"]:
                        lines.append(f"- **Why not:** {r['blockers']}")
                    st.markdown("\n".join(lines))
                    _payoff_block(r.to_dict(), units=r.get("exec_min_size"))

            sample = prows[0] if prows else {}
            if show_help:
                st.caption(
                    f"Mapping: **{sample.get('mapping_confidence', '?')}** confidence "
                    f"(key source: `{sample.get('player_key_source', '?')}`) — {sample.get('mapping_reason', '')}"
                )
            exp = expected_nodes(prows)
            if exp:
                exp_df = pd.DataFrame(exp)
                exp_df["found"] = exp_df["found"].map({True: "✅ found", False: "❌ MISSING"})
                st.caption("Expected progression layers (found vs missing):")
                st.dataframe(exp_df[["layer", "found", "source"]], hide_index=True, width="stretch",
                             column_config={"layer": "Layer", "found": "Status", "source": "Source"})
            else:
                st.caption("No advancement/winner contracts — progression ladder not applicable.")

            st.caption("All contracts for this player:")
            pdf2 = pdf.copy()
            pdf2["time_dt"] = pd.to_datetime(pdf2["time_value"], utc=True, errors="coerce")
            st.dataframe(
                pdf2[["contract", "category", "tournament", "stage", "opponent", "display_pct", "quote_quality",
                      "yes_bid_pct", "yes_ask_pct", "no_bid_pct", "no_ask_pct",
                      "spread_cents", "volume", "status", "time_dt", "kalshi_url"]],
                hide_index=True, width="stretch",
                column_config={
                    "contract": "Contract", "category": "Type", "tournament": "Tournament",
                    "stage": "Stage", "opponent": "Opponent",
                    "display_pct": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                    "quote_quality": "Quote",
                    "yes_bid_pct": st.column_config.NumberColumn("YES bid %", format="%.1f%%"),
                    "yes_ask_pct": st.column_config.NumberColumn("Buy YES %", format="%.1f%%"),
                    "no_bid_pct": st.column_config.NumberColumn("NO bid %", format="%.1f%%"),
                    "no_ask_pct": st.column_config.NumberColumn("Buy NO %", format="%.1f%%"),
                    "spread_cents": st.column_config.NumberColumn("Spread ¢", format="%.1f"),
                    "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                    "status": "Status",
                    "time_dt": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
                    "kalshi_url": st.column_config.LinkColumn("Kalshi", display_text="open ↗"),
                },
            )

            snapshot = {
                "player": chosen, "fetched_at": fetched_at, "tour": sample.get("tour"),
                "tournament": sample.get("tournament"),
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
            ec1.download_button("⬇ Export snapshot (JSON)", json.dumps(snapshot, indent=2, default=str),
                                file_name=f"{safe}_snapshot.json", mime="application/json", key="dl_snap")
            ec2.download_button("⬇ Export contracts (CSV)", pdf2.drop(columns=["time_dt"]).to_csv(index=False),
                                file_name=f"{safe}_contracts.csv", mime="text/csv", key="dl_pcsv")

    # ================================================================================
    # 8. Full diagnostics: all comparisons (collapsed) — from the membership universe
    #    (NOT thresholds), so finalized markets stay visible here. Outcome-status filter lives here.
    # ================================================================================
    with st.expander("🧪 Full diagnostics: all comparisons", expanded=False):
        status_choice = st.selectbox(
            "Outcome status", STATUS_GROUPS, index=0,
            format_func=lambda g: STATUS_GROUP_LABELS.get(g, g), key="full_diag_status",
            help="Diagnostic filter for this table only. Finalized markets remain visible here.",
        )
        view = universe.copy()
        if not view.empty and status_choice != "All":
            view = view[view["status_group"] == status_choice]
        if not view.empty:
            view = view.assign(_sort=view["status_group"].map(GROUP_SORT).fillna(9))
            view = view.sort_values(
                ["_sort", "executable_gap", "display_gap"], ascending=[True, False, False], na_position="last"
            ).drop(columns="_sort")
            st.caption(f"{len(view)} of {len(universe)} comparisons (after Outcome-status).")
            st.download_button("⬇ Download this view (CSV)", view.to_csv(index=False),
                               file_name="full_diagnostics.csv", mime="text/csv", key="dl_fulldiag")
            st.dataframe(
                view[[
                    "player", "tournament", "chain", "child_contract", "parent_contract", "child_display_pct",
                    "parent_display_pct", "child_bid_pct", "parent_ask_pct", "executable_gap",
                    "exec_min_size", "exec_max_profit_dollars", "display_gap", "status_label",
                    "tradable_disp", "rule_flag", "reason", "volume", "comp_quote_quality",
                    "child_ticker", "parent_ticker", "child_url", "parent_url",
                ]],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player", "tournament": "Tournament", "chain": "Chain",
                    "child_contract": "Deeper contract", "parent_contract": "Broader contract",
                    "child_display_pct": st.column_config.NumberColumn("Deeper %", format="%.1f%%"),
                    "parent_display_pct": st.column_config.NumberColumn("Broader %", format="%.1f%%"),
                    "child_bid_pct": st.column_config.NumberColumn("Deeper bid", format="%.1f%%"),
                    "parent_ask_pct": st.column_config.NumberColumn("Broader ask", format="%.1f%%"),
                    "executable_gap": st.column_config.NumberColumn("Executable gap (¢)", format="%.0f", help=help_for("Executable gap (¢)")),
                    "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f"),
                    "exec_max_profit_dollars": st.column_config.NumberColumn("Gross quoted profit ($)", format="$%.2f"),
                    "display_gap": st.column_config.NumberColumn("Display gap ¢", format="%.0f"),
                    "status_label": st.column_config.TextColumn("Status"),
                    "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                    "rule_flag": st.column_config.TextColumn("Rule caveat", help=help_for("Rule caveat")),
                    "reason": "Reason",
                    "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                    "comp_quote_quality": st.column_config.TextColumn("Quote quality", help=help_for("Quote quality")),
                    "child_ticker": "Deeper ticker", "parent_ticker": "Broader ticker",
                    "child_url": st.column_config.LinkColumn("Deeper link", display_text="open ↗"),
                    "parent_url": st.column_config.LinkColumn("Broader link", display_text="open ↗"),
                },
            )
        else:
            st.info("No comparisons match the current filters.")

    # ================================================================================
    # 9. Debug (collapsed)
    # ================================================================================
    with st.expander(f"🔧 Debug — {n_loaded}/{n_scanned} series loaded, {len(errors)} failed", expanded=False):
        if errors:
            st.warning("Series that failed to load (NOT silently skipped):")
            st.dataframe(pd.DataFrame(errors, columns=["series", "error"]), hide_index=True, width="stretch")
        else:
            st.success("All requested series loaded successfully.")
        if skipped_no_name > 0:
            st.caption(f"⚠ {skipped_no_name} market(s) skipped — `yes_sub_title` blank (no player name to display).")
        if n_excluded_unknown > 0:
            st.caption(f"ℹ {n_excluded_unknown} discovered series excluded — unrecognised contract kind (not in selected families).")

        if chosen_key is None:
            st.caption("Pick a Participant to see per-player raw fields, tournament source, and the link audit.")
        else:
            st.caption("Raw contract fields (incl. tournament grouping source) for this player:")
            st.dataframe(
                pdf[["series", "event_ticker", "event_title", "tournament", "tournament_source",
                     "kind", "stage", "player_key", "player_key_source", "competitor_uuid",
                     "mapping_confidence", "raw_yes_bid", "raw_yes_ask", "raw_no_bid", "raw_no_ask"]],
                hide_index=True, width="stretch",
            )
            st.caption("Comparison status + reason for this player:")
            st.dataframe(
                pchecks[["chain", "tournament", "status", "status_group", "rule_flag", "executable_gap", "display_gap", "reason"]],
                hide_index=True, width="stretch",
            )
            st.caption("Link audit — each URL and the contract identifiers it encodes:")
            st.dataframe(pd.DataFrame(link_audit(prows)), hide_index=True, width="stretch")

            dups = duplicate_node_sources(prows)
            if dups:
                st.caption("Duplicate node/source rows (a representative was chosen deterministically):")
                st.dataframe(pd.DataFrame(dups), hide_index=True, width="stretch")


render_dashboard()
