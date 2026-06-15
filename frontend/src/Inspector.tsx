/* Inspector — the DES trade card. Ported from ui-mockup-final-spa.html des().
 * Read-only, buy-only, gross. Display-only $1⇄$100 basis. Every field is the engine's; the "why ranked"
 * is a display narrative (lens-relative), not a model. */
import { useEffect, useState } from "react";
import type { FeedRow } from "./feed";
import { rankWhy } from "./lens";
import { detailKey, loadDetail, loadLadder, loadPayoff, type DetailBundle, type LadderData, type PayoffData } from "./detail";
import { PayoffChart, LadderChart } from "./Charts";

const ZB: Record<string, [string, string]> = {
  exec: ["bk-exec", "EXECUTABLE"], spec: ["bk-spec", "SPECULATIVE"], diag: ["bk-diag", "DIAGNOSTIC"],
};
const num = (v: unknown) => (typeof v === "number" && !isNaN(v) ? v : null);
const n1 = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
const cents = (c: unknown) => { const n = num(c); return n == null ? "—" : Math.round(n) + "¢"; };

export default function Inspector({ row, lens, snapshotId, showNet, longShort }:
  { row: FeedRow | null; lens: string; snapshotId: number | null; showNet: boolean; longShort?: boolean }) {
  const [basis, setBasis] = useState(1);
  if (!row) return <div className="empty">Click a blotter row to load the trade card — legs · economics · evidence.</div>;
  const cv = (c: unknown) => { const n = num(c); return n == null ? "—" : basis === 100 ? "$" + (n / 100).toFixed(2) : Math.round(n) + "¢"; };
  const z = ZB[row.zone] ?? ZB.diag;
  const isSpec = row.zone === "spec";
  const w = rankWhy(row);
  const legs = row.legs ?? [];
  const condPct = row.cond_child ?? row.cond;
  const hasCond = condPct != null;
  return (
    <div className="des">
      <div className="dtitle">
        <span className={"bk " + z[0]}>{z[1]}</span>
        <span className="t">{row.name}</span>
        <div className="basis">
          <button className={basis === 1 ? "on" : ""} onClick={() => setBasis(1)}>$1</button>
          <button className={basis === 100 ? "on" : ""} onClick={() => setBasis(100)}>$100</button>
        </div>
      </div>
      <div className="sub">{[row.sub || row.detail, row.sport, row.resolution_mode, row.scope].filter(Boolean).join(" · ")}</div>

      <div className="sect">BUY-ONLY PLAN — {row.nlegs ?? legs.length} LEG{(row.nlegs ?? legs.length) === 1 ? "" : "S"}</div>
      {legs.length ? legs.map((l, i) => {
        const yes = String(l.side || "").includes("yes");
        const lbl = longShort ? (yes ? "LONG" : "SHORT") : (yes ? "YES" : "NO");
        return (
          <div className="leg" key={i}>
            <span className={yes ? "y" : "n"}>{lbl}</span>
            <span className="l2">{l.c}</span>
            <span className="white">{l.p != null ? l.p + "¢" : "—"}</span>
            <span className="dim">×{l.sz ?? 0}</span>
            {l.u ? <a href={l.u} target="_blank" rel="noreferrer">↗</a> : null}
          </div>
        );
      }) : <div className="note">No leg detail.</div>}

      <div className="sect">ECONOMICS (PER UNIT)</div>
      <div className="kv">
        <span className="l">Cost</span><span className="v">{cv(row.cost)}</span>
        <span className="l">{isSpec ? "Max loss" : "Worst case"}</span><span className="v red">{cv(row.max_loss)}</span>
        <span className="l">{isSpec ? "Max profit" : "Best case"}</span><span className="v green">{cv(row.max_profit ?? row.profit)}</span>
        <span className="l">ROI</span><span className="v">{num(row.roi) == null ? "—" : (row.roi as number).toFixed(1) + "%"}</span>
        <span className="l">Max units</span><span className="v">{num(row.max_units ?? row.units) ?? "—"}</span>
        <span className="l">Quote</span><span className="v">{row.quote_health || "—"}</span>
        <span className="l">Tradable</span>
        <span className={"v " + (String(row.tradable || "").toLowerCase().startsWith("yes") ? "green" : "amber")}>{row.tradable || "—"}</span>
        {row.parent_over_maxloss != null
          ? <><span className="l">Ripeness (parent÷loss)</span><span className="v amber">{(row.parent_over_maxloss as number).toFixed(2)}</span></>
          : null}
        {showNet
          ? <><span className="l">Est. fees</span><span className="v">{cents(row.fees)}</span>
              <span className="l">Est. net edge</span><span className="v">{cents(row.net_edge)}</span></>
          : null}
      </div>

      {hasCond ? (
        <div className="note" style={{ marginTop: 6 }}>
          <b className="violet">Conditional (market-implied):</b> P(deeper │ reached) ≈ <span className="violet">{n1(condPct as number)}%</span>
          {" "}— the raw price ratio. See the <b>Participant Detail</b> tab for the full table. <span className="uncal">uncalibrated · not fair value</span>
        </div>
      ) : null}

      <div className="sect">WHY RANKED HERE · {(lens || "ENGINE ORDER").toUpperCase()}</div>
      <div className="why"><b>Promotes:</b><span className="green">{w.up}</span></div>
      <div className="why"><b>Demotes:</b><span className="dim">{w.down}</span></div>

      {row.rule || row.settlement_caveat
        ? <><div className="sect">SETTLEMENT / RULES</div>
            <div className="note">{row.rule ? <span className="uncal">{String(row.rule)} </span> : null}{row.settlement_caveat || row.caveat || ""}</div></>
        : null}
      {row.blk ? <div className="donoth"><b>BLOCKED:</b> {String(row.blk)}</div> : null}
      {isSpec ? <div className="donoth"><b>NOT AN EDGE:</b> bounded-loss speculation — can lose money; metrics gross/top-of-book, never feed actionability.</div> : null}

      <div className="sect">EVIDENCEPACK</div>
      <div className="kv">
        <span className="l">Snapshot</span><span className="v">#{snapshotId ?? "—"}</span>
        <span className="l">Status</span><span className="v">{row.status || "—"}</span>
        <span className="l">Opp id</span><span className="v">{row.id}</span>
        {row.url ? <><span className="l">Market</span><span className="v"><a href={String(row.url)} target="_blank" rel="noreferrer" className="cyan">open ↗</a></span></> : null}
      </div>
    </div>
  );
}

const gv = (r: Record<string, unknown>, k: string): string => {
  const v = r[k];
  if (v == null || v === "") return "—";
  return typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(1)) : String(v);
};

function Tbl({ rows, cols }: { rows: Record<string, unknown>[]; cols: [string, string][] }) {
  if (!rows?.length) return null;
  return (
    <table className="condtbl"><tbody>
      <tr>{cols.map(([k, l]) => <th key={k}>{l}</th>)}</tr>
      {rows.map((r, i) => <tr key={i}>{cols.map(([k]) => <td key={k}>{gv(r, k)}</td>)}</tr>)}
    </tbody></table>
  );
}

export function Detail({ row, showIds, showRules = true }: { row: FeedRow | null; showIds?: boolean; showRules?: boolean }) {
  const key = detailKey(row);
  const [bundle, setBundle] = useState<DetailBundle | null>(null);
  const [ladder, setLadder] = useState<LadderData | null>(null);
  const [payoff, setPayoff] = useState<PayoffData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setBundle(null); setLadder(null); setPayoff(null); setErr(null);
    if (!row) return;
    let alive = true;
    if (key) {
      loadDetail(key).then((b) => alive && setBundle(b)).catch((e) => alive && setErr(String(e)));
      loadLadder(key).then((l) => alive && setLadder(l)).catch(() => {});
    }
    loadPayoff(row.id).then((p) => alive && setPayoff(p)).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row?.id]);

  if (!row) return <div className="empty">Click a blotter row.</div>;
  const z = ZB[row.zone] ?? ZB.diag;
  const raw = row.cond ?? row.cond_child;
  const hasCond = row.cond != null || row.cond_child != null;
  return (
    <div className="des">
      <div className="dtitle"><span className={"bk " + z[0]}>{z[1]}</span><span className="t">{row.name}</span></div>
      <div className="sub">{[row.sub, row.sport].filter(Boolean).join(" · ")} · participant detail</div>

      {hasCond ? (
        <>
          <div className="sect">CONDITIONAL PROBABILITY <span className="uncal">UNCALIBRATED · DISPLAY-ONLY · NOT FAIR VALUE</span></div>
          <div className="note" style={{ marginBottom: 4 }}>
            The market-implied chance the <b>deeper</b> outcome happens <i>given</i> the <b>broader</b> one
            already did — just the raw price ratio (deeper ÷ broader), uncalibrated and not a fair-value model.
          </div>
          <table className="condtbl"><tbody>
            <tr><th>Stage</th><th>raw (price ratio)</th></tr>
            <tr><td>Broader: {row.pnode || row.detail || "parent"}</td><td>{row.pbid != null ? row.pbid + "¢" : "—"}</td></tr>
            <tr><td>P(deeper │ broader reached)</td><td className="violet">{row.cond_child != null ? n1(row.cond_child) + "%" : (raw != null ? raw + "%" : "—")}</td></tr>
            <tr><td>P(success │ broader reached)</td><td>{row.cond_success != null ? n1(row.cond_success) + "%" : "—"}</td></tr>
          </tbody></table>
          <div className="formula">P(deeper│reached) = price(deeper) ÷ price(parent){row.cask != null && row.pbid ? ` = ${row.cask}/${row.pbid} = ${row.cond}%` : ""}</div>
        </>
      ) : <div className="note" style={{ marginTop: 6 }}>No parent/child containment node on this row (e.g. a dutch-book field/game). Conditional probability applies to ladder (containment) rows only.</div>}

      {!key ? (
        <div className="note" style={{ marginTop: 8 }}>No single-participant anchor on this row — drill-down tables (chain / spreads / contracts) apply to ladder rows with a participant key + tournament.</div>
      ) : err ? (
        <div className="note red" style={{ marginTop: 8 }}>detail unavailable: {err}</div>
      ) : !bundle ? (
        <div className="note" style={{ marginTop: 8 }}>loading participant detail…</div>
      ) : (
        <>
          {bundle.indicators.length ? (
            <><div className="sect">DERIVED MARKET-IMPLIED INDICATORS <span className="uncal">DISPLAY-ONLY BOUND</span></div>
              {bundle.indicators.map((ind, i) => (
                <div className="note" key={i}>{gv(ind, "label")} {gv(ind, "comparator")} {gv(ind, "value_pct")}{ind.value_pct != null ? "%" : ""} <span className="dim">{gv(ind, "note")}</span></div>
              ))}</>
          ) : null}

          {bundle.chain.length ? (
            <><div className="sect">CONTAINMENT CHAIN (BROAD → DEEP)</div>
              <Tbl rows={bundle.chain} cols={[["layer", "Layer"], ["source", "Source"], ["display_pct", "Disp %"], ["bid_pct", "Bid %"], ["ask_pct", "Ask %"], ["quote", "Quote"]]} />
              <LadderChart data={ladder} /></>
          ) : null}

          {payoff && payoff.scenarios.length ? (
            <><div className="sect">PER-UNIT PAYOFF BY SCENARIO <span className="uncal">GROSS</span></div><PayoffChart data={payoff} /></>
          ) : null}

          {bundle.spreads.length ? (
            <><div className="sect">RAW STAGE-LADDER SPREADS</div>
              <Tbl rows={bundle.spreads} cols={[["from_layer", "From"], ["to_layer", "To"], ["spread_pct", "Spread pp"], ["spread_cents", "Spread ¢"], ["quote", "Quote"]]} /></>
          ) : null}

          {bundle.expected.length ? (
            <><div className="sect">EXPECTED VS FOUND</div>
              <Tbl rows={bundle.expected} cols={[["layer", "Layer"], ["found", "Found"], ["source", "Source"]]} /></>
          ) : null}

          {bundle.contracts.length ? (
            <><div className="sect">ALL CONTRACTS ({bundle.contracts.length})</div>
              <Tbl rows={bundle.contracts} cols={[["contract", "Contract"], ["stage", "Stage"], ["display_pct", "Disp %"], ["bid_pct", "Bid %"], ["ask_pct", "Ask %"], ["quote", "Quote"], ["status", "Status"]]} /></>
          ) : null}

          {showRules && bundle.rules.length ? (
            <><div className="sect">RESOLUTION CRITERIA (SETTLEMENT RULES)</div>
              {bundle.rules.map((r, i) => (
                <div className="note" key={i}><b className="white">{r.contract}</b> — {r.text}</div>
              ))}</>
          ) : null}

          {showIds && bundle.raw_fields.length ? (
            <><div className="sect">RAW FIELDS · IDS &amp; CODES</div>
              <Tbl rows={bundle.raw_fields} cols={[["series", "Series"], ["tournament", "Tournament"], ["tournament_source", "T-src"], ["player_key", "Player key"], ["mapping_confidence", "Map conf"]]} /></>
          ) : null}
        </>
      )}
    </div>
  );
}

export function Formulas({ row }: { row: FeedRow | null }) {
  if (!row) return <div className="empty">Click a blotter row.</div>;
  const z = ZB[row.zone] ?? ZB.diag;
  return (
    <div className="des">
      <div className="dtitle"><span className={"bk " + z[0]}>{z[1]}</span><span className="t">Formulas — {row.name}</span></div>
      <div className="note">Each metric with its computation, real numbers plugged in (single-sourced from glossary.py in the engine).</div>
      <div className="sect">COST / ROI</div>
      <div className="formula">cost = Σ leg ask = {cents(row.cost)} · ROI = max profit ÷ cost = {num(row.roi) == null ? "—" : (row.roi as number).toFixed(1) + "%"}</div>
      <div className="sect">MAX LOSS / MAX PROFIT</div>
      <div className="formula">max profit = {cents(row.max_profit ?? row.profit)} · max loss = {cents(row.max_loss)} · upside:risk = {num(row.ratio) == null ? "—" : n1(row.ratio as number)}</div>
      <div className="sect">RIPENESS (parent ÷ max loss)</div>
      <div className="formula">parent_display ÷ (cost − 100) = {row.parent_over_maxloss != null ? (row.parent_over_maxloss as number).toFixed(2) : "n/a"} — in-the-money chance per ¢ at risk</div>
      <div className="sect">CONDITIONAL <span className="uncal">UNCALIBRATED</span></div>
      <div className="formula">P(deeper│reached) = price(deeper)/price(parent) = {row.cond != null ? `${row.cask}/${row.pbid} = ${row.cond}%` : "n/a"}</div>
      <div className="sect">FEES (estimate, display-only)</div>
      <div className="formula">kalshi taker fee ≈ 0.07·c·p·(1−p) → fees {cents(row.fees)} · net edge {cents(row.net_edge)} · never affects ranking</div>
      <div className="note" style={{ marginTop: 6 }}>All gross & top-of-book; fees, collateral, full-depth execution are documented limits.</div>
    </div>
  );
}
