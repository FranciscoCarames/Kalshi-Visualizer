/* Copy trade reference (#8) — a READ-ONLY clipboard reference for the selected opportunity.
 * NOT an order, not order entry, not automation: plain text only, buy-only wording, every caveat the row
 * carries, and an explicit "verify the current book" guard. `buildReference` is PURE (unit-tested); the
 * thin `copyReference` wrapper writes to the clipboard with a legacy fallback for non-secure/pop-out
 * contexts. Prices respect the active $1/$100 basis; sides use the canonical buy-only YES/NO (clearer and
 * safer for an order reference than the LONG/SHORT display toggle — and never the word "sell"/"short"). */
import type { FeedRow } from "./feed";

const fmtC = (c: unknown, basis: number): string => {
  const n = typeof c === "number" && !isNaN(c) ? c : null;
  return n == null ? "—" : basis === 100 ? "$" + (n / 100).toFixed(2) : Math.round(n) + "¢";
};

/** A short, human "what kind of row" line so a copied reference never reads as a trade plan when it isn't. */
function zoneNote(row: FeedRow): string {
  if (row.zone === "diag") return "DIAGNOSTIC ONLY — not a trade plan.";
  if (row.section === "specmodel") return "SPECULATIVE MODEL — market-implied, not fair value, not arbitrage; can lose money.";
  if (row.section === "nm") return "WATCHLIST / NEAR-MISS — not an executable edge.";
  if (row.zone === "spec" || row.section === "bounded") return "BOUNDED-LOSS SPECULATION — can lose money.";
  if (row.section === "rev") return "REVIEW — settlement/rule-dependent; confirm the rules before trading.";
  return "Structural buy-only plan. Gross, top-of-book.";
}

/** Build the plain-text reference. PURE — no clipboard, no Date; the caller passes the snapshot capture
 * time so the output is deterministic and testable. */
export function buildReference(
  row: FeedRow,
  opts: { basis: number; longShort?: boolean; snapshotId: number | null; capturedAt: string | null },
): string {
  const { basis, snapshotId, capturedAt } = opts;
  const L: string[] = [];
  L.push("KALSHI STRUCTURED SCANNER — TRADE REFERENCE (read-only)");
  L.push("Not an order. Gross, top-of-book; fees / collateral / position limits not modelled.");
  L.push("VERIFY THE CURRENT BOOK BEFORE TRADING — quotes may have moved since this snapshot.");
  L.push("");
  L.push(`${row.name ?? "(unnamed)"}${row.sport ? "  ·  " + row.sport : ""}`);
  L.push(zoneNote(row));
  L.push(`Snapshot #${snapshotId ?? "—"}${capturedAt ? "  ·  captured " + capturedAt : ""}`);

  const legs = (row.legs ?? []).filter((l) => !l.bo);   // book-only pseudo-legs are references, not buys
  if (legs.length) {
    L.push("");
    L.push(`BUY-ONLY PLAN — ${legs.length} leg${legs.length === 1 ? "" : "s"} (buy the same count on every leg, capped by the thinnest leg):`);
    for (const l of legs) {
      const side = String(l.side || "").includes("yes") ? "BUY YES " : "BUY NO  ";
      const tk = l.tk ? ` [${l.tk}]` : "";
      const sz = l.sz != null ? `  (top quote ${l.sz})` : "";
      L.push(`  ${side}${l.c ?? ""}${tk} @ ${fmtC(l.p, basis)}${sz}`);
    }
  } else {
    L.push("");
    L.push("(No buy-only legs on this row.)");
  }

  L.push("");
  L.push("ECONOMICS (per unit, gross/top-of-book):");
  L.push(`  Cost ${fmtC(row.cost, basis)}  ·  Worst ${fmtC(row.max_loss, basis)}  ·  Best ${fmtC(row.max_profit ?? row.profit, basis)}`);
  const roi = typeof row.roi === "number" ? row.roi.toFixed(1) + "%" : "—";
  const mu = (row.max_units ?? row.units);
  L.push(`  ROI ${roi}  ·  Max units ${mu ?? "—"}  ·  Quote ${row.quote_health ?? "—"}  ·  Tradable ${row.tradable ?? "—"}`);

  const caveats = [row.settlement_caveat, row.rule, row.blk].filter((x) => x && String(x).trim());
  if (caveats.length) {
    L.push("");
    L.push("CAVEATS:");
    for (const c of caveats) L.push(`  - ${c}`);
  }
  L.push("");
  L.push(`opportunity_id: ${row.id}`);
  return L.join("\n");
}

/** Write text to the clipboard; resolves true on success. Falls back to a hidden <textarea> + execCommand
 * for non-secure (LAN http) / pop-out contexts where navigator.clipboard is unavailable. Never throws. */
export async function copyReference(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
