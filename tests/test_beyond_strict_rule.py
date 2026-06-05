"""Unit tests for the "beyond the strict rule" feature (PR 29): risk-budget candidates (containment
near-misses — bounded loss, convex upside) and near-miss dutch books (flat-payout watchlist). Covers the
opt-in band (default-off = no-op), the containment-only / equivalence-excluded guard, honest tradability,
the convex payoff plumbing, the strict-XOR-near-miss dedupe, and the strict-pipeline isolation."""
from __future__ import annotations

import pandas as pd
from test_consistency import _ckey_row, leg  # reuse the existing row builders (tests dir is on sys.path)
from test_dutchbook import market

import consistency
import dutchbook
import lifecycle
import scanner
from webui import viewmodel as vm


# --- consistency: RISK_BUDGET_CANDIDATE (containment near-miss) -----------------------------------------
def test_risk_budget_candidate_is_opt_in_and_honestly_tradable():
    # child bid 34 ≤ parent ask 36 → gap −2 → cost 102, worst-case loss 2, convex upside.
    child = leg(display_c=34, bid_c=34, ask_c=35, no_ask_c=66)
    parent = leg(display_c=36, bid_c=35, ask_c=36)
    # default (band off) → an ordinary CLEAN row, byte-for-byte unchanged.
    assert consistency._classify(child, parent, equivalence=False)["status"] == "CLEAN"
    out = consistency._classify(child, parent, equivalence=False, risk_budget_max_loss_c=5)
    assert out["status"] == "RISK_BUDGET_CANDIDATE"
    assert out["exec_gap_c"] == -2                  # worst-case profit per unit (the loss)
    assert out["tradable_now"] == "Yes"             # legs firm/sized/active → honestly placeable
    assert out["action_1_side"] == "buy_yes" and out["action_2_side"] == "buy_no"
    assert consistency.bucket_of(out) == "risk_budget"


def test_risk_budget_excludes_equivalence_match_alignment():
    # Same near-miss prices but as an equivalence (match-alignment) pair → never a risk-budget candidate
    # (no clean convex payoff; carries a rule-risk settlement state).
    child = leg(display_c=34, bid_c=34, ask_c=35, no_ask_c=66)
    parent = leg(display_c=36, bid_c=35, ask_c=36)
    out = consistency._classify(child, parent, equivalence=True, risk_budget_max_loss_c=5)
    assert out["status"] != "RISK_BUDGET_CANDIDATE"


def test_risk_budget_boundaries_zero_loss_in_six_out():
    # gap 0 (cost exactly 100 — zero downside, convex upside = the premium candidate) is INCLUDED.
    child0 = leg(display_c=36, bid_c=36, ask_c=37, no_ask_c=64)
    parent0 = leg(display_c=36, bid_c=35, ask_c=36)
    out0 = consistency._classify(child0, parent0, False, risk_budget_max_loss_c=5)
    assert out0["status"] == "RISK_BUDGET_CANDIDATE" and out0["exec_gap_c"] == 0
    # gap −6 (loss 6 > the 5¢ budget) is EXCLUDED → ordinary CLEAN.
    child6 = leg(display_c=30, bid_c=30, ask_c=31, no_ask_c=70)
    parent6 = leg(display_c=36, bid_c=35, ask_c=36)
    out6 = consistency._classify(child6, parent6, False, risk_budget_max_loss_c=5)
    assert out6["status"] == "CLEAN"


def test_build_checks_band_tags_convex_payoff_and_edge_class():
    # Win Tournament (deeper) bid 39 ≤ Reach Final (broader) ask 42 → gap −3 near-miss.
    champ = _ckey_row("P", "uuid-p", "winner", "Champion", 40)   # bid 39 / ask 41
    final = _ckey_row("P", "uuid-p", "advance", "Final", 41)      # bid 40 / ask 42
    df = pd.DataFrame([champ, final])
    base = consistency.build_checks(df)                           # default: no band
    assert "risk_budget" not in set(base["bucket"])
    out = consistency.build_checks(df, risk_budget_max_loss_c=5)
    rb = out[out["bucket"] == "risk_budget"]
    assert len(rb) == 1
    r = rb.iloc[0]
    assert r["status"] == "RISK_BUDGET_CANDIDATE" and r["edge_class"] == "risk_budget"
    assert r["exec_gap_c"] == -3
    assert r["worst_case_profit_c"] == -3 and r["best_case_profit_c"] == 97   # convex: bounded loss, $1 bonus
    assert r["roc_pct"] is not None and r["roc_pct"] < 0                       # worst-case ROC, honestly negative


# --- dutchbook: NEAR_MISS_DUTCH_BOOK (flat-payout watchlist) ---------------------------------------------
def _near_miss_book(over=2):
    """A 2-way overround book overpriced by `over`¢: no_ask sum = 100 + over (flat-loss near-miss);
    underround pushed well out of band so the overround is the selected direction."""
    no_ask = (100 + over) // 2
    a = market("Sabalenka", yes_bid_c=44, yes_ask_c=70, no_ask_c=no_ask)
    b = market("Shnaider", yes_bid_c=44, yes_ask_c=70, no_ask_c=(100 + over) - no_ask)
    return [a, b]


def test_near_miss_surfaces_only_with_band_and_is_flat_loss():
    rows = _near_miss_book(over=2)
    assert dutchbook.find_dutch_books(rows) == []                # strict-only default: nothing
    out = dutchbook.find_dutch_books(rows, near_miss_max_over_c=5)
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.NEAR_MISS_DUTCH_BOOK
    assert f["edge_class"] == "near_miss" and f["bucket"] == "near_miss"
    assert f["cost_c"] == 102 and f["exec_gap_c"] == -2
    assert f["worst_case_profit_c"] == f["best_case_profit_c"] == -2          # flat payout, guaranteed loss
    assert f["tradable_now"] == "Yes"                                         # legs honestly tradable
    assert f["blocked_reason"] == ""                                          # near_miss bucket ≠ blocked
    assert "watchlist only" in f["reason"].lower()
    assert f["settlement_caveat"]                                             # the flat-loss caveat is attached


def test_strict_dutch_book_wins_over_near_miss():
    # underround 45 + 48 = 93 < 100 → a strict book; the near-miss band must not change it.
    a = market("Alcaraz", yes_bid_c=43, yes_ask_c=45)
    b = market("Sinner", yes_bid_c=46, yes_ask_c=48)
    out = dutchbook.find_dutch_books([a, b], near_miss_max_over_c=5)
    assert len(out) == 1
    assert out[0]["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and out[0]["edge_class"] == "strict"


def test_near_miss_excludes_break_even_and_beyond_band():
    assert dutchbook.find_dutch_books(_near_miss_book(over=0), near_miss_max_over_c=5) == []   # break-even gross
    assert dutchbook.find_dutch_books(_near_miss_book(over=6), near_miss_max_over_c=5) == []   # 6¢ > 5¢ band


# --- scanner round-trip: the new buckets reach the unified frame --------------------------------------
def _containment_near_miss_df():
    """One player whose Win-Tournament bid is 3¢ BELOW the Reach-Final ask → a risk-budget near-miss."""
    def row(series, kind, stage, bid, ask):
        return {"series": series, "kind": kind, "stage": stage, "player": "P", "player_key": "uuid-p",
                "contract": f"{kind}-{stage}", "display_pct": float(bid), "display_c": bid,
                "yes_bid_c": bid, "yes_ask_c": ask, "yes_bid_pct": float(bid), "yes_ask_pct": float(ask),
                "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
                "market_ticker": f"T-{stage}", "kalshi_url": "x", "status": "active",
                "tournament": "French Open", "event_ticker": f"E-{stage}"}
    return pd.DataFrame([row("KXFOWOMEN", "winner", "Champion", 37, 38),    # Win Tournament bid 37
                         row("KXWTAADVANCE", "advance", "Final", 39, 40)])  # Reach Final ask 40 → gap −3


def test_scanner_surfaces_risk_budget_with_convex_columns():
    unified, errors = scanner.unified_opportunities(
        lambda sid: _containment_near_miss_df() if sid == "tennis" else pd.DataFrame())
    assert errors == []
    assert list(unified.columns) == scanner.UNIFIED_COLUMNS
    rb = unified[unified["bucket"] == "risk_budget"]
    assert len(rb) == 1
    r = rb.iloc[0]
    assert r["edge_class"] == "risk_budget" and r["exec_gap_c"] == -3
    assert r["worst_case_profit_c"] == -3 and r["best_case_profit_c"] == 97
    assert r["roi_pct"] is not None and r["roi_pct"] < 0


def test_bucket_priority_and_dashboard_buckets_stay_in_sync():
    assert set(scanner.BUCKET_PRIORITY) == set(consistency.DASHBOARD_BUCKETS)
    bp = scanner.BUCKET_PRIORITY
    assert bp["blocked"] < bp["risk_budget"] < bp["near_miss"] < bp["near_edge"]


# --- strict-pipeline isolation (audit §6): lifecycle/alerts/backlog ignore the new buckets ----------------
def test_lifecycle_ignores_risk_budget_and_near_miss():
    def op(oid, bucket):
        return {"opportunity_id": oid, "bucket": bucket, "market_status": "active"}

    def snap(ts, *rows):
        return {"fetched_at": f"t{ts}", "fetched_ts": float(ts), "opportunities": list(rows)}

    prev_s = snap(1, op("x", "blocked"))
    cur_s = snap(2, op("rb", "risk_budget"), op("nm", "near_miss"), op("x", "blocked"))
    # Neither new bucket counts as "new actionable".
    assert lifecycle.new_actionable(prev_s, cur_s) == []
    # Neither ever appears in the recently-actionable backlog (they were never actionable).
    hist = [snap(1, op("rb", "risk_budget"), op("nm", "near_miss")), cur_s]
    assert lifecycle.recently_actionable(hist) == []
    # A strict→risk_budget transition is not a new-actionable either.
    assert lifecycle.new_actionable(snap(1, op("y", "actionable")), snap(2, op("y", "risk_budget"))) == []


# --- viewmodel: the two opt-in sections' pure band-filters + display rows ------------------------------
def _rb(oid, *, worst, best, cost=102):
    return {"opportunity_id": oid, "bucket": "risk_budget", "source": "containment", "sport": "tennis",
            "sport_label": "Tennis", "name": "Alcaraz", "detail": "Win ≤ Final", "cost_c": cost,
            "worst_case_profit_c": worst, "best_case_profit_c": best, "roi_pct": -2.9,
            "tradable_now": "Yes", "settlement_caveat": "", "blocked_reason": ""}


def _nm(oid, *, gap, cost=102):
    return {"opportunity_id": oid, "bucket": "near_miss", "source": "dutch_book", "sport": "tennis",
            "sport_label": "Tennis", "name": "A vs B", "detail": "overround", "cost_c": cost,
            "exec_gap_c": gap, "tradable_now": "Yes", "settlement_caveat": "watchlist only — NOT an edge"}


def test_risk_budget_view_filters_by_max_loss_and_ratio():
    opps = [_rb("loss2", worst=-2, best=98), _rb("loss5", worst=-5, best=95),
            _rb("loss8", worst=-8, best=92), _rb("premium", worst=0, best=100)]
    ids = lambda rows: {r["opportunity_id"] for r in rows}  # noqa: E731
    assert ids(vm.risk_budget_view(opps, max_loss_c=5)) == {"loss2", "loss5", "premium"}     # loss8 dropped
    # ratio gate ≥ 20.0:1 (tenths 200): loss2 49:1 passes, loss5 19:1 drops, premium (∞) always passes.
    assert ids(vm.risk_budget_view(opps, max_loss_c=5, min_ratio_tenths=200)) == {"loss2", "premium"}


def test_near_miss_view_filters_by_overpay():
    opps = [_nm("o2", gap=-2), _nm("o4", gap=-4), _nm("o0", gap=0)]
    ids = lambda rows: {r["opportunity_id"] for r in rows}  # noqa: E731
    assert ids(vm.near_miss_view(opps, max_over_c=3)) == {"o2"}          # o4 too far, o0 not over the floor
    assert ids(vm.near_miss_view(opps, max_over_c=5)) == {"o2", "o4"}


def test_risk_budget_row_leads_with_convex_economics():
    r = vm.risk_budget_row(_rb("x", worst=-3, best=97), set())
    assert r["max_loss"] == 3 and r["max_profit"] == 97 and r["ratio"] == round(97 / 3, 1)
    assert vm.risk_budget_row(_rb("p", worst=0, best=100), set())["ratio"] == "∞"   # zero-downside premium


def test_near_miss_row_shows_overpay_and_note_not_edge():
    r = vm.near_miss_row(_nm("y", gap=-2), set())
    assert r["overpay"] == 2 and r["note"]
