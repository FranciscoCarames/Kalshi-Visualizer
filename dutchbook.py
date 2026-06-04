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

The N-leg **exact-score synthetic bundle** (a player's MECE set scores priced vs their match-winner) is
BUILT in the sibling ``synthetic_bundle.py`` (milestone m5). Still out of scope here: n-outcome winner
FIELDS (≥3-player tournament/advance fields). No Streamlit / pandas imports here, so this module is
independently testable.
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


def _settlement_caveat(rows: list[dict[str, Any]]) -> str:
    """The NON-blocking settlement caveat for a finding's legs, or '' when none applies.

    A per-game (`_GAME_FAMILY`) book — NBA/WNBA single games and soccer 3-way games — can be broken by an
    abnormal resolution (postponed / abandoned / no-contest / not-as-scheduled), so it carries the
    `game_settlement` caveat. Match/series books settle together under normal one-winner settlement → ''.
    This is ADVISORY: it never enters `blockers`/`blocked_reason`, so it can't change tradability/bucket.
    """
    return BLOCKERS["game_settlement"] if any(r.get("kind") == _GAME_FAMILY for r in rows) else ""


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

    reason = (
        f"{direction}: {side.replace('_', ' ')} both legs costs {best['cost_c']}¢ < 100¢ "
        f"→ {gap_c}¢ gross per unit, under normal one-winner settlement "
        f"({label_a} {best['price_a']}¢ + {label_b} {best['price_b']}¢)"
    )

    # Stage-1 schema: stable opportunity_id + relationship_type + dashboard bucket + REQUIRED
    # blocked_reason. Id recipe = the check type + the event + the SORTED participant keys, so it is
    # leg-order-independent and unique per event (one finding per event). A dutch book is actionable
    # when tradable (the settlement caveat is advisory, not a blocker), else blocked; blocked_reason is
    # non-empty IFF blocked.
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
        # Normalized leg-status for the lifecycle diff (§9 market_status / §10 "leg inactive"): a single
        # market_status from the same both-legs-active check that drives tradability.
        "market_status": "active" if both_active else "inactive",
        "blockers": blockers_str,
        # Non-blocking settlement caveat (per-game books only); advisory, never affects tradability/bucket.
        "settlement_caveat": _settlement_caveat([a, b]),
        # Two-leg buy-only action plan (same vocabulary as consistency rows, so the dashboard reuses it).
        "action_1_side": side, "action_1_contract": label_a, "action_1_price_c": best["price_a"],
        "action_1_text": _buy_text(side, label_a, best["price_a"]),
        "action_2_side": side, "action_2_contract": label_b, "action_2_price_c": best["price_b"],
        "action_2_text": _buy_text(side, label_b, best["price_b"]),
        # Profit / sizing (mirrors consistency's exec_* keys; gross of fees/slippage).
        "cost_c": best["cost_c"],
        "payout_floor_c": 100,   # a 2-way book pays exactly 100¢ in every state (PR 13 schema parity)
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
                  diag: dict | None = None) -> dict[str, Any] | None:
    """Detect an n-outcome dutch book on one MECE event (currently soccer 3-way games), or None."""
    proof = prove_mece(rows, cfg)
    if not proof.ok:
        _record(diag, "rejected", event_ticker, proof.reason)
        return None
    n = len(rows)
    candidates = [c for c in (_n_direction_candidate("buy_yes", rows),
                              _n_direction_candidate("buy_no", rows)) if c is not None]
    fired = [c for c in candidates if c["gap_c"] > 0]
    if not fired:
        _record(diag, "eligible_non_firing", event_ticker, "priced, no positive gap")
        return None
    best = max(fired, key=lambda c: c["gap_c"])
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
    bucket = "actionable" if tradable_now.startswith("Yes") else "blocked"
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
    reason = (f"{direction}: {word} all {n} legs costs {cost}c < {floor}c payout floor "
              f"-> {gap_c}c gross per unit, under normal one-winner settlement")

    return {
        "check_type": CHECK_TYPE,
        "relationship_type": CHECK_TYPE,
        "opportunity_id": oid,
        "bucket": bucket,
        "blocked_reason": blocked_reason,
        "status": EXECUTABLE_DUTCH_BOOK,
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
        # Non-blocking settlement caveat (soccer 3-way games are per-game → carry it); advisory only.
        "settlement_caveat": _settlement_caveat(rows),
        # Full N-leg plan in `legs`; action_1/2 backfilled from the first two legs so the unified 2-leg
        # columns + lifecycle still render. payout_floor_c is the (n-1)*100 (overround) / 100 (underround).
        "legs": legs, "n_legs": n, "payout_floor_c": floor,
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


def find_dutch_books(rows: list[dict[str, Any]],
                     _diag: dict | None = None) -> list[dict[str, Any]]:
    """Scan per-player contract rows and return one dutch-book finding per qualifying event (possibly
    empty). Eligible rows are grouped by ``event_ticker``; **soccer 3-way games dispatch to
    ``_detect_n_way``, every other 2-way sport keeps ``_detect_pair`` byte-identical**. The optional
    ``_diag`` dict collects rejected + eligible-non-firing n-way candidates (for Debug / live smoke).
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
        cfg = sports.sport_for_series(markets[0].get("series"))
        if cfg.sport_id == "soccer":
            finding = _detect_n_way(event_ticker, markets, cfg, _diag)
        else:
            finding = _detect_pair(event_ticker, markets)
        if finding is not None:
            out.append(finding)
    # Strongest edge first (largest gross gap), deterministic tiebreak on event ticker.
    out.sort(key=lambda f: (-f["exec_gap_c"], f["event_ticker"]))
    return out
