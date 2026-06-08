"""PR1 read-path optimization: prove the actionable-narrowed store reads + optimized lifecycle siblings
are SEMANTICALLY IDENTICAL to the full-history path, plus the new store APIs' edge cases and that the
perf indexes are actually built/used. Run against a tmp DB — no network, no shared state."""
from __future__ import annotations

import config
import lifecycle
import store
from webui import engine


def _db(tmp_path):
    return str(tmp_path / "snap.db")


def _opp(oid, *, bucket="actionable", status="EXECUTABLE_VIOLATION", market_status="active", **extra):
    """A persisted unified row carrying the fields lifecycle §10/§8 read."""
    row = {
        "opportunity_id": oid,
        "relationship_type": "containment_adjacent",
        "bucket": bucket,
        "status": status,
        "blocked_reason": extra.get("blocked_reason", ""),
        "market_status": market_status,
        "sport": extra.get("sport", "tennis"),
        "name": extra.get("name", oid.upper()),
        "url": extra.get("url", f"https://kalshi.com/{oid}"),
        "exec_gap_c": extra.get("exec_gap_c"),
        "action_1_text": extra.get("a1", f"Buy YES {oid}"),
        "action_2_text": extra.get("a2", f"Buy NO {oid}"),
        "legs": extra.get("legs"),
        "payout_floor_c": extra.get("payout_floor_c"),
        "roi_pct": extra.get("roi_pct"),
        "settlement_caveat": extra.get("settlement_caveat", ""),
    }
    return row


def _seed_history(db):
    """A history exercising every §10 branch:
      - A: actionable 100-300, present-CLEAN 400/500  -> reason 'went clean'
      - B: actionable 100, present-BLOCKED 200-500    -> reason 'went blocked'
      - E: actionable 200, present-INACTIVE 300-500   -> reason 'leg inactive'
      - G: actionable 400, ABSENT at 500              -> reason 'disappeared'
      - F: actionable 300/400/500                      -> still actionable now (excluded)
      - H: actionable only at 500 (latest)            -> current, not 'recently' (excluded)
      - ts=250 has NO actionable rows (only a clean X) -> the empty-snapshot-inclusion test:
        E's last-actionable is 200, so left_ts MUST resolve to 250 (the first snapshot after), which only
        holds if the narrowed history still includes the actionable-less 250 snapshot."""
    store.write_snapshot(100, [_opp("A"), _opp("B"), _opp("C", bucket="clean"),
                               _opp("D", bucket="blocked")], db_path=db)
    store.write_snapshot(200, [_opp("A"), _opp("B", bucket="blocked"), _opp("E")], db_path=db)
    store.write_snapshot(250, [_opp("X", bucket="clean")], db_path=db)                  # no actionable rows
    store.write_snapshot(300, [_opp("A"), _opp("E", bucket="clean", market_status="inactive"),
                               _opp("F")], db_path=db)
    store.write_snapshot(400, [_opp("A", bucket="clean"), _opp("F"), _opp("G")], db_path=db)
    store.write_snapshot(500, [_opp("A", bucket="clean"), _opp("B", bucket="blocked"),
                               _opp("E", bucket="clean", market_status="inactive"),
                               _opp("F"), _opp("H")], db_path=db)


WINDOW = 10_000.0   # covers the whole 100..500 span (newest-relative)


def test_backlog_optimized_equals_full_history(tmp_path):
    db = _db(tmp_path)
    _seed_history(db)
    full = lifecycle.recently_actionable(store.snapshots_since(WINDOW, db_path=db))
    optimized = engine.backlog(WINDOW, db_path=db)
    assert optimized == full                       # field-wise AND order identical
    # sanity: the expected set + a couple of reason_left branches actually fired
    by = {r["opportunity_id"]: r for r in optimized}
    assert set(by) == {"A", "B", "E", "G"}
    assert by["A"]["reason_left"] == "went clean"
    assert by["B"]["reason_left"] == "went blocked"
    assert by["E"]["reason_left"] == "leg inactive"
    assert by["G"]["reason_left"] == "disappeared"
    assert by["E"]["left_ts"] == 250.0             # proves the empty 250 snapshot was included


def test_backlog_empty_store(tmp_path):
    db = _db(tmp_path)
    assert engine.backlog(WINDOW, db_path=db) == lifecycle.recently_actionable(
        store.snapshots_since(WINDOW, db_path=db)) == []


def test_persisting_alert_optimized_equals_full_history(tmp_path):
    db = _db(tmp_path)
    _seed_history(db)
    for persist in (None, 150.0, 10_000.0):
        full = lifecycle.persisting_new_actionable(
            store.snapshots_since(config.SNAPSHOT_RETENTION_SECONDS, db_path=db), persist, now_ts=None)
        narrowed = lifecycle.persisting_new_actionable(
            store.actionable_history_since(config.SNAPSHOT_RETENTION_SECONDS, db_path=db), persist, now_ts=None)
        assert narrowed == full, f"persist={persist}"


def test_actionable_history_includes_every_snapshot_in_window(tmp_path):
    db = _db(tmp_path)
    _seed_history(db)
    hist = store.actionable_history_since(WINDOW, db_path=db)
    # every snapshot present (incl. the actionable-less 250), oldest->newest, newest-relative window
    assert [s["fetched_ts"] for s in hist] == [100.0, 200.0, 250.0, 300.0, 400.0, 500.0]
    empty = next(s for s in hist if s["fetched_ts"] == 250.0)
    assert empty["opportunities"] == []
    # only actionable rows survive the narrowing
    at100 = next(s for s in hist if s["fetched_ts"] == 100.0)
    assert {o["opportunity_id"] for o in at100["opportunities"]} == {"A", "B"}
    assert all(o["bucket"] == "actionable" for s in hist for o in s["opportunities"])


def test_actionable_history_window_is_newest_relative(tmp_path):
    db = _db(tmp_path)
    _seed_history(db)
    # window 150s back from newest (500) -> cutoff 350 -> snapshots 400, 500 only
    hist = store.actionable_history_since(150.0, db_path=db)
    assert [s["fetched_ts"] for s in hist] == [400.0, 500.0]


def test_latest_rows_by_id_empty_and_from_latest_only(tmp_path):
    db = _db(tmp_path)
    assert store.latest_rows_by_id([], db_path=db) == {}
    assert store.latest_rows_by_id([""], db_path=db) == {}        # blank ids dropped -> {}
    _seed_history(db)
    assert store.latest_rows_by_id([], db_path=db) == {}
    got = store.latest_rows_by_id(["A", "F", "G", "missing"], db_path=db)
    assert set(got) == {"A", "F"}                                 # G absent at 500, 'missing' never existed
    assert got["A"]["bucket"] == "clean" and got["F"]["bucket"] == "actionable"
    # full row round-trips (not a thin projection)
    assert got["A"]["opportunity_id"] == "A" and got["A"]["name"] == "A" and got["A"]["url"].endswith("/A")


def test_latest_rows_by_id_chunks_over_param_limit(tmp_path, monkeypatch):
    db = _db(tmp_path)
    ids = [f"o{i}" for i in range(50)]
    store.write_snapshot(1000, [_opp(i) for i in ids], db_path=db)
    monkeypatch.setattr(store, "_SQLITE_MAX_VARS", 7)             # force many chunks
    got = store.latest_rows_by_id(ids, db_path=db)
    assert set(got) == set(ids)


def test_perf_indexes_present_and_used(tmp_path):
    db = _db(tmp_path)
    store.write_snapshot(1000, [_opp("a")], db_path=db)
    conn = store._connect(db)
    try:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert {"ix_opp_snap_bucket", "ix_opp_snap_oid", "ix_snap_ts"} <= names
        plan = " ".join(str(r[-1]) for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT data FROM opportunities "
            "WHERE snapshot_id = 1 AND bucket = 'actionable'").fetchall())
        assert "ix_opp_snap_bucket" in plan                       # the narrowing query uses the index
    finally:
        conn.close()
