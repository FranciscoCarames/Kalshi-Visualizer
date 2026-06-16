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


def test_latest_snapshot_id_tracks_newest(tmp_path):
    db = _db(tmp_path)
    assert store.latest_snapshot_id(db_path=db) is None          # empty store -> None
    sid1 = store.write_snapshot(1000, [_opp("a")], db_path=db)
    assert store.latest_snapshot_id(db_path=db) == sid1
    sid2 = store.write_snapshot(2000, [_opp("b")], db_path=db)
    assert sid2 > sid1
    assert store.latest_snapshot_id(db_path=db) == sid2          # advances to the newest id


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


# --- Stage 4: schema v2 (meta) — both migration paths + latest() ----------------------
def _table_columns(db, table):
    con = sqlite3.connect(db)
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        con.close()


def _user_version(db):
    con = sqlite3.connect(db)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


def _has_table(db, name):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    finally:
        con.close()


def test_fresh_db_is_current_with_meta_frames_and_backlog(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)      # creates a fresh DB
    assert _user_version(db) == 4 == store.SCHEMA_VERSION
    assert "meta" in _table_columns(db, "snapshots")
    assert _has_table(db, "snapshot_frames")
    assert _has_table(db, "backlog_intervals")


def _build_legacy_db(db, version):
    """Hand-build a pre-current DB at `version` (1 = no meta, 2 = with meta, 3 = + snapshot_frames) +
    one snapshot + opp."""
    con = sqlite3.connect(db)
    try:
        meta_col = ", meta TEXT" if version >= 2 else ""
        con.executescript(
            f"CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, fetched_at TEXT NOT NULL, "
            f"fetched_ts REAL NOT NULL{meta_col});"
            "CREATE TABLE opportunities (snapshot_id INTEGER, opportunity_id TEXT, relationship_type TEXT, "
            "bucket TEXT, status TEXT, blocked_reason TEXT, data TEXT NOT NULL);")
        if version >= 3:
            con.executescript(store._FRAMES_SCHEMA)
        con.execute("INSERT INTO snapshots (fetched_at, fetched_ts) VALUES (?, ?)", ("old", 500.0))
        con.execute("INSERT INTO opportunities (snapshot_id, opportunity_id, data) VALUES (1, 'old1', ?)",
                    ('{"opportunity_id": "old1", "bucket": "actionable"}',))
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()
    finally:
        con.close()


def test_v1_db_upgrades_to_current(tmp_path):
    db = _db(tmp_path)
    _build_legacy_db(db, version=1)
    snap = store.latest(db_path=db)                              # any store call triggers _migrate: v1->v4
    assert _user_version(db) == 4
    assert "meta" in _table_columns(db, "snapshots") and _has_table(db, "snapshot_frames")
    assert _has_table(db, "backlog_intervals")
    assert snap["opportunities"][0]["opportunity_id"] == "old1"   # old row still readable
    assert snap["meta"] is None                                   # old snapshot has no meta


def test_v2_db_upgrades_to_current_and_backs_up(tmp_path):
    import os
    db = _db(tmp_path)
    _build_legacy_db(db, version=2)
    snap = store.latest(db_path=db)                              # v2 -> v4
    assert _user_version(db) == 4 and _has_table(db, "snapshot_frames")
    assert snap["opportunities"][0]["opportunity_id"] == "old1"   # old data intact
    # The pre-upgrade DB was backed up; the backup is itself a readable v2 SQLite file with the old row.
    backup = f"{db}.pre-v{store.SCHEMA_VERSION}-backup"
    assert os.path.exists(backup)
    con = sqlite3.connect(backup)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert con.execute("SELECT opportunity_id FROM opportunities").fetchone()[0] == "old1"
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='snapshot_frames'").fetchone() is None  # pre-v3
    finally:
        con.close()


def test_v3_db_upgrades_to_v4_preserving_data(tmp_path):
    db = _db(tmp_path)
    _build_legacy_db(db, version=3)
    assert not _has_table(db, "backlog_intervals")                # the v3 file has no backlog table
    snap = store.latest(db_path=db)                              # v3 -> v4 (pure additive table)
    assert _user_version(db) == 4 and _has_table(db, "backlog_intervals")
    assert snap["opportunities"][0]["opportunity_id"] == "old1"   # v3 data intact


def test_migration_failure_resets_to_fresh_preserving_backup(tmp_path, monkeypatch, capsys):
    import os
    db = _db(tmp_path)
    _build_legacy_db(db, version=2)
    # Force a forward step to fail; the store must back up, warn, and start a fresh current DB.
    monkeypatch.setattr(store, "_FRAMES_SCHEMA", "CREATE TABLE bad (")  # malformed -> DatabaseError
    store.write_snapshot(1000, [_opp("new")], db_path=db)
    assert _user_version(db) == store.SCHEMA_VERSION and _has_table(db, "snapshot_frames")
    assert os.path.exists(f"{db}.pre-v{store.SCHEMA_VERSION}-backup")     # original preserved
    assert f"migration v2->v{store.SCHEMA_VERSION} failed" in capsys.readouterr().out
    snap = store.latest(db_path=db)
    assert [o["opportunity_id"] for o in snap["opportunities"]] == ["new"]   # fresh DB has only new data


def test_connect_enables_wal(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        con.close()


def test_write_snapshot_meta_roundtrips_and_latest(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    store.write_snapshot(2000, [_opp("b")], meta={"scanned": 7, "failed": 1}, db_path=db)
    latest = store.latest(db_path=db)
    assert latest["fetched_ts"] == 2000.0                         # newest
    assert latest["meta"] == {"scanned": 7, "failed": 1}
    # an earlier snapshot without meta reads back None
    assert store.snapshots_since(10 ** 9, db_path=db)[0]["meta"] is None


# --- Stage 5 (PR 19): v3 snapshot_frames round-trip + partial load --------------------
def test_write_snapshot_frames_round_trip_type_safe(tmp_path):
    import datetime as _dt

    db = _db(tmp_path)
    # A frame with the tricky types the round-trip must normalize: NaN, tuple, None, datetime, nested.
    contracts = [
        {"player": "A", "yes_bid_c": 45, "display_pct": NAN, "tags": ("x", "y"),
         "opponent": None, "ts": _dt.datetime(2026, 6, 3, 12, 0, 0)},
        {"player": "B", "yes_bid_c": 48, "display_pct": 51.5, "tags": ("z",), "opponent": "A"},
    ]
    sid = store.write_snapshot(
        1000, [_opp("a")], db_path=db,
        frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": contracts},
                {"sport": "nba", "frame_type": "dutchbook", "schema_version": 1, "rows": []}])

    all_frames = store.load_frames(sid, db_path=db)
    assert {(f["sport"], f["frame_type"]) for f in all_frames} == {("tennis", "contracts"), ("nba", "dutchbook")}

    tennis = store.load_frames(sid, sport="tennis", frame_type="contracts", db_path=db)
    assert len(tennis) == 1 and tennis[0]["row_count"] == 2 and tennis[0]["schema_version"] == 1
    rows = tennis[0]["rows"]
    assert rows[0]["display_pct"] is None                # NaN -> JSON null -> None
    assert rows[0]["tags"] == ["x", "y"]                 # tuple -> list
    assert rows[0]["opponent"] is None                   # None stays None
    assert isinstance(rows[0]["ts"], str)                # datetime -> str (never a bare object)

    # partial load narrows correctly; an empty frame round-trips as row_count 0.
    assert store.load_frames(sid, sport="nba", db_path=db)[0]["row_count"] == 0
    assert store.load_frames(sid, sport="wnba", db_path=db) == []   # no such frame


def test_dataframe_frame_round_trips(tmp_path):
    import pandas as pd

    db = _db(tmp_path)
    df = pd.DataFrame([{"player": "A", "gap": 5.0}, {"player": "B", "gap": NAN}])
    sid = store.write_snapshot(1000, [_opp("a")], db_path=db,
                               frames=[{"sport": "tennis", "frame_type": "checks", "schema_version": 2, "rows": df}])
    f = store.load_frames(sid, frame_type="checks", db_path=db)[0]
    assert f["row_count"] == 2 and f["schema_version"] == 2
    assert f["rows"][1]["gap"] is None                   # NaN from a DataFrame -> None


def test_write_snapshot_without_frames_is_unchanged(tmp_path):
    db = _db(tmp_path)
    sid = store.write_snapshot(1000, [_opp("a")], db_path=db)   # no frames kwarg (back-compat)
    assert store.load_frames(sid, db_path=db) == []
    assert store.latest(db_path=db)["opportunities"][0]["opportunity_id"] == "a"


def test_retention_drops_frames_with_their_snapshot(tmp_path):
    db = _db(tmp_path)
    old = store.write_snapshot(1000, [_opp("a")], db_path=db,
                               frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1,
                                        "rows": [{"player": "A"}]}])
    # A newer snapshot far beyond the retention window evicts the old one (+ its frames).
    store.write_snapshot(1000 + config.SNAPSHOT_RETENTION_SECONDS + 10, [_opp("b")], db_path=db)
    assert store.load_frames(old, db_path=db) == []             # the old snapshot's frames are gone


# --- PR 20: heavy-frame retention size-tiers + "evidence expired" honesty --------------
def _frame(sport="tennis", ftype="contracts", n=1, pad=""):
    """A frame spec with `n` rows; `pad` inflates rows_json for the size-budget test."""
    return {"sport": sport, "frame_type": ftype, "schema_version": 1,
            "rows": [{"i": i, "pad": pad} for i in range(n)]}


def test_heavy_frames_kept_only_for_latest_n(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOT_FRAME_RETENTION_N", 3)
    db = _db(tmp_path)
    sids = []
    for t in range(5):                       # 5 snapshots, all within the 30h lean window
        sids.append(store.write_snapshot(1000 + t, [_opp(f"o{t}")], frames=[_frame()], db_path=db))

    # Lean tier untouched: every snapshot + its opportunities still load.
    assert len(store.snapshots_since(10 ** 9, db_path=db)) == 5
    # Heavy tier: only the latest 3 retain frames; the 2 oldest lost theirs but keep their opps.
    kept = [s for s in sids if store.load_frames(s, db_path=db)]
    assert kept == sids[-3:]
    for s in sids[:2]:
        assert store.load_frames(s, db_path=db) == []
        assert store.frame_status(s, db_path=db) == "expired"      # aged out by retention
    for s in sids[-3:]:
        assert store.frame_status(s, db_path=db) == "present"


def test_frame_status_absent_for_recent_opps_only_snapshot(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], frames=[_frame()], db_path=db)   # has frames
    sid2 = store.write_snapshot(2000, [_opp("b")], db_path=db)               # recent, NO frames
    # Within the latest-N window with no frames -> "absent" (never captured), not "expired".
    assert store.frame_status(sid2, db_path=db) == "absent"


def test_frame_size_budget_evicts_oldest_past_n(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOT_FRAME_RETENTION_N", 10)   # latest-N won't bind; the budget will
    db = _db(tmp_path)
    big = "x" * 2000
    sids = [store.write_snapshot(1000 + t, [_opp(f"o{t}")], frames=[_frame(n=1, pad=big)], db_path=db)
            for t in range(5)]
    # A budget smaller than 5 frames but >= 1 forces eviction down toward the newest.
    one_frame_bytes = len(store.load_frames(sids[-1], db_path=db)[0]["rows"][0]["pad"])  # ~2000
    monkeypatch.setattr(config, "SNAPSHOT_FRAME_DB_BUDGET_BYTES", 2500)
    newest = store.write_snapshot(2000, [_opp("new")], frames=[_frame(n=1, pad=big)], db_path=db)  # triggers retention
    assert store.load_frames(newest, db_path=db)                 # the newest frame-snapshot always survives
    con = sqlite3.connect(db)
    try:
        retained = con.execute("SELECT COALESCE(SUM(LENGTH(rows_json)),0) FROM snapshot_frames").fetchone()[0]
        n_frame_snaps = con.execute("SELECT COUNT(DISTINCT snapshot_id) FROM snapshot_frames").fetchone()[0]
    finally:
        con.close()
    assert retained <= config.SNAPSHOT_FRAME_DB_BUDGET_BYTES or n_frame_snaps == 1
    assert one_frame_bytes >= 2000 and n_frame_snaps < 6         # eviction happened (6 frame-snaps written)


def test_frame_retention_stats_and_no_op(tmp_path):
    db = _db(tmp_path)
    # A no-frame DB evicts nothing.
    con = store._connect(db)
    try:
        stats = store._apply_frame_retention(con, db)
    finally:
        con.close()
    assert stats["frame_snapshots_evicted"] == 0 and stats["frame_bytes"] == 0
    assert isinstance(stats["db_size_bytes"], int)               # real file -> a size in bytes


def test_no_frames_write_and_unknown_id_are_safe(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)          # no frames kwarg
    assert store.frame_status(999, db_path=db) == "absent"       # unknown id -> safe (no frames anywhere)


def _cframe(sport, rows):
    return {"sport": sport, "frame_type": "contracts", "schema_version": 1, "rows": rows}


def test_contract_frames_since_orders_groups_and_windows(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db, frames=[
        _cframe("tennis", [{"market_ticker": "T1", "yes_bid_c": 40}]),
        _cframe("nba", [{"market_ticker": "N1", "yes_bid_c": 10}])])
    store.write_snapshot(2000, [_opp("a")], db_path=db,
                         frames=[_cframe("tennis", [{"market_ticker": "T1", "yes_bid_c": 45}])])
    out = store.contract_frames_since(10 ** 9, db_path=db)
    assert [f["fetched_ts"] for f in out] == [1000.0, 2000.0]                 # oldest -> newest
    assert {r["market_ticker"] for r in out[0]["rows"]} == {"T1", "N1"}       # multi-sport grouped per snapshot
    assert out[1]["rows"][0]["yes_bid_c"] == 45
    near = store.contract_frames_since(500, db_path=db)                       # newest 2000, cutoff 1500
    assert [f["fetched_ts"] for f in near] == [2000.0]                        # the old snapshot is outside it
    assert store.contract_frames_since(10 ** 9, db_path=_db(tmp_path) + "x") == []   # empty store -> []


# --- Stage: v4 durable interval backlog ----------------------------------------------
def _bopp(oid, *, bucket="actionable", **extra):
    """A unified-shaped opportunity row with the metric fields the interval table tracks."""
    return _opp(oid, bucket=bucket, sport="tennis", name=oid, url="http://x",
                roi_pct=extra.get("roi"), best_case_profit_c=extra.get("best"),
                worst_case_profit_c=extra.get("worst"), settlement_caveat="",
                legs=extra.get("legs"))


def test_backlog_interval_opens_advances_and_peaks(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("a", roi=5, worst=-3)], db_path=db)
    store.write_snapshot(1010, [_bopp("a", roi=9, worst=-1)], db_path=db)   # advances; peaks grow
    rows = store.backlog_intervals(db_path=db)
    assert len(rows) == 1
    r = rows[0]
    assert r["is_open"] is True and r["left_ts"] is None
    assert r["first_seen_ts"] == 1000.0 and r["last_seen_ts"] == 1010.0
    assert r["peak_roi_pct"] == 9.0              # max(5, 9)
    assert r["worst_case_profit_c"] == -1.0      # least-negative (max) over the interval


def test_backlog_interval_closes_on_dropout(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("a")], db_path=db)
    store.write_snapshot(1010, [_bopp("b")], db_path=db)   # a drops out -> closes at 1010
    a = [r for r in store.backlog_intervals(db_path=db) if r["opportunity_id"] == "a"][0]
    assert a["is_open"] is False and a["left_ts"] == 1010.0
    assert a["duration_s"] == 0.0                          # first==last (seen in one snapshot)


def test_backlog_reappearance_opens_new_interval(tmp_path):
    # The audit-point-3 invariant: appear -> leave -> reappear must yield TWO intervals, not one merged row.
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("a", roi=2)], db_path=db)
    store.write_snapshot(1010, [_bopp("b")], db_path=db)            # a closes (left_ts=1010)
    store.write_snapshot(1020, [_bopp("a", roi=7)], db_path=db)     # a returns -> NEW open interval
    a_rows = [r for r in store.backlog_intervals(db_path=db) if r["opportunity_id"] == "a"]
    assert len(a_rows) == 2
    closed = [r for r in a_rows if not r["is_open"]][0]
    opened = [r for r in a_rows if r["is_open"]][0]
    assert closed["first_seen_ts"] == 1000.0 and closed["left_ts"] == 1010.0 and closed["peak_roi_pct"] == 2.0
    assert opened["first_seen_ts"] == 1020.0 and opened["left_ts"] is None and opened["peak_roi_pct"] == 7.0


def test_backlog_at_most_one_open_interval_per_key(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("a")], db_path=db)
    store.write_snapshot(1010, [_bopp("a")], db_path=db)
    con = sqlite3.connect(db)
    try:
        n_open = con.execute(
            "SELECT COUNT(*) FROM backlog_intervals WHERE opportunity_id='a' AND category='actionable' "
            "AND left_ts IS NULL").fetchone()[0]
    finally:
        con.close()
    assert n_open == 1                                    # the partial unique index holds


def test_backlog_category_derived_from_bucket(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [
        _bopp("act", bucket="actionable"),
        _bopp("rb", bucket="risk_budget"),
        _bopp("nm", bucket="near_miss"),
        _bopp("clean", bucket="clean"),          # untracked
        _bopp("blocked", bucket="blocked"),      # untracked
    ], db_path=db)
    cats = {r["opportunity_id"]: r["category"] for r in store.backlog_intervals(db_path=db)}
    assert cats == {"act": "actionable", "rb": "bounded_loss", "nm": "bounded_loss"}


def test_backlog_filters_category_and_open(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("a", bucket="actionable"), _bopp("b", bucket="risk_budget")], db_path=db)
    store.write_snapshot(1010, [_bopp("b", bucket="risk_budget")], db_path=db)   # a closes
    assert {r["opportunity_id"] for r in store.backlog_intervals(category="bounded_loss", db_path=db)} == {"b"}
    assert {r["opportunity_id"] for r in store.backlog_intervals(include_open=False, db_path=db)} == {"a"}


def test_backlog_retention_drops_old_closed_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKLOG_RETENTION_SECONDS", 100)
    db = _db(tmp_path)
    store.write_snapshot(1000, [_bopp("old")], db_path=db)
    store.write_snapshot(1010, [_bopp("keep_open")], db_path=db)   # old closes at 1010
    # Jump far ahead: old's left_ts (1010) is now > 100s behind the newest write -> dropped.
    store.write_snapshot(2000, [_bopp("keep_open")], db_path=db)
    ids = {r["opportunity_id"] for r in store.backlog_intervals(db_path=db)}
    assert "old" not in ids and "keep_open" in ids


def test_backlog_days_window(tmp_path):
    # The window filters by ACTIVITY time (left_ts / last_seen). a leaves early; a later query window
    # narrower than the gap drops it while still-recent intervals remain.
    db = _db(tmp_path)
    store.write_snapshot(0, [_bopp("a")], db_path=db)
    store.write_snapshot(100, [_bopp("b")], db_path=db)          # a closes at ts=100
    store.write_snapshot(2 * 86400, [_bopp("c")], db_path=db)    # 2 days later; b closes, a left long ago
    recent = store.backlog_intervals(days=1, db_path=db)         # 1-day activity window
    assert {r["opportunity_id"] for r in recent} == {"b", "c"}   # a (left at ts=100) is outside it
    assert {r["opportunity_id"] for r in store.backlog_intervals(db_path=db)} == {"a", "b", "c"}  # no window


def test_backlog_legs_round_trip(tmp_path):
    db = _db(tmp_path)
    legs = [{"side": "YES", "price_c": 45}, {"side": "NO", "price_c": 52}]
    store.write_snapshot(1000, [_bopp("a", legs=legs)], db_path=db)
    r = store.backlog_intervals(db_path=db)[0]
    assert r["last_legs"] == legs
    assert r["data"]["opportunity_id"] == "a"                    # full row JSON retained


def test_connect_initializes_schema_once_per_path(tmp_path, monkeypatch):
    # B2: migrate + index-build run only on the FIRST connect to a file path, not on every read connect.
    db = str(tmp_path / "snap.db")
    store._reset_init_cache()
    calls = []
    real = store._ensure_indexes
    monkeypatch.setattr(store, "_ensure_indexes", lambda conn: (calls.append(1), real(conn))[1])
    store._connect(db).close()
    store._connect(db).close()
    store._connect(db).close()
    assert len(calls) == 1                      # only the first connect built the indexes
    store._reset_init_cache()


# --- footprint: opportunity tiering + incremental auto_vacuum + footprint stats (PR footprint) ----------
def test_opp_tier_drops_old_speculative_keeps_latest_n_and_preserves_counts(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(config, "SNAPSHOT_RETENTION_SECONDS", 10**12)   # don't time-drop; isolate opp tier
    monkeypatch.setattr(config, "SNAPSHOT_OPP_TIER_ENABLED", True)
    monkeypatch.setattr(config, "SNAPSHOT_OPP_FULL_RETENTION_N", 3)
    monkeypatch.setattr(config, "SNAPSHOT_OPP_TIER_BUCKETS", ("no_structure", "data_quality", "near_miss"))
    for i in range(8):
        rows = [_opp(f"act-{i}", bucket="actionable"), _opp(f"clean-{i}", bucket="clean"),
                _opp(f"ns-{i}", bucket="no_structure"), _opp(f"dq-{i}", bucket="data_quality"),
                _opp(f"nm-{i}", bucket="near_miss")]
        store.write_snapshot(i * 1000, rows, db_path=db)

    conn = store._connect(db)
    try:
        ids = [r["id"] for r in conn.execute("SELECT id FROM snapshots ORDER BY fetched_ts DESC, id DESC")]
        # latest 3 keep ALL five buckets
        for sid in ids[:3]:
            buckets = {r["bucket"] for r in conn.execute(
                "SELECT DISTINCT bucket FROM opportunities WHERE snapshot_id = ?", (sid,))}
            assert buckets == {"actionable", "clean", "no_structure", "data_quality", "near_miss"}
        # older snapshots keep only the non-speculative buckets, and stamp counts into meta
        for sid in ids[3:]:
            buckets = {r["bucket"] for r in conn.execute(
                "SELECT DISTINCT bucket FROM opportunities WHERE snapshot_id = ?", (sid,))}
            assert buckets == {"actionable", "clean"}
            meta = conn.execute("SELECT meta FROM snapshots WHERE id = ?", (sid,)).fetchone()["meta"]
            assert '"tiered_opp_counts"' in meta and '"opp_tiered": true' in meta
    finally:
        conn.close()
    # the LIVE feed (newest snapshot) is always complete
    latest = store.latest(db_path=db)
    assert {o["bucket"] for o in latest["opportunities"]} == {
        "actionable", "clean", "no_structure", "data_quality", "near_miss"}


def test_opp_tier_disabled_keeps_every_bucket(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(config, "SNAPSHOT_RETENTION_SECONDS", 10**12)
    monkeypatch.setattr(config, "SNAPSHOT_OPP_TIER_ENABLED", False)
    monkeypatch.setattr(config, "SNAPSHOT_OPP_FULL_RETENTION_N", 1)
    for i in range(5):
        store.write_snapshot(i * 1000, [_opp(f"ns-{i}", bucket="no_structure")], db_path=db)
    conn = store._connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 5   # nothing tiered away
    finally:
        conn.close()


def test_fresh_db_uses_incremental_auto_vacuum(tmp_path):
    db = _db(tmp_path)
    conn = store._connect(db)
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2   # 2 == INCREMENTAL
    finally:
        conn.close()


def test_db_housekeeping_bounds_file_under_retention(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(config, "SNAPSHOT_RETENTION_SECONDS", 5000)    # ~6 snapshots at 1000s spacing
    monkeypatch.setattr(config, "SNAPSHOT_OPP_TIER_ENABLED", False)
    monkeypatch.setattr(config, "SNAPSHOT_HOUSEKEEPING_EVERY_N", 1)
    big = "z" * 2000
    rows = lambda i: [_opp(f"x-{i}-{j}", bucket="clean", blob=big) for j in range(120)]
    import os
    for i in range(15):
        store.write_snapshot(i * 1000, rows(i), db_path=db)
    peak = os.path.getsize(db)
    for i in range(15, 35):
        store.write_snapshot(i * 1000, rows(i), db_path=db)
    assert os.path.getsize(db) <= peak                                # incremental_vacuum keeps it bounded
    conn = store._connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] <= 8
    finally:
        conn.close()


def test_footprint_stats_reports_sizes_and_counts(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a"), _opp("b", bucket="clean")], db_path=db)
    stats = store.footprint_stats(db_path=db)
    assert stats["snapshot_count"] == 1
    assert stats["opportunity_rows"] == 2
    assert stats["db_size_bytes"] and stats["db_size_bytes"] > 0
    assert stats["freelist_pages"] is not None and stats["page_count"] > 0
