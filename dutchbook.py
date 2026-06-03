"""Dutch-book / MECE detector for Kalshi 2-outcome markets.

A separate, generic check family from the containment ladder (`consistency.py`). A **dutch book**
exists on a mutually-exclusive-and-exhaustive set of binary markets when you can cover EVERY outcome
for less than the guaranteed $1 (100¢) payout — a locked, executable edge that needs no probability
model and (unlike match-alignment) carries no settlement-rule caveat: the legs are outcomes of the
SAME event and settle together.

This module handles the **2-outcome case**: any event with exactly two distinct-participant binary
markets — a head-to-head **match/series** (tennis match, NBA/WNBA playoff series) OR a single **game**
(NBA/WNBA `KX*GAME`). The two markets are mutually exclusive (one side wins) and, for the draw-free
sports we support, exhaustive — so the pair is MECE by construction. (A draw-prone game would list a
third outcome, so its event carries 3 markets and is rejected by the exactly-2 guard.) Two directions,
each a pair of BUYS (never "sell"/"short"):

  - **Underround → Buy YES on both.** Cost = ``yes_ask_A + yes_ask_B``. If < 100¢, one side wins and
    pays 100¢, so the locked profit per unit is ``100 − cost``.
  - **Overround → Buy NO on both.** Cost = ``no_ask_A + no_ask_B``. Exactly one NO pays 100¢ (the
    loser's), so the locked profit per unit is ``100 − cost``. (Equivalent to
    ``yes_bid_A + yes_bid_B > 100``, since ``no_ask = 100 − yes_bid`` on Kalshi's unified book.)

Because ``bid ≤ ask`` always, the two directions are mutually exclusive — at most ONE fires per event.

Sizes: a Buy-YES leg's tradable size is ``yes_ask_size``; a Buy-NO leg's is ``yes_bid_size`` (Kalshi
has no NO-side sizes — buying NO matches resting YES bids). Tradable units = the smaller of the two
legs' sizes. All comparisons are EXACT integer cents (parsed upstream by ``data.to_cents``).

Out of scope (see the m1 milestone plan): n-outcome winner FIELDS (≥3 outcomes) — they need a
field-completeness proof before the YES-underround is valid, plus a multi-leg representation. No
Streamlit / pandas imports here, so this module is independently testable.
"""
from __future__ import annotations

from typing import Any

import data
import sports
from glossary import BLOCKERS

# The one status this module emits. Distinct from consistency's EXECUTABLE_VIOLATION so the ladder's
# "violation" semantics stay separate; the dashboard router (bucket_of) sends both to the same
# high-priority Actionable/Blocked sections. A single status covers actionable AND blocked — the
# `tradable_now` flag distinguishes them (mirrors how EXECUTABLE_VIOLATION is routed).
EXECUTABLE_DUTCH_BOOK = "EXECUTABLE_DUTCH_BOOK"

# A discriminator so a consumer can tell a dutch-book finding from a containment-check row.
CHECK_TYPE = "dutch_book"

_NO_FIRM_QUALITY = ("No quote", "Crossed")  # a leg with this quote has no usable resting order


def _isna(x: Any) -> bool:
    """True for None or float NaN (a None price round-trips to NaN through pandas)."""
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    """Normalize a possibly-NaN numeric to None so `is None` checks work."""
    return None if _isna(x) else x


def _pos(size: Any) -> bool:
    return size is not None and size > 0


def _firm_yes_ask_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY YES on this leg (its firm ask), or None when there's no usable order."""
    if row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    return _num(row.get("yes_ask_c"))


def _firm_no_ask_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY NO on this leg — the real ``no_ask_c``, else the structural identity
    ``100 − yes_bid_c`` (equal by construction on Kalshi's unified book). None when no usable order."""
    if row.get("quote_quality") in _NO_FIRM_QUALITY:
        return None
    api = _num(row.get("no_ask_c"))
    if api is not None:
        return api
    yb = _num(row.get("yes_bid_c"))
    return (100 - yb) if yb is not None else None


def _is_active(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "") == "active"


# Two-way (exactly-2-outcome) contract families the detector accepts. A sport's head-to-head family
# (tennis "match"; NBA/WNBA "match" = playoff series) PLUS per-game ("game" — NBA/WNBA single games).
# Both are 2-outcome and exhaustive for the draw-free sports we support; the exactly-2-distinct-
# participant guard in `_detect_pair` is the real MECE safety net (a draw-prone 3-outcome game would
# carry 3 markets and be rejected there). Tennis has no "game" family, so it's unaffected.
_GAME_FAMILY = "game"


def _is_two_way_row(row: dict[str, Any]) -> bool:
    """A row from a two-way (2-outcome) event for whatever sport owns its series.

    Eligible families: the sport's head-to-head family (`cfg.match_family`) and per-game (`"game"`).
    The sport must be RECOGNIZED — a row whose series resolves to the UNKNOWN sport is always excluded
    (a foreign/unsupported ticker never enters the detector), so the game clause can't smuggle one in."""
    cfg = sports.sport_for_series(row.get("series"))
    if cfg.sport_id == "unknown":
        return False
    kind = row.get("kind")
    return kind == cfg.match_family or kind == _GAME_FAMILY


def _leg_label(row: dict[str, Any]) -> str:
    """Human label for a leg: the participant name, else its contract label."""
    return str(row.get("player") or row.get("contract") or "this leg")


def _buy_text(side: str, contract: str, price_c: int | None) -> str:
    """e.g. 'Buy YES — Sabalenka @ 48¢'."""
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract} @ {price}"


def _direction_candidate(side: str, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    """Build the candidate for one direction ('buy_yes' = underround, 'buy_no' = overround).

    Returns None when either leg lacks a firm price for that side (so the direction can't be priced).
    `gap_c` (= 100 − cost) is the per-unit locked profit; positive means a dutch book exists.
    """
    if side == "buy_yes":
        pa, pb = _firm_yes_ask_c(a), _firm_yes_ask_c(b)
        sa, sb = a.get("yes_ask_size"), b.get("yes_ask_size")   # buying YES hits resting asks
    else:
        pa, pb = _firm_no_ask_c(a), _firm_no_ask_c(b)
        sa, sb = a.get("yes_bid_size"), b.get("yes_bid_size")   # buying NO hits resting YES bids
    if pa is None or pb is None:
        return None
    cost = pa + pb
    min_size = min(sa, sb) if (_pos(sa) and _pos(sb)) else None
    return {
        "side": side,
        "cost_c": cost,
        "gap_c": 100 - cost,
        "price_a": pa,
        "price_b": pb,
        "min_size": min_size,
    }


def _detect_pair(event_ticker: str, markets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect a dutch book on a single 2-outcome match event, or None.

    Requires EXACTLY two distinct-participant markets (the only shape we can prove MECE for the
    2-outcome case). >2 or single-sided events are out of scope and skipped.
    """
    if len(markets) != 2:
        return None
    a, b = markets
    # Two distinct participants of the same match (defensive against duplicate rows).
    if a.get("player_key") and a.get("player_key") == b.get("player_key"):
        return None

    # Soonest the edge starts settling (capital frees / opportunity expires): the earlier leg time.
    # ISO-8601 strings sort chronologically; None-safe.
    times = [t for t in (a.get("time_value"), b.get("time_value")) if t]
    resolve_time = min(times) if times else None

    # Both directions; at most one can have gap_c > 0 (bid ≤ ask), but pick the max defensively.
    candidates = [c for c in (_direction_candidate("buy_yes", a, b),
                              _direction_candidate("buy_no", a, b)) if c is not None]
    fired = [c for c in candidates if c["gap_c"] > 0]
    if not fired:
        return None
    best = max(fired, key=lambda c: c["gap_c"])

    side = best["side"]
    direction = "underround" if side == "buy_yes" else "overround"
    label_a, label_b = _leg_label(a), _leg_label(b)
    gap_c, min_size = best["gap_c"], best["min_size"]

    # Tradable now: a real, executable edge needs positive size on both legs and both markets open.
    # Dutch books carry NO rule caveat (same event, settle together), so it's a plain Yes/No.
    both_active = _is_active(a) and _is_active(b)
    tradable_now = "Yes" if (min_size is not None and both_active) else "No"

    blockers: list[str] = []
    if min_size is None:
        blockers.append(BLOCKERS["size_missing"])
    for row in (a, b):
        q = row.get("quote_quality")
        if q in ("No quote", "One-sided"):
            blockers.append(BLOCKERS["no_quote"].format(leg=_leg_label(row)))
        elif q == "Crossed":
            blockers.append(BLOCKERS["crossed"].format(leg=_leg_label(row)))
        s = str(row.get("status") or "")
        if s and s != "active":
            blockers.append(BLOCKERS["inactive"].format(leg=_leg_label(row), status=s))

    reason = (
        f"{direction}: {side.replace('_', ' ')} both legs costs {best['cost_c']}¢ < 100¢ "
        f"→ {gap_c}¢ locked per unit ({label_a} {best['price_a']}¢ + {label_b} {best['price_b']}¢)"
    )

    # Stage-1 schema: stable opportunity_id + relationship_type + dashboard bucket + REQUIRED
    # blocked_reason. Id recipe = the check type + the event + the SORTED participant keys, so it is
    # leg-order-independent and unique per event (one finding per event). A dutch book is actionable
    # when tradable (carries no rule caveat), else blocked; blocked_reason is non-empty IFF blocked.
    keys = sorted([str(a.get("player_key") or ""), str(b.get("player_key") or "")])
    oid = data.opportunity_id(CHECK_TYPE, event_ticker, keys[0], keys[1])
    bucket = "actionable" if tradable_now.startswith("Yes") else "blocked"
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""

    return {
        "check_type": CHECK_TYPE,
        "relationship_type": CHECK_TYPE,
        "opportunity_id": oid,
        "bucket": bucket,
        "blocked_reason": blocked_reason,
        "status": EXECUTABLE_DUTCH_BOOK,
        "direction": direction,
        "event_ticker": event_ticker,
        "series": a.get("series", ""),
        "tournament": a.get("tournament", ""),
        "tour": a.get("tour", ""),
        "match": f"{label_a} vs {label_b}",
        "player_a": label_a,
        "player_b": label_b,
        "player_key_a": a.get("player_key", ""),
        "player_key_b": b.get("player_key", ""),
        "resolve_time": resolve_time,
        "tradable_now": tradable_now,
        "blockers": blockers_str,
        # Two-leg buy-only action plan (same vocabulary as consistency rows, so the dashboard reuses it).
        "action_1_side": side, "action_1_contract": label_a, "action_1_price_c": best["price_a"],
        "action_1_text": _buy_text(side, label_a, best["price_a"]),
        "action_2_side": side, "action_2_contract": label_b, "action_2_price_c": best["price_b"],
        "action_2_text": _buy_text(side, label_b, best["price_b"]),
        # Profit / sizing (mirrors consistency's exec_* keys; gross of fees/slippage).
        "cost_c": best["cost_c"],
        "exec_gap_c": gap_c,
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "reason": reason,
        # Identifiers for links / debug.
        "event_title": a.get("event_title", ""),
        "ticker_a": a.get("market_ticker", ""),
        "ticker_b": b.get("market_ticker", ""),
        "url": a.get("kalshi_url", ""),
    }


def find_dutch_books(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scan per-player contract rows and return one dutch-book finding per qualifying 2-outcome match
    event (possibly empty). Groups head-to-head market rows by ``event_ticker``; only events with
    exactly two distinct-participant markets are evaluated.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not _is_two_way_row(row):
            continue
        ev = row.get("event_ticker") or ""
        if not ev:
            continue
        groups.setdefault(ev, []).append(row)

    out: list[dict[str, Any]] = []
    for event_ticker, markets in groups.items():
        finding = _detect_pair(event_ticker, markets)
        if finding is not None:
            out.append(finding)
    # Strongest edge first (largest locked gap), deterministic tiebreak on event ticker.
    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"]))
    return out
