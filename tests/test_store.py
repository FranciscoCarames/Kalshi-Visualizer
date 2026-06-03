"""Unit tests for the SQLite snapshot store (Stage 1). Run against a tmp file — no network, no
shared state. Covers round-trip, latest_two ordering, snapshots_since window boundaries, retention,
schema migration/versioning, and JSON safety (NaN / tuples / DataFrame input)."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

import config
import store

NAN = float("nan")


def _db(tmp_path):
    return str(tmp_path / "snap.db")


def _opp(oid, *, bucket="actionable", status="EXECUTABLE_VIOLATION", blocked_reason="",
         relationship_type="containment_adjacent", **extra):
    row = {
        "opportunity_id": oid,
        "relationship_type": relationship_type,
        "bucket": bucket,
        "status": status,
        "blocked_reason": blocked_reason,
    }
    row.update(extra)
    return row


def test_write_and_latest_two_round_trip(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a"), _opp("b")], db_path=db)
    store.write_snapshot(2000, [_opp("a"), _opp("c")], db_path=db)

    pair = store.latest_two(db_path=db)
    assert [s["fetched_ts"] for s in pair] == [1000.0, 2000.0]   # oldest -> newest
    assert {o["opportunity_id"] for o in pair[0]["opportunities"]} == {"a", "b"}
    assert {o["opportunity_id"] for o in pair[1]["opportunities"]} == {"a", "c"}


def test_latest_two_handles_empty_and_single(tmp_path):
    db = _db(tmp_path)
    assert store.latest_two(db_path=db) == []
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    only = store.latest_two(db_path=db)
    assert len(only) == 1 and only[0]["opportunities"][0]["opportunity_id"] == "a"


def test_full_row_round_trips_via_json_blob(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a", reason="child bid > parent ask", exec_gap_c=3)], db_path=db)
    row = store.latest_two(db_path=db)[0]["opportunities"][0]
    # Promoted columns AND arbitrary extra fields survive.
    assert row["status"] == "EXECUTABLE_VIOLATION"
    assert row["reason"] == "child bid > parent ask"
    assert row["exec_gap_c"] == 3


def test_nan_and_tuple_are_json_safe(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a", display_gap=NAN, layers=("Reach Final", "Win Tournament"))],
                         db_path=db)
    row = store.latest_two(db_path=db)[0]["opportunities"][0]
    assert row["display_gap"] is None                       # NaN -> null
    assert row["layers"] == ["Reach Final", "Win Tournament"]  # tuple -> list


def test_empty_snapshot_is_recorded(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [], db_path=db)
    snaps = store.latest_two(db_path=db)
    assert len(snaps) == 1 and snaps[0]["opportunities"] == []


def test_dataframe_input_is_accepted(tmp_path):
    pd = pytest.importorskip("pandas")
    db = _db(tmp_path)
    df = pd.DataFrame([_opp("a"), _opp("b")])
    sid = store.write_snapshot(1000, df, db_path=db)
    assert isinstance(sid, int)
    assert len(store.latest_two(db_path=db)[0]["opportunities"]) == 2


def test_snapshots_since_window_boundary_is_inclusive(tmp_path):
    db = _db(tmp_path)
    for ts in (0, 100, 200):
        store.write_snapshot(ts, [_opp(f"o{ts}")], db_path=db)
    # Newest is 200; window 100 -> cutoff 100 (inclusive) -> {100, 200}, not 0.
    got = store.snapshots_since(100, db_path=db)
    assert [s["fetched_ts"] for s in got] == [100.0, 200.0]
    # timedelta is accepted too.
    assert [s["fetched_ts"] for s in store.snapshots_since(timedelta(seconds=100), db_path=db)] \
        == [100.0, 200.0]


def test_snapshots_since_empty_db(tmp_path):
    assert store.snapshots_since(100, db_path=_db(tmp_path)) == []


def test_retention_drops_snapshots_older_than_window(tmp_path):
    db = _db(tmp_path)
    keep = config.SNAPSHOT_RETENTION_SECONDS
    store.write_snapshot(1000, [_opp("old")], db_path=db)
    # A second write far enough ahead pushes the first beyond the retention window -> dropped.
    store.write_snapshot(1000 + keep + 10, [_opp("new")], db_path=db)
    remaining = store.snapshots_since(10 * keep, db_path=db)   # wide window: show everything kept
    assert len(remaining) == 1
    assert remaining[0]["opportunities"][0]["opportunity_id"] == "new"


def test_retention_keeps_snapshots_within_window(tmp_path):
    db = _db(tmp_path)
    keep = config.SNAPSHOT_RETENTION_SECONDS
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    store.write_snapshot(1000 + keep - 10, [_opp("b")], db_path=db)   # within window
    assert len(store.snapshots_since(10 * keep, db_path=db)) == 2


def test_migration_sets_user_version_and_reopen_works(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    finally:
        con.close()
    # Reopening the existing file (no re-create) still reads prior data.
    store.write_snapshot(2000, [_opp("b")], db_path=db)
    assert len(store.latest_two(db_path=db)) == 2


def test_schema_newer_than_supported_raises(tmp_path):
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    try:
        con.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
        con.commit()
    finally:
        con.close()
    with pytest.raises(RuntimeError):
        store.latest_two(db_path=db)


def test_to_epoch_parses_display_format():
    # The exact string load_contracts stamps fetched_at with.
    assert store._to_epoch("2026-06-03 12:00:00 UTC") == pytest.approx(
        store._to_epoch("2026-06-03T12:00:00+00:00"))


def test_to_epoch_rejects_unparseable():
    with pytest.raises(ValueError):
        store._to_epoch("not a timestamp")
    with pytest.raises(ValueError):
        store._to_epoch(True)   # bool guarded (not treated as epoch 1)


# --- Stage 1 integration: REAL engine output (build_checks + find_dutch_books) through the store ---
# Unit tests above use synthetic dicts; this proves the ACTUAL row shapes — pandas numpy dtypes, the
# tuple `layers` column, and NaN gaps from MISSING_LAYER rows — survive the JSON round-trip with their
# opportunity_id / relationship_type / bucket / blocked_reason intact.
def _contract(player, key, kind, stage, dc):
    return {"player": player, "player_key": key, "kind": kind, "stage": stage,
            "contract": f"{kind}-{stage}", "display_pct": float(dc), "display_c": dc,
            "yes_bid_c": max(dc - 1, 0), "yes_ask_c": min(dc + 1, 100),
            "yes_bid_pct": float(max(dc - 1, 0)), "yes_ask_pct": float(min(dc + 1, 100)),
            "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight",
            "volume": 10, "market_ticker": f"T-{key}-{stage}", "kalshi_url": "x",
            "series": "KXWTAADVANCE", "tournament": "French Open"}


def test_real_build_checks_frame_round_trips(tmp_path):
    import pandas as pd

    import consistency
    # Final + Champion only -> a real comparison PLUS a MISSING_LAYER row (NaN display_gap, tuple layers).
    df = pd.DataFrame([_contract("Y", "uuid-y", "advance", "Final", 40),
                       _contract("Y", "uuid-y", "winner", "Champion", 20)])
    checks = consistency.build_checks(df)
    assert checks["status"].eq("MISSING_LAYER").any()        # the NaN-bearing case is present

    db = _db(tmp_path)
    store.write_snapshot("2026-06-03 12:00:00 UTC", checks, db_path=db)
    back = store.latest_two(db_path=db)[0]["opportunities"]

    assert {o["opportunity_id"] for o in back} == set(checks["opportunity_id"])
    ml = next(o for o in back if o["status"] == "MISSING_LAYER")
    assert ml["display_gap"] is None                          # numpy NaN -> JSON null -> None
    assert isinstance(ml["layers"], list)                     # tuple -> list
    for o in back:                                            # iff invariant survives persistence
        assert bool(o["blocked_reason"]) == (o["bucket"] == "blocked")


def test_real_dutch_book_finding_round_trips(tmp_path):
    import dutchbook

    def mk(player, key, ya):
        return {"series": "KXATPMATCH", "event_ticker": "E1", "kind": "match", "player": player,
                "player_key": key, "contract": f"Beat opp ({player})", "tournament": "French Open",
                "tour": "ATP", "yes_bid_c": ya - 2, "yes_ask_c": ya, "no_ask_c": None,
                "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
                "market_ticker": f"T-{key}", "kalshi_url": "x", "event_title": "M", "time_value": None}
    findings = dutchbook.find_dutch_books([mk("Alcaraz", "alc", 45), mk("Sinner", "sin", 48)])
    assert findings and findings[0]["relationship_type"] == "dutch_book"

    db = _db(tmp_path)
    store.write_snapshot("2026-06-03 12:00:00 UTC", findings, db_path=db)
    back = store.latest_two(db_path=db)[0]["opportunities"]
    assert back[0]["opportunity_id"] == findings[0]["opportunity_id"]
    assert back[0]["bucket"] == "actionable" and back[0]["blocked_reason"] == ""
