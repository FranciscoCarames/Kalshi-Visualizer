"""Unit tests for the pure fee / round-trip cost module (no network, no UI)."""
from __future__ import annotations

import roundtrip_cost as rc


def test_fee_formula_matches_published_quadratic():
    # ceil(coeff · C · P · (1−P)) in cents
    assert rc.fee_c(1, 50, 0.07) == 2          # 0.07·0.5·0.5·100 = 1.75 → 2
    assert rc.fee_c(1, 68, 0.07) == 2          # 1.5232 → 2
    assert rc.fee_c(1, 50, 0.0175) == 1        # 0.4375 → 1


def test_fee_zero_at_endpoints_and_invalid():
    assert rc.fee_c(1, 0, 0.07) == 0
    assert rc.fee_c(1, 100, 0.07) == 0
    assert rc.fee_c(0, 50, 0.07) == 0
    assert rc.fee_c(1, 50, None) == 0
    assert rc.fee_c(None, 50, 0.07) == 0


def test_roundtrip_is_two_independent_ceilings():
    # each fill ceils independently — 2 + 2, not ceil(of the sum)
    assert rc.roundtrip_cost_c(1, 50, 50, 0.07) == 4


def test_effective_coeffs_known_only_with_real_multiplier():
    known = rc.effective_coeffs("quadratic_with_maker_fees", 1)
    assert known["known"] is True
    assert abs(known["taker"] - 0.07) < 1e-9 and abs(known["maker"] - 0.0175) < 1e-9

    assumed = rc.effective_coeffs("quadratic_with_maker_fees", None)
    assert assumed["known"] is False and assumed["status"] == "assumed_multiplier"

    assert rc.effective_coeffs("flat", 1)["known"] is False
    assert rc.effective_coeffs("", None)["known"] is False
    assert rc.effective_coeffs("mystery", 1)["known"] is False


def test_plain_quadratic_has_no_maker_fee():
    eff = rc.effective_coeffs("quadratic", 1)
    assert eff["maker"] == 0.0 and eff["known"] is True


def test_cost_paths_blocks_when_fee_unknown():
    unknown = rc.cost_paths(50, None)
    assert unknown["fee_known"] is False
    known = rc.cost_paths(50, {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1})
    assert known["fee_known"] is True
    assert known["cost_hold_c"] == 2
    assert known["cost_roundtrip_taker_c"] == 4
    assert known["cost_maker_entry_taker_exit_c"] == 3      # maker 1 + taker 2
