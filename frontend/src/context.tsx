/* Shared terminal state. The chrome AND the Dockview-hosted panels read it via useTerminal(), so panels
 * re-render on state change without threading props through Dockview params. Holds the live feed poll +
 * all view state (zone/section/lens/filters/selection/columns). Still a read-only VIEW of the engine. */
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ColDef } from "ag-grid-community";
import { loadFeed, rowsFor, type Feed, type FeedRow, type FeedMeta } from "./feed";
import { COLS, colKeyOf, buildColDefs } from "./columns";
import { applyLens } from "./lens";

const POLL_MS = 4000;

interface TerminalState {
  meta: FeedMeta | null; opps: FeedRow[]; err: string | null; sports: string[];
  zone: string; section: string; lens: string; sportSel: string; part: string;
  sel: FeedRow | null; colKey: string; visible: string[]; columnDefs: ColDef<FeedRow>[]; rows: FeedRow[];
  theme: "amber" | "hc"; paletteOpen: boolean;
  goSection: (z: string, s: string) => void;
  setSection: (s: string) => void;
  toggleLens: (l: string) => void;
  setLens: (l: string) => void;
  setSportSel: (v: string) => void;
  setPart: (v: string) => void;
  setSel: (r: FeedRow | null) => void;
  toggleCol: (f: string) => void;
  resetCols: () => void;
  setColOrder: (order: string[]) => void;
  setTheme: (t: "amber" | "hc") => void;
  setPaletteOpen: (v: boolean) => void;
  registerLayout: (fn: (preset: string) => void) => void;
  applyLayout: (preset: string) => void;
}

const Ctx = createContext<TerminalState | null>(null);
export const useTerminal = (): TerminalState => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTerminal outside TerminalProvider");
  return v;
};

export function TerminalProvider({ children }: { children: ReactNode }) {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zone, setZone] = useState("exec");
  const [section, setSectionRaw] = useState("act");
  const [lens, setLens] = useState("");
  const [sportSel, setSportSel] = useState("");
  const [part, setPart] = useState("");
  const [sel, setSel] = useState<FeedRow | null>(null);
  const [colsByKey, setColsByKey] = useState<Record<string, string[]>>({});
  const [theme, setTheme] = useState<"amber" | "hc">("amber");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [, tick] = useState(0);
  const layoutRef = useRef<((preset: string) => void) | null>(null);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  useEffect(() => {
    let alive = true;
    const pull = () => loadFeed().then((f) => alive && (setFeed(f), setErr(null))).catch((e) => alive && setErr(String(e)));
    pull();
    const poll = setInterval(pull, POLL_MS);
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => { alive = false; clearInterval(poll); clearInterval(clock); };
  }, []);

  const meta = feed?.meta ?? null;
  const opps = useMemo(() => feed?.opps ?? [], [feed]);
  const sports = useMemo(() => Object.keys(meta?.sports ?? {}).sort(), [meta]);
  const colKey = colKeyOf(zone, section);
  const defVis = useMemo(() => COLS[colKey].filter((c) => !c.hide).map((c) => c.f), [colKey]);
  const visible = colsByKey[colKey] ?? defVis;
  const columnDefs = useMemo(() => buildColDefs(COLS[colKey], visible), [colKey, visible]);
  const rows = useMemo(() => {
    let r = rowsFor(opps, zone, section);
    if (sportSel) r = r.filter((o) => (o.sport || "") === sportSel);
    if (part) { const q = part.toLowerCase(); r = r.filter((o) => (o.name || "").toLowerCase().includes(q)); }
    return applyLens(r, lens);
  }, [opps, zone, section, sportSel, part, lens]);

  const value: TerminalState = {
    meta, opps, err, sports, zone, section, lens, sportSel, part, sel, colKey, visible, columnDefs, rows,
    theme, paletteOpen,
    goSection: (z, s) => { setZone(z); setSectionRaw(s); },
    setSection: setSectionRaw,
    toggleLens: (l) => setLens((cur) => (cur === l ? "" : l)),
    setLens,
    setSportSel, setPart, setSel,
    toggleCol: (f) => setColsByKey((m) => {
      const cur = m[colKey] ?? defVis;
      return { ...m, [colKey]: cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f] };
    }),
    resetCols: () => setColsByKey((m) => { const n = { ...m }; delete n[colKey]; return n; }),
    setColOrder: (order) => setColsByKey((m) => ({ ...m, [colKey]: order })),
    setTheme, setPaletteOpen,
    registerLayout: (fn) => { layoutRef.current = fn; },
    applyLayout: (preset) => layoutRef.current?.(preset),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
