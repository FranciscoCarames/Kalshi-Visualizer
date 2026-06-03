"""Streamlit-free contract fetch — the engine's data-acquisition step.

Extracted from the body of the old `app.load_contracts` so BOTH the Streamlit app and the FastAPI
service (Stage 4) can fetch the same way. The only Streamlit concern (caching) stays in `app.py`'s thin
wrapper; this module is pure I/O + parsing (`kalshi_client` + `data` + `sports`), so the API and tests
can call it directly. Family toggles are the only thing that changes WHAT is fetched.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import sports
from data import build_contracts, series_for_families
from kalshi_client import discover_series_for_sport, get_events_for_series, get_series_titles


def fetch_contracts(families: tuple, scan_all: bool, sport_id: str) -> tuple[
        pd.DataFrame, str, list[tuple[str, str]], int, int, int, int]:
    """Fetch one sport's per-player contracts.

    Returns the 7-tuple ``(df, fetched_at, errors, n_scanned, n_loaded, skipped_no_name,
    n_excluded_unknown)``: the contract DataFrame, a UTC ``fetched_at`` stamp, the list of
    ``(series, error)`` failures, the counts of series scanned / loaded, markets skipped for a blank
    name, and discovered series excluded for an unrecognised family.
    """
    cfg = sports.get_sport(sport_id)
    all_series = discover_series_for_sport(cfg) if scan_all else list(cfg.default_series)
    tickers = series_for_families(all_series, families)
    # Discovered series excluded because their family is unrecognised (never in any family list).
    n_excluded_unknown = sum(
        1 for s in all_series if cfg.category_labels.get(cfg.family_of(s), "Other") == "Other"
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
