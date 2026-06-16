"""ZIP export of the current snapshot (PR 23) — pure, stdlib-only (`zipfile`/`csv`/`json`).

`build_export_zip(...) -> bytes` packages the filtered opportunities, the persisted per-sport evidence
frames (contracts/checks/dutchbook, from `store.load_frames`), the recently-actionable backlog, and a
`manifest.json` that makes the export reproducible (snapshot id, scope counters, active filters, per-frame
schema versions, backlog window/range). NO NiceGUI / store / network import — the dashboard gathers the
data and hands the bytes to `ui.download`; keeping the builder pure makes it unit-testable on content +
manifest.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any, Iterable

from scanner import UNIFIED_COLUMNS  # stable column order for opportunities.csv

# Leading characters a spreadsheet (Excel/Sheets/LibreOffice) may interpret as a FORMULA when it opens a
# CSV. A Kalshi-supplied string (player/contract/rules text) that starts with one of these could execute
# on open → CSV formula injection. We neutralize STRING cells by prefixing a single quote (numbers are left
# alone, so a negative value like -5 is unaffected). See docs/AUTH.md.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_guard(s: str) -> str:
    return "'" + s if s and s[0] in _CSV_FORMULA_PREFIXES else s


def _cell(v: Any) -> Any:
    """A CSV-safe scalar: NaN/None → empty; list/dict/tuple → compact JSON string; a string starting with a
    spreadsheet formula trigger is quote-prefixed (formula-injection defense); else as-is."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, (list, dict, tuple)):
        return _csv_guard(json.dumps(v, default=str))
    if isinstance(v, str):
        return _csv_guard(v)
    return v


def _ordered_union(rows: list[dict[str, Any]]) -> list[str]:
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return cols


def _rows_to_csv(rows: Iterable[dict[str, Any]], *, columns: list[str] | None = None) -> str:
    """Header-row-first CSV for a list of dict rows. `columns` pins a stable order (then any extra keys
    present are appended); without it, the ordered union of keys is used. NaN/None-safe; list/dict cells
    are JSON-encoded."""
    rows = list(rows or [])
    if columns is None:
        columns = _ordered_union(rows)
    else:
        columns = list(columns)
        seen = set(columns)
        for k in _ordered_union(rows):     # append any row keys not in the pinned order
            if k not in seen:
                seen.add(k)
                columns.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: _cell(r.get(c)) for c in columns})
    return buf.getvalue()


def _safe(name: Any) -> str:
    """A filesystem-safe fragment for a ZIP member name."""
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(name or "x")) or "x"


def build_basket_csv(opps: Iterable[dict[str, Any]]) -> bytes:
    """A standalone CSV (UTF-8 bytes) of a hand-picked NO-fade basket, in the stable `UNIFIED_COLUMNS`
    order. Pure + stdlib-only — the dashboard passes the basket's unified opp rows and downloads the bytes.
    Same column shape as `opportunities.csv` so the basket round-trips through the same tooling."""
    return _rows_to_csv(opps, columns=UNIFIED_COLUMNS).encode("utf-8")


def build_export_zip(*, snapshot_id: Any, fetched_at: Any, opportunities: Iterable[dict[str, Any]],
                     coverage: dict[str, Any] | None, frames: Iterable[dict[str, Any]] | None,
                     backlog: Iterable[dict[str, Any]] | None, backlog_window: Any = None,
                     filters: dict[str, Any] | None = None, snapshot_range: Any = None,
                     exported_at: Any = None) -> bytes:
    """Build the snapshot-export ZIP and return its bytes. Members: `opportunities.csv` (the FILTERED view,
    UNIFIED_COLUMNS order), `frames/<sport>_<frame_type>.csv` per non-empty persisted frame, `backlog.csv`,
    and `manifest.json`. Empty inputs still produce a valid ZIP with an honest manifest."""
    opps = list(opportunities or [])
    frames = list(frames or [])
    backlog = list(backlog or [])
    cov = coverage or {}

    manifest: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "fetched_at": fetched_at,
        "exported_at": exported_at,
        "scope": {
            "opportunities": len(opps),
            "scanned": cov.get("scanned", 0), "loaded": cov.get("loaded", 0),
            "failed": cov.get("failed", 0),
            "contracts_scanned": cov.get("contracts_scanned", 0),
            "checks_tested": cov.get("checks_tested", 0),
            "kalshi_requests": cov.get("kalshi_requests"),
        },
        "active_filters": dict(filters or {}),
        "frames": [],
        "backlog": {"window": backlog_window, "rows": len(backlog), "snapshot_range": snapshot_range},
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("opportunities.csv", _rows_to_csv(opps, columns=UNIFIED_COLUMNS))
        for f in frames:
            rows = f.get("rows") or []
            if not rows:
                continue
            fname = f"frames/{_safe(f.get('sport'))}_{_safe(f.get('frame_type'))}.csv"
            z.writestr(fname, _rows_to_csv(rows))
            manifest["frames"].append({
                "sport": f.get("sport"), "frame_type": f.get("frame_type"),
                "schema_version": f.get("schema_version"),
                "row_count": f.get("row_count") if f.get("row_count") is not None else len(rows),
                "file": fname,
            })
        z.writestr("backlog.csv", _rows_to_csv(backlog))
        z.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
    return buf.getvalue()
