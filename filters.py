"""Market-universe and threshold filters for the dashboard's comparison rows.

Pure pandas over a `build_checks` DataFrame — NO Streamlit — so the filtering is independently
testable and the "thresholds spare Actionable now" rule can be enforced as two passes:

    universe    = apply_membership(checks, ...)      # narrows ALL sections (incl. Actionable now)
    thresholded = apply_thresholds(universe, ...)     # narrows everything EXCEPT Actionable now

Every filter treats an empty/None selection as "no filter", is NaN-safe, and returns a 0-row frame
*with its columns intact* on empty input (selecting on an empty frame would otherwise drop columns).
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

QUOTE_MODES = ["All", "Tight/OK only", "Include wide"]
STATUS_MODES = ["Any", "Active only"]


def apply_membership(
    df: pd.DataFrame,
    *,
    competitions: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
    layers: Iterable[str] | None = None,
    event_query: str = "",
    player_query: str = "",
    min_volume: float = 0,
) -> pd.DataFrame:
    """Narrow the *universe* of comparisons. Applied to every section, including Actionable now."""
    if df is None or df.empty:
        return df
    out = df
    if categories:
        cats = set(categories)
        # Keep a comparison if both legs are in-scope; "" = a leg with no category (e.g. MISSING_LAYER).
        out = out[
            (out["child_category"].isin(cats) | out["child_category"].eq(""))
            & (out["parent_category"].isin(cats) | out["parent_category"].eq(""))
        ]
    if competitions:
        out = out[out["competition"].isin(set(competitions))]
    if layers:
        sel = set(layers)
        out = out[out["layers"].apply(lambda L: bool(sel & set(L)) if isinstance(L, (set, tuple, list)) else False)]
    if event_query:
        q = event_query.strip().lower()
        ce = out["child_event_ticker"].fillna("").str.lower()
        pe = out["parent_event_ticker"].fillna("").str.lower()
        out = out[ce.str.contains(q, regex=False) | pe.str.contains(q, regex=False)]
    if player_query:
        q = player_query.strip().lower()
        out = out[out["player"].fillna("").str.lower().str.contains(q, regex=False)]
    if min_volume:
        out = out[out["volume"].fillna(0) >= min_volume]
    return out


def _both_active(row: dict[str, Any]) -> bool:
    """A comparison is tradable-now-eligible when its child leg is active and the parent leg is
    active (or absent, e.g. a single-sided unknown row)."""
    child_ok = str(row.get("child_status") or "") == "active"
    parent_status = str(row.get("parent_status") or "")
    parent_ok = parent_status in ("active", "")
    return child_ok and parent_ok


def apply_thresholds(
    df: pd.DataFrame,
    *,
    min_edge_c: float = 0,
    min_size: float = 0,
    quote_mode: str = "All",
    status_mode: str = "Any",
) -> pd.DataFrame:
    """Narrow by trade-quality thresholds. Applied to every section EXCEPT Actionable now."""
    if df is None or df.empty:
        return df
    out = df
    if min_edge_c:
        gap = pd.to_numeric(out["executable_gap"], errors="coerce")   # NaN gap -> dropped (NaN >= x is False)
        out = out[gap >= min_edge_c]
    if min_size:
        size = pd.to_numeric(out["exec_min_size"], errors="coerce").fillna(0)
        out = out[size >= min_size]
    if quote_mode == "Tight/OK only":
        out = out[out["comp_quote_quality"].isin(("Tight", "OK"))]
    elif quote_mode == "Include wide":
        out = out[out["comp_quote_quality"].isin(("Tight", "OK", "Wide", "Very wide"))]
    if status_mode == "Active only":
        out = out[out.apply(_both_active, axis=1)] if not out.empty else out
    return out
