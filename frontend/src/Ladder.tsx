/* MD ladder — the LIVE Kalshi resting order book for the selected leg's market. READ-ONLY, no order
 * controls. Replaces the old synthetic/derived depth: every level here is a real resting order fetched
 * from GET /api/terminal/orderbook (re-polled ~5s while a row is selected, aborted on change). YES bids
 * come straight from the book; YES asks are the NO bids inverted (ask price = 100 − no price). Empty or
 * closed books show an honest "no resting orders" — never fabricated rungs. DISPLAY-ONLY depth: gross /
 * top-of-book limits still apply, this is NOT net executable capacity. */
import { useEffect, useState } from "react";
import type { FeedRow, FeedLeg } from "./feed";
import { loadOrderbook, loadDetail, chainRungs, detailKey, type OrderbookData, type LadderRung } from "./detail";

const REFRESH_MS = 5000;

/** The book ticker to show: an explicitly-picked rung overrides the row's own contract; otherwise default to
 * the row's selected leg ticker, else the first ladder rung. Mirrors the audit's default-rung priority
 * (selected leg / opportunity contract → first ticker-bearing rung). */
export function resolveBookTicker(rungTicker: string | null, legTicker: string, rungs: LadderRung[]): string {
  return rungTicker ?? (legTicker || rungs[0]?.ticker || "");
}

export function legLabel(l: FeedLeg, i: number): string {
  if (l.bo) return `book · ${l.c || l.tk || "leg " + (i + 1)}`;   // book-only pseudo-leg (no trade side)
  const side = String(l.side || "").includes("yes") ? "YES" : "NO";
  return `${side} · ${l.c || "leg " + (i + 1)} @ ${l.p != null ? l.p + "¢" : "—"}`;
}

/** First leg that can actually load a book (a non-empty single-contract ticker). Tie/Draw legs are REAL
 * markets and carry tickers, so they qualify — only comparator/synthetic legs with no ticker are skipped. */
export function firstBookableLeg(legs: FeedLeg[]): number {
  const i = legs.findIndex((l) => l.tk);
  return i >= 0 ? i : 0;
}

/** Whether to show the participant's full ladder RUNG picker (vs. the per-leg picker). True ONLY for a
 * genuine CONTAINMENT parent→child pair — the feed sets both `pnode` and `cnode` on exactly those rows
 * (bounded-loss, cheap-NO containment, executable containment violations). Every AGGREGATE row — winner
 * field, dutch book, 2-way game, stage-of-elimination book/synthetic, synthetic bundle — has neither, so
 * it falls through to the leg picker and exposes ALL its legs (not one anchor team's ladder). Verified
 * against the live feed; `source`/`relationship_type`/`setup_family` are not present in the SPA feed, so
 * `pnode && cnode` is the reliable signal. */
export function showLadderRungs(row: FeedRow | null): boolean {
  return !!(row && row.pnode && row.cnode);
}

interface Level { p: number; bid: number; ask: number; }

/** Build the displayed price ladder from the raw book. YES bids verbatim; YES asks = NO bids inverted
 * (ask price = 100 − no price), so the best YES ask comes from the HIGHEST NO bid. Rows high→low price. */
export function levelsFrom(ob: OrderbookData | null): { rows: Level[]; bestBid: number | null; bestAsk: number | null; maxsz: number } {
  if (!ob) return { rows: [], bestBid: null, bestAsk: null, maxsz: 1 };
  const bid = new Map<number, number>();
  const ask = new Map<number, number>();
  for (const lvl of ob.yes || []) { const p = lvl[0], s = lvl[1]; if (p >= 1 && p <= 99 && s > 0) bid.set(p, (bid.get(p) || 0) + s); }
  for (const lvl of ob.no || []) { const ap = 100 - lvl[0], s = lvl[1]; if (ap >= 1 && ap <= 99 && s > 0) ask.set(ap, (ask.get(ap) || 0) + s); }
  const prices = [...new Set([...bid.keys(), ...ask.keys()])].sort((a, b) => b - a);
  const rows = prices.map((p) => ({ p, bid: bid.get(p) || 0, ask: ask.get(p) || 0 }));
  const bestBid = bid.size ? Math.max(...bid.keys()) : null;
  const bestAsk = ask.size ? Math.min(...ask.keys()) : null;
  const maxsz = Math.max(1, ...rows.map((r) => Math.max(r.bid, r.ask)));
  return { rows, bestBid, bestAsk, maxsz };
}

export default function Ladder({ row }: { row: FeedRow | null }) {
  const [leg, setLeg] = useState(0);
  const [ob, setOb] = useState<OrderbookData | null>(null);
  const [loading, setLoading] = useState(false);
  const [secsAgo, setSecsAgo] = useState(0);
  const [rungs, setRungs] = useState<LadderRung[]>([]);
  const [rungTicker, setRungTicker] = useState<string | null>(null);

  const legs = row?.legs ?? [];
  const idx = Math.min(leg, Math.max(0, legs.length - 1));
  const legTicker = legs[idx]?.tk || "";
  const effectiveTicker = resolveBookTicker(rungTicker, legTicker, rungs);

  // On row change: reset to the first BOOKABLE leg, clear any picked rung + the loaded rung list (so a stale
  // ladder never lingers under a new participant).
  useEffect(() => { setLeg(firstBookableLeg(legs)); setRungTicker(null); setRungs([]); }, [row?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Load the player's full ladder rungs (with tickers) for the rung picker — ONLY for a genuine CONTAINMENT
  // parent→child row (showLadderRungs). Aggregate rows (winner field, dutch book, 2-way game, stage-elim
  // book/synthetic, synthetic bundle) skip this entirely so they fall through to the leg picker and expose
  // ALL their legs — and a late response can never repopulate rungs and re-shadow the leg picker. Aborted
  // on row/key change.
  const useRungs = showLadderRungs(row);
  const key = detailKey(row);
  const keyStr = key ? `${key.sport}|${key.player_key}|${key.tournament}` : "";
  useEffect(() => {
    if (!key || !useRungs) { setRungs([]); return; }
    let alive = true;
    const ctrl = new AbortController();
    loadDetail(key, ctrl.signal)
      .then((b) => { if (alive) setRungs(chainRungs(b)); })
      .catch(() => { if (alive) setRungs([]); });
    return () => { alive = false; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyStr, useRungs]);

  // Fetch the live book for the EFFECTIVE ticker (picked rung overrides the leg); re-poll ~5s; abort in-flight
  // on change/unmount. Paused when nothing is selected (no ticker → no fetch).
  useEffect(() => {
    setOb(null); setSecsAgo(0);
    if (!effectiveTicker || row?.zone === "diag") return;   // diagnostic rows aren't tradable — no live book
    let alive = true;
    const ctrl = new AbortController();
    const pull = () => {
      setLoading(true);
      loadOrderbook(effectiveTicker, ctrl.signal)
        // Race guard: ignore a response whose ticker no longer matches the selected one (a slow reply from a
        // previous leg/rung landing after a fast switch) on top of the AbortController.
        .then((d) => { if (alive && d.ticker === effectiveTicker) { setOb(d); setSecsAgo(0); } })
        .catch((e) => { if (alive && e?.name !== "AbortError") setOb({ ticker: effectiveTicker, yes: [], no: [], ok: false, error: "order book unavailable", age_s: 0 }); })
        .finally(() => { if (alive) setLoading(false); });
    };
    pull();
    const poll = setInterval(pull, REFRESH_MS);
    const tick = setInterval(() => alive && setSecsAgo((s) => s + 1), 1000);
    return () => { alive = false; ctrl.abort(); clearInterval(poll); clearInterval(tick); };
  }, [effectiveTicker, row?.zone]);

  if (!row) return <div className="empty">—</div>;
  if (row.zone === "diag") return (<>
    <div className="ladhdr"><div className="t">{row.name}</div><div className="s">diagnostic row</div></div>
    <div className="empty">not applicable — diagnostic rows have no tradable order book</div>
  </>);
  const anyBookable = legs.some((l) => l.tk) || rungs.length > 0;
  if (!anyBookable) return (<>
    <div className="ladhdr"><div className="t">{row.name}</div><div className="s">no single-contract book</div></div>
    <div className="empty">{legs.length
      ? "multi-leg field — no single-contract book for any leg"
      : "research / field — no single-contract book"}</div>
  </>);

  const { rows, bestBid, bestAsk, maxsz } = levelsFrom(ob);
  const hasBook = rows.length > 0;
  const bar = (sz: number) => <><span className="fill" style={{ width: Math.min(100, sz / maxsz * 100) + "%" }} /><span>{sz}</span></>;
  // Rung picker (all ladder rungs of this player) supersedes the leg picker for containment rows; the leg
  // picker stays for multi-leg field/dutch rows that have no single-participant ladder.
  const ownContractIsRung = rungs.some((r) => r.ticker === legTicker);
  return (
    <>
      <div className="ladhdr">
        <div className="t">{row.name} {rungs.length > 0 ? <span className="dim">· {rungs.length} rungs</span> : legs.length > 1 ? <span className="dim">· {legs.length} contracts</span> : null}</div>
        {rungs.length > 0
          ? <select className="in" value={effectiveTicker} onChange={(e) => setRungTicker(e.target.value)} style={{ marginTop: 2, maxWidth: "100%" }}>
              {legTicker && !ownContractIsRung ? <option value={legTicker}>▸ this contract</option> : null}
              {rungs.map((r) => <option key={r.ticker} value={r.ticker}>{r.layer}{r.display_pct != null ? ` · ${r.display_pct}%` : ""}</option>)}
            </select>
          : legs.length > 1
            ? <select className="in" value={idx} onChange={(e) => setLeg(+e.target.value)} style={{ marginTop: 2, maxWidth: "100%" }}>
                {legs.map((l, i) => <option key={i} value={i}>{legLabel(l, i)}</option>)}
              </select>
            : <div className="s">{effectiveTicker || ""}</div>}
      </div>
      <div className="pbody">
        {!effectiveTicker ? <div className="empty">research / field — no single-contract book</div>
          : ob && !ob.ok ? <div className="empty">{/rate.?limit/i.test(ob.error || "")
              ? "rate-limited — retrying shortly" : (ob.error || "order book unavailable")}</div>
          : !ob && loading ? <div className="empty">loading live order book…</div>
          : !hasBook ? <div className="empty">no resting orders (empty or closed book)</div>
          : (
            <table className="ladtbl" title="Kalshi books hold YES & NO bids. A YES ask = a NO bid inverted (100 − no). To Buy NO, take a YES bid at NO price = 100 − bid."><thead><tr><th>YES bid</th><th>Px¢</th><th>YES ask</th></tr></thead>
              <tbody>{rows.map(({ p, bid, ask }) => (
                <tr key={p}>
                  <td className="bidc">{bid ? bar(bid) : null}</td>
                  <td className={"px" + (p === bestBid || p === bestAsk ? " touch" : "")}>{p}</td>
                  <td className="askc">{ask ? bar(ask) : null}</td>
                </tr>
              ))}</tbody></table>
          )}
      </div>
      {hasBook
        ? <div className="ladfoot">
            <span title="Kalshi books hold YES & NO bids; a YES ask = a NO bid inverted (100 − no).">YES book · Buy NO = 100 − YES bid</span>
            <span>refreshed {secsAgo}s · best {bestBid ?? "—"}/{bestAsk ?? "—"}¢ · top-of-book</span>
          </div>
        : null}
    </>
  );
}
