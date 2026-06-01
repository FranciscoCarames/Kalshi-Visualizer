"""Streamlit UI for the French Open Kalshi contract viewer.

Pick a player and compare all of their contracts across the different matches (events)
they appear in, sorted by implied odds / match time / volume, with a quick bar chart.
On-demand snapshot: data is cached for 60s; the Refresh button forces a re-fetch.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import SERIES
from data import contracts_from_events, filter_french_open
from kalshi_client import KalshiError, get_events

st.set_page_config(page_title="French Open Kalshi Viewer", page_icon="🎾", layout="wide")


@st.cache_data(ttl=60, show_spinner="Fetching live Kalshi market data…")
def load_contracts() -> tuple[pd.DataFrame, str]:
    """Fetch -> filter to French Open -> build the per-player contract table."""
    rows: list[dict] = []
    for tour, series_ticker in SERIES.items():
        events = get_events(series_ticker, status="open")
        rows.extend(contracts_from_events(filter_french_open(events), tour))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at


st.title("🎾 French Open — Kalshi Contract Viewer")

if st.button("🔄 Refresh data"):
    load_contracts.clear()
    st.rerun()

try:
    df, fetched_at = load_contracts()
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

st.caption(f"Last refreshed: {fetched_at}  ·  {len(df)} contracts loaded")

if df.empty:
    st.info(
        "No open French Open match contracts right now — markets may be between rounds "
        "or not yet listed. Try refreshing closer to match time."
    )
    st.stop()

# ---- Filters -------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    tours = sorted(df["tour"].unique())
    selected_tours = st.multiselect("Tour", tours, default=tours)

    vol_series = df["volume"].fillna(0)
    max_vol = int(vol_series.max()) if len(vol_series) else 0
    min_vol = st.slider("Minimum volume", 0, max_vol, 0) if max_vol > 0 else 0

view = df[df["tour"].isin(selected_tours) & (df["volume"].fillna(0) >= min_vol)]

if view.empty:
    st.info("No contracts match the current filters.")
    st.stop()

# ---- Player selection ----------------------------------------------------------------
player_names = sorted(view["player"].unique())
chosen = st.selectbox("Player", player_names)
player_df = view[view["player"] == chosen].copy()

# ---- Sorting -------------------------------------------------------------------------
sort_options = {"Implied odds": "implied_pct", "Match time": "match_time", "Volume": "volume"}
c1, c2 = st.columns(2)
sort_by = c1.selectbox("Sort by", list(sort_options))
ascending = c2.toggle("Ascending", value=(sort_by == "Match time"))
player_df = player_df.sort_values(
    sort_options[sort_by], ascending=ascending, na_position="last"
)

st.subheader(f"{chosen} — {len(player_df)} contract(s) across events")

# ---- Table ---------------------------------------------------------------------------
table_cols = [
    "opponent", "round", "match", "implied_pct", "yes_bid", "yes_ask",
    "last_price", "volume", "open_interest", "status", "match_time", "market_ticker",
]
st.dataframe(
    player_df[table_cols],
    hide_index=True,
    use_container_width=True,
    column_config={
        "opponent": "Opponent",
        "round": "Round",
        "match": "Match",
        "implied_pct": st.column_config.NumberColumn("Implied win %", format="%.1f%%"),
        "yes_bid": st.column_config.NumberColumn("Yes bid", format="$%.2f"),
        "yes_ask": st.column_config.NumberColumn("Yes ask", format="$%.2f"),
        "last_price": st.column_config.NumberColumn("Last", format="$%.2f"),
        "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
        "open_interest": st.column_config.NumberColumn("Open interest", format="%.0f"),
        "status": "Status",
        "match_time": "Match time",
        "market_ticker": "Ticker",
    },
)

# ---- Chart ---------------------------------------------------------------------------
chart_df = player_df.dropna(subset=["implied_pct"]).copy()
if not chart_df.empty:
    labels = chart_df.apply(
        lambda r: f"{r['opponent'] or '—'}"
        + (f" ({r['round']})" if r["round"] else ""),
        axis=1,
    )
    chart_df = chart_df.assign(label=labels).set_index("label")
    st.bar_chart(chart_df["implied_pct"], y_label="Implied win %")
else:
    st.info("No priced contracts to chart for this player yet.")
