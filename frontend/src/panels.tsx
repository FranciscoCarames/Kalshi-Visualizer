/* The Dockview-hosted panels. Each is a thin body that reads the shared terminal context — Dockview
 * provides the draggable/resizable/pop-out frame + tab; these render only the content. */
import { useRef, useState, type ReactNode } from "react";
import { AgGridReact } from "ag-grid-react";
import { type GridApi } from "ag-grid-community";
import { type IDockviewPanelProps } from "dockview";
import { useTerminal } from "./context";
import { COLS } from "./columns";
import { ZONES, SUBTABS, sectionCount, type FeedRow } from "./feed";
import Inspector from "./Inspector";
import Ladder from "./Ladder";
import { Watch, Alerts } from "./SidePanels";

export function BlotterPanel() {
  const t = useTerminal();
  const [chooser, setChooser] = useState(false);
  const apiRef = useRef<GridApi<FeedRow> | null>(null);
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="tp-zones">
        {ZONES.map(([z, label, hint]) => (
          <div key={z} className={"tp-zone" + (t.zone === z ? " on" : "")} data-z={z}
               onClick={() => t.goSection(z, SUBTABS[z][0][0])}>
            {label} <span className="zc">{sectionCount(t.meta, z, z === "diag" ? "diag" : SUBTABS[z][0][0]).toLocaleString()}</span> <span className="zt">{hint}</span>
          </div>
        ))}
      </div>
      <div className="tp-bt" style={{ position: "relative" }}>
        {SUBTABS[t.zone].map(([s, label]) => (
          <div key={s} className={"btb " + s + (t.section === s ? " on" : "")} onClick={() => t.setSection(s)}>
            {label}<span className="ct">{sectionCount(t.meta, t.zone, s).toLocaleString()}</span>
          </div>
        ))}
        <span className="showing">
          {t.err ? <span className="red">feed error: {t.err}</span>
                 : <>Showing <b className="white">{t.rows.length.toLocaleString()}</b> · {t.visible.length} cols · </>}
          <span className="tp-tb" style={{ marginLeft: 6 }} onClick={() => setChooser((v) => !v)}>⚙ columns ▾</span>
        </span>
        {chooser ? (
          <div className="menu" onMouseLeave={() => setChooser(false)}>
            <div className="mh">COLUMNS · {t.section.toUpperCase()} ({COLS[t.colKey].length})</div>
            {COLS[t.colKey].map((c) => (
              <label key={c.f}><input type="checkbox" checked={t.visible.includes(c.f)} onChange={() => t.toggleCol(c.f)} />{c.l}</label>
            ))}
            <div className="reset" onClick={t.resetCols}>↺ reset to defaults</div>
          </div>
        ) : null}
      </div>
      {t.multi.length > 1 ? (
        <div className="selbar">▣ <b className="white">{t.multi.length}</b> selected ·
          <button className="tp-tb" onClick={t.openCompare}>Compare</button>
          <button className="tp-tb" onClick={t.openOverlap}>⚠ Don't-take-both</button>
          <button className="tp-tb" onClick={t.exportSelected}>⬇ Export</button>
          <button className="tp-tb" onClick={() => apiRef.current?.deselectAll()}>Clear</button>
        </div>
      ) : null}
      <div style={{ flex: 1, minHeight: 0 }}>
        <div className="ag-theme-quartz ag-theme-tp" style={{ height: "100%" }}>
          <AgGridReact<FeedRow>
            theme="legacy"
            rowData={t.rows}
            columnDefs={t.columnDefs}
            defaultColDef={{ sortable: true, resizable: true }}
            getRowId={(p) => p.data.id}
            rowSelection={{ mode: "multiRow", enableClickSelection: true, checkboxes: false, headerCheckbox: false }}
            suppressCellFocus
            overlayNoRowsTemplate="No rows in this section for the current filters."
            onGridReady={(e) => { apiRef.current = e.api; }}
            onColumnMoved={() => {
              const api = apiRef.current; if (!api) return;
              t.setColOrder(api.getColumnState().map((s) => s.colId).filter((f) => t.visible.includes(f)));
            }}
            onSelectionChanged={(e) => t.setMulti(e.api.getSelectedRows())}
            onRowClicked={(e) => t.setSel(e.data ? { ...e.data } : null)}
          />
        </div>
      </div>
    </div>
  );
}

export function InspectorPanel() {
  const t = useTerminal();
  return <div style={{ height: "100%", overflow: "auto" }}>
    <Inspector row={t.sel} lens={t.lens} snapshotId={t.meta?.snapshot_id ?? null} />
  </div>;
}

export function LadderPanel() {
  const t = useTerminal();
  return <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
    <div className="lw">READ-ONLY DEPTH VIEW — NO ORDERS · TOP-OF-BOOK + DERIVED</div>
    <Ladder row={t.sel} />
  </div>;
}

export function WatchPanel() {
  const t = useTerminal();
  return <div style={{ height: "100%", overflow: "auto" }}><Watch opps={t.opps} onPick={t.setSel} /></div>;
}

export function AlertsPanel() {
  const t = useTerminal();
  return <div style={{ height: "100%", overflow: "auto" }}><Alerts opps={t.opps} meta={t.meta} /></div>;
}

// --- dynamic panels added from a multi-selection (Ctrl/Shift-click → selbar) -------------------------
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
  ["sport", "Sport"], ["section", "Zone"], ["sub", "Tournament"], ["cost", "Cost ¢"], ["max_loss", "Max loss ¢"],
  ["max_profit", "Max profit ¢"], ["roi", "ROI %"], ["edge", "Edge ¢"], ["cond_child", "Deeper|reached %"],
  ["parent_over_maxloss", "Ripeness"], ["quote_health", "Quote"], ["tradable", "Tradable"],
];

export function ComparePanel(props: IDockviewPanelProps<{ opps: FeedRow[] }>) {
  const opps = props.params.opps ?? [];
  return (
    <div style={{ height: "100%", overflow: "auto", padding: 4 }}>
      <table className="tp-tbl">
        <thead><tr><th>Metric</th>{opps.map((o) => <th key={o.id} className="r">{String(o.name || "").slice(0, 18)}</th>)}</tr></thead>
        <tbody>{COMPARE_FIELDS.map(([f, l]) => (
          <tr key={f}><td className="dim">{l}</td>{opps.map((o) => <td key={o.id} className="r">{fmtField(o, f)}</td>)}</tr>
        ))}</tbody>
      </table>
      <div className="note" style={{ padding: 4 }}>Read-only comparison · gross top-of-book · selecting rows never implies multiple orders.</div>
    </div>
  );
}

export function OverlapPanel(props: IDockviewPanelProps<{ opps: FeedRow[] }>) {
  const opps = props.params.opps ?? [];
  const warns: ReactNode[] = [];
  for (let i = 0; i < opps.length; i++) {
    for (let j = i + 1; j < opps.length; j++) {
      const A = opps[i], B = opps[j], why: string[] = [];
      if (A.name && A.name === B.name && A.sport === B.sport) why.push(`same participant ${A.name}`);
      const ta = new Set((A.legs || []).map((l) => l.tk).filter(Boolean));
      const shared = (B.legs || []).map((l) => l.tk).filter((tk) => tk && ta.has(tk));
      if (shared.length) why.push(`${shared.length} shared market${shared.length > 1 ? "s" : ""}`);
      if (why.length) warns.push(
        <div className="ar" key={`${i}-${j}`}><span className="red" style={{ fontSize: 9 }}>●</span>
          <div><b className="white">{String(A.name).slice(0, 18)}</b> &amp; <b className="white">{String(B.name).slice(0, 18)}</b> — {why.join(", ")} → doubling exposure</div>
        </div>);
    }
  }
  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <div className="note" style={{ padding: "4px 6px" }}>Flags selected opportunities that share a participant or market — you'd be <b>doubling exposure</b>, not diversifying. Read-only heuristic, not a correlation model; never changes ranking.</div>
      {warns.length ? warns : <div className="note" style={{ padding: 6 }}><span className="green">No shared participant or market</span> among the {opps.length} selected — they look independent.</div>}
    </div>
  );
}

export const PANELS = {
  blotter: BlotterPanel, inspector: InspectorPanel, ladder: LadderPanel, watch: WatchPanel, alerts: AlertsPanel,
  compare: ComparePanel, overlap: OverlapPanel,
};
