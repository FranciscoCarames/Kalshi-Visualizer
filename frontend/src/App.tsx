import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { ModuleRegistry, AllCommunityModule, type ColDef } from "ag-grid-community";
import {
  loadFeed, rowsFor, sectionCount, ZONES, SUBTABS, TILES,
  type Feed, type FeedRow,
} from "./feed";

ModuleRegistry.registerModules([AllCommunityModule]);

const POLL_MS = 4000;

function fmtAge(fetchedAt: string | null): string {
  if (!fetchedAt) return "—";
  const t = Date.parse(fetchedAt.replace(" UTC", "Z"));
  if (isNaN(t)) return "—";
  return Math.max(0, Math.round((Date.now() - t) / 1000)) + "s";
}
const cents = (v: unknown) => (typeof v === "number" ? Math.round(v) + "¢" : "—");
const pct = (v: unknown) => (typeof v === "number" ? v.toFixed(1) + "%" : "—");
const money = (v: unknown) => (typeof v === "number" ? "$" + v.toFixed(2) : "—");
const intf = (v: unknown) => (typeof v === "number" ? String(Math.round(v)) : "—");

// Phase A blotter columns — a generic set valid across buckets; the per-bucket catalogs land in Phase B.
// `bucket`/`status`/`tradable` are shown verbatim so the engine's classification is visible (parity).
const COLUMNS: ColDef<FeedRow>[] = [
  { field: "sport", headerName: "SPORT", width: 140 },
  {
    field: "name", headerName: "PARTICIPANT / MATCH", flex: 2, minWidth: 260,
    cellRenderer: (p: { data?: FeedRow }) => (
      <span><span className="nm">{p.data?.name}</span> <span className="sub">{p.data?.sub}</span></span>
    ),
  },
  { field: "bucket", headerName: "BUCKET", width: 130 },
  { field: "status", headerName: "STATUS", width: 180 },
  { field: "edge", headerName: "EDGE¢", width: 92, type: "rightAligned", valueFormatter: (p) => cents(p.value) },
  { field: "roi", headerName: "ROI%", width: 86, type: "rightAligned", valueFormatter: (p) => pct(p.value) },
  { field: "units", headerName: "UNITS", width: 86, type: "rightAligned", valueFormatter: (p) => intf(p.value) },
  { field: "profit", headerName: "MAX $", width: 96, type: "rightAligned", valueFormatter: (p) => money(p.value) },
  {
    field: "tradable", headerName: "TRADABLE", width: 140,
    cellClass: (p) => {
      const t = String(p.value || "").toLowerCase();
      return t.startsWith("yes") ? "tradable-yes" : t.startsWith("no") ? "tradable-no" : "tradable-rule";
    },
  },
  { field: "caveat", headerName: "CAVEAT", flex: 1, minWidth: 150 },
];

export default function App() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zone, setZone] = useState("exec");
  const [section, setSection] = useState("act");
  const [sportSel, setSportSel] = useState("");
  const [part, setPart] = useState("");
  const [, forceTick] = useState(0);
  const gridRef = useRef<AgGridReact<FeedRow>>(null);

  useEffect(() => {
    let alive = true;
    const pull = () => loadFeed().then((f) => alive && (setFeed(f), setErr(null)))
      .catch((e) => alive && setErr(String(e)));
    pull();
    const poll = setInterval(pull, POLL_MS);
    const tick = setInterval(() => forceTick((n) => n + 1), 1000); // keep the age clock live
    return () => { alive = false; clearInterval(poll); clearInterval(tick); };
  }, []);

  const meta = feed?.meta ?? null;
  const opps = feed?.opps ?? [];

  const rows = useMemo(() => {
    let r = rowsFor(opps, zone, section);
    if (sportSel) r = r.filter((o) => (o.sport || "") === sportSel);
    if (part) { const q = part.toLowerCase(); r = r.filter((o) => (o.name || "").toLowerCase().includes(q)); }
    return r;
  }, [opps, zone, section, sportSel, part]);

  const sports = useMemo(() => Object.keys(meta?.sports ?? {}).sort(), [meta]);
  const goSection = (z: string, s: string) => { setZone(z); setSection(s); };

  return (
    <div className="tp-app">
      {/* command line */}
      <div className="tp-cmd">
        <div className="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div className="ci"><span className="amber">&gt;</span>
          <input placeholder="SEARCH — functions · participants · lenses · layouts  (Ctrl-K)" readOnly />
          <button className="go">&lt;GO&gt;</button></div>
        <div className="clock">{fmtAge(meta?.fetched_at ?? null)} · KALSHI</div>
      </div>

      {/* trust strip */}
      <div className="tp-stat">
        <span className="s">
          <b className={err ? "red" : "green"}>●</b> SNAPSHOT #{meta?.snapshot_id ?? "—"} · {fmtAge(meta?.fetched_at ?? null)} ago
        </span>
        <span className="s">Opps <b>{(meta?.n_total ?? 0).toLocaleString()}</b></span>
        <span className="s">Contracts <b>{(meta?.contracts ?? 0).toLocaleString()}</b></span>
        <span className="s">Checks <b>{(meta?.checks ?? 0).toLocaleString()}</b></span>
        <span className="s">Requests <b>{meta?.requests ?? 0}</b></span>
        <span className="s">Sports <b>{sports.length}</b></span>
        <span className="s"><b className={meta?.failed ? "amber" : "green"}>●</b> Failed <b>{meta?.failed ?? 0}</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>

      {/* surface tabs */}
      <div className="tp-bar2">
        <div className="tab on"><span className="c">1)</span>OPP</div>
        <div className="tab"><span className="c">2)</span>RES</div>
        <div className="tab"><span className="c">3)</span>OPS</div>
        <div className="right"><span className="dim" style={{ fontSize: 9 }}>default order = engine rank · lenses in Phase B</span></div>
      </div>

      {/* tiles */}
      <div className="tp-tiles">
        {TILES.map(([label, z, s, accent]) => (
          <button key={label} className={"tp-tile" + (zone === z && section === s ? " on" : "")}
                  onClick={() => goSection(z, s)}>
            <div className="k">{label}</div>
            <div className={"v " + accent}>{sectionCount(meta, z, s).toLocaleString()}</div>
            <div className="s">{({ act: "executable now", rev: "settlement-dep", blk: "not fillable",
              bounded: "can lose money", nearmiss: "watchlist", qual: "WC setups", cheapno: "NO fades",
              diag: "diagnostic" } as Record<string, string>)[s]}</div>
          </button>
        ))}
      </div>

      {/* filter bar */}
      <div className="tp-filt">
        <label>SPORT</label>
        <select value={sportSel} onChange={(e) => setSportSel(e.target.value)}>
          <option value="">All</option>{sports.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label>PARTICIPANT</label>
        <input value={part} placeholder="contains…" onChange={(e) => setPart(e.target.value)} />
        <span className="clr" onClick={() => { setSportSel(""); setPart(""); }}>clear</span>
      </div>

      {/* workspace: the blotter (Phase A). Dockview + inspector/ladder/palette land in Phase B. */}
      <div className="tp-ws">
        <div className="tp-panel">
          <div className="tp-ph"><span className="n">1</span><h3>BLOTTER</h3>
            <span className="meta">read-only VIEW of the engine · bucket/status verbatim</span></div>
          <div className="tp-zones">
            {ZONES.map(([z, label, hint]) => (
              <div key={z} className={"tp-zone" + (zone === z ? " on" : "")} data-z={z}
                   onClick={() => goSection(z, SUBTABS[z][0][0])}>
                {label} <span className="zc">{sectionCount(meta, z, z === "diag" ? "diag" : SUBTABS[z][0][0]).toLocaleString()}</span>{" "}
                <span className="zt">{hint}</span>
              </div>
            ))}
          </div>
          <div className="tp-bt">
            {SUBTABS[zone].map(([s, label]) => (
              <div key={s} className={"btb " + s + (section === s ? " on" : "")} onClick={() => setSection(s)}>
                {label}<span className="ct">{sectionCount(meta, zone, s).toLocaleString()}</span>
              </div>
            ))}
            <span className="showing">
              {err ? <span className="red">feed error: {err}</span>
                   : <>Showing <b className="white">{rows.length.toLocaleString()}</b> · default = engine order</>}
            </span>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <div className="ag-theme-quartz ag-theme-tp" style={{ height: "100%" }}>
              <AgGridReact<FeedRow>
                ref={gridRef}
                theme="legacy"
                rowData={rows}
                columnDefs={COLUMNS}
                defaultColDef={{ sortable: true, resizable: true }}
                getRowId={(p) => p.data.id}
                rowSelection={{ mode: "singleRow", enableClickSelection: true, checkboxes: false }}
                suppressCellFocus
                overlayNoRowsTemplate="No rows in this section for the current filters."
              />
            </div>
          </div>
        </div>
      </div>

      <div className="tp-ft">
        <b>TERMINAL PRO · Phase A</b>
        <span className="dim">read-only view of the live engine feed · parity blotter · Dockview / inspector / ladder / palette / lenses land in Phase B</span>
      </div>
    </div>
  );
}
