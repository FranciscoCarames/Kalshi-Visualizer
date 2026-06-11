"""Pure market-implied probability transforms (de-vig).

NO UI, NO pandas. Turns a MECE-ish set of YES prices into normalized, **field-implied** probability
ESTIMATES. These are a proportional normalization of DISPLAYED prices — gross, top-of-book, and
**uncalibrated**: NOT calibrated fair value, NOT net of fees / full-depth execution. Never use the word
"fair"/"true". Kept pure and independently testable; **never read by executable classification, bucketing,
or ranking**.

Phase 2a scope (this is the only Phase-2 code shipped on this branch): the math + its unit tests only.
The per-sport survivor-count hook, the scanner field pre-pass that would feed these prices, the
full ``FieldStatus`` (full / partial / sparse / unknown — needs an expected participant count), and any UI
exposure all live in a SEPARATE branch gated on a field-completeness audit. Until that audit is green, no
field-implied number is shown to a trader.

Units: prices are in CENTS (a YES price of 65¢ ⇒ an implied probability mass of 0.65). ``k`` is the
survivor-slot count for the set (champion = 1, finalist = 2, semifinalist = 4, golf Top-5 = 5,
soccer 3-way game = 1 over {Home, Away, Tie}). For a one-winner field ``k = 1``.
"""
from __future__ import annotations


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x  # x == x rejects NaN


def _clean_prices_c(prices_c) -> list[float]:
    """The priceable subset: numeric, finite, non-negative cents only (drop None / NaN / negative)."""
    return [float(p) for p in (prices_c or []) if _is_num(p) and p >= 0]


def devig_proportional(prices_c, k) -> list[float] | None:
    """Proportional (multiplicative) de-vig over a list of YES prices in CENTS.

    Returns field-implied probabilities in 0..1 that sum to ``k``:
    ``field_implied_i = p_i / (Σp) · k``. Index-aligned with ``prices_c`` and ALL-OR-NOTHING — if any
    price is missing / NaN / negative, or ``k <= 0``, or the prices sum to ≤ 0, returns None (fail closed;
    use :func:`devig_field` for the priceable-subset / non-exhaustive case).

    A model-implied normalization, NOT calibrated fair value. Because it is a single uniform rescale, it
    PRESERVES ratios (``out_i / out_j == p_i / p_j``) — which is why a conditional ratio cancels common
    multiplicative vig.
    """
    if not _is_num(k) or k <= 0:
        return None
    ps = list(prices_c or [])
    if not ps or any(not _is_num(p) or p < 0 for p in ps):
        return None
    total = float(sum(ps))
    if total <= 0:
        return None
    return [float(p) / total * k for p in ps]


def devig_field(prices_c, k, *, exhaustive: bool) -> tuple[list[float], bool] | None:
    """De-vig over the PRICEABLE SUBSET, respecting exhaustiveness. Returns ``(probabilities, partial)`` in
    probability units (0..1), or None when ``k <= 0`` or no leg is priceable.

    - ``exhaustive=True`` (group baskets, soccer 3-way Home/Away/Tie): renormalize the subset to sum ``k``.
    - ``exhaustive=False`` (one-winner MECE-but-not-exhaustive fields, e.g. a tennis/golf winner field where
      longshots have empty books): scale to sum ``k`` ONLY when the subset's implied mass ``Σ(p/100) >= k``
      (overround present). Otherwise the field is SPARSE — return the raw per-leg masses as FLOORS and
      ``partial=True`` (never inflate a thin field to sum ``k``; that is the failure mode of normalizing 12
      of 80 golfers as if they were the whole field).

    ``partial=True`` is the only status derivable from prices + ``k`` alone; the richer full/partial/sparse/
    unknown ``FieldStatus`` (which needs an EXPECTED participant count) is deferred to the field-audit branch.
    """
    if not _is_num(k) or k <= 0:
        return None
    masses = [p / 100.0 for p in _clean_prices_c(prices_c)]   # cents -> probability mass
    if not masses:
        return None
    s = sum(masses)
    if s <= 0:
        return None
    if exhaustive or s >= k:
        return [m / s * k for m in masses], False
    return masses, True   # sparse one-winner field: floors only, never inflated
