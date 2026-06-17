/* Shared terminal state. The chrome AND the mockup-ported panels read it via useTerminal(), so panels
 * re-render on state change without prop threading. Holds the live feed poll + all view state
 * (zone/section/lens/filters/selection/columns/panels). Still a read-only VIEW of the engine. */
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadFeed, rowsFor, SUBTABS, type Feed, type FeedRow, type FeedMeta } from "./feed";
import { subscribeFeed } from "./stream";
import { COLS, colKeyOf } from "./columns";
import { applyLens, LENSES } from "./lens";
import { downloadCsv } from "./csv";
import { encodeUrl, decodeUrl } from "./url";
import { CompareView, OverlapView, LaddersView } from "./panels";
import { postScan, getScanStatus } from "./scan";
import { diffSnapshot, edgeMap, type Change } from "./diff";
import { type FilterState, type BandState, emptyFilters, defaultBand, isDefaultBand, applyBand, passAll, passMembership, hiddenByFee, tournamentOptions } from "./filters";
import { loadPrefs, savePrefs, PREFS_VERSION, THEMES, LAYOUT_PRESETS, SPLITS, type Prefs } from "./prefs";
import { cleanLayout, presetSnapshot, type LayoutSnapshot } from "./layout";
import { apiFetch } from "./http";

export interface ExtraPanel { title: string; body: ReactNode; }
export const TEXT_SIZES = ["compact", "normal", "large", "xlarge"] as const;
export type TextSize = (typeof TEXT_SIZES)[number];
export interface Settings { longShort: boolean; showIds: boolean; resolutionCriteria: boolean; hideNetNegExec: boolean; textSize: TextSize; tz: string; autoRefresh: string; }
const AUTO_MS: Record<string, number> = { "10s": 10000, "30s": 30000, off: 0 };

interface TerminalState {
  meta: FeedMeta | null; opps: FeedRow[]; err: string | null; sports: string[];
  zone: string; section: string; lens: string; filters: FilterState; part: string; tourOptions: string[];
  sel: FeedRow | null; colKey: string; visible: string[]; rows: FeedRow[];
  theme: "amber" | "hc"; paletteOpen: boolean; multi: FeedRow[];
  surface: "opp" | "res" | "ops" | "alrt"; showNet: boolean; itab: "card" | "detail" | "formula";
  extra: ExtraPanel | null; panelsMenuOpen: boolean; scanText: string | null; settings: Settings;
  band: BandState; bandIsDefault: boolean; split: string;
  changeOf: (id: string) => "new" | "up" | "down" | "returned" | null;   // change-signal vs the prev snapshot
  flashIds: Set<string>;                                    // rows to one-shot green-flash this snapshot
  hasBaseline: boolean;                                     // a real diff vs a prior snapshot has run (≥2 snaps)
  count: (zone: string, section: string) => number;
  zoneCount: (zone: string) => number;                      // sum of the zone's section counts (band-aware)
  hiddenByFeeCount: number;                                 // exec rows hidden by the fee filter (honest chip)
  inScope: (zone: string, section: string) => number;       // membership-only count (thresholds not applied)
  runScan: (force: boolean) => void;
  setSetting: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  setBand: (patch: Partial<BandState>) => void;
  resetBand: () => void;
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
  layout: LayoutSnapshot;
  setLayout: (s: LayoutSnapshot) => void;
  applyLayout: (preset: string) => void;       // reseed the layout from a named preset
  resetLayout: () => void;                      // restore the current preset's default layout
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
  // Net-of-fees ESTIMATE columns are shown by DEFAULT (labels carry "Est."; display-only, never rank) so a
  // thin gross edge isn't read as net profit. A returning user's saved showNet preference still wins.
  const [showNet, setShowNet] = useState(true);
  const [itab, setItab] = useState<"card" | "detail" | "formula">("card");
  const [extra, setExtra] = useState<ExtraPanel | null>(null);
  const [panelsMenuOpen, setPanelsMenuOpen] = useState(false);
  const [scanText, setScanText] = useState<string | null>(null);
  // hideNetNegExec defaults OFF (owner pref): all rows show by default. Turning the SETTINGS toggle ON
  // hides executable rows whose TAKER net-of-fees estimate is negative — a display-only declutter that
  // never re-buckets and never hides a MAKER-positive row (net_negative is taker-basis, set only on
  // complete-fee actionable rows), with a hidden-count chip to reveal them. Persisted per-user
  // (auth_store.sanitize_prefs); existing saved prefs are preserved (migrate-vs-accept → accept).
  const [settings, setSettings] = useState<Settings>({ longShort: false, showIds: false, resolutionCriteria: true, hideNetNegExec: false, textSize: "normal", tz: "local", autoRefresh: "10s" });
  // Per-section band overrides (bounded/nearmiss/cheapno). Untouched sections fall back to the engine's
  // default band (from meta.defaults), so bounded max-loss 5¢ and cheap-NO max-loss 15¢ never collide.
  const [bands, setBands] = useState<Record<string, BandState>>({});
  const [split, setSplit] = useState("all");            // bounded-loss All / Vertical / Calendar
  const [layoutPreset, setLayoutPreset] = useState("default");   // the preset SEED (per user)
  // The full custom workspace layout (column widths, per-panel height/collapse/hide, panel order). Persisted
  // per user; a preset just reseeds it. Workspace edits a local draft and commits back here.
  const [layout, setLayout] = useState<LayoutSnapshot>(() => presetSnapshot("default"));
  const scanning = useRef(false);
  const scanPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);                       // guards setState after unmount (logout/expiry)
  const setSetting = <K extends keyof Settings>(k: K, v: Settings[K]) => setSettings((s) => ({ ...s, [k]: v }));
  const refreshFeed = () => loadFeed()
    .then((f) => { if (mountedRef.current) { setFeed(f); setErr(null); } })
    .catch((e) => { if (mountedRef.current) setErr(String(e)); });

  // Manual scan (▷SCAN / ⚡force): drive POST /scan, animate the scanbar, poll /scan/status. The 4s feed
  // poll picks up the new snapshot when the scan finishes. Honors token/rate-limit (never a silent no-op).
  const runScan = (force: boolean) => {
    if (scanning.current) return;
    scanning.current = true;
    document.body.classList.add("scanning");
    setScanText("SCANNING · fetching…");
    const stopPoll = () => { if (scanPollRef.current) { clearInterval(scanPollRef.current); scanPollRef.current = null; } };
    const finish = (msg: string | null) => {
      document.body.classList.remove("scanning"); scanning.current = false;
      if (!mountedRef.current) return;                      // provider unmounted — don't setState
      setScanText(msg);
      if (msg) setTimeout(() => mountedRef.current && setScanText((cur) => (cur === msg ? null : cur)), 4000);
    };
    postScan(force).then((res) => {
      if (!res.ok) { finish("scan blocked: " + res.error); return; }
      setScanText("SCANNING · detecting…");
      let ticks = 0;
      stopPoll();                                            // never run two status polls at once
      scanPollRef.current = setInterval(async () => {
        ticks++;
        if (!mountedRef.current) { stopPoll(); return; }     // unmounted mid-poll → stop, don't leak
        try {
          const s = await getScanStatus();
          if (s.status !== "in_progress" || ticks > 40) {
            stopPoll();
            if (!s.last_scan_error) refreshFeed();             // pull the fresh snapshot immediately
            finish(s.last_scan_error ? "scan error: " + s.last_scan_error : "scan complete · snapshot refreshed");
          }
        } catch { stopPoll(); finish("scan status unavailable"); }
      }, 1500);
    }).catch((e) => finish("scan error: " + String(e)));
  };

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  // Text size rides the same <html data-*> mechanism as the theme; tokens.css maps it to --fs and every
  // font-size derives from --fs, so the whole UI scales (not just the Inspector).
  useEffect(() => { document.documentElement.dataset.textsize = settings.textSize; }, [settings.textSize]);

  // Track mount + tear down a running scan poll on unmount (logout / session expiry unmounts the provider
  // mid-scan): without this the status setInterval keeps firing and would setState on a dead component.
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; if (scanPollRef.current) clearInterval(scanPollRef.current); };
  }, []);

  // (The 1s snapshot-age clock now lives in <AgeClock> in App.tsx — a leaf with its own local tick — so it
  // no longer re-renders the whole provider tree every second.)
  // Live feed: instant paint via loadFeed(), then PUSH updates over SSE (subscribeFeed), with a polling
  // fallback baked in if the stream errors repeatedly. "off" = manual only (no live updates), matching the
  // prior poll-disabled behavior. The fallback cadence reuses the auto-refresh interval, so this is a
  // strict superset of the old polling loop.
  useEffect(() => {
    let alive = true;
    loadFeed().then((f) => alive && (setFeed(f), setErr(null))).catch((e) => alive && setErr(String(e)));
    const ms = AUTO_MS[settings.autoRefresh] ?? 10000;        // auto-refresh = fallback poll cadence (off = manual)
    if (!ms) return () => { alive = false; };                 // auto-refresh off → manual only, no live updates
    const h = subscribeFeed(
      (f) => { if (alive) { setFeed(f); setErr(null); } },
      (e) => { if (alive) setErr(e); },
      { pollMs: ms });
    return () => { alive = false; h.close(); };
  }, [settings.autoRefresh]);

  // Per-user preferences: hydrate ONCE on mount (AuthGate has already authenticated), applying only valid
  // values (defense-in-depth — the server sanitizes too). Then save durable view state, debounced. NOTE:
  // filters are intentionally NOT persisted. `hydratedRef` gates the saver so first-paint defaults never
  // overwrite the stored profile before it loads.
  const hydratedRef = useRef(false);
  const applyPrefs = (p: Prefs) => {
    // Version gate: ignore a blob written by a NEWER client schema (don't misinterpret unknown shapes).
    // Same/older/absent versions are applied field-by-field below (every field is already whitelisted).
    if (typeof p.version === "number" && p.version > PREFS_VERSION) return;
    if (p.theme && (THEMES as readonly string[]).includes(p.theme)) setTheme(p.theme);
    if (p.settings && typeof p.settings === "object") {
      setSettings((s) => {
        const next = { ...s };
        for (const k of ["longShort", "showIds", "resolutionCriteria", "hideNetNegExec"] as const) {
          if (typeof p.settings![k] === "boolean") (next as Record<string, unknown>)[k] = p.settings![k];
        }
        if (typeof p.settings!.tz === "string") next.tz = p.settings!.tz as string;
        if (["10s", "30s", "off"].includes(p.settings!.autoRefresh as string)) next.autoRefresh = p.settings!.autoRefresh as string;
        if ((TEXT_SIZES as readonly string[]).includes(p.settings!.textSize as string)) next.textSize = p.settings!.textSize as TextSize;
        return next;
      });
    }
    if (typeof p.showNet === "boolean") setShowNet(p.showNet);
    if (p.columns && typeof p.columns === "object") {
      const clean: Record<string, string[]> = {};
      for (const [k, v] of Object.entries(p.columns)) {
        if (k in COLS && Array.isArray(v) && v.every((x) => typeof x === "string")) clean[k] = v;
      }
      setColsByKey(clean);
    }
    if (p.bands && typeof p.bands === "object") {
      // Validate like every other field (defense-in-depth — the server sanitizes too): keep only sections
      // that are plain objects of FINITE scalars, so a malformed blob can't drive NaN into the filter math.
      const okScalar = (v: unknown) =>
        typeof v === "boolean" || typeof v === "string" || (typeof v === "number" && Number.isFinite(v));
      const cleanBands: Record<string, BandState> = {};
      for (const [section, band] of Object.entries(p.bands)) {
        if (band && typeof band === "object" && !Array.isArray(band) && Object.values(band).every(okScalar))
          cleanBands[section] = band as unknown as BandState;
      }
      setBands(cleanBands);
    }
    if (p.split && (SPLITS as readonly string[]).includes(p.split)) setSplit(p.split);
    const preset = p.layoutPreset && (LAYOUT_PRESETS as readonly string[]).includes(p.layoutPreset) ? p.layoutPreset : "default";
    if (p.layoutPreset && (LAYOUT_PRESETS as readonly string[]).includes(p.layoutPreset)) setLayoutPreset(p.layoutPreset);
    // A valid saved custom layout wins; otherwise seed from the saved preset. cleanLayout fail-opens (→ null)
    // on garbage, so an invalid blob never blanks the workspace.
    const cl = cleanLayout(p.layout);
    setLayout(cl ?? presetSnapshot(preset));
  };
  useEffect(() => {
    loadPrefs().then(applyPrefs).finally(() => { hydratedRef.current = true; });
  }, []);
  useEffect(() => {
    if (!hydratedRef.current) return;
    const t = setTimeout(() => {
      void savePrefs({
        version: PREFS_VERSION, theme, showNet, columns: colsByKey, split, layoutPreset,
        settings: settings as unknown as Record<string, unknown>,
        bands: bands as unknown as Record<string, Record<string, unknown>>,
        layout: layout as unknown as Record<string, unknown>,
      });
    }, 600);
    return () => clearTimeout(t);
  }, [theme, settings, showNet, colsByKey, bands, split, layoutPreset, layout]);

  const meta = feed?.meta ?? null;
  const opps = useMemo(() => feed?.opps ?? [], [feed]);

  // Effective band for the active section = the user's override, else the engine default (config-sourced
  // via meta.defaults). setBand patches the active section; resetBand drops its override (back to default).
  const band = useMemo(() => bands[section] ?? defaultBand(section, meta?.defaults), [bands, section, meta?.defaults]);
  const setBand = (patch: Partial<BandState>) =>
    setBands((m) => ({ ...m, [section]: { ...(m[section] ?? defaultBand(section, meta?.defaults)), ...patch } }));
  const resetBand = () => setBands((m) => { const n = { ...m }; delete n[section]; return n; });
  const bandIsDefault = isDefaultBand(section, band, meta?.defaults);

  // Change-signal vs the PREVIOUS snapshot — diff only when snapshot_id actually advances (NOT on every
  // same-snapshot poll), and never on the first load (no all-NEW flash). Stored as edge-by-id (NaN = no
  // edge, so a missing/null edge never produces a false up/down). Display-only; never feeds ranking.
  const prevEdgeRef = useRef<Map<string, number>>(new Map());
  const prevSnapRef = useRef<number | null>(null);
  const seenEverRef = useRef<Set<string>>(new Set());     // ids seen any time this session → "returned" vs "new"
  const [change, setChange] = useState<Map<string, Change>>(new Map());
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());
  const [baselineReady, setBaselineReady] = useState(false);          // true once a real diff vs a prior snap ran
  useEffect(() => {
    const sid = meta?.snapshot_id ?? null;
    if (sid == null || sid === prevSnapRef.current) return;          // no snapshot / unchanged → keep flags
    const isFirst = prevSnapRef.current === null;
    const { change: chg, flash } = diffSnapshot(prevEdgeRef.current, opps, isFirst, seenEverRef.current);
    setChange(chg); setFlashIds(flash);
    if (!isFirst) setBaselineReady(true);                            // a prior snapshot existed → changeOf is real
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
    let r = applyBand(rowsFor(opps, zone, section)
      .filter((o) => passAll(o, filters) && !hiddenByFee(o, zone, settings.hideNetNegExec)), section, band);
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
  }, [opps, zone, section, filters, lens, band, split, settings.hideNetNegExec]);
  // Tile/tab counts. Actionable stays membership-only (passThreshold auto-passes act/diag — see filters.ts);
  // the speculative band sections (bounded/nearmiss/cheapno) also apply their SecBar band so the badge
  // matches the rows you'll actually see (e.g. the BOUNDED-RISK count tracks the Max-loss control). The
  // hide-fee-negative filter also reduces the exec-zone counts (the hidden total surfaces via hiddenByFeeCount).
  const count = (z: string, s: string) => {
    const base = rowsFor(opps, z, s)
      .filter((o) => passAll(o, filters) && !hiddenByFee(o, z, settings.hideNetNegExec));
    return (s === "bounded" || s === "nearmiss" || s === "cheapno")
      ? applyBand(base, s, bands[s] ?? defaultBand(s, meta?.defaults)).length
      : base.length;
  };
  // How many exec rows the fee filter is hiding right now (membership-passing) — drives the honest
  // "N hidden by fee filter" chip so a dropped ACTIONABLE count never implies "no opportunities".
  const hiddenByFeeCount = useMemo(() =>
    settings.hideNetNegExec
      ? opps.filter((o) => o.zone === "exec" && o.net_negative === true && passAll(o, filters)).length
      : 0,
  [opps, filters, settings.hideNetNegExec]);
  // Zone badge = the true total across the zone's sections (NOT just the first one), so SPECULATIVE equals
  // the sum of bounded + near-miss + qualifier + cheap-no rather than mirroring the bounded count.
  const zoneCount = (z: string) => SUBTABS[z].reduce((sum, [s]) => sum + count(z, s), 0);
  // Membership-only count (thresholds NOT applied) — the "in scope" denominator for "X shown / Y in scope".
  const inScope = (z: string, s: string) => rowsFor(opps, z, s).filter((o) => passMembership(o, filters)).length;
  const patch = (p: Partial<FilterState>) => setFilters((f) => ({ ...f, ...p }));
  const toggleSet = (key: "sports" | "tours", v: string) => setFilters((f) => {
    const next = new Set(f[key]); next.has(v) ? next.delete(v) : next.add(v); return { ...f, [key]: next };
  });

  const value: TerminalState = {
    meta, opps, err, sports, zone, section, lens, filters, part: filters.part, tourOptions,
    sel, colKey, visible, rows, theme, paletteOpen, multi, surface, showNet, itab,
    extra, panelsMenuOpen, scanText, settings, band, bandIsDefault, split, count, zoneCount, hiddenByFeeCount, inScope, runScan, setSetting,
    changeOf: (id) => change.get(id) ?? null, flashIds, hasBaseline: baselineReady,
    setBand, resetBand, setSplit,
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
    layout, setLayout,
    // Picking a preset reseeds the full layout AND records the preset (so Reset knows the seed); both persist.
    applyLayout: (preset) => { setLayoutPreset(preset); setLayout(presetSnapshot(preset)); },
    resetLayout: () => setLayout(presetSnapshot(layoutPreset)),
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
      const res = await apiFetch("/api/terminal/export", { method: "POST",
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
