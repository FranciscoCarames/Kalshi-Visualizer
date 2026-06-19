/* Pure alert derivation for the ALERTS side panel — REAL change signals only, no fabricated rows.
 * Sourced from the existing client-side `changeOf` diff (the same display-only signal the blotter arrows
 * use — NOT a second lifecycle engine; the authoritative backend lifecycle powers the ALRT surface via
 * /backlog). The panel means "changes since the previous scan". Typed + None-safe so it never throws and
 * never invents text. Display-only; never feeds ranking/classification. */
import type { FeedRow, FeedMeta } from "./feed";

export type AlertKind = "new_actionable" | "returned_actionable" | "edge_up" | "edge_down" | "coverage_partial";
export type AlertSeverity = "info" | "review" | "warn";
export interface Alert { kind: AlertKind; severity: AlertSeverity; opportunity_id?: string; label: string; basis: string; }

export type ChangeFn = (id: string) => "new" | "up" | "down" | "returned" | null;

const SEV: Record<AlertKind, AlertSeverity> = {
  new_actionable: "info", returned_actionable: "info", edge_up: "info", edge_down: "review", coverage_partial: "warn",
};
export const ALERT_LABEL: Record<AlertKind, string> = {
  new_actionable: "became actionable", returned_actionable: "returned to actionable",
  edge_up: "edge up", edge_down: "edge down", coverage_partial: "series failed",
};

const MAX_ACTIONABLE = 6;   // cap each group so a big scan can't flood the panel
const MAX_MOVERS = 4;

/** Build the alert rows for the current snapshot vs the previous one. `hasBaseline` is false until a real
 * diff (≥2 distinct snapshots) has run — on first load only current-state warnings (coverage_partial) fire,
 * never a flood of false "new". Returns [] when nothing is alert-worthy (the caller shows the honest
 * baseline/empty message). NEVER emits a bucket-change row (no client-side prev-bucket truth). */
export function deriveAlerts(opps: FeedRow[], changeOf: ChangeFn, meta: FeedMeta | null, hasBaseline: boolean, hideFeeNeg = false): Alert[] {
  const out: Alert[] = [];
  const a = (kind: AlertKind, label: string, basis: string, opportunity_id?: string): Alert =>
    ({ kind, severity: SEV[kind], opportunity_id, label, basis });

  if (hasBaseline) {
    const becameAct: Alert[] = [];
    const movers: Alert[] = [];
    for (const o of opps || []) {
      const id = o?.id;
      if (!id) continue;
      // L4: a row hidden from the ACTIONABLE badge by the fee filter must not raise a contradicting alert.
      // Mirror filters.hiddenByFee (exec zone + net_negative); the suppressed count surfaces in the panel.
      if (hideFeeNeg && o.zone === "exec" && o.net_negative === true) continue;
      const c = changeOf(id);
      if (!c) continue;
      const name = String(o.name || id);
      if (o.section === "act" && c === "new") becameAct.push(a("new_actionable", name, "firm both legs · new this scan", id));
      else if (o.section === "act" && c === "returned") becameAct.push(a("returned_actionable", name, "returned to actionable this scan", id));
      else if (c === "up") movers.push(a("edge_up", name, "edge up since last scan", id));
      else if (c === "down") movers.push(a("edge_down", name, "edge down since last scan", id));
    }
    out.push(...becameAct.slice(0, MAX_ACTIONABLE), ...movers.slice(0, MAX_MOVERS));
  }

  const failed = meta?.failed ?? 0;       // current-state coverage warning — valid even on first load
  if (failed > 0) out.push(a("coverage_partial", `${failed} series failed`, "coverage partial — see OPS"));
  return out;
}
