/* Shared terminal state. The chrome AND the mockup-ported panels read it via useTerminal(), so panels
 * re-render on state change without prop threading. Holds the live feed poll + all view state
 * (zone/section/lens/filters/selection/columns/panels). Still a read-only VIEW of the engine. */
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadFeed, rowsFor, type Feed, type FeedRow, type FeedMeta } from "./feed";
import { COLS, colKeyOf } from "./columns";
import { applyLens } from "./lens";
import { downloadCsv } from "./csv";
import { CompareView, OverlapView, LaddersView } from "./panels";
import { type FilterState, emptyFilters, filteredCount, passAll, tournamentOptions } from "./filters";

const POLL_MS = 4000;

export interface ExtraPanel { title: string; body: ReactNode; }

interface TerminalState {
  meta: FeedMeta | null; opps: FeedRow[]; err: string | null; sports: string[];
  zone: string; section: string; lens: string; filters: FilterState; part: string; tourOptions: string[];
  sel: FeedRow | null; colKey: string; visible: string[]; rows: FeedRow[];
  theme: "amber" | "hc"; paletteOpen: boolean; multi: FeedRow[];
  surface: "opp" | "res" | "ops"; showNet: boolean; itab: "card" | "detail" | "formula";
  extra: ExtraPanel | null; panelsMenuOpen: boolean;
  count: (zone: string, section: string) => number;
  goSection: (z: string, s: string) => void;
  setSection: (s: string) => void;
  toggleLens: (l: string) => void;
  setLens: (l: string) => void;
  toggleSport: (v: string) => void;
  toggleTour: (v: string) => void;
  setPart: (v: string) => void;
  setMinSize: (v: number) => void;
  setTradableOnly: (v: boolean) => void;
  clearFilters: () => void;
  setSel: (r: FeedRow | null) => void;
  toggleCol: (f: string) => void;
  resetCols: () => void;
  setColOrder: (order: string[]) => void;
  setTheme: (t: "amber" | "hc") => void;
  setPaletteOpen: (v: boolean) => void;
  registerLayout: (fn: (preset: string) => void) => void;
  applyLayout: (preset: string) => void;
  setMulti: (rows: FeedRow[]) => void;
  setExtra: (e: ExtraPanel | null) => void;
  setPanelsMenuOpen: (v: boolean) => void;
  openCompare: () => void;
  openOverlap: () => void;
  openLadders: () => void;
  exportSelected: () => void;
  exportView: () => void;
  setSurface: (s: "opp" | "res" | "ops") => void;
  setShowNet: (v: boolean) => void;
  setItab: (t: "card" | "detail" | "formula") => void;
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
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const [sel, setSel] = useState<FeedRow | null>(null);
  const [colsByKey, setColsByKey] = useState<Record<string, string[]>>({});
  const [theme, setTheme] = useState<"amber" | "hc">("amber");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [multi, setMulti] = useState<FeedRow[]>([]);
  const [surface, setSurface] = useState<"opp" | "res" | "ops">("opp");
  const [showNet, setShowNet] = useState(false);
  const [itab, setItab] = useState<"card" | "detail" | "formula">("card");
  const [extra, setExtra] = useState<ExtraPanel | null>(null);
  const [panelsMenuOpen, setPanelsMenuOpen] = useState(false);
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
  const visible = useMemo(() => {
    const base = colsByKey[colKey] ?? defVis;
    if (showNet && colKey === "opp") {                 // reveal the display-only net-of-fees estimate columns
      const nets = ["net_edge", "net_profit", "fees"].filter((f) => !base.includes(f));
      if (nets.length) { const i = base.indexOf("profit"); const out = [...base]; out.splice(i < 0 ? out.length : i + 1, 0, ...nets); return out; }
    }
    return base;
  }, [colsByKey, colKey, defVis, showNet]);
  const tourOptions = useMemo(() => tournamentOptions(opps, filters.sports), [opps, filters.sports]);
  const rows = useMemo(
    () => applyLens(rowsFor(opps, zone, section).filter((o) => passAll(o, filters)), lens),
    [opps, zone, section, filters, lens]);
  // Tile/tab counts over the filtered set (Actionable membership-only — see filters.ts).
  const count = (z: string, s: string) => filteredCount(opps, z, s, filters);
  const patch = (p: Partial<FilterState>) => setFilters((f) => ({ ...f, ...p }));
  const toggleSet = (key: "sports" | "tours", v: string) => setFilters((f) => {
    const next = new Set(f[key]); next.has(v) ? next.delete(v) : next.add(v); return { ...f, [key]: next };
  });

  const value: TerminalState = {
    meta, opps, err, sports, zone, section, lens, filters, part: filters.part, tourOptions,
    sel, colKey, visible, rows, theme, paletteOpen, multi, surface, showNet, itab,
    extra, panelsMenuOpen, count,
    goSection: (z, s) => { setZone(z); setSectionRaw(s); },
    setSection: setSectionRaw,
    toggleLens: (l) => setLens((cur) => (cur === l ? "" : l)),
    setLens,
    toggleSport: (v) => toggleSet("sports", v),
    toggleTour: (v) => toggleSet("tours", v),
    setPart: (v) => patch({ part: v }),
    setMinSize: (v) => patch({ minSize: v }),
    setTradableOnly: (v) => patch({ tradableOnly: v }),
    clearFilters: () => setFilters(emptyFilters()),
    setSel,
    toggleCol: (f) => setColsByKey((m) => {
      const cur = m[colKey] ?? defVis;
      return { ...m, [colKey]: cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f] };
    }),
    resetCols: () => setColsByKey((m) => { const n = { ...m }; delete n[colKey]; return n; }),
    setColOrder: (order) => setColsByKey((m) => ({ ...m, [colKey]: order })),
    setTheme, setPaletteOpen, setMulti, setExtra, setPanelsMenuOpen,
    registerLayout: (fn) => { layoutRef.current = fn; },
    applyLayout: (preset) => layoutRef.current?.(preset),
    openCompare: () => setExtra({ title: `COMPARE (${multi.length})`, body: <CompareView opps={multi} /> }),
    openOverlap: () => setExtra({ title: "DON'T-TAKE-BOTH", body: <OverlapView opps={multi} /> }),
    openLadders: () => setExtra({ title: `LADDERS (${Math.min(8, multi.length)})`, body: <LaddersView opps={multi} /> }),
    exportSelected: () => downloadCsv(
      `selected_${multi.length}_snap${meta?.snapshot_id ?? "x"}.csv`,
      multi, COLS[colKey].filter((c) => visible.includes(c.f))),
    exportView: () => downloadCsv(
      `kalshi_${section}_snap${meta?.snapshot_id ?? "x"}.csv`,
      rows, COLS[colKey].filter((c) => visible.includes(c.f))),
    setSurface, setShowNet, setItab,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
