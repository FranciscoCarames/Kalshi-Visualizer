"""Contract fetch — the engine's data-acquisition step.

The FastAPI service (Stage 4) calls this to fetch contracts; it is pure I/O + parsing
(`kalshi_client` + `data` + `sports`), so the API and tests can call it directly. Family toggles are
the only thing that changes WHAT is fetched.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import sports
from data import build_contracts, series_for_families
from kalshi_client import discover_series_for_sport, get_events_for_series, get_series_meta


def fetch_contracts(families: tuple, scan_all: bool, sport_id: str) -> tuple[
        pd.DataFrame, str, list[tuple[str, str]], int, int, int, int, dict]:
    """Fetch one sport's per-player contracts.

    Returns the 8-tuple ``(df, fetched_at, errors, n_scanned, n_loaded, skipped_no_name,
    n_excluded_unknown, fee_rates)``: the contract DataFrame, a UTC ``fetched_at`` stamp, the list of
    ``(series, error)`` failures, the counts of series scanned / loaded, markets skipped for a blank
    name, discovered series excluded as non-core / "Other" family, and ``fee_rates`` =
    ``{UPPER_series: {"fee_type", "fee_multiplier"}}`` for this sport (DISPLAY-ONLY; rides the same
    /series GET as the titles, so no extra requests).
    """
    cfg = sports.get_sport(sport_id)
    all_series = discover_series_for_sport(cfg) if scan_all else list(cfg.default_series)
    tickers = series_for_families(all_series, families)
    # Discovered series excluded because their family is the catch-all "Other" bucket (props/awards/etc.).
    n_excluded_unknown = sum(
        1 for s in all_series if cfg.category_labels.get(cfg.family_of(s), "Other") == "Other"
    )
    results, errors = get_events_for_series(tickers)
    meta = get_series_meta([t for t, _ in results])     # {ticker: {title, fee_type, fee_multiplier}}
    fee_rates = {t.upper(): {"fee_type": m.get("fee_type"), "fee_multiplier": m.get("fee_multiplier")}
                 for t, m in meta.items()}
    rows: list[dict] = []
    diag: dict = {}
    for ticker, events in results:
        title = (meta.get(ticker) or {}).get("title", "")
        rows.extend(build_contracts(ticker, events, series_title=title, _diag=diag))
    df = pd.DataFrame(rows)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (df, fetched_at, errors, len(tickers), len(results),
            diag.get("skipped_no_name", 0), n_excluded_unknown, fee_rates)
