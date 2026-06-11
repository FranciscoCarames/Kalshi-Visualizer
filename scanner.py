"""Cross-sport opportunity scanner — Stage 2 engine.

One PURE function, `unified_opportunities`, that aggregates every opportunity across all wired sports
(tennis, NBA, WNBA, golf, soccer, MLB, NHL, motorsport) into a single best→worst-ranked frame: it runs the containment-ladder checker
(`consistency.build_checks`) and the dutch-book detector (`dutchbook.find_dutch_books`) per sport,
stamps each row with its `sport`, normalizes the two row shapes onto one schema, ranks them, and
optionally persists the scan to the Stage-1 snapshot store.

Kept Streamlit-free AND network-free: the per-sport contract fetch is dependency-INJECTED
(`fetch_fn(sport_id) -> contracts DataFrame`), so the app passes its cached `load_contracts` while unit
tests pass a stub — the scanner itself never imports `app`, `streamlit`, or `kalshi_client`. A single
sport's fetch/processing failure is recorded and skipped, never allowed to blank the whole frame.

`opportunity_id` / `relationship_type` / `bucket` / `blocked_reason` already live on every row (Stage 1);
this module only adds `sport` and the unified projection, then ranks.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import pandas as pd

import config
import consistency
import dutchbook
import exact_order
import game_support
import no_structures
import sports
import stage_elim
import synthetic_bundle

# Section priority for ranking (lower = surfaced first). Mirrors the dashboard's importance order;
# `bucket` is stamped on every row by Stage 1 (consistency.bucket_of / dutchbook). Its key set MUST equal
# consistency.DASHBOARD_BUCKETS (a test guards this). risk_budget / near_miss are "beyond the strict rule"
# (opt-in, past the actionable line), so they rank just below blocked and above the near_edge watchlist.
BUCKET_PRIORITY = {
    "actionable": 0,
    "review_signal": 1,   # settlement-caveated discrepancies (synthetic bundles) — review, just below actionable
    "blocked": 2,
    "risk_budget": 3,     # containment near-miss: bounded loss, convex upside (opt-in)
    "near_miss": 4,       # dutch-book near-miss: flat-payout watchlist (opt-in)
    "qualifier_setup": 5,  # World Cup qualifier setups (opt-in; review-only / diagnostic — never Actionable)
    "no_structure": 6,    # cheap bounded-loss NO fades (opt-in; speculative — never Actionable)
    "near_edge": 7,
    "display_signal": 8,
    "wide_signal": 9,
    "data_quality": 10,
    "clean": 11,
}

# The shared minimal schema both row shapes (containment checks + dutch-book findings) map onto. Stable
# column order so the interim table / CSV are coherent and the empty frame keeps its columns.
UNIFIED_COLUMNS = [
    "sport", "sport_label", "source",          # provenance
    "name", "detail", "tournament", "tour",    # what it is
    "action_1_text", "action_2_text",          # the two buys (same vocabulary across both shapes)
    "action_1_price_c", "action_2_price_c", "cost_c",   # numeric leg prices + combined cost (panel, Stage 5 §0)
    "exec_gap_c", "exec_min_size", "exec_max_profit_dollars",  # gross edge / sizing
    "bucket", "status", "tradable_now", "blocked_reason",      # routing / state (Stage 1)
    "market_status", "rule_flag",              # lifecycle-diff inputs (Stage 3 §9/§10)
    "settlement_caveat",                       # non-blocking per-game settlement caveat (dutch-book PR 6)
    "relationship_type", "resolution_mode",     # identity (Stage 1) + Bounded-Loss vertical/calendar split
    "opportunity_id",
    "ticker_1", "ticker_2", "url", "url_2",    # per-leg tickers + links (panel, Stage 5 §0)
    "legs", "n_legs",                          # N-leg plan (synthetic bundles); synthesized 2-leg otherwise
    "payout_floor_c", "roi_pct",               # guaranteed payout floor + gross ROI on cost (PR 13)
    "snapshot_id",                             # stamped by store.write_snapshot at write time (PR 21a)
    "participant_key",                         # the PRIMARY participant's key, for the detail panel (PR 24)
    # ALL participants on the opportunity (every leg), for the participant multi-select filter (PR6 / #13).
    # Parallel lists key<->label; the singular participant_key above stays the detail-panel anchor.
    "participant_keys", "participant_labels",
    # "Beyond the strict rule" (PR 29): edge_class tags risk-budget / near-miss rows; worst/best per-unit
    # profit drives the convex risk-budget columns (max loss / max profit / upside:risk). roi_pct (above)
    # doubles as the worst-case ROC for risk-budget rows (worst_case_profit_c == exec_gap_c).
    "edge_class", "worst_case_profit_c", "best_case_profit_c",
    # Probability-context display outrights (risk-budget "spread / outright" view) — None for non-containment
    # shapes. display_c is the DISPLAY OUTRIGHT price (reasonable-quote midpoint, else last trade).
    "parent_display_c", "child_display_c", "display_spread_c", "spread_over_parent", "spread_over_child",
    # Firm-quote passthrough (Phase 1, display-only honesty rail): parent YES bid + child YES ask drive the
    # conservative tradable-side success gap + the "Midpoint-only" flag. Never read by bucket_of / _rank_key.
    "parent_yes_bid_c", "child_yes_ask_c",
    # Phase 2 E (display-only, containment rows): ladder rung labels for "Wins if …" + worst-leg quote
    # quality for "Quote health". Never read by bucket_of / _rank_key.
    "child_node", "parent_node", "comp_quote_quality",
    # World Cup Qualifier Setups (PR1): a cross-cutting product tag, SEPARATE from bucket/routing. Read only
    # by a UI badge — never by bucket_of / _rank_key / filters. `setup_family` = product area
    # ("wc_qualifier"); `setup_type` = the specific setup (qualifier_not_winner / qualifier_yes_basket /
    # qualifier_no_basket / exact_order_top2_bundle / exact_order_top2_relative_value / game_support_signal).
    # Default "" for every other row.
    "setup_family", "setup_type",
    # Diagnostic-only numeric fields for the qualifier_setup section (PR3 declares the schema; PR4/PR5 fill
    # them). exact-order #4: qualifier_vs_top2_premium_c (a best-third-path PROXY) + its two inputs; game-
    # support #5: ask_support_score_* (3·win+draw asks — NOT expected points). join_confidence is advisory.
    "qualifier_vs_top2_premium_c", "synthetic_top_two_cost_c", "qualifier_yes_ask_c",
    "ask_support_score_total_c", "ask_support_score_per_game_c", "join_confidence",
    # Exact-order top-two bundle two-tier economics (#4 redux). opportunity_class tags the tier
    # (diagnostic_top2_bundle | speculative_top2_bundle). top2_net_if_top2_c = 100 − bundle cost (may be
    # negative); top2_loss_if_not_top2_c = bundle cost; top2_max_units = min ask size across the 12 legs.
    # worst_bundle_quote_quality / wide_bundle_leg_count cover the 12 BUNDLE legs only; comparator_quote_
    # quality is the direct qualifier (a comparator, not a leg). All None on every non-bundle row.
    "opportunity_class", "top2_net_if_top2_c", "top2_loss_if_not_top2_c", "top2_max_units",
    "worst_bundle_quote_quality", "wide_bundle_leg_count", "comparator_quote_quality",
]

# World Cup Qualifier Setups — the soccer containment leaf that IS setup #1 (qualifier-not-winner). Tagged
# in place (it stays in its actionable/blocked bucket); the tag is the only change.
_WC_QUALIFIER_FAMILY = "wc_qualifier"
_WC_NOT_WINNER_CHILD = "Win group"
_WC_NOT_WINNER_PARENT = "Reach Round of 32"


def _participants(pairs: list[tuple[Any, Any]]) -> tuple[list[str], list[str]]:
    """From (key, label) pairs, the deduped parallel (keys, labels) for the participant filter — empties
    dropped (so a Tie/draw leg or an unkeyed leg never becomes a phantom participant), order preserved.
    NEVER falls back to the primary key for a multi-leg row: a leg with no key is simply omitted."""
    keys: list[str] = []
    labels: list[str] = []
    seen: set[str] = set()
    for k, lab in pairs:
        k = str(k or "")
        if not k or k in seen:
            continue
        seen.add(k)
        keys.append(k)
        labels.append(str(lab or k))
    return keys, labels


def _cost(a: Any, b: Any) -> Any:
    """Combined cost of the two legs in cents, or None if either price is missing."""
    a, b = _num(a), _num(b)
    return (a + b) if (a is not None and b is not None) else None


def _market_status_consistency(r: dict[str, Any]) -> str:
    """Normalized leg status for a consistency row: 'inactive' if any present leg is non-active,
    else 'active' (a blank/absent leg status — e.g. a single-sided row — does not mark inactive)."""
    for s in (r.get("child_status"), r.get("parent_status")):
        s = str(s or "")
        if s and s != "active":
            return "inactive"
    return "active"


def _num(x: Any) -> Any:
    """None for None or float NaN (a None round-trips to NaN through DataFrame.to_dict)."""
    return None if x is None or (isinstance(x, float) and x != x) else x


def gross_roi_pct(gap: Any, cost: Any) -> Any:
    """Gross ROI % on top-of-book cost (gap / cost × 100, 1 dp), or None when cost is missing/non-positive.
    GROSS — before fees / slippage / partial fill (same caveat as exec_max_profit_dollars). Shared by the
    unified mappers and the Streamlit dutch-book / synthetic tables so the number is defined once."""
    gap, cost = _num(gap), _num(cost)
    if gap is None or cost is None or cost <= 0:
        return None
    return round(gap / cost * 100, 1)


def legs_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Every opportunity as a uniform list of leg dicts. Returns the row's own ``legs`` when it is a
    non-empty list (N-leg dutch books / synthetic bundles); otherwise SYNTHESIZES a 2-leg list from the
    positional ``action_1/2_*`` + ``ticker_1/2`` + ``url``/``url_2`` fields. This gives every row — the
    2-leg containment / dutch shapes AND old snapshots written before ``legs`` existed — a single render
    path. A leg with no action text is dropped, so a single-sided row yields a shorter list, not a blank
    leg."""
    legs = row.get("legs")
    if isinstance(legs, list) and legs:
        return legs
    out: list[dict[str, Any]] = []
    for i, (tk, url) in enumerate(((row.get("ticker_1"), row.get("url")),
                                   (row.get("ticker_2"), row.get("url_2"))), start=1):
        text = row.get(f"action_{i}_text")
        if not text:
            continue
        out.append({
            "side": row.get(f"action_{i}_side") or "",
            "contract": row.get(f"action_{i}_contract") or "",
            "price_c": _num(row.get(f"action_{i}_price_c")),
            "size": None,
            "ticker": tk or "",
            "url": url or "",
            "text": text,
        })
    return out


def _finalize_unified(d: dict[str, Any], *, payout_floor_c: Any) -> dict[str, Any]:
    """Stamp the derived schema fields (PR 13) onto a built unified row: the guaranteed payout floor, the
    gross ROI on cost, and a uniform ``legs`` list (synthesized for 2-leg shapes). ``n_legs`` follows the
    leg list. Idempotent over the existing ``legs`` so N-leg findings keep their real list."""
    d["payout_floor_c"] = _num(payout_floor_c)
    d["roi_pct"] = gross_roi_pct(d.get("exec_gap_c"), d.get("cost_c"))
    legs = legs_of(d)
    d["legs"] = legs or None
    d["n_legs"] = _num(d.get("n_legs")) or (len(legs) if legs else None)
    # WC Qualifier Setups (PR1): every row carries the tag fields so old snapshots + untagged rows are safe.
    d.setdefault("setup_family", "")
    d.setdefault("setup_type", "")
    # Bounded-Loss vertical/calendar split: default to the conservative "calendar" so dutch-book / synthetic
    # rows and pre-field snapshots stay safe (only risk-budget containment rows carry a real value).
    d.setdefault("resolution_mode", "calendar")
    # Phase 2 E display-only fields default empty on non-containment shapes + pre-field snapshots.
    for _k in ("child_node", "parent_node", "comp_quote_quality"):
        d.setdefault(_k, "")
    # Exact-order top-two bundle two-tier economics — default on every row so old snapshots stay safe.
    for _k in ("opportunity_class", "worst_bundle_quote_quality", "comparator_quote_quality"):
        d.setdefault(_k, "")
    for _k in ("top2_net_if_top2_c", "top2_loss_if_not_top2_c", "top2_max_units", "wide_bundle_leg_count"):
        d.setdefault(_k, None)
    # Firm-quote passthrough (Phase 1): default None so pre-field snapshots + non-containment shapes stay safe.
    for _k in ("parent_yes_bid_c", "child_yes_ask_c"):
        d.setdefault(_k, None)
    return d


def _to_unified_consistency(r: dict[str, Any], cfg) -> dict[str, Any]:
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "containment",
        "name": r.get("player") or "", "detail": r.get("chain") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _cost(r.get("action_1_price_c"), r.get("action_2_price_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": _market_status_consistency(r), "rule_flag": r.get("rule_flag") or "",
        "settlement_caveat": "",  # containment ladders aren't per-game books (soccer leaf overrides below)
        "participant_key": r.get("player_key") or "",   # for the detail panel (PR 24)
        "relationship_type": r.get("relationship_type") or "",
        "resolution_mode": r.get("resolution_mode") or "calendar",   # vertical (simultaneous) / calendar
        "opportunity_id": r.get("opportunity_id") or "",
        # Leg 1 = broader/parent (Buy YES), leg 2 = deeper/child (Buy NO). Links must follow the legs:
        # url -> parent (leg 1), url_2 -> child (leg 2). (Was reversed: url pointed at the child.)
        "ticker_1": r.get("parent_ticker") or "", "ticker_2": r.get("child_ticker") or "",
        "url": r.get("parent_url") or r.get("child_url") or "", "url_2": r.get("child_url") or r.get("parent_url") or "",
        "legs": None, "n_legs": None,  # synthesized into a 2-leg list by _finalize_unified (parity)
        # Risk-budget tag + convex payoff (PR 29) — populated only for RISK_BUDGET_CANDIDATE / executable rows.
        "edge_class": r.get("edge_class") or "",
        "worst_case_profit_c": _num(r.get("worst_case_profit_c")),
        "best_case_profit_c": _num(r.get("best_case_profit_c")),
        # Probability-context display outrights (risk-budget spread/outright view).
        "parent_display_c": _num(r.get("parent_display_c")),
        "child_display_c": _num(r.get("child_display_c")),
        "display_spread_c": _num(r.get("display_spread_c")),
        "spread_over_parent": _num(r.get("spread_over_parent")),
        "spread_over_child": _num(r.get("spread_over_child")),
        # Firm-quote passthrough (Phase 1, display-only): parent YES bid + child YES ask for the conservative gap.
        "parent_yes_bid_c": _num(r.get("parent_yes_bid_c")),
        "child_yes_ask_c": _num(r.get("child_yes_ask_c")),
        # Phase 2 E (display-only): the ladder rung labels (for "Wins if …") + the worst-leg quote quality
        # (for "Quote health"). Read only by the speculative viewmodel; never by bucket_of / _rank_key.
        "child_node": r.get("child_node") or "", "parent_node": r.get("parent_node") or "",
        "comp_quote_quality": r.get("comp_quote_quality") or "",
    }
    d["participant_keys"], d["participant_labels"] = _participants([(r.get("player_key"), r.get("player"))])
    # WC Qualifier Setups (PR1): tag ONLY the soccer "Win group ⊆ Reach Round of 32" leaf — setup #1
    # (qualifier-not-winner). Stays in its actionable/blocked bucket; the tag is read only by a UI badge.
    if (cfg.sport_id == "soccer" and r.get("child_node") == _WC_NOT_WINNER_CHILD
            and r.get("parent_node") == _WC_NOT_WINNER_PARENT):
        d["setup_family"], d["setup_type"] = _WC_QUALIFIER_FAMILY, "qualifier_not_winner"
        # Best-third mechanic: a 3rd-placed team's "Reach Round of 32" is decided only AFTER all groups
        # finish (later than "Win group"), so the two legs are NOT guaranteed to settle together → keep this
        # leaf in Calendar and stamp a non-blocking caveat (advisory; never changes bucket/tradability).
        d["resolution_mode"] = "calendar"
        d["settlement_caveat"] = ("qualification can depend on best-third standings decided after this "
                                  "group ends — the legs may not resolve together")
    # broader-YES + deeper-NO guarantees ≥100¢ in every settled state, so the floor is 100 when there's a
    # buy-plan (a firm cost), else None (CLEAN / display-only rows have no executable position).
    return _finalize_unified(d, payout_floor_c=(100 if d["cost_c"] is not None else None))


def _to_unified_dutchbook(r: dict[str, Any], cfg) -> dict[str, Any]:
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "dutch_book",
        "name": r.get("match") or "", "detail": r.get("direction") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": r.get("market_status") or "active", "rule_flag": "",  # dutch books carry no rule flag
        "settlement_caveat": r.get("settlement_caveat") or "",  # non-blocking per-game caveat (PR 6)
        # The primary participant (player A); both legs' links stay in the action summary (PR 24).
        "participant_key": r.get("player_key_a") or "",
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        # Two legs of the same event; one event link (no second link).
        "ticker_1": r.get("ticker_a") or "", "ticker_2": r.get("ticker_b") or "",
        "url": r.get("url") or "", "url_2": "",
        # 2-leg books carry legs=None (synthesized below); the n-outcome (soccer 3-way) path sets a full
        # `legs` list. _finalize_unified normalizes both into a uniform list + n_legs.
        "legs": r.get("legs"), "n_legs": _num(r.get("n_legs")),
        # Near-miss tag + flat per-unit profit (worst == best == gap_c, negative on a near-miss).
        "edge_class": r.get("edge_class") or "",
        "worst_case_profit_c": _num(r.get("worst_case_profit_c")),
        "best_case_profit_c": _num(r.get("best_case_profit_c")),
    }
    # Participants: n-leg shapes (soccer 3-way, field overround) carry per-leg identity on `legs` (a Tie/
    # draw leg has no player_key → dropped); the 2-way path has no legs yet (synthesized later), so use the
    # detector's two named participants. NEVER fall back to the single primary key for a multi-leg row.
    _legs = r.get("legs")
    if isinstance(_legs, list) and _legs:
        _pairs = [(leg.get("player_key"), leg.get("contract")) for leg in _legs]
    else:
        _pairs = [(r.get("player_key_a"), r.get("player_a")), (r.get("player_key_b"), r.get("player_b"))]
    d["participant_keys"], d["participant_labels"] = _participants(_pairs)
    # 2-way floor is 100¢; the n-way path already carries (n−1)·100 (overround) / 100 (underround).
    return _finalize_unified(d, payout_floor_c=(_num(r.get("payout_floor_c")) or 100))


def _to_unified_group_basket(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a hard-floor group-basket finding (N legs) onto the unified schema. Shares the dutch-book finding
    shape (legs / n_legs / payout_floor_c / action_1/2 / player_key_a/b), but tagged with its own minimal,
    future-compatible provenance: ``source="group_basket"`` (peer of ``"dutch_book"``) and the finding's
    ``relationship_type="group_cardinality_floor"``. NO broader proof_level / setup_type taxonomy here —
    that belongs to the separate expansion plan."""
    d = _to_unified_dutchbook(r, cfg)
    d["source"] = "group_basket"
    d["relationship_type"] = r.get("relationship_type") or "group_cardinality_floor"
    # WC Qualifier Setups (PR1): tag the hard-floor group baskets — setups #2 (YES) / #3 (NO). Stays in its
    # actionable/blocked bucket; the tag is read only by a UI badge. Direction is "yes_basket"/"no_basket".
    if cfg.sport_id == "soccer":
        d["setup_family"] = _WC_QUALIFIER_FAMILY
        d["setup_type"] = "qualifier_no_basket" if r.get("direction") == "no_basket" else "qualifier_yes_basket"
    return d


def _to_unified_stage_elim_book(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a standalone stage-of-elimination 7-way MECE book onto the unified schema. Shares the dutch-book
    finding shape (clean executable edge), tagged ``source="stage_elim"``."""
    d = _to_unified_dutchbook(r, cfg)
    d["source"] = "stage_elim"
    d["relationship_type"] = r.get("relationship_type") or stage_elim.BOOK_CHECK_TYPE
    return d


def _to_unified_stage_elim_synth(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a cross-family tail-sum (advance-rung replication) onto the unified schema. Review-only: carries
    ``rule_flag="SETTLEMENT_CHECK_REQUIRED"`` and self-assigns its review_signal/blocked bucket."""
    d = _to_unified_dutchbook(r, cfg)
    d["source"] = "stage_elim_synth"
    d["relationship_type"] = r.get("relationship_type") or stage_elim.SYNTH_CHECK_TYPE
    d["rule_flag"] = r.get("rule_flag") or "SETTLEMENT_CHECK_REQUIRED"
    return d


def _to_unified_exact_order(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map an exact-order top-two bundle finding (#4) onto the unified schema. Two tiers (Diagnostic /
    Speculative — the finding self-assigns its status/relationship/setup_type/opportunity_class), both
    self-assigning ``bucket="qualifier_setup"`` + ``exec_gap_c=None`` so they NEVER enter _rank_key /
    actionable. The qualifier is a COMPARATOR (not a leg); ``legs`` carries the 12 bundle legs verbatim.
    Participant identity comes from the JOINED QUALIFIER UUID (not the order-market pseudo-keys)."""
    uuid = r.get("participant_uuid") or ""
    keys, labels = _participants([(uuid, r.get("name"))])
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "exact_order",
        "name": r.get("name") or "", "detail": r.get("detail") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": None,
        # NEVER an executable edge. exec_gap_c=None floors it within its opt-in section.
        "exec_gap_c": None, "exec_min_size": None, "exec_max_profit_dollars": None,
        "bucket": "qualifier_setup", "status": r.get("status") or exact_order.EXACT_ORDER_DIAGNOSTIC,
        "tradable_now": r.get("tradable_now") or "Diagnostic only", "blocked_reason": "",
        "market_status": "active", "rule_flag": "",
        "settlement_caveat": r.get("settlement_caveat") or "",
        "participant_key": uuid,
        "relationship_type": r.get("relationship_type") or "exact_order_top2_bundle",
        "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": r.get("ticker_1") or "", "ticker_2": r.get("ticker_2") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": r.get("legs"), "n_legs": _num(r.get("n_legs")),
        "edge_class": "", "worst_case_profit_c": None, "best_case_profit_c": None,
        "setup_family": _WC_QUALIFIER_FAMILY, "setup_type": r.get("setup_type") or "exact_order_top2_bundle",
        # Comparator + bundle inputs (PR3 schema).
        "qualifier_vs_top2_premium_c": _num(r.get("qualifier_vs_top2_premium_c")),
        "synthetic_top_two_cost_c": _num(r.get("synthetic_top_two_cost_c")),
        "qualifier_yes_ask_c": _num(r.get("qualifier_yes_ask_c")),
        # Two-tier economics + quote split.
        "opportunity_class": r.get("opportunity_class") or "",
        "top2_net_if_top2_c": _num(r.get("top2_net_if_top2_c")),
        "top2_loss_if_not_top2_c": _num(r.get("top2_loss_if_not_top2_c")),
        "top2_max_units": _num(r.get("top2_max_units")),
        "worst_bundle_quote_quality": r.get("worst_bundle_quote_quality") or "",
        "wide_bundle_leg_count": _num(r.get("wide_bundle_leg_count")),
        "comparator_quote_quality": r.get("comparator_quote_quality") or "",
    }
    d["participant_keys"], d["participant_labels"] = keys, labels
    # No guaranteed floor; payout_floor_c stays None.
    return _finalize_unified(d, payout_floor_c=None)


def _to_unified_game_support(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a game-support signal finding (#5) onto the unified schema. Diagnostic-only ranking signal —
    self-assigns ``bucket="qualifier_setup"`` + ``exec_gap_c=None`` (never _rank_key / actionable) and
    carries NO ROI / size / profit. Participant identity is the team's ``soccer_team`` UUID."""
    uuid = r.get("participant_uuid") or ""
    keys, labels = _participants([(uuid, r.get("name"))])
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "game_support",
        "name": r.get("name") or "", "detail": r.get("detail") or "",
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": None,
        "exec_gap_c": None, "exec_min_size": None, "exec_max_profit_dollars": None,
        "bucket": "qualifier_setup", "status": r.get("status") or game_support.GAME_SUPPORT_SIGNAL,
        "tradable_now": r.get("tradable_now") or "Diagnostic only", "blocked_reason": "",
        "market_status": "active", "rule_flag": "",
        "settlement_caveat": r.get("settlement_caveat") or "",
        "participant_key": uuid,
        "relationship_type": r.get("relationship_type") or "game_support_signal",
        "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": r.get("ticker_1") or "", "ticker_2": r.get("ticker_2") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": r.get("legs"), "n_legs": _num(r.get("n_legs")),
        "edge_class": "", "worst_case_profit_c": None, "best_case_profit_c": None,
        "setup_family": _WC_QUALIFIER_FAMILY, "setup_type": "game_support_signal",
        # The diagnostic numbers (PR3 schema).
        "qualifier_yes_ask_c": _num(r.get("qualifier_yes_ask_c")),
        "ask_support_score_total_c": _num(r.get("ask_support_score_total_c")),
        "ask_support_score_per_game_c": _num(r.get("ask_support_score_per_game_c")),
    }
    d["participant_keys"], d["participant_labels"] = keys, labels
    return _finalize_unified(d, payout_floor_c=None)


def _to_unified_synthetic(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a synthetic-bundle finding (N legs) onto the unified schema. The full plan lives in `legs`;
    `action_1/2_*` are backfilled (by the detector) from the first two legs so 2-leg consumers still work."""
    legs = r.get("legs") or []
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "synthetic_bundle",
        "name": r.get("player") or r.get("match") or "",
        "detail": (f"score bundle vs "
                   f"{'reach-next-round' if r.get('hedge_kind') == 'advance' else 'match-winner'} "
                   f"({r.get('direction') or ''})").strip(),
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        "exec_gap_c": _num(r.get("exec_gap_c")), "exec_min_size": _num(r.get("exec_min_size")),
        "exec_max_profit_dollars": _num(r.get("exec_max_profit_dollars")),
        "bucket": r.get("bucket") or "", "status": r.get("status") or "",
        "tradable_now": r.get("tradable_now") or "", "blocked_reason": r.get("blocked_reason") or "",
        "market_status": r.get("market_status") or "active", "rule_flag": r.get("rule_flag") or "",
        "settlement_caveat": "",  # synthetic bundles carry their caveat in blocked_reason (always review-only)
        "relationship_type": r.get("relationship_type") or "", "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": (legs[0].get("ticker") if len(legs) > 0 else "") or "",
        "ticker_2": (legs[1].get("ticker") if len(legs) > 1 else "") or "",
        "url": r.get("url") or "", "url_2": "",
        "legs": legs, "n_legs": _num(r.get("n_legs")),
        # Synthetic bundles aren't risk-budget/near-miss rows (always review-only) — no edge_class / convex split.
        "edge_class": "", "worst_case_profit_c": None, "best_case_profit_c": None,
    }
    # A synthetic bundle is one player's score set vs one hedge — a single participant.
    d["participant_keys"], d["participant_labels"] = _participants([(r.get("player_key"), r.get("player"))])
    # synthetic forward floor = 100¢, reverse = N×100¢ (carried as payout_floor_c by _build_finding).
    return _finalize_unified(d, payout_floor_c=_num(r.get("payout_floor_c")))


def _to_unified_no_structure(r: dict[str, Any], cfg) -> dict[str, Any]:
    """Map a NO-anchored structure finding (band or outright) onto the unified schema. SPECULATIVE / opt-in:
    self-assigns ``bucket="no_structure"`` + ``exec_gap_c=None`` so it NEVER enters _rank_key / Actionable.
    A BAND carries the same containment fields as a risk-budget row (so the conditional/breakeven viewmodel
    helpers work unchanged); an OUTRIGHT is single-leg (no parent — its display/containment fields stay
    None). The convex worst/best per-unit profit drive the section's max-loss / breakeven columns."""
    is_band = r.get("kind") == "band"
    d = {
        "sport": cfg.sport_id, "sport_label": cfg.label, "source": "no_structure",
        "name": r.get("player") or "",
        "detail": (f"{r.get('parent_node')} ⊇ {r.get('child_node')}" if is_band
                   else (r.get("contract") or "")),
        "tournament": r.get("tournament") or "", "tour": r.get("tour") or "",
        "action_1_text": r.get("action_1_text") or "", "action_2_text": r.get("action_2_text") or "",
        "action_1_price_c": _num(r.get("action_1_price_c")), "action_2_price_c": _num(r.get("action_2_price_c")),
        "cost_c": _num(r.get("cost_c")),
        # NEVER an executable edge — exec_gap_c=None floors it within its own opt-in section.
        "exec_gap_c": None, "exec_min_size": _num(r.get("exec_min_size")), "exec_max_profit_dollars": None,
        "bucket": "no_structure", "status": r.get("status") or "",
        "tradable_now": "Speculative", "blocked_reason": "",
        "market_status": r.get("market_status") or "active", "rule_flag": "",
        "settlement_caveat": r.get("settlement_caveat") or "",
        "participant_key": r.get("player_key") or "",
        "relationship_type": "no_structure_band" if is_band else "no_structure_outright",
        # A band is a sequential broader→deeper pair (Calendar); an outright is a single leg (Calendar).
        "resolution_mode": "calendar",
        "opportunity_id": r.get("opportunity_id") or "",
        "ticker_1": (r.get("parent_ticker") if is_band else r.get("ticker")) or "",
        "ticker_2": (r.get("child_ticker") if is_band else "") or "",
        "url": (r.get("parent_url") if is_band else r.get("url")) or "",
        "url_2": (r.get("child_url") if is_band else "") or "",
        "legs": None, "n_legs": None,                  # synthesized into a leg list by _finalize_unified
        # Convex payoff bounds (drive max-loss / breakeven / upside columns); not a risk-budget edge_class.
        "edge_class": "", "worst_case_profit_c": _num(r.get("worst_case_profit_c")),
        "best_case_profit_c": _num(r.get("best_case_profit_c")),
        # Probability-context display outrights — present for bands, None for single-leg outrights.
        "parent_display_c": _num(r.get("parent_display_c")), "child_display_c": _num(r.get("child_display_c")),
        "display_spread_c": _num(r.get("display_spread_c")),
        "spread_over_parent": _num(r.get("spread_over_parent")), "spread_over_child": _num(r.get("spread_over_child")),
        "parent_yes_bid_c": _num(r.get("parent_yes_bid_c")), "child_yes_ask_c": _num(r.get("child_yes_ask_c")),
        "child_node": r.get("child_node") or "", "parent_node": r.get("parent_node") or "",
        "comp_quote_quality": r.get("comp_quote_quality") or "",
    }
    d["participant_keys"], d["participant_labels"] = _participants([(r.get("player_key"), r.get("player"))])
    # A band's broader-YES + deeper-NO guarantees ≥100¢ in every settled state (floor 100); an outright NO
    # has no guaranteed floor (pays 100 only if the outcome fails).
    return _finalize_unified(d, payout_floor_c=(100 if is_band else None))


def _rank_key(row: dict[str, Any]) -> tuple:
    """Actionable first, then largest gross edge (¢), then a stable id tiebreak."""
    bp = BUCKET_PRIORITY.get(row.get("bucket"), 99)
    gap = row.get("exec_gap_c")
    gap = gap if isinstance(gap, (int, float)) and gap == gap else float("-inf")
    return (bp, -gap, row.get("opportunity_id") or "")


def unified_opportunities(
    fetch_fn: Callable[[str], "pd.DataFrame | None"],
    *,
    store_writer: Callable[[Any, "pd.DataFrame"], Any] | None = None,
    fetched_at: Any = None,
    frames_out: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Aggregate opportunities across every registered sport into one ranked frame.

    `fetch_fn(sport_id)` returns that sport's per-player contract DataFrame (injected — the app passes
    its cached `load_contracts`, tests pass a stub). Each sport is processed independently; a fetch or
    processing error for one sport is recorded and skipped (never blanks the others). If `store_writer`
    is given, the scan is persisted once via `store_writer(fetched_at, frame)` (the app wires this to
    `store.write_snapshot`; tests inject a tmp-db writer or omit it).

    When `frames_out` (a list) is given, the per-sport EVIDENCE frames behind the opportunities are
    appended to it as `{sport, frame_type, schema_version, rows}` for `frame_type` ∈
    {contracts, checks, dutchbook} (empties skipped) — the caller persists them via the v3
    `store.write_snapshot(frames=…)` (PR 21a). Out-param (not a return value) so the 2-tuple return and
    every existing caller stay unchanged.

    Returns `(unified_df, per_sport_errors)` where each error is `{"sport": id, "error": msg}`.
    """
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for cfg in sports.all_sports():
        try:
            contracts = fetch_fn(cfg.sport_id)
        except Exception as exc:  # a single sport's fetch must never blank the whole scan
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        if contracts is None or getattr(contracts, "empty", False):
            continue
        try:
            records = contracts.to_dict("records")
            # "Beyond the strict rule" (PR 29): always compute the FULL opt-in bands so every scan persists
            # risk-budget + near-miss candidates; the NiceGUI UI filters them live (no rescan on a control move).
            checks = consistency.build_checks(contracts, risk_budget_max_loss_c=config.RISK_BUDGET_MAX_LOSS_C)
            checks_records = checks.to_dict("records")
            books = dutchbook.find_dutch_books(records, near_miss_max_over_c=config.NEAR_MISS_MAX_OVER_C)
            baskets = dutchbook.find_group_baskets(records)
            bundles = synthetic_bundle.find_synthetic_bundles(records)
            exact_orders = exact_order.find_exact_order_premiums(records)
            game_signals = game_support.find_game_support_signals(
                records, strong_score_c=config.WC_SUPPORT_SCORE_STRONG_C,
                qualifier_band_c=config.WC_QUALIFIER_BAND_C)
            stage_books = stage_elim.find_stage_elim_books(records)
            stage_synths = stage_elim.find_stage_elim_synthetics(records)
            no_structs = no_structures.find_no_structures(records)
        except Exception as exc:
            errors.append({"sport": cfg.sport_id, "error": str(exc)})
            continue
        rows.extend(_to_unified_consistency(r, cfg) for r in checks_records)
        rows.extend(_to_unified_dutchbook(r, cfg) for r in books)
        rows.extend(_to_unified_group_basket(r, cfg) for r in baskets)
        rows.extend(_to_unified_synthetic(r, cfg) for r in bundles)
        rows.extend(_to_unified_exact_order(r, cfg) for r in exact_orders)
        rows.extend(_to_unified_game_support(r, cfg) for r in game_signals)
        rows.extend(_to_unified_stage_elim_book(r, cfg) for r in stage_books)
        rows.extend(_to_unified_stage_elim_synth(r, cfg) for r in stage_synths)
        rows.extend(_to_unified_no_structure(r, cfg) for r in no_structs)
        if frames_out is not None:
            for frame_type, frame_rows in (("contracts", records), ("checks", checks_records),
                                           ("dutchbook", books), ("group_basket", baskets)):
                if frame_rows:
                    frames_out.append({"sport": cfg.sport_id, "frame_type": frame_type,
                                       "schema_version": 1, "rows": frame_rows})

    rows.sort(key=_rank_key)
    unified = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)

    if store_writer is not None:
        store_writer(fetched_at, unified)
    return unified, errors


def run_scan(fetch_fn: Callable[[str], tuple], *, fetched_at: Any = None,
             request_count: Callable[[], int] | None = None,
             retry_stats: Callable[[], tuple[int, float]] | None = None
             ) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    """Fetch every sport, aggregate coverage, and produce the unified ranked frame — the service entry.

    `fetch_fn(sport_id)` returns the `fetch.fetch_contracts` 7-tuple
    `(df, _fetched_at, errors, n_scanned, n_loaded, skipped_no_name, n_excluded_unknown)`. Returns
    `(unified_df, coverage, frames)` where `coverage` carries the scan-wide counts + per-series /
    per-sport errors (so `/coverage` is honest), and `frames` is the per-sport evidence to persist via
    `store.write_snapshot(frames=…)`. `request_count` is an injected no-arg counter (e.g.
    `kalshi_client.request_count`) read before/after so coverage carries the Kalshi `kalshi_requests`
    issued this scan — injected (not imported) so the scanner stays network-free. Pure: fetch injected,
    no store, no network. A per-sport fetch failure is recorded and that sport contributes nothing.
    """
    before = request_count() if request_count else None
    retry_before = retry_stats() if retry_stats else None   # Phase 0: (count, seconds) read before/after
    sport_cfgs = list(sports.all_sports())

    def _fetch_one(sid: str) -> tuple[str, tuple | None, str | None, float]:
        """Fetch one sport off the pool. Never raises — a failure is returned as the error string so the
        pool can't blank the scan. Returns (sid, result_tuple_or_None, error_or_None, elapsed_seconds)."""
        t0 = time.monotonic()
        try:
            return sid, fetch_fn(sid), None, time.monotonic() - t0
        except Exception as exc:   # a single sport's fetch failure must not blank the scan
            return sid, None, str(exc), time.monotonic() - t0

    # Fetch sports CONCURRENTLY (PR perf/parallel-sport-fetch): each sport still fans out across its
    # series internally and the process-wide MAX_RPS throttle still caps total issuance, so this only
    # fills the idle gaps between sports (no extra Kalshi requests). `pool.map` preserves input order;
    # we key results by sport and aggregate below in sports.all_sports() order, so output is
    # DETERMINISTIC regardless of completion order. SPORT_FETCH_CONCURRENCY=1 == the old serial scan.
    workers = max(1, min(len(sport_cfgs), config.SPORT_FETCH_CONCURRENCY))
    if workers == 1:
        fetched = [_fetch_one(cfg.sport_id) for cfg in sport_cfgs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = list(pool.map(lambda c: _fetch_one(c.sport_id), sport_cfgs))
    by_sport = {sid: (res, err, secs) for sid, res, err, secs in fetched}

    dfs: dict[str, Any] = {}
    scanned = loaded = skipped = excluded = 0
    series_errors: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []
    fetch_status_by_sport: dict[str, dict[str, Any]] = {}
    for cfg in sport_cfgs:                       # aggregate in registered order -> deterministic
        sid = cfg.sport_id
        res, err, secs = by_sport[sid]
        fetch_ms = round(secs * 1000, 1)
        if err is not None:
            fetch_errors.append({"sport": sid, "error": err})
            fetch_status_by_sport[sid] = {"ok": False, "fetch_ms": fetch_ms, "error": err}
            continue
        df, _fa, errors, n_scanned, n_loaded, skipped_no_name, n_excluded = res
        dfs[sid] = df
        scanned += n_scanned
        loaded += n_loaded
        skipped += skipped_no_name
        excluded += n_excluded
        for s, msg in (errors or []):
            series_errors.append({"sport": sid, "series": s, "error": str(msg)})
        fetch_status_by_sport[sid] = {"ok": True, "fetch_ms": fetch_ms}

    # Reuse the pure aggregator over the already-fetched per-sport frames (it adds its own
    # per-sport PROCESSING errors — build_checks/find_dutch_books failures — to the set).
    frames: list[dict[str, Any]] = []
    unified, processing_errors = unified_opportunities(
        lambda sid: dfs.get(sid), fetched_at=fetched_at, frames_out=frames)

    # Two named volume counters, kept DISTINCT from the opportunity count (§ PR 19/21 meta).
    contracts_scanned = sum(len(f["rows"]) for f in frames if f["frame_type"] == "contracts")
    checks_tested = sum(len(f["rows"]) for f in frames if f["frame_type"] == "checks")
    coverage = {
        "fetched_at": fetched_at,
        "scanned": scanned, "loaded": loaded, "failed": len(series_errors), "excluded": excluded,
        "skipped_no_name": skipped,
        "contracts_scanned": contracts_scanned, "checks_tested": checks_tested,
        "sport_errors": fetch_errors + processing_errors,   # fetch-level + processing-level
        "series_errors": series_errors,
        "fetch_status_by_sport": fetch_status_by_sport,      # per-sport {ok, fetch_ms[, error]} timing
    }
    if before is not None:
        coverage["kalshi_requests"] = request_count() - before
    if retry_before is not None:
        rc_now, bs_now = retry_stats()
        coverage["retry_count"] = rc_now - retry_before[0]
        coverage["backoff_seconds_total"] = round(bs_now - retry_before[1], 2)
    return unified, coverage, frames
