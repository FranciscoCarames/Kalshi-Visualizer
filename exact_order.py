"""World Cup exact-order top-two bundle (#4) — two tiers, no UI imports.

For each team in a 4-team World Cup group, this builds the cost of "finish top two" as a 12-leg Buy-YES
bundle over the exact-order (``KXWCGROUPORDER``) outcomes where the team places 1st or 2nd, and compares
it against the market's direct "qualify from the group" YES ask (``KXWCGROUPQUAL``) — a COMPARATOR, not a
trade leg. The signed gap

    qualifier_vs_top2_premium_c = qualifier_yes_ask_c − synthetic_top_two_cost_c

is a relative-value SIGNAL (positive = the bundle is cheaper than the direct qualifier), never proof of
arbitrage. Summing one side of a 24-way book carries an overround bias, so it is typically negative.

Two tiers, both routed to the opt-in ``qualifier_setup`` section and NEVER Actionable:
  * **Diagnostic top-two bundle** (default): an honest reference comparison — economics + comparator +
    best-third caveat. Not a trading idea.
  * **Speculative top-two relative-value idea** (``_is_speculative``): a review-only idea, emitted only
    when the bundle is genuinely attractive (cost < 100¢, materially cheaper than the qualifier, no wide
    legs/comparator, real size). Neither tier is arbitrage or a qualifier replication: best-third-place
    qualification can make the direct qualifier pay while this top-two bundle pays zero.

Fail-closed by construction. Every gate below skips silently (a ``_diag`` counter), never a blocked row:
  * the event must carry exactly 24 orderings, with 4 placement names each, no duplicate within an
    ordering, and exactly 4 unique teams;
  * each team must appear in exactly 12 top-two orderings;
  * every one of those 12 legs AND the qualifier comparator must be a FIRM BUY (price present, positive
    ask size, non-crossed quote, active) — else the team is skipped (never a partial sum). A
    promotion-gate miss (e.g. wide leg) only DOWNGRADES the row to Diagnostic; it still emits.
  * the qualifier must join by group letter + normalized name (``wc_groups``).

Exact-order rows are excluded from the dutch-book / containment / synthetic / participant paths (see
``dutchbook.find_dutch_books`` guard + the ``exact_order`` family being non-laddered / non-participant).
"""

from __future__ import annotations

from typing import Any

import config
import data
import wc_groups
from glossary import SPECULATIVE_TOP2_BASIS

# Two tiers, both routed to the opt-in `qualifier_setup` section (never Actionable):
#   * EXACT_ORDER_DIAGNOSTIC          — the default reference/proxy comparison row (kept value for
#                                       back-compat with stored snapshots + the routing table).
#   * SPECULATIVE_TOP2_RELATIVE_VALUE — a review-only top-two trading idea, emitted only when the bundle
#                                       is genuinely attractive (see `_is_speculative`).
EXACT_ORDER_DIAGNOSTIC = "EXACT_ORDER_DIAGNOSTIC"
SPECULATIVE_TOP2_RELATIVE_VALUE = "SPECULATIVE_TOP2_RELATIVE_VALUE"
EXACT_ORDER_CHECK_TYPE = "exact_order"
_REL_DIAGNOSTIC = "exact_order_top2_bundle"
_REL_SPECULATIVE = "exact_order_top2_relative_value"
_QUALIFIER_SERIES = "KXWCGROUPQUAL"
_PLACE_KEYS = ("1st Place Team", "2nd Place Team", "3rd Place Team", "4th Place Team")
_NO_FIRM_QUALITY = ("No quote", "Crossed")
_WIDE_QUALITY = ("Wide", "Very wide")
_QUALITY_RANK = {"Tight": 0, "OK": 1, "Wide": 2, "Very wide": 3, "One-sided": 4, "No quote": 5, "Crossed": 6}
_GROUP_SIZE = 4
_TOP_TWO_PER_TEAM = 12   # a 4-team group: 1st in 3! + 2nd in 3! orderings
_ORDERINGS = 24          # 4! exact standings


def _worst_quality(qualities: list[str]) -> str:
    """The worst (widest) quote quality among the given legs by `_QUALITY_RANK`, or '' when empty."""
    return max((q for q in qualities if q), key=lambda q: _QUALITY_RANK.get(q, -1), default="")


def _is_speculative(synth: int, premium: int, wide_bundle_leg_count: int,
                    comparator_quote_quality: str, max_units: int | None) -> bool:
    """Promote a (firm, complete) Diagnostic bundle to the review-only Speculative tier ONLY when it is
    genuinely attractive: profitable favorable state, materially cheaper than the qualifier, no wide
    bundle legs, a non-wide comparator quote, and a real top-of-book size. A relative-value SIGNAL — never
    proof of arbitrage. Any miss leaves the row in the Diagnostic tier (it still emits)."""
    return (synth < 100
            and premium >= config.MIN_SPECULATIVE_DISCOUNT_C
            and wide_bundle_leg_count == 0
            and str(comparator_quote_quality or "") not in _WIDE_QUALITY
            and (max_units or 0) >= config.MIN_SPECULATIVE_TOP2_UNITS)


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
    premium = q_ask - synth_cost                       # >0 ⇒ bundle cheaper than the direct qualifier
    display = str(qrow.get("player") or "this team")
    uuid = qrow.get("competitor_uuid") or qrow.get("player_key") or ""

    # The trade is ONLY the 12 top-two Buy-YES legs. The qualifier is a COMPARATOR — never a leg.
    legs: list[dict[str, Any]] = []
    sizes: list[int] = []
    qualities: list[str] = []
    for m, a in zip(top2_markets, asks):
        sz = _num(m.get("yes_ask_size"))
        sizes.append(int(sz) if sz is not None else 0)
        qualities.append(str(m.get("quote_quality") or ""))
        legs.append({"side": "buy_yes", "contract": str(m.get("player") or m.get("market_ticker") or ""),
                     "price_c": a, "size": sz,
                     "ticker": m.get("market_ticker", ""), "url": m.get("kalshi_url", ""),
                     "player_key": "", "text": f"Buy YES — {m.get('player') or m.get('market_ticker')} @ {a}¢"})

    top2_max_units = min(sizes) if sizes else None
    worst_bundle_quote_quality = _worst_quality(qualities)
    wide_bundle_leg_count = sum(1 for q in qualities if q in _WIDE_QUALITY)
    comparator_quote_quality = str(qrow.get("quote_quality") or "")
    net_if_top2 = 100 - synth_cost                      # may be negative → a loss even when winning

    speculative = _is_speculative(synth_cost, premium, wide_bundle_leg_count,
                                  comparator_quote_quality, top2_max_units)
    status = SPECULATIVE_TOP2_RELATIVE_VALUE if speculative else EXACT_ORDER_DIAGNOSTIC
    relationship = _REL_SPECULATIVE if speculative else _REL_DIAGNOSTIC
    setup_type = relationship
    opportunity_class = "speculative_top2_bundle" if speculative else "diagnostic_top2_bundle"
    tradable_now = "Review execution" if speculative else "Diagnostic only"
    sign_word = "cheaper" if premium > 0 else ("more expensive" if premium < 0 else "level")
    detail = (f"Group {group_key}: speculative top-two bundle vs qualifier" if speculative
              else f"Group {group_key}: top-two bundle vs qualifier (reference)")

    return {
        "check_type": EXACT_ORDER_CHECK_TYPE,
        "relationship_type": relationship,
        "opportunity_id": data.opportunity_id(EXACT_ORDER_CHECK_TYPE, ev, uuid or display),
        "status": status,
        "bucket": "qualifier_setup",
        "tradable_now": tradable_now,
        "event_ticker": ev,
        "series": qrow.get("series", _QUALIFIER_SERIES),
        "tournament": qrow.get("tournament", ""),
        "tour": qrow.get("tour", ""),
        "group_key": group_key,
        "name": display,
        "participant_key": uuid,
        "participant_uuid": uuid,
        "setup_type": setup_type,
        "opportunity_class": opportunity_class,
        # Economics (exact integer cents). The premium is a SIGNAL — never proof of arbitrage.
        "qualifier_yes_ask_c": q_ask,
        "synthetic_top_two_cost_c": synth_cost,
        "qualifier_vs_top2_premium_c": premium,
        "top2_net_if_top2_c": net_if_top2,
        "top2_loss_if_not_top2_c": synth_cost,
        "top2_max_units": top2_max_units,
        "worst_bundle_quote_quality": worst_bundle_quote_quality,
        "wide_bundle_leg_count": wide_bundle_leg_count,
        "comparator_quote_quality": comparator_quote_quality,
        "legs": legs, "n_legs": len(legs),
        "action_1_text": f"Buy YES — Σ 12 top-two exact-order legs @ {synth_cost}¢",
        "action_2_text": f"Comparator: {display} qualify YES @ {q_ask}¢ · {abs(premium)}¢ {sign_word}",
        "action_1_price_c": synth_cost, "action_2_price_c": q_ask,
        "ticker_1": (top2_markets[0].get("market_ticker") if top2_markets else ""),
        "ticker_2": qrow.get("market_ticker", ""),
        "url": qrow.get("kalshi_url", ""),
        "exact_order_basis": SPECULATIVE_TOP2_BASIS,
        "settlement_caveat": SPECULATIVE_TOP2_BASIS,
        "detail": detail,
    }
