/* Live terminal feed — types + loader + the zone/section taxonomy.
 * The single source of truth is the backend `webui/feed.py` adapter at GET /api/terminal/feed; this file
 * only types its shape and routes rows by the engine-assigned zone/section (it never re-buckets). */
import { apiFetch } from "./http";

// `bo` (book-only): a pseudo-leg added by the feed so the depth panel can show a market's book where no
// executable leg carries the ticker — NOT a trade instruction (no side/price). See webui/feed._trim_legs.
export interface FeedLeg { side?: string; c?: string; p?: number | null; sz?: number; tk?: string; u?: string; bo?: boolean; }

export interface FeedRow {
  id: string;
  // engine-assigned, copied VERBATIM by the feed — the SPA never recomputes these:
  bucket: string; zone: string; section: string; status?: string; tradable?: string; rule?: string;
  sport?: string; name?: string; sub?: string; detail?: string;
  // routing keys the Inspector passes to /api/terminal/detail|ladder (display-only passthroughs):
  sport_key?: string; player_key?: string; tournament?: string;
  // economics (present per bucket; absent ones render "—"):
  edge?: number; roi?: number; units?: number; profit?: number; cost?: number;
  max_loss?: number; max_profit?: number; max_units?: number; quote_health?: string; caveat?: string;
  settlement_caveat?: string; blk?: string; scope?: string; resolution_mode?: string;
  // net-of-fees ESTIMATE (display-only · never ranks). Two EXECUTION SCENARIOS: taker = immediate-fill
  // (primary; `fees`/`net_edge`/`net_profit` carry it), maker = resting-order (fills/queue/edge-decay not
  // modeled). Fees resolve per leg: event override -> series fee -> labeled fallback. net_negative flags an
  // Actionable row whose estimated TAKER fees meet/exceed the gross edge — advisory chip, never a hide.
  net_edge?: number | null; net_profit?: number | null; fees?: number | null; net_negative?: boolean;
  fees_taker?: number | null; fees_maker?: number | null;
  net_edge_maker?: number | null; net_profit_maker?: number | null;
  fee_breakeven?: number | null; fee_breakeven_approx?: boolean;
  taker_complete?: boolean; maker_complete?: boolean;
  fee_source?: "event_override" | "series" | "mixed" | "fallback" | "flat" | "unknown";
  fee_legs?: {
    side?: string; price_c?: number | null; contracts?: number | null;
    series_ticker?: string; event_ticker?: string; fee_type?: string | null; fee_multiplier?: number | null;
    fee_taker_c?: number | null; fee_maker_c?: number | null;
    fee_type_source?: string; fee_multiplier_source?: string; status?: string;
  }[] | null;
  // display-only derived (computed in the adapter; uncalibrated · gross · never rank). Conditional on two
  // bases: display (dashboard price) and firm (executable bid/ask) — the firm pair is a DIAGNOSTIC, not an
  // executable edge. midpoint_only / wide_basis are honesty flags from the engine row builder.
  cond_child?: number | null; cond_success?: number | null;
  cond_child_firm?: number | null; cond_success_firm?: number | null;
  ev?: number | null; breakeven?: number | null; midpoint_only?: boolean; wide_basis?: boolean;
  parent_over_maxloss?: number | null; ratio?: number;
  pnode?: string; cnode?: string;
  pbid?: number | null; cask?: number | null; pdisp?: number | null; cdisp?: number | null;
  legs?: FeedLeg[]; nlegs?: number; url?: string;
  [k: string]: unknown;
}

export interface BandDefaults {
  bounded_max_loss_c: number; nearmiss_overpay_c: number;
  cheapno_max_loss_c: number; cheapno_max_buy_no_c: number;
}

export interface FeedMeta {
  snapshot_id: number | null; fetched_at: string | null; n_total: number;
  contracts?: number; checks?: number; requests?: number; scanned?: number; failed?: number; retry?: number;
  totals: Record<string, number>; sports: Record<string, number>;
  resolution_counts: Record<string, number>; scope_counts: Record<string, number>;
  series_errors?: unknown;
  defaults?: BandDefaults;       // old-dashboard band-control defaults (single-sourced from config)
  fee_data_status?: string;      // DISPLAY-ONLY fee provenance: ok/partial/fallback/failed/capped/disabled
}

export interface Feed { meta: FeedMeta; opps: FeedRow[]; }

export async function loadFeed(): Promise<Feed> {
  const r = await apiFetch("/api/terminal/feed", { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("feed " + r.status);
  return r.json();
}

/* The executable taxonomy (mirrors the engine's buckets). Zone -> sections -> bucket. */
export const ZONES: [string, string, string][] = [
  ["exec", "EXECUTABLE", "firm · gross edge"],
  ["spec", "SPECULATIVE", "bounded-loss · convex EV · can lose money"],
  ["diag", "DIAGNOSTIC", "review-only · data quality"],
];

export const SUBTABS: Record<string, [string, string, string][]> = {
  exec: [["act", "ACTIONABLE", "actionable"], ["rev", "REVIEW", "review_signal"], ["blk", "BLOCKED", "blocked"]],
  spec: [["bounded", "BOUNDED-LOSS", "risk_budget"], ["nearmiss", "NEAR-MISS", "near_miss"],
         ["qual", "QUALIFIER", "qualifier_setup"], ["cheapno", "CHEAP-NO", "no_structure"]],
  diag: [["diag", "DIAGNOSTIC", "data_quality"]],
};

/* The 8 landing tiles: label, zone, section, accent. */
export const TILES: [string, string, string, string][] = [
  ["ACTIONABLE", "exec", "act", "green"], ["REVIEW", "exec", "rev", "amber"], ["BLOCKED", "exec", "blk", "red"],
  ["BOUNDED-LOSS", "spec", "bounded", "amber"], ["NEAR-MISS", "spec", "nearmiss", ""],
  ["QUALIFIER", "spec", "qual", ""], ["CHEAP-NO", "spec", "cheapno", ""], ["DATA-QUALITY", "diag", "diag", "cyan"],
];

export const SECTION_BUCKET: Record<string, string> = {
  act: "actionable", rev: "review_signal", blk: "blocked", bounded: "risk_budget",
  nearmiss: "near_miss", qual: "qualifier_setup", cheapno: "no_structure",
};
export const DIAG_BUCKETS = ["data_quality", "display_signal", "wide_signal", "near_edge", "clean"];

/** Count for a (zone, section) tile/tab from the snapshot's full bucket totals. */
export function sectionCount(meta: FeedMeta | null, zone: string, section: string): number {
  if (!meta) return 0;
  if (zone === "diag") return DIAG_BUCKETS.reduce((n, b) => n + (meta.totals[b] || 0), 0);
  return meta.totals[SECTION_BUCKET[section]] || 0;
}

/** The rows shown for the current zone/section — a pure VIEW filter, never a re-bucket. */
export function rowsFor(opps: FeedRow[], zone: string, section: string): FeedRow[] {
  return opps.filter((o) => o.zone === zone && (zone === "diag" ? true : o.section === section));
}
