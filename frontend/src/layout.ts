/* Workspace layout model — the serializable snapshot the user can customize (column widths, per-panel
 * height/collapse/hide, and the panel ORDER per column) plus the preset derivations and a defensive
 * sanitizer. Kept pure + framework-free so it is unit-testable and shared by Workspace.tsx (live) and
 * context.tsx (persist/hydrate). DISPLAY-only chrome state; nothing here touches engine data. */

export type Col = "L" | "M" | "R";
export interface PanelState { collapsed: boolean; maxed: boolean; hidden: boolean; basis?: number; }
export interface LayoutSnapshot {
  colW: { M: number; R: number };
  colHidden: { M: boolean; R: boolean };
  st: Record<string, PanelState>;
  cols: { L: string[]; M: string[]; R: string[] };
}

// The fixed singleton panel registry (ids only — bodies live in Workspace.tsx). Persistence validates
// against this list; the server mirrors it in config.PREFS_PANEL_IDS.
export const PANEL_IDS = ["p-blotter", "p-des", "p-ladder", "p-watch", "p-alerts", "p-research"] as const;
export const DEFAULT_COLS: { L: string[]; M: string[]; R: string[] } = {
  L: ["p-blotter", "p-des"], M: ["p-ladder"], R: ["p-watch", "p-alerts", "p-research"],
};

const clampW = (v: number) => Math.max(60, Math.min(1000, v));
const clampBasis = (v: number) => Math.max(24, Math.min(2000, v));

function baseState(): Record<string, PanelState> {
  const st: Record<string, PanelState> = {};
  for (const id of PANEL_IDS) st[id] = { collapsed: false, maxed: false, hidden: false };
  return st;
}

/** A full snapshot for a named preset (pure mirror of the old Workspace.applyPreset). Unknown name → default. */
export function presetSnapshot(name: string): LayoutSnapshot {
  const st = baseState();
  const cols = { L: [...DEFAULT_COLS.L], M: [...DEFAULT_COLS.M], R: [...DEFAULT_COLS.R] };
  if (name === "triage") {
    st["p-des"].collapsed = true;
    return { st, cols, colHidden: { M: false, R: true }, colW: { M: 220, R: 290 } };
  }
  if (name === "inspect") {
    st["p-watch"].collapsed = st["p-alerts"].collapsed = st["p-research"].collapsed = true;
    st["p-des"].basis = 430;
    return { st, cols, colHidden: { M: false, R: false }, colW: { M: 470, R: 290 } };
  }
  if (name === "research") {
    st["p-alerts"].collapsed = true;
    st["p-des"].basis = 200;
    return { st, cols, colHidden: { M: false, R: false }, colW: { M: 330, R: 360 } };
  }
  if (name === "blotterfull") {
    st["p-des"].hidden = true;
    return { st, cols, colHidden: { M: true, R: true }, colW: { M: 330, R: 290 } };
  }
  return { st, cols, colHidden: { M: false, R: false }, colW: { M: 330, R: 290 } };
}

/** Validate + clamp a (possibly hostile / stale) saved layout into a usable snapshot, or null if it isn't an
 * object at all (caller then falls back to a preset). Enforces: colW clamped 60..1000; basis clamped 24..2000;
 * collapse/max/hidden are booleans; only KNOWN panel ids survive in `cols`/`st`; each panel appears AT MOST
 * ONCE across all columns (singleton — a duplicate is dropped); any known id missing from `cols` is restored to
 * its default column so a panel can never vanish. Fail-open by construction. */
export function cleanLayout(raw: unknown, knownIds: readonly string[] = PANEL_IDS): LayoutSnapshot | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const num = (v: unknown): number | null => (typeof v === "number" && isFinite(v) ? v : null);
  const bool = (v: unknown) => v === true;
  const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? v as Record<string, unknown> : {});

  const rw = obj(r.colW), rh = obj(r.colHidden);
  const colW = { M: clampW(num(rw.M) ?? 330), R: clampW(num(rw.R) ?? 290) };
  const colHidden = { M: bool(rh.M), R: bool(rh.R) };

  const rst = obj(r.st);
  const st: Record<string, PanelState> = {};
  for (const id of knownIds) {
    const s = obj(rst[id]);
    const b = num(s.basis);
    st[id] = { collapsed: bool(s.collapsed), maxed: bool(s.maxed), hidden: bool(s.hidden),
               ...(b != null ? { basis: clampBasis(b) } : {}) };
  }

  const rc = obj(r.cols);
  const seen = new Set<string>();
  const cleanCol = (arr: unknown): string[] => {
    const out: string[] = [];
    if (Array.isArray(arr)) {
      for (const x of arr) {
        const id = String(x);
        if (knownIds.includes(id) && !seen.has(id)) { seen.add(id); out.push(id); }   // singleton: no dupes
      }
    }
    return out;
  };
  const cols = { L: cleanCol(rc.L), M: cleanCol(rc.M), R: cleanCol(rc.R) };
  // Restore any known panel the saved layout forgot (e.g. a registry that grew) to its default column.
  for (const id of knownIds) {
    if (seen.has(id)) continue;
    const home: Col = DEFAULT_COLS.M.includes(id) ? "M" : DEFAULT_COLS.R.includes(id) ? "R" : "L";
    cols[home].push(id);
  }
  return { colW, colHidden, st, cols };
}
