/* Per-column click-sort for the blotter — a PURE DISPLAY OVERRIDE on top of the engine/lens order. It
 * never changes a row's bucket/status/rank; clearing the sort (or switching section) returns to engine
 * order. Nulls/blanks always sort last in both directions (audit). */
import type { FeedRow } from "./feed";
import { qualityOf, type Fmt } from "./columns";

export type SortDir = "asc" | "desc";
export interface SortState { field: string; dir: SortDir; }

const isNumericFmt = (fmt: Fmt) => fmt !== "text" && fmt !== "name" && fmt !== "trad" && fmt !== "qh";

/** Sort a COPY by one column. `fmtOf` gives the column's format (numeric vs string). Nulls last. Stable. */
export function sortRows(rows: FeedRow[], state: SortState | null, fmtOf: (f: string) => Fmt): FeedRow[] {
  if (!state) return rows;
  // "quality" (Setup quality) is a DERIVED column — not a stored row field — so sort it by its computed
  // numeric score (ripeness × conditional); "Insufficient data" (score null) sorts last like any blank.
  const numeric = state.field === "quality" || isNumericFmt(fmtOf(state.field));
  const key = (o: FeedRow): number | string | null => {
    if (state.field === "quality") { const s = qualityOf(o).score; return s == null ? null : s; }
    const v = o[state.field];
    if (v == null || v === "") return null;
    if (numeric) { const n = typeof v === "number" ? v : Number(v); return Number.isNaN(n) ? null : n; }
    return String(v).toLowerCase();
  };
  const sign = state.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka === null && kb === null) return 0;
    if (ka === null) return 1;            // nulls last regardless of direction
    if (kb === null) return -1;
    return ka < kb ? -1 * sign : ka > kb ? 1 * sign : 0;
  });
}

/** 3-state header-click cycle for one field: none → asc → desc → none (back to engine/lens order). */
export function nextSort(cur: SortState | null, field: string): SortState | null {
  if (!cur || cur.field !== field) return { field, dir: "asc" };
  if (cur.dir === "asc") return { field, dir: "desc" };
  return null;
}
