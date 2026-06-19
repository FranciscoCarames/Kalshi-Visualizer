/* Client-side CSV export of the current view / selected rows (no server round-trip).
 * Values match what the column FORMATTER means: `cmoney` fields are stored in CENTS but shown in dollars, so
 * they are exported scaled to dollars (e.g. 842 → "8.42"); a "$"-labeled column never emits a raw cents int.
 * Text cells get CSV formula-injection protection (a leading '=','+','-','@', tab/CR/LF is neutralised with a
 * leading apostrophe) so a hostile market title can't execute when the file is opened in a spreadsheet — parity
 * with the NiceGUI ZIP export's CSV defense. `buildCsv` is pure (exported for tests); `downloadCsv` wraps it. */
import type { FeedRow } from "./feed";
import type { Col } from "./columns";

// Spreadsheet formula triggers (OWASP CSV-injection): a cell starting with any of these is data, not a formula.
const FORMULA_TRIGGER = /^[=+\-@\t\r\n]/;
// Only free-text columns carry untrusted market strings; our own numeric formats are safe (and must not be
// mangled — e.g. a negative "-0.02" should stay numeric, not become text "'-0.02").
const TEXT_FMTS = new Set(["text", "name", "qh", "trad"]);

/** One CSV cell value (pre-quoting) for column `c` of row `r`. Pure; exported for tests. */
export function csvCell(c: Col, r: FeedRow): string {
  if (c.f === "basis_flags")               // synthetic column: export the honesty chips, not an (empty) field
    return [r.midpoint_only ? "MID-ONLY" : "", r.wide_basis ? "WIDE" : ""].filter(Boolean).join(" ");
  const v = r[c.f];
  if (c.fmt === "cmoney") {                 // stored in CENTS → export dollars to match the "$" header
    const n = typeof v === "number" ? v : (v == null || v === "" ? NaN : Number(v));
    return Number.isFinite(n) ? (n / 100).toFixed(2) : "";
  }
  let s = v == null ? "" : String(v);
  if (TEXT_FMTS.has(c.fmt) && FORMULA_TRIGGER.test(s)) s = "'" + s;   // neutralise formula injection on text cells
  return s;
}

/** Build the full CSV text (header + rows). Pure; exported for tests. */
export function buildCsv(rows: FeedRow[], cols: Col[]): string {
  const esc = (v: string) => (/[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v);
  const header = cols.map((c) => esc(c.l)).join(",");
  const body = rows.map((r) => cols.map((c) => esc(csvCell(c, r))).join(",")).join("\n");
  return header + "\n" + body;
}

export function downloadCsv(filename: string, rows: FeedRow[], cols: Col[]): void {
  const blob = new Blob([buildCsv(rows, cols)], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
