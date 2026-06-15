/* Shared terminal state. The chrome AND the mockup-ported panels read it via useTerminal(), so panels
 * re-render on state change without prop threading. Holds the live feed poll + all view state
 * (zone/section/lens/filters/selection/columns/panels). Still a read-only VIEW of the engine. */
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadFeed, rowsFor, SUBTABS, type Feed, type FeedRow, type FeedMeta } from "./feed";
import { COLS, colKeyOf } from "./columns";
import { applyLens, LENSES } from "./lens";
import { downloadCsv } from "./csv";
import { encodeUrl, decodeUrl } from "./url";
import { CompareView, OverlapView, LaddersView } from "./panels";
import { postScan, getScanStatus } from "./scan";
import { diffSnapshot, edgeMap, type Change } from "./diff";
import { type FilterState, type BandState, emptyFilters, emptyBand, applyBand, filteredCount, passAll, passMembership, tournamentOptions } from "./filters";

export interface ExtraPanel { title: string; body: ReactNode; }
export interface Settings { longShort: boolean; showIds: boolean; resolutionCriteria: boolean; tz: string; autoRefresh: string; }
const AUTO_MS: Record<string, number> = { "10s": 10000, "30s": 30000, off: 0 };

interface TerminalState {
  meta: FeedMeta | null; opps: FeedRow[]; err: string | null; sports: string[];
  zone: string; section: string; lens: string; filters: FilterState; part: string; tourOptions: string[];
  sel: FeedRow | null; colKey: string; visible: string[]; rows: FeedRow[];
  theme: "amber" | "hc"; paletteOpen: boolean; multi: FeedRow[];
  surface: "opp" | "res" | "ops" | "alrt"; showNet: boolean; itab: "card" | "detail" | "formula";
  extra: ExtraPanel | null; panelsMenuOpen: boolean; scanText: string | null; settings: Settings;
  band: BandState; split: string;
  changeOf: (id: string) => "new" | "up" | "down" | "returned" | null;   // change-signal vs the prev snapshot
  flashIds: Set<string>;                                    // rows to one-shot green-flash this snapshot
  count: (zone: string, section: string) => number;
  inScope: (zone: string, section: string) => number;       // membership-only count (thresholds not applied)
  runScan: (force: boolean) => void;
  setSetting: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  setBand: (patch: Partial<BandState>) => void;
  setSplit: (v: string) => void;
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
  exportZip: () => void;
  setSurface: (s: "opp" | "res" | "ops" | "alrt") => void;
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
  const [surface, setSurface] = useState<"opp" | "res" | "ops" | "alrt">("opp");
  const [showNet, setShowNet] = useState(false);
  const [itab, setItab] = useState<"card" | "detail" | "formula">("card");
  const [extra, setExtra] = useState<ExtraPanel | null>(null);
  const [panelsMenuOpen, setPanelsMenuOpen] = useState(false);
  const [scanText, setScanText] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings>({ longShort: false, showIds: false, resolutionCriteria: true, tz: "local", autoRefresh: "10s" });
  const [band, setBand] = useState<BandState>(emptyBand);
  const [split, setSplit] = useState("all");            // bounded-loss All / Vertical / Calendar
  const scanning = useRef(false);
  const [, tick] = useState(0);
  const layoutRef = useRef<((preset: string) => void) | null>(null);
  const setSetting = <K extends keyof Settings>(k: K, v: Settings[K]) => setSettings((s) => ({ ...s, [k]: v }));
  const refreshFeed = () => loadFeed().then((f) => (setFeed(f), setErr(null))).catch((e) => setErr(String(e)));

  // Manual scan (▷SCAN / ⚡force): drive POST /scan, animate the scanbar, poll /scan/status. The 4s feed
  // poll picks up the new snapshot when the scan finishes. Honors token/rate-limit (never a silent no-op).
  const runScan = (force: boolean) => {
    if (scanning.current) return;
    scanning.current = true;
    document.body.classList.add("scanning");
    setScanText("SCANNING · fetching…");
    const finish = (msg: string | null) => {
      document.body.classList.remove("scanning"); scanning.current = false; setScanText(msg);
      if (msg) setTimeout(() => setScanText((cur) => (cur === msg ? null : cur)), 4000);
    };
    postScan(force).then((res) => {
      if (!res.ok) { finish("scan blocked: " + res.error); return; }
      setScanText("SCANNING · detecting…");
      let ticks = 0;
      const poll = setInterval(async () => {
        ticks++;
        try {
          const s = await getScanStatus();
          if (s.status !== "in_progress" || ticks > 40) {
            clearInterval(poll);
            if (!s.last_scan_error) refreshFeed();             // pull the fresh snapshot immediately
            finish(s.last_scan_error ? "scan error: " + s.last_scan_error : "scan complete · snapshot refreshed");
          }
        } catch { clearInterval(poll); finish("scan status unavailable"); }
      }, 1500);
    }).catch((e) => finish("scan error: " + String(e)));
  };

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  useEffect(() => { const c = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(c); }, []);
  useEffect(() => {
    let alive = true;
    const pull = () => loadFeed().then((f) => alive && (setFeed(f), setErr(null))).catch((e) => alive && setErr(String(e)));
    pull();
    const ms = AUTO_MS[settings.autoRefresh] ?? 10000;        // auto-refresh = feed-poll cadence (off = manual)
    const poll = ms ? setInterval(pull, ms) : null;
    return () => { alive = false; if (poll) clearInterval(poll); };
  }, [settings.autoRefresh]);

  const meta = feed?.meta ?? null;
  const opps = useMemo(() => feed?.opps ?? [], [feed]);

  // Change-signal vs the PREVIOUS snapshot — diff only when snapshot_id actually advances (NOT on every
  // same-snapshot poll), and never on the first load (no all-NEW flash). Stored as edge-by-id (NaN = no
  // edge, so a missing/null edge never produces a false up/down). Display-only; never feeds ranking.
  const prevEdgeRef = useRef<Map<string, number>>(new Map());
  const prevSnapRef = useRef<number | null>(null);
  const seenEverRef = useRef<Set<string>>(new Set());     // ids seen any time this session → "returned" vs "new"
  const [change, setChange] = useState<Map<string, Change>>(new Map());
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    const sid = meta?.snapshot_id ?? null;
    if (sid == null || sid === prevSnapRef.current) return;          // no snapshot / unchanged → keep flags
    const { change: chg, flash } = diffSnapshot(prevEdgeRef.current, opps, prevSnapRef.current === null, seenEverRef.current);
    setChange(chg); setFlashIds(flash);
    prevEdgeRef.current = edgeMap(opps);
    prevSnapRef.current = sid;
    for (const o of opps) seenEverRef.current.add(o.id);            // remember after diffing
  }, [meta?.snapshot_id, opps]);

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

  // URL state (old-dashboard parity): restore ONCE after the first feed arrives, sanitized against the
  // live feed (drop a sport/tournament not present), then mirror changes to the URL (guarded vs loops).
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current || !meta) return;
    restoredRef.current = true;
    const d = decodeUrl(window.location.search);
    const validSports = new Set(Object.keys(meta.sports ?? {}));
    const sports = new Set((d.sports ?? []).filter((s) => validSports.has(s)));
    const validTours = new Set(tournamentOptions(opps, sports));
    const tours = new Set((d.tours ?? []).filter((tv) => validTours.has(tv)));
    setFilters((f) => ({ ...f, sports, tours, part: d.part ?? f.part }));
    if (d.surface && ["opp", "res", "ops", "alrt"].includes(d.surface)) setSurface(d.surface as "opp" | "res" | "ops" | "alrt");
    if (d.lens && LENSES.some(([l]) => l === d.lens)) setLens(d.lens);
    if (d.section) {
      const z = d.zone && SUBTABS[d.zone] ? d.zone : Object.keys(SUBTABS).find((k) => SUBTABS[k].some(([s]) => s === d.section));
      if (z && SUBTABS[z].some(([s]) => s === d.section)) { setZone(z); setSectionRaw(d.section); }
    }
  }, [meta, opps]);
  useEffect(() => {
    if (!restoredRef.current) return;                 // don't clobber the URL before the restore runs
    const q = encodeUrl({ surface, zone, section, lens,
      sports: [...filters.sports], tours: [...filters.tours], part: filters.part });
    if (q !== window.location.search) window.history.replaceState(null, "", q || window.location.pathname);
  }, [surface, zone, section, lens, filters]);
  const rows = useMemo(() => {
    let r = applyBand(rowsFor(opps, zone, section).filter((o) => passAll(o, filters)), section, band);
    // Bounded-loss Vertical/Calendar split (resolution_mode; missing → "calendar", the engine default).
    if (section === "bounded" && split !== "all") {
      r = r.filter((o) => (String(o.resolution_mode || "calendar")) === split);
    }
    const sorted = applyLens(r, lens);
    // Cheap-NO "group by ladder" is a final display grouping (after the lens), by tournament/ladder.
    if (section === "cheapno" && band.groupByLadder) {
      return [...sorted].sort((a, b) => String(a.sub || "").localeCompare(String(b.sub || "")));
    }
    return sorted;
  }, [opps, zone, section, filters, lens, band, split]);
  // Tile/tab counts over the filtered set (Actionable membership-only — see filters.ts).
  const count = (z: string, s: string) => filteredCount(opps, z, s, filters);
  // Membership-only count (thresholds NOT applied) — the "in scope" denominator for "X shown / Y in scope".
  const inScope = (z: string, s: string) => rowsFor(opps, z, s).filter((o) => passMembership(o, filters)).length;
  const patch = (p: Partial<FilterState>) => setFilters((f) => ({ ...f, ...p }));
  const toggleSet = (key: "sports" | "tours", v: string) => setFilters((f) => {
    const next = new Set(f[key]); next.has(v) ? next.delete(v) : next.add(v); return { ...f, [key]: next };
  });

  const value: TerminalState = {
    meta, opps, err, sports, zone, section, lens, filters, part: filters.part, tourOptions,
    sel, colKey, visible, rows, theme, paletteOpen, multi, surface, showNet, itab,
    extra, panelsMenuOpen, scanText, settings, band, split, count, inScope, runScan, setSetting,
    changeOf: (id) => change.get(id) ?? null, flashIds,
    setBand: (patch) => setBand((b) => ({ ...b, ...patch })), setSplit,
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
    // ZIP export — POST the full FILTERED opportunity set (all sections) so the server's opportunities.csv
    // matches what the filters show; frames stay whole-snapshot (old-dashboard parity).
    exportZip: async () => {
      const ids = opps.filter((o) => passAll(o, filters)).map((o) => o.id);
      const res = await fetch("/api/terminal/export", { method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/zip" },
        body: JSON.stringify({ opportunity_ids: ids, snapshot_id: meta?.snapshot_id ?? null }) });
      if (!res.ok) { setErr(`export ${res.status}`); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `kalshi-snapshot-${meta?.snapshot_id ?? "x"}.zip`; a.click();
      URL.revokeObjectURL(url);
    },
    setSurface, setShowNet, setItab,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
