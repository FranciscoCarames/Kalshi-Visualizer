/* The OPP workspace — a React port of the mockup's own panel/window manager (replaces Dockview), so the
 * chrome (3 columns · drag-resize splitters · per-panel ⧉ pop / ▢ max / ▁ collapse / ✕ close · presets ·
 * ▦ELEMENTS show/hide · ＋ADD palette) is pixel-exact. Layout is imperative by nature; kept isolated here.
 * The full layout (column widths, per-panel height/collapse/hide, panel order) is a serializable snapshot
 * owned by context (persisted per user); this component edits a LOCAL DRAFT for smooth live drag and commits
 * back on discrete actions / pointer-up. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { TerminalProvider, useTerminal } from "./context";
import type { Feed } from "./feed";
import Blotter from "./Blotter";
import Inspector, { Detail, Formulas } from "./Inspector";
import Ladder from "./Ladder";
import { Watch, Alerts } from "./SidePanels";
import { type Col, type LayoutSnapshot, type PanelState, type TextSize } from "./layout";

interface PanelDef { id: string; n: string; title: string; hint?: string; body: ReactNode; }

// Per-panel text-size cycle: inherit (page default) → compact → normal → large → xlarge → inherit. A panel's
// `data-textsize` scopes --fs to its own subtree (tokens.css), independent of the global page size.
const SIZE_CYCLE: (TextSize | undefined)[] = [undefined, "compact", "normal", "large", "xlarge"];
const nextSize = (cur?: TextSize): TextSize | undefined =>
  SIZE_CYCLE[(SIZE_CYCLE.indexOf(cur) + 1) % SIZE_CYCLE.length];

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
  { id: "p-blotter", n: "1", title: "SCANNER", hint: "click row · J/K · drag splitters · ⚙ columns", body: <Blotter /> },
  { id: "p-des", n: "2", title: "INSPECTOR", hint: "read-only · buy-only · gross", body: <InspectorBody /> },
  { id: "p-ladder", n: "3", title: "DEPTH LADDER", hint: "live order book · top-of-book", body: <LadderBody /> },
  { id: "p-watch", n: "★", title: "WATCHLIST · TOP ACTIONABLE", body: <WatchBody /> },
  { id: "p-alerts", n: "!", title: "ALERTS", body: <AlertsBody /> },
  { id: "p-research", n: "≈", title: "RESEARCH", hint: "read-only · P5", body: <ResearchBody /> },
];
const BY_ID: Record<string, PanelDef> = Object.fromEntries(PANELS.map((p) => [p.id, p]));

// Panels shown in an independent pop-out workspace: Scanner + Inspector + Ladder — the linked trading trio.
const POPOUT_PANELS = ["p-blotter", "p-des", "p-ladder"];

/* An INDEPENDENT pop-out mini-workspace in its own OS window. We open the window, copy the page's
 * stylesheets, then `createPortal` a NESTED <TerminalProvider embedded={feed}> into it. The nested provider
 * shares the parent's feed DATA (passed as `feed`, kept live as the parent re-renders) but owns its OWN view
 * state — selection, Inspector tab, lens, filters — so its toggles DON'T leak to the main window, and its
 * Scanner row clicks drive its OWN Inspector (linked within this window). Multiple pop-outs are each
 * independent. Cleans up on manual close (polls win.closed), on unload, and on unmount. React-rendered (never
 * innerHTML), preserving the no-reparse-untrusted-markup rule. */
function PopoutPortal({ feed, onClose }: { feed: Feed | null; onClose: () => void }) {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const w = window.open("", "_blank", "width=900,height=840");
    if (!w) { alert("Popup blocked — allow popups for this site to pop out a workspace."); onClose(); return; }
    const doc = w.document;
    doc.title = "Scanner workspace — popout";
    doc.documentElement.setAttribute("data-theme", document.documentElement.dataset.theme ?? "");
    doc.documentElement.setAttribute("data-textsize", document.documentElement.dataset.textsize ?? "");
    document.querySelectorAll('link[rel="stylesheet"],style').forEach((n) => doc.head.appendChild(doc.importNode(n, true)));
    doc.body.style.margin = "0";
    const root = doc.createElement("div");
    root.className = "popoutws";
    root.style.height = "100vh"; root.style.overflow = "auto";
    doc.body.appendChild(root);
    setContainer(root);
    const onUnload = () => onClose();
    w.addEventListener("beforeunload", onUnload);
    const poll = window.setInterval(() => { if (w.closed) onClose(); }, 500);
    return () => {
      window.clearInterval(poll);
      w.removeEventListener("beforeunload", onUnload);
      if (!w.closed) w.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!container) return null;
  return createPortal(
    <TerminalProvider embedded={feed}>
      {POPOUT_PANELS.map((id) => BY_ID[id]).filter(Boolean).map((p) => (
        <div className="panel popout" key={p.id} style={{ marginBottom: 6 }}>
          <div className="ph"><span className="n">{p.n}</span><h3>{p.title}</h3>
            <span className="hint">{p.hint || ""}</span></div>
          {p.body}
        </div>
      ))}
    </TerminalProvider>,
    container,
  );
}

export default function Workspace() {
  const t = useTerminal();
  const [draft, setDraft] = useState<LayoutSnapshot>(t.layout);
  const [dragActive, setDragActive] = useState(false);       // true while a panel/palette chip is being dragged
  const draftRef = useRef(draft);
  const appliedRef = useRef<LayoutSnapshot>(t.layout);        // last snapshot synced to/from context (loop guard)
  const draggingRef = useRef(false);                          // true during a splitter resize (defer commit)
  const dragId = useRef<string | null>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const [popouts, setPopouts] = useState<number[]>([]);      // ids of open independent pop-out workspaces
  const popoutSeq = useRef(0);

  useEffect(() => { draftRef.current = draft; }, [draft]);
  // Pull EXTERNAL context-layout changes (hydration / preset / reset) into the local draft; skip our own commits.
  useEffect(() => {
    if (t.layout !== appliedRef.current) { appliedRef.current = t.layout; setDraft(t.layout); draftRef.current = t.layout; }
  }, [t.layout]);

  const commit = (s: LayoutSnapshot) => { appliedRef.current = s; t.setLayout(s); };   // persist (debounced in context)
  const apply = (s: LayoutSnapshot) => { draftRef.current = s; setDraft(s); commit(s); };
  const st = draft.st, colW = draft.colW, colHidden = draft.colHidden, cols = draft.cols;
  const pstate = (id: string): PanelState => st[id] ?? { collapsed: false, maxed: false, hidden: false };

  const patch = (id: string, p: Partial<PanelState>) =>
    apply({ ...draftRef.current, st: { ...draftRef.current.st, [id]: { ...pstate(id), ...p } } });

  // Move a panel (an existing one being reordered, OR a hidden one dragged from the palette) into `col` at
  // `idx`, un-hiding it. Singleton: the id is removed from every column first, so it never appears twice.
  const move = (col: Col, idx: number) => {
    const from = dragId.current; if (!from) return;
    const s = draftRef.current;
    const next = { L: [...s.cols.L], M: [...s.cols.M], R: [...s.cols.R] };
    (["L", "M", "R"] as Col[]).forEach((k) => { const i = next[k].indexOf(from); if (i >= 0) next[k].splice(i, 1); });
    next[col].splice(Math.max(0, Math.min(next[col].length, idx)), 0, from);
    const stNext = pstate(from).hidden ? { ...s.st, [from]: { ...pstate(from), hidden: false } } : s.st;
    apply({ ...s, cols: next, st: stNext });
  };

  // pop-out: open a NEW independent mini-workspace window (Scanner + Inspector + Ladder under a nested
  // embedded provider — its own selection/toggles, shared feed data; see PopoutPortal). Multiple allowed,
  // each independent of the main window and of each other.
  const popOut = () => setPopouts((p) => [...p, ++popoutSeq.current]);
  const closePopout = (id: number) => setPopouts((p) => p.filter((x) => x !== id));

  // Column-WIDTH resize (M/R). Live on the draft; committed once on pointer-up/cancel (no per-tick persist).
  const dragV = (which: "M" | "R") => (e: React.PointerEvent) => {
    e.preventDefault(); const sp = e.currentTarget as HTMLElement; sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
    draggingRef.current = true;
    const x0 = e.clientX, w0 = draftRef.current.colW[which];
    const mv = (ev: PointerEvent) => setDraft((d) => {
      const nd = { ...d, colW: { ...d.colW, [which]: Math.max(60, Math.min(1000, w0 - (ev.clientX - x0))) } };
      draftRef.current = nd; return nd;
    });
    const up = () => { sp.classList.remove("drag"); draggingRef.current = false; commit(draftRef.current); cleanup(); };
    const cleanup = () => { document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up); document.removeEventListener("pointercancel", up); };
    document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up); document.addEventListener("pointercancel", up);
  };
  // Panel-HEIGHT resize. Renders after EVERY panel (incl. the last/lone one), so a single panel — e.g. the
  // DEPTH LADDER alone in a column — can be shortened, freeing space below it.
  const dragH = (id: string) => (e: React.PointerEvent) => {
    e.preventDefault(); const sp = e.currentTarget as HTMLElement; sp.setPointerCapture(e.pointerId); sp.classList.add("drag");
    draggingRef.current = true;
    const node = refs.current[id]; const y0 = e.clientY, h0 = node ? node.getBoundingClientRect().height : 200;
    const mv = (ev: PointerEvent) => setDraft((d) => {
      const nd = { ...d, st: { ...d.st, [id]: { ...(d.st[id] ?? { collapsed: false, maxed: false, hidden: false }), basis: Math.max(24, Math.min(2000, h0 + (ev.clientY - y0))) } } };
      draftRef.current = nd; return nd;
    });
    const up = () => { sp.classList.remove("drag"); draggingRef.current = false; commit(draftRef.current); cleanup(); };
    const cleanup = () => { document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up); document.removeEventListener("pointercancel", up); };
    document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up); document.addEventListener("pointercancel", up);
  };

  const onChipDragStart = (id: string) => (e: React.DragEvent) => { dragId.current = id; setDragActive(true); e.dataTransfer.effectAllowed = "move"; };
  const endDrag = () => { dragId.current = null; setDragActive(false); };

  // A drop target between/around panels — visible only while a drag is active, highlighted on hover. Dropping
  // places the dragged window at exactly this slot (and un-hides it if it came from the palette).
  const dropSlot = (c: Col, idx: number) => (
    <div key={`${c}-slot-${idx}`} className={"dropslot" + (dragActive ? " on" : "")}
         onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("over"); }}
         onDragLeave={(e) => e.currentTarget.classList.remove("over")}
         onDrop={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove("over"); move(c, idx); endDrag(); }} />
  );

  const renderCol = (c: Col) => {
    const list = cols[c].map((id) => BY_ID[id]).filter((p) => p && !pstate(p.id).hidden);
    const out: ReactNode[] = [];
    list.forEach((p, idx) => {
      const s = pstate(p.id);
      const cls = "panel" + (s.collapsed ? " collapsed" : "") + (s.maxed ? " maxed" : "");
      const style: React.CSSProperties = s.basis != null && !s.collapsed && !s.maxed ? { flex: `0 0 ${s.basis}px` } : {};
      out.push(dropSlot(c, idx));        // drop ABOVE this panel
      out.push(
        <div className={cls} id={p.id} key={p.id} style={style} data-textsize={s.textSize} ref={(el) => { refs.current[p.id] = el; }}>
          <div className="ph" draggable
               onDragStart={(e) => { if ((e.target as HTMLElement).closest(".dock")) { e.preventDefault(); return; } dragId.current = p.id; setDragActive(true); e.dataTransfer.effectAllowed = "move"; }}
               onDragEnd={endDrag}>
            <span className="n">{p.n}</span><h3>{p.title}</h3>
            <span className="hint">{p.hint || ""}</span>
            <span className="dock">
              <span className={"tsz" + (s.textSize ? " on" : "")}
                    title={`Panel text size: ${s.textSize ?? "inherit (page default)"} — click to cycle`}
                    onClick={() => patch(p.id, { textSize: nextSize(s.textSize) })}>A↕</span>
              <span title="Pop out an independent workspace (Scanner + Inspector + Ladder)" onClick={() => popOut()}>⧉</span>
              <span title="Maximize" onClick={() => patch(p.id, { maxed: !s.maxed })}>▢</span>
              <span title="Collapse" onClick={() => patch(p.id, { collapsed: !s.collapsed })}>▁</span>
              <span title="Remove from this view" onClick={() => patch(p.id, { hidden: true })}>✕</span>
            </span>
          </div>
          {p.body}
        </div>
      );
      if (!s.maxed) out.push(<div className="hsplit" key={`${p.id}-hs`} onPointerDown={dragH(p.id)} />);   // resize THIS panel's height (incl. last/lone)
    });
    out.push(dropSlot(c, list.length));  // drop at the BOTTOM of the column
    return out;
  };
  const colDrop = (c: Col) => ({
    onDragOver: (e: React.DragEvent) => e.preventDefault(),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); move(c, draftRef.current.cols[c].length); endDrag(); },
  });

  const hidden = PANELS.filter((p) => pstate(p.id).hidden);

  return (
    <div className="workspace" id="ws">
      {popouts.map((id) => (
        <PopoutPortal key={id} feed={t._feed} onClose={() => closePopout(id)} />
      ))}
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

      {t.paletteOpen ? (
        <div className="menu on" style={{ top: 0, left: 8 }} onMouseLeave={() => t.setPaletteOpen(false)}>
          <div className="mh">ADD A WINDOW — drag onto a drop-zone</div>
          {hidden.length ? hidden.map((p) => (
            <div key={p.id} className="palchip" draggable onDragStart={onChipDragStart(p.id)} onDragEnd={endDrag}>＋ {p.title}</div>
          )) : <div className="note" style={{ padding: "4px 8px" }}>All windows are already visible. Drag a window's header to move it, or ✕ to remove it.</div>}
        </div>
      ) : null}

      {t.panelsMenuOpen ? (
        <div className="menu on" style={{ top: 0, left: 8 }} onMouseLeave={() => t.setPanelsMenuOpen(false)}>
          <div className="mh">SHOW / HIDE PANELS</div>
          {PANELS.map((p) => (
            <label key={p.id}><input type="checkbox" checked={!pstate(p.id).hidden} onChange={() => patch(p.id, { hidden: !pstate(p.id).hidden })} />{p.title}</label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
