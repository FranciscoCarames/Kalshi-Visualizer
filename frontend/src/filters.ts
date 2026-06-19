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
import { rowsFor, type BandDefaults, type FeedRow } from "./feed";

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

/* DISPLAY-ONLY "hide fee-negative executables" predicate (opt-out via the SETTINGS toggle). True ⇒ HIDE.
 * Keys off the feed's `net_negative` flag, which is TAKER-basis, set ONLY on `actionable` rows, and ONLY
 * when the (taker) fee estimate is complete — so Review/Blocked and incomplete/flat/unknown-fee rows are
 * never hidden. A pure view filter: the row stays in the feed (the toggle reveals it); nothing re-buckets.
 * Centralized so the `rows` memo AND the tile/tab `count()` can't drift. */
export function hiddenByFee(o: FeedRow, zone: string, on: boolean): boolean {
  return on && zone === "exec" && o.net_negative === true;
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
  minChildOutright: number; minParentOutright: number; maxSpreadOverChild: number;
  cheapKind: string;            // "all" | "band" | "outright"
  cheapScope: string;           // cheap-NO settlement scope tab: "all" | "event" | "tournament" | "championship"
  maxBuyNo: number;             // cheap-NO: cap the Buy-NO anchor cost (¢); 0 = off
  // cheap-NO ladder-shape filters (bands only; 0 = off, so defaults are no-op):
  minLadderDepth: number;       // require the ladder to run at least N priced rungs deep
  maxLadderBottom: number;      // cap the deepest rung's display price (¢)
  maxStepRatio: number;         // cap (bottom ÷ steps); cheaper-per-step bottoms only
  groupByLadder: boolean;
}
export const emptyBand = (): BandState =>
  ({ maxLoss: 0, minRatio: 0, maxOverpay: 0, minChildOutright: 0, minParentOutright: 0, maxSpreadOverChild: 0, cheapKind: "all", cheapScope: "all", maxBuyNo: 0,
     minLadderDepth: 0, maxLadderBottom: 0, maxStepRatio: 0, groupByLadder: false });

/* Fallback band defaults if meta.defaults is absent — these literals match config.py
 * (RISK_BUDGET_DEFAULT_MAX_LOSS_C=5, NEAR_MISS_DEFAULT_OVER_C=3, NO_STRUCTURE_DEFAULT_MAX_LOSS_C=15,
 * NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C=15). meta.defaults is the source of truth when present. */
const FALLBACK_DEFAULTS: BandDefaults =
  { bounded_max_loss_c: 5, nearmiss_overpay_c: 3, cheapno_max_loss_c: 15, cheapno_max_buy_no_c: 15 };

/** The old-dashboard default band for a section (per-section so bounded max-loss 5¢ and cheap-NO max-loss
 * 15¢ never collide). Off (0) sections keep emptyBand values. Source = meta.defaults, fallback literals. */
export function defaultBand(section: string, d?: BandDefaults): BandState {
  const dd = d ?? FALLBACK_DEFAULTS;
  const b = emptyBand();
  if (section === "bounded") return { ...b, maxLoss: dd.bounded_max_loss_c };
  if (section === "nearmiss") return { ...b, maxOverpay: dd.nearmiss_overpay_c };
  if (section === "cheapno") return { ...b, maxLoss: dd.cheapno_max_loss_c, maxBuyNo: dd.cheapno_max_buy_no_c };
  return b;
}

/** True when `b` equals the section's default band (used to show "defaults applied" vs "edited" in the UI). */
export function isDefaultBand(section: string, b: BandState, d?: BandDefaults): boolean {
  const def = defaultBand(section, d);
  return (Object.keys(def) as (keyof BandState)[]).every((k) => b[k] === def[k]);
}

const fnum = (x: unknown): number => (typeof x === "number" && !Number.isNaN(x) ? x : NaN);
const overMax = (x: unknown, lim: number) => lim > 0 && fnum(x) > lim;        // present & exceeds the cap
const underMin = (x: unknown, lim: number) => lim > 0 && fnum(x) < lim;       // present & below the floor

/** Apply the active section's band thresholds (pure; fail-open on missing fields). */
export function applyBand(rows: FeedRow[], section: string, b: BandState): FeedRow[] {
  if (section === "bounded") {
    return rows.filter((o) => !overMax(o.max_loss, b.maxLoss) && !underMin(o.ratio, b.minRatio)
      && !underMin(o.child_outright, b.minChildOutright) && !underMin(o.parent_outright, b.minParentOutright)
      && !overMax(o.spread_over_child, b.maxSpreadOverChild));
  }
  if (section === "nearmiss") return rows.filter((o) => !overMax(o.overpay, b.maxOverpay));
  if (section === "cheapno") {
    let r = rows.filter((o) => !overMax(o.max_loss, b.maxLoss) && !overMax(o.buy_no, b.maxBuyNo));
    if (b.cheapKind !== "all") r = r.filter((o) => String(o.kind || "").toLowerCase().includes(b.cheapKind));
    // Settlement-scope sub-tab (Event / Tournament / Championship), mirroring the NiceGUI split. Rows with
    // a blank/unknown scope are only dropped when a specific scope tab is active (fail-open on "all").
    if (b.cheapScope !== "all") r = r.filter((o) => String(o.scope || "") === b.cheapScope);
    // Ladder-shape filters (bands only; fail-open — a row with no ladder metric is never hidden by them).
    r = r.filter((o) => !underMin(o.ladder_steps, b.minLadderDepth)
      && !overMax(o.ladder_bottom_c, b.maxLadderBottom) && !overMax(o.ladder_step_ratio, b.maxStepRatio));
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
