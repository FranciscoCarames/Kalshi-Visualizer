"""Numeric-strike ladder builder (detector expansion S2) — pure, UI-free, hermetic.

Discovers monotonic "Over / Under N" containment ladders from a market's MACHINE-READABLE numeric
strike (`strike_type` + `floor_strike` / `cap_strike`) — never from subtitle text. A `greater`
ladder nests upward: ``{X > b} ⊆ {X > a}`` for ``b > a``, so the YES price must fall as the strike
rises. A `less` ladder nests the other way: ``{X < a} ⊆ {X < b}`` for ``a < b``.

SCOPE (S2 v1 — DIAGNOSTIC ONLY): this module only BUILDS proven numeric ladders. It does NOT classify
crosses, emit opportunities, rank, or touch actionability — that wiring lands behind the F0 launch-state
gate so a numeric rung can never reach the Actionable bucket without an explicit, separately-approved
promotion. We reject anything whose containment we cannot prove from the STRUCTURED fields alone:

  * `strike_type` not in the monotone set (``custom`` / ``structured`` / ``between`` / ``functional`` /
    missing) — e.g. exact-score (`custom`) and "who-leads" leader markets (`structured`),
  * a mixed-direction group (a `greater` and a `less` market in one comparison),
  * a group with fewer than 2 distinct rungs,
  * a missing / non-numeric strike value.

IDENTITY is the caller's responsibility via ``group_key_fn`` — the SAME underlying scalar must be grouped
(same stat / period / unit / participant). The default keys on ``(series_ticker, event_ticker)``, which is
correct for a whole-event total (e.g. ``KXATPGTOTAL`` "Over N games", live-verified 2026-06-17). A
per-participant family (e.g. spreads, player props) MUST pass a key that also includes the participant,
or it would wrongly merge two different scalars.

No pandas / UI imports — independently testable.
"""
from __future__ import annotations

from typing import Any, Callable, NamedTuple

# strike_type values whose containment is monotone and provable from structured fields.
_MONOTONE_GE = ("greater", "greater_or_equal")   # YES iff value (>|>=) floor_strike
_MONOTONE_LE = ("less", "less_or_equal")          # YES iff value (<|<=) cap_strike


def _to_float(x: Any) -> float | None:
    """Best-effort numeric cast; None for missing / non-numeric (never raises)."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_numeric_strike(row: dict[str, Any]) -> tuple[str, float] | None:
    """Return ``(direction, strike)`` for a market with a PROVABLE monotone numeric strike, else None.

    ``direction`` is ``"ge"`` (greater / greater_or_equal — threshold from ``floor_strike``) or ``"le"``
    (less / less_or_equal — threshold from ``cap_strike``). Direction comes ONLY from ``strike_type``;
    the subtitle is never parsed. ``custom`` / ``structured`` / ``between`` / ``functional`` / missing
    types, and a missing/non-numeric strike value, all return None (excluded from monotonic ladders).
    """
    st = str(row.get("strike_type") or "").strip().lower()
    if st in _MONOTONE_GE:
        v = _to_float(row.get("floor_strike"))
        return ("ge", v) if v is not None else None
    if st in _MONOTONE_LE:
        v = _to_float(row.get("cap_strike"))
        return ("le", v) if v is not None else None
    return None


class NumericLadder(NamedTuple):
    """A proven monotonic numeric ladder, ordered broad → deep (parent → child).

    ``rungs`` is a list of ``(strike, row)`` from the broadest (highest YES probability) to the deepest.
    For a ``ge`` ladder broad→deep is strike ASCENDING (``Over 19.5`` ⊇ ``Over 29.5``); for a ``le``
    ladder it is strike DESCENDING (``Under 30`` ⊇ ``Under 20``). Adjacent pairs ``(rungs[i], rungs[i+1])``
    are broader/deeper, exactly the shape `consistency._classify` already consumes (child ≤ parent).
    """
    group_key: Any
    direction: str
    rungs: list[tuple[float, dict[str, Any]]]


def _default_group_key(row: dict[str, Any]) -> Any:
    return (row.get("series_ticker") or row.get("series"), row.get("event_ticker"))


def build_numeric_ladders(
    rows: list[dict[str, Any]],
    *,
    group_key_fn: Callable[[dict[str, Any]], Any] | None = None,
) -> list[NumericLadder]:
    """Build every proven monotonic numeric ladder from ``rows``.

    Groups eligible markets by ``(group_key, direction)`` — so a `greater` set and a `less` set on the
    same event become two SEPARATE ladders (never one mixed-direction comparison), satisfying the
    reject-mixed rule by construction. Within a group, rungs are ordered broad→deep and a group is
    emitted only when it has ≥ 2 DISTINCT strikes (a duplicate strike keeps the first row seen, so a
    re-listed market never fabricates a rung). Ineligible markets (`parse_numeric_strike` → None) are
    dropped silently — discovery, not a finding.
    """
    keyer = group_key_fn or _default_group_key
    groups: dict[tuple[Any, str], dict[float, dict[str, Any]]] = {}
    for row in rows or []:
        parsed = parse_numeric_strike(row)
        if parsed is None:
            continue
        direction, strike = parsed
        bucket = groups.setdefault((keyer(row), direction), {})
        bucket.setdefault(strike, row)            # first row wins on a duplicate strike

    out: list[NumericLadder] = []
    for (gkey, direction), by_strike in groups.items():
        if len(by_strike) < 2:
            continue
        # broad -> deep: ge ascends (lower bar = broader), le descends (higher cap = broader)
        ordered = sorted(by_strike.items(), key=lambda kv: kv[0], reverse=(direction == "le"))
        out.append(NumericLadder(group_key=gkey, direction=direction, rungs=ordered))
    return out
