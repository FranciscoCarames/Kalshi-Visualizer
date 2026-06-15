/* The blotter — a plain HTML <table>, ported from ui-mockup-final-spa.html blotter() (replaces AG-Grid so
 * the look is pixel-exact). Zones + bucket tabs + split + name cell + selection bar + column chooser, all
 * on the mockup's classes. Rows arrive engine-ranked + lens-sorted; a click on a header applies a display-
 * only sort override (reset when the section/catalog changes). AG-Grid's virtualization is not reproduced. */
import { memo, useEffect, useRef, useState } from "react";
import { useTerminal } from "./context";
import { ZONES, SUBTABS, type FeedRow } from "./feed";
import { COLS, fmtVal, qhClass, type Col } from "./columns";
import { sortRows, nextSort, type SortState } from "./sort";

function severityOf(o: FeedRow): { cls: string; txt: string } | null {
  if (o.blk) return { cls: "sev-blk", txt: "Blocker" };
  if (o.rule) return { cls: "sev-rev", txt: "Review" };
  if (o.settlement_caveat || o.caveat) return { cls: "sev-adv", txt: "Advisory" };
  return null;
}

// memo'd: with stable row/col references (feed rows are memoized upstream), a Cell only re-renders when its
// own props change — so selection/sort/theme changes no longer re-render every cell of every row.
const Cell = memo(function Cell({ row, col, chg }: { row: FeedRow; col: Col; chg?: "new" | "up" | "down" | "returned" | null }) {
  const v = row[col.f];
  if (col.fmt === "name") {
    return <td>
      {chg === "new" ? <span className="nw">NEW</span> : chg === "returned" ? <span className="amber" title="returned to this set">↶ </span> : null}
      {chg === "up" ? <span className="green" title="edge up since last scan">▲ </span>
        : chg === "down" ? <span className="red" title="edge down since last scan">▼ </span> : null}
      <span className="nm">{String(row.name ?? "")}</span> <span className="sub">{String(row.sub ?? row.detail ?? "")}</span>
    </td>;
  }
  if (col.f === "basis_flags") {
    const mid = !!row.midpoint_only, wide = !!row.wide_basis;
    if (!mid && !wide) return <td className="dim">—</td>;
    return <td>
      {mid ? <span className="sev sev-rev" title="positive only on the display (midpoint) basis; firm bid/ask does not confirm">MID-ONLY</span> : null}
      {mid && wide ? " " : null}
      {wide ? <span className="sev sev-adv" title="rests on a wide quote — low confidence">WIDE</span> : null}
    </td>;
  }
  if (col.f === "caveat") {
    const sev = severityOf(row);
    const txt = fmtVal(v, "text");
    return <td>{sev ? <span className={"sev " + sev.cls} title={txt === "—" ? sev.txt : txt}>{sev.txt}</span> : null} {txt === "—" ? "" : txt}</td>;
  }
  if (col.fmt === "qh") return <td className={qhClass(v)}>{fmtVal(v, col.fmt)}</td>;
  if (col.fmt === "trad") {
    const t = String(v || "").toLowerCase();
    const cl = t.startsWith("yes") ? "ty" : t.startsWith("no") ? "tn" : "tr2";
    const dot = t.startsWith("yes") ? "● " : t.startsWith("no") ? "○ " : "◐ ";
    return <td className={cl}>{v ? dot + String(v) : "—"}</td>;
  }
  const right = col.fmt !== "text";
  const cls = col.f === "edge" && typeof v === "number" && v ? "green" : col.f === "max_loss" ? "red"
    : col.f === "max_profit" || col.f === "bonus_profit" ? "green" : "";
  return <td className={(right ? "r " : "") + cls}>{fmtVal(v, col.fmt)}</td>;
});

// Cap rendered rows (no AG-Grid virtualization here): a huge section won't mount thousands of <tr>s on
// every feed poll. The full filtered count is still shown in the footer + a "+N more" hint.
const ROW_CAP = 500;

export default function Blotter() {
  const t = useTerminal();
  const [chooser, setChooser] = useState(false);
  const [sort, setSort] = useState<SortState | null>(null);
  const dragF = useRef<string | null>(null);
  const cols: Col[] = t.visible.map((f) => COLS[t.colKey].find((c) => c.f === f)).filter((c): c is Col => !!c);
  // Click-sort is a display override; reset to engine/lens order when the section/catalog changes.
  useEffect(() => { setSort(null); }, [t.colKey]);
  const fmtOf = (f: string) => COLS[t.colKey].find((c) => c.f === f)?.fmt ?? "num";
  const rows = sortRows(t.rows, sort, fmtOf);
  const shown = rows.length > ROW_CAP ? rows.slice(0, ROW_CAP) : rows;

  const onRowClick = (e: React.MouseEvent, o: FeedRow) => {
    if (e.ctrlKey || e.metaKey || e.shiftKey) {
      const has = t.multi.some((m) => m.id === o.id);
      t.setMulti(has ? t.multi.filter((m) => m.id !== o.id) : [...t.multi, o]);
    } else { t.setSel({ ...o }); t.setMulti([]); }
  };
  const onDrop = (over: string) => {
    const from = dragF.current; dragF.current = null;
    if (!from || from === over) return;
    const order = cols.map((c) => c.f);
    const fi = order.indexOf(from), ti = order.indexOf(over);
    if (fi < 0 || ti < 0) return;
    order.splice(ti, 0, ...order.splice(fi, 1));
    t.setColOrder(order);
  };
  const mids = new Set(t.multi.map((m) => m.id));
  // Truthful empty-state message (mirrors the old dashboard's distinct states).
  const emptyMsg = (): string => {
    if (t.scanText) return "Scanning — new data shortly…";
    if (!t.meta || t.meta.snapshot_id == null) return "No scan yet — hit ▷ SCAN (or open the dashboard).";
    if ((t.meta.n_total ?? 0) === 0) return "No opportunities in the latest snapshot.";
    if (t.inScope(t.zone, t.section) === 0) return "No opportunities in this section for the current filters.";
    return "All rows hidden by the section / band filters — relax them to see in-scope rows.";
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div className="zones">
        {ZONES.map(([z, label, hint]) => (
          <div key={z} className={"zone" + (t.zone === z ? " on" : "")} data-z={z}
               onClick={() => t.goSection(z, SUBTABS[z][0][0])}>
            {label} <span className="zc">{t.zoneCount(z).toLocaleString()}</span> <span className="zt">{hint}</span>
          </div>
        ))}
      </div>
      <div className="btabs" style={{ position: "relative" }}>
        {SUBTABS[t.zone].map(([s, label]) => (
          <div key={s} className={"btab" + (t.section === s ? " on" : "")} data-tab={s} onClick={() => t.setSection(s)}>
            {label}<span className="ct">{t.count(t.zone, s).toLocaleString()}</span>
          </div>
        ))}
        <span className="cols" onClick={() => setChooser((v) => !v)}>⚙ columns ▾</span>
        {chooser ? (
          <div className="menu on" style={{ right: 0, top: 20 }} onMouseLeave={() => setChooser(false)}>
            <div className="mh">COLUMNS · {t.section.toUpperCase()}</div>
            {COLS[t.colKey].map((c) => (
              <label key={c.f}><input type="checkbox" checked={t.visible.includes(c.f)} onChange={() => t.toggleCol(c.f)} />{c.l}</label>
            ))}
            <div className="mi" onClick={t.resetCols}>↺ reset to defaults</div>
          </div>
        ) : null}
      </div>
      {t.section === "bounded" ? (
        <div className="subtabs">
          {[["all", "All"], ["vertical", "Vertical"], ["calendar", "Calendar"]].map(([s, label]) => (
            <div key={s} className={"subtab" + (t.split === s ? " on" : "")} onClick={() => t.setSplit(s)}>{label}</div>
          ))}
        </div>
      ) : null}
      {t.multi.length > 1 ? (
        <div className="selbar">▣ <b className="white">{t.multi.length}</b> selected ·
          <button className="tbtn" onClick={t.openLadders}>Open ladders</button>
          <button className="tbtn" onClick={t.openCompare}>Compare</button>
          <button className="tbtn" onClick={t.exportSelected}>Export selected</button>
          <button className="tbtn" onClick={t.openOverlap}>⚠ Don't-take-both</button>
          <button className="tbtn" onClick={() => t.setMulti([])}>Clear</button>
        </div>
      ) : null}
      <div className="pbody">
        {t.err ? <div className="empty red">feed error: {t.err}</div>
          : !rows.length ? <div className="empty">{emptyMsg()}</div>
          : (
          <table>
            <thead><tr>{cols.map((c) => (
              <th key={c.f} className={c.fmt !== "text" && c.fmt !== "name" ? "r" : ""} draggable
                  aria-sort={sort?.field === c.f ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                  title={(c.tip ? c.tip + " — " : "") + "click to sort · drag to reorder"}
                  onClick={() => setSort((s) => nextSort(s, c.f))}
                  onDragStart={() => { dragF.current = c.f; }} onDragOver={(e) => e.preventDefault()} onDrop={() => onDrop(c.f)}>
                {c.l}{sort?.field === c.f ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}</th>
            ))}</tr></thead>
            <tbody>{shown.map((o) => {
              const zc = o.zone === "spec" ? " zspec" : o.zone === "diag" ? " zdiag" : "";
              const sc = t.sel?.id === o.id ? " sel" : "";
              const mc = mids.has(o.id) ? " msel" : "";
              const fc = t.flashIds.has(o.id) ? " fl" : "";
              const chg = t.changeOf(o.id);
              return <tr key={o.id} className={(zc + sc + mc + fc).trim()} onClick={(e) => onRowClick(e, o)}>
                {cols.map((c) => <Cell key={c.f} row={o} col={c} chg={c.fmt === "name" ? chg : undefined} />)}
              </tr>;
            })}
            {rows.length > ROW_CAP ? (
              <tr className="zdiag"><td className="dim" colSpan={cols.length}>
                +{(rows.length - ROW_CAP).toLocaleString()} more rows hidden — refine filters or sort to narrow the view.
              </td></tr>
            ) : null}</tbody>
          </table>
        )}
      </div>
      <div className="showing">
        Showing <b className="white">{shown.length.toLocaleString()}</b> of {t.inScope(t.zone, t.section).toLocaleString()} in scope
        {(() => { const hid = t.inScope(t.zone, t.section) - rows.length; return hid > 0 ? <> ({hid.toLocaleString()} hidden by settings)</> : null; })()}
        · {t.visible.length} cols
        {sort ? <> · sort <b className="amber">{sort.field} {sort.dir === "asc" ? "▲" : "▼"}</b></>
              : t.lens ? <> · lens <b className="amber">{t.lens}</b></> : <> · engine order</>}
      </div>
    </div>
  );
}
