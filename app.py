"""Streamlit UI for the French Open Kalshi contract viewer.

Pick a player and see all of their French Open contracts in one table: a best-effort
**Display %** plus every underlying price component (YES mid / last / bid / ask), the
spread, and a quote-quality flag so wide or empty books are obvious.

On-demand snapshot: by default only the core French Open series are fetched; an optional
checkbox enables a full dynamic scan of every tennis series. Data caches for 60s.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import DEFAULT_SERIES
from data import build_contracts
from kalshi_client import KalshiError, discover_tennis_series, get_events_for_series

st.set_page_config(page_title="French Open Kalshi Viewer", page_icon="🎾", layout="wide")

# Noisy contract types hidden by default (still selectable in the category filter).
HIDDEN_BY_DEFAULT = {"Set winner", "Exact score"}


@st.cache_data(ttl=3600, show_spinner=False)
def discover() -> list[str]:
    """All tennis series tickers (cached longer — the series list rarely changes)."""
    return discover_tennis_series()


@st.cache_data(ttl=60, show_spinner="Fetching French Open markets…")
def load_contracts(full_scan: bool) -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int]:
    """Fetch the chosen series, build the per-player contract table.

    `full_scan=False` uses the fast DEFAULT_SERIES; `True` discovers every tennis series.
    Returns (df, fetched_at, errors, n_scanned, n_loaded). Failed series are returned so the
    debug expander can show them rather than dropping them silently.
    """
    tickers = discover() if full_scan else DEFAULT_SERIES
    results, errors = get_events_for_series(tickers)
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at, errors, len(tickers), len(results)


def render_debug(errors, n_loaded, n_scanned, player_df=None) -> None:
    """Debug expander: failed series + raw fields for the selected player's contracts."""
    with st.expander(f"🔧 Debug — {n_loaded}/{n_scanned} series loaded, {len(errors)} failed"):
        if errors:
            st.warning("Series that failed to load (NOT silently skipped):")
            st.dataframe(
                pd.DataFrame(errors, columns=["series", "error"]),
                hide_index=True, width="stretch",
            )
        else:
            st.success("All scanned series loaded successfully.")
        if player_df is not None and not player_df.empty:
            st.caption("Raw fields for the selected player's contracts:")
            debug_cols = [
                "series", "event_ticker", "market_ticker", "event_title", "market_title",
                "competition", "player_key", "player_key_source",
                "raw_yes_bid", "raw_yes_ask", "raw_last",
            ]
            st.dataframe(player_df[debug_cols], hide_index=True, width="stretch")


st.title("🎾 French Open — Kalshi Contract Viewer")

c1, c2 = st.columns([1, 3])
with c1:
    refresh = st.button("🔄 Refresh data")
with c2:
    full_scan = st.checkbox(
        "Scan all tennis series (slower)",
        value=False,
        help="Default fetches 6 core French Open series. Enable to dynamically discover every "
        "tennis series (more contract types, ~20s).",
    )
if refresh:
    discover.clear()
    load_contracts.clear()
    st.rerun()

try:
    df, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)
except KalshiError as exc:
    st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

scan_note = " (full scan)" if full_scan else ""
st.caption(f"Last refreshed: {fetched_at}  ·  {len(df)} contracts from {n_loaded}/{n_scanned} series{scan_note}")

if df.empty:
    st.info(
        "No open French Open contracts right now — markets may be between rounds or not yet "
        "listed. Try refreshing closer to match time."
    )
    render_debug(errors, n_loaded, n_scanned)
    st.stop()

# ---- Controls: player + contract type -----------------------------------------------
all_categories = sorted(df["category"].unique())
default_categories = [c for c in all_categories if c not in HIDDEN_BY_DEFAULT]

fc1, fc2 = st.columns([2, 3])
with fc1:
    chosen = st.selectbox("Player", sorted(df["player"].unique()))
with fc2:
    selected_categories = st.multiselect(
        "Contract type", all_categories, default=default_categories,
        help="Set-winner and exact-score markets are hidden by default.",
    )

player_df = df[(df["player"] == chosen) & (df["category"].isin(selected_categories))].copy()
player_df = player_df.sort_values("stage_rank")

st.subheader(f"{chosen} — {len(player_df)} French Open contract(s)")

if player_df.empty:
    st.info("No contracts for this player in the selected contract types.")
    render_debug(errors, n_loaded, n_scanned)
    st.stop()

# Parse the per-row time (match time for matches, else close/expiration) for display.
player_df["time_dt"] = pd.to_datetime(player_df["time_value"], utc=True, errors="coerce")

table_cols = [
    "contract", "category", "stage", "opponent",
    "display_pct", "quote_quality",
    "yes_mid_pct", "last_pct", "yes_bid_pct", "yes_ask_pct", "spread_cents",
    "volume", "status", "time_dt", "time_kind", "kalshi_url",
]
st.dataframe(
    player_df[table_cols],
    hide_index=True,
    width="stretch",
    column_config={
        "contract": "Contract",
        "category": "Type",
        "stage": "Stage",
        "opponent": "Opponent",
        "display_pct": st.column_config.NumberColumn(
            "Display %", format="%.1f%%", help="Midpoint if the spread is reasonable, else last price, else blank."
        ),
        "quote_quality": st.column_config.TextColumn("Quote", help="Tight / OK / Wide / Very wide / No quote"),
        "yes_mid_pct": st.column_config.NumberColumn("YES mid %", format="%.1f%%"),
        "last_pct": st.column_config.NumberColumn("Last %", format="%.1f%%"),
        "yes_bid_pct": st.column_config.NumberColumn("YES bid %", format="%.1f%%"),
        "yes_ask_pct": st.column_config.NumberColumn("YES ask %", format="%.1f%%"),
        "spread_cents": st.column_config.NumberColumn("Spread ¢", format="%.1f", help="YES ask − bid, in cents."),
        "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
        "status": "Status",
        "time_dt": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
        "time_kind": st.column_config.TextColumn("Time basis", help="Match time for matches; close/expiration otherwise."),
        "kalshi_url": st.column_config.LinkColumn("Kalshi", display_text="open ↗"),
    },
)

st.caption(
    "**Display %** uses the YES midpoint when the spread is reasonable, otherwise the last "
    "trade, otherwise blank. Check the **Quote** column — *Wide* / *Very wide* / *No quote* "
    "means the price is unreliable."
)

render_debug(errors, n_loaded, n_scanned, player_df)
