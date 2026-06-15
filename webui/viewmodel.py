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
import statistics
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
    if str(o.get("tradable_now") or "") == "Review execution":
        add("Execution review required", "review_required",
            "A speculative top-two bundle — 12-leg, gross, top-of-book. Verify size and settlement before "
            "treating it as tradable. Not arbitrage.", "tradable_now")
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
    # Fee-awareness (PR E) — ADVISORY, display-only: when an Actionable row's estimated GENERAL taker fees
    # (top-of-book, at the executable size) meet or exceed its gross edge, flag it so a thin headline edge
    # isn't mistaken for net profit. This NEVER hides, demotes, re-ranks, or un-Actionables the row — it is
    # an informational chip on top of the unchanged gross engine output (the estimate isn't realized P&L).
    if o.get("bucket") == "actionable":
        nf = net_of_fees(o)
        if not nf["missing"] and nf["net_profit_dollars"] is not None and nf["net_profit_dollars"] <= 0:
            add("Net-negative (est.)", "advisory",
                "Estimated general taker fees (top-of-book, at the executable size) meet or exceed the gross "
                "edge — this row may be net-negative. Estimate only (excludes maker/rounding/product-specific "
                "schedules); informational, not a block.", "net_of_fees")
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


_SIDE_ENUM_LABEL = {"buy_yes": "Buy YES", "buy_no": "Buy NO"}


def _side_from_text(text: Any) -> str:
    t = str(text or "")
    if t.startswith("Buy YES"):
        return "Buy YES"
    if t.startswith("Buy NO"):
        return "Buy NO"
    return ""


def _side_label(leg: dict[str, Any]) -> str:
    """A human side label for a leg: the explicit ``side`` (mapping the ``buy_yes``/``buy_no`` enum the
    detectors emit to 'Buy YES'/'Buy NO'), else parsed from the leg's action text. '' when neither."""
    side = leg.get("side") or ""
    return _SIDE_ENUM_LABEL.get(side, side) or _side_from_text(leg.get("text"))


def frame_sides(text: Any, long_short: bool = False) -> Any:
    """DISPLAY-ONLY wording transform: re-word 'Buy YES' -> 'Long YES' and 'Buy NO' -> 'Short YES' when
    `long_short` is on (buying NO is economically a short on YES). No-op (returns the value unchanged)
    when off or empty — so the canonical buy-only wording is the default. Never touches the stored
    detection fields; the detection layers keep emitting 'Buy YES'/'Buy NO'."""
    if not long_short or not text:
        return text
    return str(text).replace("Buy YES", "Long YES").replace("Buy NO", "Short YES")


def action_plan_summary(opp: dict[str, Any], *, long_short: bool = False) -> dict[str, Any]:
    """Self-contained action summary for a row (pure) so the buy plan is readable WITHOUT opening detail.
    Uses the opportunity's OWN cost/floor fields — it never assumes a 100¢ floor (2-way books floor at
    100¢, but N-leg / field overrounds and synthetic bundles differ). Conservative when fields are missing:
    they're listed in `missing_fields` and never invented. N-leg findings are described as N-leg, never as
    a 2-leg plan. Returns the structured parts + a one-cell `line`. `long_short` re-words the buy legs to
    Long/Short YES at display time (see frame_sides)."""
    n = _num_or_none(opp.get("n_legs"))
    legs = opp.get("legs")
    if n is not None and n > 2:                       # genuine N-leg (synthetic bundle / n-way) — never faked as 2-leg
        summary = f"{int(n)}-leg plan — open details for legs"
    else:
        texts = [opp.get("action_1_text"), opp.get("action_2_text")]
        if not any(texts) and isinstance(legs, list) and legs:
            texts = [leg.get("text") for leg in legs]
        parts = [frame_sides(t, long_short) for t in texts if t]
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


# Exact-order top-two bundle (#4): the row-level predicate — keyed on the ROW, NEVER on the bucket (the
# `qualifier_setup` bucket ALSO holds game-support signals, which must not get top-two wording).
_EXACT_ORDER_SETUP_TYPES = {"exact_order_top2_bundle", "exact_order_top2_relative_value",
                            "exact_order_top2_proxy"}  # last entry = legacy stale snapshots


def _is_exact_order_bundle(o: dict[str, Any]) -> bool:
    return (str(o.get("source") or "") == "exact_order"
            or str(o.get("setup_type") or "") in _EXACT_ORDER_SETUP_TYPES)


def _is_comparator_leg(leg: dict[str, Any]) -> bool:
    """A legacy qualifier COMPARATOR leg (pre two-tier split it was shipped as 'Leg 13'). Identified by
    'qualify' in its contract/text — defensively dropped so even stale 13-leg snapshots render 12 legs."""
    blob = f"{leg.get('contract') or ''} {leg.get('text') or ''}".lower()
    return "qualify" in blob


def _bundle_legs(opp: dict[str, Any]) -> list[dict[str, Any]]:
    """The opportunity's leg list, with any legacy comparator leg filtered out for exact-order rows."""
    legs = opp.get("legs")
    if not (isinstance(legs, list) and legs):
        return []
    if _is_exact_order_bundle(opp):
        return [lg for lg in legs if isinstance(lg, dict) and not _is_comparator_leg(lg)]
    return list(legs)


def leg_rows(opp: dict[str, Any],
             contract_lookup: dict[str, dict[str, Any]] | None = None,
             *, long_short: bool = False) -> list[dict[str, Any]]:
    """Structured per-leg evidence for one opportunity (pure). Reads the opportunity's uniform `legs` list
    (the scanner synthesizes one even for 2-leg shapes; exact-order rows drop a legacy comparator leg).
    Per-leg `status`/`quote_quality` come from `contract_lookup` (ticker -> stored contract row) ONLY when
    present; otherwise the field is BLANK and `evidence_source` is 'unresolved' — we never infer per-leg
    status from the opportunity, nor quote quality from a worst-leg, nor fabricate price/size. Display
    only — no scanner/store schema change."""
    lookup = contract_lookup or {}
    legs = _bundle_legs(opp)
    if not legs:
        return []
    out: list[dict[str, Any]] = []
    for i, leg in enumerate(legs, start=1):
        tkr = str(leg.get("ticker") or "")
        c = lookup.get(tkr) if tkr else None
        price, size = leg.get("price_c"), leg.get("size")
        out.append({
            "leg": f"Leg {i}",
            "side": frame_sides(_side_label(leg), long_short),
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


# World Cup Qualifier Setups (PR1) — a compact, single-sourced badge prefixed onto the detail cell so a
# flagged row (qualifier-not-winner spread / group YES/NO basket) is recognisable in its existing
# actionable/blocked section. Full chip styling + the diagnostic section land in later PRs.
_SETUP_BADGE = "🏆 WC Qualifier"


def _detail_with_badge(o: dict[str, Any]) -> str:
    detail = o.get("detail") or ""
    if o.get("setup_family") == "wc_qualifier":
        return f"{_SETUP_BADGE} · {detail}" if detail else _SETUP_BADGE
    return detail


def opp_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
            flash_ids: set[str] | None = None, *, long_short: bool = False) -> dict[str, Any]:
    nf = net_of_fees(o)            # PR E: DISPLAY-ONLY net-of-fees estimate (default-hidden columns)
    return _stamp_severity({
        "opportunity_id": o.get("opportunity_id"),
        "new": o.get("opportunity_id") in new_ids,   # bool → a coloured "NEW" badge in the cell slot
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        # WC Qualifier Setups (PR1): carry the tag for the detail panel / future PR6 chip + prefix a compact
        # badge onto the detail cell so a flagged row is visible in its existing actionable/blocked section.
        "setup_family": o.get("setup_family") or "", "setup_type": o.get("setup_type") or "",
        "name": o.get("name") or "", "detail": _detail_with_badge(o),
        # Compact: just the legs (cost/floor live in the click→detail panel; "Max units" is its own column).
        "action": action_plan_summary(o, long_short=long_short)["summary"],
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


def split_by_resolution(opps: Iterable[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition bounded-loss rows into (vertical, calendar) by `resolution_mode`. Vertical = the two legs
    resolve SIMULTANEOUSLY (one event's outcome — e.g. golf Top-N, a match-alignment equivalence); calendar
    = they resolve SEQUENTIALLY across rounds. Only the explicit "vertical" goes vertical; anything else
    (incl. a missing value on an older snapshot) defaults to calendar — the conservative bucket. Input
    order is preserved within each list, so the caller's ranking carries through."""
    vertical, calendar = [], []
    for o in (opps or []):
        (vertical if o.get("resolution_mode") == "vertical" else calendar).append(o)
    return vertical, calendar


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


_BUDGET_C = 10000   # $100 gross top-of-book reference allocation, in cents


def _wins_if(o: dict[str, Any]) -> str:
    """Plain-English payoff zone for a bounded-loss bet — the broader rung happens but NOT the deeper one
    (e.g. 'Reach Final but not Win Tournament', 'Top 10 but not Top 5'). Blank when the rung labels are
    absent (display-only — `parent_node`/`child_node` never feed executable logic)."""
    parent, child = str(o.get("parent_node") or "").strip(), str(o.get("child_node") or "").strip()
    return f"{parent} but not {child}" if parent and child else ""


def _sized_at_budget(o: dict[str, Any], budget_c: int = _BUDGET_C) -> tuple[int, int, int] | None:
    """A $100 (gross, top-of-book) allocation sized down to what's affordable AND fillable:
    units = min(budget // cost, top-of-book size). Returns (units, gross max-loss ¢, gross best-upside ¢),
    or None when cost / per-unit payoffs / a positive fillable size are missing. Scales the per-unit
    worst/best-case profit already on the row — no payoff math is duplicated here."""
    cost = _num_or_none(o.get("cost_c"))
    wc, bc = _num_or_none(o.get("worst_case_profit_c")), _num_or_none(o.get("best_case_profit_c"))
    if cost is None or cost <= 0 or wc is None or bc is None:
        return None
    units = int(budget_c // cost)
    size = _num_or_none(o.get("exec_min_size"))
    if size is not None:
        units = min(units, int(size))
    if units <= 0:
        return None
    return units, round(-wc * units), round(bc * units)


def _overpay_c(o: dict[str, Any]) -> float | None:
    wc = _num_or_none(o.get("worst_case_profit_c"))
    return None if wc is None else max(0.0, -wc)


def _peer_cheap(b_val: float | None, peer_vals: list, k: float) -> bool:
    """True if `b_val` sits ≥ `k` robust z-scores (median/MAD) BELOW the peer median (lower = cheaper). MAD 0
    (a constant peer level) → flag only a strict undercut. None inputs / no peers → not cheap."""
    vals = [v for v in peer_vals if v is not None]
    if b_val is None or not vals:
        return False
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    return b_val < med if mad == 0 else (med - b_val) / mad >= k


def flag_peer_cheapness(opps: Iterable[dict[str, Any]] | None, *, band_tol_c: float | None = None,
                        min_peers: int | None = None, k: float | None = None) -> list[dict[str, Any]]:
    """Stamp DISPLAY-ONLY `cheap_cost` / `cheap_ratio` flags on each bounded-loss opp: cheap vs SAME-SPORT
    peers within `band_tol_c` ¢ of the same implied-payoff band (`display_spread_c`). A bet is cheap on
    `cost` when its overpay (max loss), or on `ratio` when its spread÷outright, is ≥ `k` robust z-scores
    below the peer median. Needs ≥ `min_peers` same-sport in-band peers, else left unflagged (insufficient).
    Mutates the opps in place (idempotent — every row is reset first); NEVER read by executable
    classify/bucket/rank. Returns the same list. Defaults pulled from config."""
    band_tol_c = config.PEER_BAND_TOLERANCE_C if band_tol_c is None else band_tol_c
    min_peers = config.PEER_MIN_COUNT if min_peers is None else min_peers
    k = config.PEER_CHEAP_MAD_K if k is None else k
    rows = list(opps or [])
    for r in rows:                                   # reset (no stale carryover from a prior, wider set)
        r["cheap_cost"], r["cheap_ratio"] = False, False
    for b in rows:
        band = _num_or_none(b.get("display_spread_c"))
        if band is None:
            continue
        sport = b.get("sport")
        peers = [p for p in rows if p is not b and p.get("sport") == sport
                 and _num_or_none(p.get("display_spread_c")) is not None
                 and abs(_num_or_none(p.get("display_spread_c")) - band) <= band_tol_c]
        if len(peers) < min_peers:
            continue                                 # insufficient same-sport peers → not judged
        b["cheap_cost"] = _peer_cheap(_overpay_c(b), [_overpay_c(p) for p in peers], k)
        b["cheap_ratio"] = _peer_cheap(_num_or_none(b.get("spread_over_child")),
                                       [_num_or_none(p.get("spread_over_child")) for p in peers], k)
    return rows


def risk_budget_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                    flash_ids: set[str] | None = None) -> dict[str, Any]:
    """Display row for the risk-budget table: leads with the convex economics (max loss / max profit /
    upside:risk); worst-case ROC is a labelled secondary, never the headline (it's honestly negative)."""
    wc, bc = o.get("worst_case_profit_c"), o.get("best_case_profit_c")
    _r2 = lambda x: None if _num_or_none(x) is None else round(x, 2)   # noqa: E731 — display rounding
    _sized = _sized_at_budget(o)   # PR E: ($100-capped units, gross max-loss ¢, gross best-upside ¢) or None
    return _stamp_severity({
        "opportunity_id": o.get("opportunity_id"),
        "new": o.get("opportunity_id") in new_ids,   # bool → a coloured "NEW" badge in the cell slot
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "max_loss": None if _isna(wc) else -wc,
        "max_profit": None if _isna(bc) else bc,
        "ratio": _upside_risk(wc, bc),
        # Implied EV ¢ (chance-weighted ranking aid): implied payoff chance (band) − overpay. Cents-only,
        # None-safe. NOT an edge / NOT a probability model — see `_implied_ev_c`.
        "ev": _implied_ev_c(o),
        # PR M — legible decomposition of the same metric (SHOW BOTH): the market gap (pp, = display_spread),
        # the breakeven chance %, their difference (== ev for the 2-leg spread), and a descriptive signal
        # class so negative/inverted rows are flagged and never read as a "chance".
        "breakeven": _breakeven_pct(o),
        "gap_vs_be": _gap_vs_breakeven_pp(o),
        "signal": _signal_class(o),
        # Phase 1 likelihood + comparability (display-only; never read by bucket_of / _rank_key). The
        # conditional chance is the headline likelihood; firm_gap is a conservative tradable-side GAP in ¢
        # (NOT a % — a firm % reads as a tradable probability), with firm_pct surfaced only in the tooltip
        # when positive; midpoint_only / wide_basis drive honesty badges; cost_per_pp pairs with gap_vs_be
        # (ordered AFTER it in the table).
        "cond_success": _cond_success_pct(o),
        # P(child | parent) = child/parent — the complement of cond_success (the two sum to 100); the
        # market-implied chance the deeper outcome ALSO happens given the broader is reached. Display-only.
        "cond_child": _cond_child_pct(o),
        "firm_gap": _firm_spread_c(o),
        "firm_pct": _firm_success_pct(o),
        "midpoint_only": _optimistic_only(o),
        "wide_basis": "wide" in str(o.get("comp_quote_quality") or "").lower(),
        "parent_over_maxloss": _parent_over_maxloss(o),
        "flags": _rb_flags(o),
        # PR E — trader columns (display-only): resolution kind, the payoff zone in words, top-of-book
        # fillable size, worst-leg quote quality, and a $100 gross allocation's units / max loss $ / best
        # upside $ (capped by the book). All blank when their inputs are missing.
        "resolution": "Vertical" if o.get("resolution_mode") == "vertical" else "Calendar",
        "wins_if": _wins_if(o),
        # PR F — peer-cheapness badge (same-sport peers at a similar implied chance; display-only). Blank
        # when not flagged / insufficient peers. Set by flag_peer_cheapness() over the bounded-loss set.
        "cheap": ", ".join(lbl for lbl, on in (("cost", o.get("cheap_cost")), ("ratio", o.get("cheap_ratio")))
                           if on),
        "max_units": _num_or_none(o.get("exec_min_size")),
        "quote_health": str(o.get("comp_quote_quality") or ""),
        "units_100": _sized[0] if _sized else None,
        "loss_100": round(_sized[1] / 100, 1) if _sized else None,    # gross max loss at $100, in dollars
        "upside_100": round(_sized[2] / 100, 1) if _sized else None,  # gross best upside at $100, in dollars
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


def speculative_explainer(o: dict[str, Any]) -> list[tuple[str, str]]:
    """Plain-English decision lines for a bounded-loss (risk_budget) candidate, for the detail panel:
    Can-I-lose-money / Wins-big-if / Why-ranked-here / Why-skip. [] for non-risk-budget opps. Display-only,
    honest: a bet (not an edge), gross, top-of-book, Uncalibrated."""
    if o.get("bucket") != "risk_budget":
        return []
    wc = _num_or_none(o.get("worst_case_profit_c"))
    gap, be, gvb = _num_or_none(o.get("display_spread_c")), _breakeven_pct(o), _gap_vs_breakeven_pp(o)
    sig, wins = _signal_class(o), _wins_if(o)
    lines: list[tuple[str, str]] = [
        ("Can I lose money?", f"Yes — a bet, not an edge. The loss is CAPPED at the overpay "
                              f"({'—' if wc is None else f'{-wc:.0f}¢/unit'}); you lose it unless the payoff "
                              "zone happens."),
    ]
    if wins:
        lines.append(("Wins big if", wins))
    cond, firm_gap = _cond_success_pct(o), _firm_spread_c(o)
    lines.append(("Chance of success (display-implied)",
                  f"If reached: {'—' if cond is None else f'{cond:g}%'} (conditional, vig-aware, "
                  f"uncalibrated). Firm success gap: {'—' if firm_gap is None else f'{firm_gap:g}¢'} "
                  "(parent bid − child ask; ≤ 0 ⇒ not confirmed by firm quotes)."))
    lines.append(("Why ranked here",
                  f"Signal: {sig}. Market gap {'—' if gap is None else f'{gap:g}'}pp vs breakeven "
                  f"{'—' if be is None else f'{be:g}'}% → gap-vs-breakeven "
                  f"{'—' if gvb is None else f'{gvb:g}'}pp (Uncalibrated, gross, top-of-book)."))
    skip = []
    if sig in ("Inverted / diagnostic", "Data quality"):
        skip.append("the displayed prices are inverted or incomplete — treat as diagnostic, not a bet")
    elif gvb is not None and gvb <= 0:
        skip.append("the market prices the payoff zone at/below its breakeven — no quote-implied edge")
    if _optimistic_only(o):
        skip.append("positive only on DISPLAY (midpoint) prices — the firm bid/ask basis does not confirm a "
                    "success zone (Midpoint-only); treat as review-only")
    if "wide" in str(o.get("comp_quote_quality") or "").lower():
        skip.append("at least one leg quote is Wide/Very-wide, so the displayed number may decay or be "
                    "untradeable (Wide basis)")
    skip.append("metrics are gross & UNCALIBRATED (fees, full-depth fill, outcome calibration not modeled); "
                "doing nothing avoids the capped loss")
    lines.append(("Why skip / doing nothing may be better", "; ".join(skip)))
    return lines


def near_miss_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                  flash_ids: set[str] | None = None) -> dict[str, Any]:
    """Display row for the near-miss watchlist: the cost, the overpay (= guaranteed bundle loss), and the
    flat-loss note. Watchlist only — never frames it as an edge, and never surfaces tradable_now (the
    bundle is a guaranteed gross loss, not a placeable trade)."""
    g = o.get("exec_gap_c")
    return {
        "opportunity_id": o.get("opportunity_id"),
        "new": o.get("opportunity_id") in new_ids,   # bool → a coloured "NEW" badge in the cell slot
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),   # PR B: one-shot green flash this snapshot
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "cost": o.get("cost_c"),
        "overpay": None if _isna(g) else -g,
        "watchlist": "Watchlist",
        "note": o.get("settlement_caveat") or "",
    }


# --- NO-anchored structures ("Cheap bounded-loss NO fades") — opt-in, speculative, never actionable -----
# A cheap convex fade anchored on a Buy-NO leg: a single Buy NO (OUTRIGHT, a directional fade watchlist) or
# a Buy NO deeper + Buy YES broader band (BAND, bounded loss = cost − 100). Pure band-filter + display-row
# builders over the membership/threshold-filtered `view`. Ranking leads with the BOUNDED DOWNSIDE and the
# BREAKEVEN chance (not convexity — convexity alone overranks 1¢ longshots); cheapness stays a filter + a
# column + the final tiebreak. Integer cents throughout. NEVER read by bucket_of / _rank_key.
def _is_band(o: dict[str, Any]) -> bool:
    return o.get("relationship_type") == "no_structure_band"


def no_structure_view(opps: Iterable[dict[str, Any]] | None, *, max_loss_c: float,
                      max_buy_no_c: float = 0, kind: str = "all",
                      good_quote_only: bool = True) -> list[dict[str, Any]]:
    """NO-anchored structures whose bounded max-loss ≤ `max_loss_c` ¢. `kind` ∈ {all, band, outright}
    (band == the ladder-bounded structures; outright == single Buy-NO watchlist). `max_buy_no_c` (0 = off)
    caps the Buy-NO leg cost — the "cheapest NO" gate. `good_quote_only` keeps only Tight/OK books (the
    default; the wide/one-sided cheap NOs are usually stale, not opportunities). A row missing a gated field
    is hidden only when that filter is active."""
    out: list[dict[str, Any]] = []
    for o in (opps or []):
        if o.get("bucket") != "no_structure":
            continue
        if kind == "band" and not _is_band(o):
            continue
        if kind == "outright" and _is_band(o):
            continue
        wc = o.get("worst_case_profit_c")
        if _isna(wc):
            continue
        if max(0.0, -wc) > max_loss_c:                # bounded max-loss ¢ (band: cost−100; outright: cost)
            continue
        if max_buy_no_c:
            no = _num_or_none(o.get("action_2_price_c"))   # the Buy-NO leg cost
            if no is None or no > max_buy_no_c:
                continue
        if good_quote_only and str(o.get("comp_quote_quality") or "") not in ("Tight", "OK"):
            continue
        out.append(o)
    return out


def _no_structure_order(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within-section order (improves on convexity-first, which overranks tiny longshots): lowest bounded
    max-loss first, then lowest breakeven chance, then highest bonus profit, then cheapest Buy-NO, then a
    stable id tiebreak. Cheapness leads the FILTER + the column; the SORT leads with downside/plausibility."""
    def key(o: dict[str, Any]) -> tuple:
        wc = _num_or_none(o.get("worst_case_profit_c"))
        max_loss = max(0.0, -wc) if wc is not None else float("inf")
        be = _breakeven_pct(o)
        be = be if be is not None else float("inf")
        bonus = _num_or_none(o.get("best_case_profit_c"))
        bonus = bonus if bonus is not None else float("-inf")
        no = _num_or_none(o.get("action_2_price_c"))
        no = no if no is not None else float("inf")
        return (max_loss, be, -bonus, no, o.get("opportunity_id") or "")
    return sorted(group, key=key)


def no_structure_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                     flash_ids: set[str] | None = None) -> dict[str, Any]:
    """Display row for the NO-fades table: leads with the Buy-NO cost + bounded max-loss + breakeven chance;
    convexity is a visible-but-secondary column. Honest: a cheap bounded fade, NOT an edge."""
    band = _is_band(o)
    cost = _num_or_none(o.get("cost_c"))
    bc = _num_or_none(o.get("best_case_profit_c"))
    wc = _num_or_none(o.get("worst_case_profit_c"))
    best_payout = (bc + cost) if (bc is not None and cost is not None) else None
    convexity = round(best_payout / cost, 2) if (best_payout is not None and cost) else None
    no_c = _num_or_none(o.get("action_2_price_c"))
    parent_c = _num_or_none(o.get("action_1_price_c"))
    wins = _wins_if(o) if band else (f"{o.get('detail') or 'the outcome'} does NOT happen")
    _sized = _sized_at_budget(o)
    return _stamp_severity({
        "opportunity_id": o.get("opportunity_id"),
        "new": o.get("opportunity_id") in new_ids,
        "_change": (changes or {}).get(o.get("opportunity_id"), ""),
        "_flash": o.get("opportunity_id") in (flash_ids or set()),
        "kind": "Band" if band else "Outright",
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "", "detail": o.get("detail") or "",
        "wins_if": wins,
        "buy_no": no_c,                                # the cheap-NO anchor cost
        "parent_yes": parent_c,                        # the bounding Buy-YES cost (blank for an outright)
        "cost": cost,
        "max_loss": None if wc is None else max(0.0, -wc),
        "breakeven": _breakeven_pct(o),                # min payoff chance % the bounded loss needs (gross)
        "bonus_profit": bc,                            # net gain in the win state (band: 200−cost)
        "convexity": convexity,                        # best payout ÷ cost — secondary, not the headline
        "max_units": _num_or_none(o.get("exec_min_size")),
        "loss_100": round(_sized[1] / 100, 1) if _sized else None,
        "upside_100": round(_sized[2] / 100, 1) if _sized else None,
        "quote_health": str(o.get("comp_quote_quality") or ""),
        "caveat": "; ".join(p for p in (o.get("settlement_caveat"), o.get("blocked_reason"))
                            if isinstance(p, str) and p),
    }, o)


def no_structure_explainer(o: dict[str, Any]) -> list[tuple[str, str]]:
    """Plain-English decision lines for the detail panel of a NO-anchored structure. For a band, the 3-state
    payoff is reused from `consistency.scenario_payoffs` (the same enumeration the risk-budget panel uses)."""
    if o.get("bucket") != "no_structure":
        return []
    band = _is_band(o)
    wc = _num_or_none(o.get("worst_case_profit_c"))
    be = _breakeven_pct(o)
    wins = _wins_if(o) if band else f"{o.get('detail') or 'the outcome'} does not happen"
    lines: list[tuple[str, str]] = [
        ("What is this?", ("A cheap bounded fade — Buy NO the deeper rung, Buy YES the broader rung that "
                           "contains it, so you win the band 'reaches the broader stage but not the deeper "
                           "one'. NOT an edge, not arbitrage.") if band else
                          ("A single cheap Buy NO — a directional fade (you win if the outcome does NOT "
                           "happen). A watchlist idea, NOT an edge: it's cheap because the market thinks "
                           "the YES is very likely.")),
        ("Can I lose money?", f"Yes — capped at {'—' if wc is None else f'{max(0.0, -wc):.0f}¢/unit'} "
                              f"(the Buy-NO {'overpay' if band else 'cost'}). You lose it unless the fade "
                              "pays."),
        ("Wins if", wins),
        ("Breakeven chance", f"{'—' if be is None else f'{be:g}%'} — the minimum chance the win state needs "
                             "before fees/slippage (gross, top-of-book, uncalibrated)."),
    ]
    if band:
        payoff = consistency.scenario_payoffs({**o, "status": "RISK_BUDGET_CANDIDATE"},
                                              units=o.get("exec_min_size"))
        if payoff:
            for s in payoff["scenarios"]:
                pc = s.get("profit_c")
                lines.append((f"  · {s['label']}", "—" if pc is None else f"{pc:+.0f}¢/unit"))
    return lines


# World Cup Qualifier Setups — human labels for the setup types (two exact-order tiers + game support).
_SETUP_TYPE_LABEL = {
    "exact_order_top2_bundle": "Diagnostic top-two bundle",
    "exact_order_top2_relative_value": "Speculative top-two bundle",
    "exact_order_top2_proxy": "Top-two bundle (legacy)",   # stale snapshots
    "game_support_signal": "Game support (heuristic)",
}


def _premium_display(prem: Any) -> str:
    """Sign-aware text for the 'cheaper vs qualifier' column. Positive ⇒ the bundle is cheaper than the
    direct qualifier; negative ⇒ more expensive. Blank when absent. (The numeric value drives sorting;
    this string is display-only.)"""
    if _num_or_none(prem) is None:
        return ""
    p = int(prem)
    if p > 0:
        return f"+{p}¢ cheaper"
    if p < 0:
        return f"{p}¢ more expensive"
    return "0¢ level"


# Quote-quality sort order, best → worst, matching data.quote_quality (Tight/OK/Wide/Very wide/One-sided/
# No quote/Crossed). "Unknown" is a DISPLAY/SORT FALLBACK ONLY for a blank or unrecognized quality — it is
# never a real quote_quality value and is never written back into engine opportunity / contract data.
QUOTE_QUALITY_SORT_ORDER = ["Tight", "OK", "Wide", "Very wide", "One-sided", "No quote", "Crossed",
                            "Unknown"]
_QUOTE_QUALITY_RANK = {q: i + 1 for i, q in enumerate(QUOTE_QUALITY_SORT_ORDER)}


def quote_quality_rank(q: Any) -> int:
    """1..8 rank for the custom quote-quality sort (best Tight=1 … worst Crossed=7); a blank or
    unrecognized value falls back to "Unknown" (8). Drives the numeric sort field while the column
    still DISPLAYS the label string (see `qualifier_row`)."""
    return _QUOTE_QUALITY_RANK.get(str(q or "").strip(), _QUOTE_QUALITY_RANK["Unknown"])


def _quote_label(q: Any) -> str:
    """The quote-quality label shown in the cell — the real value, or "Unknown" when blank."""
    return str(q or "").strip() or "Unknown"


def _bundle_leg_price_stats(opp: dict[str, Any]) -> dict[str, Any]:
    """Pure display stats over the bundle legs' ask prices (¢): highest, median, range. Uses
    `_bundle_legs` so a stale 13-leg snapshot's legacy comparator leg is excluded. Returns all-None when
    there are no valid integer-cent prices (empty/partial legs) — never raises. Display-only; the median
    may be x.5 and never feeds economic comparison or actionability."""
    prices = [int(p) for p in (lg.get("price_c") for lg in _bundle_legs(opp))
              if _num_or_none(p) is not None]
    if not prices:
        return {"highest_leg": None, "median_leg": None, "range_leg": None}
    return {"highest_leg": max(prices),
            "median_leg": statistics.median(prices),   # may be x.5 — display only
            "range_leg": max(prices) - min(prices)}


def _bundle_leg_health(opp: dict[str, Any],
                       leg_lookup: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Tri-state per-leg health over the bundle legs, sourced from the contract snapshot (`leg_lookup`:
    ticker -> stored contract row). MISSING EVIDENCE IS NEVER A FINDING: a count is None (blank) when NO
    leg resolves, and `all_legs_active` is "Unknown" unless evidence is conclusive. No-quote counts the
    "No quote" state ONLY (Crossed / One-sided are distinct). Pure; display-only; exact-order rows only."""
    lookup = leg_lookup or {}
    legs = _bundle_legs(opp)
    statuses: list[str] = []
    qualities: list[str] = []
    spreads: list[float] = []
    for lg in legs:
        tkr = str(lg.get("ticker") or "")
        c = lookup.get(tkr) if tkr else None
        if c is None:
            continue
        statuses.append(str(c.get("status") or ""))
        qualities.append(str(c.get("quote_quality") or ""))
        sp = _num_or_none(c.get("spread_cents"))
        if sp is not None:
            spreads.append(sp)
    if not statuses:                                   # nothing resolved → no finding, just blanks
        return {"inactive_legs": None, "no_quote_legs": None, "worst_leg_spread": None,
                "all_legs_active": "Unknown"}
    inactive = sum(1 for s in statuses if s and s != "active")
    no_quote = sum(1 for q in qualities if q == "No quote")
    all_resolved = len(statuses) == len(legs)
    all_active = "No" if inactive > 0 else ("Yes" if all_resolved else "Unknown")
    return {"inactive_legs": inactive, "no_quote_legs": no_quote,
            "worst_leg_spread": (max(spreads) if spreads else None), "all_legs_active": all_active}


def _comparator_evidence(comparator_contract: dict[str, Any] | None) -> dict[str, Any]:
    """Comparator (qualifier `ticker_2`) spread + market status from the contract snapshot — blank /
    "" when the ticker doesn't resolve. The comparator QUOTE QUALITY itself comes from the
    opportunity-level field (precedence), NOT from here."""
    c = comparator_contract
    if not isinstance(c, dict):
        return {"comparator_spread": None, "qualifier_market_status": ""}
    return {"comparator_spread": _num_or_none(c.get("spread_cents")),
            "qualifier_market_status": str(c.get("status") or "")}


def _caveat_badges(o: dict[str, Any]) -> list[dict[str, str]]:
    """Compact caveat chips (replacing the long Note), deterministic order. The two STRUCTURAL badges
    apply to exact-order top-two rows only (the qualifier is a comparator, never a leg; the bundle pays
    only if the team finishes top two). "Settlement caveat" is conditional. Each chip carries a tooltip
    for accessibility. Wording is conservative — no arbitrage/hedge/locked/riskless."""
    badges: list[dict[str, str]] = []
    if _is_exact_order_bundle(o):
        badges.append({"label": "Comparator only",
                       "tooltip": "The direct qualifier market is a comparator, not a trade leg — the "
                                  "bundle is the exact-order Buy-YES legs only."})
        badges.append({"label": "Top-two only",
                       "tooltip": "Pays only if the team finishes top two; a best-third-place "
                                  "qualification can make the qualifier pay while this bundle pays zero."})
    sc = o.get("settlement_caveat")
    if isinstance(sc, str) and sc:
        badges.append({"label": "Settlement caveat",
                       "tooltip": "Gross, top-of-book, settlement-unverified — review the settlement "
                                  "rules before treating this as an edge."})
    return badges


def order_qualifier_rows(opps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """In-section ordering for the Qualifier-setups table (rows carry no exec_gap to rank globally). The
    SETUP TIER stays outermost (Speculative → Diagnostic → game-support → other) so the two row-families
    don't interleave; then the requested keys: (1) cheaper-vs-qualifier desc, (2) worst-bundle quote
    best→worst, (3) comparator quote best→worst, (4) max units desc, (5) bundle cost asc; ties broken by
    name. Pure; keys read opp-level fields (this runs BEFORE `qualifier_row` maps them). A missing numeric
    value always sorts last in either direction."""
    def _num_key(v: Any, *, descending: bool = False) -> float:
        n = _num_or_none(v)
        if n is None:
            return float("inf")                        # missing → always last, both directions
        return -float(n) if descending else float(n)

    def key(o: dict[str, Any]) -> tuple:
        if str(o.get("status") or "") == "SPECULATIVE_TOP2_RELATIVE_VALUE":
            tier = 0
        elif _is_exact_order_bundle(o):
            tier = 1
        elif str(o.get("source") or "") == "game_support":
            tier = 2
        else:
            tier = 3
        return (tier,
                _num_key(o.get("qualifier_vs_top2_premium_c"), descending=True),   # cheaper first
                quote_quality_rank(o.get("worst_bundle_quote_quality")),           # best → worst
                quote_quality_rank(o.get("comparator_quote_quality")),             # best → worst
                _num_key(o.get("top2_max_units"), descending=True),                # more units first
                _num_key(o.get("synthetic_top_two_cost_c")),                       # cheaper bundle first
                str(o.get("name") or ""))
    return sorted(list(opps or []), key=key)


def qualifier_row(o: dict[str, Any], new_ids: set[str], changes: dict[str, str] | None = None,
                  flash_ids: set[str] | None = None, *,
                  leg_lookup: dict[str, dict[str, Any]] | None = None,
                  comparator_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Display row for the Qualifier-setups table. No gross-edge / ROI / size / profit (a non-executable,
    Review-only signal). TWO ROW-FAMILIES: the top-two economics, leg-price stats, leg-health and the two
    structural caveat badges are EXACT-ORDER only; game-support rows leave them blank and carry only the
    (hidden) heuristic support score. Numeric columns hold raw numbers (cell slots format display only);
    quote-quality columns sort on the `*_rank` field while showing the `*_label`. `leg_lookup` /
    `comparator_contract` (ticker -> stored contract row) enrich per-leg / comparator evidence with
    TRI-STATE blanks when a ticker is unresolved — never inferred."""
    is_exact = _is_exact_order_bundle(o)
    oid = o.get("opportunity_id")
    legs = _bundle_legs(o)
    worst_q = o.get("worst_bundle_quote_quality") if is_exact else None
    comp_q = o.get("comparator_quote_quality") if is_exact else None
    stats = (_bundle_leg_price_stats(o) if is_exact
             else {"highest_leg": None, "median_leg": None, "range_leg": None})
    health = (_bundle_leg_health(o, leg_lookup) if is_exact
              else {"inactive_legs": None, "no_quote_legs": None, "worst_leg_spread": None,
                    "all_legs_active": "Unknown"})
    comp = (_comparator_evidence(comparator_contract) if is_exact
            else {"comparator_spread": None, "qualifier_market_status": ""})
    tickers = [str(lg.get("ticker") or "") for lg in legs if lg.get("ticker")]
    row = {
        "opportunity_id": oid,
        "new": oid in new_ids,                       # bool → a coloured "NEW" badge in the cell slot
        "_change": (changes or {}).get(oid, ""),
        "_flash": oid in (flash_ids or set()),
        "sport": o.get("sport_label") or o.get("sport") or "",
        "name": o.get("name") or "",
        "setup": _SETUP_TYPE_LABEL.get(o.get("setup_type") or "", o.get("setup_type") or "Diagnostic"),
        # Economics — raw numeric → numeric sort; cell slots format display only. Exact-order only.
        "qualifier": _num_or_none(o.get("qualifier_yes_ask_c")),
        "cost": _num_or_none(o.get("synthetic_top_two_cost_c")) if is_exact else None,
        "premium": _num_or_none(o.get("qualifier_vs_top2_premium_c")) if is_exact else None,
        "premium_display": _premium_display(o.get("qualifier_vs_top2_premium_c")) if is_exact else "",
        "if_top2": _num_or_none(o.get("top2_net_if_top2_c")) if is_exact else None,
        "if_not_top2": _num_or_none(o.get("top2_loss_if_not_top2_c")) if is_exact else None,
        "max_units": _num_or_none(o.get("top2_max_units")) if is_exact else None,
        # Quote quality — the rank sorts, the label displays.
        "worst_leg_quote_rank": quote_quality_rank(worst_q if is_exact else "Unknown"),
        "worst_leg_quote_label": _quote_label(worst_q) if is_exact else "",
        "comparator_quote_rank": quote_quality_rank(comp_q if is_exact else "Unknown"),
        "comparator_quote_label": _quote_label(comp_q) if is_exact else "",
        "legs": len(legs) if is_exact else _num_or_none(o.get("n_legs")),
        "review_status": o.get("tradable_now") or "Diagnostic only",   # never "Actionable"
        # Caveat — compact structural/settlement chips replace the long note; full prose is the hidden col.
        "caveat_badges": _caveat_badges(o),
        "caveat": o.get("settlement_caveat") or "",
        # Game-support heuristic (hidden-optional) — blank for exact-order rows.
        "support": _num_or_none(o.get("ask_support_score_total_c")) if not is_exact else None,
        # Leg-price stats (exact-order only).
        "highest_leg": stats["highest_leg"],
        "median_leg": stats["median_leg"],
        "range_leg": stats["range_leg"],
        # Leg health (tri-state) + comparator evidence.
        "inactive_legs": health["inactive_legs"],
        "no_quote_legs": health["no_quote_legs"],
        "wide_legs": _num_or_none(o.get("wide_bundle_leg_count")) if is_exact else None,
        "worst_leg_spread": health["worst_leg_spread"],
        "all_legs_active": health["all_legs_active"],
        "comparator_spread": comp["comparator_spread"],
        "qualifier_market_status": comp["qualifier_market_status"],
        # Identity / reference (hidden-optional).
        "market_tickers": ", ".join(tickers),
        "comparator_ticker": o.get("ticker_2") or "",
        "tournament_key": o.get("tournament") or "",
    }
    return _stamp_severity(row, o)


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


def backlog_event_row(b: dict[str, Any], tz: str) -> dict[str, Any]:
    """One durable-interval-backlog row (v4) shaped for the table. `category` is the tracked category
    label; an OPEN interval shows 'still open' for the left time."""
    dur = b.get("duration_s")
    label = config.BACKLOG_CATEGORY_LABELS.get(b.get("category"), b.get("category") or "")
    return {
        "category": label, "sport": b.get("sport") or "", "name": b.get("name") or "",
        "first_seen": ts_disp(b.get("first_seen_ts"), tz),
        "left": "still open" if b.get("is_open") else ts_disp(b.get("left_ts"), tz),
        "mins": round(dur / 60, 1) if isinstance(dur, (int, float)) else None,
        "peak_roi": b.get("peak_roi_pct"), "last_status": b.get("last_status") or "",
    }


def _exact_order_explanation(opp: dict[str, Any], *, long_short: bool, show_ids: bool) -> list[str]:
    """The exact-order top-two bundle explanation body (the 12 filtered legs + trade/comparator economics
    + shared caveat tail). Sign-aware; the qualifier is a comparator, never a trade leg. Pure."""
    legs = _bundle_legs(opp)
    out = [f"Leg {i + 1}: {frame_sides(leg.get('text'), long_short) or '—'}"
           for i, leg in enumerate(legs)]
    name = opp.get("name") or "this team"
    synth = opp.get("synthetic_top_two_cost_c")
    q = opp.get("qualifier_yes_ask_c")
    prem = opp.get("qualifier_vs_top2_premium_c")
    net = opp.get("top2_net_if_top2_c")
    loss = opp.get("top2_loss_if_not_top2_c")
    sign = "cheaper" if (prem or 0) > 0 else ("more expensive" if (prem or 0) < 0 else "level")
    out.append(f"Trade: Buy YES on the 12 exact-order outcomes where {name} finishes top two — "
               f"cost {'—' if _isna(synth) else f'{int(synth)}¢'}")
    if not _isna(q):
        prem_s = "—" if _isna(prem) else f"{abs(int(prem))}¢ {sign}"
        out.append(f"Comparator: {name} qualify YES @ {int(q)}¢   ·   vs bundle: {prem_s}")
    out.append(f"If top two: {'—' if _isna(net) else f'{int(net):+d}¢'}   ·   "
               f"If not top two: {'—' if _isna(loss) else f'-{int(loss)}¢'}")
    out.append(f"Max units: {opp.get('top2_max_units')}   ·   "
               f"Worst leg: {opp.get('worst_bundle_quote_quality') or '—'} "
               f"({opp.get('wide_bundle_leg_count')} wide)   ·   "
               f"Comparator quote: {opp.get('comparator_quote_quality') or '—'}")
    out.append(f"Tradable now: {opp.get('tradable_now')}   ·   Relationship: {opp.get('relationship_type')}")
    if opp.get("settlement_caveat"):
        out.append(f"Settlement caveat: {opp.get('settlement_caveat')}")
    if opp.get("blocked_reason"):
        out.append(f"Caveat: {opp.get('blocked_reason')}")
    if show_ids:
        out.append(f"id {opp.get('opportunity_id')} · {opp.get('ticker_1')} / {opp.get('ticker_2')}")
    return out


def explanation_lines(opp: dict[str, Any], *, show_ids: bool = False,
                      long_short: bool = False) -> list[str]:
    """The text content of the explanation panel for one opportunity (pure → unit-testable). `long_short`
    re-words the buy legs to Long/Short YES at display time (see frame_sides)."""
    lines = [
        f"{opp.get('sport_label') or opp.get('sport')} · {opp.get('name')}",
        f"{opp.get('source')} · {opp.get('detail')} · {opp.get('tournament')}",
    ]
    if _is_exact_order_bundle(opp):
        # Dedicated path, taken BEFORE the generic leg enumeration + economics line, so a top-two bundle
        # never shows a stale "Leg 13" or a `Cost: None / Gross edge: None` line. The qualifier is a
        # COMPARATOR, not a leg (legacy comparator legs are filtered by `_bundle_legs`).
        return lines + _exact_order_explanation(opp, long_short=long_short, show_ids=show_ids)
    legs = opp.get("legs")
    if isinstance(legs, list) and legs:                      # N-leg (synthetic bundle): list every leg
        lines += [f"Leg {i + 1}: {frame_sides(leg.get('text'), long_short) or '—'}"
                  for i, leg in enumerate(legs)]
    else:                                                     # 2-leg shapes use the positional fields
        lines += [f"Leg 1: {frame_sides(opp.get('action_1_text'), long_short) or '—'}",
                  f"Leg 2: {frame_sides(opp.get('action_2_text'), long_short) or '—'}"]
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
    # Containment conditional (display-only, market-implied): given the broader outcome is reached, what
    # the market prices the deeper outcome at TODAY. Gated on both display outrights present, parent > 0,
    # and a non-inverted pair — so it appears only for containment rows (dutch/synthetic carry no parent/
    # child outrights). A current implied conditional, NOT a promise about the future traded price.
    _pc, _cc = _num_or_none(opp.get("parent_display_c")), _num_or_none(opp.get("child_display_c"))
    if _pc is not None and _cc is not None and _pc > 0 and _cc <= _pc:
        _deeper = round(_cc / _pc * 100, 1)
        lines.append(
            f"Conditional (market-implied): given the broader outcome is reached, the market prices the "
            f"deeper outcome at about {_deeper}% today, and the success zone (broader-but-not-deeper) at "
            f"{round(100 - _deeper, 1)}%. Unconditional success chance = the raw gap {round(_pc - _cc, 1)}pp.")
        lines.append(
            "A current implied conditional from display prices — not de-vigged, not fair value, not "
            "executable fills, and not a promise about the future traded price; information, time, and "
            "book width move it, and wide / stale / one-sided books make it misleading.")
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
    """Thresholds spare the Actionable bucket, dutch-book rows, and the qualifier-setup diagnostics (which
    carry no firm size/quote to threshold on — membership filters still apply). Mirrors the Streamlit split."""
    return (o.get("bucket") in ("actionable", "qualifier_setup")
            or o.get("source") == "dutch_book")


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
                 "risk_budget": "Speculative", "near_miss": "Near-miss", "qualifier_setup": "Qualifier setups",
                 "no_structure": "Cheap NO fades"}
_BUCKET_ORDER = ["actionable", "review_signal", "blocked", "risk_budget", "near_miss", "qualifier_setup",
                 "no_structure"]


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
RANK_MODES = {"blended": "Blended", "edge": "Per-unit edge ¢",
              "total_profit": "Max gross profit (top-of-book)", "spread_upside": "Spread upside",
              "spread_ratio": "Outright + spread", "implied_ev": "Implied EV"}
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
    """Estimated Kalshi GENERAL TAKER fee for `contracts` at `price_c` cents, in integer cents (rounded up):
    ``ceil(0.07 · C · P · (1−P))`` — matches Kalshi's published general formula. This is an ESTIMATE, not
    realized net P&L: special-schedule markets, maker fills (resting orders), centicent rounding, and series
    fee changes may differ. The authoritative per-series source is Kalshi's ``GET /series/fee_changes`` (not
    wired — display-only estimate by design). Zero at the 0¢/100¢ endpoints; 0 for non-positive/invalid C."""
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


def _implied_ev_c(o: dict[str, Any]) -> float | None:
    """Implied EV in cents for a bounded-loss row: the implied chance of the convex payoff (the
    parent−child display gap `display_spread_c`, in cents = %) MINUS the overpay (= the capped max loss,
    −worst_case_profit_c). A RANKING AID built from DISPLAYED prices treated as-if true — gross,
    top-of-book, market-implied probability; NOT a guarantee and NOT a probability model. Returns None when
    either input is missing (never silently 0). Defined in cents only — no cents/probability unit mixing."""
    band_c = _num_or_none(o.get("display_spread_c"))
    wc = _num_or_none(o.get("worst_case_profit_c"))
    if band_c is None or wc is None:
        return None
    return band_c - max(0.0, -wc)        # band_c − overpay_c  (overpay = the capped max loss)


def _breakeven_pct(o: dict[str, Any]) -> float | None:
    """Breakeven payoff chance % for a bounded-loss bet: `max_loss / (max_loss + max_profit) × 100`. For a
    two-leg containment spread `max_loss + max_profit ≈ 100`, so this ≈ the max loss in ¢ — the minimum
    chance the convex payoff zone needs before the bet is worth its overpay. None when inputs are missing or
    the spread is degenerate (denominator ≤ 0)."""
    wc, bc = _num_or_none(o.get("worst_case_profit_c")), _num_or_none(o.get("best_case_profit_c"))
    if wc is None or bc is None:
        return None
    max_loss, max_profit = max(0.0, -wc), max(0.0, bc)
    denom = max_loss + max_profit
    return round(max_loss / denom * 100, 1) if denom > 0 else None


def _gap_vs_breakeven_pp(o: dict[str, Any]) -> float | None:
    """Market gap (pp) MINUS the breakeven chance — the legible twin of Implied EV (equal for the canonical
    two-leg spread, where breakeven ≈ max loss). Positive ⇒ displayed prices imply a better chance of the
    payoff zone than the bet needs. None when either input is missing."""
    gap, be = _num_or_none(o.get("display_spread_c")), _breakeven_pct(o)
    return None if (gap is None or be is None) else round(gap - be, 1)


# --- Phase 1 likelihood / comparability metrics (display-only; never read by bucket_of / _rank_key) ------
# Conditional success chance, a conservative firm-side gap, the midpoint-vs-firm basis flag, and the
# "cost per implied pp" ratio. All None-safe and FAIL CLOSED (return None, never 0.0, on a degenerate book)
# so a missing/inverted quote never renders as a real probability. "display-implied" = read off display
# prices treated as-if true: gross, top-of-book, uncalibrated — a comparison aid, not a calibrated model.
def _cond_success_pct(o: dict[str, Any]) -> float | None:
    """Conditional success chance P(success zone | parent reached) = 1 − child/parent = spread_over_parent,
    as a %. Less sensitive to common multiplicative vig (it cancels in the child/parent ratio) but still
    quote-dependent and uncalibrated. Fail-closed: None when the ratio is missing or ≤ 0."""
    sop = _num_or_none(o.get("spread_over_parent"))
    return None if (sop is None or sop <= 0) else round(sop * 100, 1)


def _cond_child_pct(o: dict[str, Any]) -> float | None:
    """P(child | parent) = child/parent, as a % — the market-implied chance the DEEPER outcome occurs
    GIVEN the broader one is reached (the complement of `_cond_success_pct`; the two sum to 100). Read off
    DISPLAY prices: market-implied, gross, top-of-book, NOT de-vigged and NOT fair value — the ratio is
    only LESS sensitive to a common proportional overround, not free of it. Fail-closed: None when the
    parent outright is missing / ≤ 0 or the pair is inverted (child > parent → not a valid conditional;
    that's a display inconsistency, never shown as a chance)."""
    p = _num_or_none(o.get("parent_display_c"))
    c = _num_or_none(o.get("child_display_c"))
    if p is None or c is None or p <= 0 or c > p:
        return None
    return round(c / p * 100, 1)


def _firm_spread_c(o: dict[str, Any]) -> float | None:
    """Conservative firm-side success gap in cents: parent YES bid − child YES ask (the exit/realize sides
    the midpoint ignores). May be ≤ 0 — that IS the signal that a midpoint positive isn't tradable. None
    when either firm quote is absent (e.g. a pre-field snapshot)."""
    pb, ca = _num_or_none(o.get("parent_yes_bid_c")), _num_or_none(o.get("child_yes_ask_c"))
    return None if (pb is None or ca is None) else pb - ca


def _firm_success_pct(o: dict[str, Any]) -> float | None:
    """Firm-side conditional chance % — TOOLTIP ONLY, shown only when STRICTLY POSITIVE (a firm gap can be
    ≤ 0; a negative 'chance' is nonsense, so it's suppressed). None unless parent_yes_bid_c > 0 AND the firm
    gap > 0."""
    pb, fs = _num_or_none(o.get("parent_yes_bid_c")), _firm_spread_c(o)
    return round(fs / pb * 100, 1) if (pb is not None and pb > 0 and fs is not None and fs > 0) else None


def _optimistic_only(o: dict[str, Any]) -> bool:
    """True when the DISPLAY (midpoint) basis implies a positive success zone but the FIRM bid/ask basis does
    not (display_spread_c > 0 ≥ firm_spread_c) — drives the 'Midpoint-only' badge. False when the firm basis
    is missing (can't claim a mismatch) or is also positive."""
    gap, fs = _num_or_none(o.get("display_spread_c")), _firm_spread_c(o)
    return bool(gap is not None and gap > 0 and fs is not None and fs <= 0)


def _parent_over_maxloss(o: dict[str, Any]) -> float | None:
    """'Parent ÷ max loss': the parent's implied probability (the in-the-money chance the broader outcome
    happens, in ¢ = pp) divided by the MAX LOSS (= cost_c − 100, the overpay — the only at-risk capital).
    HIGHER = better (more in-the-money probability per cent actually at risk); deep-longshot parents sink.
    Fail-closed: None when the parent outright or cost is missing, or max loss (cost − 100) ≤ 0."""
    parent = _num_or_none(o.get("parent_display_c"))
    cost = _num_or_none(o.get("cost_c"))
    if parent is None or cost is None:
        return None
    max_loss = cost - 100
    if max_loss <= 0:
        return None
    return round(parent / max_loss, 2)


def _rb_flags(o: dict[str, Any]) -> list[dict[str, str]]:
    """Display-only honesty badges for a bounded-loss row: 'Midpoint-only' (the display basis implies a
    success zone the firm bid/ask basis does not) and 'Wide basis' (a leg quote is Wide/Very-wide). Pure
    caution chips — never read by bucket_of / _rank_key."""
    flags: list[dict[str, str]] = []
    if _optimistic_only(o):
        flags.append({"label": "Midpoint-only", "color": "warning",
                      "tooltip": "Positive on display (midpoint) prices, but the firm bid/ask basis does "
                                 "not confirm a success zone — treat as review-only."})
    if "wide" in str(o.get("comp_quote_quality") or "").lower():
        flags.append({"label": "Wide basis", "color": "grey-7",
                      "tooltip": "At least one leg quote is Wide/Very-wide; the displayed number may decay "
                                 "or be untradeable."})
    return flags


def _signal_class(o: dict[str, Any]) -> str:
    """Descriptive class for a bounded-loss row (display + ranking honesty; NOT an actionability threshold):
    Data quality (no display gap) / Inverted (deeper priced above broader — a negative gap, never shown as a
    "chance") / Candidate (gap beats breakeven) / Breakeven / Negative proxy. Computed from full-precision
    values so display rounding can't flip it."""
    gap = _num_or_none(o.get("display_spread_c"))
    if gap is None:
        return "Data quality"
    if gap < 0:
        return "Inverted / diagnostic"
    gvb = _gap_vs_breakeven_pp(o)
    if gvb is None:
        return "Data quality"
    if gvb > 0:
        return "Candidate"
    return "Breakeven" if gvb == 0 else "Negative proxy"


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


def _implied_ev_order(group: list[dict[str, Any]], is_risk: bool) -> list[dict[str, Any]]:
    """Chance-weighted order for risk-budget rows: highest IMPLIED EV first (implied payoff chance −
    overpay; see `_implied_ev_c`). This is the lens that distinguishes a high upside:risk at near-zero
    chance from a lower ratio that is far likelier to pay. A row missing either input sorts AFTER all
    scored rows (never treated as ev=0). Non-risk buckets have no convex payoff -> fall back to per-unit
    edge. RANKING AID only — gross, top-of-book, market-implied probability; never an edge."""
    if not is_risk:
        return sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or ""))

    def key(o: dict[str, Any]) -> tuple:
        ev = _implied_ev_c(o)
        if ev is None:                                  # no implied EV -> last, deterministic by id
            return (1, 0.0, o.get("opportunity_id") or "")
        return (0, -ev, o.get("opportunity_id") or "")  # highest implied EV first
    return sorted(group, key=key)


def _total_profit_order(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order by GROSS DEPLOYABLE PROFIT — per-unit edge × the executable (min-leg) size: the most you could
    put to work at the inside. So a thin-but-deep book (2¢ × 5000) outranks a fat-but-shallow one (5¢ × 1),
    which the per-unit modes invert. GROSS and TOP-OF-BOOK only — no fees, no depth past the inside (the
    mode label says so); it deliberately does NOT read any net-of-fees field. Rows missing edge or size sort
    last, deterministic by id. Engine bucketing/`scanner._rank_key` are untouched — this is a UI sort."""
    def key(o: dict[str, Any]) -> tuple:
        gap = _num_or_none(o.get("exec_gap_c"))
        size = _num_or_none(o.get("exec_min_size"))
        if gap is None or size is None:
            return (1, 0.0, -_edge(o), o.get("opportunity_id") or "")
        return (0, -(gap * size), -_edge(o), o.get("opportunity_id") or "")
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
        if bucket == "no_structure":
            # Independent of the global rank mode: a cheap-NO fade is ordered by bounded downside +
            # breakeven (see _no_structure_order), never by the executable-edge modes.
            out.extend(_no_structure_order(group))
            continue
        if mode == "total_profit":
            out.extend(_total_profit_order(group))
        elif mode == "spread_upside":
            out.extend(_spread_upside_order(group, is_risk))
        elif mode == "spread_ratio":
            out.extend(_spread_ratio_order(group, is_risk))
        elif mode == "implied_ev":
            out.extend(_implied_ev_order(group, is_risk))
        elif mode == "blended":
            out.extend(_blended_order(group, is_risk))
        else:                                           # "edge" (and any unknown mode) -> per-unit edge ¢
            out.extend(sorted(group, key=lambda o: (-_edge(o), o.get("opportunity_id") or "")))
    return out


def selection_left_view(selected: dict[str, Any] | None, view: Iterable[dict[str, Any]]) -> bool:
    """True when a selection exists but its opportunity_id is absent from the filtered view — the
    dashboard then clears the row highlight and the stale detail surfaces. None-safe and pure (the
    headless browser suite can't click-select table rows, so the decision logic lives here for unit
    tests)."""
    if not selected:
        return False
    sid = selected.get("opportunity_id")
    return sid not in {o.get("opportunity_id") for o in view or []}


# --- "most liquid right now" (PR F) — over the stored CONTRACT rows (opportunities lack size/spread) ---
def liquidity_panel(contracts: Iterable[dict[str, Any]] | None, n: int = 5) -> dict[str, list]:
    """Top-N most liquid sports + contracts RIGHT NOW (pure, DISPLAY-ONLY telemetry — NOT an opportunity
    signal). Only `active`, genuinely two-sided books (bid>0, ask<100, both sizes>0) count, and a market's
    tradable liquidity = `min(bid_size, ask_size)` (the depth on the thinner side), tiebroken by a tighter
    spread then volume. Per-sport depth is the SUM of that across the sport's qualifying markets (UNKNOWN
    sport excluded). Returns ``{top_sports: [(label, depth, buyable$, sellable$, depth×mid$)…],
    top_contracts: [(label, depth, spread¢)…], tightest: [(label, spread¢, depth)…],
    most_traded: [(label, volume)…]}`` (volume is the documented proxy for transaction activity — Kalshi
    exposes no transaction count). All lists empty/None-safe."""
    # Per sport: summed thinner-side depth (contracts) + three executable notional totals at the touch (in
    # cents → dollars): buyable = Σ ask_size×ask (cost to lift the offers), sellable = Σ bid_size×bid
    # (proceeds to hit the bids), depth×mid = Σ min-side×midpoint.
    per_sport: dict[str, dict[str, float]] = {}
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
            agg = per_sport.setdefault(cfg.label, {"depth": 0.0, "buy_c": 0.0, "sell_c": 0.0, "dm_c": 0.0})
            agg["depth"] += depth
            agg["buy_c"] += ask_sz * ask_c                       # buyable notional (lift the offers)
            agg["sell_c"] += bid_sz * bid_c                      # sellable notional (hit the bids)
            agg["dm_c"] += depth * (bid_c + ask_c) / 2           # depth × midpoint
        rows.append((depth, spread, _num_or_none(c.get("volume")) or 0, _contract_label(c)))
    top_sports = sorted(per_sport.items(), key=lambda kv: (-kv[1]["depth"], kv[0]))[:n]
    by_depth = sorted(rows, key=lambda r: (-r[0], r[1], -r[2], r[3]))       # depth desc, spread asc, vol desc
    by_spread = sorted(rows, key=lambda r: (r[1], -r[0], r[3]))             # spread asc (tightest), depth desc
    by_volume = sorted(rows, key=lambda r: (-r[2], -r[0], r[3]))            # volume desc (most traded)
    return {
        # (label, depth contracts, buyable $, sellable $, depth×mid $)
        "top_sports": [(label, int(a["depth"]), round(a["buy_c"] / 100), round(a["sell_c"] / 100),
                        round(a["dm_c"] / 100)) for label, a in top_sports],
        "top_contracts": [(label, int(depth), int(spread)) for depth, spread, _v, label in by_depth[:n]],
        "tightest": [(label, int(spread), int(depth)) for depth, spread, _v, label in by_spread[:n]],
        "most_traded": [(label, int(vol)) for _d, _s, vol, label in by_volume[:n]],
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


def cascaded_options(opps: Iterable[dict[str, Any]], *, sports: Iterable[str] | None = None,
                     tournaments: Iterable[str] | None = None) -> dict[str, Any]:
    """Cascaded select options that narrow as upstream filters are chosen. Sport options are ALL sports
    present (the top of the cascade — never narrowed). Tournament options are the tournaments present
    once the selected SPORTS are applied; participant options are those present once the selected sports
    AND tournaments are applied. Empty/None selection = no narrowing at that level. Reuses filter_opps +
    derive_options so the narrowing can never drift from the table filtering; NaN-safe."""
    rows = list(opps or [])
    all_opts = derive_options(rows)
    tour_scope = filter_opps(rows, sports=sports) if sports else rows
    tours = derive_options(tour_scope)["tournaments"]
    part_scope = filter_opps(rows, sports=sports, tournaments=tournaments)
    parts = derive_options(part_scope)["participants"]
    return {"sports": all_opts["sports"], "tournaments": tours, "participants": parts}


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
             f"{int(cov.get('opportunities', 0)):,} opportunities"]
    if cov.get("meta_present"):
        parts.append(f"{int(cov.get('scanned', 0)):,} series · {int(cov.get('failed', 0)):,} failed")
        cs, ct = cov.get("contracts_scanned"), cov.get("checks_tested")
        parts.append(f"{int(cs or 0):,} contracts scanned · {int(ct or 0):,} checks tested")
        if cov.get("kalshi_requests") is not None:
            parts.append(f"{int(cov['kalshi_requests']):,} Kalshi requests")
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


def derived_indicators(chain: list[dict[str, Any]] | None, sport: str) -> list[dict[str, Any]]:
    """Derived market-implied indicators (DISPLAY-ONLY bounds) for the detail panel — quantities the market
    doesn't trade directly but the ladder's display prices imply (e.g. golf "make the cut" ≥ Top-20 price).
    Reuses the chain's per-node display % as the input map; [] for a sport with no hook. Pure pass-through
    to SportConfig.derived_indicators — never an edge, never fed to detection."""
    cfg = sports.get_sport(sport)
    node_pct = {r.get("layer"): _num(r.get("display_pct")) for r in (chain or [])}
    return cfg.derived_indicators(node_pct)


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
    "exact_order_top2_bundle": "Top-two bundle (reference): the cost of buying YES on the 12 exact-order "
                               "outcomes where the team finishes top two, shown against the direct qualifier "
                               "YES (a comparator, not a leg). Not arbitrage and not a qualifier "
                               "replication — best-third qualification can make the qualifier pay while the "
                               "bundle pays zero.",
    "exact_order_top2_relative_value": "Speculative top-two idea (review-only): the 12-leg top-two bundle "
                                       "is materially cheaper than the direct qualifier YES. A "
                                       "relative-value signal, not arbitrage; the qualifier is a comparator, "
                                       "not a leg. Best-third qualification breaks the equivalence.",
    "exact_order_top2_proxy": "Top-two bundle (legacy reference): qualifier YES vs a 12-leg top-two bundle. "
                              "Not arbitrage; the qualifier is a comparator.",
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


def considered_inventory(contract_rows: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    """Distinct coverage over the latest snapshot's CONTRACT rows — *everything the app is currently
    considering* (the full fetched universe), independent of whether a row becomes an opportunity. One
    pass; sport is derived from each row's `series` via sports.sport_for_series (rows carry no sport tag),
    UNKNOWN included so the view is honest about everything fetched. NaN/None-safe.

    Returns four display-row lists for the debug grids:
      - ``sports``       : {sport, tournaments, participants, contracts, kinds} — per-sport at-a-glance.
      - ``tournaments``  : {sport, tournament, sources, participants, contracts, kinds} — sources/kinds are
                           the JOINED DISTINCT values present (no first-row-wins).
      - ``participants`` : {sport, tournament, participant, confidence, contracts} — one row per distinct
                           (sport, tournament, participant identity).
      - ``kinds``        : {sport, kind, category, contracts, laddered} — grouped by (sport, kind, category)
                           so a kind spanning categories never silently collapses; ``laddered`` counts
                           ladder-eligible rows.

    A participant's identity is ``player_key`` with a per-row FALLBACK when blank (``market_ticker``, else
    ``event_ticker·player``), so rows missing a key never all collapse into one phantom participant."""
    rows = list(contract_rows or [])
    sport_label: dict[str, str] = {}                         # sport_id -> display label
    sport_tours: dict[str, set] = {}
    sport_parts: dict[str, set] = {}
    sport_kinds: dict[str, set] = {}
    sport_contracts: dict[str, int] = {}
    tour_sources: dict[tuple, set] = {}
    tour_parts: dict[tuple, set] = {}
    tour_kinds: dict[tuple, set] = {}
    tour_contracts: dict[tuple, int] = {}
    part_label: dict[tuple, str] = {}
    part_conf: dict[tuple, str] = {}
    part_contracts: dict[tuple, int] = {}
    kind_contracts: dict[tuple, int] = {}
    kind_laddered: dict[tuple, int] = {}

    for r in rows:
        cfg = sports.sport_for_series(r.get("series"))
        sid = cfg.sport_id
        sport_label[sid] = cfg.label
        tour = r.get("tournament") or "—"
        kind = r.get("kind") or r.get("market_family") or "—"
        category = r.get("category") or "—"
        source = r.get("tournament_source") or "—"
        pkey = (r.get("player_key") or r.get("market_ticker")
                or f"{r.get('event_ticker') or ''}·{r.get('player') or ''}")
        plabel = r.get("player") or pkey
        conf = r.get("mapping_confidence") or ""

        sport_contracts[sid] = sport_contracts.get(sid, 0) + 1
        sport_tours.setdefault(sid, set()).add(tour)
        sport_parts.setdefault(sid, set()).add((tour, pkey))
        sport_kinds.setdefault(sid, set()).add(kind)

        tk = (sid, tour)
        tour_contracts[tk] = tour_contracts.get(tk, 0) + 1
        tour_sources.setdefault(tk, set()).add(source)
        tour_parts.setdefault(tk, set()).add(pkey)
        tour_kinds.setdefault(tk, set()).add(kind)

        pk = (sid, tour, pkey)
        part_contracts[pk] = part_contracts.get(pk, 0) + 1
        part_label.setdefault(pk, plabel)
        if not part_conf.get(pk):
            part_conf[pk] = conf

        kk = (sid, kind, category)
        kind_contracts[kk] = kind_contracts.get(kk, 0) + 1
        if r.get("ladder_eligible"):
            kind_laddered[kk] = kind_laddered.get(kk, 0) + 1

    def lab(sid: str) -> str:
        return sport_label.get(sid, sid)

    sports_out = [{
        "sport": lab(sid), "tournaments": len(sport_tours.get(sid, set())),
        "participants": len(sport_parts.get(sid, set())), "contracts": sport_contracts.get(sid, 0),
        "kinds": len(sport_kinds.get(sid, set())),
    } for sid in sorted(sport_label, key=lab)]
    tournaments_out = [{
        "sport": lab(sid), "tournament": tour,
        "sources": ", ".join(sorted(tour_sources[(sid, tour)])),
        "participants": len(tour_parts[(sid, tour)]), "contracts": tour_contracts[(sid, tour)],
        "kinds": ", ".join(sorted(tour_kinds[(sid, tour)])),
    } for (sid, tour) in sorted(tour_contracts, key=lambda k: (lab(k[0]), k[1]))]
    participants_out = [{
        "sport": lab(sid), "tournament": tour, "participant": part_label[(sid, tour, pkey)],
        "confidence": part_conf.get((sid, tour, pkey), ""), "contracts": part_contracts[(sid, tour, pkey)],
    } for (sid, tour, pkey) in sorted(part_contracts,
                                      key=lambda k: (lab(k[0]), k[1], part_label[k].lower()))]
    kinds_out = [{
        "sport": lab(sid), "kind": kind, "category": category,
        "contracts": kind_contracts[(sid, kind, category)],
        "laddered": kind_laddered.get((sid, kind, category), 0),
    } for (sid, kind, category) in sorted(kind_contracts, key=lambda k: (lab(k[0]), k[1], k[2]))]
    return {"sports": sports_out, "tournaments": tournaments_out,
            "participants": participants_out, "kinds": kinds_out}


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
