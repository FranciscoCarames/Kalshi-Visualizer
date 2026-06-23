"""Golden tests for the pure forward-test scorer (``paper_engine``)."""
from __future__ import annotations

import config
import paper_engine as pe
import roundtrip_cost


def _row(**over):
    """A minimal unified-opportunity row with a 2-leg buy-only plan."""
    base = {
        "opportunity_id": "opp-abc",
        "sport": "tennis",
        "bucket": "actionable",
        "relationship_type": "dutch_book",
        "exec_gap_c": 5,
        "cost_c": 95,
        "legs": [
            {"side": "buy_yes", "ticker": "TICK_A", "price_c": 48, "size": 10, "contract": "A wins"},
            {"side": "buy_yes", "ticker": "TICK_B", "price_c": 47, "size": 8, "contract": "B wins"},
        ],
    }
    base.update(over)
    return base


def _settle(result, status="settled", settled_ts=1000.0):
    return {"result": result, "status": status, "settled_ts": settled_ts}


# --- extract_entry ----------------------------------------------------------------

def test_extract_executable_entry_basics():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    assert e is not None
    assert e.scorable is True
    assert e.opportunity_class == "executable"
    assert e.cost_c == 95
    assert e.max_loss_c == 95          # buy-only: loss bounded by the stake
    assert [leg.side for leg in e.legs] == ["yes", "yes"]
    assert e.fill_model == config.PAPER_FILL_MODEL


def test_extract_speculative_when_exec_gap_none():
    e = pe.extract_entry(_row(exec_gap_c=None, bucket="speculative_model"), opened_ts=1.0)
    assert e.opportunity_class == "speculative"
    assert e.scorable is True          # speculative is still scorable when legs are priced


def test_entry_key_is_stable_and_fill_model_scoped():
    a = pe.extract_entry(_row(), opened_ts=1.0)
    b = pe.extract_entry(_row(), opened_ts=999.0)        # different time, same structure
    assert a.entry_key == b.entry_key                     # opened-once identity, time-independent
    c = pe.extract_entry(_row(), opened_ts=1.0, fill_model="other_v9")
    assert c.entry_key != a.entry_key                     # methodology change ⇒ distinct entry


def test_extract_none_without_opportunity_id():
    assert pe.extract_entry(_row(opportunity_id=""), opened_ts=1.0) is None


def test_extract_unscorable_when_leg_missing_price():
    bad = _row(cost_c=None, legs=[{"side": "buy_yes", "ticker": "T", "price_c": None}])
    e = pe.extract_entry(bad, opened_ts=1.0)
    assert e.scorable is False
    assert "price" in e.unscorable_reason


# --- score_entry ------------------------------------------------------------------

def test_winning_dutch_book_nets_positive():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    # A wins the head-to-head: TICK_A settles yes, TICK_B settles no.
    res = pe.score_entry(e, {"TICK_A": _settle("yes"), "TICK_B": _settle("no")},
                         fee_coeffs={"TICK_A": config.FEE_TAKER_BASE_COEFF,
                                     "TICK_B": config.FEE_TAKER_BASE_COEFF})
    assert res.status == pe.STATUS_SETTLED
    assert res.gross_c == 5            # 100 payout − 95 cost
    expected_fees = (roundtrip_cost.fee_c(1, 48, config.FEE_TAKER_BASE_COEFF)
                     + roundtrip_cost.fee_c(1, 47, config.FEE_TAKER_BASE_COEFF))
    assert res.fees_c == expected_fees
    assert res.net_c == res.gross_c - res.fees_c
    assert res.won is (res.net_c > 0)
    assert res.fee_known is True


def test_losing_position_nets_negative():
    e = pe.extract_entry(_row(cost_c=105), opened_ts=1.0)
    res = pe.score_entry(e, {"TICK_A": _settle("yes"), "TICK_B": _settle("no")})
    assert res.status == pe.STATUS_SETTLED
    assert res.gross_c == -5           # 100 − 105
    assert res.net_c < 0
    assert res.won is False


def test_containment_bonus_state_pays_both_legs():
    # Buy YES broader @30, Buy NO deeper @60. If broader=yes and deeper=no, BOTH legs pay 100.
    row = _row(cost_c=90, relationship_type="containment", legs=[
        {"side": "buy_yes", "ticker": "BROAD", "price_c": 30, "size": 5},
        {"side": "buy_no", "ticker": "DEEP", "price_c": 60, "size": 5},
    ])
    e = pe.extract_entry(row, opened_ts=1.0)
    res = pe.score_entry(e, {"BROAD": _settle("yes"), "DEEP": _settle("no")})
    assert res.gross_c == 200 - 90


def test_open_when_a_leg_unsettled():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    res = pe.score_entry(e, {"TICK_A": _settle("yes")})   # TICK_B unknown
    assert res.status == pe.STATUS_OPEN
    assert res.net_c is None


def test_determined_pending_does_not_finalize():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    res = pe.score_entry(e, {"TICK_A": _settle("yes", status="determined"),
                             "TICK_B": _settle("no", status="determined")})
    assert res.status == pe.STATUS_DETERMINED_PENDING
    assert res.net_c is None           # outcomes known but not yet paid out

def test_non_binary_result_keeps_open():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    res = pe.score_entry(e, {"TICK_A": _settle("scalar"), "TICK_B": _settle("")})
    assert res.status == pe.STATUS_OPEN


def test_unscorable_entry_scores_unscorable():
    bad = _row(cost_c=None, legs=[{"side": "buy_yes", "ticker": "T", "price_c": None}])
    e = pe.extract_entry(bad, opened_ts=1.0)
    res = pe.score_entry(e, {})
    assert res.status == pe.STATUS_UNSCORABLE


def test_missing_fee_coeff_flags_fee_unknown():
    e = pe.extract_entry(_row(), opened_ts=1.0)
    res = pe.score_entry(e, {"TICK_A": _settle("yes"), "TICK_B": _settle("no")})  # no fee_coeffs
    assert res.status == pe.STATUS_SETTLED
    assert res.fee_known is False       # fell back to the taker base → disclosed
