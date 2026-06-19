/* Per-bucket column catalogs — ported from ui-mockup-final-spa.html COLS, which mirror the webui/dashboard
 * column defs. Each bucket (zone/section) shows its own catalog; the SPA renders the engine's row fields
 * verbatim (it never recomputes them). `hide` = present in the chooser but off by default. The blotter
 * renders these as a plain <table> (see Blotter.tsx); the formatters below are reused there. */

export type Fmt = "c" | "cmoney" | "pct" | "money" | "x" | "num" | "text" | "qh" | "trad" | "name";
export interface Col { f: string; l: string; fmt: Fmt; hide?: boolean; tip?: string; }

const C = (f: string, l: string, fmt: Fmt = "num", hide = false, tip = ""): Col => ({ f, l, fmt, hide, tip });
const NAME: Col = { f: "name", l: "Participant / market", fmt: "name" };

export const COLS: Record<string, Col[]> = {
  opp: [NAME, C("sport", "Sport", "text"), C("detail", "Detail", "text", true), C("action", "Action plan", "text", true),
    C("edge", "Gross edge ¢", "c", false, "firm child bid − parent ask (or Σ-floor for dutch)"),
    C("roi", "ROI %", "pct"), C("units", "Max units", "num"), C("profit", "Max gross profit", "money"),
    C("net_edge", "Est. net edge $", "cmoney", true, "PER-UNIT net edge in $ (gross edge − immediate-fill/taker fee estimate; 0.07 × effective multiplier; event override else series; fallback labeled) · distinct from the total 'Est. net max profit' · resting-order scenario + breakeven in the Inspector · not net P&L · still gross of depth · never ranks"),
    C("net_profit", "Est. net max profit", "money", true, "immediate-fill (taker) estimate only · not net P&L"),
    C("fees", "Est. fees $", "cmoney", true, "immediate-fill (taker) estimate in $ · event override → series → fallback · maker/resting scenario + breakeven in the Inspector · conservative pre-trade estimate"),
    C("tradable", "Tradable", "trad"), C("caveat", "Caveat", "text")],
  risk: [C("signal", "Signal", "text"), C("flags", "Flags", "text"), C("resolution", "Kind", "text"),
    C("cheap", "Cheap vs peers", "text"), C("sport", "Sport", "text"), NAME, C("detail", "Detail", "text", true),
    C("quality", "Setup quality", "text", false, "Uncalibrated diagnostic combining ripeness (parent ÷ max loss) with the market-implied conditional chance P(deeper│reached): High / Med / Low, or 'Insufficient data' when either input is missing. Not fair value; never an executable ranking."),
    C("wins_if", "Wins if…", "text"), C("cost", "Cost ¢", "c", true), C("max_loss", "Max loss ¢", "c"),
    C("max_profit", "Max profit ¢", "c"), C("max_units", "Max units", "num"),
    C("capacity", "Top-book cost cap $", "money", false, "EXPERIMENTAL · display-only: $ to take the whole VISIBLE top book (cost ¢ × top-book units) — NOT full-depth, NOT guaranteed fill; makes a thin longshot vs a deep name tangible"),
    C("loss_100", "Max loss @ $100", "money"), C("upside_100", "Best upside @ $100", "money"),
    C("quote_health", "Quote health", "qh"), C("ratio", "Upside:risk", "num"),
    C("ev", "Implied EV ¢", "c", false, "gross · top-of-book · display proxy · not net of fees · not fair value · never affects ranking"),
    C("breakeven", "Breakeven %", "pct", false, "max loss ÷ (max loss + max profit) — min payoff chance the bet needs"),
    C("basis_flags", "Basis", "text", false, "honesty flags: MID-ONLY = positive only on the display basis; WIDE = rests on a wide quote"),
    C("display_spread", "Market gap (pp)", "num"),
    C("cond_success", "Success given reached % (display)", "pct", false, "P(success│reached) on the display price (midpoint when the spread is reasonable, else last trade) — uncalibrated, gross"),
    C("cond_child", "Deeper given reached % (display)", "pct", false, "P(deeper│reached) on the display price (midpoint when the spread is reasonable, else last trade) — uncalibrated, gross"),
    C("cond_success_firm", "Success given reached % (bid/ask)", "pct", true, "P(success│reached) on the executable bid/ask — diagnostic, NOT an executable edge"),
    C("cond_child_firm", "Deeper given reached % (bid/ask)", "pct", true, "P(deeper│reached) on the executable bid/ask — diagnostic, NOT an executable edge"),
    C("firm_gap", "Bid/ask success gap ¢", "c"),
    C("gap_vs_be", "Gap vs breakeven (pp)", "num"),
    C("parent_over_maxloss", "Parent ÷ max loss", "num", false, "RIPENESS lens — in-the-money chance per ¢ at risk"),
    C("roc", "Worst-case ROC %", "pct", true), C("spread_over_parent", "Spread÷parent", "num", true),
    C("spread_over_child", "Spread÷child", "num", true), C("parent_outright", "Parent outright ¢", "c", true),
    C("child_outright", "Child outright ¢", "c", true), C("caveat", "Caveat", "text")],
  nm: [C("sport", "Sport", "text"), NAME, C("detail", "Direction", "text"), C("cost", "Cost ¢", "c"),
    C("overpay", "Overpay ¢", "c"), C("note", "Note", "text")],
  no: [C("kind", "Kind", "text"), C("sport", "Sport", "text"), NAME, C("wins_if", "Wins if…", "text"),
    C("buy_no", "Buy NO ¢", "c"), C("cost", "Cost ¢", "c"), C("max_loss", "Max loss ¢", "c"),
    C("breakeven", "Breakeven %", "pct"), C("bonus_profit", "Win profit ¢", "c"),
    C("convexity", "Payout÷cost", "x", true, "payout ÷ cost on a cheap-NO longshot — a high multiple reflects a LOW-probability payout, not an edge; opt-in (hidden by default to avoid lottery-ticket misreading)"),
    C("quote_health", "Quote health", "qh"), C("caveat", "Caveat", "text"),
    C("detail", "Detail", "text", true), C("parent_yes", "Buy YES (bound) ¢", "c", true),
    C("max_units", "Max units", "num", true), C("loss_100", "Max loss @ $100", "money", true),
    C("upside_100", "Best upside @ $100", "money", true),
    // ladder-shape triage (bands only; hidden by default) — pair with the cheap-NO depth filters
    C("ladder_steps", "Ladder depth", "num", true), C("ladder_bottom_c", "Ladder bottom ¢", "c", true),
    C("ladder_step_ratio", "Bottom÷steps", "num", true)],
  qs: [C("sport", "Sport", "text"), NAME, C("setup", "Setup", "text"), C("qualifier", "Qualifier YES ask ¢", "c"),
    C("cost", "Top-two bundle cost ¢", "c"), C("premium", "Cheaper vs qualifier ¢", "c"),
    C("if_top2", "If top two ¢", "c"), C("if_not_top2", "If not top two ¢", "c"), C("max_units", "Max units", "num"),
    C("worst_leg_quote_label", "Worst leg quote", "text"), C("comparator_quote_label", "Comparator quote", "text"),
    C("legs", "Legs", "num"), C("review_status", "Review status", "text"), C("caveat", "Caveat", "text"),
    C("support", "Support score ¢", "c", true), C("highest_leg", "Highest leg ask ¢", "c", true),
    C("median_leg", "Median leg ¢", "c", true), C("tournament_key", "Tournament key", "text", true)],
  diag: [C("sport", "Sport", "text"), NAME, C("status", "Status", "text"), C("edge", "Gross edge ¢", "c"),
    C("roi", "ROI %", "pct"), C("tradable", "Tradable", "trad"), C("caveat", "Caveat", "text")],
};

/** Which catalog a (zone, section) uses. */
export function colKeyOf(zone: string, section: string): string {
  return section === "bounded" ? "risk" : section === "nearmiss" ? "nm" : section === "qual" ? "qs"
    : section === "cheapno" ? "no" : zone === "diag" ? "diag" : "opp";
}

const n1 = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
const num = (v: unknown) => (typeof v === "number" && !isNaN(v) ? v : null);

/** Human-readable labels for the engine's bounded-loss `signal` classes (webui/viewmodel._signal_class).
 *  Display-only: the raw value still drives ranking/honesty narrative (see lens.rankWhy). An unknown value
 *  falls through to itself so a new class is never blanked. */
export const SIGNAL_LABELS: Record<string, string> = {
  "Candidate": "Candidate setup",
  "Breakeven": "At breakeven",
  "Negative proxy": "Below breakeven",
  "Inverted / diagnostic": "Inverted (diagnostic)",
  "Data quality": "Insufficient data",
};
/** Friendly label for a raw signal value (raw fallback for anything unmapped). */
export function signalLabel(raw: unknown): string {
  const s = raw == null ? "" : String(raw);
  if (!s) return "—";
  return SIGNAL_LABELS[s] ?? s;
}

export type QualityTier = "High" | "Med" | "Low" | "n/a";
export interface Quality { tier: QualityTier; label: string; score: number | null; }
/** Single uncalibrated diagnostic for a bounded-loss row: blends RIPENESS (parent ÷ max loss — in-the-money
 *  chance per ¢ at risk) with the market-implied CONDITIONAL chance P(deeper│reached). When EITHER input is
 *  missing the result is "Insufficient data" — never "Low" (missing ≠ bad). Thresholds are uncalibrated and
 *  display-only; this never affects bucket/actionability. score = ripeness × (conditional ÷ 100). */
export function qualityOf(row: Record<string, unknown>): Quality {
  const ripeness = num(row.parent_over_maxloss);
  const cond = num(row.cond_child);                 // P(deeper│reached) %, display basis
  if (ripeness === null || cond === null) return { tier: "n/a", label: "Insufficient data", score: null };
  const frac = Math.max(0, Math.min(1, cond / 100));
  const score = ripeness * frac;
  const tier: QualityTier = score >= 2 ? "High" : score >= 1 ? "Med" : "Low";
  return { tier, label: tier, score };
}

/** A cents amount rendered as display dollars: "$1.75", "-$0.12", and "$0.00" (never "-$0.00").
 *  Shared by the `cmoney` column formatter AND the Inspector fee block so the rule lives in one place. */
export function centsToDollars(cents: number): string {
  const d = cents / 100;
  const s = d.toFixed(2);
  if (Object.is(d, 0) || s === "0.00" || s === "-0.00") return "$0.00";
  return d < 0 ? "-$" + Math.abs(d).toFixed(2) : "$" + s;
}
export function fmtVal(v: unknown, fmt: Fmt): string {
  const n = num(v);
  if (fmt === "text" || fmt === "name" || fmt === "trad" || fmt === "qh") return v == null ? "—" : String(v);
  if (n === null) return "—";
  switch (fmt) {
    case "c": return Math.round(n) + "¢";
    case "cmoney": return centsToDollars(n);   // cents value -> "$1.75" / "-$0.12" (display dollars)
    case "pct": return n1(n) + "%";
    case "money": return "$" + n.toFixed(2);
    case "x": return n1(n) + "×";
    default: return n1(n);
  }
}
export function qhClass(v: unknown): string {
  const s = String(v || "").toLowerCase();
  return /tight/.test(s) ? "qh-tight" : /ok/.test(s) ? "qh-ok" : /wide/.test(s) ? "qh-wide"
    : /cross|one|miss|no quote/.test(s) ? "qh-bad" : "dim";
}
export function tradClass(v: unknown): string {
  const t = String(v || "").toLowerCase();
  return t.startsWith("yes") ? "ty" : t.startsWith("no") ? "tn" : "tr2";
}
