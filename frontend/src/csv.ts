/* Client-side CSV export of selected rows (no server round-trip). Raw field values, current columns. */
import type { FeedRow } from "./feed";
import type { Col } from "./columns";

export function downloadCsv(filename: string, rows: FeedRow[], cols: Col[]): void {
  const esc = (v: string) => (/[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v);
  const header = cols.map((c) => esc(c.l)).join(",");
  const body = rows.map((r) => cols.map((c) => {
    const v = r[c.f];
    return esc(v == null ? "" : String(v));
  }).join(",")).join("\n");
  const blob = new Blob([header + "\n" + body], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
