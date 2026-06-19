/* Lenses — CLIENT-SIDE SORT ONLY, ported from ui-mockup-final-spa.html rk()/rankWhy().
 * A lens re-orders the rows currently shown; it NEVER changes a row's bucket/status/actionability (those
 * are the engine's). The default view is engine order (no lens active). Isolation-safe by construction:
 * it only reads display fields and reorders an array. */
import type { FeedRow } from "./feed";
import { qualityOf } from "./columns";

export const LENSES: [string, string, string][] = [
  ["blended", "BLENDED", "Weighted mix of edge + ROI + payoff geometry — the all-rounder."],
  ["edge", "EDGE¢", "Pure per-unit gross edge ¢ — biggest mispricing first."],
  ["spread", "SPREAD", "Best-case payoff spread (how much you can win)."],
  ["ratio", "OUTRIGHT+SPREAD", "Child outright magnitude, then spread÷outright — cheap longshots with room."],
  ["ev", "IMPLIED EV", "Display-spread minus overpay — a ranking aid, NOT a real edge."],
  ["ripeness", "RIPENESS", "Parent ÷ max loss — in-the-money chance per ¢ at risk (bounded-loss). Higher = riper."],
  ["quality", "SETUP QUALITY", "Uncalibrated diagnostic: ripeness × conditional chance P(deeper│reached). Insufficient-data rows sort last."],
];

/* Which lenses make sense per zone (the rest sort on fields a zone's rows don't carry, so they'd be
 * no-ops or misleading). Executable rows only have a gross edge → edge/blended; the speculative bucket has
 * the full payoff-geometry set; diagnostic rows are review-only and get NO lens bar (engine order only). */
const _LENSES_BY_ZONE: Record<string, Set<string>> = {
  exec: new Set(["blended", "edge"]),
  spec: new Set(["blended", "edge", "spread", "ratio", "ev", "ripeness", "quality"]),
  diag: new Set(),
};
// RIPENESS / SETUP QUALITY rank on containment-only fields (parent_over_maxloss, conditional chance) that only
// the bounded-loss section carries. On other spec sections (cheap-NO, near-miss, qualifier) they'd sort on
// absent fields → no-ops/misleading, so gate them to `bounded`. (Undefined section keeps all — no regression.)
const _CONTAINMENT_ONLY = new Set(["ripeness", "quality"]);
export function lensesFor(zone: string, section?: string): [string, string, string][] {
  const allow = _LENSES_BY_ZONE[zone] ?? _LENSES_BY_ZONE.spec;
  const keepContainment = section == null || section === "bounded";
  return LENSES.filter(([k]) => allow.has(k) && (keepContainment || !_CONTAINMENT_ONLY.has(k)));
}
/** True when `lens` is valid for the given (zone, section) — used to reset a leaked lens on section change. */
export function lensValid(lens: string, zone: string, section?: string): boolean {
  return !lens || lensesFor(zone, section).some(([k]) => k === lens);
}

const n = (v: unknown) => (typeof v === "number" && !isNaN(v) ? v : 0);

/** Sort key for a lens (higher = ranked first). Mirrors the mockup exactly. */
export function rankKey(o: FeedRow, lens: string): number {
  const e = n(o.edge), r = n(o.roi), best = n(o.max_profit ?? o.profit), worst = n(o.max_loss), sp = best - worst, c = n(o.cost);
  if (lens === "edge") return e;
  if (lens === "spread") return sp || best;
  if (lens === "ratio") return c ? (sp / c) * 100 : 0;
  if (lens === "ev") return n(o.ev);
  if (lens === "ripeness") return o.parent_over_maxloss == null ? -1e9 : n(o.parent_over_maxloss);
  if (lens === "quality") { const q = qualityOf(o); return q.score == null ? -1e9 : q.score; }   // insufficient data sorts last
  return e * 0.35 + r * 0.45 + (sp || best) * 0.2;     // blended
}

/** Sort a copy by a lens, or return as-is (engine order) when no lens is active. */
export function applyLens(rows: FeedRow[], lens: string): FeedRow[] {
  if (!lens) return rows;
  return [...rows].sort((a, b) => rankKey(b, lens) - rankKey(a, lens));
}

/** Why a row ranks where it does (for the inspector). Display narrative, not a model. */
export function rankWhy(o: FeedRow): { up: string; down: string } {
  const up: string[] = [], dn: string[] = [];
  if (n(o.roi) > 4) up.push("high ROI " + n(o.roi).toFixed(1) + "%");
  if (n(o.edge) >= 5) up.push("edge " + Math.round(n(o.edge)) + "¢");
  if (n(o.parent_over_maxloss) > 3) up.push("ripe " + n(o.parent_over_maxloss).toFixed(1));
  const qh = String(o.quote_health || "");
  if (/Tight/.test(qh)) up.push("tight quote");
  if (/Wide|One|Crossed/.test(qh)) dn.push(qh.toLowerCase());
  if (o.rule) dn.push("rule check");
  const sig = String(o.signal || "");
  if (/Negative|Inverted|quality/.test(sig)) dn.push(sig.toLowerCase());
  return { up: up.join(" · ") || "baseline", down: dn.join(" · ") || "none" };
}
