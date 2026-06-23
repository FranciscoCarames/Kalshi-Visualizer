/* Forward-test / paper-position harness — types + loaders for the PAPER surface.
 * The single source of truth is the backend GET /api/terminal/paper(+/positions); this file only types
 * its shape and renders it. It is a DISPLAY-ONLY view of a server-computed forward-test report — the SPA
 * never scores positions or places orders. Figures are net-of-fees under conservative paper-fill
 * assumptions (top-of-book, size-capped, no queue/slippage); the panel surfaces that caveat. */
import { apiFetch } from "./http";

export interface PaperAgg {
  settled: number; wins: number; losses: number; net_c: number;
  open: number; determined_pending: number; net_dollars: number; win_rate: number | null;
}

export interface PaperReport {
  enabled: boolean; fill_model: string;
  overall: PaperAgg;
  by_class: Record<string, PaperAgg>;
  by_bucket: Record<string, PaperAgg>;
  by_sport: Record<string, PaperAgg>;
  unscorable: number;
  fill_model_note: string;
}

export interface PaperLeg {
  ticker: string; side: string; entry_price_c: number; size: number | null;
  contract: string; result: string | null; payout_c: number | null;
}

export interface PaperPosition {
  entry_key: string; opportunity_id: string; first_snapshot_id: number | null; opened_ts: number | null;
  source_bucket: string; sport: string; relationship_type: string; opportunity_class: string;
  fill_model: string; cost_c: number | null; max_loss_c: number | null; status: string;
  gross_c: number | null; fees_c: number | null; net_c: number | null; won: number | null;
  settled_ts: number | null; legs: PaperLeg[];
}

export async function loadPaperReport(): Promise<PaperReport> {
  const r = await apiFetch("/api/terminal/paper", { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("paper " + r.status);
  return r.json();
}

export async function loadPaperPositions(status?: string): Promise<PaperPosition[]> {
  const q = status ? "?status=" + encodeURIComponent(status) : "";
  const r = await apiFetch("/api/terminal/paper/positions" + q, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("paper positions " + r.status);
  return (await r.json()).positions ?? [];
}

/** Dollars from integer cents, SIGNED, 2dp (for P&L; null/undefined → "—"). */
export function dollars(c: number | null | undefined): string {
  if (c == null) return "—";
  const v = c / 100;
  return (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2);
}

/** Dollars from integer cents, UNSIGNED, 2dp (for a cost/outlay; null/undefined → "—"). */
export function money(c: number | null | undefined): string {
  if (c == null) return "—";
  return "$" + (c / 100).toFixed(2);
}
