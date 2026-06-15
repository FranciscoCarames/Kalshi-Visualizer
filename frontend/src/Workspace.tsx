/* The OPP workspace — a React port of the mockup's own panel/window manager (replaces Dockview), so the
 * chrome (3 columns · drag-resize splitters · per-panel ⧉ pop / ▢ max / ▁ collapse / ✕ close · presets ·
 * ▦ELEMENTS show/hide) is pixel-exact. Layout is imperative by nature; kept isolated here. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTerminal } from "./context";
import Blotter from "./Blotter";
import Inspector, { Detail, Formulas } from "./Inspector";
import Ladder from "./Ladder";
import { Watch, Alerts } from "./SidePanels";

type Col = "L" | "M" | "R";
interface PanelDef { id: string; n: string; title: string; col: Col; hint?: string; body: ReactNode; }
interface PState { collapsed: boolean; maxed: boolean; hidden: boolean; basis?: number; }

function InspectorBody() {
  const t = useTerminal();
  const ITABS: [string, string][] = [["card", "TRADE CARD"], ["detail", "PARTICIPANT DETAIL"], ["formula", "FORMULAS"]];
  return (
    <>
      <div className="itabs">
        {ITABS.map(([k, l]) => (
          <div key={k} className={"itab" + (t.itab === k ? " on" : "")} onClick={() => t.setItab(k as "card" | "detail" | "formula")}>{l}</div>
        ))}
      </div>
      <div className="pbody">
        {t.itab === "detail" ? <Detail row={t.sel} showIds={t.settings.showIds} showRules={t.settings.resolutionCriteria} />
          : t.itab === "formula" ? <Formulas row={t.sel} />
          : <Inspector row={t.sel} lens={t.lens} snapshotId={t.meta?.snapshot_id ?? null} showNet={t.showNet} longShort={t.settings.longShort} />}
      </div>
    </>
  );
}
function LadderBody() {
  const t = useTerminal();
  return <>
    <div className="ladwarn">READ-ONLY · LIVE KALSHI ORDER BOOK · TOP-OF-BOOK · POLL-REFRESHED</div>
    <Ladder row={t.sel} />
  </>;
}
function WatchBody() { const t = useTerminal(); return <div className="pbody"><Watch opps={t.opps} onPick={t.setSel} /></div>; }
function AlertsBody() { return <div className="pbody"><Alerts /></div>; }
function ResearchBody() {
  const t = useTerminal();
  const m = t.meta;
  const max = Math.max(1, ...Object.values(m?.sports ?? { x: 1 }));
  return <div className="respanel">
    <div className="note"><b>Read-only research</b> (P5) — derived data only, never feeds actionability.</div>
    <div className="sect" style={{ marginTop: 12 }}>OPPORTUNITIES BY SPORT</div>
    <div className="resbars">{Object.entries(m?.sports ?? {}).slice(0, 8).map(([s, n]) => (
      <div className="b" key={s} style={{ height: ((n as number) / max * 100) + "%" }}><span>{s.slice(0, 4)}</span></div>
    ))}</div>
    <div className="sect" style={{ color: "var(--violet)", marginTop: 16 }}>BOUNDED-LOSS MIX</div>
    <div className="note">Vertical {m?.resolution_counts?.vertical || 0} · Calendar {m?.resolution_counts?.calendar || 0}.
      Cheap-NO scope — Championship {m?.scope_counts?.championship || 0} · Tournament {m?.scope_counts?.tournament || 0} · Event {m?.scope_counts?.event || 0}.</div>
  </div>;
}

const PANELS: PanelDef[] = [
  { id: "p-blotter", n: "1", title: "BLOTTER", col: "L", hint: "click row · J/K · ENTER · drag splitters · ⚙ columns", body: <Blotter /> },
  { id: "p-des", n: "2", title: "INSPECTOR", col: "L", hint: "read-only · buy-only · gross", body: <InspectorBody /> },
  { id: "p-ladder", n: "3", title: "DEPTH LADDER", col: "M", hint: "live order book · top-of-book", body: <LadderBody /> },
  { id: "p-watch", n: "★", title: "WATCHLIST · TOP ACTIONABLE", col: "R", body: <WatchBody /> },
  { id: "p-alerts", n: "!", title: "ALERTS", col: "R", body: <AlertsBody /> },
  { id: "p-research", n: "≈", title: "RESEARCH", col: "R", hint: "read-only · P5", body: <ResearchBody /> },
];

const DEFAULT_STATE = (): Record<string, PState> =>
  Object.fromEntries(PANELS.map((p) => [p.id, { collapsed: false, maxed: false, hidden: false }]));
const DEFAULT_COLS = (): Record<Col, string[]> => ({
  L: PANELS.filter((p) => p.col === "L").map((p) => p.id),
  M: PANELS.filter((p) => p.col === "M").map((p) => p.id),
  R: PANELS.filter((p) => p.col === "R").map((p) => p.id),
});
const BY_ID: Record<string, PanelDef> = Object.fromEntries(PANELS.map((p) => [p.id, p]));

export default function Workspace() {
  const t = useTerminal();
  const [st, setSt] = useState<Record<string, PState>>(DEFAULT_STATE);
  const [colHidden, setColHidden] = useState<{ M: boolean; R: boolean }>({ M: false, R: false });
  const [colW, setColW] = useState<{ M: number; R: number }>({ M: 330, R: 290 });
  const [cols, setCols] = useState<Record<Col, string[]>>(DEFAULT_COLS);
  const dragId = useRef<string | null>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const patch = (id: string, p: Partial<PState>) => setSt((s) => ({ ...s, [id]: { ...s[id], ...p } }));

  // header drag-to-move a panel between/within columns (mockup wirePanelDrag). dragId set on .ph dragstart.
  const move = (col: Col, idx: number) => {
    const from = dragId.current; if (!from) return;
    setCols((c) => {
      const next: Record<Col, string[]> = { L: [...c.L], M: [...c.M], R: [...c.R] };
      (["L", "M", "R"] as Col[]).forEach((k) => { const i = next[k].indexOf(from); if (i >= 0) next[k].splice(i, 1); });
      next[col].splice(Math.max(0, Math.min(next[col].length, idx)), 0, from);
      return next;
    });
  };

  // presets — mirror the mockup applyPreset()
  const applyPreset = (name: string) => {
    const s = DEFAULT_STATE();
    if (name === "triage") { s["p-des"].collapsed = true; setColHidden({ M: false, R: true }); setColW({ M: 220, R: 290 }); }
    else if (name === "inspect") { s["p-watch"].collapsed = s["p-alerts"].collapsed = s["p-research"].collapsed = true; s["p-des"].basis = 430; setColHidden({ M: false, R: false }); setColW({ M: 470, R: 290 }); }
    else if (name === "research") { s["p-alerts"].collapsed = true; s["p-des"].basis = 200; setColHidden({ M: false, R: false }); setColW({ M: 330, R: 360 }); }
    else if (name === "blotterfull") { s["p-des"].hidden = true; setColHidden({ M: true, R: true }); }
    else { setColHidden({ M: false, R: false }); setColW({ M: 330, R: 290 }); }
    setCols(DEFAULT_COLS());
    setSt(s);
  };
  useEffect(() => { t.registerLayout(applyPreset); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // pop-out: a window with the panel's current DOM + the page's stylesheets. We CLONE nodes (importNode)
  // rather than serializing node.innerHTML into document.write: a string round-trip would re-parse the
  // panel's HTML in a fresh same-origin document, re-interpreting any untrusted feed text (names, labels,
  // URLs) as markup. Cloning preserves React's already-escaped DOM; title/theme are set as text/attribute,
  // never interpolated into an HTML string.
  const popOut = (id: string, title: string) => {
    const node = refs.current[id]; if (!node) return;
    const w = window.open("", "_blank", "width=560,height=600"); if (!w) return;
    const doc = w.document;
    doc.documentElement.setAttribute("data-theme", document.documentElement.dataset.theme ?? "");
    doc.title = `${title} — popout`;
    document.querySelectorAll('link[rel="stylesheet"],style').forEach((n) => doc.head.appendChild(doc.importNode(n, true)));
    doc.body.style.height = "100vh";
    doc.body.style.margin = "0";
    const wrap = doc.createElement("div");
    wrap.className = "panel";
    wrap.style.height = "100%";
    wrap.appendChild(doc.importNode(node, true));
    doc.body.appendChild(wrap);
  };

  const dragV = (which: "M" | "R") => (e: React.PointerEvent) => {
    e.preventDefault(); const sp = e.currentTarget as HTMLElement; sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
    const x0 = e.clientX, w0 = colW[which];
    const mv = (ev: PointerEvent) => setColW((c) => ({ ...c, [which]: Math.max(60, Math.min(1000, w0 - (ev.clientX - x0))) }));
    const up = () => { sp.classList.remove("drag"); document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up); };
    document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up);
  };
  const dragH = (id: string) => (e: React.PointerEvent) => {
    e.preventDefault(); const sp = e.currentTarget as HTMLElement; sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
    const node = refs.current[id]; const y0 = e.clientY, h0 = node ? node.getBoundingClientRect().height : 200;
    const mv = (ev: PointerEvent) => patch(id, { basis: Math.max(24, h0 + (ev.clientY - y0)) });
    const up = () => { sp.classList.remove("drag"); document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up); };
    document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up);
  };

  const clearDragover = () => document.querySelectorAll(".panel.dragover").forEach((n) => n.classList.remove("dragover"));
  const renderCol = (c: Col) => {
    const list = cols[c].map((id) => BY_ID[id]).filter((p) => p && !st[p.id].hidden);
    return list.map((p, idx) => {
      const s = st[p.id];
      const cls = "panel" + (s.collapsed ? " collapsed" : "") + (s.maxed ? " maxed" : "");
      const style: React.CSSProperties = s.basis != null && !s.collapsed && !s.maxed ? { flex: `0 0 ${s.basis}px` } : {};
      const panel = (
        <div className={cls} id={p.id} style={style} ref={(el) => { refs.current[p.id] = el; }}
             onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("dragover"); }}
             onDragLeave={(e) => e.currentTarget.classList.remove("dragover")}
             onDrop={(e) => { e.preventDefault(); e.stopPropagation(); clearDragover(); move(c, cols[c].indexOf(p.id)); }}>
          <div className="ph" draggable
               onDragStart={(e) => { if ((e.target as HTMLElement).closest(".dock")) { e.preventDefault(); return; } dragId.current = p.id; e.dataTransfer.effectAllowed = "move"; }}
               onDragEnd={() => { dragId.current = null; clearDragover(); }}>
            <span className="n">{p.n}</span><h3>{p.title}</h3>
            <span className="hint">{p.hint || ""}</span>
            <span className="dock">
              <span title="Pop out" onClick={() => popOut(p.id, p.title)}>⧉</span>
              <span title="Maximize" onClick={() => patch(p.id, { maxed: !s.maxed })}>▢</span>
              <span title="Collapse" onClick={() => patch(p.id, { collapsed: !s.collapsed })}>▁</span>
              <span title="Remove from this view" onClick={() => patch(p.id, { hidden: true })}>✕</span>
            </span>
          </div>
          {p.body}
        </div>
      );
      return <div key={p.id} style={{ display: "contents" }}>{panel}{idx < list.length - 1 ? <div className="hsplit" onPointerDown={dragH(p.id)} /> : null}</div>;
    });
  };
  const colDrop = (c: Col) => ({
    onDragOver: (e: React.DragEvent) => e.preventDefault(),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); clearDragover(); move(c, cols[c].length); },
  });

  return (
    <div className="workspace" id="ws">
      <div className="col" id="colL" {...colDrop("L")}>{renderCol("L")}</div>
      {!colHidden.M ? <>
        <div className="vsplit" onPointerDown={dragV("M")} />
        <div className="col" id="colM" style={{ flex: `0 0 ${colW.M}px` }} {...colDrop("M")}>{renderCol("M")}</div>
      </> : null}
      {!colHidden.R ? <>
        <div className="vsplit" onPointerDown={dragV("R")} />
        <div className="col" id="colR" style={{ flex: `0 0 ${colW.R}px` }} {...colDrop("R")}>{renderCol("R")}</div>
      </> : null}

      {t.extra ? (
        <div className="panel maxed">
          <div className="ph"><span className="n">▣</span><h3>{t.extra.title}</h3><span className="hint" />
            <span className="dock"><span title="Close" onClick={() => t.setExtra(null)}>✕</span></span></div>
          <div className="pbody">{t.extra.body}</div>
        </div>
      ) : null}

      {t.panelsMenuOpen ? (
        <div className="menu on" style={{ top: 0, left: 8 }} onMouseLeave={() => t.setPanelsMenuOpen(false)}>
          <div className="mh">SHOW / HIDE PANELS</div>
          {PANELS.map((p) => (
            <label key={p.id}><input type="checkbox" checked={!st[p.id].hidden} onChange={() => patch(p.id, { hidden: !st[p.id].hidden })} />{p.title}</label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
