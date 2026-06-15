/* Loaders for the read-only participant drill-down + chart endpoints (Stage 1 backend).
 * Everything here is DISPLAY-ONLY (gross, top-of-book, uncalibrated); it never feeds bucket/rank. */
import type { FeedRow } from "./feed";

export interface DetailBundle {
  chain: Record<string, unknown>[];
  indicators: Record<string, unknown>[];
  spreads: Record<string, unknown>[];
  expected: Record<string, unknown>[];
  contracts: Record<string, unknown>[];
  raw_fields: Record<string, unknown>[];
  link_audit: Record<string, unknown>[];
  duplicates: Record<string, unknown>[];
  rules: { contract: string; text: string }[];
}
export interface PayoffData { scenarios: { scenario: string; payout_c: number | null; profit_c: number | null; role: string }[]; cost_c: number | null; }
export interface LadderData { layers: { layer: string; display_pct: number | null; rank: number; inverted: boolean }[]; }

/** The (sport_key, player_key, tournament) a detail/ladder fetch needs, or null when the row can't anchor
 * a participant (e.g. a dutch-book field/game with no single participant). */
export function detailKey(row: FeedRow | null): { sport: string; player_key: string; tournament: string } | null {
  if (!row) return null;
  const sport = String(row.sport_key || "");
  const player_key = String(row.player_key || "");
  const tournament = String(row.tournament || "");
  return sport && player_key && tournament ? { sport, player_key, tournament } : null;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { headers: { Accept: "application/json" }, signal });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

/** Live resting order book for one market (the SPA depth ladder). yes/no are [price_c, size] ascending
 * (best bid last). DISPLAY-ONLY depth — gross/top-of-book limits still apply; not net executable capacity. */
export interface OrderbookData {
  ticker: string; yes: number[][]; no: number[][]; ok: boolean; error: string | null; age_s: number;
}
export const loadOrderbook = (ticker: string, signal?: AbortSignal) =>
  getJson<OrderbookData>(`/api/terminal/orderbook?ticker=${encodeURIComponent(ticker)}`, signal);

export const loadDetail = (k: { sport: string; player_key: string; tournament: string }) =>
  getJson<DetailBundle>(`/api/terminal/detail?sport=${encodeURIComponent(k.sport)}&player_key=${encodeURIComponent(k.player_key)}&tournament=${encodeURIComponent(k.tournament)}`);

export const loadLadder = (k: { sport: string; player_key: string; tournament: string }) =>
  getJson<LadderData>(`/api/terminal/ladder?sport=${encodeURIComponent(k.sport)}&player_key=${encodeURIComponent(k.player_key)}&tournament=${encodeURIComponent(k.tournament)}`);

export const loadPayoff = (opportunityId: string) =>
  getJson<PayoffData>(`/api/terminal/payoff?opportunity_id=${encodeURIComponent(opportunityId)}`);

export interface Diagnostics {
  checks: Record<string, unknown>[]; contracts: Record<string, unknown>[];
  category: Record<string, unknown>; failures: Record<string, unknown>;
  checks_truncated: number; contracts_truncated: number;
}
export const loadDiagnostics = () => getJson<Diagnostics>("/api/terminal/diagnostics");

export interface BacklogItem { opportunity_id?: string; sport?: string; name?: string; became_ts?: number; left_ts?: number; duration_s?: number; reason_left?: string; last_edge_c?: number; }
export interface BacklogInterval { category?: string; sport?: string; name?: string; first_seen_ts?: number; left_ts?: number; duration_s?: number; peak_roi_pct?: number; last_status?: string; is_open?: boolean; }
export const loadBacklog = (windowS = 3600) => getJson<BacklogItem[]>(`/backlog?window_s=${windowS}`);
export const loadBacklogEvents = (days = 7) => getJson<BacklogInterval[]>(`/backlog/events?days=${days}`);

export interface Telemetry {
  snapshot_id: number | null;
  top_sports: unknown[][]; top_contracts: unknown[][]; tightest: unknown[][]; most_traded: unknown[][];
  volatility: string | null;
}
export const loadTelemetry = () => getJson<Telemetry>("/api/terminal/telemetry");
