/* The Dockview-hosted panels. Each is a thin body that reads the shared terminal context — Dockview
 * provides the draggable/resizable/pop-out frame + tab; these render only the content. */
import { useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { type GridApi } from "ag-grid-community";
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
      <div style={{ flex: 1, minHeight: 0 }}>
        <div className="ag-theme-quartz ag-theme-tp" style={{ height: "100%" }}>
          <AgGridReact<FeedRow>
            theme="legacy"
            rowData={t.rows}
            columnDefs={t.columnDefs}
            defaultColDef={{ sortable: true, resizable: true }}
            getRowId={(p) => p.data.id}
            rowSelection={{ mode: "singleRow", enableClickSelection: true, checkboxes: false }}
            suppressCellFocus
            overlayNoRowsTemplate="No rows in this section for the current filters."
            onGridReady={(e) => { apiRef.current = e.api; }}
            onColumnMoved={() => {
              const api = apiRef.current; if (!api) return;
              t.setColOrder(api.getColumnState().map((s) => s.colId).filter((f) => t.visible.includes(f)));
            }}
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

export const PANELS = {
  blotter: BlotterPanel, inspector: InspectorPanel, ladder: LadderPanel, watch: WatchPanel, alerts: AlertsPanel,
};
