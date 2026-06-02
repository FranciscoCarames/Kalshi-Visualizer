"""Pure chart-data preparation for the dashboard — NO Streamlit, so it is unit-testable.

The app renders the chart (Altair); this module only shapes the tidy frame it needs.
"""
from __future__ import annotations

import pandas as pd


def opportunity_ranking(actionable: pd.DataFrame, near: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """Tidy frame for the opportunity-ranking bar: one row per opportunity.

    Columns: ``label`` (player · tournament · chain), ``edge_c`` (gross edge in cents), ``kind``
    ("Actionable" uses the firm executable gap; "Near-edge" uses the signed executable gap, which is
    ≤ 0). Sorted by edge descending, capped at ``top``. Labels are made unique so the chart's y-axis
    never collapses two rows.
    """
    parts: list[pd.DataFrame] = []

    def _add(frame: pd.DataFrame, edge_col: str, kind: str) -> None:
        if frame is None or frame.empty or edge_col not in frame.columns:
            return
        f = frame.copy()
        f["edge_c"] = pd.to_numeric(f[edge_col], errors="coerce")
        f["kind"] = kind
        f["label"] = (f.get("player", "").astype(str) + " · "
                      + f.get("tournament", "").astype(str) + " · "
                      + f.get("chain", "").astype(str))
        parts.append(f[["label", "edge_c", "kind"]])

    _add(actionable, "exec_gap_c", "Actionable")
    _add(near, "executable_gap", "Near-edge")
    if not parts:
        return pd.DataFrame(columns=["label", "edge_c", "kind"])

    out = pd.concat(parts, ignore_index=True).dropna(subset=["edge_c"])
    out = out.sort_values("edge_c", ascending=False).head(top).reset_index(drop=True)
    # Disambiguate any duplicate labels so the bar chart keeps them as distinct rows.
    if out["label"].duplicated().any():
        dup = out.groupby("label").cumcount()
        out["label"] = out["label"].where(dup == 0, out["label"] + " (#" + (dup + 1).astype(str) + ")")
    return out
