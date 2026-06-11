"""Unit tests for the pure de-vig transforms in ``probability.py`` (Phase 2a — math only, no UI).

These prove the normalization sums to the survivor count K, that a uniform vig cancels in ratios, and that
a sparse one-winner field is NOT inflated. No field-implied number is exposed to the UI on this branch.
"""
import math

import pytest

import probability as P


# --- devig_proportional ------------------------------------------------------------------------------
@pytest.mark.parametrize("k", [1, 2, 4, 5])
def test_devig_proportional_sums_to_k(k):
    out = P.devig_proportional([60, 30, 10, 5], k)
    assert out is not None
    assert math.isclose(sum(out), k, rel_tol=1e-9)
    assert all(0 <= v for v in out)


def test_devig_proportional_preserves_ratios_so_vig_cancels():
    # A uniform multiplicative vig (scale every price by a common factor) leaves the normalized
    # probabilities — and therefore any ratio between two of them — unchanged. This IS the vig-cancellation
    # property the conditional "chance if reached" relies on.
    base = [50, 25, 25]
    vigged = [p * 1.18 for p in base]   # +18% overround applied uniformly
    a = P.devig_proportional(base, 1)
    b = P.devig_proportional(vigged, 1)
    assert a is not None and b is not None
    for x, y in zip(a, b):
        assert math.isclose(x, y, rel_tol=1e-9)
    # ratio child/parent is identical to the raw price ratio
    assert math.isclose(a[1] / a[0], base[1] / base[0], rel_tol=1e-9)


def test_devig_proportional_fails_closed():
    assert P.devig_proportional([], 1) is None
    assert P.devig_proportional([10, 20], 0) is None          # k <= 0
    assert P.devig_proportional([10, 20], -1) is None
    assert P.devig_proportional([0, 0], 1) is None            # sum <= 0
    assert P.devig_proportional([10, None, 20], 1) is None    # all-or-nothing on a missing leg
    assert P.devig_proportional([10, float("nan")], 1) is None
    assert P.devig_proportional([10, -5], 1) is None          # negative price


# --- devig_field -------------------------------------------------------------------------------------
def test_devig_field_exhaustive_three_way_normalizes_to_one():
    # Soccer 3-way (Home/Away/Tie), prices overround to >100¢: renormalize to sum K=1.
    out = P.devig_field([45, 40, 25], 1, exhaustive=True)
    assert out is not None
    probs, partial = out
    assert partial is False
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)


def test_devig_field_basket_k2_sums_to_two():
    out = P.devig_field([70, 60, 50, 40], 2, exhaustive=True)
    assert out is not None
    probs, partial = out
    assert math.isclose(sum(probs), 2.0, rel_tol=1e-9)
    assert partial is False


def test_devig_field_one_winner_overround_normalizes():
    # Priceable subset sums to >100¢ (overround present) → scale to K=1, not partial.
    out = P.devig_field([70, 50], 1, exhaustive=False)
    assert out is not None
    probs, partial = out
    assert partial is False
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)


def test_devig_field_sparse_one_winner_returns_floors_not_inflated():
    # The 12-of-80-golfers failure mode: visible subset sums to 0.85 (<K=1). Do NOT inflate to sum 1 —
    # return the raw masses as floors and flag partial.
    out = P.devig_field([60, 25], 1, exhaustive=False)
    assert out is not None
    probs, partial = out
    assert partial is True
    assert math.isclose(probs[0], 0.60, rel_tol=1e-9)
    assert math.isclose(probs[1], 0.25, rel_tol=1e-9)
    assert sum(probs) < 1.0


def test_devig_field_drops_unpriced_legs_in_subset():
    # None/negative legs are dropped from the priceable subset; the rest still normalize.
    out = P.devig_field([70, None, 50, -3], 1, exhaustive=False)
    assert out is not None
    probs, partial = out
    assert len(probs) == 2
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)


def test_devig_field_fails_closed():
    assert P.devig_field([], 1, exhaustive=True) is None
    assert P.devig_field([50, 50], 0, exhaustive=True) is None
    assert P.devig_field([0, 0], 1, exhaustive=True) is None
