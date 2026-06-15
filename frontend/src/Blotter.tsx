/* The blotter — a plain HTML <table>, ported from ui-mockup-final-spa.html blotter() (replaces AG-Grid so
 * the look is pixel-exact). Zones + bucket tabs + split + sparkline name cell + selection bar + column
 * chooser, all on the mockup's classes. Rows are engine-ranked + lens-sorted (no click-sort — matches the
 * mockup; AG-Grid's sort/virtualization are intentionally not reproduced at this gate). */
import { useEffect, useRef, useState } from "react";
import { useTerminal } from "./context";
import { ZONES, SUBTABS, type FeedRow } from "./feed";
import { COLS, fmtVal, qhClass, type Col } from "./columns";
import { sortRows, nextSort, type SortState } from "./sort";

const cssv = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#ffb000";

function Spark({ pts }: { pts?: number[] }) {
  if (!pts || pts.length < 2) return null;
  const w = 44, h = 12, mn = Math.min(...pts), rg = Math.max(1, Math.max(...pts) - mn), st = w / (pts.length - 1);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${(i * st).toFixed(1)},${(h - 2 - ((p - mn) / rg) * (h - 4)).toFixed(1)}`).join(" ");
  return <svg width={w} height={h} style={{ verticalAlign: "middle", marginLeft: 5 }}>
    <path d={d} fill="none" stroke={cssv("--amber")} strokeWidth={1.2} opacity={0.65} /></svg>;
}

function Cell({ row, col, chg }: { row: FeedRow; col: Col; chg?: "new" | "up" | "down" | null }) {
  const v = row[col.f];
  if (col.fmt === "name") {
    return <td>
      {chg === "new" ? <span className="nw">NEW</span> : null}
      {chg === "up" ? <span className="green" title="edge up since last scan">▲ </span>
        : chg === "down" ? <span className="red" title="edge down since last scan">▼ </span> : null}
      <span className="nm">{String(row.name ?? "")}</span> <span className="sub">{String(row.sub ?? row.detail ?? "")}</span><Spark pts={row.spark} />
    </td>;
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
}

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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div className="zones">
        {ZONES.map(([z, label, hint]) => (
          <div key={z} className={"zone" + (t.zone === z ? " on" : "")} data-z={z}
               onClick={() => t.goSection(z, SUBTABS[z][0][0])}>
            {label} <span className="zc">{t.count(z, z === "diag" ? "diag" : SUBTABS[z][0][0]).toLocaleString()}</span> <span className="zt">{hint}</span>
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
          : !t.rows.length ? <div className="empty">No rows in this section for the current filters.</div>
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
            <tbody>{rows.map((o) => {
              const zc = o.zone === "spec" ? " zspec" : o.zone === "diag" ? " zdiag" : "";
              const sc = t.sel?.id === o.id ? " sel" : "";
              const mc = mids.has(o.id) ? " msel" : "";
              const fc = t.flashIds.has(o.id) ? " fl" : "";
              const chg = t.changeOf(o.id);
              return <tr key={o.id} className={(zc + sc + mc + fc).trim()} onClick={(e) => onRowClick(e, o)}>
                {cols.map((c) => <Cell key={c.f} row={o} col={c} chg={c.fmt === "name" ? chg : undefined} />)}
              </tr>;
            })}</tbody>
          </table>
        )}
      </div>
      <div className="showing">
        Showing <b className="white">{rows.length.toLocaleString()}</b> · {t.visible.length} cols
        {sort ? <> · sort <b className="amber">{sort.field} {sort.dir === "asc" ? "▲" : "▼"}</b></>
              : t.lens ? <> · lens <b className="amber">{t.lens}</b></> : <> · engine order</>}
      </div>
    </div>
  );
}
