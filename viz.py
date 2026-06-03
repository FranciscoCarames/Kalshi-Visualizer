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


def payoff_chart_data(pay: dict | None) -> pd.DataFrame:
    """Tidy frame for the per-opportunity payoff bar chart — the visual twin of the scenario table.

    Takes a ``consistency.scenario_payoffs`` result. One row per settlement scenario, in the same
    order. Columns: ``scenario`` (state label), ``payout_c`` and ``profit_c`` (per single unit, in
    cents), and ``role`` ("Floor" / "Bonus" / "Risk"). The app charts ``payout_c`` against a cost
    reference line — every bar clearing the line means profit in every state ("locked"). The "Risk"
    row (an equivalence pair's rules-diverge state) carries None payout and is dropped by the app
    before plotting, but is kept here so callers can see the full state set.
    """
    cols = ["scenario", "payout_c", "profit_c", "role"]
    if not pay or not pay.get("scenarios"):
        return pd.DataFrame(columns=cols)
    rows = [
        {
            "scenario": s.get("label", ""),
            "payout_c": s.get("payout_c"),
            "profit_c": s.get("profit_c"),
            "role": "Risk" if s.get("is_risk") else ("Bonus" if s.get("is_bonus") else "Floor"),
        }
        for s in pay["scenarios"]
    ]
    return pd.DataFrame(rows, columns=cols)


def ladder_prices(chain_rows: list[dict]) -> pd.DataFrame:
    """Tidy frame for the containment-ladder price chart, making inversions visible.

    Input is the player-detail progression chain — a list of ``{"Layer", "Display %", ...}`` dicts in
    broad→deep order (Reach Semifinal → Reach Final → Win Tournament). Prices should step DOWN as you
    go deeper (a deeper outcome can't be more likely than the prerequisite containing it). A layer
    priced ABOVE its nearest broader neighbour is flagged ``inverted`` — the visual signature of a
    consistency violation.

    Columns: ``layer`` (node name), ``display_pct`` (0–100, None if no price), ``rank`` (broad→deep
    order index), ``inverted`` (bool). NaN prices are normalised to None.
    """
    cols = ["layer", "display_pct", "rank", "inverted"]
    if not chain_rows:
        return pd.DataFrame(columns=cols)
    rows: list[dict] = []
    prev: float | None = None   # nearest broader layer's price
    for i, r in enumerate(chain_rows):
        pct = r.get("Display %")
        if pct is None or (isinstance(pct, float) and pct != pct):   # NaN-safe
            pct = None
        inverted = prev is not None and pct is not None and pct > prev
        rows.append({"layer": r.get("Layer", ""), "display_pct": pct, "rank": i, "inverted": bool(inverted)})
        if pct is not None:
            prev = pct
    return pd.DataFrame(rows, columns=cols)
