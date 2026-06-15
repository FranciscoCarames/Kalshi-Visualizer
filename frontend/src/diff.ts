/* Change-signal diff vs the PREVIOUS snapshot (pure, display-only — never feeds ranking). The caller diffs
 * only when snapshot_id advances and passes `first=true` on the initial load so nothing flashes as "NEW".
 * A missing/NaN edge never yields a false up/down. */
import type { FeedRow } from "./feed";

export type Change = "new" | "up" | "down";

export function edgeMap(opps: FeedRow[]): Map<string, number> {
  return new Map(opps.map((o) => [o.id, typeof o.edge === "number" ? o.edge : NaN]));
}

export function diffSnapshot(prevEdge: Map<string, number>, opps: FeedRow[], first: boolean):
  { change: Map<string, Change>; flash: Set<string> } {
  const change = new Map<string, Change>();
  const flash = new Set<string>();
  if (first) return { change, flash };          // first load: no all-NEW flash
  for (const o of opps) {
    const e = typeof o.edge === "number" ? o.edge : NaN;
    if (!prevEdge.has(o.id)) { change.set(o.id, "new"); flash.add(o.id); continue; }
    const pe = prevEdge.get(o.id)!;
    if (e > pe) { change.set(o.id, "up"); flash.add(o.id); }       // NaN comparisons are false → no false signal
    else if (e < pe) { change.set(o.id, "down"); flash.add(o.id); }
  }
  return { change, flash };
}
