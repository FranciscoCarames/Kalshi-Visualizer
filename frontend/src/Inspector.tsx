/* Inspector — the DES trade card. Ported from ui-mockup-final-spa.html des().
 * Read-only, buy-only, gross. Display-only $1⇄$100 basis. Every field is the engine's; the "why ranked"
 * is a display narrative (lens-relative), not a model. */
import { useState } from "react";
import type { FeedRow } from "./feed";
import { rankWhy } from "./lens";

const ZB: Record<string, [string, string]> = {
  exec: ["bk-exec", "EXECUTABLE"], spec: ["bk-spec", "SPECULATIVE"], diag: ["bk-diag", "DIAGNOSTIC"],
};
const num = (v: unknown) => (typeof v === "number" && !isNaN(v) ? v : null);

export default function Inspector({ row, lens, snapshotId }: { row: FeedRow | null; lens: string; snapshotId: number | null }) {
  const [basis, setBasis] = useState(1);
  if (!row) return <div className="empty">Click a blotter row to load the trade card — legs · economics · evidence.</div>;
  const cv = (c: unknown) => { const n = num(c); return n == null ? "—" : basis === 100 ? "$" + (n / 100).toFixed(2) : Math.round(n) + "¢"; };
  const z = ZB[row.zone] ?? ZB.diag;
  const isSpec = row.zone === "spec";
  const w = rankWhy(row);
  const legs = row.legs ?? [];
  return (
    <div className="des">
      <div className="dtitle">
        <span className={"bk " + z[0]}>{z[1]}</span>
        <span className="t">{row.name}</span>
        <div className="basis">
          <button className={basis === 1 ? "on" : ""} onClick={() => setBasis(1)}>$1</button>
          <button className={basis === 100 ? "on" : ""} onClick={() => setBasis(100)}>$100</button>
        </div>
      </div>
      <div className="sub">{[row.sub || row.detail, row.sport, row.resolution_mode, row.scope].filter(Boolean).join(" · ")}</div>

      <div className="sect">BUY-ONLY PLAN — {row.nlegs ?? legs.length} LEG{(row.nlegs ?? legs.length) === 1 ? "" : "S"}</div>
      {legs.length ? legs.map((l, i) => {
        const yes = String(l.side || "").includes("yes");
        return (
          <div className="leg" key={i}>
            <span className={yes ? "y" : "n"}>{yes ? "YES" : "NO"}</span>
            <span className="l2">{l.c}</span>
            <span className="white">{l.p != null ? l.p + "¢" : "—"}</span>
            <span className="dim">×{l.sz ?? 0}</span>
            {l.u ? <a href={l.u} target="_blank" rel="noreferrer">↗</a> : null}
          </div>
        );
      }) : <div className="note">No leg detail.</div>}

      <div className="sect">ECONOMICS (PER UNIT)</div>
      <div className="kv">
        <span className="l">Cost</span><span className="v">{cv(row.cost)}</span>
        <span className="l">{isSpec ? "Max loss" : "Worst case"}</span><span className="v red">{cv(row.max_loss)}</span>
        <span className="l">{isSpec ? "Max profit" : "Best case"}</span><span className="v green">{cv(row.max_profit ?? row.profit)}</span>
        <span className="l">ROI</span><span className="v">{num(row.roi) == null ? "—" : (row.roi as number).toFixed(1) + "%"}</span>
        <span className="l">Max units</span><span className="v">{num(row.max_units ?? row.units) ?? "—"}</span>
        <span className="l">Quote</span><span className="v">{row.quote_health || "—"}</span>
        <span className="l">Tradable</span>
        <span className={"v " + (String(row.tradable || "").toLowerCase().startsWith("yes") ? "green" : "amber")}>{row.tradable || "—"}</span>
        {row.parent_over_maxloss != null
          ? <><span className="l">Ripeness (parent÷loss)</span><span className="v amber">{(row.parent_over_maxloss as number).toFixed(2)}</span></>
          : null}
      </div>

      <div className="sect">WHY RANKED HERE · {(lens || "ENGINE ORDER").toUpperCase()}</div>
      <div className="why"><b>Promotes:</b><span className="green">{w.up}</span></div>
      <div className="why"><b>Demotes:</b><span className="dim">{w.down}</span></div>

      {row.rule || row.settlement_caveat
        ? <><div className="sect">SETTLEMENT / RULES</div>
            <div className="note">{row.rule ? <span className="uncal">{String(row.rule)} </span> : null}{row.settlement_caveat || row.caveat || ""}</div></>
        : null}
      {row.blk ? <div className="donoth"><b>BLOCKED:</b> {String(row.blk)}</div> : null}
      {isSpec ? <div className="donoth"><b>NOT AN EDGE:</b> bounded-loss speculation — can lose money; metrics gross/top-of-book, never feed actionability.</div> : null}

      <div className="sect">EVIDENCEPACK</div>
      <div className="kv">
        <span className="l">Snapshot</span><span className="v">#{snapshotId ?? "—"}</span>
        <span className="l">Status</span><span className="v">{row.status || "—"}</span>
        <span className="l">Opp id</span><span className="v">{row.id}</span>
        {row.url ? <><span className="l">Market</span><span className="v"><a href={String(row.url)} target="_blank" rel="noreferrer" className="cyan">open ↗</a></span></> : null}
      </div>
    </div>
  );
}
