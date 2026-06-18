/* The blotter — a plain HTML <table>, ported from ui-mockup-final-spa.html blotter() (replaces AG-Grid so
 * the look is pixel-exact). Zones + bucket tabs + split + name cell + selection bar + column chooser, all
 * on the mockup's classes. Rows arrive engine-ranked + lens-sorted; a click on a header applies a display-
 * only sort override (reset when the section/catalog changes). AG-Grid's virtualization is not reproduced. */
import { memo, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTerminal } from "./context";
import { ZONES, SUBTABS, type FeedRow } from "./feed";
import { COLS, fmtVal, qhClass, signalLabel, qualityOf, type Col } from "./columns";
import { sortRows, nextSort, type SortState } from "./sort";

function severityOf(o: FeedRow): { cls: string; txt: string } | null {
  if (o.blk) return { cls: "sev-blk", txt: "Blocker" };
  if (o.rule) return { cls: "sev-rev", txt: "Review" };
  if (o.settlement_caveat || o.caveat) return { cls: "sev-adv", txt: "Advisory" };
  // Display-only fee note: immediate-fill (taker) fees meet/exceed the gross edge. The "Fee:" prefix keeps
  // it from reading like a bucket/rank/instruction — it never hides, demotes, or re-ranks the row.
  if (o.net_negative) return { cls: "sev-adv", txt: "Fee: taker net-neg (est.)" };
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
  // Human-readable bounded-loss signal class (display-only; raw value still drives ranking narrative).
  if (col.f === "signal") return <td>{signalLabel(v)}</td>;
  // Single uncalibrated setup-quality diagnostic (ripeness × conditional). "Insufficient data" ≠ "Low".
  if (col.f === "quality") {
    const q = qualityOf(row);
    if (q.tier === "n/a") return <td className="dim" title="ripeness or conditional chance missing — not scored (missing ≠ low)">Insufficient data</td>;
    const cls = q.tier === "High" ? "green" : q.tier === "Med" ? "amber" : "dim";
    return <td><span className={cls} title={`uncalibrated: ripeness × P(deeper│reached); score ${q.score!.toFixed(2)}`}>{q.label}</span></td>;
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
  // Fixed-position anchor for the column menu (viewport coords of the ⚙ button). The menu is PORTALED to the
  // document body with position:fixed so the scanner panel's `overflow:hidden` can't clip it — that was
  // hiding the lower half of the (30+ row) bounded-loss catalog. Captured on open.
  const [menuPos, setMenuPos] = useState<{ top: number; right: number; maxH: number } | null>(null);
  const [sort, setSort] = useState<SortState | null>(null);
  // Per-section dismissal of the section-note banner (persisted in localStorage so it stays hidden across
  // reloads). Dismissing qualifier's banner doesn't touch near-miss's.
  const NOTE_KEY = "kss_dismissed_secnotes";
  const [dismissedNotes, setDismissedNotes] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem(NOTE_KEY) || "[]")); } catch { return new Set(); }
  });
  const setNoteDismissed = (section: string, hide: boolean) => setDismissedNotes((d) => {
    const n = new Set(d); if (hide) n.add(section); else n.delete(section);
    try { localStorage.setItem(NOTE_KEY, JSON.stringify([...n])); } catch { /* storage unavailable — keep in-memory */ }
    return n;
  });
  const dragF = useRef<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const colsBtnRef = useRef<HTMLSpanElement | null>(null);
  const openChooser = () => {
    if (chooser) { setChooser(false); return; }
    const btn = colsBtnRef.current;
    if (btn) {
      const r = btn.getBoundingClientRect();
      const win = btn.ownerDocument.defaultView ?? window;   // the menu's own window (handles pop-outs)
      setMenuPos({ top: r.bottom + 2, right: win.innerWidth - r.right, maxH: win.innerHeight - r.bottom - 12 });
    }
    setChooser(true);
  };
  // Close the column chooser on an OUTSIDE click — never on mouse-leave. Mouse-leave made a long catalog
  // (bounded-loss has 30+ columns) impossible to use: the menu vanished the instant the cursor left it to
  // reach the scrollbar, so the bottom options were unreachable.
  useEffect(() => {
    if (!chooser) return;
    // Scope the listener to the MENU's OWN document, not the module-global `document`. In a pop-out window
    // the menu lives in that window's document, so listening on the main `document` would never see the
    // pop-out's clicks (and vice-versa) — each window's chooser must close on ITS own outside clicks.
    const doc = menuRef.current?.ownerDocument ?? document;
    const onDown = (e: MouseEvent) => {
      const tgt = e.target as Node;
      if (menuRef.current?.contains(tgt) || colsBtnRef.current?.contains(tgt)) return;
      setChooser(false);
    };
    doc.addEventListener("mousedown", onDown);
    return () => doc.removeEventListener("mousedown", onDown);
  }, [chooser]);
  const cols: Col[] = t.visible.map((f) => COLS[t.colKey].find((c) => c.f === f)).filter((c): c is Col => !!c);
  // Click-sort is a display override; reset to engine/lens order when the section/catalog changes.
  useEffect(() => { setSort(null); }, [t.colKey]);
  const fmtOf = (f: string) => COLS[t.colKey].find((c) => c.f === f)?.fmt ?? "num";
  const rows = sortRows(t.rows, sort, fmtOf);
  const shown = rows.length > ROW_CAP ? rows.slice(0, ROW_CAP) : rows;

  // Section-note banner: collapse a boilerplate field to ONE banner line only when its value is identical
  // across EVERY visible row (and non-empty). A field that varies stays a per-row column — so a row-specific
  // caveat (or differing note) is never hidden. Near-miss collapses its shared "note"; qualifier collapses
  // its shared setup / legs / review-status / caveat.
  const BANNER_FIELDS: Record<string, string[]> = {
    nearmiss: ["note"],
    qual: ["setup", "legs", "review_status", "caveat"],
  };
  // Compare + display the FORMATTED value (via the column's formatter), not the raw field — so a field whose
  // value is an object/array (e.g. `legs` holds the leg array, a "num" column that renders "—") is skipped
  // rather than stringified to "[object Object]".
  const bannerVal = (f: string): string | null => {
    if (!rows.length) return null;
    const fmt = fmtOf(f);
    const s0 = fmtVal(rows[0][f], fmt);
    if (!s0 || s0 === "—") return null;
    for (const r of rows) { if (fmtVal(r[f], fmt) !== s0) return null; }
    return s0;
  };
  const banners = (BANNER_FIELDS[t.section] ?? [])
    .map((f) => { const v = bannerVal(f); return v == null ? null : { f, l: COLS[t.colKey].find((c) => c.f === f)?.l ?? f, v }; })
    .filter((x): x is { f: string; l: string; v: string } => !!x);
  const bannerSet = new Set(banners.map((b) => b.f));
  const tableCols = cols.filter((c) => !bannerSet.has(c.f));

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
        <span className="cols" ref={colsBtnRef} onClick={openChooser}>⚙ columns ▾</span>
        {chooser && menuPos ? createPortal(
          <div className="menu on" ref={menuRef}
               style={{ position: "fixed", top: menuPos.top, right: menuPos.right, maxHeight: menuPos.maxH }}>
            <div className="mh">COLUMNS · {t.section.toUpperCase()}
              <span className="mclose" title="close" onClick={() => setChooser(false)}>✕</span></div>
            {COLS[t.colKey].map((c) => (
              <label key={c.f}><input type="checkbox" checked={t.visible.includes(c.f)} onChange={() => t.toggleCol(c.f)} />{c.l}</label>
            ))}
            <div className="mi" onClick={t.resetCols}>↺ reset to defaults</div>
          </div>,
          (colsBtnRef.current?.ownerDocument ?? document).body,
        ) : null}
      </div>
      {t.section === "bounded" ? (
        <div className="subtabs">
          {[["all", "All"], ["vertical", "Vertical"], ["calendar", "Calendar"]].map(([s, label]) => (
            <div key={s} className={"subtab" + (t.split === s ? " on" : "")} onClick={() => t.setSplit(s)}>{label}</div>
          ))}
        </div>
      ) : null}
      {t.section === "cheapno" ? (
        // Settlement-scope subsection tabs (parallel to bounded's split) — wired to the existing cheapScope
        // band filter (filters.applyBand), so this is purely a prominent UI for a filter that already exists.
        <div className="subtabs">
          {[["all", "All"], ["event", "Event"], ["tournament", "Tournament"], ["championship", "Championship"]].map(([s, label]) => (
            <div key={s} className={"subtab" + (t.band.cheapScope === s ? " on" : "")} onClick={() => t.setBand({ cheapScope: s })}>{label}</div>
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
      {banners.length ? (
        dismissedNotes.has(t.section) ? (
          <div className="secnote secnote-collapsed" title="show section notes" onClick={() => setNoteDismissed(t.section, false)}>
            ▸ section notes
          </div>
        ) : (
          <div className="secnote">
            {banners.map((b) => (
              <span key={b.f} className="secnote-item"><b>{b.l}:</b> {b.v}</span>
            ))}
            <span className="secnote-x" title="hide these notes" onClick={() => setNoteDismissed(t.section, true)}>✕</span>
          </div>
        )
      ) : null}
      <div className="pbody">
        {t.err ? <div className="empty red">feed error: {t.err}</div>
          : !rows.length ? <div className="empty">{emptyMsg()}</div>
          : (
          <table>
            <thead><tr>{tableCols.map((c) => (
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
                {tableCols.map((c) => <Cell key={c.f} row={o} col={c} chg={c.fmt === "name" ? chg : undefined} />)}
              </tr>;
            })}
            {rows.length > ROW_CAP ? (
              <tr className="zdiag"><td className="dim" colSpan={tableCols.length}>
                +{(rows.length - ROW_CAP).toLocaleString()} more rows hidden — refine filters or sort to narrow the view.
              </td></tr>
            ) : null}</tbody>
          </table>
        )}
      </div>
      <div className="showing">
        Showing <b className="white">{shown.length.toLocaleString()}</b> of {t.inScope(t.zone, t.section).toLocaleString()} in scope
        {(() => {
          // Distinguish rows hidden by the SUB-TAB (bounded Vertical/Calendar split) from rows removed by the
          // band/size/tradable FILTERS, instead of lumping both into a vague "hidden by settings". `count`
          // applies membership+threshold+band across all splits; `rows` is after the split → the difference is
          // the tab. Clamped so a transient async mismatch can't print a negative.
          const inScope = t.inScope(t.zone, t.section), cnt = t.count(t.zone, t.section);
          const byTab = Math.max(0, cnt - rows.length);          // the Vertical/Calendar tab you're not on
          const byFilters = Math.max(0, inScope - cnt);          // band / min-size / tradable-only
          return <>
            {byTab > 0 ? <> · <b className="amber">{byTab.toLocaleString()}</b> on other tabs</> : null}
            {byFilters > 0 ? <> · <b className="amber">{byFilters.toLocaleString()}</b> by filters</> : null}
          </>;
        })()}
        · {tableCols.length} cols
        {sort ? <> · sort <b className="amber">{sort.field} {sort.dir === "asc" ? "▲" : "▼"}</b></>
              : t.lens ? <> · lens <b className="amber">{t.lens}</b></> : <> · engine order</>}
      </div>
    </div>
  );
}
