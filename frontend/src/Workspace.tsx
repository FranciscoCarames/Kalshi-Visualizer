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
        {t.itab === "detail" ? <Detail row={t.sel} />
          : t.itab === "formula" ? <Formulas row={t.sel} />
          : <Inspector row={t.sel} lens={t.lens} snapshotId={t.meta?.snapshot_id ?? null} showNet={t.showNet} />}
      </div>
    </>
  );
}
function LadderBody() {
  const t = useTerminal();
  return <>
    <div className="ladwarn">READ-ONLY · TOP-OF-BOOK + DERIVED · POLL-REFRESHED · LIVE BOOK = FUTURE</div>
    <Ladder row={t.sel} />
  </>;
}
function WatchBody() { const t = useTerminal(); return <div className="pbody"><Watch opps={t.opps} onPick={t.setSel} /></div>; }
function AlertsBody() { const t = useTerminal(); return <div className="pbody"><Alerts opps={t.opps} meta={t.meta} /></div>; }
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
  { id: "p-ladder", n: "3", title: "DEPTH LADDER", col: "M", hint: "top-of-book + derived", body: <LadderBody /> },
  { id: "p-watch", n: "★", title: "RECENTLY ACTIONABLE", col: "R", body: <WatchBody /> },
  { id: "p-alerts", n: "!", title: "ALERTS", col: "R", body: <AlertsBody /> },
  { id: "p-research", n: "≈", title: "RESEARCH", col: "R", hint: "read-only · P5", body: <ResearchBody /> },
];

const DEFAULT_STATE = (): Record<string, PState> =>
  Object.fromEntries(PANELS.map((p) => [p.id, { collapsed: false, maxed: false, hidden: false }]));

export default function Workspace() {
  const t = useTerminal();
  const [st, setSt] = useState<Record<string, PState>>(DEFAULT_STATE);
  const [colHidden, setColHidden] = useState<{ M: boolean; R: boolean }>({ M: false, R: false });
  const [colW, setColW] = useState<{ M: number; R: number }>({ M: 330, R: 290 });
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const patch = (id: string, p: Partial<PState>) => setSt((s) => ({ ...s, [id]: { ...s[id], ...p } }));

  // presets — mirror the mockup applyPreset()
  const applyPreset = (name: string) => {
    const s = DEFAULT_STATE();
    if (name === "triage") { s["p-des"].collapsed = true; setColHidden({ M: false, R: true }); setColW({ M: 220, R: 290 }); }
    else if (name === "inspect") { s["p-watch"].collapsed = s["p-alerts"].collapsed = s["p-research"].collapsed = true; s["p-des"].basis = 430; setColHidden({ M: false, R: false }); setColW({ M: 470, R: 290 }); }
    else if (name === "research") { s["p-alerts"].collapsed = true; s["p-des"].basis = 200; setColHidden({ M: false, R: false }); setColW({ M: 330, R: 360 }); }
    else if (name === "blotterfull") { s["p-des"].hidden = true; setColHidden({ M: true, R: true }); }
    else { setColHidden({ M: false, R: false }); setColW({ M: 330, R: 290 }); }
    setSt(s);
  };
  useEffect(() => { t.registerLayout(applyPreset); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // pop-out: a window with the panel's current DOM + the page's stylesheets
  const popOut = (id: string, title: string) => {
    const node = refs.current[id]; if (!node) return;
    const w = window.open("", "_blank", "width=560,height=600"); if (!w) return;
    const css = Array.from(document.querySelectorAll('link[rel="stylesheet"],style')).map((n) => n.outerHTML).join("");
    w.document.write(`<!doctype html><html data-theme="${document.documentElement.dataset.theme}"><head><title>${title} — popout</title>${css}</head><body style="height:100vh;margin:0"><div class="panel" style="height:100%">${node.innerHTML}</div></body></html>`);
    w.document.close();
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

  const renderCol = (c: Col) => {
    const list = PANELS.filter((p) => p.col === c && !st[p.id].hidden);
    return list.map((p, idx) => {
      const s = st[p.id];
      const cls = "panel" + (s.collapsed ? " collapsed" : "") + (s.maxed ? " maxed" : "");
      const style: React.CSSProperties = s.basis != null && !s.collapsed && !s.maxed ? { flex: `0 0 ${s.basis}px` } : {};
      const panel = (
        <div className={cls} id={p.id} style={style} ref={(el) => { refs.current[p.id] = el; }}>
          <div className="ph">
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

  return (
    <div className="workspace" id="ws">
      <div className="col" id="colL">{renderCol("L")}</div>
      {!colHidden.M ? <>
        <div className="vsplit" onPointerDown={dragV("M")} />
        <div className="col" id="colM" style={{ flex: `0 0 ${colW.M}px` }}>{renderCol("M")}</div>
      </> : null}
      {!colHidden.R ? <>
        <div className="vsplit" onPointerDown={dragV("R")} />
        <div className="col" id="colR" style={{ flex: `0 0 ${colW.R}px` }}>{renderCol("R")}</div>
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
