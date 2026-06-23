"""Capture hook for the forward-test harness: turn a completed scan's flagged opportunities into SIMULATED
paper positions and persist them (open-once).

Default-OFF. ``paper_enabled()`` mirrors ``scanner._conditional_blend_enabled`` — the flag is read at THIS
boundary (config default OR env ``PAPER_TRADING_ENABLED``), keeping ``config.py`` env-free. When the flag
is off, nothing here runs and the snapshot/scanner path is byte-for-byte unchanged.

This records simulated positions only; it places no orders and uses no credentials.
"""
from __future__ import annotations

import os
from typing import Any

import config
import paper_engine as pe
import paper_store


def paper_enabled() -> bool:
    """Forward-test recording gate (DEFAULT-OFF): on only when ``config.PAPER_TRADING_ENABLED`` is True or
    env ``PAPER_TRADING_ENABLED`` is truthy (read here so config.py stays env-free)."""
    return bool(config.PAPER_TRADING_ENABLED) or \
        os.getenv("PAPER_TRADING_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _records(unified: Any) -> list[dict[str, Any]]:
    """Rows as plain dicts (NaN-safe via the engine's own coercion). Accepts a pandas DataFrame or a list
    of dicts; anything else yields no rows."""
    if unified is None:
        return []
    if hasattr(unified, "to_dict"):
        return unified.to_dict("records")
    if isinstance(unified, list):
        return unified
    return []


def record_from_unified(unified: Any, snapshot_id: Any, *, opened_ts: float,
                        db_path: str | None = None,
                        fill_model: str = config.PAPER_FILL_MODEL) -> int:
    """Record paper positions for every flagged opportunity in a scan's unified frame that carries a
    buy-only plan (a non-empty ``legs`` list). Non-opportunity rows (CLEAN / display-only, no plan) are
    skipped; a plan with missing prices is recorded as ``unscorable`` (surfaced, never silently dropped).
    Returns the number of NEWLY-opened entries. Idempotent across scans (open-once on the entry key)."""
    entries: list[pe.PaperEntry] = []
    for row in _records(unified):
        legs = row.get("legs")
        if not isinstance(legs, list) or not legs:
            continue                                   # not an executable/speculative opportunity
        entry = pe.extract_entry(row, opened_ts=opened_ts, fill_model=fill_model)
        if entry is not None:
            entries.append(entry)
    return paper_store.record_entries(entries, snapshot_id, db_path=db_path)
