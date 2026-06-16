/* Dynamic multi-selection views shown in the workspace's "extra" overlay panel (Compare / Don't-take-both /
 * Open ladders). Prop-based and library-free — no Dockview, no AG-Grid. Read-only; never changes ranking. */
import type { ReactNode } from "react";
import type { FeedRow } from "./feed";
import Ladder from "./Ladder";

function fmtField(o: FeedRow, f: string): string {
  const v = o[f];
  if (v == null || v === "") return "—";
  if (typeof v === "number") {
    if (["cost", "max_loss", "max_profit", "edge"].includes(f)) return Math.round(v) + "¢";
    if (f === "roi" || f === "cond_child" || f === "cond_success") return v.toFixed(1) + "%";
    if (f === "parent_over_maxloss") return v.toFixed(2);
    return String(v);
  }
  return String(v);
}

const COMPARE_FIELDS: [string, string][] = [
  ["sport", "Sport"], ["section", "Section"], ["sub", "Tournament"], ["cost", "Cost ¢"], ["max_loss", "Max loss ¢"],
  ["max_profit", "Max profit ¢"], ["roi", "ROI %"], ["edge", "Edge ¢"], ["cond_child", "Deeper|reached %"],
  ["parent_over_maxloss", "Ripeness"], ["quote_health", "Quote"], ["tradable", "Tradable"],
];

export function CompareView({ opps }: { opps: FeedRow[] }) {
  return (
    <div style={{ padding: 4 }}>
      <table className="condtbl">
        <thead><tr><th>Metric</th>{opps.map((o) => <th key={o.id} className="r">{String(o.name || "").slice(0, 18)}</th>)}</tr></thead>
        <tbody>{COMPARE_FIELDS.map(([f, l]) => (
          <tr key={f}><td className="dim">{l}</td>{opps.map((o) => <td key={o.id} className="r">{fmtField(o, f)}</td>)}</tr>
        ))}</tbody>
      </table>
      <div className="note" style={{ padding: 4 }}>Read-only comparison · gross top-of-book · selecting rows never implies multiple orders.</div>
    </div>
  );
}

const yesNo = (s: unknown): "yes" | "no" | "" => {
  const v = String(s || "").toLowerCase();
  return v.includes("yes") ? "yes" : v.includes("no") ? "no" : "";
};

export function OverlapView({ opps }: { opps: FeedRow[] }) {
  const warns: ReactNode[] = [];
  for (let i = 0; i < opps.length; i++) {
    for (let j = i + 1; j < opps.length; j++) {
      const A = opps[i], B = opps[j], why: string[] = [];
      if (A.name && A.name === B.name && A.sport === B.sport) why.push(`same participant ${A.name}`);
      // Shared markets, side-aware: same side on the shared ticker = doubling; opposite = offsetting (a hedge).
      const sideA = new Map<string, string>();
      (A.legs || []).forEach((l) => { if (l.tk) sideA.set(l.tk, yesNo(l.side)); });
      const known: boolean[] = []; let shared = 0;
      (B.legs || []).forEach((l) => {
        if (!l.tk || !sideA.has(l.tk)) return;
        shared++;
        const sa = sideA.get(l.tk) || "", sb = yesNo(l.side);
        if (sa && sb) known.push(sa === sb);     // true = same side, false = opposite
      });
      if (shared) {
        const verdict = !known.length ? "overlapping exposure — check sides"
          : known.every(Boolean) ? "doubling exposure"
          : known.every((s) => !s) ? "offsetting exposure (hedge)"
          : "mixed overlap — inspect legs";
        why.push(`${shared} shared market${shared > 1 ? "s" : ""} → ${verdict}`);
      }
      if (why.length) warns.push(
        <div className="arow" key={`${i}-${j}`}><span className="ic" style={{ background: "var(--amber)" }} />
          <div><b className="white">{String(A.name).slice(0, 18)}</b> &amp; <b className="white">{String(B.name).slice(0, 18)}</b> — {why.join(", ")}</div>
        </div>);
    }
  }
  return (
    <div>
      <div className="note" style={{ padding: "4px 6px" }}>Flags selected opportunities that share a participant or market. Shared markets are checked side-aware — same side <b>doubles</b> exposure, opposite sides <b>offset</b> (a hedge). Read-only heuristic, never changes ranking.</div>
      {warns.length ? warns : <div className="note" style={{ padding: 6 }}><span className="green">No shared participant or market</span> among the {opps.length} selected — they look independent.</div>}
    </div>
  );
}

export function LaddersView({ opps }: { opps: FeedRow[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: 6 }}>
      {opps.slice(0, 8).map((o) => (
        <div key={o.id} className="panel" style={{ width: 280, flex: "0 0 auto", maxHeight: 360 }}>
          <div className="ph"><span className="n">▦</span><h3 style={{ fontSize: 9 }}>{String(o.name).slice(0, 22)}</h3></div>
          <Ladder row={o} />
        </div>
      ))}
    </div>
  );
}
