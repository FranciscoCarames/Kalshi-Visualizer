"""NO-anchored structures — "Cheap bounded-loss NO fades" detector (pure; no UI, no network).

A SPECULATIVE, opt-in, NEVER-actionable family: cheap convex fades anchored on a Buy-NO leg. Two tiers:

- **BAND** (`NO_STRUCTURE_BAND`): Buy NO on the deeper (child) ladder rung + Buy YES on the broader
  (parent) rung that CONTAINS it. A defined-risk band — it pays an extra $1 in the "reaches the broader
  stage but NOT the deeper one" window, and the loss is capped at ``cost − 100¢``. Emitted only when
  ``cost ≥ 100`` (a ``cost < 100`` band is exactly the strict ``EXECUTABLE_VIOLATION`` the consistency
  checker already owns — ``cost = parent_yes_ask + child_no_ask`` and on Kalshi's unified book
  ``child_no_ask = 100 − child_yes_bid``, so ``cost < 100 ⟺ child_yes_bid > parent_yes_ask``) and the
  bounded max-loss ≤ ``config.NO_STRUCTURE_BAND_MAX_LOSS_C``. ``cost == 100`` IS emitted (gap exactly 0 is
  CLEAN, not a strict cross) with ``max_loss = 0`` and a fees/slippage caveat — never sold as free money.

- **OUTRIGHT** (`NO_STRUCTURE_OUTRIGHT`): a single Buy NO — a directional fade WATCHLIST, never framed as
  an edge. Emitted only when the Buy-NO cost ≤ ``config.NO_STRUCTURE_OUTRIGHT_MAX_C`` so all-sport cheap
  NOs (obvious favourites) don't flood the store.

These are NOT edge, NOT arbitrage: a cheap NO is cheap because the market thinks the YES is very likely.
The number it ranks on is the bounded downside / breakeven, never an edge. Gross, top-of-book,
uncalibrated. The detector self-assigns ``bucket="no_structure"`` and ``exec_gap_c=None`` so a finding
NEVER enters the executable edge rank / Actionable.

Reuses the consistency checker's building blocks (ladder grouping, representative selection, Buy-NO price,
display-outright helpers) — payoff math is the trivial 3-state containment band, computed once here and
mirrored by ``consistency.scenario_payoffs`` for the detail panel. Imports ``consistency`` (which imports
pandas), so this module is pure in the no-UI / no-network sense, NOT pandas-free.
"""
from __future__ import annotations

from typing import Any

import config
import consistency
from data import opportunity_id

NO_STRUCTURE_BAND = "NO_STRUCTURE_BAND"
NO_STRUCTURE_OUTRIGHT = "NO_STRUCTURE_OUTRIGHT"

# Books with no firm, two-sided order to anchor a Buy-NO / Buy-YES leg on.
_BAD_QUOTES = ("No quote", "Crossed", "One-sided")


def _isna(x: Any) -> bool:
    """True for None or float NaN (a None price round-trips to NaN through pandas)."""
    return x is None or (isinstance(x, float) and x != x)


def _num(x: Any) -> Any:
    return None if _isna(x) else x


def _pos(size: Any) -> bool:
    return size is not None and not _isna(size) and size > 0


def _firm(row: dict[str, Any]) -> bool:
    """A leg we can actually anchor on: a real two-sided book, active, whole-cent (not subpenny)."""
    return (str(row.get("quote_quality") or "") not in _BAD_QUOTES
            and str(row.get("status") or "") == "active"
            and not bool(row.get("subpenny")))


def find_no_structures(rows: list[dict[str, Any]], _diag: dict | None = None) -> list[dict[str, Any]]:
    """All NO-anchored structures over ONE sport's contract records (as produced by
    ``data.build_contracts`` → ``df.to_dict("records")``). Returns a list of finding dicts (possibly
    empty). Deterministic order: bands first (cheapest max-loss first), then outright (cheapest NO first)."""
    bands = _band_findings(rows or [])
    outrights = _outright_findings(rows or [])
    bands.sort(key=lambda f: (f["max_loss_c"], f.get("opportunity_id") or ""))
    outrights.sort(key=lambda f: (f["buy_no_c"], f.get("opportunity_id") or ""))
    return bands + outrights


# --- Tier 1: bounded NO bands (Buy NO child + Buy YES parent) ------------------------------------------
def _band_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # Group one sport's contracts by (player_key, tournament) exactly as consistency.build_checks does, so a
    # band only spans rungs of the SAME participant in the SAME tournament. Drop subpenny rows up front (their
    # cents are rounded → never a trusted band leg) — mirrors build_checks.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("subpenny"):
            continue
        groups.setdefault((str(r.get("player_key") or ""), str(r.get("tournament") or "")), []).append(r)

    for (player_key, tournament), grp in groups.items():
        if not player_key:
            continue
        cfg = consistency._sport_for_rows(grp)
        nodes = consistency.build_player_nodes(grp)
        if not nodes:
            continue
        ladder = cfg.ladder_for(grp)
        for child_node, parent_node in ladder.adjacent_pairs:    # (deeper, broader)
            child = consistency.representative(nodes.get(child_node))
            parent = consistency.representative(nodes.get(parent_node))
            if child is None or parent is None or not _firm(child) or not _firm(parent):
                continue
            # Buy YES the broader (parent) at its ask; Buy NO the deeper (child) at the NO ask. The Buy-NO
            # leg's tradable size is the child's YES bid size (no NO-side sizes on Kalshi's unified book).
            parent_ask, parent_ask_size = consistency._leg(parent, "ask")
            child_no = consistency._buy_no_c(child)
            child_no_size = child.get("yes_bid_size")
            if (parent_ask is None or child_no is None
                    or not _pos(parent_ask_size) or not _pos(child_no_size)):
                continue
            cost = parent_ask + child_no
            if cost < 100:               # a sub-100¢ band is a STRICT executable cross — owned by consistency
                continue
            max_loss = cost - 100
            if max_loss > config.NO_STRUCTURE_BAND_MAX_LOSS_C:
                continue
            out.append(_build_band(cfg, player_key, tournament, child_node, parent_node,
                                   child, parent, parent_ask, child_no, cost, max_loss,
                                   _min_size(parent_ask_size, child_no_size)))
    return out


def _build_band(cfg, player_key: str, tournament: str, child_node: str, parent_node: str,
                child: dict[str, Any], parent: dict[str, Any], parent_ask: int, child_no: int,
                cost: int, max_loss: int, units: Any) -> dict[str, Any]:
    """Assemble one band finding. The 3-state containment band: two states return 100¢ (profit 100−cost =
    −max_loss), the 'reaches broader, not deeper' state pays 200¢ (profit 200−cost). worst/best mirror
    ``consistency.scenario_payoffs`` (reused by the detail panel)."""
    worst = 100 - cost                                   # the two non-band states (= −max_loss)
    best = 200 - cost                                    # the band ("reaches broader, not deeper") state
    quote = consistency._worst_quality(str(child.get("quote_quality") or ""),
                                       str(parent.get("quote_quality") or ""))
    caveat = ""
    if cost == 100:
        caveat = ("gross zero-loss optionality — fees/slippage can turn it into a small net loss; "
                  "not free money")
    elif max_loss <= config.RISK_BUDGET_MAX_LOSS_C:
        caveat = "also surfaced as a risk-budget near-miss (the same bounded-loss trade, another lens)"
    return {
        "kind": "band",
        "status": NO_STRUCTURE_BAND,
        "player": parent.get("player") or child.get("player") or "",
        "player_key": player_key,
        "tournament": tournament,
        "tour": parent.get("tour") or child.get("tour") or "",
        "child_node": child_node, "parent_node": parent_node,
        # Buy YES the broader (parent) — leg 1; Buy NO the deeper (child) — leg 2.
        "action_1_text": _buy_text("buy_yes", parent.get("contract"), parent_ask),
        "action_1_side": "buy_yes", "action_1_contract": parent.get("contract") or "",
        "action_1_price_c": parent_ask,
        "action_2_text": _buy_text("buy_no", child.get("contract"), child_no),
        "action_2_side": "buy_no", "action_2_contract": child.get("contract") or "",
        "action_2_price_c": child_no,
        "buy_no_c": child_no,
        "cost_c": cost, "max_loss_c": max_loss,
        "worst_case_profit_c": worst, "best_case_profit_c": best,
        "exec_min_size": _num(units),
        "comp_quote_quality": quote,
        # Display-outright probability context (reused by the conditional / breakeven viewmodel helpers).
        "parent_display_c": consistency._disp_c(parent),
        "child_display_c": consistency._disp_c(child),
        "display_spread_c": consistency._disp_spread(parent, child),
        "spread_over_parent": consistency._disp_ratio(parent, child, "parent"),
        "spread_over_child": consistency._disp_ratio(parent, child, "child"),
        "parent_yes_bid_c": _num(parent.get("yes_bid_c")),
        "child_yes_ask_c": _num(child.get("yes_ask_c")),
        "settlement_caveat": caveat,
        "market_status": "active",
        "parent_ticker": parent.get("market_ticker") or "", "child_ticker": child.get("market_ticker") or "",
        "parent_url": parent.get("kalshi_url") or "", "child_url": child.get("kalshi_url") or "",
        "opportunity_id": opportunity_id("no_structure_band", player_key, tournament, child_node, parent_node),
    }


# --- Tier 2: cheap NO outright (single Buy-NO, directional fade watchlist) -----------------------------
def _outright_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not _firm(r):
            continue
        if not _pos(r.get("yes_bid_size")):              # the Buy-NO leg's tradable size
            continue
        buy_no = consistency._buy_no_c(r)
        if buy_no is None or buy_no <= 0 or buy_no > config.NO_STRUCTURE_OUTRIGHT_MAX_C:
            continue
        ticker = r.get("market_ticker") or ""
        out.append({
            "kind": "outright",
            "status": NO_STRUCTURE_OUTRIGHT,
            "player": r.get("player") or "", "player_key": str(r.get("player_key") or ""),
            "tournament": str(r.get("tournament") or ""), "tour": r.get("tour") or "",
            "contract": r.get("contract") or "", "contract_kind": str(r.get("kind") or ""),
            "category": str(r.get("category") or ""),
            # Single Buy-NO leg (leg 2, mirroring the band's NO leg position); no Buy-YES bounding leg.
            "action_1_text": "", "action_1_side": None, "action_1_contract": "", "action_1_price_c": None,
            "action_2_text": _buy_text("buy_no", r.get("contract"), buy_no),
            "action_2_side": "buy_no", "action_2_contract": r.get("contract") or "", "action_2_price_c": buy_no,
            "buy_no_c": buy_no,
            "cost_c": buy_no, "max_loss_c": buy_no,
            # Pays 100¢ if the outcome FAILS (profit 100−cost), 0¢ if it happens (profit −cost). No floor.
            "worst_case_profit_c": -buy_no, "best_case_profit_c": 100 - buy_no,
            "exec_min_size": _num(r.get("yes_bid_size")),
            "comp_quote_quality": str(r.get("quote_quality") or ""),
            "market_status": "active",
            "ticker": ticker, "url": r.get("kalshi_url") or "",
            "opportunity_id": opportunity_id("no_structure_outright", ticker),
        })
    return out


# --- small shared helpers -----------------------------------------------------------------------------
def _min_size(a: Any, b: Any) -> Any:
    a, b = _num(a), _num(b)
    return min(a, b) if (a is not None and b is not None) else None


def _buy_text(side: str, contract: Any, price_c: Any) -> str:
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract or '—'} @ {price}"
