"""Unit tests for the NiceGUI dashboard's engine layer (Stage 5). The correctness backbone is the
in-process accessors in `webui.engine` over a tmp-seeded store (no network, no browser); plus a smoke
test that `webui.dashboard` imports and registers its page. Interactive rendering is verified by the
live `serve.py` boot. Engine/API suites remain the correctness backbone."""
from __future__ import annotations

import pandas as pd
import pytest

import config
import store
from webui import dashboard as dash  # noqa: F401  — kept for the import-and-registers smoke test
from webui import engine
from webui import viewmodel as vm


def op(oid, *, sport="tennis", bucket="actionable", **kw):
    return {
        "opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": "dutch_book",
        "name": kw.get("name", "A vs B"), "detail": "underround", "tournament": "T", "tour": "ATP",
        "action_1_text": "Buy YES — A @ 45¢", "action_2_text": "Buy YES — B @ 48¢",
        "action_1_price_c": 45, "action_2_price_c": 48, "cost_c": 93,
        "exec_gap_c": kw.get("exec_gap_c", 7), "exec_min_size": 100, "exec_max_profit_dollars": 7.0,
        "bucket": bucket, "status": kw.get("status", "EXECUTABLE_DUTCH_BOOK"),
        "tradable_now": kw.get("tradable_now", "Yes"), "blocked_reason": kw.get("blocked_reason", ""),
        "market_status": kw.get("market_status", "active"), "rule_flag": "",
        "relationship_type": "dutch_book", "ticker_1": "T-a", "ticker_2": "T-b",
        "url": "u1", "url_2": "",
    }


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    db = str(tmp_path / "webui.db")
    monkeypatch.setattr(config, "SNAPSHOT_DB_PATH", db)   # engine calls store with db_path=None -> uses this
    return db


def test_latest_and_bucket_split(tmpdb):
    store.write_snapshot("2026-06-04 12:00:00 UTC",
                         [op("a", bucket="actionable"), op("b", bucket="blocked")])
    assert {o["opportunity_id"] for o in engine.latest_opportunities()} == {"a", "b"}
    assert [o["opportunity_id"] for o in engine.opportunities_in_bucket("blocked")] == ["b"]
    assert [o["opportunity_id"] for o in engine.opportunities_in_bucket("actionable")] == ["a"]


def test_coverage_empty_then_with_meta(tmpdb):
    cov = engine.coverage()
    assert cov["meta_present"] is False and cov["fetched_at"] is None and cov["opportunities"] == 0
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("a")],
                         meta={"scanned": 5, "loaded": 4, "failed": 1, "excluded": 0})
    cov = engine.coverage()
    assert cov["meta_present"] and cov["scanned"] == 5 and cov["loaded"] == 4 and cov["opportunities"] == 1
    assert isinstance(cov["data_age_seconds"], (int, float))


def test_backlog_and_alerts(tmpdb):
    store.write_snapshot(1000, [op("x", bucket="actionable")])
    store.write_snapshot(2000, [op("x", bucket="blocked", market_status="active"),
                                op("y", bucket="actionable")])
    bl = engine.backlog(10 ** 9)
    assert any(b["opportunity_id"] == "x" and b["reason_left"] == "went blocked" for b in bl)
    al = engine.alerts()
    assert [r["opportunity_id"] for r in al["new_actionable"]] == ["y"]
    assert any(c["opportunity_id"] == "x" and c["transitioned"] for c in al["blocked_changes"])


def test_latest_cache_reuses_object_and_reloads_on_new_snapshot(tmpdb):
    store.write_snapshot(1000, [op("a")])
    first = engine._cached_latest(None)
    assert first is engine._cached_latest(None)               # same deserialized object within a snapshot
    assert {o["opportunity_id"] for o in first["opportunities"]} == {"a"}
    store.write_snapshot(2000, [op("b")])                     # new snapshot -> latest_snapshot_id advances
    refreshed = engine._cached_latest(None)
    assert refreshed is not first                             # cache re-read on the new id
    assert {o["opportunity_id"] for o in refreshed["opportunities"]} == {"b"}


def test_latest_cache_one_store_load_across_accessors(tmpdb, monkeypatch):
    # coverage()+latest_opportunities()+alerts() share ONE deserialize of the latest snapshot:
    # the first accessor loads via store.latest, the others hit the cache, and alerts() uses latest_two.
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("a")], meta={"scanned": 1})
    calls = {"n": 0}
    real = store.latest

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(store, "latest", spy)
    engine.coverage()
    engine.latest_opportunities()
    engine.alerts()
    assert calls["n"] == 1


def test_contract_by_ticker_finds_by_ticker_and_handles_misses(tmpdb):
    # PR4 (#7): resolution-criteria lookup is by globally-unique market_ticker; sport is only a hint.
    engine._FRAME_CACHE.clear()        # avoid a stale (snapshot_id, sport, frame) entry from a prior test
    store.write_snapshot("2026-06-05 12:00:00 UTC", [op("o1")], frames=[{
        "sport": "tennis", "frame_type": "contracts", "schema_version": 1,
        "rows": [{"market_ticker": "T-a", "contract": "Beat A", "rules_primary": "Settles YES if A wins."},
                 {"market_ticker": "T-b", "contract": "Beat B", "rules_primary": "Settles YES if B wins."}],
    }])
    assert engine.contract_by_ticker("T-a")["rules_primary"].startswith("Settles YES if A")
    assert engine.contract_by_ticker("T-b", sport="nba")["contract"] == "Beat B"   # sport mismatch still hits
    assert engine.contract_by_ticker("T-zzz") is None                              # truthful miss
    assert engine.contract_by_ticker("") is None


def _two_way_stub():
    """A 2-market underround stub fetch (one actionable dutch book) — no network."""
    def mk(p, k, ask):
        return {"series": "KXATPMATCH", "event_ticker": "EV", "kind": "match", "player": p,
                "player_key": k, "contract": f"Beat ({p})", "tournament": "T", "tour": "ATP",
                "yes_bid_c": ask - 2, "yes_ask_c": ask, "no_ask_c": None, "yes_bid_size": 100,
                "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
                "market_ticker": f"T-{k}", "kalshi_url": "", "event_title": "M", "time_value": None}
    df = pd.DataFrame([mk("A", "ka", 45), mk("B", "kb", 48)])

    def stub(sport_id):
        return (df, "fa", [], 2, 2, 0, 0) if sport_id == "tennis" else (pd.DataFrame(), "fa", [], 1, 0, 0, 0)
    return stub


def test_run_scan_now_offline(tmpdb, monkeypatch):
    monkeypatch.setattr(engine, "fetch_dep", lambda: _two_way_stub())   # no network
    st = engine.run_scan_now()                               # NON-force; empty tmpdb -> the first scan runs
    assert st["status"] == "done"
    cov = st["last_result"]
    assert cov["scanned"] >= 2 and cov["fetched_at"]
    assert engine.latest_opportunities()                     # something was persisted


def test_run_scan_now_non_force_skips_within_ttl(tmpdb, monkeypatch):
    """PR S3: the default (non-force) button respects the TTL — a click right after a scan does NOT refetch
    (returns `skipped`), so many LAN viewers clicking can't hammer Kalshi."""
    monkeypatch.setattr(engine, "fetch_dep", lambda: _two_way_stub())
    assert engine.run_scan_now()["status"] == "done"         # first scan runs
    second = engine.run_scan_now()                           # immediately again, non-force
    assert second["status"] == "skipped" and second["reason"] == "ttl"


def test_run_scan_now_force_overrides_ttl(tmpdb, monkeypatch):
    """Force (the token-gated admin path) still bypasses the TTL."""
    monkeypatch.setattr(engine, "fetch_dep", lambda: _two_way_stub())
    assert engine.run_scan_now()["status"] == "done"
    assert engine.run_scan_now(force=True)["status"] == "done"   # force re-runs despite the TTL


def test_dashboard_imports_and_registers_page():
    import webui.dashboard
    assert callable(webui.dashboard.dashboard)


# --- dashboard pure builders (no NiceGUI runtime needed) ------------------------------
def test_opp_row_new_marker_and_fields():
    o = op("AAA", bucket="actionable")
    r = vm.opp_row(o, {"AAA"})
    assert r["new"] == "🆕" and r["opportunity_id"] == "AAA"
    assert r["sport"] == "Tennis" and r["edge"] == 7 and r["units"] == 100 and r["profit"] == 7.0
    assert vm.opp_row(o, set())["new"] == ""            # not new -> blank marker


def test_opp_row_handles_none_numbers():
    o = op("Z", bucket="blocked")
    o["exec_gap_c"] = o["exec_min_size"] = o["exec_max_profit_dollars"] = None
    r = vm.opp_row(o, set())
    assert r["edge"] is None and r["units"] is None and r["profit"] is None   # no crash on None


def test_opp_row_change_marker():
    o = op("x", bucket="actionable")
    assert vm.opp_row(o, set())["_change"] == ""                    # no change map -> blank
    assert vm.opp_row(o, set(), {"x": "up"})["_change"] == "up"     # stamped from the changes map
    assert vm.opp_row(o, set(), {"x": "down"})["_change"] == "down"
    r = vm.opp_row(o, {"x"}, {"x": "new"})                          # new-actionable marker is independent
    assert r["new"] == "🆕" and r["_change"] == "new"


def test_rows_flash_only_for_flash_ids():
    # PR B: a row flashes green ONLY when its id is in the (one-shot, snapshot-scoped) flash set. A plain
    # filter rerender passes no flash set, so nothing replays — `_flash` is a bare bool (no positive copy).
    o = op("x", bucket="actionable")
    assert vm.opp_row(o, set())["_flash"] is False                 # no flash set -> never flashes
    assert vm.opp_row(o, set(), {}, {"x"})["_flash"] is True       # in the flash set -> flashes once
    assert vm.opp_row(o, set(), {}, {"other"})["_flash"] is False  # other ids -> no flash
    rb = op("RB", bucket="risk_budget")
    rb["worst_case_profit_c"], rb["best_case_profit_c"] = -3, 97
    assert vm.risk_budget_row(rb, set(), {}, {"RB"})["_flash"] is True
    assert vm.near_miss_row(op("NM", bucket="near_miss", exec_gap_c=-2), set(), {}, {"NM"})["_flash"] is True


def test_speculative_rows_drop_tradable_and_positive_framing():
    # Risk-budget (speculative bounded-loss) row: even with active legs, the BUNDLE is not auto-placeable,
    # so the row must not surface a "tradable" field (PR 1 de-risking).
    o = op("RB", bucket="risk_budget", tradable_now="Yes")
    o["worst_case_profit_c"], o["best_case_profit_c"] = -3, 97
    rb = vm.risk_budget_row(o, set())
    assert "tradable" not in rb
    # Near-miss watchlist row: no tradable, explicit Watchlist marker.
    nm = vm.near_miss_row(op("NM", bucket="near_miss", tradable_now="Yes", exec_gap_c=-2), set())
    assert "tradable" not in nm and nm["watchlist"] == "Watchlist"
    # No positive edge/actionability framing leaks into the displayed values of either speculative row.
    for row in (rb, nm):
        blob = " ".join(str(v) for v in row.values()).lower()
        for term in ("actionable", "arbitrage", "tradable", "locked", "riskless", "guaranteed"):
            assert term not in blob


def test_watchlist_row_merges_buckets_with_type_and_nonimperative_structure():
    # PR C: one merged row per bucket. Bounded-loss bet keeps its convex economics; near-miss keeps overpay;
    # each blanks the other type's numeric fields. Structure is DESCRIPTIVE (no imperative "Buy …").
    rb = op("RB", bucket="risk_budget")
    rb["worst_case_profit_c"], rb["best_case_profit_c"] = -3, 97
    rrow = vm.watchlist_row(rb, set())
    assert rrow["type"] == "Bounded-loss bet"
    assert rrow["max_loss"] == 3 and rrow["overpay"] is None          # bounded-loss filled, near-miss blank
    assert "Buy" not in rrow["structure"] and "YES" in rrow["structure"]   # non-imperative, still informative
    nrow = vm.watchlist_row(op("NM", bucket="near_miss", exec_gap_c=-2), set())
    assert nrow["type"] == "Overpriced book"
    assert nrow["overpay"] == 2 and nrow["max_loss"] is None          # near-miss filled, bounded-loss blank
    assert "watchlist" not in nrow                                    # the Type column replaces the old marker
    # Both rows must still pass the watchlist value blacklist (no edge / positive / tradable framing).
    for row in (rrow, nrow):
        blob = " ".join(str(v) for v in row.values()).lower()
        for term in ("actionable", "arbitrage", "tradable", "locked", "riskless", "guaranteed"):
            assert term not in blob


def test_watchlist_view_orders_bounded_loss_first_and_respects_include_flags():
    rb = op("RB", bucket="risk_budget")
    rb["worst_case_profit_c"], rb["best_case_profit_c"] = -3, 97
    nm = op("NM", bucket="near_miss", exec_gap_c=-2)
    # Bounded-loss bets come first regardless of input order (each subset filters by its own bucket).
    both = vm.watchlist_view([nm, rb], include_rb=True, include_nm=True, max_loss_c=5, max_over_c=5)
    assert [o["opportunity_id"] for o in both] == ["RB", "NM"]
    only_rb = vm.watchlist_view([rb, nm], include_rb=True, include_nm=False, max_loss_c=5, max_over_c=5)
    only_nm = vm.watchlist_view([rb, nm], include_rb=False, include_nm=True, max_loss_c=5, max_over_c=5)
    assert [o["opportunity_id"] for o in only_rb] == ["RB"]
    assert [o["opportunity_id"] for o in only_nm] == ["NM"]
    assert vm.watchlist_view([rb, nm], include_rb=False, include_nm=False, max_loss_c=5, max_over_c=5) == []


def test_severity_badges_are_structural_and_ordered():
    # blocked_reason (blocker) + settlement_caveat (advisory) -> blocker sorts first.
    o = op("x", bucket="blocked", blocked_reason="A leg is finalized.")
    o["settlement_caveat"] = "Per-game postponement risk."
    badges = vm.severity_badges(o)
    assert [b["severity"] for b in badges][0] == "blocker"
    assert {"blocker", "advisory"} <= {b["severity"] for b in badges}
    assert all(set(b) == {"label", "severity", "tooltip", "source"} for b in badges)
    # rule_flag -> review_required, sourced from the STRUCTURAL field (not free-text matching).
    oy = op("y")
    oy["rule_flag"] = "RULE_MISMATCH"
    rb = vm.severity_badges(oy)
    assert rb[0]["severity"] == "review_required" and rb[0]["source"] == "rule_flag"
    # A clean actionable row with no row-specific caveat -> no badges (universal limits live in the strip).
    clean = op("z", bucket="actionable")
    clean["settlement_caveat"] = ""
    assert vm.severity_badges(clean) == []


def test_rows_stamp_top_severity_for_the_cell_chip():
    blk = vm.opp_row(op("b", bucket="blocked", blocked_reason="A leg is finalized."), set())
    assert blk["_sev"] == "blocker" and blk["_sev_label"] == "Blocker"
    # PR A: the compact caveat chip shows the content-descriptive top-badge label, full prose stays in `caveat`.
    assert blk["_caveat_tag"] == "Blocked" and "finalized" in blk["caveat"]
    clean = vm.opp_row(op("c", bucket="actionable"), set())
    assert clean["_sev"] == "" and clean["_sev_label"] == "" and clean["_caveat_tag"] == ""


def test_action_plan_summary_two_leg_uses_own_floor():
    o = op("a", bucket="actionable")
    o["payout_floor_c"] = 100
    aps = vm.action_plan_summary(o)
    assert "Buy YES" in aps["summary"] and " + " in aps["summary"]      # both legs concatenated
    assert aps["cost"] == "93¢" and aps["floor"] == "100¢" and aps["max_units"] == "100"
    assert aps["is_complete"] and aps["missing_fields"] == []
    assert "cost 93¢" in aps["line"] and "floor 100¢" in aps["line"]


def test_action_plan_summary_nleg_not_faked_as_two_leg():
    o = op("b", bucket="review_signal")
    o["n_legs"], o["payout_floor_c"] = 4, 100
    o["legs"] = [{"text": f"Buy YES — S{i}"} for i in range(4)]
    aps = vm.action_plan_summary(o)
    assert aps["summary"] == "4-leg plan — open details for legs" and " + " not in aps["summary"]


def test_action_plan_summary_no_hardcoded_100_floor_and_conservative_on_missing():
    o = op("c", bucket="blocked")
    o["payout_floor_c"] = 200                                  # e.g. a field overround floors above 100
    assert vm.action_plan_summary(o)["floor"] == "200¢"        # echoes the opp's OWN floor, not a constant
    o2 = op("d")
    o2["cost_c"] = o2["payout_floor_c"] = None
    aps2 = vm.action_plan_summary(o2)
    assert {"cost", "floor"} <= set(aps2["missing_fields"])
    assert aps2["cost"] == "—" and aps2["floor"] == "—" and not aps2["is_complete"]


def test_leg_rows_enriches_from_lookup_and_blanks_unresolved():
    o = op("x")
    o["legs"] = [
        {"text": "Buy YES — A @ 45¢", "side": "Buy YES", "price_c": 45, "size": 30,
         "ticker": "T-a", "url": "u1", "contract": "Reach Final"},
        {"text": "Buy NO — B @ 52¢", "price_c": 52, "ticker": "T-gone", "url": "u2"},
    ]
    rows = vm.leg_rows(o, {"T-a": {"status": "active", "quote_quality": "Tight"}})
    assert len(rows) == 2
    assert (rows[0]["status"], rows[0]["quote_quality"]) == ("active", "Tight")
    assert rows[0]["evidence_source"] == "contract_lookup" and rows[0]["price"] == "45¢" and rows[0]["size"] == "30"
    # unresolved ticker -> blanks + warning, never fabricated; side parsed from text when absent.
    assert rows[1]["status"] == "" and rows[1]["quote_quality"] == "" and rows[1]["side"] == "Buy NO"
    assert rows[1]["warning"] == "unavailable in snapshot" and rows[1]["evidence_source"] == "opportunity"


def test_leg_rows_empty_when_no_legs():
    assert vm.leg_rows(op("y")) == []                          # op() carries no legs -> nothing to show


def test_opp_row_carries_action_plan_line():
    o = op("z", bucket="actionable")
    o["payout_floor_c"] = 100
    assert "Buy YES" in vm.opp_row(o, set())["action"]


def test_ts_disp_and_backlog_row():
    assert vm.ts_disp(None, "UTC") == "—"
    assert vm.ts_disp(1000.0, "UTC") != "—"             # formats an epoch
    b = {"sport": "nba", "name": "X vs Y", "became_ts": 1000.0, "left_ts": 1180.0,
         "duration_s": 180.0, "reason_left": "went blocked", "last_edge_c": 4,
         "current_status": "blocked"}
    row = vm.backlog_row(b, "UTC")
    assert row["mins"] == 3.0 and row["reason"] == "went blocked" and row["last_edge"] == 4
    # None duration / timestamps are safe
    safe = vm.backlog_row({"became_ts": None, "left_ts": None, "duration_s": None}, "UTC")
    assert safe["became"] == "—" and safe["left"] == "—" and safe["mins"] is None


def test_explanation_lines_content():
    o = op("AAA", bucket="blocked", blocked_reason="leg inactive")
    lines = vm.explanation_lines(o, show_ids=True)
    blob = "\n".join(lines)
    assert "Leg 1: Buy YES — A @ 45¢" in blob and "Leg 2:" in blob
    assert "Cost: 93¢" in blob and "Gross edge: 7¢" in blob and "Gross profit: $7.0" in blob
    assert "Relationship: dutch_book" in blob and "Market: active" in blob
    assert "Caveat: leg inactive" in blob                 # blocked_reason surfaced
    assert any("T-a / T-b" in line for line in lines)      # show_ids -> tickers
    # without show_ids and without a caveat, those lines are omitted
    plain = vm.explanation_lines(op("BBB", bucket="actionable"), show_ids=False)
    assert not any("T-a / T-b" in line for line in plain) and not any(line.startswith("Caveat") for line in plain)


def test_explanation_lines_iterates_n_legs_for_synthetic_bundle():
    o = op("SYN", bucket="blocked", status="EXECUTABLE_SYNTHETIC_BUNDLE",
           tradable_now="Review rules", blocked_reason="settlement caveat")
    o["source"] = "synthetic_bundle"
    o["legs"] = [
        {"text": "Buy YES — P wins 3-0 @ 2¢", "url": "u30"},
        {"text": "Buy YES — P wins 3-1 @ 2¢", "url": "u31"},
        {"text": "Buy YES — P wins 3-2 @ 2¢", "url": "u32"},
        {"text": "Buy NO — P @ 90¢", "url": "uw"},
    ]
    blob = "\n".join(vm.explanation_lines(o))
    assert "Leg 1: Buy YES — P wins 3-0 @ 2¢" in blob
    assert "Leg 4: Buy NO — P @ 90¢" in blob          # ALL four legs listed, not just two
    assert "Tradable now: Review rules" in blob and "Caveat: settlement caveat" in blob
    # 2-leg shapes (no `legs` list) keep the positional fallback.
    assert "Leg 2: Buy YES — B @ 48¢" in "\n".join(vm.explanation_lines(op("DB")))


# --- participant detail engine accessors + frame cache (PR 24) -------------------------
def _frame(sport, ftype, rows):
    return {"sport": sport, "frame_type": ftype, "schema_version": 1, "rows": rows}


def test_participant_contracts_and_checks_filter_by_player_key(tmpdb):
    engine._FRAME_CACHE.clear()
    contracts = [{"player_key": "p1", "contract": "Final"}, {"player_key": "p2", "contract": "Other"}]
    checks = [{"player_key": "p1", "opportunity_id": "o1", "status": "EXECUTABLE_VIOLATION"}]
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("o1")],
                         frames=[_frame("tennis", "contracts", contracts),
                                 _frame("tennis", "checks", checks)])
    assert [r["contract"] for r in engine.participant_contracts("tennis", "p1")] == ["Final"]
    assert engine.participant_contracts("tennis", "p2")[0]["contract"] == "Other"
    assert [c["opportunity_id"] for c in engine.participant_checks("tennis", "p1")] == ["o1"]
    assert engine.participant_contracts("tennis", "") == []          # no key → empty (no crash)


def test_frame_cache_avoids_reread_and_invalidates_on_new_snapshot(tmpdb, monkeypatch):
    engine._FRAME_CACHE.clear()
    store.write_snapshot(1000, [op("o1")],
                         frames=[_frame("tennis", "contracts", [{"player_key": "p1", "contract": "v1"}])])
    calls = {"n": 0}
    real = store.load_frames

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(store, "load_frames", counting)
    engine.participant_contracts("tennis", "p1")
    engine.participant_contracts("tennis", "p1")                     # second call served from the cache
    assert calls["n"] == 1
    # A newer snapshot invalidates the whole cache → a fresh read returns the new rows.
    store.write_snapshot(2000, [op("o1")],
                         frames=[_frame("tennis", "contracts", [{"player_key": "p1", "contract": "v2"}])])
    assert engine.participant_contracts("tennis", "p1")[0]["contract"] == "v2"
    assert calls["n"] == 2


def test_frame_availability_and_payoff_for_opp(tmpdb):
    engine._FRAME_CACHE.clear()
    assert engine.frame_availability() == "absent"                  # honest when the store is empty
    check = {"player_key": "p1", "opportunity_id": "o1", "status": "EXECUTABLE_VIOLATION",
             "action_1_side": "buy_yes", "action_2_side": "buy_no",
             "action_1_price_c": 40, "action_2_price_c": 55,
             "parent_node": "Reach Final", "child_node": "Win Tournament"}
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("o1")], frames=[_frame("tennis", "checks", [check])])
    assert engine.frame_availability() == "present"
    pay = engine.payoff_for_opp({"opportunity_id": "o1", "sport": "tennis",
                                 "participant_key": "p1", "exec_min_size": 10})
    assert pay and pay["cost_c"] == 95
    # An unmatched / dutch-book opp has no matched checks row → None (so the dashboard guards the chart).
    assert engine.payoff_for_opp({"opportunity_id": "zzz", "sport": "tennis", "participant_key": "p1"}) is None


# --- observability accessors (PR 25a) -------------------------------------------------
import scan_manager  # noqa: E402


def test_engine_metrics_diagnostics_and_category(tmpdb):
    engine._FRAME_CACHE.clear()
    scan_manager.manager.reset()
    contracts = [
        {"ladder_eligible": True, "mapping_confidence": "high", "series": "KXATPADVANCE", "market_family": "advance"},
        {"ladder_eligible": False, "mapping_confidence": "low", "series": "KXZZUNKNOWN", "market_family": "props"},
    ]
    store.write_snapshot("2026-06-04 12:00:00 UTC",
                         [op("a", bucket="actionable"), op("b", bucket="blocked")],
                         meta={"scanned": 5, "loaded": 4, "failed": 1, "kalshi_requests": 12,
                               "contracts_scanned": 2, "checks_tested": 3,
                               "sport_errors": [{"sport": "nba", "error": "x"}],
                               "series_errors": [{"sport": "tennis", "series": "KXX", "error": "y"}]},
                         frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1,
                                  "rows": contracts}])
    m = engine.metrics()
    assert m["snapshot_id"] and m["opportunities"] == 2 and m["actionable"] == 1
    assert m["kalshi_requests"] == 12 and m["failed_series"] == 1 and m["sport_error_count"] == 1
    assert m["scan_status"] == "idle"                        # no scan run through the manager

    d = engine.diagnostics()
    assert d["sport_errors"][0]["sport"] == "nba" and d["series_errors"][0]["series"] == "KXX"

    c = engine.category_breakdown()
    assert c["total"] == 2 and c["laddered"] == 1 and c["non_laddered"] == 1
    assert c["low_confidence"] == 1 and c["unsupported"] == 1


def test_engine_metrics_honest_when_empty(tmpdb):
    scan_manager.manager.reset()
    m = engine.metrics()
    assert m["snapshot_id"] is None and m["opportunities"] == 0 and m["scan_status"] == "idle"
    assert engine.diagnostics()["sport_errors"] == [] and engine.category_breakdown()["total"] == 0


def test_engine_all_checks_all_contracts_and_viewer_count(tmpdb):
    import presence
    engine._FRAME_CACHE.clear()
    scan_manager.manager.reset()
    presence.reset()
    store.write_snapshot("2026-06-04 12:00:00 UTC", [op("a")],
                         frames=[
                             {"sport": "tennis", "frame_type": "contracts", "schema_version": 1,
                              "rows": [{"player_key": "p1"}, {"player_key": "p2"}]},
                             {"sport": "tennis", "frame_type": "checks", "schema_version": 1,
                              "rows": [{"opportunity_id": "c1"}]},
                             {"sport": "nba", "frame_type": "checks", "schema_version": 1,
                              "rows": [{"opportunity_id": "c2"}]},
                         ])
    assert len(engine.all_contracts()) == 2
    assert {c["opportunity_id"] for c in engine.all_checks()} == {"c1", "c2"}   # concat across sports
    assert engine.metrics()["viewer_count"] == 0
    presence.connect()
    assert engine.metrics()["viewer_count"] == 1
    presence.reset()
