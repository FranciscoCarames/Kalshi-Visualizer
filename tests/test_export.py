"""Unit tests for webui.export (PR 23) — the pure ZIP/manifest builder (no NiceGUI, no store)."""
from __future__ import annotations

import csv
import io
import json
import zipfile

import scanner
from webui import export


def _opp(oid, **kw):
    row = {"opportunity_id": oid, "sport": "tennis", "bucket": "actionable", "exec_gap_c": 7,
           "legs": [{"text": "Buy YES — A @ 45¢"}, {"text": "Buy NO — B @ 48¢"}], "n_legs": 2}
    row.update(kw)
    return row


def test_csv_formula_injection_is_neutralized():
    """A Kalshi-supplied string starting with a spreadsheet formula trigger is quote-prefixed; numbers and
    benign strings are untouched."""
    assert export._cell("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1"
    assert export._cell("+1+1") == "'+1+1"
    assert export._cell("@SUM(A1)") == "'@SUM(A1)"
    assert export._cell("-5") == "'-5"               # a STRING "-5" is guarded
    assert export._cell(-5) == -5                     # a numeric -5 is left alone
    assert export._cell("Buy YES") == "Buy YES"
    # A JSON-encoded list/dict starts with [ or { — already formula-safe, so it is left unprefixed.
    assert export._cell(["=evil", 1]) == '["=evil", 1]'


def _open(blob: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(blob))


def _csv_rows(z: zipfile.ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8"))))


def test_zip_has_all_members():
    blob = export.build_export_zip(
        snapshot_id=5, fetched_at="2026-06-04 12:00:00 UTC", opportunities=[_opp("a"), _opp("b")],
        coverage={"scanned": 30, "contracts_scanned": 1493, "checks_tested": 1098, "kalshi_requests": 48},
        frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "row_count": 2,
                 "rows": [{"player": "A", "yes_bid_c": 45}, {"player": "B", "yes_bid_c": 48}]},
                {"sport": "nba", "frame_type": "dutchbook", "schema_version": 1, "row_count": 0, "rows": []}],
        backlog=[{"name": "X vs Y", "reason_left": "went blocked"}], backlog_window="1 hour",
        filters={"sports": ["tennis"]}, snapshot_range=[1, 5], exported_at="2026-06-04 12:05:00 UTC")
    z = _open(blob)
    names = set(z.namelist())
    assert {"opportunities.csv", "backlog.csv", "manifest.json"} <= names
    assert "frames/tennis_contracts.csv" in names
    assert "frames/nba_dutchbook.csv" not in names      # empty frame skipped


def test_opportunities_csv_header_first_and_legs_json():
    blob = export.build_export_zip(
        snapshot_id=1, fetched_at="t", opportunities=[_opp("a")], coverage={}, frames=[], backlog=[])
    z = _open(blob)
    text = z.read("opportunities.csv").decode("utf-8")
    header = text.splitlines()[0].split(",")
    assert header[:3] == scanner.UNIFIED_COLUMNS[:3]    # stable UNIFIED_COLUMNS order, header first
    rows = _csv_rows(z, "opportunities.csv")
    assert len(rows) == 1 and rows[0]["opportunity_id"] == "a"
    assert json.loads(rows[0]["legs"])[0]["text"] == "Buy YES — A @ 45¢"   # nested legs -> JSON string cell


def test_manifest_records_scope_filters_frames_backlog():
    blob = export.build_export_zip(
        snapshot_id=5, fetched_at="2026-06-04 12:00:00 UTC", opportunities=[_opp("a")],
        coverage={"scanned": 30, "loaded": 28, "failed": 2, "contracts_scanned": 1493,
                  "checks_tested": 1098, "kalshi_requests": 48},
        frames=[{"sport": "tennis", "frame_type": "checks", "schema_version": 2, "row_count": 9, "rows": [{"x": 1}]}],
        backlog=[{"name": "X"}], backlog_window="4 hours", filters={"sports": ["tennis"], "min_size": 50.0},
        snapshot_range=[2, 5])
    m = json.loads(_open(blob).read("manifest.json"))
    assert m["snapshot_id"] == 5 and m["fetched_at"] == "2026-06-04 12:00:00 UTC"
    assert m["scope"]["opportunities"] == 1 and m["scope"]["contracts_scanned"] == 1493
    assert m["scope"]["checks_tested"] == 1098 and m["scope"]["kalshi_requests"] == 48
    assert m["active_filters"] == {"sports": ["tennis"], "min_size": 50.0}
    assert m["frames"] == [{"sport": "tennis", "frame_type": "checks", "schema_version": 2,
                            "row_count": 9, "file": "frames/tennis_checks.csv"}]
    assert m["backlog"] == {"window": "4 hours", "rows": 1, "snapshot_range": [2, 5]}


def test_empty_inputs_still_valid_zip():
    blob = export.build_export_zip(snapshot_id=None, fetched_at=None, opportunities=[], coverage=None,
                                   frames=None, backlog=None)
    z = _open(blob)
    assert {"opportunities.csv", "backlog.csv", "manifest.json"} <= set(z.namelist())
    # opportunities.csv still has the full UNIFIED_COLUMNS header even with no rows.
    assert z.read("opportunities.csv").decode("utf-8").splitlines()[0].split(",")[0] == scanner.UNIFIED_COLUMNS[0]
    m = json.loads(z.read("manifest.json"))
    assert m["scope"]["opportunities"] == 0 and m["frames"] == [] and m["backlog"]["rows"] == 0


def test_rows_to_csv_is_nan_and_collection_safe():
    nan = float("nan")
    out = export._rows_to_csv([{"a": nan, "b": None, "c": [1, 2], "d": {"k": "v"}, "e": "x"}])
    r = next(csv.DictReader(io.StringIO(out)))
    assert r["a"] == "" and r["b"] == ""                 # NaN/None -> empty cell
    assert json.loads(r["c"]) == [1, 2] and json.loads(r["d"]) == {"k": "v"} and r["e"] == "x"
