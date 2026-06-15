/* App shell — DOM + classes ported VERBATIM from ui-mockup-final-spa.html so the chrome is pixel-exact.
 * React supplies the live data/state; the look is the mockup's. */
import { useEffect, useState } from "react";
import { TerminalProvider, useTerminal } from "./context";
import { TILES } from "./feed";
import { LENSES } from "./lens";
import { loadDiagnostics, loadBacklog, loadBacklogEvents, loadTelemetry, type Diagnostics, type BacklogItem, type BacklogInterval, type Telemetry } from "./detail";
import Workspace from "./Workspace";

function MarketTelemetry() {
  const [d, setD] = useState<Telemetry | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { let a = true; loadTelemetry().then((x) => a && setD(x)).catch((e) => a && setErr(String(e))); return () => { a = false; }; }, []);
  const tbl = (title: string, rows: unknown[][], cols: string[]) => (
    <div className="rp"><div className="h">{title}<span className="resb">CONTEXT</span></div><div className="c">
      {rows.length === 0 ? <div className="note dim">no two-sided books</div> :
        <table><thead><tr><th>{cols[0]}</th>{cols.slice(1).map((c) => <th key={c} className="r">{c}</th>)}</tr></thead>
          <tbody>{rows.slice(0, 5).map((r, i) => (
            <tr key={i}><td className="nm">{String(r[0])}</td>{r.slice(1).map((v, j) => <td key={j} className="r">{typeof v === "number" ? v.toLocaleString() : String(v)}</td>)}</tr>
          ))}</tbody></table>}
    </div></div>
  );
  if (err) return <div className="rp"><div className="h">MARKET TELEMETRY</div><div className="c"><div className="note red">{err}</div></div></div>;
  if (!d) return <div className="rp"><div className="h">MARKET TELEMETRY</div><div className="c"><div className="note">loading…</div></div></div>;
  return <>
    {tbl("MOST LIQUID — SPORTS", d.top_sports, ["Sport", "Depth", "Buy $", "Sell $", "Depth×mid $"])}
    {tbl("MOST LIQUID — CONTRACTS", d.top_contracts, ["Contract", "Depth", "Spread ¢"])}
    {tbl("TIGHTEST BOOKS", d.tightest, ["Contract", "Spread ¢", "Depth"])}
    {tbl("MOST TRADED", d.most_traded, ["Contract", "Volume"])}
    <div className="rp"><div className="h">MOST VOLATILE NOW<span className="resb">DISPLAY-ONLY</span></div>
      <div className="c"><div className="note">{d.volatility || "—"} <b className="dim">— context, not a tradable signal.</b></div></div></div>
  </>;
}
import Keys from "./Keys";
import Palette from "./Palette";
import MultiSelect from "./MultiSelect";

const DIAG_DISPLAY_CAP = 200;   // cap rendered rows (endpoint caps the payload at 2000); never silent

function GridCard({ title, rows, total, cols }: { title: string; rows: Record<string, unknown>[]; total?: number; cols?: string[] }) {
  if (!rows.length) return <div className="rp"><div className="h">{title}</div><div className="c"><div className="note dim">none</div></div></div>;
  const keys = cols ?? Object.keys(rows[0]).slice(0, 9);
  const shown = rows.slice(0, DIAG_DISPLAY_CAP);
  const n = total ?? rows.length;
  return <div className="rp"><div className="h">{title}<span className="resb">{n > shown.length ? `${shown.length} of ${n.toLocaleString()}` : n.toLocaleString()}</span></div>
    <div className="c" style={{ maxHeight: 260, overflow: "auto" }}>
      <table><thead><tr>{keys.map((k) => <th key={k}>{k}</th>)}</tr></thead>
        <tbody>{shown.map((r, i) => <tr key={i}>{keys.map((k) => <td key={k}>{String(r[k] ?? "")}</td>)}</tr>)}</tbody></table>
    </div></div>;
}

function OpsDiag() {
  const t = useTerminal();
  const [d, setD] = useState<Diagnostics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { let a = true; loadDiagnostics().then((x) => a && setD(x)).catch((e) => a && setErr(String(e))); return () => { a = false; }; }, []);
  const catRows = d ? Object.entries(d.category).filter(([, v]) => typeof v === "number" || typeof v === "string") : [];
  const sumMaxima = t.opps.filter((o) => o.section === "act").reduce((s, o) => s + (typeof o.profit === "number" ? o.profit : 0), 0);
  // considered inventory derived from the LOADED contracts (honest label — not "considered by engine").
  const inv = (() => {
    const c = d?.contracts ?? [];
    const tours = new Set(c.map((r) => String(r.tournament ?? "")));
    const parts = new Set(c.map((r) => String(r.player_key ?? r.player ?? "")));
    const kinds: Record<string, number> = {};
    c.forEach((r) => { const k = String(r.kind ?? "?"); kinds[k] = (kinds[k] || 0) + 1; });
    return { nTour: tours.size, nPart: parts.size, kinds: Object.entries(kinds).sort((a, b) => b[1] - a[1]) };
  })();
  return (
    <>
      <div className="rp"><div className="h">CATEGORY HONESTY<span className="resb">DIAGNOSTIC</span></div><div className="c">
        {err ? <div className="note red">{err}</div> : !d ? <div className="note">loading…</div>
          : <table><tbody>{catRows.map(([k, v]) => <tr key={k}><td className="dim">{k}</td><td className="r white">{typeof v === "number" ? (v as number).toLocaleString() : String(v)}</td></tr>)}
            <tr><td className="dim">sum of independent row maxima (actionable)</td><td className="r white">${sumMaxima.toFixed(2)}</td></tr></tbody></table>}
        <div className="note dim" style={{ marginTop: 4 }}>Sum is NOT a simultaneous total — each opportunity's max is independent.</div>
      </div></div>
      <div className="rp"><div className="h">CONSIDERED INVENTORY<span className="resb">DERIVED</span></div><div className="c">
        {!d ? <div className="note">loading…</div> : <>
          <div className="note">{inv.nTour.toLocaleString()} tournaments · {inv.nPart.toLocaleString()} participants · {d.contracts.length.toLocaleString()} contracts loaded{d.contracts_truncated ? <span className="amber"> (+{d.contracts_truncated} beyond cap)</span> : null}.</div>
          <table style={{ marginTop: 4 }}><thead><tr><th>Kind</th><th className="r">Contracts</th></tr></thead>
            <tbody>{inv.kinds.slice(0, 12).map(([k, n]) => <tr key={k}><td>{k}</td><td className="r white">{n.toLocaleString()}</td></tr>)}</tbody></table>
          <div className="note dim" style={{ marginTop: 3 }}>Derived from the loaded contracts — not the engine's "considered" set; failed/excluded series show under SCAN COVERAGE.</div>
        </>}
      </div></div>
      <GridCard title="FULL CHECK ROWS" rows={d?.checks ?? []} total={(d?.checks.length ?? 0) + (d?.checks_truncated ?? 0)} />
      <GridCard title="LOADED CONTRACTS" rows={d?.contracts ?? []} total={(d?.contracts.length ?? 0) + (d?.contracts_truncated ?? 0)} />
    </>
  );
}

const TILE_SUB: Record<string, string> = {
  act: "executable now", rev: "settlement-dep", blk: "not fillable", bounded: "can lose money",
  nearmiss: "watchlist", qual: "WC setups", cheapno: "NO fades", diag: "diagnostic",
};
const TILE_ACCENT: Record<string, string> = { green: "g", amber: "a", red: "r", cyan: "c", "": "" };

function fmtAge(fetchedAt: string | null): string {
  if (!fetchedAt) return "—";
  const t = Date.parse(fetchedAt.replace(" UTC", "Z"));
  return isNaN(t) ? "—" : Math.max(0, Math.round((Date.now() - t) / 1000)) + "s";
}

function Surface({ id }: { id: "res" | "ops" }) {
  const t = useTerminal();
  const m = t.meta;
  if (id === "res") return (
    <div className="view on"><div className="gridfill">
      <div className="rp"><div className="h">RESEARCH LAB — read-only over derived data<span className="resb">P5 · FUTURE</span></div>
        <div className="c"><div className="note">Research surfaces are <b>P5, not a parity predecessor</b> — derived data only, never new scoring, never feed actionability.</div></div></div>
      <div className="rp"><div className="h">CONDITIONAL PROBABILITY — raw + field de-vig<span className="resb">UNCALIBRATED</span></div>
        <div className="c"><div className="note">Per-node P(deeper│reached), raw price-ratio AND field-implied de-vig, in the inspector's <b>Participant Detail</b> tab.</div></div></div>
      <MarketTelemetry />
    </div></div>
  );
  const buckets = Object.entries(m?.totals ?? {}).sort((a, b) => (b[1] as number) - (a[1] as number));
  const sports = Object.entries(m?.sports ?? {}).sort((a, b) => (b[1] as number) - (a[1] as number));
  const errs = (m?.series_errors as Record<string, unknown> | undefined) ?? {};
  return (
    <div className="view on"><div className="gridfill">
      <div className="rp"><div className="h">SCAN COVERAGE — SNAPSHOT #{m?.snapshot_id ?? "—"}</div><div className="c"><table className="kv-tbl">
        <tbody>{[["Opportunities", m?.n_total], ["Contracts scanned", m?.contracts], ["Checks tested", m?.checks],
          ["Kalshi requests", m?.requests], ["Series scanned", m?.scanned], ["Failed series", m?.failed], ["Retry count", m?.retry]].map(([l, v]) => (
          <tr key={String(l)}><td className="dim">{l}</td><td className="r white">{(typeof v === "number" ? v : 0).toLocaleString()}</td></tr>
        ))}<tr><td className="dim">Fetched at</td><td className="r">{m?.fetched_at ?? "—"}</td></tr></tbody></table></div></div>
      <div className="rp"><div className="h">PER-SPORT COVERAGE</div><div className="c"><table className="kv-tbl"><tbody>
        {sports.map(([s, n]) => <tr key={s}><td className="dim">{s}</td><td className="r white">{(n as number).toLocaleString()}</td></tr>)}</tbody></table></div></div>
      <div className="rp"><div className="h">BUCKET DISTRIBUTION</div><div className="c"><table className="kv-tbl"><tbody>
        {buckets.map(([b, n]) => <tr key={b}><td className="dim">{b}</td><td className="r white">{(n as number).toLocaleString()}</td></tr>)}</tbody></table></div></div>
      <div className="rp"><div className="h">SERIES ERRORS / DATA-QUALITY</div><div className="c">
        {Object.keys(errs).length ? <table className="kv-tbl"><tbody>{Object.entries(errs).map(([k, v]) => (
          <tr key={k}><td className="dim">{k}</td><td className="r">{String(v)}</td></tr>))}</tbody></table>
          : <div className="note green">no series errors this scan</div>}</div></div>
      <OpsDiag />
    </div></div>
  );
}

function SettingsMenu({ close }: { close: () => void }) {
  const t = useTerminal();
  const [big, setBig] = useState(document.body.classList.contains("big"));
  const s = t.settings;
  return (
    <div className="menu on" style={{ right: 6, top: 28 }} onMouseLeave={close}>
      <div className="mh">SETTINGS</div>
      <label><input type="checkbox" checked={t.showNet} onChange={(e) => t.setShowNet(e.target.checked)} />Show net of fees (est.)</label>
      <label><input type="checkbox" checked={big} onChange={(e) => { setBig(e.target.checked); document.body.classList.toggle("big", e.target.checked); }} />Larger text</label>
      <label><input type="checkbox" checked={s.showIds} onChange={(e) => t.setSetting("showIds", e.target.checked)} />Show IDs &amp; codes</label>
      <label><input type="checkbox" checked={s.resolutionCriteria} onChange={(e) => t.setSetting("resolutionCriteria", e.target.checked)} />Resolution criteria</label>
      <label><input type="checkbox" checked={s.longShort} onChange={(e) => t.setSetting("longShort", e.target.checked)} />Long / short wording</label>
      <div className="mi">Time zone
        <select value={s.tz} onChange={(e) => t.setSetting("tz", e.target.value)}>
          <option value="local">Local</option><option value="utc">UTC</option><option value="America/New_York">America/New_York</option>
        </select></div>
      <div className="mi">Auto-refresh
        <select value={s.autoRefresh} onChange={(e) => t.setSetting("autoRefresh", e.target.value)}>
          <option value="10s">on · 10s</option><option value="30s">on · 30s</option><option value="off">off</option>
        </select></div>
      <div className="mi" onClick={() => { t.setTheme(t.theme === "amber" ? "hc" : "amber"); }}>◐ Theme: {t.theme === "amber" ? "Amber" : "High-contrast"}</div>
    </div>
  );
}

function fmtTs(ts: number | undefined, tz: string): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  try {
    if (tz === "utc") return d.toLocaleString("en-GB", { timeZone: "UTC", hour12: false }).replace(",", "");
    if (tz && tz !== "local") return d.toLocaleString("en-GB", { timeZone: tz, hour12: false }).replace(",", "");
  } catch { /* fall through to local */ }
  return d.toLocaleString();
}
const mins = (s?: number) => (s == null ? "—" : Math.round(s / 60) + "m");

const BACKLOG_WINDOWS: [number, string][] = [[3600, "1 hour"], [10800, "3 hours"], [21600, "6 hours"], [43200, "12 hours"], [86400, "24 hours"]];

function BacklogSurface() {
  const t = useTerminal();
  const tz = t.settings.tz;
  const [recent, setRecent] = useState<BacklogItem[] | null>(null);
  const [durable, setDurable] = useState<BacklogInterval[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [windowS, setWindowS] = useState(3600);
  useEffect(() => {
    let a = true;
    setRecent(null);
    loadBacklog(windowS).then((x) => a && setRecent(x)).catch((e) => a && setErr(String(e)));
    loadBacklogEvents().then((x) => a && setDurable(x)).catch(() => {});
    return () => { a = false; };
  }, [windowS]);
  const winLabel = BACKLOG_WINDOWS.find(([s]) => s === windowS)?.[1] ?? "1 hour";
  return (
    <div className="view on"><div className="gridfill">
      <div className="rp"><div className="h">RECENTLY ACTIONABLE — {winLabel}
        <select className="in" style={{ marginLeft: "auto" }} aria-label="Backlog window" value={windowS} onChange={(e) => setWindowS(Number(e.target.value))}>
          {BACKLOG_WINDOWS.map(([s, l]) => <option key={s} value={s}>{l}</option>)}</select></div><div className="c">
        {err ? <div className="note red">{err}</div> : !recent ? <div className="note">loading…</div> : recent.length === 0 ? <div className="note">none in the window</div> :
          <table><thead><tr><th>Participant</th><th>Sport</th><th className="r">Became</th><th className="r">Left</th><th className="r">Lasted</th><th>Why left</th></tr></thead>
            <tbody>{recent.map((b, i) => <tr key={i}><td className="nm">{b.name}</td><td>{b.sport}</td><td className="r">{fmtTs(b.became_ts, tz)}</td><td className="r">{fmtTs(b.left_ts, tz)}</td><td className="r">{mins(b.duration_s)}</td><td className="dim">{b.reason_left || "—"}</td></tr>)}</tbody></table>}
      </div></div>
      <div className="rp"><div className="h">DURABLE BACKLOG — 7 days<span className="resb">v4</span></div><div className="c">
        {!durable ? <div className="note">loading…</div> : durable.length === 0 ? <div className="note">no intervals in the window</div> :
          <table><thead><tr><th>Category</th><th>Participant</th><th>Sport</th><th className="r">First seen</th><th className="r">Lasted</th><th className="r">Peak ROI</th><th>Last status</th></tr></thead>
            <tbody>{durable.map((b, i) => <tr key={i}><td>{b.category}</td><td className="nm">{b.name}</td><td>{b.sport}</td><td className="r">{fmtTs(b.first_seen_ts, tz)}</td><td className="r">{b.is_open ? "open" : mins(b.duration_s)}</td><td className="r">{b.peak_roi_pct != null ? b.peak_roi_pct.toFixed(1) + "%" : "—"}</td><td className="dim">{b.last_status || "—"}</td></tr>)}</tbody></table>}
      </div></div>
    </div></div>
  );
}

// Per-section default hints (mirror config.py, surfaced via meta.defaults) — shown so non-zero defaults
// that intentionally hide rows are visible + resettable.
const BAND_HINT: Record<string, string> = {
  bounded: "defaults: max-loss 5¢", nearmiss: "defaults: max-overpay 3¢",
  cheapno: "defaults: max-loss 15¢ · max-Buy-NO 15¢",
};

function SecBar() {
  const t = useTerminal();
  const b = t.band;
  const numI = (v: number, key: string, label: string, step = 1) => (
    <label>{label} <input type="number" min={0} step={step} value={v || 0}
      onChange={(e) => t.setBand({ [key]: Math.max(0, Number(e.target.value) || 0) })} /></label>
  );
  // The defaults hint + a "reset band" that drops the section's override back to the config default.
  const hint = (
    <span className="bandhint">{BAND_HINT[t.section]}{t.bandIsDefault ? " (active)" : null}
      {!t.bandIsDefault ? <a onClick={() => t.resetBand()}> · reset band</a> : null}</span>
  );
  if (t.section === "bounded") return (
    <div className="secbar"><span className="tag">BOUNDED-LOSS</span>
      {numI(b.maxLoss, "maxLoss", "Max loss ¢")}
      {numI(b.minRatio, "minRatio", "Min upside:risk", 0.1)}
      {numI(b.minChildOutright, "minChildOutright", "Min child-outright ¢")}
      {numI(b.maxSpreadOverChild, "maxSpreadOverChild", "Max spread÷child", 0.1)}{hint}</div>
  );
  if (t.section === "nearmiss") return (
    <div className="secbar"><span className="tag">NEAR-MISS</span>{numI(b.maxOverpay, "maxOverpay", "Max overpay ¢")}{hint}</div>
  );
  if (t.section === "cheapno") return (
    <div className="secbar"><span className="tag">CHEAP-NO</span>
      <label>Kind <select value={b.cheapKind} onChange={(e) => t.setBand({ cheapKind: e.target.value })}>
        <option value="all">all</option><option value="band">band</option><option value="outright">outright</option></select></label>
      {numI(b.maxLoss, "maxLoss", "Max loss ¢")}
      {numI(b.maxBuyNo, "maxBuyNo", "Max Buy-NO ¢")}
      <label className="chk"><input type="checkbox" checked={b.groupByLadder}
        onChange={(e) => t.setBand({ groupByLadder: e.target.checked })} />Group by ladder</label>{hint}</div>
  );
  return <div className="secbar" />;
}

function Shell() {
  const t = useTerminal();
  const m = t.meta;
  const [setOpen, setSetOpen] = useState(false);
  const alrt = t.count("exec", "act");   // ALRT badge = executable-now opportunities (the alert-worthy set)
  const newAct = t.opps.filter((o) => o.section === "act" && t.changeOf(o.id) === "new").length;
  const [bannerSnap, setBannerSnap] = useState<number | null>(null);   // dismissed-for snapshot id
  const showBanner = newAct > 0 && bannerSnap !== (m?.snapshot_id ?? null);
  const FK: [string, string, "opp" | "res" | "ops" | "alrt" | ""][] = [["OPP", "y", "opp"], ["RES", "g", "res"], ["OPS", "c", "ops"], ["ALRT", "r", "alrt"]];
  return (
    <>
      <div className="cmdline">
        <div className="fkeys">{FK.map(([l, c, s]) => (
          <span key={l} className={"fkey " + c} onClick={() => s && t.setSurface(s)}>{l}</span>
        ))}</div>
        <div className="cmdinput"><span className="pr">&gt;</span>
          <input aria-label="Open command palette" placeholder="SEARCH — functions · participants · lenses · layouts   (press / or Ctrl-K)" readOnly
                 onFocus={() => t.setPaletteOpen(true)} onClick={() => t.setPaletteOpen(true)} />
          <span className="kbd">Ctrl K</span><button className="go" onClick={() => t.setPaletteOpen(true)}>&lt;GO&gt;</button></div>
        <div className="clock">{fmtAge(m?.fetched_at ?? null)} · KALSHI</div>
      </div>
      <div className="scanbar" />
      <div className="statline">
        <span className="s"><b className={t.scanText ? "amber blink" : t.err ? "red" : "green"}>●</b> {t.scanText ?? `SNAPSHOT #${m?.snapshot_id ?? "—"} · ${fmtAge(m?.fetched_at ?? null)} ago`}</span>
        <span className="s">Opps <b>{(m?.n_total ?? 0).toLocaleString()}</b></span>
        <span className="s">Contracts <b>{(m?.contracts ?? 0).toLocaleString()}</b></span>
        <span className="s">Checks <b>{(m?.checks ?? 0).toLocaleString()}</b></span>
        <span className="s">Requests <b>{m?.requests ?? 0}</b></span>
        <span className="s">Sports <b>{t.sports.length}</b></span>
        <span className="s"><b className={m?.failed ? "amber" : "green"}>●</b> Failed <b>{m?.failed ?? 0}</b></span>
        <span className={"s" + (alrt ? " blink" : "")}><b className="red">●</b> ALRT <b>{alrt}</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS · fees est. only</span>
      </div>

      <div className="bar2">
        <div className={"stab" + (t.surface === "opp" ? " on" : "")} onClick={() => t.setSurface("opp")}><span className="c">1)</span>OPP</div>
        <div className={"stab" + (t.surface === "res" ? " on" : "")} onClick={() => t.setSurface("res")}><span className="c">2)</span>RES</div>
        <div className={"stab" + (t.surface === "ops" ? " on" : "")} onClick={() => t.setSurface("ops")}><span className="c">3)</span>OPS</div>
        <div className="right">
          <span className="dim" style={{ fontSize: 9 }}>LAYOUT</span>
          <select className="in" defaultValue="default" onChange={(e) => t.applyLayout(e.target.value)}>
            <option value="default">Default</option><option value="triage">Triage</option><option value="inspect">Inspect</option>
            <option value="research">Research</option><option value="blotterfull">Blotter full</option>
          </select>
          <button className="tbtn" onClick={() => t.setPanelsMenuOpen(true)}>＋ ADD ▾</button>
          <button className="tbtn" onClick={() => t.setPanelsMenuOpen(true)}>▦ ELEMENTS ▾</button>
          <span className="dim" style={{ fontSize: 9 }}>LENS</span>
          <div className="lens">{LENSES.map(([l, lbl, tip]) => (
            <button key={l} className={t.lens === l ? "on" : ""} title={tip} onClick={() => t.toggleLens(l)}>{lbl}</button>
          ))}</div>
          <div style={{ position: "relative" }}>
            <button className="tbtn" onClick={() => setSetOpen((v) => !v)}>⚙ SETTINGS ▾</button>
            {setOpen ? <SettingsMenu close={() => setSetOpen(false)} /> : null}
          </div>
          <button className="tbtn" aria-label="Scan now" title="Scan now (non-force)" onClick={() => t.runScan(false)}>▷ SCAN</button>
          <button className="tbtn force" aria-label="Force scan (bypass cooldown)" title="Advanced: bypass TTL/cooldown" onClick={() => t.runScan(true)}>⚡</button>
          <button className="tbtn" aria-label="Toggle theme" onClick={() => t.setTheme(t.theme === "amber" ? "hc" : "amber")}>◐</button>
        </div>
      </div>

      <div className="filt">
        <label>SPORT</label><MultiSelect label="Sport" options={t.sports} selected={t.filters.sports} onToggle={t.toggleSport} />
        <label>TOURNAMENT</label><MultiSelect label="Tournament" options={t.tourOptions} selected={t.filters.tours} onToggle={t.toggleTour} />
        <label>PARTICIPANT</label><input type="text" className="in" aria-label="Filter by participant" value={t.part} placeholder="contains…" onChange={(e) => t.setPart(e.target.value)} />
        <label>MIN SIZE</label><input type="number" className="in" aria-label="Minimum size" min={0} step={10} value={t.filters.minSize || 0}
               onChange={(e) => t.setMinSize(Math.max(0, Number(e.target.value) || 0))} />
        <label className="chk"><input type="checkbox" checked={t.filters.tradableOnly} onChange={(e) => t.setTradableOnly(e.target.checked)} />Tradable-only</label>
        <button className="tbtn" aria-label="Export current view as CSV" onClick={t.exportView}>⬇ CSV</button>
        <button className="tbtn" aria-label="Export filtered snapshot as ZIP" title="Export filtered snapshot (opportunities + evidence frames + manifest) as ZIP" onClick={t.exportZip}>⬇ ZIP</button>
        <span className="sp">{t.rows.length.toLocaleString()} shown</span><span className="clr" onClick={t.clearFilters}>clear</span>
      </div>
      <SecBar />
      {showBanner ? (
        <div className="newbanner" onClick={() => { t.setSurface("opp"); t.goSection("exec", "act"); }}>
          ▲ <b>{newAct}</b> newly actionable this scan
          <span className="x" onClick={(e) => { e.stopPropagation(); setBannerSnap(m?.snapshot_id ?? null); }}>✕</span>
        </div>
      ) : null}
      <div className="tiles">
        {TILES.map(([label, z, s, accent]) => (
          <div key={label} className={"tile" + (t.zone === z && t.section === s ? " on" : "")} onClick={() => { t.setSurface("opp"); t.goSection(z, s); }}>
            <div className="k">{label}</div>
            <div className={"v " + (TILE_ACCENT[accent] || "")}>{t.count(z, s).toLocaleString()}</div>
            <div className="s">{TILE_SUB[s]}</div>
          </div>
        ))}
      </div>

      <div className="view on" style={{ display: t.surface === "opp" ? "flex" : "none" }}><Workspace /></div>
      {t.surface === "res" ? <Surface id="res" /> : null}
      {t.surface === "ops" ? <Surface id="ops" /> : null}
      {t.surface === "alrt" ? <BacklogSurface /> : null}

      <div className="foot">
        <div><b className="amber">KALSHI STRUCTURED SCANNER</b> · real viewmodel rows · full column catalog · bounded-loss + cheap-NO splits · read-only over the live snapshot</div>
        <div className="help"><span><b>Ctrl K</b> palette</span><span><b>1-6</b> lens</span><span><b>J/K</b> rows</span><span><b>↵</b> open</span><span><b>drag splitters</b> resize</span><span><b>Ctrl/Shift-click</b> multi-select</span></div>
      </div>
      <Keys />
      <Palette />
    </>
  );
}

export default function App() {
  return <TerminalProvider><Shell /></TerminalProvider>;
}
