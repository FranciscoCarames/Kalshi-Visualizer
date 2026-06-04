"""Unit tests for the cross-sport scanner (Stage 2). No network: the per-sport fetch is a stub.

The stub returns tennis-shaped fixtures regardless of sport_id — the scanner stamps `sport` from the
sport it fetched FOR (by design; per-sport classification is covered by test_consistency/test_dutchbook/
test_sports). These tests cover aggregation, sport stamping, ranking, partial-failure tolerance, and the
injected snapshot write."""
from __future__ import annotations

import pandas as pd

import scanner
import sports
import store


def _containment_df(prefix="t", gap=5):
    """One player whose Win-Tournament bid crosses the Reach-Final ask by `gap`, both legs active ->
    an actionable EXECUTABLE_VIOLATION. Also yields a MISSING_LAYER (Reach Semifinal absent)."""
    parent_ask = 40
    child_bid = parent_ask + gap

    def row(series, kind, stage, bid, ask):
        return {
            "series": series, "kind": kind, "stage": stage,
            "player": f"P{prefix}", "player_key": f"uuid-{prefix}", "contract": f"{kind}-{stage}",
            "display_pct": float(bid), "display_c": bid, "yes_bid_c": bid, "yes_ask_c": ask,
            "yes_bid_pct": float(bid), "yes_ask_pct": float(ask), "yes_bid_size": 100,
            "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
            "market_ticker": f"T-{prefix}-{stage}", "kalshi_url": "x", "status": "active",
            "tournament": "French Open", "event_ticker": f"E-{prefix}-{stage}",
        }
    return pd.DataFrame([
        row("KXFOWOMEN", "winner", "Champion", child_bid, child_bid + 1),   # Win Tournament (deeper)
        row("KXWTAADVANCE", "advance", "Final", parent_ask - 1, parent_ask),  # Reach Final (broader)
    ])


def _dutchbook_df(gap=7):
    """Two match markets whose YES asks sum to 100-gap -> underround dutch book, actionable."""
    a_ask = 45
    b_ask = (100 - gap) - a_ask

    def mk(player, key, ask):
        return {
            "series": "KXATPMATCH", "event_ticker": "EV", "kind": "match", "player": player,
            "player_key": key, "contract": f"Beat opp ({player})", "tournament": "French Open",
            "tour": "ATP", "yes_bid_c": ask - 2, "yes_ask_c": ask, "no_ask_c": None,
            "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
            "market_ticker": f"T-{key}", "kalshi_url": "x", "event_title": "M", "time_value": None,
        }
    return pd.DataFrame([mk("A", "ka", a_ask), mk("B", "kb", b_ask)])


def _synthetic_df():
    """3 exact-score states for player P (forward-firing: 2*3 + no_ask 90 = 96 < 100) + a real 2-player
    match event so the match-winner hedge joins. Yields one EXECUTABLE_SYNTHETIC_BUNDLE (4-leg)."""
    def score(s, ask):
        return {
            "series": "KXATPEXACTMATCH", "event_ticker": "ES", "kind": "exact_score",
            "player": f"P wins {s}", "player_key": "kp", "tour": "ATP", "tournament": "French Open",
            "stage": "Semifinal", "raw_custom_strike": {"Set Score": s, "tennis_competitor": "kp"},
            "yes_ask_c": ask, "yes_bid_c": 1, "no_ask_c": None, "yes_bid_size": 100, "yes_ask_size": 100,
            "quote_quality": "Tight", "status": "active", "market_ticker": f"S-{s}", "kalshi_url": "x",
            "time_value": None,
        }

    def mk(player, key, no_ask):
        return {
            "series": "KXATPMATCH", "event_ticker": "EM", "kind": "match", "player": player,
            "player_key": key, "tour": "ATP", "tournament": "French Open", "stage": "Semifinal",
            "yes_ask_c": 50, "yes_bid_c": 48, "no_ask_c": no_ask, "yes_bid_size": 100, "yes_ask_size": 100,
            "quote_quality": "Tight", "status": "active", "market_ticker": f"M-{key}", "kalshi_url": "x",
            "event_title": "M", "time_value": None,
        }
    return pd.DataFrame([score("3-0", 2), score("3-1", 2), score("3-2", 2),
                         mk("P", "kp", 90), mk("Q", "kq", 10)])


def test_scanner_includes_synthetic_bundle_with_legs():
    unified, errors = scanner.unified_opportunities(
        lambda sid: _synthetic_df() if sid == "tennis" else pd.DataFrame())
    assert errors == []
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS    # legs/n_legs columns present
    syn = unified[unified["source"] == "synthetic_bundle"]
    assert len(syn) == 1
    r = syn.iloc[0]
    assert r["status"] == "EXECUTABLE_SYNTHETIC_BUNDLE"
    # PR 18: a priced/sized/active bundle routes to the review_signal bucket (not blocked).
    assert r["bucket"] == "review_signal" and r["tradable_now"] == "Review rules"
    assert r["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED"
    assert r["n_legs"] == 4 and isinstance(r["legs"], list) and len(r["legs"]) == 4
    # PR 13: every row carries a payout floor + gross ROI; the synthetic forward floor is 100¢.
    assert r["payout_floor_c"] == 100 and r["roi_pct"] == round(r["exec_gap_c"] / r["cost_c"] * 100, 1)


def _fetch(sport_id):
    if sport_id == "tennis":
        return _containment_df(gap=5)
    if sport_id == "nba":
        return _dutchbook_df(gap=7)
    return pd.DataFrame()   # wnba (and anything else): no open contracts


def test_aggregates_multiple_sports_and_stamps_sport():
    unified, errors = scanner.unified_opportunities(_fetch)
    assert errors == []
    assert set(unified["sport"]) == {"tennis", "nba"}                 # ≥2 sports in one frame
    assert set(unified["source"]) == {"containment", "dutch_book"}    # both detectors represented
    # The dutch-book row was fetched for nba -> stamped nba; the containment rows for tennis.
    assert (unified.loc[unified["source"] == "dutch_book", "sport"] == "nba").all()
    assert (unified.loc[unified["source"] == "containment", "sport"] == "tennis").all()
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS


def test_ranking_actionable_first_then_edge():
    unified, _ = scanner.unified_opportunities(_fetch)
    # nba dutch book (actionable, edge 7) outranks tennis containment (actionable, edge 5);
    # the MISSING_LAYER data-quality row sorts last.
    assert unified.iloc[0]["source"] == "dutch_book" and unified.iloc[0]["exec_gap_c"] == 7
    assert unified.iloc[1]["source"] == "containment" and unified.iloc[1]["exec_gap_c"] == 5
    assert unified.iloc[0]["bucket"] == "actionable" and unified.iloc[1]["bucket"] == "actionable"
    assert unified.iloc[-1]["bucket"] == "data_quality"


def test_partial_failure_does_not_blank_other_sports():
    def fetch_raises(sport_id):
        if sport_id == "tennis":          # first sport in the registry order -> proves no blanking
            raise RuntimeError("boom")
        return _fetch(sport_id)
    unified, errors = scanner.unified_opportunities(fetch_raises)
    assert errors == [{"sport": "tennis", "error": "boom"}]
    assert set(unified["sport"]) == {"nba"}            # nba still present despite tennis failing
    assert not unified.empty


def test_snapshot_written_via_injected_store(tmp_path):
    db = str(tmp_path / "scan.db")
    unified, _ = scanner.unified_opportunities(
        _fetch,
        store_writer=lambda fa, df: store.write_snapshot(fa, df, db_path=db),
        fetched_at="2026-06-03 12:00:00 UTC",
    )
    back = store.latest_two(db_path=db)[0]["opportunities"]
    assert {o["opportunity_id"] for o in back} == set(unified["opportunity_id"])
    assert len(back) == len(unified)


def test_empty_when_all_sports_empty():
    unified, errors = scanner.unified_opportunities(lambda sid: pd.DataFrame())
    assert unified.empty
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS    # columns intact even when empty
    assert errors == []


# --- Stage 3: unified row carries the lifecycle-diff fields (rule_flag + market_status) ---
def test_unified_columns_include_lifecycle_fields():
    assert "rule_flag" in scanner.UNIFIED_COLUMNS
    assert "market_status" in scanner.UNIFIED_COLUMNS


def test_rows_carry_market_status_and_rule_flag():
    unified, _ = scanner.unified_opportunities(_fetch)
    assert set(unified["market_status"]) <= {"active", "inactive"}
    # containment rows expose rule_flag (possibly ""), dutch-book rows never carry a rule caveat
    assert (unified.loc[unified["source"] == "dutch_book", "rule_flag"] == "").all()


def test_market_status_derived_from_leg_statuses():
    # consistency mapper: inactive iff any present leg is non-active (blank does not count).
    assert scanner._market_status_consistency({"child_status": "active", "parent_status": "active"}) == "active"
    assert scanner._market_status_consistency({"child_status": "active", "parent_status": ""}) == "active"
    assert scanner._market_status_consistency({"child_status": "finalized", "parent_status": "active"}) == "inactive"


# --- Stage 4: run_scan coverage aggregation -------------------------------------------
def test_run_scan_aggregates_coverage_and_unifies():
    def fetch_fn(sid):
        if sid == "tennis":
            return _containment_df(gap=5), "fa", [("KXBAD", "boom")], 6, 5, 1, 2
        if sid == "nba":
            return _dutchbook_df(gap=7), "fa", [], 6, 6, 0, 0
        return pd.DataFrame(), "fa", [], 6, 0, 0, 0   # every other registered sport: empty
    unified, cov = scanner.run_scan(fetch_fn, fetched_at="FA")
    assert cov["fetched_at"] == "FA"
    # 6 scanned per registered sport (robust as sports are added); only tennis(5)+nba(6) load.
    assert cov["scanned"] == 6 * len(sports.all_sports()) and cov["loaded"] == 11
    assert cov["failed"] == 1 and cov["excluded"] == 2 and cov["skipped_no_name"] == 1
    assert len(cov["series_errors"]) == 1 and cov["series_errors"][0]["series"] == "KXBAD"
    assert not unified.empty and set(unified["sport"]) <= {"tennis", "nba"}


def test_run_scan_records_sport_fetch_failure_without_blanking():
    def fetch_fn(sid):
        if sid == "tennis":
            raise RuntimeError("down")
        if sid == "nba":
            return _dutchbook_df(gap=7), "fa", [], 6, 6, 0, 0
        return pd.DataFrame(), "fa", [], 6, 0, 0, 0
    unified, cov = scanner.run_scan(fetch_fn, fetched_at="FA")
    assert any(e["sport"] == "tennis" and "down" in e["error"] for e in cov["sport_errors"])
    assert set(unified["sport"]) <= {"nba"}                      # tennis failed; others still scanned


# --- leg <-> ticker <-> url alignment (regression: links must follow the legs) -------
def test_consistency_leg_ticker_url_alignment():
    """Containment row: leg 1 = parent/broader (Buy YES), leg 2 = child/deeper (Buy NO).
    The links must match the legs: url -> parent (leg 1), url_2 -> child (leg 2)."""
    r = {
        "parent_ticker": "PT", "child_ticker": "CT",
        "parent_url": "https://k/parent", "child_url": "https://k/child",
    }
    out = scanner._to_unified_consistency(r, sports.TENNIS)
    assert out["ticker_1"] == "PT" and out["url"] == "https://k/parent"    # leg 1 -> parent
    assert out["ticker_2"] == "CT" and out["url_2"] == "https://k/child"   # leg 2 -> child
    # Fallbacks stay within the leg's own side: a missing child link does not steal leg 1's parent link.
    out2 = scanner._to_unified_consistency(
        {"parent_ticker": "PT", "child_ticker": "CT", "parent_url": "https://k/parent"}, sports.TENNIS)
    assert out2["url"] == "https://k/parent" and out2["url_2"] == "https://k/parent"


def test_dutchbook_leg_ticker_url_shape():
    """Dutch-book row: two legs of one event -> both leg tickers, a single event link, no second link."""
    r = {"ticker_a": "TA", "ticker_b": "TB", "url": "https://k/event"}
    out = scanner._to_unified_dutchbook(r, sports.NBA)
    assert out["ticker_1"] == "TA" and out["ticker_2"] == "TB"
    assert out["url"] == "https://k/event" and out["url_2"] == ""


# --- Stage 5 §0: explanation-panel enrichment fields ---------------------------------
def test_unified_columns_include_explanation_fields():
    for col in ("action_1_price_c", "action_2_price_c", "cost_c", "ticker_1", "ticker_2", "url_2"):
        assert col in scanner.UNIFIED_COLUMNS


def test_explanation_fields_populated_per_source():
    unified, _ = scanner.unified_opportunities(_fetch)
    for col in ("action_1_price_c", "action_2_price_c", "cost_c", "ticker_1", "ticker_2", "url_2"):
        assert col in unified.columns
    db = unified[unified["source"] == "dutch_book"].iloc[0]
    assert db["cost_c"] is not None and db["action_1_price_c"] is not None
    assert db["ticker_1"] and db["ticker_2"]          # both leg tickers present
    cont = unified[unified["source"] == "containment"]
    # the actionable containment row carries numeric leg prices + both leg tickers
    act = cont[cont["bucket"] == "actionable"]
    if not act.empty:
        r = act.iloc[0]
        assert r["action_1_price_c"] is not None and r["ticker_1"] and r["ticker_2"]


# --- PR 13: payout_floor_c + roi_pct + uniform legs ----------------------------------
def test_unified_columns_include_floor_and_roi():
    for col in ("payout_floor_c", "roi_pct"):
        assert col in scanner.UNIFIED_COLUMNS


def test_gross_roi_pct_helper():
    assert scanner.gross_roi_pct(7, 93) == round(7 / 93 * 100, 1)
    assert scanner.gross_roi_pct(10, 0) is None          # non-positive cost -> None (no divide-by-zero)
    assert scanner.gross_roi_pct(None, 93) is None
    assert scanner.gross_roi_pct(5, float("nan")) is None


def test_legs_of_synthesizes_two_leg_and_passes_through_n_leg():
    # N-leg shape: returns the row's own legs untouched.
    real = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    assert scanner.legs_of({"legs": real}) is real
    # 2-leg shape: synthesize from positional action fields + tickers + links.
    row = {"action_1_side": "buy_yes", "action_1_contract": "Reach Final", "action_1_price_c": 40,
           "action_1_text": "Buy YES — Reach Final @ 40¢", "ticker_1": "PT", "url": "u1",
           "action_2_side": "buy_no", "action_2_contract": "Win", "action_2_price_c": 38,
           "action_2_text": "Buy NO — Win @ 38¢", "ticker_2": "CT", "url_2": "u2"}
    legs = scanner.legs_of(row)
    assert [lg["text"] for lg in legs] == ["Buy YES — Reach Final @ 40¢", "Buy NO — Win @ 38¢"]
    assert legs[0]["ticker"] == "PT" and legs[0]["url"] == "u1" and legs[0]["price_c"] == 40
    assert legs[1]["ticker"] == "CT" and legs[1]["url"] == "u2"
    # A leg with no action text is dropped (a single-sided / clean row yields a shorter list, no blank leg).
    assert scanner.legs_of({"action_1_text": "only one", "ticker_1": "X"}) == [
        {"side": "", "contract": "", "price_c": None, "size": None, "ticker": "X", "url": "", "text": "only one"}]
    assert scanner.legs_of({}) == []


def test_rows_carry_floor_roi_and_synthesized_legs():
    unified, _ = scanner.unified_opportunities(_fetch)
    db = unified[unified["source"] == "dutch_book"].iloc[0]
    assert db["payout_floor_c"] == 100                                       # 2-way book pays 100¢
    assert db["roi_pct"] == round(db["exec_gap_c"] / db["cost_c"] * 100, 1)
    assert isinstance(db["legs"], list) and len(db["legs"]) == 2             # synthesized 2-leg list
    act = unified[(unified["source"] == "containment") & (unified["bucket"] == "actionable")]
    if not act.empty:
        r = act.iloc[0]
        assert r["payout_floor_c"] == 100 and r["roi_pct"] is not None       # broader-YES + deeper-NO floor
        assert isinstance(r["legs"], list) and len(r["legs"]) == 2
