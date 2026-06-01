"""Streamlit UI for the French Open Kalshi viewer — Layer Consistency Checker.

Main area shows the layer-consistency table (a deeper outcome must not price above its
prerequisite) and a per-player detail view; the right-hand column holds controls/filters.

On-demand snapshot: by default only the core French Open series are fetched; an optional
checkbox enables a full dynamic scan. Data caches for 60s.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from config import DEFAULT_SERIES
from consistency import (
    MATCH_STAGE_TO_NODE,
    NODE_ORDER,
    build_checks,
    build_player_nodes,
    expected_nodes,
    layer_spreads,
    representative,
)
from data import build_contracts
from kalshi_client import KalshiError, discover_tennis_series, get_events_for_series

st.set_page_config(page_title="French Open Kalshi Viewer", page_icon="🎾", layout="wide")

TOUR_FILTER = {"Women": ["WTA"], "Men": ["ATP"], "Both": ["ATP", "WTA"]}
STATUS_GROUPS = ["All", "Clean", "Broken", "Warning", "Missing data", "Unknown relationship"]
GROUP_SORT = {"Broken": 0, "Warning": 1, "Missing data": 2, "Unknown relationship": 3, "Clean": 4}
ALL_CONTRACT_TYPES = ["Tournament winner", "Stage advancement", "Match result"]


@st.cache_data(ttl=3600, show_spinner=False)
def discover() -> list[str]:
    return discover_tennis_series()


@st.cache_data(ttl=60, show_spinner="Fetching French Open markets…")
def load_contracts(full_scan: bool) -> tuple[pd.DataFrame, str, list[tuple[str, str]], int, int]:
    tickers = discover() if full_scan else DEFAULT_SERIES
    results, errors = get_events_for_series(tickers)
    rows: list[dict] = []
    for ticker, events in results:
        rows.extend(build_contracts(ticker, events))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, fetched_at, errors, len(tickers), len(results)


st.title("🎾 French Open — Layer Consistency Checker")

main, controls = st.columns([3, 1])

# ---- Right-hand controls panel (part 1: drives the data load) ------------------------
with controls:
    st.header("Controls")
    if st.button("🔄 Refresh data"):
        discover.clear()
        load_contracts.clear()
        st.rerun()
    tournament = st.radio("Tournament", ["Women", "Men", "Both"], index=0)
    full_scan = st.checkbox(
        "Scan all tennis series (slower)", value=False,
        help="Default fetches 6 core French Open series. Enable to discover every tennis series (~20s).",
    )

try:
    df_all, fetched_at, errors, n_scanned, n_loaded = load_contracts(full_scan)
except KalshiError as exc:
    with main:
        st.error(f"Couldn't load Kalshi data: {exc}")
    st.stop()

df = df_all[df_all["tour"].isin(TOUR_FILTER[tournament])] if not df_all.empty else df_all
checks = build_checks(df)

# ---- Right-hand controls panel (part 2: filters) -------------------------------------
with controls:
    selected_types = st.multiselect(
        "Contract type", ALL_CONTRACT_TYPES,
        default=["Tournament winner", "Stage advancement"],
        help="Match result enables the match↔advancement alignment checks.",
    )
    status_choice = st.selectbox("Outcome status", STATUS_GROUPS, index=0)
    quote_choice = st.selectbox("Quote quality", ["All", "Tight/OK only", "Include wide"], index=0)
    max_vol = int(df["volume"].fillna(0).max()) if not df.empty else 0
    min_vol = st.slider("Minimum volume", 0, max_vol, 0) if max_vol > 0 else 0
    # Select by stable player_key (disambiguate the label only when a display name maps to
    # more than one key) so two players with the same display name are never conflated.
    if not df.empty:
        uniq = df.drop_duplicates("player_key")[["player_key", "player"]]
        name_counts = uniq["player"].value_counts()
        label_to_key = {}
        for _, r in uniq.iterrows():
            label = r["player"] if name_counts[r["player"]] == 1 else f'{r["player"]} [{str(r["player_key"])[:6]}]'
            label_to_key[label] = r["player_key"]
        chosen_label = st.selectbox("Player", sorted(label_to_key))
        chosen_key = label_to_key[chosen_label]
    else:
        chosen_key = None

# ---- Apply filters to the consistency table ------------------------------------------
def _passes_type(row) -> bool:
    cc, pc = row["child_category"], row["parent_category"]
    return (cc in selected_types or cc == "") and (pc in selected_types or pc == "")


def _passes_quote(row) -> bool:
    q = row["comp_quote_quality"]
    if quote_choice == "All":
        return True
    if quote_choice == "Tight/OK only":
        return q in ("Tight", "OK")
    return q in ("Tight", "OK", "Wide", "Very wide")  # Include wide


view = checks.copy()
if not view.empty:
    view = view[view.apply(_passes_type, axis=1)]
    if status_choice != "All":
        view = view[view["status_group"] == status_choice]
    view = view[view.apply(_passes_quote, axis=1)]
    view = view[view["volume"].fillna(0) >= min_vol]
    view = view.assign(_sort=view["status_group"].map(GROUP_SORT).fillna(9))
    view = view.sort_values(
        ["_sort", "executable_gap", "display_gap"], ascending=[True, False, False], na_position="last"
    ).drop(columns="_sort")

# ---- Main area -----------------------------------------------------------------------
with main:
    scan_note = " (full scan)" if full_scan else ""
    st.caption(
        f"Last refreshed: {fetched_at}  ·  {tournament}  ·  {len(df)} contracts, "
        f"{len(checks)} comparisons ({len(view)} shown){scan_note}"
    )

    st.subheader("Layer consistency")
    if view.empty:
        st.info("No comparisons match the current filters.")
    else:
        st.dataframe(
            view[[
                "player", "chain", "child_contract", "parent_contract", "child_display_pct",
                "parent_display_pct", "child_bid_pct", "parent_ask_pct", "executable_gap",
                "display_gap", "status", "rule_flag", "reason", "volume", "comp_quote_quality",
                "child_ticker", "parent_ticker", "child_url", "parent_url",
            ]],
            hide_index=True,
            width="stretch",
            column_config={
                "player": "Player",
                "chain": "Chain",
                "child_contract": "Child contract",
                "parent_contract": "Parent contract",
                "child_display_pct": st.column_config.NumberColumn("Child %", format="%.1f%%"),
                "parent_display_pct": st.column_config.NumberColumn("Parent %", format="%.1f%%"),
                "child_bid_pct": st.column_config.NumberColumn("Child bid", format="%.1f%%"),
                "parent_ask_pct": st.column_config.NumberColumn("Parent ask", format="%.1f%%"),
                "executable_gap": st.column_config.NumberColumn("Exec gap ¢", format="%.0f", help="child bid − parent ask, in cents; >0 = executable inconsistency."),
                "display_gap": st.column_config.NumberColumn("Display gap ¢", format="%.0f"),
                "status": "Status",
                "rule_flag": st.column_config.TextColumn("Rule check", help="Match-alignment pairs need settlement-rule verification."),
                "reason": "Reason",
                "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                "comp_quote_quality": "Quote",
                "child_ticker": "Child ticker",
                "parent_ticker": "Parent ticker",
                "child_url": st.column_config.LinkColumn("Child link", display_text="open ↗"),
                "parent_url": st.column_config.LinkColumn("Parent link", display_text="open ↗"),
            },
        )
        st.caption(
            "Only **EXECUTABLE_VIOLATION** (firm bid/ask cross with size) is *Broken*; display-only "
            "gaps are *Warnings*. Findings are **executable inconsistencies**, not arbitrage — "
            "match-alignment rows need their settlement rules verified (see Rule check)."
        )

    # ---- Player detail ---------------------------------------------------------------
    if chosen_key is not None:
        prows = df[df["player_key"] == chosen_key].to_dict("records")
        chosen = prows[0]["player"] if prows else chosen_label
        st.divider()
        st.subheader(f"Player detail — {chosen}")
        nodes = build_player_nodes(prows)

        # ---- Progression chain / ladder view (kept as the primary visualization) -----
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
        st.caption("Progression chain (broad → deep) — inspect the ladder prices first:")
        st.dataframe(
            pd.DataFrame(chain_rows), hide_index=True, width="stretch",
            column_config={
                "Display %": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                "Bid %": st.column_config.NumberColumn("Bid %", format="%.1f%%"),
                "Ask %": st.column_config.NumberColumn("Ask %", format="%.1f%%"),
            },
        )

        # ---- Raw stage-ladder spreads (directly under the ladder) --------------------
        spread_rows = layer_spreads(prows)
        st.caption("Raw stage-ladder spreads (adjacent layers) — broader minus deeper:")
        st.dataframe(
            pd.DataFrame(spread_rows)[
                ["from_layer", "to_layer", "from_pct", "to_pct", "spread_pct", "spread_cents", "quote", "status", "inverted"]
            ],
            hide_index=True, width="stretch",
            column_config={
                "from_layer": "From layer", "to_layer": "To layer",
                "from_pct": st.column_config.NumberColumn("From %", format="%.1f%%"),
                "to_pct": st.column_config.NumberColumn("To %", format="%.1f%%"),
                "spread_pct": st.column_config.NumberColumn("Spread (pp)", format="%.1f pp"),
                "spread_cents": st.column_config.NumberColumn("Spread (¢)", format="%.1f"),
                "quote": st.column_config.TextColumn("Quote", help="Worst quote quality of the two layers — most ladder legs are illiquid, so treat wide / No-quote spreads with caution."),
                "status": "Status",
                "inverted": st.column_config.CheckboxColumn("Inverted"),
            },
        )
        st.caption(
            "Raw price gaps only — not a probability model. **Quote** shows the worse of the two layers' "
            "book quality; most ladder markets are illiquid, so trust mainly Tight/OK rows. A "
            "**missing_price** row means a layer exists but has no usable price (shown blank). An "
            "**inverted** row (deeper priced above broader) is the same inconsistency flagged above."
        )

        # ---- Mapping confidence + expected-vs-found layers ---------------------------
        sample = prows[0] if prows else {}
        st.caption(
            f"Mapping: **{sample.get('mapping_confidence', '?')}** confidence "
            f"(key source: `{sample.get('player_key_source', '?')}`) — {sample.get('mapping_reason', '')}"
        )
        exp = expected_nodes(prows)
        exp_df = pd.DataFrame(exp)
        exp_df["found"] = exp_df["found"].map({True: "✅ found", False: "❌ MISSING"})
        st.caption("Expected progression layers (explicit found vs missing):")
        st.dataframe(
            exp_df[["layer", "found", "source"]],
            hide_index=True, width="stretch",
            column_config={"layer": "Layer", "found": "Status", "source": "Source"},
        )

        # Confident match contracts for this player.
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
        pdf = df[df["player_key"] == chosen_key].copy().sort_values("stage_rank")
        pdf["time_dt"] = pd.to_datetime(pdf["time_value"], utc=True, errors="coerce")
        pchecks = checks[checks["player_key"] == chosen_key] if "player_key" in checks.columns else checks.iloc[0:0]
        st.dataframe(
            pdf[["contract", "category", "stage", "opponent", "display_pct", "quote_quality",
                 "mapping_confidence", "yes_bid_pct", "yes_ask_pct", "spread_cents", "volume",
                 "status", "time_dt", "time_kind", "kalshi_url"]],
            hide_index=True, width="stretch",
            column_config={
                "contract": "Contract", "category": "Type", "stage": "Stage", "opponent": "Opponent",
                "display_pct": st.column_config.NumberColumn("Display %", format="%.1f%%"),
                "quote_quality": "Quote",
                "mapping_confidence": "Mapping",
                "yes_bid_pct": st.column_config.NumberColumn("YES bid %", format="%.1f%%"),
                "yes_ask_pct": st.column_config.NumberColumn("YES ask %", format="%.1f%%"),
                "spread_cents": st.column_config.NumberColumn("Spread ¢", format="%.1f"),
                "volume": st.column_config.NumberColumn("Volume", format="%.0f"),
                "status": "Status",
                "time_dt": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
                "time_kind": "Time basis",
                "kalshi_url": st.column_config.LinkColumn("Kalshi", display_text="open ↗"),
            },
        )

        # ---- Exportable per-player debug snapshot ------------------------------------
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

        # ---- Debug expander ----------------------------------------------------------
        with st.expander(f"🔧 Debug — {n_loaded}/{n_scanned} series loaded, {len(errors)} failed"):
            if errors:
                st.warning("Series that failed to load (NOT silently skipped):")
                st.dataframe(pd.DataFrame(errors, columns=["series", "error"]), hide_index=True, width="stretch")
            else:
                st.success("All scanned series loaded successfully.")

            st.caption("Raw contract fields for this player:")
            st.dataframe(
                pdf[["series", "event_ticker", "market_ticker", "event_title", "market_title",
                     "kind", "stage", "player_key", "player_key_source", "mapping_confidence",
                     "mapping_reason", "raw_yes_bid", "raw_yes_ask", "raw_last"]],
                hide_index=True, width="stretch",
            )

            st.caption("Comparison status + reason for this player:")
            st.dataframe(
                pchecks[["chain", "status", "status_group", "rule_flag", "executable_gap", "display_gap", "reason"]],
                hide_index=True, width="stretch",
            )
