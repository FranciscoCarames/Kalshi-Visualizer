/* App shell — DOM + classes ported VERBATIM from ui-mockup-final-spa.html so the chrome is pixel-exact.
 * React supplies the live data/state; the look is the mockup's. */
import { useState } from "react";
import { TerminalProvider, useTerminal } from "./context";
import { TILES } from "./feed";
import { LENSES } from "./lens";
import Workspace from "./Workspace";
import Keys from "./Keys";
import Palette from "./Palette";
import MultiSelect from "./MultiSelect";

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
    </div></div>
  );
}

function SettingsMenu({ close }: { close: () => void }) {
  const t = useTerminal();
  const [big, setBig] = useState(document.body.classList.contains("big"));
  return (
    <div className="menu on" style={{ right: 6, top: 28 }} onMouseLeave={close}>
      <div className="mh">SETTINGS</div>
      <label><input type="checkbox" checked={t.showNet} onChange={(e) => t.setShowNet(e.target.checked)} />Show net of fees (est.)</label>
      <label><input type="checkbox" checked={big} onChange={(e) => { setBig(e.target.checked); document.body.classList.toggle("big", e.target.checked); }} />Larger text</label>
      <div className="mi" onClick={() => { t.setTheme(t.theme === "amber" ? "hc" : "amber"); }}>◐ Theme: {t.theme === "amber" ? "Amber" : "High-contrast"}</div>
    </div>
  );
}

function Shell() {
  const t = useTerminal();
  const m = t.meta;
  const [setOpen, setSetOpen] = useState(false);
  const alrt = t.count("exec", "act");   // ALRT badge = executable-now opportunities (the alert-worthy set)
  const FK: [string, string, "opp" | "res" | "ops" | ""][] = [["OPP", "y", "opp"], ["RES", "g", "res"], ["OPS", "c", "ops"], ["ALRT", "r", ""]];
  return (
    <>
      <div className="cmdline">
        <div className="fkeys">{FK.map(([l, c, s]) => (
          <span key={l} className={"fkey " + c} onClick={() => s && t.setSurface(s)}>{l}</span>
        ))}</div>
        <div className="cmdinput"><span className="pr">&gt;</span>
          <input placeholder="SEARCH — functions · participants · lenses · layouts   (press / or Ctrl-K)" readOnly
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
          <button className="tbtn" title="Scan now (non-force)" onClick={() => t.runScan(false)}>▷ SCAN</button>
          <button className="tbtn force" title="Advanced: bypass TTL/cooldown" onClick={() => t.runScan(true)}>⚡</button>
          <button className="tbtn" onClick={() => t.setTheme(t.theme === "amber" ? "hc" : "amber")}>◐</button>
        </div>
      </div>

      <div className="filt">
        <label>SPORT</label><MultiSelect label="Sport" options={t.sports} selected={t.filters.sports} onToggle={t.toggleSport} />
        <label>TOURNAMENT</label><MultiSelect label="Tournament" options={t.tourOptions} selected={t.filters.tours} onToggle={t.toggleTour} />
        <label>PARTICIPANT</label><input type="text" className="in" value={t.part} placeholder="contains…" onChange={(e) => t.setPart(e.target.value)} />
        <label>MIN SIZE</label><input type="number" className="in" min={0} step={10} value={t.filters.minSize || 0}
               onChange={(e) => t.setMinSize(Math.max(0, Number(e.target.value) || 0))} />
        <label className="chk"><input type="checkbox" checked={t.filters.tradableOnly} onChange={(e) => t.setTradableOnly(e.target.checked)} />Tradable-only</label>
        <button className="tbtn" onClick={t.exportView}>⬇ CSV</button>
        <span className="sp">{t.rows.length.toLocaleString()} shown</span><span className="clr" onClick={t.clearFilters}>clear</span>
      </div>
      <div className="secbar" />
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

      <div className="foot">
        <div><b className="amber">TERMINAL PRO</b> · real viewmodel rows · full column catalog · bounded-loss + cheap-NO splits · read-only over the live snapshot</div>
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
