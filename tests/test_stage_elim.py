"""Unit tests for the stage-of-elimination detector (KXWCSTAGEOFELIM) — no network.

Covers both outputs: the standalone within-event 7-way MECE book (underround / overround, fail-closed
proof gates, blocked states) and the cross-family tail-sum vs the advance ladder (review-only, never
Actionable). Plus the proof_audit diagnostic and the scanner round-trip.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import data
import scanner
import sports
import stage_elim

_BUCKETS = ("GS", "R32", "R16", "QF", "SF", "FL", "FW")


def selim(suffix, *, team="usa", event="KXWCSTAGEOFELIM-26USA", yes_ask_c=None, no_ask_c=None,
          yes_bid_c=None, status="active", quality="Tight", ask_size=100, bid_size=100):
    """One stage-of-elimination bucket row (the market-ticker suffix carries the bucket)."""
    return {
        "series": "KXWCSTAGEOFELIM", "event_ticker": event, "kind": "stage_of_elim",
        "player": f"USA {suffix}", "player_key": team, "is_participant": True,
        "tournament": "2026 FIFA World Cup", "tour": "",
        "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c, "yes_bid_c": yes_bid_c,
        "yes_ask_size": ask_size, "yes_bid_size": bid_size, "quote_quality": quality, "status": status,
        "market_ticker": f"{event}-{suffix}", "kalshi_url": "https://kalshi.com/x", "event_title": "USA SoE",
    }


def team_buckets(yes_asks=None, no_asks=None, suffixes=_BUCKETS, **kw):
    rows = []
    for i, s in enumerate(suffixes):
        d = dict(kw)
        if yes_asks is not None:
            d["yes_ask_c"] = yes_asks[i]
        if no_asks is not None:
            d["no_ask_c"] = no_asks[i]
        rows.append(selim(s, **d))
    return rows


# --- standalone 7-way MECE book -----------------------------------------------------
def test_book_underround_fires():
    # 7 YES asks of 10 each = 70 < 100 floor (one bucket wins) -> 30c gross per unit.
    f = stage_elim.find_stage_elim_books(team_buckets(yes_asks=[10] * 7))
    assert len(f) == 1
    g = f[0]
    assert g["status"] == stage_elim.EXECUTABLE_STAGE_ELIM_BOOK and g["direction"] == "underround"
    assert g["payout_floor_c"] == 100 and g["cost_c"] == 70 and g["exec_gap_c"] == 30
    assert g["n_legs"] == 7 and all(leg["side"] == "buy_yes" for leg in g["legs"])
    assert g["bucket"] == "actionable" and g["tradable_now"] == "Yes"
    assert g["settlement_caveat"] == ""           # a clean MECE set carries no caveat
    assert "locked" not in g["reason"].lower() and "arbitrage" not in g["reason"].lower()


def test_book_overround_fires():
    # 7 NO asks of 10 each = 70 < 600 floor (six lose) -> 530c. YES priced high so underround can't fire.
    f = stage_elim.find_stage_elim_books(team_buckets(yes_asks=[92] * 7, no_asks=[10] * 7))
    assert len(f) == 1
    g = f[0]
    assert g["direction"] == "overround" and g["payout_floor_c"] == 600
    assert g["cost_c"] == 70 and g["exec_gap_c"] == 530
    assert all(leg["side"] == "buy_no" for leg in g["legs"])


def test_book_missing_bucket_rejected_fail_closed():
    diag: dict = {}
    rows = team_buckets(yes_asks=[10] * 6, suffixes=_BUCKETS[:6])   # only 6 of 7 buckets
    assert stage_elim.find_stage_elim_books(rows, diag) == []
    assert any("expected 7 buckets" in r["reason"] for r in diag["rejected"])


def test_book_spanning_two_teams_rejected():
    diag: dict = {}
    rows = team_buckets(yes_asks=[10] * 7)
    rows[3]["player_key"] = "different-team"
    assert stage_elim.find_stage_elim_books(rows, diag) == []
    assert any("more than one team" in r["reason"] for r in diag["rejected"])


def test_book_sizeless_leg_blocked():
    rows = team_buckets(yes_asks=[10] * 7)
    rows[2]["yes_ask_size"] = 0
    f = stage_elim.find_stage_elim_books(rows)
    assert len(f) == 1 and f[0]["bucket"] == "blocked" and f[0]["tradable_now"] == "No"
    assert "0 contracts are available" in f[0]["blocked_reason"]


def test_book_inactive_leg_blocked():
    rows = team_buckets(yes_asks=[10] * 7)
    rows[5]["status"] = "finalized"
    f = stage_elim.find_stage_elim_books(rows)
    assert len(f) == 1 and f[0]["bucket"] == "blocked"
    assert "not open for trading" in f[0]["blocked_reason"]


def test_book_no_positive_gap_no_finding():
    diag: dict = {}
    # YES sum 105 > 100 (no underround); NO sum 700 > 600 (no overround).
    assert stage_elim.find_stage_elim_books(team_buckets(yes_asks=[15] * 7, no_asks=[100] * 7), diag) == []
    assert any("no positive gap" in r["reason"] for r in diag["eligible_non_firing"])


def test_book_subpenny_excluded():
    diag: dict = {}
    rows = team_buckets(yes_asks=[10] * 7)
    for r in rows:
        r["subpenny"] = True
    assert stage_elim.find_stage_elim_books(rows, diag) == []
    assert any("subpenny" in r["reason"] for r in diag["rejected"])


# --- cross-family tail-sum (review-only) --------------------------------------------
def _hedge(node, *, team="usa", yes_ask_c=None, no_ask_c=None, kind="advance", status="active",
           quality="Tight", ask_size=100, bid_size=100):
    return {
        "series": "KXWCROUND", "event_ticker": f"KXWCROUND-{node[:4]}", "kind": kind,
        "player": "USA", "player_key": team, "ladder_node": node, "tournament": "2026 FIFA World Cup",
        "tour": "", "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c,
        "yes_ask_size": ask_size, "yes_bid_size": bid_size, "quote_quality": quality, "status": status,
        "market_ticker": f"KXWCROUND-{node[:4]}-USA", "kalshi_url": "https://kalshi.com/x",
    }


def test_synthetic_forward_fires_review_only():
    # Reach Finals tail = {FL, FW}. Buy YES FL+FW (5+5) + Buy NO the advance market (80) = 90 < 100 -> 10c.
    rows = team_buckets(yes_asks=[40, 40, 40, 40, 40, 5, 5])         # FL, FW are the last two
    hedge = _hedge("Reach Finals", no_ask_c=80)
    out = stage_elim.find_stage_elim_synthetics(rows + [hedge])
    fin = [f for f in out if f["rung_node"] == "Reach Finals"]
    assert len(fin) == 1
    g = fin[0]
    assert g["status"] == stage_elim.STAGE_ELIM_SYNTHETIC and g["direction"] == "forward"
    assert g["cost_c"] == 90 and g["exec_gap_c"] == 10 and g["n_legs"] == 3
    # ALWAYS review-only — NEVER Actionable, carries the settlement flag + caveat.
    assert g["bucket"] == "review_signal" and g["tradable_now"] == "Review rules"
    assert g["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED" and g["settlement_caveat"]
    assert g["bucket"] != "actionable"


def test_synthetic_skips_rung_without_hedge():
    # No advance markets at all -> no rung can be hedged -> nothing emitted.
    rows = team_buckets(yes_asks=[5] * 7)
    assert stage_elim.find_stage_elim_synthetics(rows) == []


def test_synthetic_requires_full_bucket_set():
    rows = team_buckets(yes_asks=[5] * 6, suffixes=_BUCKETS[:6])     # incomplete
    hedge = _hedge("Reach Finals", no_ask_c=80)
    assert stage_elim.find_stage_elim_synthetics(rows + [hedge]) == []


def test_synthetic_never_actionable_even_when_firm_sized_active():
    rows = team_buckets(yes_asks=[40, 40, 40, 40, 40, 5, 5])
    hedge = _hedge("Reach Finals", no_ask_c=80)
    for f in stage_elim.find_stage_elim_synthetics(rows + [hedge]):
        assert f["tradable_now"] != "Yes" and f["bucket"] in ("review_signal", "blocked")


# --- scanner round-trip + proof audit -----------------------------------------------
def test_scanner_round_trip_book_and_synth():
    book = stage_elim.find_stage_elim_books(team_buckets(yes_asks=[10] * 7))[0]
    ub = scanner._to_unified_stage_elim_book(book, sports.SOCCER)
    assert ub["source"] == "stage_elim" and ub["bucket"] == "actionable" and ub["n_legs"] == 7

    rows = team_buckets(yes_asks=[40, 40, 40, 40, 40, 5, 5])
    synth = stage_elim.find_stage_elim_synthetics(rows + [_hedge("Reach Finals", no_ask_c=80)])[0]
    us = scanner._to_unified_stage_elim_synth(synth, sports.SOCCER)
    assert us["source"] == "stage_elim_synth" and us["bucket"] == "review_signal"
    assert us["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED"


def test_proof_audit_reports_books_synths_and_diag():
    audit = stage_elim.proof_audit(team_buckets(yes_asks=[15] * 7, no_asks=[100] * 7))
    assert audit["books"] == [] and "eligible_non_firing" in audit["diag"]


# --- live fixtures flow through the engine ------------------------------------------
_FIX = Path(__file__).parent / "fixtures" / "wc_stage_elim"


def test_live_fixtures_classify_and_are_consumed():
    files = sorted(_FIX.glob("KXWCSTAGEOFELIM-*.json"))
    assert len(files) >= 2, "expected >=2 captured teams as Phase-C evidence"
    for fp in files:
        ev = json.loads(fp.read_text(encoding="utf-8"))
        rows = data.build_contracts("KXWCSTAGEOFELIM", [ev])
        assert len(rows) == 7, fp.name                              # 7 buckets
        assert all(r["kind"] == "stage_of_elim" for r in rows), fp.name
        assert len({r["player_key"] for r in rows}) == 1, fp.name   # one team UUID across buckets
        recs = [{**r} for r in pd.DataFrame(rows).to_dict("records")]
        # The detector consumes the real (tight) books without error; a finding may or may not fire.
        for f in stage_elim.find_stage_elim_books(recs):
            assert f["status"] == stage_elim.EXECUTABLE_STAGE_ELIM_BOOK and f["n_legs"] == 7
