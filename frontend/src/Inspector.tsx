/* Inspector — the DES trade card. Ported from ui-mockup-final-spa.html des().
 * Read-only, buy-only, gross. Display-only $1⇄$100 basis. Every field is the engine's; the "why ranked"
 * is a display narrative (lens-relative), not a model. */
import { useEffect, useState } from "react";
import type { FeedRow } from "./feed";
import { rankWhy } from "./lens";
import { centsToDollars, qualityOf } from "./columns";
import { detailKey, loadDetail, loadLadder, loadPayoff, type DetailBundle, type LadderData, type PayoffData } from "./detail";
import { PayoffChart, LadderChart } from "./Charts";

const ZB: Record<string, [string, string]> = {
  exec: ["bk-exec", "EXECUTABLE"], spec: ["bk-spec", "SPECULATIVE"], diag: ["bk-diag", "DIAGNOSTIC"],
};
const num = (v: unknown) => (typeof v === "number" && !isNaN(v) ? v : null);
const n1 = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
const cents = (c: unknown) => { const n = num(c); return n == null ? "—" : Math.round(n) + "¢"; };
// Only render a URL from feed/market data as a link if it is a real http(s) URL — never a `javascript:`/
// `data:` scheme that would execute in the authenticated origin on click. Returns the URL or null.
const safeHref = (u: unknown): string | null => {
  if (typeof u !== "string" || !u) return null;
  try { return ["http:", "https:"].includes(new URL(u).protocol) ? u : null; } catch { return null; }
};

// Fee estimate as TWO EXECUTION SCENARIOS (display-only, never ranks). Taker (immediate-fill) is primary
// and drives the breakeven + net-neg badge; maker (resting-order) is shown separately and caveated, since
// fills/queue/edge-decay are not modeled. A flat/unknown leg marks a scenario incomplete (never faked).
function FeeScenarios({ row }: { row: FeedRow }) {
  const legs = row.fee_legs ?? [];
  const multiLeg = legs.length > 2;
  const srcChip: Record<string, string> = {
    event_override: "event override", series: "series-level", mixed: "mixed (event + series)",
    fallback: "general-rate fallback (no live fee data)", flat: "flat fee — not estimated",
    unknown: "unknown fee type — incomplete",
  };
  // Fee totals + net edge shown in DOLLARS (consistent with Cost/Max-profit), reusing the shared
  // cents->$ rule. Breakeven + per-leg fees stay in ¢ (per-unit price quantities, like "edge").
  const dol = (c: number | null | undefined) => { const n = num(c); return n == null ? "—" : centsToDollars(n); };
  const takerLine = row.taker_complete === false
    ? <span className="v amber">incomplete — flat/unknown leg</span>
    : <span className="v">{dol(row.fees_taker ?? row.fees)}</span>;
  const makerLine = row.maker_complete === false
    ? <span className="v amber">incomplete — flat/unknown leg</span>
    : <span className="v">{dol(row.fees_maker)}</span>;
  return (
    <>
      <div className="sect">FEES — IMMEDIATE-FILL (TAKER)</div>
      <div className="kv">
        <span className="l">Est. fees (whole order)</span>{takerLine}
        <span className="l">Est. net edge / unit</span><span className="v">{row.taker_complete === false ? "—" : dol(row.net_edge)}</span>
        <span className="l">Breakeven gross gap</span>
        <span className="v">{row.fee_breakeven == null ? "—" : cents(row.fee_breakeven) + (row.fee_breakeven_approx ? " (approx)" : "")}</span>
      </div>
      <div className="note dim" style={{ marginTop: 2 }}>
        Fee total is for the <b>whole order — every leg at the full fillable size</b>, not per contract. Net edge &amp;
        breakeven are per unit. Immediate-fill estimate — cross visible top-of-book now.</div>

      <div className="sect">FEES — RESTING-ORDER (MAKER)</div>
      <div className="kv">
        <span className="l">Est. fees (whole order)</span>{makerLine}
        <span className="l">Est. net edge / unit</span><span className="v">{row.maker_complete === false ? "—" : dol(row.net_edge_maker)}</span>
      </div>
      <div className="note dim" style={{ marginTop: 2 }}>
        Resting-order scenario: assumes posted orders later fill; queue position, fill probability, and edge decay are not modeled.
        {multiLeg ? " All-maker assumes every leg rests and fills before prices move." : null} Mixed execution (some legs taker, some maker) is not modeled.
      </div>

      {legs.length ? <>
        <div className="sect">PER-LEG FEES</div>
        {legs.map((l, i) => (
          <div className="leg" key={i}>
            <span className={String(l.side || "").includes("yes") ? "y" : "n"}>{String(l.side || "").includes("yes") ? "YES" : "NO"}</span>
            <span className="l2">{l.series_ticker || "—"}</span>
            <span className="white">{l.price_c != null ? l.price_c + "¢" : "—"}</span>
            <span className="dim">{l.fee_type || "?"}×{l.fee_multiplier ?? "?"}</span>
            <span className="dim">t {cents(l.fee_taker_c)} · m {cents(l.fee_maker_c)}</span>
            <span className="dim">{l.fee_type_source || "?"}</span>
          </div>
        ))}
      </> : null}
      <div className="note" style={{ marginTop: 4 }}>
        <span className="dim">Source: {srcChip[row.fee_source ?? "fallback"] ?? row.fee_source}. </span>
        Conservative pre-trade estimate; realized fee depends on fill path, price precision, quantity,
        rounding fee, rebate, and the fee accumulator. Still gross of order-book depth. <span className="uncal">never ranks</span>
      </div>
    </>
  );
}

export default function Inspector({ row, lens, snapshotId, showNet, longShort }:
  { row: FeedRow | null; lens: string; snapshotId: number | null; showNet: boolean; longShort?: boolean }) {
  const [basis, setBasis] = useState(1);
  if (!row) return <div className="empty">Click a scanner row to load the trade card — legs · economics · evidence.</div>;
  const cv = (c: unknown) => { const n = num(c); return n == null ? "—" : basis === 100 ? "$" + (n / 100).toFixed(2) : Math.round(n) + "¢"; };
  const z = ZB[row.zone] ?? ZB.diag;
  const isSpec = row.zone === "spec";
  const isDiag = row.zone === "diag";   // diagnostic rows are NOT tradable — no buy plan / economics card
  const w = rankWhy(row);
  const legs = row.legs ?? [];
  const condPct = row.cond_child;                 // display-basis P(deeper│reached); firm shown in Detail
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

      {isDiag ? (
        <div className="note" style={{ marginTop: 6 }}>
          <b>Diagnostic row — not a tradable opportunity.</b> This row is surfaced for review/data-quality
          only, so it has no buy-only plan or economics. See the evidence and Participant Detail below.
        </div>
      ) : (<>
      <div className="sect">BUY-ONLY PLAN — {row.nlegs ?? legs.length} LEG{(row.nlegs ?? legs.length) === 1 ? "" : "S"}</div>
      {legs.length ? legs.map((l, i) => {
        const href = safeHref(l.u);
        // Book-only pseudo-leg (bo): a reference market the engine attached for the depth panel — NOT a
        // buy instruction (no side/price). Render it as a reference row, never as a blank "NO @ —" leg
        // (e.g. the exact-order bundle's qualifier comparator).
        if (l.bo) return (
          <div className="leg" key={i}>
            <span className="dim">BOOK</span>
            <span className="l2">{l.c || l.tk || "reference market"}</span>
            <span className="dim">reference only</span>
            <span className="dim" />
            {href ? <a href={href} target="_blank" rel="noreferrer">↗</a> : null}
          </div>
        );
        const yes = String(l.side || "").includes("yes");
        const lbl = longShort ? (yes ? "LONG" : "SHORT") : (yes ? "YES" : "NO");
        return (
          <div className="leg" key={i}>
            <span className={yes ? "y" : "n"}>{lbl}</span>
            <span className="l2">{l.c}</span>
            {l.tk ? <span className="dim" style={{ fontFamily: "monospace", fontSize: "0.85em" }} title="market ticker">{l.tk}</span> : null}
            <span className="white">{l.p != null ? l.p + "¢" : "—"}</span>
            <span className="dim">×{l.sz ?? 0}</span>
            {href ? <a href={href} target="_blank" rel="noreferrer">↗</a> : null}
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
        {row.section === "bounded" ? (() => {
          // Single uncalibrated setup-quality diagnostic = ripeness × conditional chance. Shown ALONGSIDE the
          // raw ripeness (above) and the conditional note (below) — never replacing them. "Insufficient data"
          // when an input is missing (≠ Low).
          const q = qualityOf(row);
          const cls = q.tier === "High" ? "green" : q.tier === "Med" ? "amber" : "dim";
          return <><span className="l">Setup quality</span>
            <span className={"v " + cls} title="uncalibrated diagnostic: ripeness × P(deeper│reached). Not fair value; never executable ranking.">
              {q.tier === "n/a" ? "Insufficient data" : `${q.label}${q.score != null ? ` (${q.score.toFixed(2)})` : ""}`}</span></>;
        })() : null}
      </div>

      {showNet ? <FeeScenarios row={row} /> : null}
      </>)}

      {hasCond ? (
        <div className="note" style={{ marginTop: 6 }}>
          <b className="violet">Conditional (market-implied · display basis):</b> P(deeper │ reached) ≈ <span className="violet">{n1(condPct as number)}%</span>
          {row.cond_child_firm != null ? <> · bid/ask <span className="violet">{n1(row.cond_child_firm)}%</span></> : null}
          {" "}— price ratio. See the <b>Participant Detail</b> tab for the full table. <span className="uncal">uncalibrated · not fair value</span>
        </div>
      ) : (row.pnode || row.cnode) ? (
        <div className="note" style={{ marginTop: 6 }}>
          <b className="violet">Conditional</b> unavailable — {row.cond_reason || row.cond_reason_firm || "missing quote"}.
          {" "}<span className="uncal">needs a price on both legs</span>
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
        {safeHref(row.url) ? <><span className="l">Market</span><span className="v"><a href={safeHref(row.url)!} target="_blank" rel="noreferrer" className="cyan">open ↗</a></span></> : null}
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

// Single-sourced so the conditional displays don't each repeat the long warning (owner asked to de-noise it).
const CONDITIONAL_DISCLAIMER =
  "Market-implied display ratios — uncalibrated, gross, top-of-book; not a fair-value model and never an executable edge.";

/** One readable row per ladder rung (broad→deep) for the LADDER PROBABILITY table: the absolute chance of
 * reaching the rung (its display price) and the conditional chance GIVEN the prior rung (price ratio). The
 * conditional is suppressed — with a visible reason, never silently — when a price is missing or the ladder
 * inverts (deeper priced above broader), so a ratio is never shown above 100%. Pure + display-only. */
export interface CondRow { stage: string; reaching: number | null; given: number | null; quote: string; note: string; }
export function condRungRows(chain: Record<string, unknown>[]): CondRow[] {
  const out: CondRow[] = [];
  let prev: number | null = null;
  for (let i = 0; i < (chain?.length ?? 0); i++) {
    const c = chain[i];
    const reaching = typeof c.display_pct === "number" ? c.display_pct : null;
    let given: number | null = null;
    let note = "";
    if (i === 0) note = "broadest";
    else if (reaching == null || prev == null || prev <= 0) note = "no quote";
    else if (reaching > prev) note = "inverted — suppressed";   // deeper above broader = display inconsistency
    else given = (reaching / prev) * 100;
    out.push({ stage: String(c.layer ?? ""), reaching, given, quote: String(c.quote ?? ""), note });
    prev = reaching;
  }
  return out;
}

export function Detail({ row, showIds, showRules = true }: { row: FeedRow | null; showIds?: boolean; showRules?: boolean }) {
  const baseKey = detailKey(row);   // the row's own single-participant anchor (sport+player_key+tournament)
  // Distinct per-leg participants (field / multi-participant rows like a 2-way game or a winner field) →
  // a participant chooser. Skips book-only legs and legs without a participant UUID.
  const legParts: { pk: string; label: string }[] = [];
  const _seen = new Set<string>();
  for (const l of (row?.legs ?? [])) {
    const pk = l.pk;
    // Real participants only: skip book-only legs, legs without a pk, and the synthetic Tie/draw leg
    // (pk "tie::…") — a tie has no participant ladder, so it's never a chooser option.
    if (!pk || l.bo || pk.startsWith("tie::") || _seen.has(pk)) continue;
    _seen.add(pk); legParts.push({ pk, label: l.c || pk });
  }
  const [pickPk, setPickPk] = useState<string | null>(null);
  // A chooser is offered only when the row exposes sport_key + tournament (needed to form a detail key for
  // a picked side). The picked participant overrides the row's own anchor; `validPick` guards against a
  // stale pick carried across a row change.
  const canPick = !!(row?.sport_key && row?.tournament) && legParts.length > 0;
  const validPick = pickPk && legParts.some((p) => p.pk === pickPk) ? pickPk : null;
  const pickedKey = canPick && validPick
    ? { sport: String(row!.sport_key), player_key: validPick, tournament: String(row!.tournament) } : null;
  const key = pickedKey ?? baseKey;
  const keyStr = key ? `${key.sport}|${key.player_key}|${key.tournament}` : "";
  const [bundle, setBundle] = useState<DetailBundle | null>(null);
  const [ladder, setLadder] = useState<LadderData | null>(null);
  const [payoff, setPayoff] = useState<PayoffData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPickPk(null); }, [row?.id]);   // reset the chosen side when the row changes
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
  }, [row?.id, keyStr]);

  if (!row) return <div className="empty">Click a scanner row.</div>;
  const z = ZB[row.zone] ?? ZB.diag;
  const hasCond = row.cond_child != null || row.cond_child_firm != null;
  // PD-fix: only a participant with ≥2 PRICED rungs is a real containment ladder. A match/game/single-
  // contract row has 0-1 priced rungs, so the ladder/chain/spreads/expected sections would render empty
  // templates (the "Bryce vs Suarez" confusion). Below we gate those on hasLadder and otherwise show just
  // a clear note + ALL CONTRACTS + resolution (the actual evidence).
  const hasLadder = !!bundle && condRungRows(bundle.chain).filter((r) => r.reaching != null).length >= 2;
  return (
    <div className="des">
      <div className="dtitle"><span className={"bk " + z[0]}>{z[1]}</span><span className="t">{row.name}</span></div>
      <div className="sub">{[row.sub, row.sport].filter(Boolean).join(" · ")} · participant detail</div>

      {canPick ? (
        <div className="note pchooser" style={{ marginTop: 6 }}>
          <b>Participant:</b>{" "}
          {legParts.map((p) => (
            <button key={p.pk} className={(validPick ?? baseKey?.player_key) === p.pk ? "on" : ""} onClick={() => setPickPk(p.pk)}>{p.label}</button>
          ))}
          {" "}<span className="uncal">pick a side to view its ladder</span>
        </div>
      ) : null}

      {hasCond ? (
        <>
          <div className="sect">CONDITIONAL PROBABILITY <span className="uncal">UNCALIBRATED · DISPLAY-ONLY · NOT FAIR VALUE</span></div>
          <div className="note" style={{ marginBottom: 4 }}>
            The market-implied chance the <b>deeper</b> outcome happens <i>given</i> the <b>broader</b> one
            already did — the price ratio (deeper ÷ broader) on two bases: <b>display</b> (the dashboard
            price — midpoint when the spread is reasonable, else last trade) and <b>bid/ask</b> (executable
            quotes). Uncalibrated, not a fair-value model; the bid/ask figure is a diagnostic, not an
            executable edge.
          </div>
          <table className="condtbl"><tbody>
            <tr><th>Stage</th><th>display</th><th>bid/ask</th></tr>
            <tr><td>P(deeper │ broader reached)</td>
              <td className="violet">{row.cond_child != null ? n1(row.cond_child) + "%" : "—"}</td>
              <td>{row.cond_child_firm != null ? n1(row.cond_child_firm) + "%" : "—"}</td></tr>
            <tr><td>P(success │ broader reached)</td>
              <td>{row.cond_success != null ? n1(row.cond_success) + "%" : "—"}</td>
              <td>{row.cond_success_firm != null ? n1(row.cond_success_firm) + "%" : "—"}</td></tr>
          </tbody></table>
          <div className="formula">display: P(deeper│reached) = price(deeper) ÷ price(parent){row.cdisp != null && row.pdisp ? ` = ${row.cdisp}/${row.pdisp} = ${n1(row.cond_child as number)}%` : ""}</div>
          {row.cask != null && row.pbid ? <div className="formula">bid/ask: child ask ÷ parent bid = {row.cask}/{row.pbid}{row.cond_child_firm != null ? ` = ${n1(row.cond_child_firm)}%` : ""}</div> : null}
          {row.cond_child == null && row.cond_reason
            ? <div className="note" style={{ marginTop: 4 }}>Display conditional unavailable — {row.cond_reason}.</div> : null}
        </>
      ) : (row.pnode || row.cnode) ? (
        <>
          <div className="sect">CONDITIONAL PROBABILITY <span className="uncal">UNCALIBRATED · DISPLAY-ONLY</span></div>
          <div className="note" style={{ marginTop: 6 }}>
            Conditional unavailable — {row.cond_reason || row.cond_reason_firm || "missing quote"}.
            {row.pnode && row.cnode ? <> ({String(row.cnode)} ÷ {String(row.pnode)})</> : null} A price is needed
            on both the broader and deeper legs to imply P(deeper │ reached).
          </div>
        </>
      ) : key ? (
        <div className="note" style={{ marginTop: 6 }}>Conditional probability needs a comparable broader+deeper pair, which this row doesn't have.</div>
      ) : <div className="note" style={{ marginTop: 6 }}>No participant anchor on this row (e.g. a 2-way dutch-book game). {canPick ? "Pick a participant above to view its ladder." : "Participant detail applies to ladder (containment) rows."}</div>}

      {!key ? (
        <div className="note" style={{ marginTop: 8 }}>{canPick
          ? "Pick a participant above to load its chain / spreads / contracts."
          : "No single-participant anchor on this row — drill-down tables (chain / spreads / contracts) apply to ladder rows with a participant key + tournament."}</div>
      ) : err ? (
        <div className="note red" style={{ marginTop: 8 }}>detail unavailable: {err}</div>
      ) : !bundle ? (
        <div className="note" style={{ marginTop: 8 }}>loading participant detail…</div>
      ) : (
        <>
          {!hasLadder ? (
            <div className="note" style={{ marginTop: 8 }}>This market isn't part of a containment ladder
              (no nested stages with prices to compare) — showing its contract(s) and resolution below.</div>
          ) : null}
          {hasLadder ? (() => {
            const cr = condRungRows(bundle.chain);
            const bounds = bundle.indicators.filter((ind) => ind.kind === "bound");   // golf make-cut etc.
            return (
              <><div className="sect">LADDER PROBABILITY <span className="uncal">market-implied display ratio · not fair value</span></div>
                <table className="condtbl"><tbody>
                  <tr><th>Stage</th><th>Chance of reaching</th><th>Given prior stage</th><th>Quote</th></tr>
                  {cr.map((r, i) => (
                    <tr key={i}>
                      <td>{r.stage}</td>
                      <td className="violet">{r.reaching != null ? n1(r.reaching) + "%" : "—"}</td>
                      <td>{r.given != null ? <span className="violet">{n1(r.given)}%</span> : <span className="dim">{r.note || "—"}</span>}</td>
                      <td className="dim">{r.quote || "—"}</td>
                    </tr>
                  ))}
                </tbody></table>
                {bounds.map((ind, i) => (
                  <div className="note" key={i}>{gv(ind, "label")} {gv(ind, "comparator")} {gv(ind, "value_pct")}{ind.value_pct != null ? "%" : ""} <span className="dim">(bound, not a traded market)</span></div>
                ))}
                <div className="note" style={{ marginTop: 4 }}>{CONDITIONAL_DISCLAIMER}</div>
              </>
            );
          })() : null}

          {hasLadder ? (
            <><div className="sect">CONTAINMENT CHAIN (BROAD → DEEP)</div>
              <Tbl rows={bundle.chain} cols={[["layer", "Layer"], ["source", "Source"], ["display_pct", "Disp %"], ["bid_pct", "Bid %"], ["ask_pct", "Ask %"], ["quote", "Quote"]]} />
              <div className="note" style={{ marginTop: 4 }}>
                A blank rung means <b>missing layer</b> (no market loaded for that rung), <b>missing quote</b>
                {" "}(a market with no usable price), or an <b>unverifiable</b> round mapping — never a violation.
              </div>
              <LadderChart data={ladder} /></>
          ) : null}

          {payoff && payoff.scenarios.length ? (
            <><div className="sect">PER-UNIT PAYOFF BY SCENARIO <span className="uncal">GROSS</span></div><PayoffChart data={payoff} /></>
          ) : null}

          {hasLadder && bundle.spreads.length ? (
            <><div className="sect">RAW STAGE-LADDER SPREADS</div>
              <Tbl rows={bundle.spreads} cols={[["from_layer", "From"], ["to_layer", "To"], ["spread_pct", "Spread pp"], ["spread_cents", "Spread ¢"], ["quote", "Quote"]]} /></>
          ) : null}

          {hasLadder && bundle.expected.length ? (
            <><div className="sect">EXPECTED VS FOUND</div>
              <Tbl rows={bundle.expected} cols={[["layer", "Layer"], ["found", "Found"], ["source", "Source"], ["reason", "If missing"]]} />
              {bundle.expected.some((e) => !e.found) ? (
                <div className="note" style={{ marginTop: 4 }}>
                  Missing rungs are a coverage gap, not an error.
                  {row.sport_key === "tennis" ? (
                    <> Tennis ladders are short (Reach Semifinal → Reach Final → Win Tournament) and ATP/WTA
                    advance markets are often sparse or closed between rounds, so cheap-NO bands form less
                    often than in a dense live ladder such as the World Cup round ladder.</>
                  ) : null}
                </div>
              ) : null}</>
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
  if (!row) return <div className="empty">Click a scanner row.</div>;
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
      <div className="sect">CONDITIONAL <span className="uncal">UNCALIBRATED · DISPLAY-ONLY</span></div>
      <div className="formula">display: P(deeper│reached) = price(deeper)/price(parent) = {row.cond_child != null && row.cdisp != null && row.pdisp ? `${row.cdisp}/${row.pdisp} = ${n1(row.cond_child)}%` : "n/a"}</div>
      <div className="formula">bid/ask: child ask/parent bid = {row.cond_child_firm != null && row.cask != null && row.pbid ? `${row.cask}/${row.pbid} = ${n1(row.cond_child_firm)}%` : "n/a"} <span className="uncal">diagnostic, not an executable edge</span></div>
      <div className="sect">FEES (estimate, display-only)</div>
      <div className="formula">kalshi taker fee ≈ 0.07·c·p·(1−p) → fees {cents(row.fees)} · net edge {cents(row.net_edge)} · never affects ranking</div>
      <div className="note"><span className="uncal">general taker estimate only · not net P&L · special schedules / maker fills / rounding / series fee changes may differ</span></div>
      <div className="note" style={{ marginTop: 6 }}>All gross & top-of-book; fees, collateral, full-depth execution are documented limits.</div>
    </div>
  );
}
