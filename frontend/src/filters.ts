/* Pure, client-side two-pass filter — the old NiceGUI dashboard's policy, mirrored exactly so the SPA
 * stays a faithful VIEW (it narrows rows for display; it NEVER re-buckets or re-ranks):
 *
 *   - MEMBERSHIP  (sport / tournament / participant)  narrows EVERY section.
 *   - THRESHOLDS  (min-size / tradable-only)          gate the others but SPARE Actionable AND Diagnostics
 *                                                     (so a firm actionable edge or a finalized-market
 *                                                      diagnostic never disappears behind a size slider).
 *
 * Because passThreshold auto-passes Actionable + Diagnostics, `passAll` is the single filter for both the
 * shown rows AND the tile/tab counts — the Actionable count is therefore membership-only, the invariant the
 * plan's audit (§4) calls for. Kept pure (no React) so it is unit-testable in isolation. */
import { rowsFor, type FeedRow } from "./feed";

export interface FilterState {
  sports: Set<string>;        // membership — empty = all
  tours: Set<string>;         // membership — empty = all
  part: string;               // membership — case-insensitive substring on the participant/market name
  minSize: number;            // threshold — 0 = off
  tradableOnly: boolean;      // threshold
}

export const emptyFilters = (): FilterState =>
  ({ sports: new Set(), tours: new Set(), part: "", minSize: 0, tradableOnly: false });

export function passMembership(o: FeedRow, f: FilterState): boolean {
  if (f.sports.size && !f.sports.has(String(o.sport || ""))) return false;
  if (f.tours.size && !f.tours.has(String(o.tournament || ""))) return false;
  if (f.part) { const q = f.part.toLowerCase(); if (!String(o.name || "").toLowerCase().includes(q)) return false; }
  return true;
}

const sizeOf = (o: FeedRow): number => {
  const v = (o.max_units ?? o.units) as unknown;
  return typeof v === "number" && !Number.isNaN(v) ? v : 0;
};

export function passThreshold(o: FeedRow, f: FilterState): boolean {
  if (o.section === "act" || o.zone === "diag") return true;          // Actionable + Diagnostics are SPARED
  if (f.minSize > 0 && sizeOf(o) < f.minSize) return false;
  if (f.tradableOnly && !String(o.tradable || "").toLowerCase().startsWith("yes")) return false;
  return true;
}

export function passAll(o: FeedRow, f: FilterState): boolean {
  return passMembership(o, f) && passThreshold(o, f);
}

/** Filtered rows for the current (zone, section) — a pure VIEW narrowing, never a re-bucket. */
export function filteredRows(opps: FeedRow[], zone: string, section: string, f: FilterState): FeedRow[] {
  return rowsFor(opps, zone, section).filter((o) => passAll(o, f));
}

/** Tile/tab count for a (zone, section) over the filtered set. Actionable is membership-only (thresholds
 * auto-pass), so applying a size/tradable threshold never undercounts Actionable. */
export function filteredCount(opps: FeedRow[], zone: string, section: string, f: FilterState): number {
  return filteredRows(opps, zone, section, f).length;
}

/* Per-section band controls (the SecBar). These are THRESHOLDS scoped to one speculative section — they
 * never touch Actionable/Diagnostics (those sections don't render a SecBar). All numeric "off" value is 0.
 * Fail-OPEN on missing/NaN fields: a row is dropped only when the field is a finite number AND violates,
 * so a missing metric never silently hides a row (audit). Cheap-NO band vs outright are distinct row types
 * (o.kind), so the kind filter selects type explicitly and max-loss applies to the band's capped risk. */
export interface BandState {
  maxLoss: number; minRatio: number; maxOverpay: number;
  minChildOutright: number; maxSpreadOverChild: number;
  cheapKind: string;            // "all" | "band" | "outright"
  groupByLadder: boolean;
}
export const emptyBand = (): BandState =>
  ({ maxLoss: 0, minRatio: 0, maxOverpay: 0, minChildOutright: 0, maxSpreadOverChild: 0, cheapKind: "all", groupByLadder: false });

const fnum = (x: unknown): number => (typeof x === "number" && !Number.isNaN(x) ? x : NaN);
const overMax = (x: unknown, lim: number) => lim > 0 && fnum(x) > lim;        // present & exceeds the cap
const underMin = (x: unknown, lim: number) => lim > 0 && fnum(x) < lim;       // present & below the floor

/** Apply the active section's band thresholds (pure; fail-open on missing fields). */
export function applyBand(rows: FeedRow[], section: string, b: BandState): FeedRow[] {
  if (section === "bounded") {
    return rows.filter((o) => !overMax(o.max_loss, b.maxLoss) && !underMin(o.ratio, b.minRatio)
      && !underMin(o.child_outright, b.minChildOutright) && !overMax(o.spread_over_child, b.maxSpreadOverChild));
  }
  if (section === "nearmiss") return rows.filter((o) => !overMax(o.overpay, b.maxOverpay));
  if (section === "cheapno") {
    let r = rows.filter((o) => !overMax(o.max_loss, b.maxLoss));
    if (b.cheapKind !== "all") r = r.filter((o) => String(o.kind || "").toLowerCase().includes(b.cheapKind));
    return r;
  }
  return rows;
}

/** Distinct tournaments present in the feed, cascaded to the selected sports (mockup behavior). */
export function tournamentOptions(opps: FeedRow[], sportsSel: Set<string>): string[] {
  const set = new Set<string>();
  for (const o of opps) {
    if (sportsSel.size && !sportsSel.has(String(o.sport || ""))) continue;
    const tv = String(o.tournament || "");
    if (tv) set.add(tv);
  }
  return [...set].sort();
}
