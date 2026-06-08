"""World Cup exact-order diagnostic (#4) — the qualifier-vs-top-two premium PROXY (no UI imports).

For each team in a 4-team World Cup group, this compares the market's "qualify from the group" YES ask
(``KXWCGROUPQUAL``) against the cost of synthetically replicating "finish top two" by buying YES on all
**12** exact-order (``KXWCGROUPORDER``) outcomes where the team places 1st or 2nd. The gap

    qualifier_vs_top2_premium_c = qualifier_yes_ask_c − synthetic_top_two_cost_c

is a PROXY for the market's implied value of the best-third (non-top-two) qualification path — NOT a
settlement-proven number and NEVER executable. Diagnostic-only: gross, top-of-book, fees not modeled.

Fail-closed by construction. Every gate below skips silently (a ``_diag`` counter), never a blocked row:
  * the event must carry exactly 24 orderings, with 4 placement names each, no duplicate within an
    ordering, and exactly 4 unique teams;
  * each team must appear in exactly 12 top-two orderings;
  * every one of those 12 legs AND the qualifier leg must be a FIRM BUY (price present, positive ask
    size, non-crossed quote, active) — else the team is skipped (never a partial sum);
  * the qualifier must join by group letter + normalized name (``wc_groups``).

Exact-order rows are excluded from the dutch-book / containment / synthetic / participant paths (see
``dutchbook.find_dutch_books`` guard + the ``exact_order`` family being non-laddered / non-participant).
"""

from __future__ import annotations

from typing import Any

import data
import wc_groups
from glossary import EXACT_ORDER_BASIS

EXACT_ORDER_DIAGNOSTIC = "EXACT_ORDER_DIAGNOSTIC"
EXACT_ORDER_CHECK_TYPE = "exact_order"
_QUALIFIER_SERIES = "KXWCGROUPQUAL"
_PLACE_KEYS = ("1st Place Team", "2nd Place Team", "3rd Place Team", "4th Place Team")
_NO_FIRM_QUALITY = ("No quote", "Crossed")
_GROUP_SIZE = 4
_TOP_TWO_PER_TEAM = 12   # a 4-team group: 1st in 3! + 2nd in 3! orderings
_ORDERINGS = 24          # 4! exact standings


def _num(x: Any) -> Any:
    return None if x is None or (isinstance(x, float) and x != x) else x


def _record(diag: dict | None, kind: str, event_ticker: str, reason: str) -> None:
    if diag is not None:
        diag.setdefault(kind, []).append({"event_ticker": event_ticker, "reason": reason})


def _firm_buy_ask_c(row: dict[str, Any]) -> int | None:
    """Cents to BUY YES on a FIRM, SIZED, ACTIVE, non-crossed leg — else None (skip the team).

    Stricter than dutchbook's price-only ``_firm_yes_ask_c`` on purpose: the synthetic bundle is only
    meaningful if every leg is actually buyable at top of book."""
    if str(row.get("quote_quality") or "") in _NO_FIRM_QUALITY:
        return None
    if str(row.get("status") or "") != "active":
        return None
    size = row.get("yes_ask_size")
    if size is None or size <= 0:
        return None
    return _num(row.get("yes_ask_c"))


def _placements(row: dict[str, Any]) -> list[str] | None:
    """The four placement team names (normalized, 1st→4th) for an exact-order ordering market, or None
    when the custom-strike is malformed / has a duplicate team within the one ordering."""
    cs = row.get("raw_custom_strike") or row.get("custom_strike") or {}
    if not isinstance(cs, dict):
        return None
    names: list[str] = []
    for k in _PLACE_KEYS:
        if k not in cs:
            return None
        n = wc_groups.normalize_country_name(cs[k])
        if not n:
            return None
        names.append(n)
    if len(set(names)) != _GROUP_SIZE:   # a placement repeated within one ordering → malformed
        return None
    return names


def _qualifier_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Map ``(group_letter, normalized_team_name) → qualifier row`` for the KXWCGROUPQUAL legs."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if str(r.get("series") or "").upper() != _QUALIFIER_SERIES:
            continue
        gk = wc_groups.parse_wc_group_key(r.get("event_ticker"))
        nm = wc_groups.normalize_country_name(r.get("player"))
        if gk and nm:
            index[(gk, nm)] = r
    return index


def find_exact_order_premiums(rows: list[dict[str, Any]],
                              _diag: dict | None = None) -> list[dict[str, Any]]:
    """One diagnostic finding per (team, group) where the 12-leg top-two bundle and the qualifier are all
    firm. Consumes per-player contract rows (``df.to_dict("records")``) so it is NaN-safe."""
    rows = rows or []
    qual_index = _qualifier_index(rows)
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("kind") != "exact_order":
            continue
        ev = r.get("event_ticker") or ""
        if not ev:
            continue
        if r.get("subpenny"):
            _record(_diag, "rejected", ev, "exact order: subpenny price (variable tick) — not trusted")
            continue
        groups.setdefault(ev, []).append(r)

    out: list[dict[str, Any]] = []
    for ev, markets in groups.items():
        out.extend(_detect_group(ev, markets, qual_index, _diag))
    # Largest premium-proxy first; deterministic id tiebreak (never the global _rank_key — exec_gap_c=None).
    out.sort(key=lambda f: (-(f["qualifier_vs_top2_premium_c"]), f["opportunity_id"]))
    return out


def _detect_group(ev: str, markets: list[dict[str, Any]], qual_index: dict, diag: dict | None
                  ) -> list[dict[str, Any]]:
    if len(markets) != _ORDERINGS:
        _record(diag, "rejected", ev, f"exact order: expected {_ORDERINGS} orderings, got {len(markets)}")
        return []
    gk = wc_groups.parse_wc_group_key(ev)
    if not gk:
        _record(diag, "rejected", ev, "exact order: unparseable group key")
        return []
    orderings: list[tuple[dict[str, Any], list[str]]] = []
    teams: set[str] = set()
    for m in markets:
        pl = _placements(m)
        if pl is None:
            _record(diag, "rejected", ev, "exact order: malformed / duplicate-team ordering")
            return []
        orderings.append((m, pl))
        teams.update(pl)
    if len(teams) != _GROUP_SIZE:
        _record(diag, "rejected", ev, f"exact order: expected {_GROUP_SIZE} unique teams, got {len(teams)}")
        return []

    findings: list[dict[str, Any]] = []
    for team in sorted(teams):
        top2 = [(m, pl) for (m, pl) in orderings if team in pl[:2]]
        if len(top2) != _TOP_TWO_PER_TEAM:
            _record(diag, "rejected", ev,
                    f"exact order: team {team} in {len(top2)} top-two orderings (expected {_TOP_TWO_PER_TEAM})")
            continue
        asks = [_firm_buy_ask_c(m) for (m, _pl) in top2]
        if any(a is None for a in asks):
            _record(diag, "not_price_proven", ev, f"exact order: team {team} has a non-firm top-two leg")
            continue
        qrow = qual_index.get((gk, team))
        if qrow is None:
            _record(diag, "rejected", ev, f"exact order: no qualifier for {team} in group {gk}")
            continue
        q_ask = _firm_buy_ask_c(qrow)
        if q_ask is None:
            _record(diag, "not_price_proven", ev, f"exact order: qualifier for {team} not firm")
            continue
        synth_cost = sum(asks)
        findings.append(_build_finding(ev, gk, qrow, [m for (m, _pl) in top2], asks, synth_cost, q_ask))
    return findings


def _build_finding(ev: str, group_key: str, qrow: dict[str, Any], top2_markets: list[dict[str, Any]],
                   asks: list[int], synth_cost: int, q_ask: int) -> dict[str, Any]:
    premium = q_ask - synth_cost
    display = str(qrow.get("player") or "this team")
    uuid = qrow.get("competitor_uuid") or qrow.get("player_key") or ""
    legs: list[dict[str, Any]] = []
    for m, a in zip(top2_markets, asks):
        legs.append({"side": "buy_yes", "contract": str(m.get("player") or m.get("market_ticker") or ""),
                     "price_c": a, "size": _num(m.get("yes_ask_size")),
                     "ticker": m.get("market_ticker", ""), "url": m.get("kalshi_url", ""),
                     "player_key": "", "text": f"Buy YES — {m.get('player') or m.get('market_ticker')} @ {a}¢"})
    legs.append({"side": "buy_yes", "contract": f"{display} qualify", "price_c": q_ask,
                 "size": _num(qrow.get("yes_ask_size")), "ticker": qrow.get("market_ticker", ""),
                 "url": qrow.get("kalshi_url", ""), "player_key": uuid,
                 "text": f"Buy YES — {display} qualify @ {q_ask}¢"})
    return {
        "check_type": EXACT_ORDER_CHECK_TYPE,
        "relationship_type": "exact_order_top2_proxy",
        "opportunity_id": data.opportunity_id(EXACT_ORDER_CHECK_TYPE, ev, uuid or display),
        "status": EXACT_ORDER_DIAGNOSTIC,
        "bucket": "qualifier_setup",
        "tradable_now": "Diagnostic only",
        "event_ticker": ev,
        "series": qrow.get("series", _QUALIFIER_SERIES),
        "tournament": qrow.get("tournament", ""),
        "tour": qrow.get("tour", ""),
        "group_key": group_key,
        "name": display,
        "participant_key": uuid,
        "participant_uuid": uuid,
        # The diagnostic numbers (PR3 schema).
        "qualifier_yes_ask_c": q_ask,
        "synthetic_top_two_cost_c": synth_cost,
        "qualifier_vs_top2_premium_c": premium,
        "legs": legs, "n_legs": len(legs),
        "action_1_text": f"Buy YES — Σ 12 top-two exact-order legs @ {synth_cost}¢",
        "action_2_text": f"vs {display} qualify YES @ {q_ask}¢ → premium {premium:+d}¢ (proxy)",
        "action_1_price_c": synth_cost, "action_2_price_c": q_ask,
        "ticker_1": (top2_markets[0].get("market_ticker") if top2_markets else ""),
        "ticker_2": qrow.get("market_ticker", ""),
        "url": qrow.get("kalshi_url", ""),
        "exact_order_basis": EXACT_ORDER_BASIS,
        "settlement_caveat": EXACT_ORDER_BASIS,
        "detail": f"Group {group_key}: qualifier vs top-two premium proxy",
    }
