"""Pure chart-data preparation for the dashboard — NO Streamlit, so it is unit-testable.

The app renders the chart (Altair); this module only shapes the tidy frame it needs.
"""
from __future__ import annotations

import pandas as pd


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
