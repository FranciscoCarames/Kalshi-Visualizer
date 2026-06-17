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
import sports
from data import opportunity_id, parse_fetched_at

NO_STRUCTURE_BAND = "NO_STRUCTURE_BAND"
NO_STRUCTURE_OUTRIGHT = "NO_STRUCTURE_OUTRIGHT"

# Books with no firm, two-sided order to anchor a Buy-NO / Buy-YES leg on.
_BAD_QUOTES = ("No quote", "Crossed", "One-sided")

# --- Settlement-level taxonomy (display-only) ---------------------------------------------------------
# Each cheap-NO finding is tagged with the SETTLEMENT LEVEL of the contract it fades — how many "grouping"
# levels it sits above a single contest — so the dashboard splits the watchlist into Event / Tournament /
# Championship tables (0/1/2). The level is declared PER SPORT in `SportConfig.family_levels`, keyed on the
# family (== row "kind", `data.py:646`), because the SAME family name means different things per sport: a
# tennis "match" is a single match (Event), but an NBA/NHL/WNBA "match" is the best-of-7 series
# (Tournament). A family absent from a sport's map is EXCLUDED (scope None) — fail-closed; the registry
# guard test forces a new family to be categorised. Pure display-only: never read by classify/bucket_of.
_LEVEL_SCOPE = {0: "event", 1: "tournament", 2: "championship"}


def scope_for(cfg, family: Any, stage: Any = None) -> str | None:
    """Settlement scope of a cheap-NO finding: ``"event" | "tournament" | "championship"``, or ``None``
    when the family is excluded/unmapped. Level = ``cfg.family_levels[family]`` (0=event, 1=tournament,
    2=championship). When a family SPANS levels by stage (team-sport ``advance``: "Reach Playoffs" is a
    regular-season qualification = tournament, but conference/title rungs = championship) its value is a
    ``dict[stage, level]`` with a ``"*"`` default; the ``stage`` is whitespace-normalised before lookup. A
    band passes its DEEPER child rung's family + stage (it fades that rung → inherits its level)."""
    lvl = (getattr(cfg, "family_levels", None) or {}).get(str(family or ""))
    if isinstance(lvl, dict):
        lvl = lvl.get(str(stage or "").strip(), lvl.get("*"))
    return _LEVEL_SCOPE.get(lvl)


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
        # Ladder-shape triage metrics (display-only, additive — NEVER read by classify/bucket_of/_rank_key).
        # Computed once per participant ladder; describes the linear ladder this band sits in so the SPA can
        # filter cheap-NO bands by how deep the ladder runs and how cheap its bottom rung is.
        #   steps  = count of PRESENT (priced) rungs in the broad→deep node_order (side-branch leaves excluded)
        #   bottom = display ¢ of the DEEPEST present rung (the most specific outcome, e.g. "win tournament")
        #   ratio  = bottom ÷ steps (the owner's "bottom of the ladder divided by the number of steps")
        _present = [n for n in ladder.node_order if consistency.representative(nodes.get(n)) is not None]
        _steps = len(_present)
        _bottom_rep = consistency.representative(nodes.get(_present[-1])) if _present else None
        _bottom_c = consistency._disp_c(_bottom_rep) if _bottom_rep is not None else None
        _ratio = round(_bottom_c / _steps, 2) if (_bottom_c is not None and _steps) else None
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
                                   _min_size(parent_ask_size, child_no_size),
                                   ladder_steps=_steps, ladder_bottom_c=_bottom_c, ladder_step_ratio=_ratio))
    return out


def _build_band(cfg, player_key: str, tournament: str, child_node: str, parent_node: str,
                child: dict[str, Any], parent: dict[str, Any], parent_ask: int, child_no: int,
                cost: int, max_loss: int, units: Any, *, ladder_steps: int | None = None,
                ladder_bottom_c: float | None = None, ladder_step_ratio: float | None = None) -> dict[str, Any]:
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
        # A NO-fade band is classified by its faded DEEPER (child) NO leg — that rung is the risk thesis.
        # Pass the child's stage too so a team "Reach Playoffs" child → tournament, "Win Conference" → championship.
        "scope": scope_for(cfg, child.get("kind"), child.get("stage")),
        # Faded leg's ladder node + display price → "Cheapness vs field" (compares this leg vs the field
        # de-vig at the same node). The band fades the child, so its node/display is the child's.
        "faded_node": child_node, "faded_display_c": consistency._disp_c(child),
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
        # Ladder-shape triage metrics (display-only; see _band_findings). None on outright fades (no ladder).
        "ladder_steps": ladder_steps, "ladder_bottom_c": ladder_bottom_c, "ladder_step_ratio": ladder_step_ratio,
        "settlement_caveat": caveat,
        "market_status": "active",
        # Display-only: the band's full hold resolves at the LATER of its two legs (capital-lock-up horizon).
        "close_time": _later_close(parent.get("close_time"), child.get("close_time")),
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
        # Settlement scope from the faded contract's family (None for excluded prop/other — the row still
        # EMITS so audit/API/export keep the evidence; only the display tables drop scope-None rows).
        cfg = sports.sport_for_series(r.get("series"))
        scope = scope_for(cfg, r.get("kind"), r.get("stage"))
        out.append({
            "kind": "outright",
            "scope": scope,
            # Faded leg's ladder node + display price → "Cheapness vs field" (None node when non-laddered).
            "faded_node": consistency.node_of(r) or "", "faded_display_c": consistency._disp_c(r),
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
            "close_time": r.get("close_time") or "",       # display-only capital-lock-up horizon
            "ticker": ticker, "url": r.get("kalshi_url") or "",
            "opportunity_id": opportunity_id("no_structure_outright", ticker),
        })
    return out


# --- small shared helpers -----------------------------------------------------------------------------
def _min_size(a: Any, b: Any) -> Any:
    a, b = _num(a), _num(b)
    return min(a, b) if (a is not None and b is not None) else None


def _later_close(a: Any, b: Any) -> str:
    """The LATER of two raw ISO close-time strings (a band's full capital-lock-up horizon resolves at the
    later leg). Parses both via ``data.parse_fetched_at``; returns the later parseable one's ORIGINAL
    string, the only parseable one, or "" when neither parses. Display-only metadata, never a comparison."""
    da, db = parse_fetched_at(a), parse_fetched_at(b)
    if da and db:
        return str(a) if da >= db else str(b)
    if da:
        return str(a)
    if db:
        return str(b)
    return ""


def _buy_text(side: str, contract: Any, price_c: Any) -> str:
    word = "Buy YES" if side == "buy_yes" else "Buy NO"
    price = f"{int(price_c)}¢" if price_c is not None else "—"
    return f"{word} — {contract or '—'} @ {price}"
