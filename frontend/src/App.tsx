import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { ModuleRegistry, AllCommunityModule, type GridApi } from "ag-grid-community";
import {
  loadFeed, rowsFor, sectionCount, ZONES, SUBTABS, TILES,
  type Feed, type FeedRow,
} from "./feed";
import { COLS, colKeyOf, buildColDefs } from "./columns";
import { LENSES, applyLens } from "./lens";
import Inspector from "./Inspector";
import Ladder from "./Ladder";
import { Watch, Alerts } from "./SidePanels";

ModuleRegistry.registerModules([AllCommunityModule]);

const POLL_MS = 4000;
const TILE_SUB: Record<string, string> = {
  act: "executable now", rev: "settlement-dep", blk: "not fillable", bounded: "can lose money",
  nearmiss: "watchlist", qual: "WC setups", cheapno: "NO fades", diag: "diagnostic",
};

function fmtAge(fetchedAt: string | null): string {
  if (!fetchedAt) return "—";
  const t = Date.parse(fetchedAt.replace(" UTC", "Z"));
  return isNaN(t) ? "—" : Math.max(0, Math.round((Date.now() - t) / 1000)) + "s";
}

export default function App() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zone, setZone] = useState("exec");
  const [section, setSection] = useState("act");
  const [lens, setLens] = useState("");                  // "" = engine order (default); a lens re-sorts only
  const [sportSel, setSportSel] = useState("");
  const [part, setPart] = useState("");
  const [sel, setSel] = useState<FeedRow | null>(null);
  const [colsByKey, setColsByKey] = useState<Record<string, string[]>>({});
  const [chooser, setChooser] = useState(false);
  const [, tick] = useState(0);
  const apiRef = useRef<GridApi<FeedRow> | null>(null);

  useEffect(() => {
    let alive = true;
    const pull = () => loadFeed().then((f) => alive && (setFeed(f), setErr(null))).catch((e) => alive && setErr(String(e)));
    pull();
    const poll = setInterval(pull, POLL_MS);
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => { alive = false; clearInterval(poll); clearInterval(clock); };
  }, []);

  const meta = feed?.meta ?? null;
  const opps = feed?.opps ?? [];
  const colKey = colKeyOf(zone, section);
  const defVis = useMemo(() => COLS[colKey].filter((c) => !c.hide).map((c) => c.f), [colKey]);
  const visible = colsByKey[colKey] ?? defVis;
  const columnDefs = useMemo(() => buildColDefs(COLS[colKey], visible), [colKey, visible]);

  const rows = useMemo(() => {
    let r = rowsFor(opps, zone, section);
    if (sportSel) r = r.filter((o) => (o.sport || "") === sportSel);
    if (part) { const q = part.toLowerCase(); r = r.filter((o) => (o.name || "").toLowerCase().includes(q)); }
    return applyLens(r, lens);                            // client SORT only; never re-buckets
  }, [opps, zone, section, sportSel, part, lens]);

  const sports = useMemo(() => Object.keys(meta?.sports ?? {}).sort(), [meta]);
  const goSection = (z: string, s: string) => { setZone(z); setSection(s); setChooser(false); };
  const toggleLens = (l: string) => setLens((cur) => (cur === l ? "" : l));
  const toggleCol = (f: string) => {
    const cur = colsByKey[colKey] ?? defVis;
    setColsByKey({ ...colsByKey, [colKey]: cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f] });
  };
  const onColumnMoved = () => {
    const api = apiRef.current; if (!api) return;
    const order = api.getColumnState().map((s) => s.colId).filter((f) => visible.includes(f));
    setColsByKey((m) => ({ ...m, [colKey]: order }));     // persist drag-reorder
  };

  return (
    <div className="tp-app">
      <div className="tp-cmd">
        <div className="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div className="ci"><span className="amber">&gt;</span>
          <input placeholder="SEARCH — functions · participants · lenses · layouts  (Ctrl-K · Phase B3)" readOnly />
          <button className="go">&lt;GO&gt;</button></div>
        <div className="clock">{fmtAge(meta?.fetched_at ?? null)} · KALSHI</div>
      </div>

      <div className="tp-stat">
        <span className="s"><b className={err ? "red" : "green"}>●</b> SNAPSHOT #{meta?.snapshot_id ?? "—"} · {fmtAge(meta?.fetched_at ?? null)} ago</span>
        <span className="s">Opps <b>{(meta?.n_total ?? 0).toLocaleString()}</b></span>
        <span className="s">Contracts <b>{(meta?.contracts ?? 0).toLocaleString()}</b></span>
        <span className="s">Checks <b>{(meta?.checks ?? 0).toLocaleString()}</b></span>
        <span className="s">Requests <b>{meta?.requests ?? 0}</b></span>
        <span className="s">Sports <b>{sports.length}</b></span>
        <span className="s"><b className={meta?.failed ? "amber" : "green"}>●</b> Failed <b>{meta?.failed ?? 0}</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>

      <div className="tp-bar2">
        <div className="tab on"><span className="c">1)</span>OPP</div>
        <div className="tab"><span className="c">2)</span>RES</div>
        <div className="tab"><span className="c">3)</span>OPS</div>
        <div className="right">
          <span className="dim" style={{ fontSize: 9 }}>LENS</span>
          <div className="tp-lens">
            {LENSES.map(([l, lbl, tip]) => (
              <button key={l} className={lens === l ? "on" : ""} title={tip} onClick={() => toggleLens(l)}>{lbl}</button>
            ))}
          </div>
          <span className="dim" style={{ fontSize: 9 }}>{lens ? "sort lens" : "engine order"}</span>
        </div>
      </div>

      <div className="tp-tiles">
        {TILES.map(([label, z, s, accent]) => (
          <button key={label} className={"tp-tile" + (zone === z && section === s ? " on" : "")} onClick={() => goSection(z, s)}>
            <div className="k">{label}</div>
            <div className={"v " + accent}>{sectionCount(meta, z, s).toLocaleString()}</div>
            <div className="s">{TILE_SUB[s]}</div>
          </button>
        ))}
      </div>

      <div className="tp-filt">
        <label>SPORT</label>
        <select value={sportSel} onChange={(e) => setSportSel(e.target.value)}>
          <option value="">All</option>{sports.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label>PARTICIPANT</label>
        <input value={part} placeholder="contains…" onChange={(e) => setPart(e.target.value)} />
        <span className="clr" onClick={() => { setSportSel(""); setPart(""); }}>clear</span>
      </div>

      <div className="tp-ws">
        {/* BLOTTER */}
        <div className="tp-panel p-bl">
          <div className="tp-ph"><span className="n">1</span><h3>BLOTTER</h3>
            <span className="meta">read-only VIEW of the engine · bucket/status verbatim · drag headers to reorder</span></div>
          <div className="tp-zones">
            {ZONES.map(([z, label, hint]) => (
              <div key={z} className={"tp-zone" + (zone === z ? " on" : "")} data-z={z} onClick={() => goSection(z, SUBTABS[z][0][0])}>
                {label} <span className="zc">{sectionCount(meta, z, z === "diag" ? "diag" : SUBTABS[z][0][0]).toLocaleString()}</span> <span className="zt">{hint}</span>
              </div>
            ))}
          </div>
          <div className="tp-bt" style={{ position: "relative" }}>
            {SUBTABS[zone].map(([s, label]) => (
              <div key={s} className={"btb " + s + (section === s ? " on" : "")} onClick={() => setSection(s)}>
                {label}<span className="ct">{sectionCount(meta, zone, s).toLocaleString()}</span>
              </div>
            ))}
            <span className="showing">
              {err ? <span className="red">feed error: {err}</span>
                   : <>Showing <b className="white">{rows.length.toLocaleString()}</b> · {visible.length} cols · </>}
              <span className="tp-tb" style={{ marginLeft: 6 }} onClick={() => setChooser((v) => !v)}>⚙ columns ▾</span>
            </span>
            {chooser ? (
              <div className="menu" onMouseLeave={() => setChooser(false)}>
                <div className="mh">COLUMNS · {section.toUpperCase()} ({COLS[colKey].length})</div>
                {COLS[colKey].map((c) => (
                  <label key={c.f}>
                    <input type="checkbox" checked={visible.includes(c.f)} onChange={() => toggleCol(c.f)} />{c.l}
                  </label>
                ))}
                <div className="reset" onClick={() => setColsByKey((m) => { const n = { ...m }; delete n[colKey]; return n; })}>↺ reset to defaults</div>
              </div>
            ) : null}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <div className="ag-theme-quartz ag-theme-tp" style={{ height: "100%" }}>
              <AgGridReact<FeedRow>
                theme="legacy"
                rowData={rows}
                columnDefs={columnDefs}
                defaultColDef={{ sortable: true, resizable: true }}
                getRowId={(p) => p.data.id}
                rowSelection={{ mode: "singleRow", enableClickSelection: true, checkboxes: false }}
                suppressCellFocus
                overlayNoRowsTemplate="No rows in this section for the current filters."
                onGridReady={(e) => { apiRef.current = e.api; }}
                onColumnMoved={onColumnMoved}
                onRowClicked={(e) => setSel(e.data ? { ...e.data } : null)}
              />
            </div>
          </div>
        </div>

        {/* INSPECTOR */}
        <div className="tp-panel p-de">
          <div className="tp-ph"><span className="n">2</span><h3>INSPECTOR — TRADE CARD</h3>
            <span className="meta">{sel?.zone === "spec" ? "CAN LOSE MONEY · bounded-loss" : "read-only · buy-only · gross"}</span></div>
          <div className="tp-pb"><Inspector row={sel} lens={lens} snapshotId={meta?.snapshot_id ?? null} /></div>
        </div>

        {/* MD LADDER */}
        <div className="tp-panel p-la">
          <div className="tp-ph"><span className="n">3</span><h3>MD LADDER</h3><span className="meta">top-of-book + derived</span></div>
          <div className="lw">READ-ONLY DEPTH VIEW — NO ORDERS · TOP-OF-BOOK + DERIVED</div>
          <Ladder row={sel} />
        </div>

        {/* WATCH / ALERTS */}
        <div className="tp-panel p-wa"><div className="tp-ph"><span className="n">★</span><h3>RECENTLY ACTIONABLE</h3></div>
          <div className="tp-pb"><Watch opps={opps} onPick={setSel} /></div></div>
        <div className="tp-panel p-al"><div className="tp-ph"><span className="n">!</span><h3>ALERTS</h3></div>
          <div className="tp-pb"><Alerts opps={opps} meta={meta} /></div></div>
      </div>

      <div className="tp-ft">
        <b>TERMINAL PRO · Phase B1</b>
        <span className="dim">multi-panel workspace · 6 lenses (sort-only) · per-bucket columns + chooser · inspector + ladder · Dockview / palette / multi-select land in B2–B4</span>
      </div>
    </div>
  );
}
