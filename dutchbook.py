"""Dutch-book / MECE detector for Kalshi 2-outcome markets.

A separate, generic check family from the containment ladder (`consistency.py`). A **dutch book**
exists on a mutually-exclusive-and-exhaustive set of binary markets when you can cover EVERY outcome
for less than the guaranteed $1 (100¢) payout — a gross, executable pricing discrepancy that needs no
probability model. It holds under NORMAL one-winner settlement (NOT riskless, NOT "true arbitrage"): the
legs are outcomes of the SAME event and normally settle together, but an abnormal resolution (a postponed
/ abandoned / no-contest game) can break that, so per-game (`KX*GAME`) findings carry a postponement
settlement caveat (`settlement_caveat`); match/series settle together.

This module handles the **2-outcome case**: any event with exactly two distinct-participant binary
markets — a head-to-head **match/series** (tennis match, NBA/WNBA playoff series) OR a single **game**
(NBA/WNBA `KX*GAME`). The two markets are mutually exclusive (one side wins) and, for the draw-free
sports we support, exhaustive — so the pair is MECE by construction. (A draw-prone game would list a
third outcome, so its event carries 3 markets and is rejected by the exactly-2 guard.) Two directions,
each a pair of BUYS (never "sell"/"short"):

  - **Underround → Buy YES on both.** Cost = ``yes_ask_A + yes_ask_B``. If < 100¢, one side wins and
    pays 100¢, so the gross gap per unit is ``100 − cost``.
  - **Overround → Buy NO on both.** Cost = ``no_ask_A + no_ask_B``. Exactly one NO pays 100¢ (the
    loser's), so the gross gap per unit is ``100 − cost``. (Equivalent to
    ``yes_bid_A + yes_bid_B > 100``, since ``no_ask = 100 − yes_bid`` on Kalshi's unified book.)

Because ``bid ≤ ask`` always, the two directions are mutually exclusive — at most ONE fires per event.

Sizes: a Buy-YES leg's tradable size is ``yes_ask_size``; a Buy-NO leg's is ``yes_bid_size`` (Kalshi
has no NO-side sizes — buying NO matches resting YES bids). Tradable units = the smaller of the two
legs' sizes. All comparisons are EXACT integer cents (parsed upstream by ``data.to_cents``).

Beyond the 2-outcome case this module also handles two n-outcome shapes:
  - **Soccer 3-way games** (Home/Away/Tie) via ``_detect_n_way`` (both directions; needs the full MECE set).
  - **Tournament-winner FIELDS** (≥3-player "win the tournament" markets) via ``_detect_field`` —
    **OVERROUND ONLY.** A field is mutually exclusive (one champion) but NOT provably exhaustive (a Grand
    Slam lists fewer markets than its draw), so underround (Buy YES all) is unsafe and never emitted. The
    overround is safe on **any priceable subset** of a mutually-exclusive set: buying NO on k legs pays
    ≥(k−1)·100¢ (an unlisted/illiquid winner only pays MORE), so we trade the priceable legs and skip the
    empty-book longshots. ``gap = Σ yes_bid(subset) − 100``.

The N-leg **exact-score synthetic bundle** (a player's MECE set scores priced vs their match-winner) is
BUILT in the sibling ``synthetic_bundle.py`` (milestone m5). No Streamlit / pandas imports here, so this
module is independently testable.
"""
from __future__ import annotations

from typing import Any, NamedTuple

import data
import sports
from glossary import BLOCKERS

# The one status this module emits. Distinct from consistency's EXECUTABLE_VIOLATION so the ladder's
# "violation" semantics stay separate; the dashboard router (bucket_of) sends both to the same
# high-priority Actionable/Blocked sections. A single status covers actionable AND blocked — the
# `tradable_now` flag distinguishes them (mirrors how EXECUTABLE_VIOLATION is routed).
EXECUTABLE_DUTCH_BOOK = "EXECUTABLE_DUTCH_BOOK"

# A near-miss dutch book: a MECE book that costs SLIGHTLY OVER its payout floor — a FLAT-payout guaranteed
# gross loss as a bundle, surfaced as an opt-in watchlist (never actionable). Distinct status + `near_miss`
# bucket so it can never leak into the strict actionable/blocked sets.
NEAR_MISS_DUTCH_BOOK = "NEAR_MISS_DUTCH_BOOK"

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


# The tournament-winner family ("win the tournament", one market per participant). An event's winner
# markets form a mutually-exclusive FIELD (one champion) → an OVERROUND-only dutch book (see _detect_field).
_WINNER_FAMILY = "winner"


def _is_field_row(row: dict[str, Any]) -> bool:
    """A row from a tournament-winner field event of a RECOGNIZED sport (an UNKNOWN sport is excluded)."""
    cfg = sports.sport_for_series(row.get("series"))
    if cfg.sport_id == "unknown":
        return False
    return row.get("kind") == _WINNER_FAMILY


def _leg_label(row: dict[str, Any]) -> str:
    """Human label for a leg: the participant name, else its contract label."""
    return str(row.get("player") or row.get("contract") or "this leg")


def _buy_text(side: str, contract: str, price_c: int | None) -> str:
    """e.g. 'Buy YES — Sabalenka @ 48¢'."""
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract} @ {price}"


def _settlement_caveat(rows: list[dict[str, Any]]) -> str:
    """The NON-blocking settlement caveat for a finding's legs, or '' when none applies.

    A per-game (`_GAME_FAMILY`) book — NBA/WNBA single games and soccer 3-way games — can be broken by an
    abnormal resolution (postponed / abandoned / no-contest / not-as-scheduled), so it carries the
    `game_settlement` caveat. Match/series books settle together under normal one-winner settlement → ''.
    This is ADVISORY: it never enters `blockers`/`blocked_reason`, so it can't change tradability/bucket.
    """
    return BLOCKERS["game_settlement"] if any(r.get("kind") == _GAME_FAMILY for r in rows) else ""


def _select_edge(candidates: list[dict[str, Any] | None],
                 near_miss_max_over_c: int) -> tuple[dict[str, Any] | None, str | None]:
    """Pick ONE finding per event from the priced direction candidates: **strict XOR near-miss**.

    `gap_c` (= payout floor − cost) is the per-unit gross gap for any direction (2-way or n-way). The single
    best (max-gap) candidate decides: a positive gap is a strict dutch book (today's behaviour); otherwise,
    when the opt-in band is on and the overpay (= −gap) is in `[1, near_miss_max_over_c]`, it's a near-miss
    watchlist row. Strict ALWAYS wins (the max-gap candidate is positive iff any direction fires), so an
    event never yields both. `near_miss_max_over_c = 0` (default) → strict-only, byte-for-byte unchanged."""
    priced = [c for c in candidates if c is not None]
    if not priced:
        return None, None
    best = max(priced, key=lambda c: c["gap_c"])
    if best["gap_c"] > 0:
        return best, "strict"
    if near_miss_max_over_c > 0 and -near_miss_max_over_c <= best["gap_c"] <= -1:
        return best, "near_miss"
    return None, None


def _classify_edge(edge_class: str, tradable_now: str, base_caveat: str) -> tuple[str, str, str]:
    """(status, bucket, settlement_caveat) for a finding by edge class. A near-miss gets the distinct
    NEAR_MISS_DUTCH_BOOK status + `near_miss` bucket (never actionable/blocked) and prepends the flat-loss
    watchlist note to its caveat; a strict book routes actionable/blocked by tradability, as before."""
    if edge_class == "near_miss":
        caveat = "; ".join(p for p in (BLOCKERS["near_miss_flat"], base_caveat) if p)
        return NEAR_MISS_DUTCH_BOOK, "near_miss", caveat
    return EXECUTABLE_DUTCH_BOOK, ("actionable" if tradable_now.startswith("Yes") else "blocked"), base_caveat


def _direction_candidate(side: str, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    """Build the candidate for one direction ('buy_yes' = underround, 'buy_no' = overround).

    Returns None when either leg lacks a firm price for that side (so the direction can't be priced).
    `gap_c` (= 100 − cost) is the per-unit gross gap; positive means a dutch book exists.
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


def _detect_pair(event_ticker: str, markets: list[dict[str, Any]],
                 near_miss_max_over_c: int = 0) -> dict[str, Any] | None:
    """Detect a dutch book on a single 2-outcome match event, or None.

    Requires EXACTLY two distinct-participant markets (the only shape we can prove MECE for the
    2-outcome case). >2 or single-sided events are out of scope and skipped. `near_miss_max_over_c` > 0
    additionally surfaces a near-miss watchlist row when no strict book fires (see `_select_edge`).
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

    # Both directions; strict wins, else an opt-in near-miss. At most one fires per event (_select_edge).
    candidates = [_direction_candidate("buy_yes", a, b), _direction_candidate("buy_no", a, b)]
    best, edge_class = _select_edge(candidates, near_miss_max_over_c)
    if best is None:
        return None

    side = best["side"]
    direction = "underround" if side == "buy_yes" else "overround"
    label_a, label_b = _leg_label(a), _leg_label(b)
    gap_c, min_size = best["gap_c"], best["min_size"]

    # Tradable now: a real, executable edge needs positive size on both legs and both markets open.
    # The settlement caveat (a postponement note on per-game books; see `_settlement_caveat`) is a
    # NON-blocking advisory — it never changes tradability, so this stays a plain Yes/No.
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

    if edge_class == "near_miss":
        reason = (
            f"near-miss {direction}: {side.replace('_', ' ')} both legs costs {best['cost_c']}¢ ≥ 100¢ "
            f"→ {-gap_c}¢ gross LOSS per unit if taken as a bundle (flat payout); watchlist only "
            f"({label_a} {best['price_a']}¢ + {label_b} {best['price_b']}¢)"
        )
    else:
        reason = (
            f"{direction}: {side.replace('_', ' ')} both legs costs {best['cost_c']}¢ < 100¢ "
            f"→ {gap_c}¢ gross per unit, under normal one-winner settlement "
            f"({label_a} {best['price_a']}¢ + {label_b} {best['price_b']}¢)"
        )

    # Stage-1 schema: stable opportunity_id + relationship_type + dashboard bucket + REQUIRED
    # blocked_reason. Id recipe = the check type + the event + the SORTED participant keys, so it is
    # leg-order-independent and unique per event (one finding per event). A strict dutch book is actionable
    # when tradable, else blocked; a near-miss gets its own watchlist bucket. blocked_reason non-empty IFF
    # blocked (so a near-miss carries its watchlist note in settlement_caveat, not blocked_reason).
    keys = sorted([str(a.get("player_key") or ""), str(b.get("player_key") or "")])
    oid = data.opportunity_id(CHECK_TYPE, event_ticker, keys[0], keys[1])
    status, bucket, settlement_caveat = _classify_edge(edge_class, tradable_now, _settlement_caveat([a, b]))
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""

    return {
        "check_type": CHECK_TYPE,
        "relationship_type": CHECK_TYPE,
        "opportunity_id": oid,
        "bucket": bucket,
        "blocked_reason": blocked_reason,
        "status": status,
        "edge_class": edge_class,
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
        # Normalized leg-status for the lifecycle diff (§9 market_status / §10 "leg inactive"): a single
        # market_status from the same both-legs-active check that drives tradability.
        "market_status": "active" if both_active else "inactive",
        "blockers": blockers_str,
        # Non-blocking settlement caveat (per-game books only, + the flat-loss note for a near-miss);
        # advisory, never affects tradability/bucket.
        "settlement_caveat": settlement_caveat,
        # Two-leg buy-only action plan (same vocabulary as consistency rows, so the dashboard reuses it).
        "action_1_side": side, "action_1_contract": label_a, "action_1_price_c": best["price_a"],
        "action_1_text": _buy_text(side, label_a, best["price_a"]),
        "action_2_side": side, "action_2_contract": label_b, "action_2_price_c": best["price_b"],
        "action_2_text": _buy_text(side, label_b, best["price_b"]),
        # Profit / sizing (mirrors consistency's exec_* keys; gross of fees/slippage). A MECE book pays its
        # floor in EVERY state, so the per-unit profit is flat (worst == best == gap_c, negative on a
        # near-miss = the guaranteed bundle loss).
        "cost_c": best["cost_c"],
        "payout_floor_c": 100,   # a 2-way book pays exactly 100¢ in every state (PR 13 schema parity)
        "exec_gap_c": gap_c,
        "worst_case_profit_c": gap_c, "best_case_profit_c": gap_c,
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "reason": reason,
        # Identifiers for links / debug.
        "event_title": a.get("event_title", ""),
        "ticker_a": a.get("market_ticker", ""),
        "ticker_b": b.get("market_ticker", ""),
        "url": a.get("kalshi_url", ""),
    }


# ---- N-outcome (n>=3) MECE dutch book ----------------------------------------------------------------
# Soccer World Cup group games are 3-WAY (Home / Away / Tie), so `_detect_pair` (which rejects any event
# without exactly 2 markets) can't see them. `find_dutch_books` dispatches the soccer `game` family to
# `_detect_n_way`; every other 2-way sport keeps `_detect_pair` byte-identical.
#   - Underround -> Buy YES all n. One outcome wins -> pays 100c. Fires if sum(yes_ask) < 100c (needs
#     EXHAUSTIVE). Gross gap = 100 - cost.
#   - Overround -> Buy NO all n. Exactly one outcome wins -> the other (n-1) NOs each pay 100c, so the
#     payout floor is (n-1)*100c (needs MUTUALLY EXCLUSIVE). Fires if sum(no_ask) < (n-1)*100c.
# (n=2 reduces to `_detect_pair`'s 100c floor.) Exact integer cents throughout.

_DRAW_EXCLUDED_PHRASE = "does not include extra time or penalties"


class MeceProof(NamedTuple):
    ok: bool
    mutually_exclusive: bool
    exhaustive: bool
    settlement_basis: str
    reason: str


def prove_mece(event_rows: list[dict[str, Any]], cfg: Any) -> MeceProof:
    """Prove a soccer game event is a true MECE 3-way (Home/Away/Tie) safe to dutch-book.

    Requires: exactly 2 real participants + 1 non-participant Tie (from `is_participant`); 3 distinct
    keys; the event flagged `mutually_exclusive`; the draw-excluded settlement phrase present (a true
    90-minute 3-way, not a 2-way "to advance" book); and a SHARED settlement basis (the same rule-token
    set on every leg). `ok` gates emission.
    """
    teams = [r for r in event_rows if r.get("is_participant")]
    ties = [r for r in event_rows if not r.get("is_participant")]
    if len(event_rows) != 3 or len(teams) != 2 or len(ties) != 1:
        return MeceProof(False, False, False, "", "expected exactly 2 participants + 1 tie")
    if len({str(r.get("player_key") or "") for r in event_rows}) != 3:
        return MeceProof(False, False, False, "", "duplicate participant keys")
    if not all(bool(r.get("mutually_exclusive")) for r in event_rows):
        return MeceProof(False, False, False, "", "event not flagged mutually_exclusive")
    if not any(_DRAW_EXCLUDED_PHRASE in str(r.get("rules_primary") or "").lower() for r in event_rows):
        return MeceProof(False, True, False, "", "missing draw-excluded settlement phrase")
    bases = {frozenset(data.rule_tokens(r.get("rules_primary"))) for r in event_rows}
    if len(bases) != 1:
        return MeceProof(False, True, True, "", "settlement basis differs across legs")
    basis = ", ".join(sorted(next(iter(bases)))) or "standard one-winner"
    return MeceProof(True, True, True, basis, "")


def _n_direction_candidate(side: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Price one direction across all n legs. Underround floor = 100c; overround floor = (n-1)*100c."""
    n = len(rows)
    if side == "buy_yes":
        prices = [_firm_yes_ask_c(r) for r in rows]
        sizes = [r.get("yes_ask_size") for r in rows]   # buying YES hits resting asks
        floor = 100
    else:
        prices = [_firm_no_ask_c(r) for r in rows]
        sizes = [r.get("yes_bid_size") for r in rows]   # buying NO hits resting YES bids
        floor = (n - 1) * 100
    if any(p is None for p in prices):
        return None
    cost = sum(prices)
    min_size = min(sizes) if all(_pos(s) for s in sizes) else None
    return {"side": side, "cost_c": cost, "gap_c": floor - cost, "prices": prices,
            "min_size": min_size, "payout_floor_c": floor}


def _record(diag: dict | None, kind: str, event_ticker: str, reason: str) -> None:
    """Fold a rejected / eligible-non-firing candidate into the optional `_diag` (Debug / live smoke)."""
    if diag is not None:
        diag.setdefault(kind, []).append({"event_ticker": event_ticker, "reason": reason})


def _detect_n_way(event_ticker: str, rows: list[dict[str, Any]], cfg: Any,
                  diag: dict | None = None, near_miss_max_over_c: int = 0) -> dict[str, Any] | None:
    """Detect an n-outcome dutch book on one MECE event (currently soccer 3-way games), or None."""
    proof = prove_mece(rows, cfg)
    if not proof.ok:
        _record(diag, "rejected", event_ticker, proof.reason)
        return None
    n = len(rows)
    candidates = [_n_direction_candidate("buy_yes", rows), _n_direction_candidate("buy_no", rows)]
    best, edge_class = _select_edge(candidates, near_miss_max_over_c)
    if best is None:
        _record(diag, "eligible_non_firing", event_ticker, "priced, no positive gap")
        return None
    side = best["side"]
    direction = "underround" if side == "buy_yes" else "overround"
    word = "buy YES" if side == "buy_yes" else "buy NO"
    gap_c, min_size, floor, cost = best["gap_c"], best["min_size"], best["payout_floor_c"], best["cost_c"]

    legs: list[dict[str, Any]] = []
    for r, p in zip(rows, best["prices"]):
        size = r.get("yes_ask_size") if side == "buy_yes" else r.get("yes_bid_size")
        label = _leg_label(r)
        legs.append({"side": side, "contract": label, "price_c": p, "size": _num(size),
                     "ticker": r.get("market_ticker", ""), "url": r.get("kalshi_url", ""),
                     "text": _buy_text(side, label, p)})

    all_active = all(_is_active(r) for r in rows)
    tradable_now = "Yes" if (min_size is not None and all_active) else "No"
    blockers: list[str] = []
    if min_size is None:
        blockers.append(BLOCKERS["size_missing"])
    for r in rows:
        q = r.get("quote_quality")
        if q in ("No quote", "One-sided"):
            blockers.append(BLOCKERS["no_quote"].format(leg=_leg_label(r)))
        elif q == "Crossed":
            blockers.append(BLOCKERS["crossed"].format(leg=_leg_label(r)))
        s = str(r.get("status") or "")
        if s and s != "active":
            blockers.append(BLOCKERS["inactive"].format(leg=_leg_label(r), status=s))

    # Id recipe = check type + event + SORTED participant keys (leg-order-independent, one finding/event).
    keys = sorted(str(r.get("player_key") or "") for r in rows)
    oid = data.opportunity_id(CHECK_TYPE, event_ticker, *keys)
    status, bucket, settlement_caveat = _classify_edge(edge_class, tradable_now, _settlement_caveat(rows))
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""
    # a/b are the real participants (teams) so the participant filter matches a chosen team regardless of
    # market order; the Tie / any extra legs live only in `legs` (and are never selectable participants).
    team_rows = [r for r in rows if r.get("is_participant")] or rows
    participants = [_leg_label(r) for r in team_rows]
    match = " vs ".join(participants) if participants else (rows[0].get("event_title") or event_ticker)
    pa = team_rows[0]
    pb = team_rows[1] if len(team_rows) > 1 else team_rows[0]
    times = [t for t in (r.get("time_value") for r in rows) if t]
    if edge_class == "near_miss":
        reason = (f"near-miss {direction}: {word} all {n} legs costs {cost}c >= {floor}c payout floor "
                  f"-> {-gap_c}c gross LOSS per unit if taken as a bundle (flat payout); watchlist only")
    else:
        reason = (f"{direction}: {word} all {n} legs costs {cost}c < {floor}c payout floor "
                  f"-> {gap_c}c gross per unit, under normal one-winner settlement")

    return {
        "check_type": CHECK_TYPE,
        "relationship_type": CHECK_TYPE,
        "opportunity_id": oid,
        "bucket": bucket,
        "blocked_reason": blocked_reason,
        "status": status,
        "edge_class": edge_class,
        "direction": direction,
        "event_ticker": event_ticker,
        "series": rows[0].get("series", ""),
        "tournament": rows[0].get("tournament", ""),
        "tour": rows[0].get("tour", ""),
        "match": match,
        "player_a": _leg_label(pa), "player_b": _leg_label(pb),
        "player_key_a": pa.get("player_key", ""), "player_key_b": pb.get("player_key", ""),
        "resolve_time": min(times) if times else None,
        "tradable_now": tradable_now,
        "market_status": "active" if all_active else "inactive",
        "blockers": blockers_str,
        # Non-blocking settlement caveat (soccer 3-way games are per-game → carry it; + flat-loss note on a
        # near-miss); advisory only.
        "settlement_caveat": settlement_caveat,
        # Full N-leg plan in `legs`; action_1/2 backfilled from the first two legs so the unified 2-leg
        # columns + lifecycle still render. payout_floor_c is the (n-1)*100 (overround) / 100 (underround).
        "legs": legs, "n_legs": n, "payout_floor_c": floor,
        # Flat payout across all MECE states → worst == best == gap_c (negative on a near-miss).
        "worst_case_profit_c": gap_c, "best_case_profit_c": gap_c,
        "action_1_side": legs[0]["side"], "action_1_contract": legs[0]["contract"],
        "action_1_price_c": legs[0]["price_c"], "action_1_text": legs[0]["text"],
        "action_2_side": legs[1]["side"], "action_2_contract": legs[1]["contract"],
        "action_2_price_c": legs[1]["price_c"], "action_2_text": legs[1]["text"],
        "cost_c": cost,
        "exec_gap_c": gap_c,
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "reason": reason,
        "event_title": rows[0].get("event_title", ""),
        "ticker_a": rows[0].get("market_ticker", ""),
        "ticker_b": rows[1].get("market_ticker", ""),
        "url": rows[0].get("kalshi_url", ""),
    }


def proof_audit(event_rows: list[dict[str, Any]], cfg: Any) -> dict[str, Any]:
    """For tests / live smoke: the MECE proof + both priced directions WITHOUT the gap>0 filter."""
    return {
        "proof": prove_mece(event_rows, cfg),
        "underround": _n_direction_candidate("buy_yes", event_rows),
        "overround": _n_direction_candidate("buy_no", event_rows),
    }


# ---- Tournament-winner FIELD (overround-only) -------------------------------------------------------
def prove_field_mece(event_rows: list[dict[str, Any]], cfg: Any) -> MeceProof:
    """Prove a tournament-winner FIELD is mutually exclusive — safe for an OVERROUND-only dutch book.

    Requires ≥3 distinct-participant winner markets all flagged ``mutually_exclusive``. Exhaustiveness is
    deliberately NOT proven (`exhaustive=False`): a Grand Slam lists fewer "win" markets than its draw, so
    underround (Buy YES all) could pay 0 and is never emitted. The overround is safe from mutual
    exclusivity alone — at most one market settles YES, so buying NO on any k≥2 legs pays ≥(k−1)·100¢, and
    a winner outside the traded subset only pays MORE.
    """
    if len(event_rows) < 3:
        return MeceProof(False, False, False, "", "winner field needs >=3 outcomes")
    if len({str(r.get("player_key") or "") for r in event_rows}) != len(event_rows):
        return MeceProof(False, False, False, "", "duplicate participant keys")
    if not all(bool(r.get("mutually_exclusive")) for r in event_rows):
        return MeceProof(False, False, False, "", "event not flagged mutually_exclusive")
    return MeceProof(True, True, False, "tournament winner (one champion)", "")


def _field_overround_subset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The legs to BUY NO on: every leg with a firm no-side price AND ``yes_bid_c > 0``.

    Overround is safe on ANY subset of a mutually-exclusive set, so we trade only the priceable legs — a
    field's longshots have empty 0/1 books that would otherwise make the whole field unpriceable. Adding a
    leg with ``yes_bid b`` raises the gross gap by exactly ``b`` (``gap = Σ yes_bid − 100``), so the
    priceable-and-bid>0 set is also the gap-maximising one.
    """
    return [r for r in rows if _firm_no_ask_c(r) is not None and (_num(r.get("yes_bid_c")) or 0) > 0]


def _detect_field(event_ticker: str, rows: list[dict[str, Any]], cfg: Any,
                  diag: dict | None = None) -> dict[str, Any] | None:
    """Detect an OVERROUND dutch book on a tournament-winner field (mutually-exclusive, n-outcome), or None.

    Overround only (underround needs an exhaustive field we can't prove). Trades the priceable subset; the
    payout floor is ``(k−1)·100`` for the ``k`` legs actually bought.
    """
    proof = prove_field_mece(rows, cfg)
    if not proof.ok:
        _record(diag, "rejected", event_ticker, f"field: {proof.reason}")
        return None
    subset = _field_overround_subset(rows)
    if len(subset) < 2:
        _record(diag, "eligible_non_firing", event_ticker, "field: fewer than 2 priceable legs")
        return None
    cand = _n_direction_candidate("buy_no", subset)   # overround only; floor=(k-1)*100, cost=Σ no_ask
    if cand is None or cand["gap_c"] <= 0:
        _record(diag, "eligible_non_firing", event_ticker, "field: priced, no positive overround gap")
        return None

    n_field, k = len(rows), len(subset)
    cost, gap_c, min_size, floor = cand["cost_c"], cand["gap_c"], cand["min_size"], cand["payout_floor_c"]

    legs: list[dict[str, Any]] = []
    for r, p in zip(subset, cand["prices"]):
        label = _leg_label(r)
        legs.append({"side": "buy_no", "contract": label, "price_c": p, "size": _num(r.get("yes_bid_size")),
                     "ticker": r.get("market_ticker", ""), "url": r.get("kalshi_url", ""),
                     "text": _buy_text("buy_no", label, p)})

    all_active = all(_is_active(r) for r in subset)
    tradable_now = "Yes" if (min_size is not None and all_active) else "No"
    blockers: list[str] = []
    if min_size is None:
        blockers.append(BLOCKERS["size_missing"])
    for r in subset:
        q = r.get("quote_quality")
        if q in ("No quote", "One-sided"):
            blockers.append(BLOCKERS["no_quote"].format(leg=_leg_label(r)))
        elif q == "Crossed":
            blockers.append(BLOCKERS["crossed"].format(leg=_leg_label(r)))
        s = str(r.get("status") or "")
        if s and s != "active":
            blockers.append(BLOCKERS["inactive"].format(leg=_leg_label(r), status=s))

    # Stable id: one field overround per EVENT (NOT the variable priceable subset, which shifts between
    # scans as books fill) so lifecycle tracking is continuous.
    oid = data.opportunity_id(CHECK_TYPE, event_ticker, "field", "overround")
    bucket = "actionable" if tradable_now.startswith("Yes") else "blocked"
    blockers_str = "; ".join(blockers)
    blocked_reason = (blockers_str or "not executable now") if bucket == "blocked" else ""
    pa, pb = subset[0], subset[1]
    tournament = rows[0].get("tournament", "")
    match = (f"{tournament} winner field".strip()) or (rows[0].get("event_title") or event_ticker)
    times = [t for t in (r.get("time_value") for r in subset) if t]
    reason = (f"overround: buy NO on {k} of {n_field} mutually-exclusive winner-field legs costs {cost}c "
              f"< {floor}c payout floor -> {gap_c}c gross per unit, under normal one-winner settlement")

    return {
        "check_type": CHECK_TYPE,
        "relationship_type": CHECK_TYPE,
        "opportunity_id": oid,
        "bucket": bucket,
        "blocked_reason": blocked_reason,
        "status": EXECUTABLE_DUTCH_BOOK,
        "direction": "overround",
        "event_ticker": event_ticker,
        "series": rows[0].get("series", ""),
        "tournament": tournament,
        "tour": rows[0].get("tour", ""),
        "match": match,
        "player_a": _leg_label(pa), "player_b": _leg_label(pb),
        "player_key_a": pa.get("player_key", ""), "player_key_b": pb.get("player_key", ""),
        "resolve_time": min(times) if times else None,
        "tradable_now": tradable_now,
        "market_status": "active" if all_active else "inactive",
        "blockers": blockers_str,
        # Advisory only: an overround on a SUBSET of the field — never affects tradability/bucket.
        "settlement_caveat": BLOCKERS["field_overround"],
        "legs": legs, "n_legs": k, "field_size": n_field, "payout_floor_c": floor,
        "action_1_side": legs[0]["side"], "action_1_contract": legs[0]["contract"],
        "action_1_price_c": legs[0]["price_c"], "action_1_text": legs[0]["text"],
        "action_2_side": legs[1]["side"], "action_2_contract": legs[1]["contract"],
        "action_2_price_c": legs[1]["price_c"], "action_2_text": legs[1]["text"],
        "cost_c": cost,
        "exec_gap_c": gap_c,
        "exec_min_size": min_size,
        "exec_max_profit_dollars": round(gap_c * min_size / 100, 2) if min_size is not None else None,
        "reason": reason,
        "event_title": rows[0].get("event_title", ""),
        "ticker_a": legs[0]["ticker"],
        "ticker_b": legs[1]["ticker"],
        "url": rows[0].get("kalshi_url", ""),
    }


def find_dutch_books(rows: list[dict[str, Any]],
                     _diag: dict | None = None, *,
                     near_miss_max_over_c: int = 0) -> list[dict[str, Any]]:
    """Scan per-player contract rows and return one dutch-book finding per qualifying event (possibly
    empty). Two-way rows are grouped by ``event_ticker`` (**soccer 3-way games dispatch to
    ``_detect_n_way``, every other 2-way sport keeps ``_detect_pair`` byte-identical**); tournament-winner
    field rows are grouped separately and dispatched to ``_detect_field`` (overround-only). The optional
    ``_diag`` dict collects rejected + eligible-non-firing n-way/field candidates (for Debug / live smoke).

    ``near_miss_max_over_c`` > 0 additionally surfaces FLAT-payout near-miss watchlist rows (a 2-way or
    n-way MECE book overpriced by up to that many cents) — strict findings still win per event. It is NOT
    applied to ``_detect_field`` (a winner-field overround is convex on a subset, not a flat guaranteed
    loss, so the near-miss framing would be wrong). 0 (default) → strict-only, byte-for-byte unchanged."""
    groups: dict[str, list[dict[str, Any]]] = {}
    field_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        ev = row.get("event_ticker") or ""
        if not ev:
            continue
        if _is_two_way_row(row):
            groups.setdefault(ev, []).append(row)
        elif _is_field_row(row):
            field_groups.setdefault(ev, []).append(row)

    out: list[dict[str, Any]] = []
    for event_ticker, markets in groups.items():
        cfg = sports.sport_for_series(markets[0].get("series"))
        if cfg.sport_id == "soccer":
            finding = _detect_n_way(event_ticker, markets, cfg, _diag, near_miss_max_over_c)
        else:
            finding = _detect_pair(event_ticker, markets, near_miss_max_over_c)
        if finding is not None:
            out.append(finding)
    for event_ticker, markets in field_groups.items():
        cfg = sports.sport_for_series(markets[0].get("series"))
        finding = _detect_field(event_ticker, markets, cfg, _diag)
        if finding is not None:
            out.append(finding)
    # Strongest edge first (largest gross gap), deterministic tiebreak on event ticker.
    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"]))
    return out
