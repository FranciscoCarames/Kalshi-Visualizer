"""Pure observability builders for the dashboard + REST `/metrics` (PR 25a) — NiceGUI-/store-/
scan_manager-free, so both `api.py` (which must NOT import `engine`) and `webui/engine.py` can call them
after fetching their own inputs. The split mirrors `webui/viewmodel.py` + `webui/export.py`: the assembly
is here and unit-testable; the thin wrappers just supply the latest snapshot + scan-manager status.

Three builders:
- `build_metrics`   — a low-cardinality JSON monitoring payload (counters + scan heartbeat, NO per-row data).
- `build_failures`  — the meta failure lists that `engine.coverage()` curates away (for the debug UI, PR 25b).
- `build_category_breakdown` — honest contract-category counts: non-laddered vs low-confidence vs
  unsupported are SEPARATE axes, never lumped into one "unmapped".
"""
from __future__ import annotations

from typing import Any

import sports


def _meta(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return (snapshot or {}).get("meta") or {}


def build_metrics(*, snapshot: dict[str, Any] | None, scan_status: dict[str, Any] | None,
                  now_age: float | None = None, stale: bool | None = None,
                  now: float | None = None) -> dict[str, Any]:
    """A low-cardinality monitoring payload (no per-row data, no unbounded lists) assembled from the latest
    snapshot + the scan-manager status. Honest (zeros / None, never raises) when either input is empty.

    `now_age` is the snapshot's data age in seconds and `stale` its staleness — the caller computes both
    via `data.data_age_seconds` / `data.is_stale` (real clock). `now` (epoch seconds, caller-supplied) is
    used only to report the elapsed time of an in-progress scan; omitted → that field is None. Injecting
    these keeps this builder pure (no clock of its own)."""
    meta = _meta(snapshot)
    status = scan_status or {}
    last_result = status.get("last_result") or {}
    opps = (snapshot or {}).get("opportunities") or []
    since = status.get("since")
    in_progress = status.get("status") == "in_progress"
    elapsed = (now - since) if (in_progress and now is not None and since is not None) else None
    return {
        "snapshot_id": (snapshot or {}).get("snapshot_id"),
        "snapshot_age_seconds": now_age,
        "stale": stale,
        "opportunities": len(opps),
        "actionable": sum(1 for o in opps if o.get("bucket") == "actionable"),
        "contracts_scanned": meta.get("contracts_scanned", 0),
        "checks_tested": meta.get("checks_tested", 0),
        "kalshi_requests": meta.get("kalshi_requests", 0),
        "scanned_series": meta.get("scanned", 0),
        "failed_series": meta.get("failed", 0),
        # COUNT (not the list) — keeps the payload low-cardinality; the full lists live in build_failures.
        "sport_error_count": len(meta.get("sport_errors") or []),
        "scan_status": status.get("status") or "idle",
        "scan_since": since,
        "scan_in_progress_seconds": elapsed,
        # On a failed scan the manager stores {"error": …} as last_result; on success it's the coverage dict.
        "last_scan_error": last_result.get("error"),
        # The live viewer count is a NiceGUI client concept; the UI layer populates it in PR 25b.
        "viewer_count": None,
    }


def build_failures(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """The scan failure lists from the latest snapshot's meta — surfaced for the debug UI (PR 25b) because
    `engine.coverage()` curates them away. Empty lists / zeros when there is no scan / no meta."""
    meta = _meta(snapshot)
    return {
        "sport_errors": list(meta.get("sport_errors") or []),
        "series_errors": list(meta.get("series_errors") or []),
        "skipped_no_name": meta.get("skipped_no_name", 0),
        "excluded": meta.get("excluded", 0),
        "loaded": meta.get("loaded", 0),
        "scanned": meta.get("scanned", 0),
        "failed": meta.get("failed", 0),
    }


def build_category_breakdown(contract_rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Honest category counts over the stored contract rows. The honesty axes are SEPARATE counts, never a
    single lumped "unmapped":

    - `laddered` / `non_laddered` — `ladder_eligible` (a per-game/prop/award market is non-laddered, not a
      failure).
    - `low_confidence` — `mapping_confidence != "high"` (name-fallback identity rather than a stable UUID).
    - `unsupported` — the row's `series` resolves to the UNKNOWN sport (no SportConfig owns it).
    - `by_family` — count per `market_family`, so the non-laddered set is explainable.

    A row can land in more than one axis (e.g. a laddered row with low-confidence mapping), which is the
    point — each axis answers a different question. NaN-safe."""
    rows = list(contract_rows or [])
    laddered = sum(1 for r in rows if r.get("ladder_eligible"))
    low_conf = sum(1 for r in rows if (r.get("mapping_confidence") or "") != "high")
    unsupported = sum(1 for r in rows if sports.sport_for_series(r.get("series")).sport_id == "unknown")
    by_family: dict[str, int] = {}
    for r in rows:
        fam = r.get("market_family") or "—"
        by_family[fam] = by_family.get(fam, 0) + 1
    return {
        "total": len(rows),
        "laddered": laddered,
        "non_laddered": len(rows) - laddered,
        "low_confidence": low_conf,
        "unsupported": unsupported,
        "by_family": dict(sorted(by_family.items())),
    }
