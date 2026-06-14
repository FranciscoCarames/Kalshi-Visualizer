import { TerminalProvider, useTerminal } from "./context";
import { TILES, sectionCount } from "./feed";
import { LENSES } from "./lens";
import Workspace from "./Workspace";
import { ResSurface, OpsSurface } from "./Surfaces";
import Keys from "./Keys";
import Palette from "./Palette";

const TILE_SUB: Record<string, string> = {
  act: "executable now", rev: "settlement-dep", blk: "not fillable", bounded: "can lose money",
  nearmiss: "watchlist", qual: "WC setups", cheapno: "NO fades", diag: "diagnostic",
};

function fmtAge(fetchedAt: string | null): string {
  if (!fetchedAt) return "—";
  const t = Date.parse(fetchedAt.replace(" UTC", "Z"));
  return isNaN(t) ? "—" : Math.max(0, Math.round((Date.now() - t) / 1000)) + "s";
}

function Shell() {
  const t = useTerminal();
  const m = t.meta;
  return (
    <div className="tp-app">
      <div className="tp-cmd">
        <div className="fk"><span>OPP</span><span>RES</span><span>OPS</span><span>ALRT</span></div>
        <div className="ci"><span className="amber">&gt;</span>
          <input placeholder="SEARCH — functions · participants · lenses · layouts   (Ctrl-K or /)" readOnly
                 onFocus={() => t.setPaletteOpen(true)} onClick={() => t.setPaletteOpen(true)} />
          <span className="kbd">Ctrl K</span>
          <button className="go" onClick={() => t.setPaletteOpen(true)}>&lt;GO&gt;</button></div>
        <div className="clock">{fmtAge(m?.fetched_at ?? null)} · KALSHI</div>
      </div>

      <div className="tp-stat">
        <span className="s"><b className={t.err ? "red" : "green"}>●</b> SNAPSHOT #{m?.snapshot_id ?? "—"} · {fmtAge(m?.fetched_at ?? null)} ago</span>
        <span className="s">Opps <b>{(m?.n_total ?? 0).toLocaleString()}</b></span>
        <span className="s">Contracts <b>{(m?.contracts ?? 0).toLocaleString()}</b></span>
        <span className="s">Checks <b>{(m?.checks ?? 0).toLocaleString()}</b></span>
        <span className="s">Requests <b>{m?.requests ?? 0}</b></span>
        <span className="s">Sports <b>{t.sports.length}</b></span>
        <span className="s"><b className={m?.failed ? "amber" : "green"}>●</b> Failed <b>{m?.failed ?? 0}</b></span>
        <span className="s discl">GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>
      </div>

      <div className="tp-bar2">
        <div className={"tab" + (t.surface === "opp" ? " on" : "")} onClick={() => t.setSurface("opp")}><span className="c">1)</span>OPP</div>
        <div className={"tab" + (t.surface === "res" ? " on" : "")} onClick={() => t.setSurface("res")}><span className="c">2)</span>RES</div>
        <div className={"tab" + (t.surface === "ops" ? " on" : "")} onClick={() => t.setSurface("ops")}><span className="c">3)</span>OPS</div>
        <div className="right">
          <span className="dim" style={{ fontSize: 9 }}>LENS</span>
          <div className="tp-lens">
            {LENSES.map(([l, lbl, tip]) => (
              <button key={l} className={t.lens === l ? "on" : ""} title={tip} onClick={() => t.toggleLens(l)}>{lbl}</button>
            ))}
          </div>
          <span className="dim" style={{ fontSize: 9 }}>{t.lens ? "sort lens" : "engine order"}</span>
          <button className="tp-tb" title="Toggle theme (amber / high-contrast)"
                  onClick={() => t.setTheme(t.theme === "amber" ? "hc" : "amber")}>◐</button>
        </div>
      </div>

      <div className="tp-tiles">
        {TILES.map(([label, z, s, accent]) => (
          <button key={label} className={"tp-tile" + (t.zone === z && t.section === s ? " on" : "")} onClick={() => t.goSection(z, s)}>
            <div className="k">{label}</div>
            <div className={"v " + accent}>{sectionCount(m, z, s).toLocaleString()}</div>
            <div className="s">{TILE_SUB[s]}</div>
          </button>
        ))}
      </div>

      <div className="tp-filt">
        <label>SPORT</label>
        <select value={t.sportSel} onChange={(e) => t.setSportSel(e.target.value)}>
          <option value="">All</option>{t.sports.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label>PARTICIPANT</label>
        <input value={t.part} placeholder="contains…" onChange={(e) => t.setPart(e.target.value)} />
        <label className="chk"><input type="checkbox" checked={t.showNet} onChange={(e) => t.setShowNet(e.target.checked)} />Net of fees (est.)</label>
        <span className="clr" onClick={() => { t.setSportSel(""); t.setPart(""); }}>clear</span>
      </div>

      {/* OPP keeps the Dockview workspace mounted (display-toggled) so its layout survives surface switches. */}
      <div style={{ flex: 1, minHeight: 0, flexDirection: "column", display: t.surface === "opp" ? "flex" : "none" }}><Workspace /></div>
      {t.surface === "res" ? <ResSurface /> : null}
      {t.surface === "ops" ? <OpsSurface /> : null}

      <div className="tp-ft">
        <b>TERMINAL PRO · Phase C</b>
        <span className="dim">OPP / RES / OPS surfaces · inspector tabs (trade card · participant detail · formulas) · net-of-fees toggle (display-only)</span>
      </div>
      <Keys />
      <Palette />
    </div>
  );
}

export default function App() {
  return <TerminalProvider><Shell /></TerminalProvider>;
}
