import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DataEditor, GridCellKind, type Item, type GridColumn, type GridCell, type DataEditorRef } from "@glideapps/glide-data-grid";
import { createStream } from "@bakeoff/shared/stream";
import { createPerf } from "@bakeoff/shared/perf";
import type { Row } from "@bakeoff/shared/data";

const stream = createStream(200, 30);
const perf = createPerf("React + Glide (canvas)");
const BUCKETS = [["act", "ACTIONABLE", "act"], ["rev", "REVIEW", "rev"], ["blk", "BLOCKED", "blk"], ["res", "RESEARCH", "res"]];
const COLS: GridColumn[] = [
  { id: "chg", title: "", width: 44 }, { id: "sport", title: "SPT", width: 80 },
  { id: "name", title: "Participant / match", width: 300 }, { id: "setup", title: "Setup", width: 150 },
  { id: "edge", title: "Edge¢", width: 80 }, { id: "roi", title: "ROI%", width: 70 }, { id: "units", title: "Units", width: 80 },
  { id: "profit", title: "Profit$", width: 90 }, { id: "tradable", title: "Tradable", width: 120 }, { id: "cav", title: "Caveat", width: 170 },
];
const EDGE_COL = 4;
const chgSym = (c: string) => c === "new" ? "NEW" : c === "up" ? "▲" : c === "down" ? "▼" : c === "ret" ? "↺" : "";
const GLIDE_THEME = {
  accentColor: "#ffb000", accentLight: "rgba(255,176,0,.15)",
  textDark: "#e8c878", textMedium: "#b79a52", textLight: "#7a6a3a", textHeader: "#7a6a3a",
  bgCell: "#0a0a08", bgCellMedium: "#0d0c09", bgHeader: "#0d0c09", bgHeaderHasFocus: "#14120a", bgHeaderHovered: "#14120a",
  borderColor: "#1b1910", horizontalBorderColor: "#1b1910", drilldownBorder: "#2a2616",
  fontFamily: "Consolas, 'SF Mono', monospace", baseFontStyle: "11px", headerFontStyle: "600 9px", editorFontSize: "11px",
  cellHorizontalPadding: 8, textBubble: "#e8c878",
};

export default function App() {
  const ref = useRef<DataEditorRef>(null);
  const visibleRef = useRef<Row[]>([]);
  const idIdx = useRef<Map<string, number>>(new Map());
  const bucketRef = useRef("act");
  const [bucket, setBucket] = useState("act");
  const [rowCount, setRowCount] = useState(0);
  const [sel, setSel] = useState<Row | null>(stream.rows[0]);
  const [basis, setBasis] = useState(1);

  const rebuild = useCallback(() => {
    visibleRef.current = stream.rows.filter(r => r.bucket === bucketRef.current);
    idIdx.current = new Map(visibleRef.current.map((r, i) => [r.id, i]));
    setRowCount(visibleRef.current.length);
  }, []);

  const getCellContent = useCallback(([c, r]: Item): GridCell => {
    const row = visibleRef.current[r];
    const id = COLS[c].id as keyof Row;
    let disp = "", align: "right" | "left" = "left", color: string | undefined;
    if (!row) return { kind: GridCellKind.Text, data: "", displayData: "", allowOverlay: false };
    if (id === "chg") { disp = chgSym(row.chg); color = row.chg === "down" ? "#ff453a" : "#33ff7a"; }
    else if (id === "name") disp = row.name + "  —  " + row.sub;
    else if (id === "edge") { disp = String(row.edge); align = "right"; color = row.chg === "up" ? "#33ff7a" : row.chg === "down" ? "#ff453a" : undefined; }
    else if (id === "roi") { disp = row.roi ? row.roi.toFixed(1) : "—"; align = "right"; }
    else if (id === "units") { disp = row.units ? String(row.units) : "—"; align = "right"; }
    else if (id === "profit") { disp = row.profit ? row.profit.toFixed(2) : "—"; align = "right"; }
    else disp = String((row as any)[id] ?? "");
    return { kind: GridCellKind.Text, data: disp, displayData: disp, allowOverlay: false, contentAlign: align, ...(color ? { themeOverride: { textDark: color } } : {}) };
  }, []);

  useEffect(() => {
    rebuild();
    const unsub = stream.subscribe((batch) => {
      if (batch.reset) { rebuild(); }
      else {
        const cells: { cell: Item }[] = [];
        for (const r of batch.changed) { const i = idIdx.current.get(r.id); if (i !== undefined) cells.push({ cell: [EDGE_COL, i] as Item }); }
        if (cells.length) ref.current?.updateCells(cells);
      }
      perf.recordLatency(performance.now() - batch.t0); perf.recordBatch();
    });
    perf.mount((rows, rate) => stream.setStress(rows, rate), (m) => stream.setMode(m as any));
    stream.start();
    return () => { unsub(); stream.stop(); };
  }, []);

  function onBucket(b: string) { setBucket(b); bucketRef.current = b; rebuild(); }

  return (
    <div className="tp-app">
      <div className="tp-cmd">
        <div className="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div className="ci"><span className="amber">&gt;</span><input placeholder="FUNCTION OR TICKER, THEN <GO>" /><button className="go">&lt;GO&gt;</button></div>
        <div className="badge">KALSHI&lt;WS&gt;</div>
      </div>
      <div className="tp-scanbar" />
      <div className="tp-stat">
        <span className="s"><b className="green">●</b> SCAN IDLE · 12s</span><span className="s">Contracts <b>1,204</b></span><span className="s">Checks <b>747</b></span><span className="s">Req <b>49</b></span>
        <span className="s"><b className="green">●</b> Exchange Open</span><span className="s">Auto-scan <b>on · 30s</b></span><span className="s"><b className="amber">●</b> Failed <b>1</b></span><span className="s">DB <b>42 MB</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>
      <div className="tp-bar2">
        <div className="tab on"><span style={{ color: "var(--green)", fontSize: 8 }}>1)</span>OPP</div><div className="tab"><span style={{ color: "var(--green)", fontSize: 8 }}>2)</span>RES</div><div className="tab"><span style={{ color: "var(--green)", fontSize: 8 }}>3)</span>OPS</div>
        <div className="right"><span className="dim" style={{ fontSize: 9 }}>CANVAS GRID · GLIDE</span></div>
      </div>
      <div className="tp-tiles">
        {[["ACT-NOW", "4", "green", "executable"], ["REVIEW", "2", "amber", "settlement"], ["NEW", "2", "", "this scan"], ["MOVERS", "3", "", "edge moved"], ["STALE", "1", "red", "one-sided"], ["FAILED", "1", "amber", "KXMOTOGP"], ["TOP LENS", "+7¢", "green", "Sinner"]].map((t, i) =>
          <button className="tp-tile" key={i}><div className="k">{t[0]}</div><div className={"v " + t[2]}>{t[1]}</div><div className="s">{t[3]}</div></button>)}
      </div>

      <div className="tp-ws">
        <div className="tp-panel tp-bl">
          <div className="tp-ph"><span className="n">1</span><h3>BLOTTER · CANVAS (GLIDE)</h3><span className="meta">virtualized canvas · updateCells on stream</span></div>
          <div className="tp-bt">{BUCKETS.map(([b, lbl, cls]) => <div key={b} className={"btb " + cls + (bucket === b ? " on" : "")} onClick={() => onBucket(b)}>{lbl}</div>)}</div>
          <div className="tp-pb" style={{ position: "relative" }}>
            <DataEditor ref={ref} columns={COLS} rows={rowCount} getCellContent={getCellContent}
              theme={GLIDE_THEME} rowHeight={24} headerHeight={24} smoothScrollX smoothScrollY
              width="100%" height="100%" rowMarkers="none" getCellsForSelection={true}
              onCellClicked={([, r]) => { const row = visibleRef.current[r]; if (row) setSel({ ...row }); }} />
          </div>
        </div>

        <div className="tp-panel tp-de"><div className="tp-ph"><span className="n">2</span><h3>DES — TRADE CARD</h3></div>
          <div className="tp-pb">{sel ? <Card row={sel} basis={basis} setBasis={setBasis} /> : <div className="empty">Click a row.</div>}</div></div>
        <div className="tp-panel tp-la"><div className="tp-ph"><span className="n">3</span><h3>MD LADDER</h3></div>
          <div className="lw">READ-ONLY DEPTH VIEW — NO ORDERS</div>{sel ? <Ladder row={sel} /> : <div className="empty">—</div>}</div>
        <div className="tp-panel tp-wa"><div className="tp-ph"><span className="n">★</span><h3>WATCH · MOVERS</h3></div><div className="tp-pb"><Watch onPick={setSel} /></div></div>
        <div className="tp-panel tp-al"><div className="tp-ph"><span className="n">!</span><h3>ALERTS</h3></div><div className="tp-pb"><Alerts /></div></div>
      </div>

      <div className="tp-ft"><b>7-REACT + GLIDE (CANVAS)</b><span className="dim">canvas grid — the no-lag ceiling vs DOM AG Grid · stress it in the PERF overlay →</span></div>
    </div>
  );
}

function Ladder({ row }: { row: Row }) {
  if (row.bucket === "res" || !row.touch) return <div className="empty">research — no executable book</div>;
  const base = row.touch, max = (row.fill * 3.2) || 120, rows = [];
  for (let p = base + 5; p >= base - 5; p--) {
    const bid = p <= base ? Math.round(row.fill * (1 + (base - p) * 0.7)) : 0;
    const ask = p >= base ? Math.round(row.fill * (1 + (p - base) * 0.6)) : 0;
    rows.push(<tr key={p}><td className="bc">{bid ? <><span className="f" style={{ width: Math.min(100, bid / max * 100) + "%" }} /><span>{bid}</span></> : null}</td>
      <td className={"px" + (p === base ? " t" : "")}>{p}{p === base + 2 ? <span className="tg">◀ watch</span> : null}</td>
      <td className="ac">{ask ? <><span className="f" style={{ width: Math.min(100, ask / max * 100) + "%" }} /><span>{ask}</span></> : null}</td></tr>);
  }
  return (<><div className="lh"><div className="t">{row.name} <span className="dim">· {row.sport}</span></div><div className="s">{row.legs[0]?.label}</div></div>
    <div className="tp-pb"><table className="lt"><thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead><tbody>{rows}</tbody></table></div>
    <div className="lf"><span>Touch {base}¢ · eff fill@50 ≈ {row.cost + 1}¢</span><span>max fill {row.fill}</span></div></>);
}
function Card({ row, basis, setBasis }: { row: Row; basis: number; setBasis: (n: number) => void }) {
  const cv = (c: number) => basis === 100 ? "$" + c.toFixed(2) : c + "¢";
  return (<div className="des"><div className="col">
    <div className="dt"><span className={"bk bk-" + row.bucket}>{row.bucket.toUpperCase()}</span><span className="t">{row.name}</span>
      <div className="basis"><button className={basis === 1 ? "on" : ""} onClick={() => setBasis(1)}>$1</button><button className={basis === 100 ? "on" : ""} onClick={() => setBasis(100)}>$100</button></div></div>
    <div className="sub" style={{ marginBottom: 3 }}>{row.sub} · {row.setup}</div>
    <div className="sect">BUY-ONLY PLAN (LEGS)</div>
    {row.legs.map((l, i) => <div className="leg" key={i}><span className={l.side === "YES" ? "y" : "n"}>{l.side}</span><span className="l2">{l.label}</span><span className="white">{l.px}</span><span className="dim">×{l.sz}</span></div>)}
    <div className="kv" style={{ marginTop: 4 }}><span className="l">Cost / unit</span><span className="v">{cv(row.cost)}</span><span className="l">Payout floor</span><span className="v">{cv(row.floor)}</span>
      <span className="l">Worst / best</span><span className="v">{row.worst}¢ / +{row.best}¢</span><span className="l">Break-even</span><span className="v">{row.be}%</span><span className="l">Fillable</span><span className="v">{row.fill}</span></div>
    <div className="sect">EVIDENCEPACK</div><div className="kv"><span className="l">Scan</span><span className="v">scan_8841</span><span className="l">Quote ts</span><span className="v">12s</span><span className="l">Rules</span><span className="v">r3</span></div>
  </div><div className="col"><div className="sect">DECOMPOSED CONFIDENCE — 9 DIM</div>
    {Object.entries(row.conf).map(([k, v]) => <div className="cf" key={k}><span className="dim">{k}</span><div className="gz"><i style={{ width: v + "%" }} /></div><span className="r white">{v || "—"}</span></div>)}
    <div className="sect">WHY FLAGGED</div><div className="note">Firm child bid exceeds parent ask — a deeper outcome priced above the broader one that contains it. Gross, top-of-book; fees &amp; full depth not modeled.</div></div></div>);
}
function Watch({ onPick }: { onPick: (r: Row) => void }) {
  const W = [["Sinner — Reach Final ⊇ Win", "Tennis · executable", "live", "green"], ["Celtics — SF ≡ Win Conf", "NBA · rule-check", "+1¢", "amber"], ["CS2 Map 1 dutch", "Esports · watching", "+2¢", "cyan"], ["Dodgers — WS ladder", "MLB · needs size", "size 0", "red"]];
  return <>{W.map((w, i) => <div className="wr" key={i} onClick={() => onPick(stream.rows[i] || stream.rows[0])}><span className={w[3]}>●</span><div className="n3">{w[0]}<div className="sub">{w[1]}</div></div><span className={w[3]}>{w[2]}</span></div>)}</>;
}
function Alerts() {
  const A = [["became executable", "Sinner Reach Final ⊇ Win", "2m · firm both legs", "green"], ["bucket changed", "Celtics → Review", "7m · rule-check", "amber"], ["watched moved", "CS2 Map 1 +3¢", "9m", "cyan"], ["series failed", "KXMOTOGP not fetched", "12m", "red"]];
  return <>{A.map((a, i) => <div className="ar" key={i}><span className={a[3]} style={{ fontSize: 9 }}>●</span><div><div><b className="white">{a[0]}</b> — {a[1]}</div><div className="m">{a[2]}</div></div></div>)}</>;
}
