"""Pure Kalshi fee / round-trip cost estimates — NO UI, NO pandas, stdlib + ``config`` only.

A standalone port of the fee formula in ``webui/viewmodel.py`` (which can't be imported here because that
module pulls in NiceGUI). Kalshi's published GENERAL schedule is ``fee = ceil(coeff · C · P · (1−P))`` per
fill, in integer cents, where ``C`` = contracts, ``P`` = price in dollars (0 at the 0¢/100¢ endpoints), and
``coeff = base × the series/event fee_multiplier`` (taker base 0.07, maker base 0.0175 — ``config``).

Used by the dark conditional-blend validator to estimate a candidate's cost. **Every estimate is a
conservative pre-trade figure, not a realized fee** (special/flat schedules, exact centicent rounding, and
the per-order rebate accumulator differ). When the per-series fee metadata is unknown, ``effective_coeffs``
reports ``known=False`` so a caller can BLOCK a cost-vs-gap comparison rather than silently assume a base
coefficient.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import config


def _num_or_none(x: Any) -> float | None:
    """Parse to float, or None for missing/NaN/non-numeric (so ``is None`` checks work)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v          # reject NaN


def fee_c(contracts: float, price_c: float, coeff: float = config.FEE_TAKER_BASE_COEFF) -> int:
    """Estimated fee for ``contracts`` at ``price_c`` cents, in integer cents, rounded UP:
    ``ceil(coeff · C · P · (1−P))``. ``coeff`` is the EFFECTIVE coefficient (base × fee_multiplier).
    Decimal math avoids ``0.07×mult`` float dust. Zero at the 0¢/100¢ endpoints; 0 for non-positive or
    invalid ``C``/``coeff``. Byte-for-byte equivalent to ``webui.viewmodel.kalshi_fee_c``."""
    c, p, k = _num_or_none(contracts), _num_or_none(price_c), _num_or_none(coeff)
    if c is None or p is None or k is None or c <= 0 or p <= 0 or p >= 100 or k <= 0:
        return 0
    pf = Decimal(str(p)) / Decimal(100)
    cents = Decimal(str(k)) * Decimal(str(c)) * pf * (Decimal(1) - pf) * Decimal(100)
    return int(cents.to_integral_value(rounding="ROUND_CEILING"))


def effective_coeffs(fee_type: Any, fee_multiplier: Any) -> dict[str, Any]:
    """Resolve effective taker/maker coefficients from a series' ``fee_type`` + ``fee_multiplier``.

    Returns ``{taker, maker, known, status}`` (taker/maker floats or None). ``known`` is True ONLY when a
    real multiplier is present for a recognised quadratic schedule — a missing multiplier
    (``assumed_multiplier``), a flat/special schedule, or an unknown type all yield ``known=False`` so the
    caller blocks a cost gate rather than trusting a base-coefficient floor. Mirrors
    ``webui.viewmodel.effective_coeffs`` but tightens ``assumed_multiplier`` to ``known=False``."""
    ft = str(fee_type or "").strip().lower()
    mult = _num_or_none(fee_multiplier)
    if ft in ("", "none"):
        return {"taker": None, "maker": None, "known": False, "status": "unknown_fee_type"}
    if ft == "flat":
        return {"taker": None, "maker": None, "known": False, "status": "unsupported_flat"}
    if ft not in ("quadratic", "quadratic_with_maker_fees"):
        return {"taker": None, "maker": None, "known": False, "status": "unknown_fee_type"}
    status = "complete"
    if mult is None or mult <= 0:
        mult, status = config.FEE_DEFAULT_MULTIPLIER, "assumed_multiplier"
    taker = config.FEE_TAKER_BASE_COEFF * mult
    maker = config.FEE_MAKER_BASE_COEFF * mult if ft == "quadratic_with_maker_fees" else 0.0
    return {"taker": taker, "maker": maker, "known": status == "complete", "status": status}


def roundtrip_cost_c(contracts: float, entry_price_c: float, exit_price_c: float,
                     coeff: float = config.FEE_TAKER_BASE_COEFF) -> int:
    """Round-trip cost = entry fee + exit fee, EACH ceiled independently (Kalshi rounds per fill, not on
    the summed total). ``coeff`` is the effective taker coefficient for both legs."""
    return fee_c(contracts, entry_price_c, coeff) + fee_c(contracts, exit_price_c, coeff)


def cost_paths(price_c: float, fee_meta: dict[str, Any] | None, *, contracts: float = 1.0) -> dict[str, Any]:
    """Per-unit cost estimates (cents) for the three theses a convergence candidate could be traded under,
    plus ``fee_known``. ``fee_meta`` is the series' ``{"fee_type", "fee_multiplier"}`` (from
    ``fetch.fetch_contracts``'s ``fee_rates``); when its multiplier is unknown, ``fee_known=False`` and the
    figures are computed at the assumed-multiplier floor and must NOT be used to pass a cost gate.

    - ``cost_hold_c`` — taker entry, hold to settlement (entry fee only).
    - ``cost_roundtrip_taker_c`` — taker entry + taker exit (exit priced at the same level, a proxy).
    - ``cost_maker_entry_taker_exit_c`` — maker entry (resting) + taker exit.
    """
    eff = effective_coeffs((fee_meta or {}).get("fee_type"), (fee_meta or {}).get("fee_multiplier"))
    taker = eff["taker"] if eff["taker"] is not None else config.FEE_TAKER_BASE_COEFF
    maker = eff["maker"] if eff["maker"] is not None else config.FEE_MAKER_BASE_COEFF
    return {
        "cost_hold_c": fee_c(contracts, price_c, taker),
        "cost_roundtrip_taker_c": roundtrip_cost_c(contracts, price_c, price_c, taker),
        "cost_maker_entry_taker_exit_c": fee_c(contracts, price_c, maker) + fee_c(contracts, price_c, taker),
        "fee_known": bool(eff["known"]),
        "fee_status": eff["status"],
        "coeff_taker": taker,
    }
