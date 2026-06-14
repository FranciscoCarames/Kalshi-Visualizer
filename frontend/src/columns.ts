/* Per-bucket column catalogs — ported from ui-mockup-final-spa.html COLS, which mirror the webui/dashboard
 * column defs. Each bucket (zone/section) shows its own catalog; the SPA renders the engine's row fields
 * verbatim (it never recomputes them). `hide` = present in the chooser but off by default. */
import { createElement } from "react";
import type { ColDef } from "ag-grid-community";
import type { FeedRow } from "./feed";

export type Fmt = "c" | "pct" | "money" | "x" | "num" | "text" | "qh" | "trad" | "name";
export interface Col { f: string; l: string; fmt: Fmt; hide?: boolean; tip?: string; }

const C = (f: string, l: string, fmt: Fmt = "num", hide = false, tip = ""): Col => ({ f, l, fmt, hide, tip });
const NAME: Col = { f: "name", l: "Participant / market", fmt: "name" };

export const COLS: Record<string, Col[]> = {
  opp: [NAME, C("sport", "Sport", "text"), C("detail", "Detail", "text", true), C("action", "Action plan", "text", true),
    C("edge", "Gross edge ¢", "c", false, "firm child bid − parent ask (or Σ-floor for dutch)"),
    C("roi", "ROI %", "pct"), C("units", "Max units", "num"), C("profit", "Max gross profit", "money"),
    C("tradable", "Tradable", "trad"), C("caveat", "Caveat", "text")],
  risk: [C("signal", "Signal", "text"), C("flags", "Flags", "text"), C("resolution", "Kind", "text"),
    C("cheap", "Cheap vs peers", "text"), C("sport", "Sport", "text"), NAME, C("detail", "Detail", "text", true),
    C("wins_if", "Wins if…", "text"), C("cost", "Cost ¢", "c", true), C("max_loss", "Max loss ¢", "c"),
    C("max_profit", "Max profit ¢", "c"), C("max_units", "Max units", "num"),
    C("loss_100", "Max loss @ $100", "money"), C("upside_100", "Best upside @ $100", "money"),
    C("quote_health", "Quote health", "qh"), C("ratio", "Upside:risk", "num"),
    C("display_spread", "Market gap (pp)", "num"), C("cond_success", "Success given reached %", "pct"),
    C("cond_child", "Deeper given reached %", "pct"), C("firm_gap", "Firm success gap ¢", "c"),
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
    C("convexity", "Payout÷cost", "x"), C("quote_health", "Quote health", "qh"), C("caveat", "Caveat", "text"),
    C("detail", "Detail", "text", true), C("parent_yes", "Buy YES (bound) ¢", "c", true),
    C("max_units", "Max units", "num", true), C("loss_100", "Max loss @ $100", "money", true),
    C("upside_100", "Best upside @ $100", "money", true)],
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
export function fmtVal(v: unknown, fmt: Fmt): string {
  const n = num(v);
  if (fmt === "text" || fmt === "name" || fmt === "trad" || fmt === "qh") return v == null ? "—" : String(v);
  if (n === null) return "—";
  switch (fmt) {
    case "c": return Math.round(n) + "¢";
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
  return t.startsWith("yes") ? "tradable-yes" : t.startsWith("no") ? "tradable-no" : "tradable-rule";
}

/** Build AG-Grid ColDefs from a catalog, honoring a visible-set (column chooser) + the user's order. */
export function buildColDefs(cols: Col[], visible: string[] | null): ColDef<FeedRow>[] {
  const vis = visible ?? cols.filter((c) => !c.hide).map((c) => c.f);
  const byF = new Map(cols.map((c) => [c.f, c]));
  return vis.map((f) => byF.get(f)).filter((c): c is Col => !!c).map((c) => {
    const right = c.fmt !== "text" && c.fmt !== "name" && c.fmt !== "trad" && c.fmt !== "qh";
    const def: ColDef<FeedRow> = {
      field: c.f, headerName: c.l, headerTooltip: c.tip || undefined,
      type: right ? "rightAligned" : undefined,
      minWidth: c.fmt === "name" ? 240 : 70,
      flex: c.fmt === "name" ? 2 : c.fmt === "text" ? 1 : undefined,
      valueFormatter: (p) => fmtVal(p.value, c.fmt),
    };
    if (c.fmt === "name") {
      def.headerName = "Participant / match";
      // Return a React element (NOT an HTML string): ag-grid-react renders a function renderer's return as
      // React children, so a string would show its literal <span> tags as text.
      def.cellRenderer = (p: { data?: FeedRow }) => createElement(
        "span", null,
        createElement("span", { className: "nm" }, p.data?.name ?? ""), " ",
        createElement("span", { className: "sub" }, p.data?.sub ?? ""),
      );
    } else if (c.fmt === "qh") def.cellClass = (p) => qhClass(p.value);
    else if (c.fmt === "trad") def.cellClass = (p) => tradClass(p.value);
    else if (c.f === "edge") def.cellClass = (p) => (num(p.value) ? "green" : "");
    else if (c.f === "max_loss") def.cellClass = "red";
    else if (c.f === "max_profit" || c.f === "bonus_profit") def.cellClass = "green";
    return def;
  });
}
