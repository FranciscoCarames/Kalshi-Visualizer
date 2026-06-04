"""Streamlit UI for the Kalshi multi-sport viewer — trader-first executable-inconsistency dashboard.

Pick a Sport in the sidebar; the whole dashboard is driven by that sport's `SportConfig` (sports.py) —
its series, containment ladder, division control, families, and labels. Default view: what's actionable
now, what's blocked and why, what's near the edge. Non-laddered markets (per-game, props) surface in a
dedicated table. Diagnostics, per-player detail, and debug are collapsed below.

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

import dutchbook
import lifecycle
import scanner
import sports
import store
import synthetic_bundle
from config import (
    ALERT_PERSISTENCE_OPTIONS,
    BACKLOG_DEFAULT,
    BACKLOG_WINDOWS,
    FRESHNESS_TICK_SECONDS,
    FULL_SCAN_MIN_INTERVAL,
    REFRESH_DEFAULT_SECONDS,
    REFRESH_OPTIONS,
    REFRESH_TTL,
    SNAPSHOT_RETENTION_SECONDS,
    STALE_AFTER_SECONDS,
    TIMEZONE_DEFAULT,
    TIMEZONE_OPTIONS,
)
from consistency import (
    ACTION_STATUSES,
    bucket_of,
    build_checks,
    build_player_nodes,
    duplicate_node_sources,
    expected_nodes,
    layer_spreads,
    representative,
    scenario_payoffs,
)
from data import data_age_seconds, fmt_time, is_stale, link_audit
from fetch import fetch_contracts
from filters import QUOTE_MODES, STATUS_MODES, apply_membership, apply_thresholds
from glossary import help_for
from kalshi_client import KalshiError
from viz import ladder_prices, payoff_chart_data

# The selected sport drives the whole dashboard. It is held in session_state so set_page_config (which
# must be the FIRST Streamlit call) can read it before the sidebar renders the Sport selector. The
# selector (key="sport_id") updates it; changing it triggers a rerun that repaints the title.
st.session_state.setdefault("sport_id", sports.TENNIS.sport_id)
_cfg = sports.get_sport(st.session_state["sport_id"])
if _cfg.sport_id == "unknown":
    _cfg = sports.TENNIS
    st.session_state["sport_id"] = _cfg.sport_id

st.set_page_config(page_title=f"Kalshi {_cfg.label} Dashboard", page_icon=_cfg.emoji, layout="wide")

STATUS_GROUPS = ["All", "Clean", "Broken", "Warning", "Missing data", "Unknown relationship"]
GROUP_SORT = {"Broken": 0, "Warning": 1, "Missing data": 2, "Unknown relationship": 3, "Clean": 4}

STATUS_GROUP_LABELS = {
    "All": "All",
    "Clean": "Consistent",
    "Broken": "Executable edge",
    "Warning": "Theoretical / watchlist",
    "Missing data": "Incomplete data",
    "Unknown relationship": "Unverifiable",
}
# "Executable" = firm bid/ask + size (you can place both buys now). "Theoretical" = based on a display
# price (midpoint/last), not a firm, sized order — informative, not actionable.
STATUS_LABELS = {
    "CLEAN": "Consistent",
    "EXECUTABLE_VIOLATION": "Executable edge",
    "DISPLAY_VIOLATION": "Theoretical inconsistency",
    "WIDE_QUOTE": "Wide quote / watchlist",
    "MISSING_QUOTE": "Missing firm quote",
    "MISSING_LAYER": "Missing layer",
    "QUOTE_SIZE_MISSING": "Blocked: no size",
    "UNKNOWN_RELATIONSHIP": "Unverifiable",
}
TRADABLE_DISP = {
    "Yes": "✅ Yes",
    "Yes — rule-dependent": "⚠ Yes (verify rules)",
    "Review rules": "⚠ Review rules",
    "No": "❌ No",
}


@st.cache_data(ttl=REFRESH_TTL, show_spinner="Fetching markets…")
def load_contracts(families: tuple, scan_all: bool, sport_id: str) -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int, int, int]:
    # Thin Streamlit-cached wrapper over the pure fetch (fetch.py) — the API uses the same fetch path.
    # Family toggles are the only control that changes WHAT is fetched.
    return fetch_contracts(families, scan_all, sport_id)


def _buy_disp(contract: str, price_c) -> str:
    """Compact buy cell, e.g. 'Reach Final @ 46¢' (the column header carries Buy YES / Buy NO)."""
    if not contract:
        return ""
    price = f"{int(price_c)}¢" if pd.notna(price_c) else "—"
    return f"{contract} @ {price}"


def dutch_plan_text(row: dict) -> str:
    """The full buy-every-leg plan for a dutch-book finding. Lists ALL legs for an n-outcome (e.g. soccer
    3-way) finding from its `legs` list; falls back to the positional action_1/2 fields for 2-leg books."""
    legs = row.get("legs")
    if isinstance(legs, list) and legs:
        return "   ·   ".join(str(lg.get("text") or "—") for lg in legs)
    return "   ·   ".join(t for t in (row.get("action_1_text"), row.get("action_2_text")) if t)


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

# ---- Sidebar (part 1: before the fetch — sport + family + scan_all affect what's fetched) -----
with st.sidebar:
    st.header("Controls")
    st.radio(
        "Sport", [c.sport_id for c in sports.all_sports()],
        format_func=lambda sid: f"{sports.get_sport(sid).emoji} {sports.get_sport(sid).label}",
        key="sport_id", horizontal=True,
        help="Which sport's markets to load. Each sport has its own contracts, ladder, and filters.",
    )
    cfg = sports.get_sport(st.session_state["sport_id"])
    if st.button("🔄 Refresh data"):
        load_contracts.clear()   # clears the cached fetch (discovery is now inside fetch_contracts)
        st.rerun()
    all_contract_types = [v for k, v in cfg.category_labels.items() if k != "other"]
    selected_types = st.multiselect(
        "Contract family", all_contract_types, default=all_contract_types,
        key=f"families_{cfg.sport_id}",
        help="Which contract types to FETCH. Fewer families → fewer API requests.",
    )
    st.caption("ℹ️ Only contract-family toggles change what's **fetched**. Tournament, event and "
               "participant filters are **client-side** (no extra API requests).")

try:
    df_all, fetched_at, errors, n_scanned, n_loaded, _skipped, _excl = load_contracts(
        tuple(selected_types), scan_all, cfg.sport_id)
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

# Stash freshness inputs so the lightweight freshness fragment can re-render the age/stale strip on its
# OWN fast timer WITHOUT re-fetching (the heavy fetch stays on load_contracts' cache + the dashboard's
# refresh interval). render_dashboard() refreshes this dict each time it actually re-fetches.
st.session_state["_freshness"] = {
    "fetched_at": fetched_at, "errors": errors, "n_scanned": n_scanned, "n_loaded": n_loaded,
    "skipped_no_name": _skipped, "n_excluded_unknown": _excl,
}

# ---- Sidebar (part 2: after the fetch — options derived from the loaded data) --------------
with st.sidebar:
    # Division control is sport-specific: tennis splits by Tour (Women/Men); a sport with no division
    # concept (e.g. NBA) hides it entirely and applies no division filter.
    if cfg.divisions:
        division = st.radio(
            cfg.division_label, list(cfg.divisions), index=len(cfg.divisions) - 1,
            key=f"division_{cfg.sport_id}", help=f"Filter by {cfg.division_label.lower()}.",
        )
        div_label = division
        div_values = cfg.divisions[division]
        df = df_all[df_all["tour"].isin(div_values)] if not df_all.empty else df_all
    else:
        div_label = cfg.label
        div_values = None
        df = df_all

    t_opts = sorted(df["tournament"].dropna().unique().tolist()) if not df.empty else []
    sel_tournaments = st.multiselect(
        "Tournament / season", t_opts, default=t_opts, key=f"tournaments_{cfg.sport_id}",
        help="Client-side filter. Each tournament/season's ladders are grouped separately.",
    )

    auto_refresh = st.toggle("Auto-refresh", value=True,
                             help="Re-fetch on a timer; rate stays under the free-tier limit.")
    interval = st.selectbox("Refresh interval (seconds)", REFRESH_OPTIONS,
                            index=REFRESH_OPTIONS.index(REFRESH_DEFAULT_SECONDS))

    # Participant + event option maps (from the tour-filtered data).
    if not df.empty:
        # Only real competitors are selectable (soccer's Tie / non-participant outcomes carry
        # is_participant=False and must never appear as a participant). Guard the column for back-compat.
        _sel = df[df["is_participant"]] if "is_participant" in df.columns else df
        uniq = _sel.drop_duplicates("player_key")[["player_key", "player"]]
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
                                   key=f"participant_{cfg.sport_id}",
                                   help="Pick a participant to filter the whole dashboard to them and "
                                        "show their detail below. 'All' = no filter.")
        chosen_key = label_to_key.get(participant) if participant != "All" else None
        sel_event_labels = st.multiselect("Event / game", sorted(ev_label_to_tickers), default=[],
                                           key=f"events_{cfg.sport_id}")
        sel_events = set().union(*[ev_label_to_tickers[lbl] for lbl in sel_event_labels]) if sel_event_labels else set()
        sel_layers = st.multiselect("Stage / layer", list(cfg.ladder.node_order) + match_stages, default=[],
                                    key=f"layers_{cfg.sport_id}",
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
        show_unmapped = st.toggle("Show non-laddered / unmapped contracts", value=False,
                                  help="Contracts not part of a containment ladder (per-game, props, "
                                       "spreads, …). Off = ladder-only view.")

    with st.expander("Display"):
        tz_name = st.selectbox(
            "Time zone", TIMEZONE_OPTIONS, index=TIMEZONE_OPTIONS.index(TIMEZONE_DEFAULT),
            help="Display zone for all timestamps (default Lisbon). Comparison math is unaffected — "
                 "it is always exact UTC cents.",
        )
        show_codes = st.toggle(
            "Show IDs & codes", value=False,
            help="Reveal series/event/market (contract) tickers and participant IDs in the tables and "
                 "the per-player detail.",
        )
        show_advanced = st.toggle(
            "Advanced: diagnostics & debug", value=False,
            help="Show Full diagnostics and the Debug panel. Hidden by default.",
        )

    with st.expander("Advanced — data scope"):
        st.toggle(f"Scan all {cfg.label} series", key="scan_all_toggle",
                  help=f"ON (default): discover & fetch all {cfg.label} series for the enabled families. "
                       "OFF: only the core default series.")
        max_vol = int(df["volume"].fillna(0).max()) if not df.empty else 0
        min_vol = st.slider("Min traded volume (history)", 0, max_vol, 0,
                            help="Historical traded volume — distinct from 'Min available size'.") if max_vol > 0 else 0
        show_cross_sport = st.toggle(
            "Scan all sports (cross-sport view)", value=False, key="cross_sport",
            help="Adds one ranked table aggregating opportunities across ALL sports "
                 "(tennis + NBA + WNBA) and persists each scan. Heavier — fetches every sport.")
        show_help = st.toggle("Show explanations", value=True)

    # Full scan / cross-sport are heavy: warn and never auto-refresh faster than FULL_SCAN_MIN_INTERVAL.
    if scan_all or show_cross_sport:
        effective_interval = max(interval, FULL_SCAN_MIN_INTERVAL)
        if auto_refresh and interval < FULL_SCAN_MIN_INTERVAL:
            _why = "Scan-all" if scan_all else "Cross-sport scan"
            st.warning(f"⚠ {_why} is heavy; auto-refresh raised to {FULL_SCAN_MIN_INTERVAL}s "
                       f"(you selected {interval}s).")
    else:
        effective_interval = interval
    run_every = effective_interval if auto_refresh else None

players_filter = [chosen_key] if chosen_key else None

st.title(f"{cfg.emoji} Kalshi {cfg.label} — Executable Inconsistency Dashboard")


def _render_freshness_strip(fr: dict) -> None:
    """Render the always-visible data-freshness & coverage strip from a stashed inputs dict.
    Pure presentation; age is recomputed against the current time on every call (so it climbs)."""
    fa = fr.get("fetched_at")
    errors = fr.get("errors") or []
    n_loaded, n_scanned = fr.get("n_loaded", 0), fr.get("n_scanned", 0)
    n_excluded_unknown, skipped_no_name = fr.get("n_excluded_unknown", 0), fr.get("skipped_no_name", 0)
    age = data_age_seconds(fa)
    stale = is_stale(age, STALE_AFTER_SECONDS)
    if errors and n_loaded == 0:
        refresh_status = "❌ Failed"
    elif errors:
        refresh_status = f"⚠ Partial ({len(errors)} failed)"
    else:
        refresh_status = "✅ Success"
    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("Data time", fmt_time(fa, tz_name, fmt="%H:%M:%S %Z") or "—")
    fc2.metric("Data age", f"{int(age)}s" if age is not None else "—")
    fc3.metric("Refresh status", refresh_status)
    fc4.metric("Coverage", f"{n_loaded}/{n_scanned} series",
               help="Series loaded / scanned for the enabled contract families.")
    cov_bits = []
    if n_excluded_unknown:
        cov_bits.append(f"{n_excluded_unknown} series excluded (unrecognised kind)")
    if skipped_no_name:
        cov_bits.append(f"{skipped_no_name} markets skipped (no participant name)")
    if errors:
        cov_bits.append(f"{len(errors)} series failed")
    if cov_bits:
        st.caption("Coverage notes: " + " · ".join(cov_bits) + ". (Full list in Advanced → Debug.)")
    if stale:
        st.warning(
            f"⚠ Stale data — last refresh was {int(age)}s ago (threshold {STALE_AFTER_SECONDS}s). "
            "Auto-refresh may be off, or the last fetch failed."
        )


@st.fragment(run_every=FRESHNESS_TICK_SECONDS)
def render_freshness() -> None:
    """Re-render the freshness strip every few seconds so 'Data age' climbs and the stale warning
    appears even when the main auto-refresh is off — WITHOUT re-fetching market data (reads the
    stashed dict only)."""
    fr = st.session_state.get("_freshness")
    if not fr:
        st.caption("Loading market data…")
        return
    _render_freshness_strip(fr)


render_freshness()


@st.fragment(run_every=run_every)
def render_dashboard() -> None:
    try:
        df_all, fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown = load_contracts(
            tuple(selected_types), scan_all, cfg.sport_id)
    except KalshiError as exc:
        st.error(f"Couldn't refresh Kalshi data: {exc}")
        return
    # Refresh the freshness strip's inputs whenever we actually re-fetch (resets Data age to ~0).
    st.session_state["_freshness"] = {
        "fetched_at": fetched_at, "errors": errors, "n_scanned": n_scanned, "n_loaded": n_loaded,
        "skipped_no_name": skipped_no_name, "n_excluded_unknown": n_excluded_unknown,
    }
    df = df_all[df_all["tour"].isin(div_values)] if (div_values and not df_all.empty) else df_all
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

    # ---- Dutch-book / MECE findings (2-outcome match books) ----------------------------------
    # A check family SEPARATE from the containment ladder (dutchbook.py): a head-to-head whose two
    # player books can be covered for < 100¢. Computed on the same contracts and narrowed by the same
    # tournament / event / participant membership (empty selection = no filter, like apply_membership),
    # so it tracks the rest of the dashboard. `bucket_of` routes each finding (actionable / blocked).
    db_df = pd.DataFrame(dutchbook.find_dutch_books(df.to_dict("records")) if not df.empty else [])
    if not db_df.empty:
        if sel_tournaments:
            db_df = db_df[db_df["tournament"].isin(set(sel_tournaments))]
        if sel_events:
            db_df = db_df[db_df["event_ticker"].isin(set(sel_events))]
        if chosen_key is not None:
            db_df = db_df[(db_df["player_key_a"] == chosen_key) | (db_df["player_key_b"] == chosen_key)]
    if not db_df.empty:
        db_df = db_df.assign(
            bucket=db_df.apply(bucket_of, axis=1),
            tradable_disp=db_df["tradable_now"].map(TRADABLE_DISP).fillna(db_df["tradable_now"]),
        ).sort_values("exec_gap_c", ascending=False)

    # ---- Synthetic exact-score bundles (N-leg, vs the match-winner hedge) ---------------------
    # A SEPARATE family (synthetic_bundle.py): a player's MECE exact-score set replicates "they win the
    # match", priced against their match-winner. Always settlement-caveated (review-only, never tradable
    # as arbitrage). Narrowed by the same tournament / event / participant membership as the rest.
    sb_df = pd.DataFrame(synthetic_bundle.find_synthetic_bundles(df.to_dict("records")) if not df.empty else [])
    if not sb_df.empty:
        if sel_tournaments:
            sb_df = sb_df[sb_df["tournament"].isin(set(sel_tournaments))]
        if sel_events:
            sb_df = sb_df[sb_df["event_ticker"].isin(set(sel_events))]
        if chosen_key is not None:
            sb_df = sb_df[sb_df["player_key"] == chosen_key]
    if not sb_df.empty:
        sb_df = sb_df.assign(
            tradable_disp=sb_df["tradable_now"].map(TRADABLE_DISP).fillna(sb_df["tradable_now"]),
            bundle_text=sb_df["legs"].apply(lambda legs: " + ".join(x.get("text", "") for x in (legs or []))),
        ).sort_values("exec_gap_c", ascending=False)

    # Per-player frames for the detail/debug sections (driven by the Participant control).
    if chosen_key is not None:
        prows = df[df["player_key"] == chosen_key].to_dict("records")
        chosen = prows[0]["player"] if prows else participant
        pdf = df[df["player_key"] == chosen_key].copy().sort_values("stage_rank")
        pchecks = checks[checks["player_key"] == chosen_key] if "player_key" in checks.columns else checks.iloc[0:0]
    else:
        prows, chosen, pdf, pchecks = [], None, df.iloc[0:0], checks.iloc[0:0]

    # ================================================================================
    # 1. Header + data-freshness & coverage strip (ALWAYS visible — never behind Advanced)
    # ================================================================================
    scan_note = f" · all {cfg.label} (full scan)" if scan_all else " · core series"
    refresh_note = f" · auto-refresh {effective_interval}s" if auto_refresh else " · auto-refresh off"
    local_refreshed = fmt_time(fetched_at, tz_name) or fetched_at
    st.caption(
        f"Last refreshed {local_refreshed} · {cfg.emoji} {div_label} · {len(df)} contracts · "
        f"{len(checks)} comparisons{scan_note}{refresh_note}"
    )

    # (The data-freshness & coverage strip is rendered by render_freshness() above the dashboard, on
    # its own fast timer, so 'Data age' climbs live and the stale warning fires without re-fetching.)

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
    c6.metric("Last refreshed", fmt_time(fetched_at, tz_name, fmt="%H:%M:%S %Z") or fetched_at)

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
    # 2b. All loaded markets — cross-sport scanner (Stage 2; toggle-gated, off by default)
    # ================================================================================
    # An ADDITIVE view: the per-sport dashboard below is unchanged. When enabled, scanner.py
    # aggregates opportunities (containment + dutch-book) across EVERY sport into one ranked frame,
    # and persists the scan to the Stage-1 SQLite store. Interim Streamlit surfacing — replaced by
    # NiceGUI at Stage 5, so it's kept minimal. NOT all of Kalshi — only the loaded series.
    if show_cross_sport:
        def _cross_sport_fetch(sport_id: str) -> pd.DataFrame:
            cfg2 = sports.get_sport(sport_id)
            fams = tuple(sorted(set(cfg2.category_labels.values())))   # all families for this sport
            return load_contracts(fams, scan_all, sport_id)[0]

        def _snapshot_writer(fa, frame) -> None:
            # Persist once per distinct fetch tick; Streamlit reruns (widget clicks) must not duplicate.
            if st.session_state.get("_last_snap_fetched_at") == fa:
                return
            store.write_snapshot(fa, frame)
            st.session_state["_last_snap_fetched_at"] = fa

        st.subheader("🌐 All loaded markets — cross-sport")
        st.caption(f"All loaded markets ({'full scan' if scan_all else 'core series'}) across every "
                   "sport, ranked best→worst — NOT all of Kalshi. Gross of fees.")
        uni, sport_errs = scanner.unified_opportunities(
            _cross_sport_fetch, store_writer=_snapshot_writer, fetched_at=fetched_at)
        _sport_opts = [c.sport_id for c in sports.all_sports()]
        _sel_sports = st.multiselect(
            "Sports", _sport_opts, default=_sport_opts,
            format_func=lambda sid: f"{sports.get_sport(sid).emoji} {sports.get_sport(sid).label}",
            key="cross_sport_filter")
        uni = apply_membership(uni, sports=_sel_sports)

        # --- Lifecycle (Stage 3) — derived from the snapshot history just written -----------------
        # Safe normalization: latest_two() can be [] or length 1, so never unpack blindly.
        _pair = store.latest_two()
        _prev = _pair[0] if len(_pair) == 2 else None
        _cur = _pair[-1] if _pair else None
        _persist = st.selectbox("New-actionable banner persistence", list(ALERT_PERSISTENCE_OPTIONS),
                                index=0, key="alert_persist", help=help_for("New actionable"))
        _window_s = ALERT_PERSISTENCE_OPTIONS[_persist]
        if _window_s is None:
            _new_rows = lifecycle.new_actionable(_prev, _cur)
        else:   # full retained history so first-seen isn't clipped (see lifecycle.persisting_new_actionable)
            _new_rows = lifecycle.persisting_new_actionable(
                store.snapshots_since(SNAPSHOT_RETENTION_SECONDS), _window_s, now_ts=None)
        _new_ids = {r.get("opportunity_id") for r in _new_rows}
        if _new_ids:
            st.success(f"🆕 {len(_new_ids)} newly actionable — flagged in the table below.")
        if not uni.empty:
            uni = uni.assign(is_new=uni["opportunity_id"].isin(_new_ids))

        if sport_errs:
            st.warning("⚠ Some sports failed to load: "
                       + ", ".join(f"{e['sport']} ({e['error']})" for e in sport_errs))
        if uni.empty:
            st.info("No opportunities across the loaded sports right now.")
        else:
            st.download_button("⬇ Cross-sport opportunities (CSV)", uni.to_csv(index=False),
                               file_name="cross_sport_opportunities.csv", mime="text/csv",
                               key="dl_cross_sport")
            uni_disp = uni.assign(
                tradable_disp=uni["tradable_now"].map(TRADABLE_DISP).fillna(uni["tradable_now"]),
                source_disp=uni["source"].map(
                    {"containment": "Containment", "dutch_book": "Dutch book"}).fillna(uni["source"]),
            )
            _id_cols = ["opportunity_id"] if show_codes else []
            st.dataframe(
                uni_disp[["is_new", "sport_label", "source_disp", "name", "detail", "tournament",
                          "action_1_text", "action_2_text", "exec_gap_c", "exec_min_size",
                          "exec_max_profit_dollars", "tradable_disp", "blocked_reason"]
                         + _id_cols + ["url"]],
                hide_index=True, width="stretch",
                column_config={
                    "is_new": st.column_config.CheckboxColumn("New", help=help_for("New actionable")),
                    "sport_label": "Sport",
                    "source_disp": st.column_config.TextColumn(
                        "Type", help="Containment-ladder inconsistency or a dutch-book (MECE) arbitrage."),
                    "name": "Participant / match",
                    "detail": "Detail",
                    "tournament": "Tournament",
                    "action_1_text": st.column_config.TextColumn("Leg 1"),
                    "action_2_text": st.column_config.TextColumn("Leg 2"),
                    "exec_gap_c": st.column_config.NumberColumn(
                        "Gross edge (¢)", format="%.0f", help=help_for("Executable gap (¢)")),
                    "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f"),
                    "exec_max_profit_dollars": st.column_config.NumberColumn(
                        "Gross profit ($)", format="$%.2f", help=help_for("Gross quoted profit ($)")),
                    "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                    "blocked_reason": st.column_config.TextColumn("Caveat"),
                    "opportunity_id": st.column_config.TextColumn("Opportunity ID"),
                    "url": st.column_config.LinkColumn("Market", display_text="open ↗"),
                },
            )
            n_act = int((uni["bucket"] == "actionable").sum())
            st.caption(f"{n_act} actionable · {len(uni)} opportunities across {uni['sport'].nunique()} "
                       "sport(s). Gross, before fees/slippage. Scan persisted to the snapshot store.")

        def _ts_disp(ts) -> str:
            return fmt_time(datetime.fromtimestamp(ts, timezone.utc), tz_name, fmt="%H:%M:%S %Z") if ts else "—"

        # --- Recently-actionable backlog (§10) ----------------------------------------------------
        with st.expander("📉 Recently actionable (left the actionable set)"):
            _win = st.selectbox("Window", list(BACKLOG_WINDOWS),
                                index=list(BACKLOG_WINDOWS).index(BACKLOG_DEFAULT),
                                key="backlog_window", help=help_for("Recently actionable"))
            _win_s = BACKLOG_WINDOWS[_win]
            _hist = store.snapshots_since(_win_s if _win_s is not None else SNAPSHOT_RETENTION_SECONDS)
            _recent = lifecycle.recently_actionable(_hist)
            if not _recent:
                st.caption("Nothing left the actionable set in this window.")
            else:
                rdf = pd.DataFrame(_recent)
                rdf["became"] = [_ts_disp(t) for t in rdf["became_ts"]]
                rdf["left"] = [_ts_disp(t) for t in rdf["left_ts"]]
                rdf["mins"] = (pd.to_numeric(rdf["duration_s"], errors="coerce") / 60).round(1)
                st.download_button("⬇ Recently-actionable (CSV)", rdf.to_csv(index=False),
                                   file_name="recently_actionable.csv", mime="text/csv", key="dl_recent")
                st.dataframe(
                    rdf[["sport", "name", "became", "left", "mins", "reason_left", "last_edge_c",
                         "current_status", "url"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "sport": "Sport", "name": "Participant / match",
                        "became": "Became actionable", "left": "Left actionable",
                        "mins": st.column_config.NumberColumn("Lasted (min)", format="%.1f"),
                        "reason_left": "Why it left",
                        "last_edge_c": st.column_config.NumberColumn("Last edge (¢)", format="%.0f"),
                        "current_status": "Now", "url": st.column_config.LinkColumn("Market", display_text="open ↗"),
                    },
                )
                st.caption(f"{len(_recent)} opportunity(ies) were actionable in the last {_win} but aren't now.")

        # --- Changed-while-blocked (§9, minimal interim surfacing) ---------------------------------
        _changed = lifecycle.blocked_change(_prev, _cur)
        if _changed:
            with st.expander(f"🔁 Changed while blocked ({len(_changed)})"):
                cdf = pd.DataFrame([{
                    "opportunity_id": c["opportunity_id"],
                    "from": c["prev_bucket"], "to": c["cur_bucket"],
                    "what changed": ", ".join(c["changes"]) or ("entered/left blocked" if c["transitioned"] else ""),
                    "sport": (c["row"] or {}).get("sport"), "name": (c["row"] or {}).get("name"),
                    "caveat": (c["row"] or {}).get("blocked_reason"),
                } for c in _changed])
                st.dataframe(cdf, hide_index=True, width="stretch",
                             column_config={"what changed": st.column_config.TextColumn(
                                 "What changed", help=help_for("Changed while blocked"))})
        st.divider()

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
        _code_cols = ["player_key", "child_event_ticker", "child_ticker", "parent_ticker"] if show_codes else []
        _act_cols = (["player", "tournament", "chain", "buy_yes_disp", "buy_no_disp", "exec_gap_c",
                      "exec_min_size", "exec_max_profit_dollars", "resolve_hrs", "tradable_disp",
                      "caveat_disp"] + _code_cols + ["child_url", "parent_url"])
        st.dataframe(
            a[_act_cols],
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
                "player_key": st.column_config.TextColumn("Participant ID"),
                "child_event_ticker": st.column_config.TextColumn("Event code"),
                "child_ticker": st.column_config.TextColumn("Deeper ticker"),
                "parent_ticker": st.column_config.TextColumn("Broader ticker"),
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

    # ================================================================================
    # 3b. Dutch-book arbitrage (2-outcome match books) — a check family separate from
    #     the containment ladder. Both legs are the SAME side, so it gets its own table.
    # ================================================================================
    st.subheader("🎯 Dutch-book arbitrage — match, game & 3-way books")
    st.caption("Books where you can cover EVERY outcome for under the guaranteed payout floor (100¢ for a "
               "two-way match/game; **(n−1)×100¢** for an n-way overround) — a locked edge needing no model. "
               "Every leg is the **same** side (Buy YES on all, or Buy NO on all). Includes 3-way soccer "
               "World Cup games (Home / Away / Tie). Distinct from the containment ladder above; thresholds "
               "do not filter this.")
    if db_df.empty:
        st.success("No dutch books right now (each event's prices sum to ≥ its payout floor).")
    else:
        DIR_LABEL = {"underround": "Buy YES all legs (underround)", "overround": "Buy NO all legs (overround)"}
        d = db_df.assign(
            dir_disp=db_df["direction"].map(DIR_LABEL).fillna(db_df["direction"]),
            caveat_disp=db_df["blockers"].replace("", "—").fillna("—"),
            plan=db_df.apply(dutch_plan_text, axis=1),
        )
        st.dataframe(
            d[["match", "tournament", "dir_disp", "plan", "cost_c",
               "exec_gap_c", "exec_min_size", "exec_max_profit_dollars", "tradable_disp",
               "caveat_disp", "url"]],
            hide_index=True, width="stretch",
            column_config={
                "match": "Match",
                "tournament": "Tournament",
                "dir_disp": st.column_config.TextColumn(
                    "Trade", help="Every leg is the SAME side: Buy YES on all (underround) or Buy NO on "
                                  "all (overround). Covers 2-way match/game books AND 3-way soccer games."),
                "plan": st.column_config.TextColumn(
                    "Plan (all legs)", help="Buy every listed leg the same side; the locked edge holds "
                                            "whichever single outcome wins."),
                "cost_c": st.column_config.NumberColumn(
                    "Cost (¢)", format="%.0f", help="Combined cost of all legs. Payout floor = 100¢ "
                                                    "(underround) or (n−1)×100¢ (n-way overround)."),
                "exec_gap_c": st.column_config.NumberColumn(
                    "Locked edge (¢)", format="%.0f", help=help_for("Locked edge (¢)")),
                "exec_min_size": st.column_config.NumberColumn("Max units", format="%.0f"),
                "exec_max_profit_dollars": st.column_config.NumberColumn(
                    "Gross profit ($)", format="$%.2f", help=help_for("Gross quoted profit ($)")),
                "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                "caveat_disp": st.column_config.TextColumn("Caveat"),
                "url": st.column_config.LinkColumn("Market", display_text="open ↗"),
            },
        )
        n_live = int((db_df["tradable_now"] == "Yes").sum())
        st.caption(f"{n_live} tradable now · {len(db_df)} found. Gross, before fees, slippage, latency, "
                   "and partial-fill risk.")

    # ================================================================================
    # 3c. Synthetic-bundle discrepancies (exact-score set vs match-winner) — review only.
    #     N legs, all the SAME structure, so it gets its own table (not the 2-leg ladder).
    # ================================================================================
    st.subheader("🧩 Synthetic-bundle discrepancies — exact-score vs match-winner")
    st.caption("A player's exact-set-score contracts ({3-0, 3-1, 3-2} best-of-5; {2-0, 2-1} best-of-3) "
               "together replicate 'they win the match'; priced against their match-winner this can reveal "
               "a **gross pricing discrepancy**. **Not riskless** — an exact score is not the match-winner, "
               "and a retirement / no-ball-played settles the score legs to Fair Market Price while the "
               "winner settles cleanly. **Review the settlement rules before trading.** Gross, top-of-book.")
    if sb_df.empty:
        st.info("No synthetic-bundle discrepancies right now.")
    else:
        DIR_LABEL = {"forward": "Buy YES states + Buy NO winner", "reverse": "Buy NO states + Buy YES winner"}
        s = sb_df.assign(
            dir_disp=sb_df["direction"].map(DIR_LABEL).fillna(sb_df["direction"]),
            caveat_disp=sb_df["blocked_reason"].replace("", "—").fillna("—"),
        )
        st.dataframe(
            s[["player", "tournament", "dir_disp", "bundle_text", "cost_c", "exec_gap_c",
               "exec_min_size", "exec_max_profit_dollars", "tradable_disp", "caveat_disp", "url"]],
            hide_index=True, width="stretch",
            column_config={
                "player": "Player",
                "tournament": "Tournament",
                "dir_disp": st.column_config.TextColumn(
                    "Trade", help="Every leg is a BUY: all score states one side + the match-winner the other."),
                "bundle_text": st.column_config.TextColumn("Bundle (all legs)", help=help_for("Bundle (all legs)")),
                "cost_c": st.column_config.NumberColumn(
                    "Cost (¢)", format="%.0f", help="Combined cost of all legs (top-of-book, gross of fees)."),
                "exec_gap_c": st.column_config.NumberColumn(
                    "Gross discrepancy (¢)", format="%.0f", help=help_for("Bundle (all legs)")),
                "exec_min_size": st.column_config.NumberColumn(
                    "Max units", format="%.0f", help="Top-of-book size; full-depth fill not modeled."),
                "exec_max_profit_dollars": st.column_config.NumberColumn("Gross ($)", format="$%.2f"),
                "tradable_disp": st.column_config.TextColumn("Tradable now", help=help_for("Tradable now")),
                "caveat_disp": st.column_config.TextColumn("Caveat"),
                "url": st.column_config.LinkColumn("Match", display_text="open ↗"),
            },
        )
        st.caption(f"{len(sb_df)} found · all review-only (settlement-caveated, never riskless). "
                   "Gross, before fees and partial-fill risk.")

    # (Removed) The gross-edge ranking bar chart was misleading. The Actionable-now table above is
    # already sorted by gross edge and is the ranking surface; Stage 2 replaces it with a unified,
    # cross-sport sortable opportunity table.

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
            _b_code_cols = ["player_key", "child_event_ticker", "child_ticker", "parent_ticker"] if show_codes else []
            _b_cols = (["player", "tournament", "chain", "buy_yes_disp", "buy_no_disp", "blockers",
                        "tradable_disp"] + _b_code_cols + ["child_url", "parent_url"])
            st.dataframe(
                b[_b_cols],
                hide_index=True, width="stretch",
                column_config={
                    "player": "Player", "tournament": "Tournament", "chain": "Chain",
                    "buy_yes_disp": st.column_config.TextColumn("Buy YES (indicative)"),
                    "buy_no_disp": st.column_config.TextColumn("Buy NO (indicative)"),
                    "blockers": st.column_config.TextColumn("Why blocked"),
                    "tradable_disp": st.column_config.TextColumn("Tradable now"),
                    "player_key": st.column_config.TextColumn("Participant ID"),
                    "child_event_ticker": st.column_config.TextColumn("Event code"),
                    "child_ticker": st.column_config.TextColumn("Deeper ticker"),
                    "parent_ticker": st.column_config.TextColumn("Broader ticker"),
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
    # 6c. Non-laddered / unmapped contracts (toggle) — markets excluded from ladder checks
    # ================================================================================
    if show_unmapped:
        if not df.empty and "ladder_eligible" in df.columns:
            unmapped = df[~df["ladder_eligible"].astype(bool)]
        else:
            unmapped = df.iloc[0:0]
        with st.expander(f"🗂 Non-laddered / unmapped contracts ({len(unmapped)})", expanded=False):
            st.caption("Contracts that aren't part of a containment ladder (per-game, props, spreads, "
                       "awards, …). Shown for transparency — never silently dropped, never in ladder checks.")
            if unmapped.empty:
                st.caption("None — every loaded contract maps to the ladder.")
            else:
                fam_opts = sorted(unmapped["market_family"].dropna().unique().tolist())
                sel_fams = st.multiselect("Market family", fam_opts, default=fam_opts,
                                          key=f"unmapped_fams_{cfg.sport_id}")
                view = unmapped[unmapped["market_family"].isin(sel_fams)] if sel_fams else unmapped
                view = view.sort_values(["market_family", "volume"], ascending=[True, False],
                                        na_position="last")
                st.caption(f"{len(view)} of {len(unmapped)} non-laddered contracts.")
                st.dataframe(
                    view[["player", "contract", "market_family", "category", "classification_reason",
                          "display_pct", "volume", "status", "kalshi_url"]],
                    hide_index=True, width="stretch",
                    column_config={
                        "player": "Participant", "contract": "Contract",
                        "market_family": st.column_config.TextColumn("Family"),
                        "category": "Type",
                        "classification_reason": st.column_config.TextColumn("Why not laddered"),
                        "display_pct": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                        "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                        "status": "Status",
                        "kalshi_url": st.column_config.LinkColumn("Kalshi", display_text="open ↗"),
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
            for node in cfg.ladder.node_order:
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
                    y=alt.Y("layer:N", sort=list(cfg.ladder.node_order), title=None),
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
            _p_code_cols = (["series", "event_ticker", "market_ticker", "player_key", "player_key_source"]
                            if show_codes else [])
            _p_cols = (["contract", "category", "tournament", "stage", "opponent", "display_pct",
                        "quote_quality", "yes_bid_pct", "yes_ask_pct", "no_bid_pct", "no_ask_pct",
                        "spread_cents", "volume", "status", "time_dt"] + _p_code_cols + ["kalshi_url"])
            st.dataframe(
                pdf2[_p_cols],
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
                    "series": st.column_config.TextColumn("Series code"),
                    "event_ticker": st.column_config.TextColumn("Event code"),
                    "market_ticker": st.column_config.TextColumn("Market / contract ticker"),
                    "player_key": st.column_config.TextColumn("Participant ID"),
                    "player_key_source": st.column_config.TextColumn("ID source"),
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

    # Diagnostics + Debug are hidden by default; the sidebar "Advanced: diagnostics & debug" toggle
    # reveals them. They are the LAST two sections, so an early return keeps everything above always
    # visible without reindenting their bodies.
    if not show_advanced:
        return

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
