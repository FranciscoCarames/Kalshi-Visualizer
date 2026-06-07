"""Pure presentation viewmodel for the NiceGUI dashboard (PR 22) — NiceGUI-/Streamlit-free, unit-testable.

Input (the stored opportunity rows + coverage + control values) → display rows / filtered rows / scope
text / URL state. `webui/dashboard.py` is the thin NiceGUI shell that calls these builders; keeping the
logic here means the filtering, scope, and URL round-trip can be tested without a browser.

Filtering mirrors the Streamlit two-pass rule (see `filters.py`): MEMBERSHIP (sport / tournament /
participant) narrows EVERY row; THRESHOLDS (min size / active-only) narrow everything EXCEPT the
Actionable bucket and dutch-book rows (spared, like "Actionable now" in the Streamlit app). The unified
opportunity rows carry only a subset of fields, so the webui filters on those (sport / tournament / name /
exec_min_size / market_status); richer quote/layer filters need the persisted *checks* frame (PR 24/25).
"""
from __future__ import annotations

import math
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

import config
import consistency
import data
import scanner
import sports
import viz


# --- display-row builders (moved from dashboard.py; the canonical, testable home) -----
def ts_disp(ts: Any, tz: str) -> str:
    return data.fmt_time(datetime.fromtimestamp(ts, timezone.utc), tz, fmt="%H:%M:%S %Z") if ts else "—"


def classify_changes(prev: dict[str, dict], cur: dict[str, dict], ever_seen: set[str],
                     *, metric: str = "exec_gap_c") -> dict[str, str]:
    """Per-opportunity change vs the PREVIOUS snapshot, keyed by opportunity_id:
    'up'/'down' (the headline `metric` — gross edge — moved), 'new' (id never seen before),
    'returned' (seen before but absent in the previous snapshot), '' (unchanged). Pure; no UI. Computed
    once per new snapshot (see dashboard.reload_data) and persisted, so a plain filter re-render never
    re-derives or "replays" it."""
    out: dict[str, str] = {}
    for oid, o in cur.items():
        if oid in prev:
            a, b = _num_or_none(prev[oid].get(metric)), _num_or_none(o.get(metric))
            out[oid] = "" if (a is None or b is None or a == b) else ("up" if b > a else "down")
        else:
            out[oid] = "returned" if oid in ever_seen else "new"
    return out


# --- per-row severity badges (PR 2) ---------------------------------------------------
# Row-SPECIFIC caveats only (universal gross/top-of-book limits live once in the limitation strip, NOT
# per row — see glossary.KNOWN_LIMIT_BADGES). The mapper keys on STRUCTURAL fields first (rule_flag,
# tradable_now, presence of settlement_caveat / blocked_reason, quote_quality) — NO free-text matching,
# which is brittle (blocked_reason can be concatenated prose). Severity drives ordering + the row chip
# colour; the label always carries the meaning (colour is never the only signal).
_SEVERITY_RANK = {"blocker": 0, "review_required": 1, "advisory": 2, "info": 3}
_SEVERITY_SHORT = {"blocker": "Blocker", "review_required": "Review", "advisory": "Caveat", "info": "Info"}


def severity_badges(o: dict[str, Any]) -> list[dict[str, str]]:
    """Structured, row-specific caveat badges for one opportunity, highest severity first. Each badge is
    ``{label, severity, tooltip, source}`` with severity in info|advisory|review_required|blocker."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, severity: str, tooltip: str, source: str) -> None:
        if label not in seen:
            seen.add(label)
            out.append({"label": label, "severity": severity, "tooltip": tooltip, "source": source})

    if str(o.get("rule_flag") or "") in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH"):
        add("Rule review required", "review_required",
            "Two markets that should settle the same, but their settlement rules aren't confirmed to "
            "match — review them before trading.", "rule_flag")
    if str(o.get("tradable_now") or "") == "Review rules":
        add("Review rules", "review_required",
            "Settlement basis differs across the legs — review the rules before treating this as an edge.",
            "tradable_now")
    sc = o.get("settlement_caveat")
    if isinstance(sc, str) and sc:
        add("Settlement caveat", "advisory", sc, "settlement_caveat")
    br = o.get("blocked_reason")
    if isinstance(br, str) and br:
        add("Blocked", "blocker", br, "blocked_reason")
    qq = o.get("quote_quality")
    if qq in ("Wide", "Very wide"):
        add("Wide quote", "advisory", f"{qq} bid/ask spread — the displayed edge may not be executable.",
            "quote_quality")
    elif qq in ("No quote", "Crossed", "One-sided"):
        add("No firm quote", "blocker", f"{qq} book — no firm two-sided price to trade against.",
            "quote_quality")
    out.sort(key=lambda b: _SEVERITY_RANK.get(b["severity"], 9))
    return out


def _stamp_severity(row: dict[str, Any], o: dict[str, Any]) -> dict[str, Any]:
    """Add the TOP row-specific severity to a display row: ``_sev`` (severity key, for the cell colour),
    ``_sev_label`` (short severity word), and ``_caveat_tag`` (the top badge's content-descriptive label,
    e.g. "Settlement caveat" — shown in the compact caveat chip). Empty strings when no row-specific
    caveat. The full caveat prose lives in ``row["caveat"]`` (chip tooltip) and the detail panel."""
    badges = severity_badges(o)
    top = badges[0] if badges else None
    row["_sev"] = top["severity"] if top else ""
    row["_sev_label"] = _SEVERITY_SHORT.get(top["severity"], "") if top else ""
    row["_caveat_tag"] = top["label"] if top else ""
    return row


# --- mandatory action-plan summary + structured leg evidence (PR 3) --------------------
def _cents_str(v: Any) -> str:
    n = _num_or_none(v)
    return "—" if n is None else f"{int(round(n))}¢"


def _side_from_text(text: Any) -> str:
    t = str(text or "")
    if t.startswith("Buy YES"):
        return "Buy YES"
    if t.startswith("Buy NO"):
        return "Buy NO"
    return ""


def action_plan_summary(opp: dict[str, Any]) -> dict[str, Any]:
    """Self-contained action summary for a row (pure) so the buy plan is readable WITHOUT opening detail.
    Uses the opportunity's OWN cost/floor fields — it never assumes a 100¢ floor (2-way books floor at
    100¢, but N-leg / field overrounds and synthetic bundles differ). Conservative when fields are missing:
    they're listed in `missing_fields` and never invented. N-leg findings are described as N-leg, never as
    a 2-leg plan. Returns the structured parts + a one-cell `line`."""
    n = _num_or_none(opp.get("n_legs"))
    legs = opp.get("legs")
    if n is not None and n > 2:                       # genuine N-leg (synthetic bundle / n-way) — never faked as 2-leg
        summary = f"{int(n)}-leg plan — open details for legs"
    else:
        texts = [opp.get("action_1_text"), opp.get("action_2_text")]
        if not any(texts) and isinstance(legs, list) and legs:
            texts = [leg.get("text") for leg in legs]
        parts = [str(t) for t in texts if t]
        summary = " + ".join(parts) if parts else "—"
    cost, floor, units = opp.get("cost_c"), opp.get("payout_floor_c"), opp.get("exec_min_size")
    missing = [] if summary != "—" else ["legs"]
    for k, v in (("cost", cost), ("floor", floor), ("max_units", units)):
        if _num_or_none(v) is None:
            missing.append(k)
    units_str = "—" if _num_or_none(units) is None else str(int(units))
    return {
        "summary": summary,
        "cost": _cents_str(cost),
        "floor": _cents_str(floor),
        "max_units": units_str,
        "gross_edge": _cents_str(opp.get("exec_gap_c")),
        "line": f"{summary} (cost {_cents_str(cost)} → floor {_cents_str(floor)}, ≤{units_str} units)",
        "is_complete": not missing,
        "missing_fields": missing,
    }


def leg_rows(opp: dict[str, Any],
             contract_lookup: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Structured per-leg evidence for one opportunity (pure). Reads the opportunity's uniform `legs` list
    (the scanner synthesizes one even for 2-leg shapes). Per-leg `status`/`quote_quality` come from
    `contract_lookup` (ticker -> stored contract row) ONLY when present; otherwise the field is BLANK and
    `evidence_source` is 'unresolved' — we never infer per-leg status from the opportunity, nor quote
    quality from a worst-leg, nor fabricate price/size. Display only — no scanner/store schema change."""
    lookup = contract_lookup or {}
    legs = opp.get("legs")
    if not (isinstance(legs, list) and legs):
        return []
    out: list[dict[str, Any]] = []
    for i, leg in enumerate(legs, start=1):
        tkr = str(leg.get("ticker") or "")
        c = lookup.get(tkr) if tkr else None
        price, size = leg.get("price_c"), leg.get("size")
        out.append({
            "leg": f"Leg {i}",
            "side": leg.get("side") or _side_from_text(leg.get("text")),
            "market": leg.get("contract") or leg.get("text") or tkr or "—",
            "price": "" if _num_or_none(price) is None else f"{int(round(price))}¢",
            "size": "" if _num_or_none(size) is None else str(int(size)),
            "status": (c or {}).get("status") or "",
            "quote_quality": (c or {}).get("quote_quality") or "",
            "url": leg.get("url") or "",
            "evidence_source": ("contract_lookup" if c else
                                ("opportunity" if (leg.get("text") or price is not None) else "unresolved")),
            "warning": "" if (c or not tkr) else "unavailable in snapshot",
        })
    return out


def opp_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
            flash_ids: set[str] | None = None) -> dict[str, Any]:
    nf = net_of_fees(o)            # PR E: DISPLAY-ONLY net-of-fees estimate (default-hidden columns)
    return _stamp_severity({
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "action": action_plan_summary(o)["line"],   # mandatory self-contained buy plan (PR 3)
        "edge": o.get("exec_gap_c"), "roi": o.get("roi_pct"), "units": o.get("exec_min_size"),
        "profit": o.get("exec_max_profit_dollars"),
        # Net-of-fees ESTIMATE (PR E) — display only; blank when a leg price/units is missing. Never ranks.
        "fees": nf["total_fees_c"], "net_edge": nf["net_edge_c"], "net_profit": nf["net_profit_dollars"],
        "tradable": o.get("tradable_now") or "",
        # The non-blocking per-game settlement caveat (PR 6) shows alongside any blocked_reason, so an
        # actionable game book still surfaces its postponement risk.
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }, o)


# --- "Beyond the strict rule" (PR 29) — risk-budget candidates + near-miss books -----
# Pure band-filters + display-row builders for the two opt-in sections. They run over the already
# membership/threshold-filtered `view`, so sport/tournament/participant filters still apply; the band
# controls (max-loss ¢ + min upside:risk for risk-budget; max-overpay ¢ for near-miss) are the extra
# narrowing. Integer cents throughout; min upside:risk is compared as integer tenths (no float ratio).
def risk_budget_view(opps: Iterable[dict[str, Any]] | None, *, max_loss_c: float,
                     min_ratio_tenths: int = 0, min_outright_c: float = 0,
                     max_spread_ratio_hundredths: int = 0) -> list[dict[str, Any]]:
    """Risk-budget candidates whose worst-case loss ≤ `max_loss_c` ¢ and (optionally) whose upside:risk ≥
    `min_ratio_tenths`/10. A worst-case loss of 0 (cost exactly 100¢ — zero downside, convex upside) is the
    premium case and always passes the ratio gate.

    Two probability-context filters narrow on the DISPLAY OUTRIGHT (not executable risk), each 0 = off:
    `min_outright_c` keeps only rows whose deeper (child) display outright ≥ that many ¢ (the longshot
    cut), and `max_spread_ratio_hundredths` keeps only rows whose child display spread/outright ≤ that/100.
    A row missing the field (e.g. an older snapshot) is HIDDEN only when the corresponding filter is active
    (it can't prove it passes); with both filters off, behavior is byte-for-byte unchanged."""
    out: list[dict[str, Any]] = []
    for o in (opps or []):
        if o.get("bucket") != "risk_budget":
            continue
        wc = o.get("worst_case_profit_c")
        if _isna(wc):
            continue
        risk = -wc                                    # worst-case loss ¢ (≥ 0)
        if risk > max_loss_c:
            continue
        bc = o.get("best_case_profit_c")
        if min_ratio_tenths and risk > 0 and not _isna(bc):
            if bc * 10 < min_ratio_tenths * risk:     # exact integer compare: best/risk ≥ ratio
                continue
        if min_outright_c:
            co = o.get("child_display_c")
            if _isna(co) or co < min_outright_c:      # missing / below the longshot floor -> hide
                continue
        if max_spread_ratio_hundredths:
            soc = o.get("spread_over_child")
            if _isna(soc) or soc * 100 > max_spread_ratio_hundredths:   # missing / over the cap -> hide
                continue
        out.append(o)
    return out


def near_miss_view(opps: Iterable[dict[str, Any]] | None, *, max_over_c: float) -> list[dict[str, Any]]:
    """Near-miss dutch books overpriced by 1..`max_over_c` ¢ over their payout floor (a flat-payout
    guaranteed loss as a bundle — watchlist only)."""
    out: list[dict[str, Any]] = []
    for o in (opps or []):
        if o.get("bucket") != "near_miss":
            continue
        g = o.get("exec_gap_c")
        if _isna(g):
            continue
        if 1 <= -g <= max_over_c:                      # overpay = −gap
            out.append(o)
    return out


def _upside_risk(worst: Any, best: Any) -> Any:
    """Upside:risk ratio for display. '∞' when there's zero downside (risk 0 = the premium case);
    None when either side is missing."""
    if _isna(worst):
        return None
    risk = -worst
    if risk == 0:
        return "∞"
    return None if _isna(best) else round(best / risk, 1)


def risk_budget_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                    flash_ids: set[str] | None = None) -> dict[str, Any]:
    """Display row for the risk-budget table: leads with the convex economics (max loss / max profit /
    upside:risk); worst-case ROC is a labelled secondary, never the headline (it's honestly negative)."""
    wc, bc = o.get("worst_case_profit_c"), o.get("best_case_profit_c")
    _r2 = lambda x: None if _num_or_none(x) is None else round(x, 2)   # noqa: E731 — display rounding
    return _stamp_severity({
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "max_loss": None if _isna(wc) else -wc,
        "max_profit": None if _isna(bc) else bc,
        "ratio": _upside_risk(wc, bc),
        # NOTE: no "tradable" field — a speculative bounded-loss BUNDLE is not auto-placeable even when its
        # legs are active, so we never surface tradable_now here (PR 1: de-risk speculative framing).
        "roc": o.get("roi_pct"),                       # worst-case ROC (gross, negative) — labelled, secondary
        # Probability context (DISPLAY OUTRIGHT, not executable): both outrights, the display spread, and
        # the spread/outright ratios that drive the "Outright + spread" rank mode + the new filters.
        "parent_outright": _num_or_none(o.get("parent_display_c")),
        "child_outright": _num_or_none(o.get("child_display_c")),
        "display_spread": _num_or_none(o.get("display_spread_c")),
        "spread_over_parent": _r2(o.get("spread_over_parent")),
        "spread_over_child": _r2(o.get("spread_over_child")),
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }, o)


def near_miss_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                  flash_ids: set[str] | None = None) -> dict[str, Any]:
    """Display row for the near-miss watchlist: the cost, the overpay (= guaranteed bundle loss), and the
    flat-loss note. Watchlist only — never frames it as an edge, and never surfaces tradable_now (the
    bundle is a guaranteed gross loss, not a placeable trade)."""
    g = o.get("exec_gap_c")
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": "🆕" if o.get("opportunity_id") in new_ids else "",
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "overpay": None if _isna(g) else -g,
        "watchlist": "Watchlist",
        "note": o.get("settlement_caveat") or "",
    }


# --- merged Watchlist (PR C) — one table over both speculative buckets --------------------------------
# The two opt-in buckets (risk_budget = bounded-loss bets; near_miss = overpriced books) share one
# "Watchlist — not actionable now" table. `watchlist_row` delegates to the per-bucket builders above (so
# their economics never diverge), then adds a Type chip + a DESCRIPTIVE, NON-IMPERATIVE Structure line, and
# blanks the other type's numeric columns. Honest framing only: no "tradable" field, no imperative "Buy …",
# none of the positive/edge vocabulary (see test_speculative_rows_drop_tradable_and_positive_framing).
_WATCHLIST_BLANKS = ("max_loss", "max_profit", "ratio", "roc", "parent_outright", "child_outright",
                     "display_spread", "spread_over_parent", "spread_over_child", "overpay")


def _watchlist_structure(o: dict[str, Any]) -> str:
    """A descriptive (never imperative) one-line structure for a bounded-loss bet: the action-plan legs with
    the "Buy" command stripped, so the watchlist describes the structure without telling anyone to trade."""
    line = action_plan_summary(o)["line"]
    return line.replace("Buy YES", "YES").replace("Buy NO", "NO")


def watchlist_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                  flash_ids: set[str] | None = None) -> dict[str, Any]:
    """One merged watchlist row. Branches on `o["bucket"]`, reuses the existing per-bucket builder, then
    stamps `type` + `structure` (and blanks the other type's numeric fields). Never frames the row as an
    edge or a placeable trade."""
    if o.get("bucket") == "risk_budget":
        row = risk_budget_row(o, new_ids, changes, flash_ids)
        row["type"] = "Bounded-loss bet"
        row["structure"] = _watchlist_structure(o)
        row["note"] = row.pop("caveat", "") or ""        # unify the text column name
        row["overpay"] = None
    else:                                                  # near_miss — an overpriced book (flat loss as a bundle)
        row = near_miss_row(o, new_ids, changes, flash_ids)
        row["type"] = "Overpriced book"
        row["structure"] = "Watch only — flat payout below cost (loss as a bundle)"
        row.pop("watchlist", None)                         # the Type column replaces the standalone marker
        for k in _WATCHLIST_BLANKS[:-1]:                   # blank bounded-loss-only fields (keep overpay)
            row[k] = None
    return row


def watchlist_view(opps: Iterable[dict[str, Any]] | None, *, include_rb: bool, include_nm: bool,
                   max_loss_c: float, min_ratio_tenths: int = 0, min_outright_c: float = 0,
                   max_spread_ratio_hundredths: int = 0, max_over_c: float = 0) -> list[dict[str, Any]]:
    """The merged watchlist opps: bounded-loss bets (when `include_rb`) FIRST, then overpriced books (when
    `include_nm`). Each subset is produced by its existing band-filter view and is already in `rank_opps`
    order, so we concatenate without re-sorting."""
    out: list[dict[str, Any]] = []
    if include_rb:
        out.extend(risk_budget_view(opps, max_loss_c=max_loss_c, min_ratio_tenths=min_ratio_tenths,
                                    min_outright_c=min_outright_c,
                                    max_spread_ratio_hundredths=max_spread_ratio_hundredths))
    if include_nm:
        out.extend(near_miss_view(opps, max_over_c=max_over_c))
    return out


def backlog_row(b: dict[str, Any], tz: str) -> dict[str, Any]:
    dur = b.get("duration_s")
    return {
        "sport": b.get("sport") or "", "name": b.get("name") or "",
        "became": ts_disp(b.get("became_ts"), tz), "left": ts_disp(b.get("left_ts"), tz),
        "mins": round(dur / 60, 1) if isinstance(dur, (int, float)) else None,
        "reason": b.get("reason_left") or "", "last_edge": b.get("last_edge_c"),
        "caveat": b.get("last_settlement_caveat") or "",
        "current": b.get("current_status") or b.get("current_bucket") or "gone",
    }


def explanation_lines(opp: dict[str, Any], *, show_ids: bool = False) -> list[str]:
    """The text content of the explanation panel for one opportunity (pure → unit-testable)."""
    lines = [
        f"{opp.get('sport_label') or opp.get('sport')} · {opp.get('name')}",
        f"{opp.get('source')} · {opp.get('detail')} · {opp.get('tournament')}",
    ]
    legs = opp.get("legs")
    if isinstance(legs, list) and legs:                      # N-leg (synthetic bundle): list every leg
        lines += [f"Leg {i + 1}: {leg.get('text') or '—'}" for i, leg in enumerate(legs)]
    else:                                                     # 2-leg shapes use the positional fields
        lines += [f"Leg 1: {opp.get('action_1_text') or '—'}", f"Leg 2: {opp.get('action_2_text') or '—'}"]
    _roi = opp.get("roi_pct")
    _floor = opp.get("payout_floor_c")
    lines += [
        f"Cost: {opp.get('cost_c')}¢   ·   Floor: {_floor}¢   ·   Gross edge: {opp.get('exec_gap_c')}¢"
        + (f"   ·   ROI: {_roi}%" if _roi is not None else "")
        + f"   ·   Max units: {opp.get('exec_min_size')}   ·   Gross profit: ${opp.get('exec_max_profit_dollars')}",
        f"Tradable now: {opp.get('tradable_now')}   ·   Relationship: {opp.get('relationship_type')}"
        f"   ·   Market: {opp.get('market_status')}",
    ]
    nf = net_of_fees(opp)        # PR E: net-of-fees ESTIMATE — display only; never affects ranking
    if not nf["missing"]:
        lines.append(
            f"Est. net of fees: fees ${nf['total_fees_c'] / 100:.2f}   ·   net edge {nf['net_edge_c']}¢"
            f"   ·   net max profit ${nf['net_profit_dollars']}"
            "   (general taker-fee estimate — display only; does not affect ranking)")
    if opp.get("bucket") == "risk_budget":
        wc, bc = opp.get("worst_case_profit_c"), opp.get("best_case_profit_c")
        loss = "—" if _isna(wc) else -wc
        lines.append(f"Speculative (bounded loss, convex upside): max loss {loss}¢   ·   "
                     f"max profit {'—' if _isna(bc) else bc}¢   ·   upside:risk {_upside_risk(wc, bc)}   ·   "
                     "GROSS of fees — NOT an edge.")
    elif opp.get("bucket") == "near_miss":
        g = opp.get("exec_gap_c")
        lines.append(f"Near-miss watchlist: overpay {'—' if _isna(g) else -g}¢ over the "
                     f"{opp.get('payout_floor_c')}¢ floor — a guaranteed gross loss as a bundle, NOT an edge.")
    if opp.get("settlement_caveat"):
        lines.append(f"Settlement caveat: {opp.get('settlement_caveat')}")
    if opp.get("blocked_reason"):
        lines.append(f"Caveat: {opp.get('blocked_reason')}")
    if show_ids:
        lines.append(f"id {opp.get('opportunity_id')} · {opp.get('ticker_1')} / {opp.get('ticker_2')}")
    return lines


# --- filtering (shape-branched; no fetch — narrows the STORED snapshot only) ----------
def _isna(x: Any) -> bool:
    return x is None or (isinstance(x, float) and x != x)


def _spared(o: dict[str, Any]) -> bool:
    """Thresholds spare the Actionable bucket and dutch-book rows (mirrors the Streamlit split)."""
    return o.get("bucket") == "actionable" or o.get("source") == "dutch_book"


def filter_opps(opps: Iterable[dict[str, Any]], *, sports: Iterable[str] | None = None,
                tournaments: Iterable[str] | None = None, participant: Any = "",
                min_size: float | None = None, active_only: bool = False) -> list[dict[str, Any]]:
    """Apply the membership + threshold filters to the unified opportunity rows. Membership narrows every
    row; thresholds narrow everything except `_spared` rows. Empty/None selection = no filter; NaN-safe.

    `participant` is a LIST of participant keys (the multi-select, PR6) — a row matches if ANY selected key
    is among its `participant_keys` (so both sides of a match / every named leg are reachable). A plain
    string is still accepted as a legacy case-insensitive substring match on the opportunity name."""
    rows = list(opps or [])
    if sports:
        sset = set(sports)
        rows = [o for o in rows if o.get("sport") in sset]
    if tournaments:
        tset = set(tournaments)
        rows = [o for o in rows if o.get("tournament") in tset]
    if participant:
        if isinstance(participant, (list, tuple, set)):
            keyset = {str(k) for k in participant}
            rows = [o for o in rows if keyset.intersection(o.get("participant_keys") or [])]
        else:
            needle = str(participant).strip().lower()
            rows = [o for o in rows if needle in str(o.get("name") or "").lower()]
    if min_size:
        rows = [o for o in rows
                if _spared(o) or (not _isna(o.get("exec_min_size")) and o.get("exec_min_size") >= min_size)]
    if active_only:
        rows = [o for o in rows if _spared(o) or str(o.get("market_status") or "") == "active"]
    return rows


# --- honest per-bucket counts for the status bar (PR 4) -------------------------------
# Distinguish hidden-by-membership vs hidden-by-threshold by reusing the EXACT filter_opps path (no
# duplicated filtering logic — the drift guard): in_scope = membership only; shown = membership + thresholds.
# Hidden-by-section-toggle is a pure UI concern handled by bucket_counts_line (the toggle state lives in the
# dashboard). Thresholds spare Actionable / dutch-book, so for those shown == in_scope by construction.
_MEMBERSHIP_KEYS = ("sports", "tournaments", "participant")
_BUCKET_LABEL = {"actionable": "Actionable", "review_signal": "Review", "blocked": "Blocked",
                 "risk_budget": "Speculative", "near_miss": "Near-miss"}
_BUCKET_ORDER = ["actionable", "review_signal", "blocked", "risk_budget", "near_miss"]


def _count_by_bucket(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in rows:
        b = o.get("bucket") or ""
        out[b] = out.get(b, 0) + 1
    return out


def bucket_counts(opps: Iterable[dict[str, Any]] | None,
                  filters: dict[str, Any] | None = None) -> dict[str, dict[str, int]]:
    """Per-bucket {total, in_scope, shown} over the snapshot, reusing filter_opps so the numbers can never
    drift from what the tables actually render. total = whole snapshot; in_scope = after MEMBERSHIP filters
    (sport/tournament/participant); shown = after membership + THRESHOLDS (min size / active-only)."""
    filters = filters or {}
    rows = list(opps or [])
    membership = {k: filters[k] for k in _MEMBERSHIP_KEYS if filters.get(k)}
    total = _count_by_bucket(rows)
    in_scope = _count_by_bucket(filter_opps(rows, **membership))
    shown = _count_by_bucket(filter_opps(rows, **filters))
    return {b: {"total": total.get(b, 0), "in_scope": in_scope.get(b, 0), "shown": shown.get(b, 0)}
            for b in (set(total) | set(in_scope) | set(shown))}


def bucket_counts_line(counts: dict[str, dict[str, int]] | None,
                       visible: dict[str, bool] | None = None) -> str:
    """Format the per-bucket counts unambiguously (never mixing "shown / in scope" for one bucket with a raw
    count for another). A toggled-off section reports its in-scope count as "hidden by settings" so the user
    knows content exists behind the toggle. Buckets with nothing in scope are omitted. Actionable is always
    visible. `visible` maps bucket -> toggle state for the opt-in sections."""
    counts = counts or {}
    visible = visible or {}
    parts: list[str] = []
    for b in _BUCKET_ORDER:
        c = counts.get(b)
        if not c or c["in_scope"] == 0:
            continue
        label = _BUCKET_LABEL[b]
        if b != "actionable" and not visible.get(b, False):
            parts.append(f"{label}: hidden by settings ({c['in_scope']} in scope)")
        elif c["shown"] < c["in_scope"]:
            parts.append(f"{label}: {c['shown']} shown / {c['in_scope']} in scope")
        else:
            parts.append(f"{label}: {c['shown']} shown")
    return " · ".join(parts)


# --- ranking modes (#1/#9) — payoff GEOMETRY, no probability / no expected-value ---------------------
# Three display-time orderings over the already-filtered rows; buckets ALWAYS group first (Actionable
# before Review before Blocked …), and a mode only re-orders WITHIN a bucket. Pure in-memory re-sort of
# the cached opportunities — no rescan, no store read. Risk-budget geometry comes from the existing PR29
# payoff fields (worst/best_case_profit_c); a row missing them simply sorts last within its bucket.
RANK_MODES = {"blended": "Blended", "edge": "Per-unit edge ¢", "spread_upside": "Spread upside",
              "spread_ratio": "Outright + spread"}
RANK_MODE_DEFAULT = "blended"
# Within-bucket Blended weights (renormalized over the components a row actually has). ROI is weighted a
# touch above absolute edge so the owner's "a 2¢→3¢ gap is a 50% improvement just like 20¢→30¢" shows up —
# a small-edge/high-ROI row can out-rank a big-edge/low-ROI one. Pure-absolute lives in the "edge" mode.
_BLEND_W = {"edge": 0.35, "roi": 0.45, "geom": 0.2}


def _num_or_none(x: Any) -> float | None:
    return x if isinstance(x, (int, float)) and x == x else None


# --- Net-of-fees ESTIMATE (PR E) — DISPLAY ONLY, never touches ranking/bucketing/actionability ----------
# Kalshi's published GENERAL taker-fee schedule: fee = ceil(0.07 × C × P × (1−P)) per fill, in cents, where
# C = contracts and P = price in dollars (0 at P=0 or P=1). This is an ESTIMATE: it's the general schedule,
# not a universal rate — some products use different/maker schedules — and it's gross of nothing else. The
# UI labels every net number "Est." and "general taker-fee estimate"; rank_opps / _edge / bucket_of never
# read these fields (see test_net_of_fees_does_not_affect_ranking).
def kalshi_fee_c(contracts: float, price_c: float) -> int:
    """Estimated Kalshi general taker fee for `contracts` at `price_c` cents, in integer cents (rounded up).
    Zero at the 0¢/100¢ endpoints. Returns 0 for non-positive/invalid contracts."""
    c, p = _num_or_none(contracts), _num_or_none(price_c)
    if c is None or p is None or c <= 0 or p <= 0 or p >= 100:
        return 0
    pf = p / 100.0
    fee_c = 0.07 * c * pf * (1 - pf) * 100
    return math.ceil(round(fee_c, 9))      # round off binary FP dust before the ceil (175.0000…3 -> 175)


def net_of_fees(opp: dict[str, Any], units: float | None = None) -> dict[str, Any]:
    """DISPLAY-ONLY net-of-fees estimate for one opportunity. Sums the estimated general taker fee over
    every leg's buy price (legs[].price_c, falling back to the 2-leg action_*_price_c) for `units` contracts
    (default: the opp's exec_min_size). Returns ``{total_fees_c, net_edge_c, net_profit_dollars,
    is_estimate, missing}``. When any required input (units / gap / a leg price) is missing, every net is
    BLANK (None) and ``missing`` is True — fees are never treated as 0 just because a price is absent."""
    u = _num_or_none(units if units is not None else opp.get("exec_min_size"))
    gap = _num_or_none(opp.get("exec_gap_c"))
    legs = opp.get("legs")
    if isinstance(legs, list) and legs:
        prices = [leg.get("price_c") for leg in legs]
    else:                                                      # 2-leg shapes without a synthesized legs list
        prices = [opp.get("action_1_price_c"), opp.get("action_2_price_c")]
    prices = [_num_or_none(p) for p in prices]
    if u is None or u <= 0 or gap is None or not prices or any(p is None for p in prices):
        return {"total_fees_c": None, "net_edge_c": None, "net_profit_dollars": None,
                "is_estimate": True, "missing": True}
    total_fees_c = sum(kalshi_fee_c(u, p) for p in prices)
    net_profit_c = gap * u - total_fees_c                      # gross profit (gap × units) minus fees
    return {
        "total_fees_c": total_fees_c,
        "net_edge_c": round(net_profit_c / u),                # per-unit net edge ¢ (display)
        "net_profit_dollars": round(net_profit_c / 100, 2),
        "is_estimate": True,
        "missing": False,
    }


def _edge(o: dict[str, Any]) -> float:
    g = _num_or_none(o.get("exec_gap_c"))
    return g if g is not None else float("-inf")


def _geometry(o: dict[str, Any]) -> tuple[float, float, float] | None:
    """(max_loss_c, spread_upside_c, upside_risk_ratio) from the convex payoff bounds, or None when they
    aren't present. ratio = +inf when there's upside but zero downside (a bounded-loss-of-0 row)."""
    wc, bc = _num_or_none(o.get("worst_case_profit_c")), _num_or_none(o.get("best_case_profit_c"))
    if wc is None or bc is None:
        return None
    max_loss = max(0.0, -wc)
    if max_loss == 0:
        ratio = float("inf") if bc > 0 else 0.0
    else:
        ratio = bc / max_loss
    return (max_loss, bc, ratio)


def _norm(vals: list[float | None]) -> list[float | None]:
    """Min-max normalize the present (non-None) values to 0..1; a constant set -> all 0; absent -> None."""
    present = [v for v in vals if v is not None]
    if not present:
        return [None] * len(vals)
    lo, hi = min(present), max(present)
    if hi <= lo:
        return [0.0 if v is not None else None for v in vals]
    return [((v - lo) / (hi - lo)) if v is not None else None for v in vals]


def _blended_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    n = len(group)
    edges = _norm([_num_or_none(o.get("exec_gap_c")) for o in group])
    rois = _norm([_num_or_none(o.get("roi_pct")) for o in group])
    geo_raw: list[float | None] = [None] * n
    if is_risk:
        geos = [_geometry(o) for o in group]
        finite = [g[2] for g in geos if g and g[2] != float("inf")]
        cap = (max(finite) + 1) if finite else 1.0     # map an infinite ratio to one step above the max finite
        geo_raw = [None if g is None else (cap if g[2] == float("inf") else g[2]) for g in geos]
    geos_n = _norm(geo_raw)

    scored: list[tuple[float | None, dict[str, Any]]] = []
    for i, o in enumerate(group):
        parts = [(w, v) for w, v in ((_BLEND_W["edge"], edges[i]), (_BLEND_W["roi"], rois[i]),
                                     (_BLEND_W["geom"], geos_n[i])) if v is not None]
        score = (sum(w * v for w, v in parts) / sum(w for w, _ in parts)) if parts else None
        scored.append((score, o))
    # known scores first (descending); rows with no usable inputs last; edge/id break ties deterministically.
    return [o for _, o in sorted(
        scored, key=lambda sv: (0 if sv[0] is not None else 1, -(sv[0] or 0.0),
                                -_edge(sv[1]), sv[1].get("opportunity_id") or ""))]


def _spread_upside_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    if not is_risk:                                     # no convex payoff here -> fall back to edge
        return sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or ""))

    def key(o: dict[str, Any]) -> tuple:
        g = _geometry(o)
        if g is None:                                   # unknown geometry sorts AFTER known, by edge
            return (1, -_edge(o), 0.0, 0.0, o.get("opportunity_id") or "")
        max_loss, upside, ratio = g
        return (0, -ratio, -upside, max_loss, o.get("opportunity_id") or "")   # +inf ratio -> top
    return sorted(group, key=key)


def _spread_ratio_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    """Probability-led order for risk-budget rows: the deeper (child) DISPLAY OUTRIGHT magnitude FIRST
    (descending — a 30¢/20¢ pair outranks a 3¢/2¢ pair even though both share a 0.5 spread/outright ratio,
    because spread/outright is scale-invariant), then the lower display spread/outright (child, then
    parent) as the relative-risk tiebreak. Rows with no usable deeper outright (missing/zero — e.g. an
    older snapshot lacking these fields, or a No-quote book) sort AFTER all known rows. Non-risk buckets
    have no display-outright legs -> fall back to per-unit edge."""
    if not is_risk:
        return sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or ""))

    def key(o: dict[str, Any]) -> tuple:
        co = _num_or_none(o.get("child_display_c"))
        if co is None or co <= 0:                       # no probability context -> last
            return (1, 0.0, 0.0, 0.0, o.get("opportunity_id") or "")
        soc = _num_or_none(o.get("spread_over_child"))
        sop = _num_or_none(o.get("spread_over_parent"))
        return (0, -co,                                 # higher-probability deeper outright first
                soc if soc is not None else float("inf"),
                sop if sop is not None else float("inf"),
                o.get("opportunity_id") or "")
    return sorted(group, key=key)


def rank_opps(opps: Iterable[dict[str, Any]] | None, mode: str = RANK_MODE_DEFAULT) -> list[dict[str, Any]]:
    """Re-order opportunities by `mode` (see RANK_MODES). Buckets group first; the mode re-orders within a
    bucket only. Pure in-memory — switching modes never rescans or reads the store."""
    rows = list(opps or [])
    by_bucket: dict[Any, list[dict[str, Any]]] = {}
    for o in rows:
        by_bucket.setdefault(o.get("bucket"), []).append(o)
    out: list[dict[str, Any]] = []
    for bucket in sorted(by_bucket, key=lambda b: scanner.BUCKET_PRIORITY.get(b, 99)):
        group = by_bucket[bucket]
        is_risk = bucket == "risk_budget"
        if mode == "spread_upside":
            out.extend(_spread_upside_order(group, is_risk))
        elif mode == "spread_ratio":
            out.extend(_spread_ratio_order(group, is_risk))
        elif mode == "blended":
            out.extend(_blended_order(group, is_risk))
        else:                                           # "edge" (and any unknown mode) -> per-unit edge ¢
            out.extend(sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or "")))
    return out


# --- "most liquid right now" (PR F) — over the stored CONTRACT rows (opportunities lack size/spread) ---
def liquidity_panel(contracts: Iterable[dict[str, Any]] | None, n: int = 5) -> dict[str, list]:
    """Top-N most liquid sports + contracts RIGHT NOW (pure, DISPLAY-ONLY telemetry — NOT an opportunity
    signal). Only `active`, genuinely two-sided books (bid>0, ask<100, both sizes>0) count, and a market's
    tradable liquidity = `min(bid_size, ask_size)` (the depth on the thinner side), tiebroken by a tighter
    spread then volume. Per-sport depth is the SUM of that across the sport's qualifying markets (UNKNOWN
    sport excluded). Returns
    ``{top_sports: [(label, depth)…], top_contracts: [(label, depth, spread¢)…]}`` — both empty/None-safe."""
    per_sport: dict[str, float] = {}
    rows: list[tuple[float, float, float, str]] = []
    for c in contracts or []:
        if str(c.get("status") or "") != "active":
            continue
        bid_sz, ask_sz = _num_or_none(c.get("yes_bid_size")), _num_or_none(c.get("yes_ask_size"))
        bid_c, ask_c = _num_or_none(c.get("yes_bid_c")), _num_or_none(c.get("yes_ask_c"))
        spread = _num_or_none(c.get("spread_cents"))
        if not bid_sz or not ask_sz or spread is None:           # firm size on BOTH sides + a spread
            continue
        if bid_c is None or ask_c is None or bid_c <= 0 or ask_c >= 100:   # reject the empty 0/100 book
            continue
        depth = min(bid_sz, ask_sz)
        cfg = sports.sport_for_series(c.get("series"))
        if cfg.sport_id != "unknown":
            per_sport[cfg.label] = per_sport.get(cfg.label, 0.0) + depth
        rows.append((depth, spread, _num_or_none(c.get("volume")) or 0, _contract_label(c)))
    top_sports = sorted(per_sport.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    rows.sort(key=lambda r: (-r[0], r[1], -r[2], r[3]))          # depth desc, spread asc, volume desc, label
    return {
        "top_sports": [(label, int(depth)) for label, depth in top_sports],
        "top_contracts": [(label, int(depth), int(spread)) for depth, spread, _vol, label in rows[:n]],
    }


def _contract_label(c: dict[str, Any]) -> str:
    name, contract = c.get("player") or "", c.get("contract") or c.get("market_ticker") or "?"
    return f"{name} — {contract}" if name else contract


def _mid(c: dict[str, Any]) -> float | None:
    """YES midpoint in cents, ONLY for a genuine two-sided book (bid>0, ask<100, bid<=ask); else None
    (an empty 0/100, one-sided, or crossed book has no meaningful mid)."""
    bid, ask = _num_or_none(c.get("yes_bid_c")), _num_or_none(c.get("yes_ask_c"))
    if bid is None or ask is None or bid <= 0 or ask >= 100 or bid > ask:
        return None
    return (bid + ask) / 2


def volatility_leader(frames: list[dict[str, Any]] | None) -> str | None:
    """A one-line 'most volatile right now' message over recent CONTRACT frames (oldest->newest, each
    ``{fetched_ts, rows}``). Per market_ticker, the metric is the largest |Δ mid| between consecutive
    USABLE (two-sided) observations. Reports the leader with its ACTUAL observation count + the real span
    (so it never implies continuous sampling). Truthful when there isn't enough history or nothing moved."""
    frames = list(frames or [])
    if len(frames) < 2:
        return "Market telemetry: volatility unavailable yet — need at least two recent scans with order books."
    series: dict[str, list[tuple[Any, float]]] = {}
    labels: dict[str, str] = {}
    for f in frames:
        ts = f.get("fetched_ts")
        for c in f.get("rows") or []:
            mid = _mid(c)
            tkr = c.get("market_ticker") or ""
            if mid is None or not tkr:
                continue
            series.setdefault(tkr, []).append((ts, mid))
            labels[tkr] = _contract_label(c)        # last (newest) label wins
    best = None        # (max_delta_c, obs, ticker)
    for tkr, obs in series.items():
        if len(obs) < 2:
            continue
        obs.sort(key=lambda x: x[0])
        max_d = max(abs(obs[i][1] - obs[i - 1][1]) for i in range(1, len(obs)))
        if best is None or (max_d, len(obs)) > (best[0], best[1]):
            best = (max_d, len(obs), tkr)
    if best is None or best[0] == 0:
        return "Market telemetry: volatility unavailable yet — prices haven't moved across recent scans."
    max_d, obs, tkr = best
    span_min = max(1, round((frames[-1]["fetched_ts"] - frames[0]["fetched_ts"]) / 60))
    return f"Market telemetry: largest move: {labels[tkr]} — moved {max_d:.0f}¢ over {obs} obs in ~{span_min} min"


def derive_options(opps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Select options sourced from the loaded snapshot, so a dropdown only offers what's present.
    `sports` is an ``{id: label}`` map (the filter matches the id); `tournaments` a sorted list."""
    sports: dict[str, str] = {}
    tournaments: set[str] = set()
    pmap: dict[str, str] = {}        # participant_key -> display label (first label wins; stable across opps)
    for o in opps or []:
        if o.get("sport"):
            sports[o["sport"]] = o.get("sport_label") or o["sport"]
        if o.get("tournament"):
            tournaments.add(o["tournament"])
        for k, lab in zip(o.get("participant_keys") or [], o.get("participant_labels") or []):
            if k and k not in pmap:
                pmap[k] = lab or k
    # Key-based options (two same-named players never merge). Disambiguate a label shared by >1 key with a
    # short key suffix, mirroring the Streamlit "Name [key6]" convention.
    label_counts = Counter(pmap.values())
    participants = [{"value": k, "label": (f"{lab} [{k[:6]}]" if label_counts[lab] > 1 else lab)}
                    for k, lab in sorted(pmap.items(), key=lambda kv: (kv[1].lower(), kv[0]))]
    return {"sports": dict(sorted(sports.items())), "tournaments": sorted(tournaments),
            "participants": participants}


# --- scope banner (honest; surfaces the PR 21a counters) ------------------------------
def scope_banner(cov: dict[str, Any] | None, tz: str = "UTC", *, stale_after: float | None = None) -> str:
    """The data-scope line from the scan's own coverage meta (incl. contracts_scanned / checks_tested /
    kalshi_requests, distinct from the opportunity count). The data AGE is recomputed live from
    `fetched_at` (so a per-second timer keeps it current). Honest when there's no scan / no meta."""
    if not cov or cov.get("fetched_at") is None:
        return "No scan yet — press “Refresh snapshot”."
    when = data.fmt_time(cov["fetched_at"], tz, fmt="%H:%M:%S %Z")
    age = data.data_age_seconds(cov["fetched_at"])
    threshold = config.STALE_AFTER_SECONDS if stale_after is None else stale_after
    stale = "  ⚠ STALE" if data.is_stale(age, threshold) else ""
    parts = [f"Data {when} · age {int(age) if isinstance(age, (int, float)) else '—'}s{stale}",
             f"{cov.get('opportunities', 0)} opportunities"]
    if cov.get("meta_present"):
        parts.append(f"{cov.get('scanned', 0)} series · {cov.get('failed', 0)} failed")
        cs, ct = cov.get("contracts_scanned"), cov.get("checks_tested")
        parts.append(f"{cs or 0} contracts scanned · {ct or 0} checks tested")
        if cov.get("kalshi_requests") is not None:
            parts.append(f"{cov['kalshi_requests']} Kalshi requests")
    else:
        parts.append("no coverage meta")
    return " · ".join(parts)


# --- URL state (compact, graceful reset of unknown sport/tournament) ------------------
def state_from_query(params: dict[str, Any], *, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse compact query params into control values. A `sport`/`tournament`/`participant` not present in
    the snapshot (`options`) is DROPPED, not errored (graceful reset of a stale link). `participant` is a
    comma-separated, URL-encoded list of participant KEYS (PR6)."""
    state: dict[str, Any] = {}
    valid_sports = set((options or {}).get("sports") or {})
    valid_tours = set((options or {}).get("tournaments") or [])
    valid_participants = {p["value"] for p in (options or {}).get("participants") or []}
    if params.get("sport"):
        sel = [s for s in str(params["sport"]).split(",") if s and (options is None or s in valid_sports)]
        if sel:
            state["sports"] = sel
    if params.get("tournament"):
        sel = [t for t in str(params["tournament"]).split(",") if t and (options is None or t in valid_tours)]
        if sel:
            state["tournaments"] = sel
    if params.get("participant"):
        sel = [urllib.parse.unquote(p) for p in str(params["participant"]).split(",") if p]
        # validate against the snapshot's participants when options are supplied (stale-link reset)
        sel = [k for k in sel if not valid_participants or k in valid_participants]
        if sel:
            state["participant"] = sel
    if params.get("min_size"):
        try:
            state["min_size"] = float(params["min_size"])
        except (ValueError, TypeError):
            pass
    if str(params.get("active") or "").lower() in ("1", "true"):
        state["active_only"] = True
    return state


def query_from_state(state: dict[str, Any]) -> dict[str, str]:
    """The compact query string params for the current control state (empties omitted)."""
    q: dict[str, str] = {}
    if state.get("sports"):
        q["sport"] = ",".join(state["sports"])
    if state.get("tournaments"):
        q["tournament"] = ",".join(state["tournaments"])
    if state.get("participant"):
        q["participant"] = ",".join(urllib.parse.quote(str(k), safe="") for k in state["participant"])
    if state.get("min_size"):
        q["min_size"] = str(state["min_size"])
    if state.get("active_only"):
        q["active"] = "1"
    return q


def active_filter_chips(state: dict[str, Any], options: dict[str, Any] | None = None) -> list[str]:
    """Short human labels for the currently-active filters (for the filter-chips row)."""
    chips: list[str] = []
    smap = (options or {}).get("sports") or {}
    if state.get("sports"):
        chips.append("sport: " + ", ".join(smap.get(s, s) for s in state["sports"]))
    if state.get("tournaments"):
        chips.append("tournament: " + ", ".join(state["tournaments"]))
    if state.get("participant"):
        pmap = {p["value"]: p["label"] for p in (options or {}).get("participants") or []}
        chips.append("participant: " + ", ".join(pmap.get(k, k) for k in state["participant"]))
    if state.get("min_size"):
        chips.append(f"min size ≥ {state['min_size']:g}")
    if state.get("active_only"):
        chips.append("active only")
    return chips


# --- participant detail (PR 24) — pure builders over a participant's STORED contract rows ----------
def _num(v: Any) -> Any:
    return None if v is None or (isinstance(v, float) and v != v) else v


def detail_chain(prows: list[dict[str, Any]], sport: str) -> list[dict[str, Any]]:
    """The containment progression chain (broad → deep) for one participant: one row per ladder node
    with its representative price. [] for a sport with no ladder (e.g. golf-less / unknown). Reuses
    consistency.build_player_nodes + representative."""
    cfg = sports.get_sport(sport)
    order = getattr(cfg.ladder, "node_order", ()) if cfg.ladder else ()
    if not order:
        return []
    nodes = consistency.build_player_nodes(list(prows or []))
    out: list[dict[str, Any]] = []
    for node in order:
        src = nodes.get(node, {})
        primary = consistency.representative(src)
        if primary is None:
            out.append({"layer": node, "source": "— missing —", "display_pct": None,
                        "bid_pct": None, "ask_pct": None, "quote": ""})
        else:
            out.append({"layer": node,
                        "source": "advance/winner" if "market" in src else "match-implied",
                        "display_pct": _num(primary.get("display_pct")),
                        "bid_pct": _num(primary.get("yes_bid_pct")), "ask_pct": _num(primary.get("yes_ask_pct")),
                        "quote": primary.get("quote_quality") or ""})
    return out


def detail_spreads(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Raw adjacent-layer stage-ladder spreads (broader − deeper). Reuses consistency.layer_spreads."""
    return consistency.layer_spreads(list(prows or []))


def detail_expected(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expected-vs-found ladder checklist (Layer / found / source). Reuses consistency.expected_nodes."""
    return consistency.expected_nodes(list(prows or []))


def detail_contracts(prows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All of a participant's contracts, sorted by stage_rank, with the display columns."""
    def _rank(r: dict[str, Any]) -> float:
        v = r.get("stage_rank")
        return v if isinstance(v, (int, float)) and v == v else 1e9
    return [{
        "contract": r.get("contract") or "", "category": r.get("category") or "",
        "stage": r.get("stage") or "", "opponent": r.get("opponent") or "",
        "display_pct": _num(r.get("display_pct")), "quote": r.get("quote_quality") or "",
        "bid_pct": _num(r.get("yes_bid_pct")), "ask_pct": _num(r.get("yes_ask_pct")),
        "volume": _num(r.get("volume")), "status": r.get("status") or "", "url": r.get("kalshi_url") or "",
    } for r in sorted(list(prows or []), key=_rank)]


_REL_EXPLAIN = {
    "containment": "Containment ladder: a deeper outcome (e.g. Win Tournament) is contained in a broader "
                   "one (e.g. Reach Final), so it must never price higher. The trade is Buy YES the broader "
                   "leg + Buy NO the deeper leg.",
    "dutch_book": "Dutch book: cover every (covered) outcome of a mutually-exclusive set for under the "
                  "payout floor — a gross pricing discrepancy under normal one-winner settlement. Covers "
                  "2-way match/game books, 3-way soccer games, and tournament-winner fields (overround on "
                  "the priceable subset). A per-game book carries a postponement caveat.",
    "synthetic_bundle": "Synthetic bundle: a player's exact-set-score contracts together replicate 'they "
                        "win', priced against their match-winner — settlement-caveated, shown review-only.",
}


def relationship_explanation(opp: dict[str, Any]) -> str:
    """Plain-English meaning of an opportunity's relationship type, with a SAFE fallback for an unknown
    type (never raises on a future relationship)."""
    rel = str(opp.get("relationship_type") or opp.get("source") or "")
    if opp.get("rule_flag") and rel.startswith("containment"):
        return ("Match-alignment equivalence: two DIFFERENT markets that should settle the same — "
                "rule-dependent, so it isn't a secured gross spread (review the settlement rules).")
    return _REL_EXPLAIN.get(rel, f"Relationship: {rel or 'unknown'} — see the legs above.")


def ladder_chart_option(chain_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """An ECharts horizontal-bar `option` for the containment ladder (red bar = inverted), or None when
    fewer than 2 layers are priced (nothing to plot / non-containment)."""
    # viz.ladder_prices wants the Streamlit-style "Layer"/"Display %" keys; adapt the detail_chain rows.
    adapted = [{"Layer": r.get("layer", ""), "Display %": r.get("display_pct")} for r in (chain_rows or [])]
    recs = [r for r in viz.ladder_prices(adapted).to_dict("records") if r["display_pct"] is not None]
    if len(recs) < 2:
        return None
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "name": "Display %", "max": 100},
        "yAxis": {"type": "category", "data": [r["layer"] for r in recs]},
        "series": [{"type": "bar", "data": [
            {"value": r["display_pct"], "itemStyle": {"color": "#c62828" if r["inverted"] else "#1565c0"}}
            for r in recs]}],
    }


def payoff_chart_option(pay: dict[str, Any] | None) -> dict[str, Any] | None:
    """An ECharts bar `option` for the per-unit payoff (Floor/Bonus bars + a dashed cost line), or None
    for a None / non-containment payoff (the 'Risk' rows carry no payout and are dropped)."""
    recs = [r for r in viz.payoff_chart_data(pay).to_dict("records")
            if r["role"] != "Risk" and r["payout_c"] is not None]
    if not recs:
        return None
    colors = {"Floor": "#2e7d32", "Bonus": "#1565c0"}
    series: dict[str, Any] = {"type": "bar", "data": [
        {"value": r["payout_c"], "itemStyle": {"color": colors.get(r["role"], "#888")}} for r in recs]}
    cost = (pay or {}).get("cost_c")
    if cost is not None:
        series["markLine"] = {"symbol": "none", "lineStyle": {"color": "#c62828", "type": "dashed"},
                              "data": [{"yAxis": cost, "name": "cost"}]}
    return {"tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [r["scenario"] for r in recs]},
            "yAxis": {"type": "value", "name": "Payout ¢"}, "series": [series]}


# --- diagnostics / debug display builders (PR 25b) — pure projections over STORED frames ----------
def diagnostics_rows(check_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Project the stored consistency-check rows (all sports) to the full-diagnostics grid columns. The
    grid pages/filters/sorts client-side, so this is just a NaN-safe column projection."""
    return [{
        "player": r.get("player") or "", "chain": r.get("chain") or "",
        "tournament": r.get("tournament") or "", "status": r.get("status") or "",
        "status_group": r.get("status_group") or "", "rule_flag": r.get("rule_flag") or "",
        "executable_gap": _num(r.get("executable_gap")), "display_gap": _num(r.get("display_gap")),
        "reason": r.get("reason") or "",
    } for r in (check_rows or [])]


def non_laddered_rows(contract_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The contracts that aren't part of a containment ladder (per-game, props, awards, …) — shown for
    transparency, never silently dropped. Sorted by family then volume desc (mirrors the Streamlit app)."""
    out = [{
        "player": r.get("player") or "", "contract": r.get("contract") or "",
        "market_family": r.get("market_family") or "—", "category": r.get("category") or "",
        "classification_reason": r.get("classification_reason") or "",
        "display_pct": _num(r.get("display_pct")), "volume": _num(r.get("volume")),
        "status": r.get("status") or "", "url": r.get("kalshi_url") or "",
    } for r in (contract_rows or []) if not r.get("ladder_eligible")]
    out.sort(key=lambda r: (r["market_family"], -(r["volume"] or 0)))
    return out


def raw_fields_rows(contract_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Per-participant raw contract fields (incl. the tournament grouping source + mapping confidence) for
    the debug sub-panel — the NiceGUI twin of the Streamlit raw-fields table."""
    return [{
        "series": r.get("series") or "", "event_ticker": r.get("event_ticker") or "",
        "event_title": r.get("event_title") or "", "tournament": r.get("tournament") or "",
        "tournament_source": r.get("tournament_source") or "", "kind": r.get("kind") or "",
        "stage": r.get("stage") or "", "player_key": r.get("player_key") or "",
        "player_key_source": r.get("player_key_source") or "",
        "mapping_confidence": r.get("mapping_confidence") or "",
        "raw_yes_bid": r.get("raw_yes_bid"), "raw_yes_ask": r.get("raw_yes_ask"),
        "raw_no_bid": r.get("raw_no_bid"), "raw_no_ask": r.get("raw_no_ask"),
    } for r in (contract_rows or [])]


def sum_row_maxima(opps: Iterable[dict[str, Any]] | None) -> float:
    """The sum of per-opportunity max gross profit over the ACTIONABLE rows. Labelled "Sum of independent
    row maxima" in the UI, NOT "gross profit": each opportunity's max is independent, so the sum is not a
    guaranteed simultaneous total (you can't necessarily capture every maximum at once). NaN-safe."""
    total = 0.0
    for o in (opps or []):
        if o.get("bucket") == "actionable":
            v = o.get("exec_max_profit_dollars")
            if not _isna(v):
                total += float(v)
    return round(total, 2)


def link_audit_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Thin pass-through to data.link_audit (URL ↔ contract-identifier correctness), so the dashboard keeps
    importing only the viewmodel."""
    return data.link_audit(list(rows or []))


def duplicate_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Thin pass-through to consistency.duplicate_node_sources (where a representative was chosen among
    duplicates), for the debug sub-panel."""
    return consistency.duplicate_node_sources(list(rows or []))


# --- truthful empty states (PR 26a) — one honest message per empty scope, or None when there's content ---
def empty_state(*, cov: dict[str, Any] | None, total_opps: int, shown_opps: int,
                scan_status: dict[str, Any] | None = None) -> str | None:
    """The honest message to show when the opportunity area is empty, distinguishing WHY it's empty — or
    None when there is content (`shown_opps > 0`). Scopes: no-scan / scanning / scan-failed /
    no-opportunities / filter-hid-all. Never raises on missing keys (NaN/None-safe)."""
    if shown_opps > 0:
        return None
    status = (scan_status or {}).get("status")
    err = ((scan_status or {}).get("last_result") or {}).get("error")
    if not cov or cov.get("fetched_at") is None:
        if status == "in_progress":
            return "Scanning… results will appear here."
        return "No scan yet — press “Refresh snapshot”."
    if total_opps == 0:
        if status == "error" and err:
            return f"Last scan failed: {err}. Showing the last good snapshot (no opportunities)."
        return "Scan complete — no opportunities right now (between rounds, this is normal)."
    return f"All {total_opps} opportunities are hidden by the current filters — clear filters to see them."
