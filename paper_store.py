"""SQLite persistence for the forward-test / paper-position harness.

Two normalized tables (one opportunity → N legs) plus a settlement cache, living in the SAME SQLite file
as the snapshot store but **independent of it**: NO foreign key to ``snapshots``, because the snapshot
store self-prunes on a ~6h window (``store._apply_retention``) and a paper position must outlive the
snapshot it was opened from (settlement can be days later). We reuse ``store._connect`` only for its
connection/PRAGMA setup.

Open-once semantics: an entry is keyed on ``entry_key = sha1(opportunity_id | fill_model)`` — a stable
structure hash — and inserted with ``INSERT OR IGNORE``, so re-seeing the same live opportunity across
scans is a no-op (it is never re-opened or double-counted).
"""
from __future__ import annotations

import sqlite3
from typing import Any

import paper_engine as pe
import store

_PAPER_DDL = """
CREATE TABLE IF NOT EXISTS paper_entries (
    entry_key          TEXT PRIMARY KEY,
    opportunity_id     TEXT,
    first_snapshot_id  INTEGER,            -- reference only; NOT a FK (snapshots self-prune)
    opened_ts          REAL,
    source_bucket      TEXT,
    sport              TEXT,
    relationship_type  TEXT,
    opportunity_class  TEXT,               -- executable | speculative
    fill_model         TEXT,
    cost_c             INTEGER,
    max_loss_c         INTEGER,
    scorable           INTEGER,
    unscorable_reason  TEXT,
    status             TEXT,               -- open | determined_pending | settled | unscorable
    gross_c            INTEGER,
    fees_c             INTEGER,
    net_c              INTEGER,
    won                INTEGER,
    settled_ts         REAL
);
CREATE TABLE IF NOT EXISTS paper_legs (
    entry_key      TEXT,
    leg_index      INTEGER,
    ticker         TEXT,
    side           TEXT,
    entry_price_c  INTEGER,
    size           INTEGER,
    contract       TEXT,
    result         TEXT,
    payout_c       INTEGER,
    PRIMARY KEY (entry_key, leg_index)
);
CREATE TABLE IF NOT EXISTS paper_settlements (
    ticker              TEXT PRIMARY KEY,
    result              TEXT,
    settlement_value_c  INTEGER,
    settled_ts          REAL,
    status_raw          TEXT,
    fetched_ts          REAL
);
CREATE INDEX IF NOT EXISTS idx_paper_legs_ticker ON paper_legs(ticker);
CREATE INDEX IF NOT EXISTS idx_paper_entries_status ON paper_entries(status);
"""

_OPEN_STATUSES = (pe.STATUS_OPEN, pe.STATUS_DETERMINED_PENDING)


def _connect(db_path: str | None) -> sqlite3.Connection:
    """A store connection (WAL/PRAGMAs/snapshot migration) with the paper tables ensured (idempotent)."""
    conn = store._connect(db_path)
    conn.executescript(_PAPER_DDL)
    return conn


# --- recording ---------------------------------------------------------------------

def record_entries(entries: list[pe.PaperEntry], snapshot_id: Any, *, db_path: str | None = None) -> int:
    """Persist new paper entries (open-once). Returns the count of NEWLY-opened entries (existing ones are
    left untouched by ``INSERT OR IGNORE``)."""
    if not entries:
        return 0
    conn = _connect(db_path)
    try:
        opened = 0
        for e in entries:
            cur = conn.execute(
                """INSERT OR IGNORE INTO paper_entries
                   (entry_key, opportunity_id, first_snapshot_id, opened_ts, source_bucket, sport,
                    relationship_type, opportunity_class, fill_model, cost_c, max_loss_c, scorable,
                    unscorable_reason, status, gross_c, fees_c, net_c, won, settled_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL)""",
                (e.entry_key, e.opportunity_id, snapshot_id, e.opened_ts, e.source_bucket, e.sport,
                 e.relationship_type, e.opportunity_class, e.fill_model, e.cost_c, e.max_loss_c,
                 int(e.scorable), e.unscorable_reason,
                 pe.STATUS_UNSCORABLE if not e.scorable else pe.STATUS_OPEN),
            )
            if cur.rowcount:
                opened += 1
                conn.executemany(
                    """INSERT OR IGNORE INTO paper_legs
                       (entry_key, leg_index, ticker, side, entry_price_c, size, contract, result, payout_c)
                       VALUES (?,?,?,?,?,?,?,NULL,NULL)""",
                    [(e.entry_key, i, leg.ticker, leg.side, leg.entry_price_c, leg.size, leg.contract)
                     for i, leg in enumerate(e.legs)],
                )
        conn.commit()
        return opened
    finally:
        conn.close()


# --- settlement --------------------------------------------------------------------

def open_tickers(db_path: str | None = None) -> list[str]:
    """Distinct tickers on entries that are still open / determined-pending (need a settlement lookup)."""
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(_OPEN_STATUSES))
        rows = conn.execute(
            f"""SELECT DISTINCT l.ticker FROM paper_legs l
                JOIN paper_entries e ON e.entry_key = l.entry_key
                WHERE e.status IN ({marks}) AND e.scorable = 1 AND l.ticker <> ''""",
            _OPEN_STATUSES,
        ).fetchall()
        return [r["ticker"] for r in rows]
    finally:
        conn.close()


def cache_settlements(settlements: list[dict[str, Any]], fetched_ts: float,
                      *, db_path: str | None = None) -> int:
    """Upsert settlement outcomes (``{ticker, result, status_raw, settlement_value_c, settled_ts}``)."""
    if not settlements:
        return 0
    conn = _connect(db_path)
    try:
        conn.executemany(
            """INSERT INTO paper_settlements (ticker, result, settlement_value_c, settled_ts, status_raw, fetched_ts)
               VALUES (:ticker, :result, :settlement_value_c, :settled_ts, :status_raw, :fetched_ts)
               ON CONFLICT(ticker) DO UPDATE SET
                   result=excluded.result, settlement_value_c=excluded.settlement_value_c,
                   settled_ts=excluded.settled_ts, status_raw=excluded.status_raw, fetched_ts=excluded.fetched_ts""",
            [{"ticker": s.get("ticker"), "result": s.get("result"),
              "settlement_value_c": s.get("settlement_value_c"), "settled_ts": s.get("settled_ts"),
              "status_raw": s.get("status_raw"), "fetched_ts": fetched_ts} for s in settlements],
        )
        conn.commit()
        return len(settlements)
    finally:
        conn.close()


def _load_settlement_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM paper_settlements").fetchall()
    return {r["ticker"]: {"result": r["result"], "status": r["status_raw"],
                          "settled_ts": r["settled_ts"], "settlement_value_c": r["settlement_value_c"]}
            for r in rows}


def _entry_from_rows(erow: sqlite3.Row, legs: list[sqlite3.Row]) -> pe.PaperEntry:
    return pe.PaperEntry(
        entry_key=erow["entry_key"], opportunity_id=erow["opportunity_id"], opened_ts=erow["opened_ts"],
        source_bucket=erow["source_bucket"], sport=erow["sport"],
        relationship_type=erow["relationship_type"], opportunity_class=erow["opportunity_class"],
        fill_model=erow["fill_model"], cost_c=erow["cost_c"], max_loss_c=erow["max_loss_c"],
        scorable=bool(erow["scorable"]), unscorable_reason=erow["unscorable_reason"] or "",
        legs=[pe.PaperLeg(ticker=lg["ticker"], side=lg["side"], entry_price_c=lg["entry_price_c"],
                          size=lg["size"], contract=lg["contract"] or "") for lg in legs],
    )


def rescore(db_path: str | None = None) -> int:
    """Re-score every still-open scorable entry against the cached settlements; persist any that newly
    settle (or move to determined-pending). Returns the number of entries that changed status."""
    conn = _connect(db_path)
    try:
        settle_map = _load_settlement_map(conn)
        marks = ",".join("?" * len(_OPEN_STATUSES))
        entries = conn.execute(
            f"SELECT * FROM paper_entries WHERE status IN ({marks}) AND scorable = 1", _OPEN_STATUSES,
        ).fetchall()
        changed = 0
        for erow in entries:
            legs = conn.execute(
                "SELECT * FROM paper_legs WHERE entry_key = ? ORDER BY leg_index", (erow["entry_key"],),
            ).fetchall()
            entry = _entry_from_rows(erow, legs)
            res = pe.score_entry(entry, settle_map)
            if res.status == erow["status"] and res.status != pe.STATUS_SETTLED:
                continue
            conn.execute(
                """UPDATE paper_entries SET status=?, gross_c=?, fees_c=?, net_c=?, won=?, settled_ts=?
                   WHERE entry_key=?""",
                (res.status, res.gross_c, res.fees_c, res.net_c,
                 None if res.won is None else int(res.won), res.settled_ts, erow["entry_key"]),
            )
            for i, lp in enumerate(res.leg_payouts):
                conn.execute("UPDATE paper_legs SET result=?, payout_c=? WHERE entry_key=? AND leg_index=?",
                             (lp.get("result"), lp.get("payout_c"), erow["entry_key"], i))
            if res.status != erow["status"]:
                changed += 1
        conn.commit()
        return changed
    finally:
        conn.close()


# --- reporting ---------------------------------------------------------------------

def _blank_agg() -> dict[str, Any]:
    return {"settled": 0, "wins": 0, "losses": 0, "net_c": 0, "open": 0, "determined_pending": 0}


def _fold(agg: dict[str, Any], row: sqlite3.Row) -> None:
    st = row["status"]
    if st == pe.STATUS_SETTLED:
        agg["settled"] += 1
        agg["net_c"] += row["net_c"] or 0
        if row["won"]:
            agg["wins"] += 1
        else:
            agg["losses"] += 1
    elif st == pe.STATUS_OPEN:
        agg["open"] += 1
    elif st == pe.STATUS_DETERMINED_PENDING:
        agg["determined_pending"] += 1


def _finalize_agg(agg: dict[str, Any]) -> dict[str, Any]:
    agg["net_dollars"] = round(agg["net_c"] / 100.0, 2)
    agg["win_rate"] = round(agg["wins"] / agg["settled"], 3) if agg["settled"] else None
    return agg


def report(db_path: str | None = None) -> dict[str, Any]:
    """Aggregate the paper book into a forward-test report: realized net-of-fees P&L and win rate overall
    and sliced by opportunity_class / bucket / sport, plus open/pending/unscorable counts. Per-unit cents.

    Headline P&L counts SETTLED scorable entries only; unscorable entries are reported separately and never
    fold into the P&L. Every figure is under conservative paper-fill assumptions (top-of-book, size-capped,
    no queue/slippage) — the SPA surfaces that caveat.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT status, won, net_c, opportunity_class, source_bucket, sport "
                            "FROM paper_entries").fetchall()
        overall = _blank_agg()
        by_class: dict[str, dict[str, Any]] = {}
        by_bucket: dict[str, dict[str, Any]] = {}
        by_sport: dict[str, dict[str, Any]] = {}
        unscorable = 0
        for r in rows:
            if r["status"] == pe.STATUS_UNSCORABLE:
                unscorable += 1
                continue
            _fold(overall, r)
            _fold(by_class.setdefault(r["opportunity_class"] or "unknown", _blank_agg()), r)
            _fold(by_bucket.setdefault(r["source_bucket"] or "unknown", _blank_agg()), r)
            _fold(by_sport.setdefault(r["sport"] or "unknown", _blank_agg()), r)
        return {
            "overall": _finalize_agg(overall),
            "by_class": {k: _finalize_agg(v) for k, v in sorted(by_class.items())},
            "by_bucket": {k: _finalize_agg(v) for k, v in sorted(by_bucket.items())},
            "by_sport": {k: _finalize_agg(v) for k, v in sorted(by_sport.items())},
            "unscorable": unscorable,
            "fill_model_note": "Entry at firm ask captured at flag time, size-capped at visible top-of-book "
                               "depth; held to settlement; net of entry taker fees. No queue position, "
                               "latency, slippage, or partial fill beyond visible size. No orders placed.",
        }
    finally:
        conn.close()


def list_positions(db_path: str | None = None, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Recent paper positions (newest first) with their legs, for the SPA table."""
    conn = _connect(db_path)
    try:
        if status:
            erows = conn.execute("SELECT * FROM paper_entries WHERE status = ? ORDER BY opened_ts DESC LIMIT ?",
                                 (status, limit)).fetchall()
        else:
            erows = conn.execute("SELECT * FROM paper_entries ORDER BY opened_ts DESC LIMIT ?",
                                 (limit,)).fetchall()
        out = []
        for er in erows:
            legs = conn.execute("SELECT ticker, side, entry_price_c, size, contract, result, payout_c "
                                "FROM paper_legs WHERE entry_key = ? ORDER BY leg_index",
                                (er["entry_key"],)).fetchall()
            d = dict(er)
            d["legs"] = [dict(lg) for lg in legs]
            out.append(d)
        return out
    finally:
        conn.close()
