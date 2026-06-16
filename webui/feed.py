"""Terminal-feed adapter — a DENORMALIZED, read-only VIEW of the latest snapshot for the Terminal Pro SPA.

This is the single backend surface the React workstation (`/terminal`) reads. It is deliberately NOT a
second engine (see the plan's PRIME INVARIANT): it re-presents `store.latest()` through the existing
`webui.viewmodel` row builders and adds a handful of DISPLAY-ONLY fields the terminal shows. It must never
re-derive `bucket` / `status` / `tradable_now` / `rule_flag` / actionability — those are copied verbatim
from the engine's opportunity rows — and it must never mutate the input opportunities or feed back into
`scanner` / `consistency._classify` / ranking.

Lifted from the one-off `_export_mockup_data.py` (which produced the mockup's static `tp-final-data.js`),
turned into a pure, testable function so a live API route can serve it. The transform is pure: same
snapshot in -> same `{meta, opps[]}` out, no side effects, no clock, no IO beyond the caller's
`store.latest()`.

Layers used (all UI-free, so `api.py` can import this without a cycle): `store` (snapshot read) and
`webui.viewmodel` (the pure display-row builders). Does NOT import `webui.engine` (which imports `api`).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import config
import data
import store
import webui.viewmodel as vm


def _band_defaults() -> dict[str, int]:
    """The old-dashboard band-control defaults, single-sourced from config so the SPA SecBar never drifts
    (bounded max-loss 5¢, near-miss overpay 3¢, cheap-NO max-loss 15¢, cheap-NO max-Buy-NO 15¢)."""
    return {
        "bounded_max_loss_c": int(config.RISK_BUDGET_DEFAULT_MAX_LOSS_C),
        "nearmiss_overpay_c": int(config.NEAR_MISS_DEFAULT_OVER_C),
        "cheapno_max_loss_c": int(config.NO_STRUCTURE_DEFAULT_MAX_LOSS_C),
        "cheapno_max_buy_no_c": int(config.NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C),
    }

# bucket -> (zone, section-key). Mirrors the engine's bucket set; diagnostic buckets collapse to one
# "diag" section. An unknown bucket falls back to diag (never silently dropped).
_SEC: dict[str, tuple[str, str]] = {
    "actionable": ("exec", "act"), "review_signal": ("exec", "rev"), "blocked": ("exec", "blk"),
    "risk_budget": ("spec", "bounded"), "near_miss": ("spec", "nearmiss"),
    "qualifier_setup": ("spec", "qual"), "no_structure": ("spec", "cheapno"),
    "data_quality": ("diag", "diag"), "display_signal": ("diag", "diag"),
    "wide_signal": ("diag", "diag"), "near_edge": ("diag", "diag"), "clean": ("diag", "diag"),
}
_EMPTY = (set(), {}, set())   # (new_ids, changes, flash_ids) the row builders accept


def _clean(r: dict[str, Any]) -> dict[str, Any]:
    """Drop the private `_`-prefixed display helpers (severity tags etc.) the SPA doesn't consume."""
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _num(x: Any) -> float | None:
    """A JSON-safe float, or None for None/blank/NaN/non-numeric (so the SPA renders '—', never crashes).
    Coerces Decimal cents to float — the wire format is plain JSON numbers."""
    try:
        if x is None or x == "":
            return None
        f = float(x)
        return None if f != f else round(f, 4)   # NaN-safe
    except (TypeError, ValueError):
        return None


def _leg_deep_link(url: str | None, ticker: str | None, side: str | None) -> str | None:
    """Per-participant + per-side Kalshi deep link (owner-confirmed format):
    ``<event_url>?op_market_ticker=<FULL_TICKER>&op_order_side=<yes|no>`` — opens the exact contract with the
    buy side preselected. The engine is BUY-ONLY, so the side is always the buy's yes/no (never a sell).
    Falls back to the bare event url when the ticker is missing (keeps the link working). Does NOT touch
    ``data.kalshi_url`` (the event url stays canonical for link_audit)."""
    if not url or not ticker:
        return url
    side_param = "yes" if "yes" in (side or "").lower() else "no"
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}op_market_ticker={ticker}&op_order_side={side_param}"


def _trim_legs(o: dict[str, Any]) -> list[dict[str, Any]]:
    """The opportunity's legs, trimmed to the fields the ladder/trade-card need (read-only, ≤24 legs).
    Each leg's ``u`` is the per-participant + per-side deep link (see ``_leg_deep_link``).

    Ticker reconciliation (so the depth ladder can load a book wherever one EXISTS): a leg may carry an
    empty ``tk`` even though the row holds the real market ticker in a positional slot — notably the
    cheap-NO OUTRIGHT, whose market sits in ``ticker_1`` while its only action is ``action_2`` (Buy-NO), so
    the synthesized leg lands in slot 2 with an empty ticker. We (1) fill an existing action leg's empty
    ``tk`` from an unused positional ticker (the leg stays a real trade leg — just gains its book), and
    (2) append any STILL-unused positional ticker as a BOOK-ONLY pseudo-leg (``bo: True``, never an
    executable instruction — e.g. the deeper child market of a single-sided containment row). Display-only;
    no engine change."""
    legs = (o.get("legs") or [])[:24]
    have = {str(leg.get("ticker") or "") for leg in legs if leg.get("ticker")}
    spare = [t for t in (o.get("ticker_1"), o.get("ticker_2"),
                         o.get("parent_ticker"), o.get("child_ticker"))
             if t and str(t) not in have]           # positional tickers no leg represents, in priority order
    si = 0
    out: list[dict[str, Any]] = []
    for leg in legs:
        tk = leg.get("ticker") or ""
        if not tk and si < len(spare):              # (1) backfill an existing leg's missing book ticker
            tk = spare[si]
            si += 1
        out.append({"side": leg.get("side"), "c": leg.get("contract"), "p": _num(leg.get("price_c")),
                    "sz": _num(leg.get("size")) or 0, "tk": tk, "bo": False,
                    "u": _leg_deep_link(leg.get("url"), tk, leg.get("side"))})
    for t in spare[si:]:                            # (2) book-only legs for any still-unused market ticker
        out.append({"side": "", "c": "", "p": None, "sz": 0, "tk": str(t), "bo": True,
                    "u": _leg_deep_link(o.get("url") or o.get("url_2"), str(t), None)})
    return out[:24]


def _cond_pair_with_reason(
        parent: float | None, child: float | None) -> tuple[float | None, float | None, str]:
    """SINGLE SOURCE for the display-only market-implied conditional P(deeper│reached) = child/parent over
    ONE like-for-like price pair (both display, or both firm). Returns ``(cond_child%, cond_success%,
    reason)``: a value pair with ``reason == ""`` when computable, or ``(None, None, <why>)`` when a guard
    trips. Guard ORDER (mirrored exactly by `_cond_pair`): missing parent → missing child → non-positive
    parent (empty book) → invalid child → inverted pair. The reason is a DISPLAY annotation only (so a bare
    "—" can say WHY); it never affects the numbers. Uncalibrated, gross, top-of-book, not fair value —
    never feeds classification/ranking."""
    if parent is None:
        return None, None, "no valid parent quote"
    if child is None:
        return None, None, "no valid child quote"
    if parent <= 0:
        return None, None, "empty book (no parent midpoint)"
    if child < 0:
        return None, None, "no valid child quote"
    if child > parent:
        return None, None, "inverted display (deeper above broader) — a display inconsistency, not a probability"
    child_pct = round(child / parent * 100, 1)
    return child_pct, round(100 - child_pct, 1), ""


def _cond_pair(parent: float | None, child: float | None) -> tuple[float | None, float | None]:
    """Value-only wrapper over `_cond_pair_with_reason` (unchanged contract for existing callers/tests)."""
    child_pct, success_pct, _ = _cond_pair_with_reason(parent, child)
    return child_pct, success_pct


def _ripeness(o: dict[str, Any]) -> float | None:
    """DISPLAY-ONLY 'ripeness' = parent display outright ÷ max loss ¢ — in-the-money chance per ¢ at risk
    (the bounded-loss sort lens). Computed here only; never a backend RANK_MODE. None when there's no
    bounded downside (no max loss) or no parent outright."""
    parent = _num(o.get("parent_display_c"))
    worst = _num(o.get("worst_case_profit_c"))
    cost = _num(o.get("cost_c"))
    max_loss = (-worst if (worst is not None and worst < 0)
                else (cost - 100 if (cost is not None and cost > 100) else None))
    if parent is None or not max_loss or max_loss <= 0:
        return None
    return round(parent / max_loss, 3)


# --- Per-leg fee resolution (DISPLAY-ONLY) -------------------------------------------
# Resolve each leg's effective fee from its market ticker: event override (GET /events/fee_changes) ->
# series fee (the /series object) -> general fallback. series/event are derived from the ticker the way
# the whole app identifies series (the prefix before the first '-'; the event is the ticker minus its
# final strike segment) — consistent with data.series_for_families / classification. NEVER feeds ranking.
def _series_of(ticker: str) -> str:
    return (ticker or "").split("-", 1)[0].upper()


def _event_of(ticker: str) -> str:
    t = ticker or ""
    return (t.rsplit("-", 1)[0] if "-" in t else t).upper()


def _leg_tickers(o: dict[str, Any]) -> list[str]:
    """Per-leg market tickers, aligned 1:1 with vm._leg_prices(o)."""
    legs = o.get("legs")
    if isinstance(legs, list) and legs:
        return [str(leg.get("ticker") or "") for leg in legs]
    return [str(o.get("ticker_1") or ""), str(o.get("ticker_2") or "")]


def _resolve_leg_coeffs(o: dict[str, Any], fee_rates: dict[str, Any],
                        overrides: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the per-leg `leg_coeffs` list net_of_fees consumes: effective fee_type/multiplier (event
    override -> series -> labeled fallback) resolved per leg, with per-field sources. When `fee_rates` is
    entirely absent (feature off / pre-fee snapshot) every leg uses the labeled general-rate fallback."""
    legs = o.get("legs")
    sides = ([leg.get("side") for leg in legs] if isinstance(legs, list) and legs
             else [o.get("action_1_side"), o.get("action_2_side")])
    out: list[dict[str, Any]] = []
    for tk, side in zip(_leg_tickers(o), sides):
        series, event = _series_of(tk), _event_of(tk)
        sm = (fee_rates or {}).get(series)
        ov = (overrides or {}).get(event) or {}
        ov_ft, ov_mult = ov.get("fee_type_override"), ov.get("fee_multiplier_override")
        if not fee_rates or (sm is None and not ov):       # no per-market data at all -> labeled fallback
            ft, mult, ft_src, mult_src = "quadratic_with_maker_fees", config.FEE_DEFAULT_MULTIPLIER, "fallback", "fallback"
        else:
            sm = sm or {}
            ft = ov_ft if ov_ft is not None else sm.get("fee_type")
            mult = ov_mult if ov_mult is not None else sm.get("fee_multiplier")
            ft_src = "event" if ov_ft is not None else ("series" if sm.get("fee_type") is not None else "unknown")
            mult_src = "event" if ov_mult is not None else ("series" if sm.get("fee_multiplier") is not None else "fallback")
        ec = vm.effective_coeffs(ft, mult)
        out.append({"taker": ec["taker"], "maker": ec["maker"], "status": ec["status"],
                    "fee_type": ft, "fee_multiplier": mult, "fee_type_source": ft_src,
                    "fee_multiplier_source": mult_src, "series_ticker": series,
                    "event_ticker": event, "side": side})
    return out


def _build_row(o: dict[str, Any], fee_rates: dict[str, Any] | None = None,
               overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """One opportunity -> one denormalized terminal row. Pure; never mutates `o`. The engine's verbatim
    fields (bucket/status/tradable/rule) are copied as-is; the only NEW fields are display-only."""
    bucket = o.get("bucket")
    zone, sec = _SEC.get(bucket, ("diag", "diag"))
    try:
        if bucket == "risk_budget":
            base = _clean(vm.risk_budget_row(o, *_EMPTY))
        elif bucket == "near_miss":
            base = _clean(vm.near_miss_row(o, *_EMPTY))
        elif bucket == "no_structure":
            base = _clean(vm.no_structure_row(o, *_EMPTY))
        elif bucket == "qualifier_setup":
            base = _clean(vm.qualifier_row(o, *_EMPTY))
        else:
            base = _clean(vm.opp_row(o, set(), {}, set()))
    except Exception as e:                         # a row builder must never sink the whole feed
        base = {"name": o.get("name"), "sport": o.get("sport_label"), "caveat": f"(row err: {e})"}
    leg_coeffs = _resolve_leg_coeffs(o, fee_rates or {}, overrides or {})
    nf = vm.net_of_fees(o, leg_coeffs=leg_coeffs)   # DISPLAY-ONLY estimate (two scenarios; never ranks)
    # Conditional P(deeper│reached) on TWO bases, both display-only / gross / uncalibrated (never rank):
    #   • display — the dashboard's display price (midpoint when the spread is reasonable, else last trade);
    #   • firm — the executable bid/ask. For risk-budget rows the row builder already emits the display
    #     pair (`cond_child`/`cond_success`) from the engine's own fields, so we keep those VERBATIM (exact
    #     old-dashboard parity, never a re-derivation); other containment buckets get a derived display pair
    #     for the Inspector only. Both bases share the same guarded `_cond_pair` (impossible values closed).
    pdisp, cdisp = _num(o.get("parent_display_c")), _num(o.get("child_display_c"))
    pbid, cask = _num(o.get("parent_yes_bid_c")), _num(o.get("child_yes_ask_c"))
    cc_disp, cs_disp, cond_reason = _cond_pair_with_reason(pdisp, cdisp)
    cond_child = base["cond_child"] if "cond_child" in base else cc_disp
    cond_success = base["cond_success"] if "cond_success" in base else cs_disp
    cond_child_firm, cond_success_firm, cond_reason_firm = _cond_pair_with_reason(pbid, cask)
    base.update({
        "id": o["opportunity_id"], "bucket": bucket, "zone": zone, "section": sec,
        "scope": o.get("no_structure_scope"), "resolution_mode": o.get("resolution_mode"),
        "sport": o.get("sport_label") or base.get("sport"),
        # Routing keys the Inspector passes to GET /api/terminal/detail|ladder (read-only passthroughs;
        # NOT display values). sport_key is the registry id ("tennis"/"nba"), distinct from `sport` label.
        "sport_key": o.get("sport"), "player_key": o.get("participant_key"),
        "tournament": o.get("tournament") or "",
        "sub": o.get("tournament") or base.get("detail") or "",
        "status": o.get("status"), "tradable": o.get("tradable_now") or base.get("tradable"),
        "rule": o.get("rule_flag"), "settlement_caveat": o.get("settlement_caveat"),
        "blk": o.get("blocked_reason"),
        "legs": _trim_legs(o),
        "nlegs": int(o["n_legs"]) if _num(o.get("n_legs")) else len(o.get("legs") or []),
        "url": o.get("url"), "url2": o.get("url_2"),
        "pnode": o.get("parent_node"), "cnode": o.get("child_node"),
        "pbid": pbid, "cask": cask, "pdisp": pdisp, "cdisp": cdisp,
        # DISPLAY-ONLY derived fields (computed in this adapter only — never in the engine). The firm-basis
        # conditional is a DIAGNOSTIC, NOT an executable edge — do not feed it into ranking/classification.
        "cond_child": cond_child, "cond_success": cond_success,
        "cond_child_firm": cond_child_firm, "cond_success_firm": cond_success_firm,
        # DISPLAY-ONLY: why a conditional is blank ("" when a number is shown), so the Inspector can explain
        # the dash instead of leaving it opaque. The display reason describes the cond_child/cond_success
        # pair; for risk-budget rows that pair is the engine's verbatim value (same inputs → same reason).
        "cond_reason": cond_reason, "cond_reason_firm": cond_reason_firm,
        "parent_over_maxloss": _ripeness(o),
        # Fees: TWO execution scenarios (taker=immediate-fill primary, maker=resting-order). Display-only,
        # per-leg (event override -> series -> fallback), never ranks. `fees`/`net_edge`/`net_profit` keep
        # the taker (primary) value for back-compat with existing consumers.
        "fees": nf.get("total_fees_c"), "net_edge": nf.get("net_edge_c"),
        "net_profit": nf.get("net_profit_dollars"),
        "fees_taker": nf.get("total_fees_taker_c"), "fees_maker": nf.get("total_fees_maker_c"),
        "net_edge_maker": nf.get("net_edge_maker_c"), "net_profit_maker": nf.get("net_profit_maker_dollars"),
        "fee_breakeven": nf.get("breakeven_c"), "fee_breakeven_approx": nf.get("breakeven_approx"),
        "taker_complete": nf.get("taker_complete"), "maker_complete": nf.get("maker_complete"),
        "fee_source": nf.get("fee_source"), "fee_legs": nf.get("per_leg"),
        # DISPLAY-ONLY advisory: an Actionable row whose estimated TAKER (immediate-fill) fees meet/exceed
        # the gross edge at the executable size. Informational chip; never hides/demotes/re-ranks the row.
        "net_negative": (bucket == "actionable" and not nf.get("missing")
                         and nf.get("net_profit_dollars") is not None
                         and nf.get("net_profit_dollars") <= 0),
    })
    if isinstance(base.get("flags"), list):        # normalize the flags list -> a short string
        base["flags"] = " ".join(
            (f.get("label") if isinstance(f, dict) else str(f)) for f in base["flags"]) if base["flags"] else ""
    return base


def feed_from_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Pure transform: a snapshot dict -> ``{"meta": {...}, "opps": [...]}``. Preserves the engine's
    opportunity ORDER (the snapshot is already scanner-ranked — the SPA's default view), so the feed is a
    faithful 1:1 VIEW: every snapshot opportunity yields exactly one feed row, no re-sort, no re-bucket, no
    cap. Honest empty feed when there's no snapshot."""
    if not snap:
        return {"meta": {"snapshot_id": None, "fetched_at": None, "n_total": 0, "totals": {},
                         "sports": {}, "resolution_counts": {}, "scope_counts": {},
                         "defaults": _band_defaults()}, "opps": []}
    opps = snap.get("opportunities") or []
    meta = snap.get("meta") or {}
    fee_rates = meta.get("fee_rates") or {}
    overrides = meta.get("event_fee_overrides") or {}
    rows = [_build_row(o, fee_rates, overrides) for o in opps]
    res_counts = Counter((o.get("resolution_mode") or "?") for o in opps if o.get("bucket") == "risk_budget")
    scope_counts = Counter((o.get("no_structure_scope") or "other") for o in opps
                           if o.get("bucket") == "no_structure")
    feed_meta = {
        "snapshot_id": snap.get("snapshot_id"), "fetched_at": snap.get("fetched_at"), "n_total": len(opps),
        "contracts": meta.get("contracts_scanned"), "checks": meta.get("checks_tested"),
        "requests": meta.get("kalshi_requests"), "scanned": meta.get("scanned"),
        "failed": meta.get("failed"), "retry": meta.get("retry_count"),
        "totals": dict(Counter(o.get("bucket") for o in opps)),
        "sports": dict(Counter(o.get("sport_label") or o.get("sport") for o in opps)),
        "resolution_counts": dict(res_counts), "scope_counts": dict(scope_counts),
        "series_errors": meta.get("series_errors"),
        "defaults": _band_defaults(),
        # DISPLAY-ONLY fee provenance for the whole snapshot: ok/partial/fallback/failed/capped/disabled.
        "fee_data_status": meta.get("fee_data_status") or ("ok" if fee_rates else "fallback"),
    }
    return {"meta": feed_meta, "opps": rows}


def build_feed(db_path: str | None = None) -> dict[str, Any]:
    """The live terminal feed for the newest stored snapshot (read-only; same store the dashboard reads).

    Applies the Wave 1b staleness gate HERE (the live boundary, where the snapshot age is real) rather than
    inside the pure `feed_from_snapshot` transform — so the transform stays verbatim/unit-testable while the
    live feed downgrades `tradable_now` on a stale snapshot, using the SAME age + thresholds as api._opps so
    the feed ↔ /opportunities parity holds."""
    snap = store.latest(db_path=db_path)
    if snap:
        age = data.data_age_seconds(snap.get("fetched_at"))
        gated = data.gate_stale_tradability(snap.get("opportunities") or [], age,
                                            config.STALE_AFTER_SECONDS,
                                            by_sport=config.STALE_AFTER_SECONDS_BY_SPORT)
        snap = {**snap, "opportunities": gated}
    return feed_from_snapshot(snap)
