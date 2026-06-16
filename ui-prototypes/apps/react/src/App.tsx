import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { ModuleRegistry, AllCommunityModule, type GridApi, type ColDef } from "ag-grid-community";
import { createStream } from "@bakeoff/shared/stream";
import { createPerf } from "@bakeoff/shared/perf";
import type { Row } from "@bakeoff/shared/data";

ModuleRegistry.registerModules([AllCommunityModule]);

const stream = createStream(200, 30);
const perf = createPerf("React + AG Grid");

const BUCKETS = [["act", "ACTIONABLE", "act"], ["rev", "REVIEW", "rev"], ["blk", "BLOCKED", "blk"], ["res", "RESEARCH", "res"]];
const LENSES = [["blended", "BLENDED", "edge"], ["edge", "EDGE", "edge"], ["roi", "ROI", "roi"], ["ev", "IMPLIED EV", "roi"]];

function chgSym(c: string) { return c === "new" ? "NEW" : c === "up" ? "▲" : c === "down" ? "▼" : c === "ret" ? "↺" : ""; }

export default function App() {
  const apiRef = useRef<GridApi | null>(null);
  const bucketRef = useRef("act");
  const [bucket, setBucket] = useState("act");
  const [lens, setLens] = useState("blended");
  const [sel, setSel] = useState<Row | null>(stream.rows[0]);
  const [basis, setBasis] = useState(1);
  const initialRows = useMemo(() => stream.rows, []);

  const columnDefs = useMemo<ColDef[]>(() => [
    { headerName: "", field: "chg", width: 40, valueFormatter: p => chgSym(p.value), cellClass: p => p.data.chg === "up" ? "green" : p.data.chg === "down" ? "red" : p.data.chg === "new" ? "green" : "amber" },
    { field: "sport", width: 84, headerName: "SPT" },
    { field: "name", headerName: "Participant / match", flex: 2, minWidth: 220, cellRenderer: (p: any) => <span><span className="nm">{p.data.name}</span> <span className="sub">{p.data.sub}</span></span> },
    { field: "setup", flex: 1, minWidth: 120 },
    { field: "edge", headerName: "Edge¢", width: 84, type: "rightAligned" },
    { field: "roi", headerName: "ROI%", width: 76, type: "rightAligned", valueFormatter: p => p.value ? (+p.value).toFixed(1) : "—" },
    { field: "units", headerName: "Units", width: 80, type: "rightAligned", valueFormatter: p => p.value || "—" },
    { field: "profit", headerName: "Profit$", width: 84, type: "rightAligned", valueFormatter: p => p.value ? (+p.value).toFixed(2) : "—" },
    { field: "tradable", width: 120, cellClass: p => p.value === "Yes" ? "tradable-yes" : p.value === "No" ? "tradable-no" : "tradable-rule" },
    { field: "cav", headerName: "Caveat", flex: 1, minWidth: 130, cellClass: p => p.data.sev === "blk" ? "red" : p.data.sev === "rev" ? "amber" : "dim" },
  ], []);

  useEffect(() => {
    const unsub = stream.subscribe((batch) => {
      const api = apiRef.current; if (!api) return;
      if (batch.reset) {
        api.setGridOption("rowData", stream.rows);
      } else {
        api.applyTransaction({ update: batch.changed });
        const nodes = batch.changed.map(r => api.getRowNode(r.id)).filter(Boolean) as any[];
        if (nodes.length) api.flashCells({ rowNodes: nodes, columns: ["edge"], flashDuration: 500 });
      }
      perf.recordLatency(performance.now() - batch.t0);
      perf.recordBatch();
    });
    perf.mount(
      (rows, rate) => stream.setStress(rows, rate),
      (mode) => stream.setMode(mode as any),
    );
    stream.start();
    return () => { unsub(); stream.stop(); };
  }, []);

  function onLens(l: string, col: string) {
    setLens(l);
    apiRef.current?.applyColumnState({ state: [{ colId: col, sort: "desc" }], defaultState: { sort: null } });
  }
  function onBucket(b: string) { setBucket(b); bucketRef.current = b; apiRef.current?.onFilterChanged(); }

  return (
    <div className="tp-app">
      <div className="tp-cmd">
        <div className="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div className="ci"><span className="amber">&gt;</span><input placeholder="FUNCTION OR TICKER, THEN <GO>" /><button className="go">&lt;GO&gt;</button></div>
        <div className="badge">KALSHI&lt;WS&gt;</div>
      </div>
      <div className="tp-scanbar" />
      <div className="tp-stat">
        <span className="s"><b className="green">●</b> SCAN IDLE · 12s</span>
        <span className="s">Contracts <b>1,204</b></span><span className="s">Checks <b>747</b></span><span className="s">Req <b>49</b></span>
        <span className="s"><b className="green">●</b> Exchange Open</span><span className="s">Auto-scan <b>on · 30s</b></span>
        <span className="s"><b className="amber">●</b> Failed <b>1</b></span><span className="s">DB <b>42 MB</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>
      <div className="tp-bar2">
        <div className="tab on"><span style={{ color: "var(--green)", fontSize: 8 }}>1)</span>OPP</div>
        <div className="tab"><span style={{ color: "var(--green)", fontSize: 8 }}>2)</span>RES</div>
        <div className="tab"><span style={{ color: "var(--green)", fontSize: 8 }}>3)</span>OPS</div>
        <div className="right">
          <span className="dim" style={{ fontSize: 9 }}>LENS</span>
          <div className="tp-lens">{LENSES.map(([l, lbl, col]) => <button key={l} className={lens === l ? "on" : ""} onClick={() => onLens(l, col)}>{lbl}</button>)}</div>
        </div>
      </div>
      <div className="tp-tiles">
        {[["ACT-NOW", "4", "green", "executable"], ["REVIEW", "2", "amber", "settlement"], ["NEW", "2", "", "this scan"], ["MOVERS", "3", "", "edge moved"], ["STALE", "1", "red", "one-sided"], ["FAILED", "1", "amber", "KXMOTOGP"], ["TOP LENS", "+7¢", "green", "Sinner"]].map((t, i) =>
          <button className="tp-tile" key={i}><div className="k">{t[0]}</div><div className={"v " + t[2]}>{t[1]}</div><div className="s">{t[3]}</div></button>)}
      </div>

      <div className="tp-ws">
        <div className="tp-panel tp-bl">
          <div className="tp-ph"><span className="n">1</span><h3>BLOTTER</h3><span className="meta">streaming · click row → DES + ladder</span></div>
          <div className="tp-bt">{BUCKETS.map(([b, lbl, cls]) => <div key={b} className={"btb " + cls + (bucket === b ? " on" : "")} onClick={() => onBucket(b)}>{lbl}</div>)}</div>
          <div className="tp-pb">
            <AgGridReact
              theme="legacy"
              className="ag-theme-quartz ag-theme-bakeoff"
              rowData={initialRows}
              columnDefs={columnDefs}
              defaultColDef={{ sortable: true, resizable: true }}
              getRowId={(p) => p.data.id}
              rowSelection={{ mode: "singleRow", enableClickSelection: true, checkboxes: false }}
              suppressCellFocus={true}
              isExternalFilterPresent={() => true}
              doesExternalFilterPass={(node: any) => node.data.bucket === bucketRef.current}
              onGridReady={(e) => { apiRef.current = e.api; e.api.applyColumnState({ state: [{ colId: "edge", sort: "desc" }] }); }}
              onRowClicked={(e: any) => setSel({ ...e.data })}
            />
          </div>
        </div>

        <div className="tp-panel tp-de">
          <div className="tp-ph"><span className="n">2</span><h3>DES — TRADE CARD</h3></div>
          <div className="tp-pb">{sel ? <Card row={sel} basis={basis} setBasis={setBasis} /> : <div className="empty">Click a row.</div>}</div>
        </div>

        <div className="tp-panel tp-la">
          <div className="tp-ph"><span className="n">3</span><h3>MD LADDER</h3></div>
          <div className="lw">READ-ONLY DEPTH VIEW — NO ORDERS</div>
          {sel ? <Ladder row={sel} /> : <div className="empty">—</div>}
        </div>

        <div className="tp-panel tp-wa"><div className="tp-ph"><span className="n">★</span><h3>WATCH · MOVERS</h3></div>
          <div className="tp-pb"><Watch onPick={setSel} /></div></div>
        <div className="tp-panel tp-al"><div className="tp-ph"><span className="n">!</span><h3>ALERTS</h3></div>
          <div className="tp-pb"><Alerts /></div></div>
      </div>

      <div className="tp-ft"><b>7-REACT + AG GRID</b><span className="dim">virtual-DOM benchmark · AG Grid transactions + flash · stress it in the PERF overlay →</span></div>
    </div>
  );
}

function Ladder({ row }: { row: Row }) {
  if (row.bucket === "res" || !row.touch) return <div className="empty">research — no executable book</div>;
  const base = row.touch, max = (row.fill * 3.2) || 120, rows = [];
  for (let p = base + 5; p >= base - 5; p--) {
    const bid = p <= base ? Math.round(row.fill * (1 + (base - p) * 0.7)) : 0;
    const ask = p >= base ? Math.round(row.fill * (1 + (p - base) * 0.6)) : 0;
    rows.push(
      <tr key={p}>
        <td className="bc">{bid ? <><span className="f" style={{ width: Math.min(100, bid / max * 100) + "%" }} /><span>{bid}</span></> : null}</td>
        <td className={"px" + (p === base ? " t" : "")}>{p}{p === base + 2 ? <span className="tg">◀ watch</span> : null}</td>
        <td className="ac">{ask ? <><span className="f" style={{ width: Math.min(100, ask / max * 100) + "%" }} /><span>{ask}</span></> : null}</td>
      </tr>);
  }
  return (<>
    <div className="lh"><div className="t">{row.name} <span className="dim">· {row.sport}</span></div><div className="s">{row.legs[0]?.label}</div></div>
    <div className="tp-pb"><table className="lt"><thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead><tbody>{rows}</tbody></table></div>
    <div className="lf"><span>Touch {base}¢ · eff fill@50 ≈ {row.cost + 1}¢</span><span>max fill {row.fill}</span></div>
  </>);
}

function Card({ row, basis, setBasis }: { row: Row; basis: number; setBasis: (n: number) => void }) {
  const cv = (c: number) => basis === 100 ? "$" + c.toFixed(2) : c + "¢";
  return (
    <div className="des">
      <div className="col">
        <div className="dt"><span className={"bk bk-" + row.bucket}>{row.bucket.toUpperCase()}</span><span className="t">{row.name}</span>
          <div className="basis"><button className={basis === 1 ? "on" : ""} onClick={() => setBasis(1)}>$1</button><button className={basis === 100 ? "on" : ""} onClick={() => setBasis(100)}>$100</button></div></div>
        <div className="sub" style={{ marginBottom: 3 }}>{row.sub} · {row.setup}</div>
        <div className="sect">BUY-ONLY PLAN (LEGS)</div>
        {row.legs.map((l, i) => <div className="leg" key={i}><span className={l.side === "YES" ? "y" : "n"}>{l.side}</span><span className="l2">{l.label}</span><span className="white">{l.px}</span><span className="dim">×{l.sz}</span></div>)}
        <div className="kv" style={{ marginTop: 4 }}>
          <span className="l">Cost / unit</span><span className="v">{cv(row.cost)}</span>
          <span className="l">Payout floor</span><span className="v">{cv(row.floor)}</span>
          <span className="l">Worst / best</span><span className="v">{row.worst}¢ / +{row.best}¢</span>
          <span className="l">Break-even</span><span className="v">{row.be}%</span>
          <span className="l">Fillable</span><span className="v">{row.fill}</span>
        </div>
        <div className="sect">EVIDENCEPACK</div>
        <div className="kv"><span className="l">Scan</span><span className="v">scan_8841</span><span className="l">Quote ts</span><span className="v">12s</span><span className="l">Rules</span><span className="v">r3</span></div>
      </div>
      <div className="col">
        <div className="sect">DECOMPOSED CONFIDENCE — 9 DIM</div>
        {Object.entries(row.conf).map(([k, v]) => <div className="cf" key={k}><span className="dim">{k}</span><div className="gz"><i style={{ width: v + "%" }} /></div><span className="r white">{v || "—"}</span></div>)}
        <div className="sect">WHY FLAGGED</div>
        <div className="note">Firm child bid exceeds parent ask — a deeper outcome priced above the broader one that contains it. Gross, top-of-book; fees &amp; full depth not modeled.</div>
      </div>
    </div>
  );
}

function Watch({ onPick }: { onPick: (r: Row) => void }) {
  const W = [["Sinner — Reach Final ⊇ Win", "Tennis · executable", "live", "green"], ["Celtics — SF ≡ Win Conf", "NBA · rule-check", "+1¢", "amber"], ["CS2 Map 1 dutch", "Esports · watching", "+2¢", "cyan"], ["Dodgers — WS ladder", "MLB · needs size", "size 0", "red"]];
  return (<>{W.map((w, i) => <div className="wr" key={i} onClick={() => onPick(stream.rows[i] || stream.rows[0])}><span className={w[3]}>●</span><div className="n3">{w[0]}<div className="sub">{w[1]}</div></div><span className={w[3]}>{w[2]}</span></div>)}</>);
}
function Alerts() {
  const A = [["became executable", "Sinner Reach Final ⊇ Win", "2m · firm both legs", "green"], ["bucket changed", "Celtics → Review", "7m · rule-check", "amber"], ["watched moved", "CS2 Map 1 +3¢", "9m", "cyan"], ["series failed", "KXMOTOGP not fetched", "12m", "red"]];
  return (<>{A.map((a, i) => <div className="ar" key={i}><span className={a[3]} style={{ fontSize: 9 }}>●</span><div><div><b className="white">{a[0]}</b> — {a[1]}</div><div className="m">{a[2]}</div></div></div>)}</>);
}
