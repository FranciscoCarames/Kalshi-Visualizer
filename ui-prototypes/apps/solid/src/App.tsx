import { createSignal, onMount, onCleanup, For, Show } from "solid-js";
import { createGrid, ModuleRegistry, AllCommunityModule, type GridApi, type ColDef } from "ag-grid-community";
import { createStream } from "@bakeoff/shared/stream";
import { createPerf } from "@bakeoff/shared/perf";
import type { Row } from "@bakeoff/shared/data";

ModuleRegistry.registerModules([AllCommunityModule]);
const stream = createStream(200, 30);
const perf = createPerf("Solid + AG Grid");

const BUCKETS = [["act", "ACTIONABLE", "act"], ["rev", "REVIEW", "rev"], ["blk", "BLOCKED", "blk"], ["res", "RESEARCH", "res"]];
const LENSES = [["blended", "BLENDED", "edge"], ["edge", "EDGE", "edge"], ["roi", "ROI", "roi"], ["ev", "IMPLIED EV", "roi"]];
const chgSym = (c: string) => c === "new" ? "NEW" : c === "up" ? "▲" : c === "down" ? "▼" : c === "ret" ? "↺" : "";

export default function App() {
  const [sel, setSel] = createSignal<Row | null>(stream.rows[0]);
  const [lens, setLens] = createSignal("blended");
  const [bucket, setBucket] = createSignal("act");
  const [basis, setBasis] = createSignal(1);
  let gridDiv!: HTMLDivElement;
  let api: GridApi;
  let bucketVal = "act";
  let unsub: (() => void) | undefined;

  const columnDefs: ColDef[] = [
    { headerName: "", field: "chg", width: 40, valueFormatter: p => chgSym(p.value), cellClass: p => p.data.chg === "up" ? "green" : p.data.chg === "down" ? "red" : p.data.chg === "new" ? "green" : "amber" },
    { field: "sport", width: 84, headerName: "SPT" },
    { field: "name", headerName: "Participant / match", flex: 2, minWidth: 220, cellRenderer: (p: any) => `<span class="nm">${p.data.name}</span> <span class="sub">${p.data.sub}</span>` },
    { field: "setup", flex: 1, minWidth: 120 },
    { field: "edge", headerName: "Edge¢", width: 84, type: "rightAligned" },
    { field: "roi", headerName: "ROI%", width: 76, type: "rightAligned", valueFormatter: p => p.value ? (+p.value).toFixed(1) : "—" },
    { field: "units", headerName: "Units", width: 80, type: "rightAligned", valueFormatter: p => p.value || "—" },
    { field: "profit", headerName: "Profit$", width: 84, type: "rightAligned", valueFormatter: p => p.value ? (+p.value).toFixed(2) : "—" },
    { field: "tradable", width: 120, cellClass: p => p.value === "Yes" ? "tradable-yes" : p.value === "No" ? "tradable-no" : "tradable-rule" },
    { field: "cav", headerName: "Caveat", flex: 1, minWidth: 130, cellClass: p => p.data.sev === "blk" ? "red" : p.data.sev === "rev" ? "amber" : "dim" },
  ];

  onMount(() => { setTimeout(() => {
    api = createGrid(gridDiv, {
      theme: "legacy", rowData: stream.rows, columnDefs,
      defaultColDef: { sortable: true, resizable: true },
      getRowId: (p) => p.data.id,
      rowSelection: { mode: "singleRow", enableClickSelection: true, checkboxes: false },
      suppressCellFocus: true,
      isExternalFilterPresent: () => true,
      doesExternalFilterPass: (n: any) => n.data.bucket === bucketVal,
      onRowClicked: (e: any) => setSel({ ...e.data }),
    });
    api.applyColumnState({ state: [{ colId: "edge", sort: "desc" }] });

    unsub = stream.subscribe((batch) => {
      if (batch.reset) api.setGridOption("rowData", stream.rows);
      else {
        api.applyTransaction({ update: batch.changed });
        const nodes = batch.changed.map(r => api.getRowNode(r.id)).filter(Boolean) as any[];
        if (nodes.length) api.flashCells({ rowNodes: nodes, columns: ["edge"], flashDuration: 500 });
      }
      perf.recordLatency(performance.now() - batch.t0);
      perf.recordBatch();
    });
    perf.mount((rows, rate) => stream.setStress(rows, rate), (m) => stream.setMode(m as any));
    stream.start();
  }, 0); });
  onCleanup(() => { unsub?.(); stream.stop(); });

  const onLens = (l: string, col: string) => { setLens(l); api.applyColumnState({ state: [{ colId: col, sort: "desc" }], defaultState: { sort: null } }); };
  const onBucket = (b: string) => { setBucket(b); bucketVal = b; api.onFilterChanged(); };

  return (
    <div class="tp-app">
      <div class="tp-cmd">
        <div class="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div class="ci"><span class="amber">&gt;</span><input placeholder="FUNCTION OR TICKER, THEN <GO>" /><button class="go">&lt;GO&gt;</button></div>
        <div class="badge">KALSHI&lt;WS&gt;</div>
      </div>
      <div class="tp-scanbar" />
      <div class="tp-stat">
        <span class="s"><b class="green">●</b> SCAN IDLE · 12s</span><span class="s">Contracts <b>1,204</b></span><span class="s">Checks <b>747</b></span><span class="s">Req <b>49</b></span>
        <span class="s"><b class="green">●</b> Exchange Open</span><span class="s">Auto-scan <b>on · 30s</b></span><span class="s"><b class="amber">●</b> Failed <b>1</b></span><span class="s">DB <b>42 MB</b></span>
        <span class="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>
      <div class="tp-bar2">
        <div class="tab on"><span style="color:var(--green);font-size:8px">1)</span>OPP</div><div class="tab"><span style="color:var(--green);font-size:8px">2)</span>RES</div><div class="tab"><span style="color:var(--green);font-size:8px">3)</span>OPS</div>
        <div class="right"><span class="dim" style="font-size:9px">LENS</span>
          <div class="tp-lens"><For each={LENSES}>{(l) => <button class={lens() === l[0] ? "on" : ""} onClick={() => onLens(l[0], l[2])}>{l[1]}</button>}</For></div>
        </div>
      </div>
      <div class="tp-tiles">
        <For each={[["ACT-NOW", "4", "green", "executable"], ["REVIEW", "2", "amber", "settlement"], ["NEW", "2", "", "this scan"], ["MOVERS", "3", "", "edge moved"], ["STALE", "1", "red", "one-sided"], ["FAILED", "1", "amber", "KXMOTOGP"], ["TOP LENS", "+7¢", "green", "Sinner"]]}>
          {(t) => <button class="tp-tile"><div class="k">{t[0]}</div><div class={"v " + t[2]}>{t[1]}</div><div class="s">{t[3]}</div></button>}</For>
      </div>

      <div class="tp-ws">
        <div class="tp-panel tp-bl">
          <div class="tp-ph"><span class="n">1</span><h3>BLOTTER</h3><span class="meta">streaming · click row → DES + ladder</span></div>
          <div class="tp-bt"><For each={BUCKETS}>{(b) => <div class={"btb " + b[2] + (bucket() === b[0] ? " on" : "")} onClick={() => onBucket(b[0])}>{b[1]}</div>}</For></div>
          <div class="tp-pb"><div ref={gridDiv} class="ag-theme-quartz ag-theme-bakeoff" style="height:100%;width:100%" /></div>
        </div>

        <div class="tp-panel tp-de">
          <div class="tp-ph"><span class="n">2</span><h3>DES — TRADE CARD</h3></div>
          <div class="tp-pb"><Show when={sel()} fallback={<div class="empty">Click a row.</div>}>{(row) => <Card row={row()} basis={basis()} setBasis={setBasis} />}</Show></div>
        </div>

        <div class="tp-panel tp-la">
          <div class="tp-ph"><span class="n">3</span><h3>MD LADDER</h3></div>
          <div class="lw">READ-ONLY DEPTH VIEW — NO ORDERS</div>
          <Show when={sel()} fallback={<div class="empty">—</div>}>{(row) => <Ladder row={row()} />}</Show>
        </div>

        <div class="tp-panel tp-wa"><div class="tp-ph"><span class="n">★</span><h3>WATCH · MOVERS</h3></div><div class="tp-pb"><Watch onPick={setSel} /></div></div>
        <div class="tp-panel tp-al"><div class="tp-ph"><span class="n">!</span><h3>ALERTS</h3></div><div class="tp-pb"><Alerts /></div></div>
      </div>

      <div class="tp-ft"><b>7-SOLID + AG GRID</b><span class="dim">fine-grained signals (no VDOM) · same AG Grid engine · stress it in the PERF overlay →</span></div>
    </div>
  );
}

function Ladder(props: { row: Row }) {
  const r = props.row;
  if (r.bucket === "res" || !r.touch) return <div class="empty">research — no executable book</div>;
  const base = r.touch, max = (r.fill * 3.2) || 120;
  const rows: any[] = [];
  for (let p = base + 5; p >= base - 5; p--) {
    const bid = p <= base ? Math.round(r.fill * (1 + (base - p) * 0.7)) : 0;
    const ask = p >= base ? Math.round(r.fill * (1 + (p - base) * 0.6)) : 0;
    rows.push({ p, bid, ask });
  }
  return (<>
    <div class="lh"><div class="t">{r.name} <span class="dim">· {r.sport}</span></div><div class="s">{r.legs[0]?.label}</div></div>
    <div class="tp-pb"><table class="lt"><thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead><tbody>
      <For each={rows}>{(x) => <tr>
        <td class="bc"><Show when={x.bid}><span class="f" style={{ width: Math.min(100, x.bid / max * 100) + "%" }} /><span>{x.bid}</span></Show></td>
        <td class={"px" + (x.p === base ? " t" : "")}>{x.p}<Show when={x.p === base + 2}><span class="tg">◀ watch</span></Show></td>
        <td class="ac"><Show when={x.ask}><span class="f" style={{ width: Math.min(100, x.ask / max * 100) + "%" }} /><span>{x.ask}</span></Show></td>
      </tr>}</For>
    </tbody></table></div>
    <div class="lf"><span>Touch {base}¢ · eff fill@50 ≈ {r.cost + 1}¢</span><span>max fill {r.fill}</span></div>
  </>);
}

function Card(props: { row: Row; basis: number; setBasis: (n: number) => void }) {
  const r = props.row;
  const cv = (c: number) => props.basis === 100 ? "$" + c.toFixed(2) : c + "¢";
  return (
    <div class="des">
      <div class="col">
        <div class="dt"><span class={"bk bk-" + r.bucket}>{r.bucket.toUpperCase()}</span><span class="t">{r.name}</span>
          <div class="basis"><button class={props.basis === 1 ? "on" : ""} onClick={() => props.setBasis(1)}>$1</button><button class={props.basis === 100 ? "on" : ""} onClick={() => props.setBasis(100)}>$100</button></div></div>
        <div class="sub" style="margin-bottom:3px">{r.sub} · {r.setup}</div>
        <div class="sect">BUY-ONLY PLAN (LEGS)</div>
        <For each={r.legs}>{(l) => <div class="leg"><span class={l.side === "YES" ? "y" : "n"}>{l.side}</span><span class="l2">{l.label}</span><span class="white">{l.px}</span><span class="dim">×{l.sz}</span></div>}</For>
        <div class="kv" style="margin-top:4px">
          <span class="l">Cost / unit</span><span class="v">{cv(r.cost)}</span><span class="l">Payout floor</span><span class="v">{cv(r.floor)}</span>
          <span class="l">Worst / best</span><span class="v">{r.worst}¢ / +{r.best}¢</span><span class="l">Break-even</span><span class="v">{r.be}%</span><span class="l">Fillable</span><span class="v">{r.fill}</span>
        </div>
        <div class="sect">EVIDENCEPACK</div>
        <div class="kv"><span class="l">Scan</span><span class="v">scan_8841</span><span class="l">Quote ts</span><span class="v">12s</span><span class="l">Rules</span><span class="v">r3</span></div>
      </div>
      <div class="col">
        <div class="sect">DECOMPOSED CONFIDENCE — 9 DIM</div>
        <For each={Object.entries(r.conf)}>{([k, v]) => <div class="cf"><span class="dim">{k}</span><div class="gz"><i style={{ width: v + "%" }} /></div><span class="r white">{v || "—"}</span></div>}</For>
        <div class="sect">WHY FLAGGED</div>
        <div class="note">Firm child bid exceeds parent ask — a deeper outcome priced above the broader one that contains it. Gross, top-of-book; fees &amp; full depth not modeled.</div>
      </div>
    </div>
  );
}

function Watch(props: { onPick: (r: Row) => void }) {
  const W = [["Sinner — Reach Final ⊇ Win", "Tennis · executable", "live", "green"], ["Celtics — SF ≡ Win Conf", "NBA · rule-check", "+1¢", "amber"], ["CS2 Map 1 dutch", "Esports · watching", "+2¢", "cyan"], ["Dodgers — WS ladder", "MLB · needs size", "size 0", "red"]];
  return <For each={W}>{(w, i) => <div class="wr" onClick={() => props.onPick(stream.rows[i()] || stream.rows[0])}><span class={w[3]}>●</span><div class="n3">{w[0]}<div class="sub">{w[1]}</div></div><span class={w[3]}>{w[2]}</span></div>}</For>;
}
function Alerts() {
  const A = [["became executable", "Sinner Reach Final ⊇ Win", "2m · firm both legs", "green"], ["bucket changed", "Celtics → Review", "7m · rule-check", "amber"], ["watched moved", "CS2 Map 1 +3¢", "9m", "cyan"], ["series failed", "KXMOTOGP not fetched", "12m", "red"]];
  return <For each={A}>{(a) => <div class="ar"><span class={a[3]} style="font-size:9px">●</span><div><div><b class="white">{a[0]}</b> — {a[1]}</div><div class="m">{a[2]}</div></div></div>}</For>;
}
