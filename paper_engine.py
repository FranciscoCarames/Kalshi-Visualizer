"""Pure forward-test / paper-position scoring — NO UI, NO pandas, stdlib + ``data``/``roundtrip_cost``.

The honest core of the paper harness. It turns a scanner-flagged opportunity (a buy-only plan of legs)
into a SIMULATED paper position, then — once its markets settle — scores realized **net-of-fees** P&L.

It is a forward-test + calibration model ONLY: it never creates, submits, cancels, previews, signs, or
routes exchange orders, uses no portfolio credentials, and calls no order endpoints. "Trade" here means a
recorded simulated position, nothing more.

Conservative paper-fill assumptions (every report must surface these — see the SPA caveats banner):
  - Entry at the firm ask captured at flag time (``leg.price_c``), size-capped at the snapshotted
    top-of-book depth (``leg.size``). No queue position, no latency, no slippage, no partial fill beyond
    the visible size, no stale-snapshot penalty.
  - Held to settlement ⇒ the only fee is the ENTRY taker fee (Kalshi charges no settlement fee).
  - Binary markets only (this app's universe): each leg pays 100¢ if its side wins, else 0¢. There is no
    scalar / tie settlement to score (scalar markets are out of scope upstream).

P&L is computed PER UNIT (one contract per leg) in exact integer cents; floats are display-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
import data
import roundtrip_cost

# Settlement statuses the harness recognises. Trimmed to what this app's binary universe actually produces
# (NOT the full Kalshi lifecycle): a position is scorable only once every leg is finalized with a
# definitive yes/no result. `determined_pending` = outcome known but not yet paid out (we do NOT finalize
# P&L there, per the conservative settlement rule).
STATUS_OPEN = "open"
STATUS_DETERMINED_PENDING = "determined_pending"
STATUS_SETTLED = "settled"
STATUS_UNSCORABLE = "unscorable"

# Raw Kalshi market `status` values that count as a FINAL payout (positions only finalize here).
_FINAL_STATUSES = ("finalized", "settled")


def normalize_side(side: Any) -> str | None:
    """Map a leg's action side to the market side it is long: ``"yes"`` or ``"no"`` (``buy_yes``/``yes`` →
    yes, ``buy_no``/``no`` → no). Returns None for anything unrecognised (→ the leg is unscorable)."""
    s = str(side or "").strip().lower()
    if s in ("yes", "buy_yes", "buy yes"):
        return "yes"
    if s in ("no", "buy_no", "buy no"):
        return "no"
    return None


def normalize_result(result: Any) -> str | None:
    """Normalize a settled binary market's ``result`` to ``"yes"``/``"no"``, else None (still open /
    non-binary / unknown). A scalar/other value yields None so it is never mis-scored as a binary win."""
    r = str(result or "").strip().lower()
    return r if r in ("yes", "no") else None


@dataclass
class PaperLeg:
    """One leg of a simulated paper position: a long position on ``side`` of ``ticker`` at ``entry_price_c``."""
    ticker: str
    side: str                       # normalized: "yes" | "no"
    entry_price_c: int
    size: int | None = None         # snapshotted top-of-book depth (fill cap); None = unknown
    contract: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ticker": self.ticker, "side": self.side, "entry_price_c": self.entry_price_c,
                "size": self.size, "contract": self.contract}


@dataclass
class PaperEntry:
    """A simulated paper position opened from one flagged opportunity (the whole buy-only plan)."""
    entry_key: str
    opportunity_id: str
    opened_ts: float
    source_bucket: str
    sport: str
    relationship_type: str
    opportunity_class: str          # "executable" | "speculative"
    fill_model: str
    legs: list[PaperLeg]
    cost_c: int
    max_loss_c: int                 # buy-only ⇒ loss is bounded by the stake (== cost_c)
    scorable: bool = True
    unscorable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_key": self.entry_key, "opportunity_id": self.opportunity_id,
            "opened_ts": self.opened_ts, "source_bucket": self.source_bucket, "sport": self.sport,
            "relationship_type": self.relationship_type, "opportunity_class": self.opportunity_class,
            "fill_model": self.fill_model, "cost_c": self.cost_c, "max_loss_c": self.max_loss_c,
            "scorable": self.scorable, "unscorable_reason": self.unscorable_reason,
            "legs": [leg.to_dict() for leg in self.legs],
        }


@dataclass
class EntryResult:
    """The scored outcome of a paper entry against the currently-known settlements."""
    entry_key: str
    status: str
    gross_c: int | None = None      # gross P&L (payout − cost), per unit
    fees_c: int | None = None       # entry taker fees, per unit
    net_c: int | None = None        # gross − fees, per unit
    won: bool | None = None
    fee_known: bool = True
    settled_ts: float | None = None
    leg_payouts: list[dict[str, Any]] = field(default_factory=list)


def _coerce_cents(x: Any) -> int | None:
    """Integer cents from a unified-row ``*_c`` field that is ALREADY in cents (price_c / cost_c), or None
    for missing / NaN / non-numeric. (NOT ``data.to_cents`` — that converts a dollar value to cents; these
    fields are integer cents already.)"""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:                      # NaN (a None round-trips to NaN through a DataFrame)
        return None
    return int(round(v))


def extract_entry(row: dict[str, Any], *, opened_ts: float,
                  fill_model: str = config.PAPER_FILL_MODEL) -> PaperEntry | None:
    """Build a :class:`PaperEntry` from a unified-opportunity row (a dict from the scanner's frame).

    The opportunity is recorded as a buy-only plan of legs (``row["legs"]``, already synthesized by
    ``scanner._finalize_unified``). Class is ``"speculative"`` when ``exec_gap_c is None`` (the universal
    speculative gate — conditional-blend / NO-fade / diagnostic rows), else ``"executable"``.

    Returns None only when there is no opportunity_id to key on. A row whose legs are missing prices/sides
    is returned with ``scorable=False`` (recorded but excluded from headline P&L), never silently dropped.
    """
    opp_id = str(row.get("opportunity_id") or "").strip()
    if not opp_id:
        return None

    # Entry identity: stable opportunity_id × fill-model version (so a methodology change never silently
    # mixes old and new entries). opportunity_id is itself a deterministic structure-hash, stable across
    # snapshots, so this opens each distinct opportunity exactly once.
    entry_key = data.opportunity_id(opp_id, fill_model)

    raw_legs = row.get("legs")
    legs: list[PaperLeg] = []
    reasons: list[str] = []
    if not isinstance(raw_legs, list) or not raw_legs:
        reasons.append("no legs")
        raw_legs = []
    for lg in raw_legs:
        if not isinstance(lg, dict):
            reasons.append("malformed leg")
            continue
        ticker = str(lg.get("ticker") or "").strip()
        side = normalize_side(lg.get("side"))
        price_c = _coerce_cents(lg.get("price_c"))
        size = lg.get("size")
        try:
            size = int(size) if size is not None else None
        except (TypeError, ValueError):
            size = None
        if not ticker:
            reasons.append("leg missing ticker")
        if side is None:
            reasons.append("leg missing side")
        if price_c is None:
            reasons.append("leg missing price")
        if ticker and side is not None and price_c is not None:
            legs.append(PaperLeg(ticker=ticker, side=side, entry_price_c=price_c, size=size,
                                 contract=str(lg.get("contract") or "")))

    # Cost: prefer the row's combined cost; fall back to the sum of leg prices.
    cost_c = _coerce_cents(row.get("cost_c"))
    if cost_c is None and legs:
        cost_c = sum(leg.entry_price_c for leg in legs)

    scorable = bool(legs) and not reasons and cost_c is not None
    if cost_c is None:
        reasons.append("no cost")
        cost_c = 0

    # Speculative gate: exec_gap_c is None for every speculative/diagnostic row. A row sourced from a
    # DataFrame turns that None into float NaN, so treat NaN as None too (else it misclassifies as executable).
    gap = row.get("exec_gap_c")
    gap_is_none = gap is None or (isinstance(gap, float) and gap != gap)
    opp_class = "speculative" if gap_is_none else "executable"

    return PaperEntry(
        entry_key=entry_key,
        opportunity_id=opp_id,
        opened_ts=opened_ts,
        source_bucket=str(row.get("bucket") or ""),
        sport=str(row.get("sport") or ""),
        relationship_type=str(row.get("relationship_type") or ""),
        opportunity_class=opp_class,
        fill_model=fill_model,
        legs=legs,
        # Buy-only worst case: every leg loses ⇒ you forfeit the full stake. Loss is bounded by cost.
        cost_c=int(cost_c),
        max_loss_c=int(cost_c),
        scorable=scorable,
        unscorable_reason="; ".join(dict.fromkeys(reasons)) if not scorable else "",
    )


def score_entry(entry: PaperEntry, settlements: dict[str, dict[str, Any]], *,
                fee_coeffs: dict[str, float] | None = None) -> EntryResult:
    """Score a paper entry against the known settlements (``ticker -> {result, status, settled_ts,
    settlement_value_c}``). Finalizes net-of-fees P&L ONLY when every leg is finalized with a definitive
    yes/no result; otherwise returns ``open`` (no leg resolved yet) or ``determined_pending`` (outcomes
    known but not all paid out). Per-unit, exact integer cents.

    ``fee_coeffs`` maps a ticker to its effective taker coefficient (from the series fee metadata); a
    missing ticker falls back to the taker base and flags ``fee_known=False`` so the report can disclose it.
    """
    if not entry.scorable:
        return EntryResult(entry_key=entry.entry_key, status=STATUS_UNSCORABLE)

    fee_coeffs = fee_coeffs or {}
    leg_payouts: list[dict[str, Any]] = []
    all_resolved = True
    all_final = True
    settled_ts: float | None = None
    gross_payout_c = 0
    fees_c = 0
    fee_known = True

    for leg in entry.legs:
        s = settlements.get(leg.ticker) or {}
        result = normalize_result(s.get("result"))
        status_raw = str(s.get("status") or "").strip().lower()
        is_final = status_raw in _FINAL_STATUSES
        if result is None:
            all_resolved = False
            all_final = False
            leg_payouts.append({"ticker": leg.ticker, "side": leg.side, "result": None, "payout_c": None})
            continue
        if not is_final:
            all_final = False
        payout_c = 100 if leg.side == result else 0
        gross_payout_c += payout_c
        coeff = fee_coeffs.get(leg.ticker)
        if coeff is None:
            coeff = config.FEE_TAKER_BASE_COEFF
            fee_known = False
        fees_c += roundtrip_cost.fee_c(1, leg.entry_price_c, coeff)
        ts = s.get("settled_ts")
        if ts is not None:
            settled_ts = ts if settled_ts is None else max(settled_ts, ts)
        leg_payouts.append({"ticker": leg.ticker, "side": leg.side, "result": result, "payout_c": payout_c})

    if not all_resolved:
        return EntryResult(entry_key=entry.entry_key, status=STATUS_OPEN, leg_payouts=leg_payouts)
    if not all_final:
        # Every outcome is known but at least one leg hasn't paid out — do NOT finalize P&L yet.
        return EntryResult(entry_key=entry.entry_key, status=STATUS_DETERMINED_PENDING,
                           leg_payouts=leg_payouts)

    gross_c = gross_payout_c - entry.cost_c
    net_c = gross_c - fees_c
    return EntryResult(
        entry_key=entry.entry_key, status=STATUS_SETTLED,
        gross_c=gross_c, fees_c=fees_c, net_c=net_c, won=net_c > 0,
        fee_known=fee_known, settled_ts=settled_ts, leg_payouts=leg_payouts,
    )
