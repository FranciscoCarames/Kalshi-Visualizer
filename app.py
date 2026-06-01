"""Streamlit UI for the French Open Kalshi contract viewer.

Pick a player and see ALL of their French Open contracts — match results, stage
advancement, the tournament winner market, and more — sorted by implied odds, tournament
stage, volume, or match time, with a quick bar chart.

On-demand snapshot: tennis series are discovered dynamically and their open French Open
events fetched concurrently. Data is cached for 60s; the Refresh button forces a re-fetch.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from data import build_contracts
from kalshi_client import KalshiError, discover_tennis_series, get_events_for_series

st.set_page_config(page_title="French Open Kalshi Viewer", page_icon="🎾", layout="wide")

# Contract categories hidden by default (still selectable) to keep the view uncluttered.
HIDDEN_BY_DEFAULT = {"Set winner", "Exact score"}
TOUR_LABEL = {"ATP": "Men (ATP)", "WTA": "Women (WTA)"}


@st.cache_data(ttl=3600, show_spinner=False)
def discover() -> list[str]:
    """Tennis series tickers to scan (cached longer — the series list rarely changes)."""
    return discover_tennis_series()


@st.cache_data(ttl=60, show_spinner="Discovering tennis series and fetching French Open markets…")
def load_contracts() -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int]:
    """Discover -> fetch all series concurrently -> build the per-player contract table.

    Returns (df, fetched_at, errors, n_scanned, n_loaded). `errors` lists every series that
    failed so the UI can show them rather than silently dropping them.
    """
    tickers = discover()
    results, errors = get_events_for_series(tickers)
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at, errors, len(tickers), len(results)


st.title("🎾 French Open — Kalshi Contract Viewer")

if st.button("🔄 Refresh data"):
    discover.clear()
    load_contracts.clear()
    st.rerun()

try:
    df, fetched_at, errors, n_scanned, n_loaded = load_contracts()
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

st.caption(f"Last refreshed: {fetched_at}  ·  {len(df)} contracts from {n_loaded}/{n_scanned} tennis series")

# ---- Debug: surface failed series (never silently skipped) ---------------------------
with st.expander(f"🔧 Debug — {n_loaded}/{n_scanned} series loaded, {len(errors)} failed"):
    if errors:
        st.warning("These series failed to load and were NOT included:")
        st.dataframe(
            pd.DataFrame(errors, columns=["series", "error"]),
            hide_index=True,
            width="stretch",
        )
    else:
        st.success("All scanned series loaded successfully.")
    if not df.empty:
        st.caption("French Open contracts contributed per series:")
        contrib = (
            df.groupby(["series", "category"]).size().reset_index(name="contracts")
            .sort_values("contracts", ascending=False)
        )
        st.dataframe(contrib, hide_index=True, width="stretch")

if df.empty:
    st.info(
        "No open French Open contracts right now — markets may be between rounds or not yet "
        "listed. Try refreshing closer to match time."
    )
    st.stop()

# ---- Filters -------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    tours = sorted(df["tour"].unique())
    selected_tours = st.multiselect(
        "Tour", tours, default=tours, format_func=lambda t: TOUR_LABEL.get(t, t)
    )

    all_categories = sorted(df["category"].unique())
    default_categories = [c for c in all_categories if c not in HIDDEN_BY_DEFAULT]
    selected_categories = st.multiselect(
        "Contract type", all_categories, default=default_categories,
        help="Set-winner and exact-score markets are hidden by default; add them here.",
    )

    vol_series = df["volume"].fillna(0)
    max_vol = int(vol_series.max()) if len(vol_series) else 0
    min_vol = st.slider("Minimum volume", 0, max_vol, 0) if max_vol > 0 else 0

view = df[
    df["tour"].isin(selected_tours)
    & df["category"].isin(selected_categories)
    & (df["volume"].fillna(0) >= min_vol)
]

if view.empty:
    st.info("No contracts match the current filters.")
    st.stop()

# ---- Player selection ----------------------------------------------------------------
player_names = sorted(view["player"].unique())
chosen = st.selectbox("Player", player_names)
player_df = view[view["player"] == chosen].copy()

# ---- Sorting -------------------------------------------------------------------------
sort_options = {
    "Implied odds": "implied_pct",
    "Tournament stage": "stage_rank",
    "Volume": "volume",
    "Match time": "match_time",
}
c1, c2 = st.columns(2)
sort_by = c1.selectbox("Sort by", list(sort_options))
# Sensible default direction per sort key (stage/time ascending, odds/volume descending).
ascending = c2.toggle("Ascending", value=sort_by in ("Tournament stage", "Match time"))
player_df = player_df.sort_values(
    sort_options[sort_by], ascending=ascending, na_position="last"
)

st.subheader(f"{chosen} — {len(player_df)} French Open contract(s)")

# ---- Table ---------------------------------------------------------------------------
table_cols = [
    "category", "contract", "stage", "opponent", "implied_pct", "yes_bid", "yes_ask",
    "last_price", "volume", "open_interest", "status", "match_time", "series", "market_ticker",
]
st.dataframe(
    player_df[table_cols],
    hide_index=True,
    width="stretch",
    column_config={
        "category": "Type",
        "contract": "Contract",
        "stage": "Stage",
        "opponent": "Opponent",
        "implied_pct": st.column_config.NumberColumn("Implied %", format="%.1f%%"),
        "yes_bid": st.column_config.NumberColumn("Yes bid", format="$%.2f"),
        "yes_ask": st.column_config.NumberColumn("Yes ask", format="$%.2f"),
        "last_price": st.column_config.NumberColumn("Last", format="$%.2f"),
        "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
        "open_interest": st.column_config.NumberColumn("Open int.", format="%.0f"),
        "status": "Status",
        "match_time": "Match time",
        "series": "Series",
        "market_ticker": "Ticker",
    },
)

# ---- Chart ---------------------------------------------------------------------------
chart_df = player_df.dropna(subset=["implied_pct"]).copy()
if not chart_df.empty:
    chart_df = chart_df.assign(label=chart_df["contract"]).set_index("label")
    st.bar_chart(chart_df["implied_pct"], y_label="Implied win %")
else:
    st.info("No priced contracts to chart for this player yet.")
