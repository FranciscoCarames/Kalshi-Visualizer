/* MD ladder — the LIVE Kalshi resting order book for the selected leg's market. READ-ONLY, no order
 * controls. Replaces the old synthetic/derived depth: every level here is a real resting order fetched
 * from GET /api/terminal/orderbook (re-polled ~5s while a row is selected, aborted on change). YES bids
 * come straight from the book; YES asks are the NO bids inverted (ask price = 100 − no price). Empty or
 * closed books show an honest "no resting orders" — never fabricated rungs. DISPLAY-ONLY depth: gross /
 * top-of-book limits still apply, this is NOT net executable capacity. */
import { useEffect, useState } from "react";
import type { FeedRow, FeedLeg } from "./feed";
import { loadOrderbook, type OrderbookData } from "./detail";

const REFRESH_MS = 5000;

function legLabel(l: FeedLeg, i: number): string {
  const side = String(l.side || "").includes("yes") ? "YES" : "NO";
  return `${side} · ${l.c || "leg " + (i + 1)} @ ${l.p != null ? l.p + "¢" : "—"}`;
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

  const legs = row?.legs ?? [];
  const idx = Math.min(leg, Math.max(0, legs.length - 1));
  const ticker = legs[idx]?.tk || "";

  useEffect(() => { setLeg(0); }, [row?.id]);            // reset to leg 0 when the selected row changes

  // Fetch the live book for the selected ticker; re-poll ~5s; abort the in-flight request on change/unmount
  // (debounces rapid leg switches). Paused implicitly when nothing is selected (no ticker → no fetch).
  useEffect(() => {
    setOb(null); setSecsAgo(0);
    if (!ticker) return;
    let alive = true;
    const ctrl = new AbortController();
    const pull = () => {
      setLoading(true);
      loadOrderbook(ticker, ctrl.signal)
        .then((d) => { if (alive) { setOb(d); setSecsAgo(0); } })
        .catch((e) => { if (alive && e?.name !== "AbortError") setOb({ ticker, yes: [], no: [], ok: false, error: "order book unavailable", age_s: 0 }); })
        .finally(() => { if (alive) setLoading(false); });
    };
    pull();
    const poll = setInterval(pull, REFRESH_MS);
    const tick = setInterval(() => alive && setSecsAgo((s) => s + 1), 1000);
    return () => { alive = false; ctrl.abort(); clearInterval(poll); clearInterval(tick); };
  }, [ticker]);

  if (!row) return <div className="empty">—</div>;
  if (!legs.length) return (<>
    <div className="ladhdr"><div className="t">{row.name}</div><div className="s">no executable book</div></div>
    <div className="empty">research / field — no single-contract book</div>
  </>);

  const { rows, bestBid, bestAsk, maxsz } = levelsFrom(ob);
  const hasBook = rows.length > 0;
  const bar = (sz: number) => <><span className="fill" style={{ width: Math.min(100, sz / maxsz * 100) + "%" }} /><span>{sz}</span></>;
  return (
    <>
      <div className="ladhdr">
        <div className="t">{row.name} {legs.length > 1 ? <span className="dim">· {legs.length} contracts</span> : null}</div>
        {legs.length > 1
          ? <select className="in" value={idx} onChange={(e) => setLeg(+e.target.value)} style={{ marginTop: 2, maxWidth: "100%" }}>
              {legs.map((l, i) => <option key={i} value={i}>{legLabel(l, i)}</option>)}
            </select>
          : <div className="s">{ticker || ""}</div>}
      </div>
      <div className="pbody">
        {!ticker ? <div className="empty">research / field — no single-contract book</div>
          : ob && !ob.ok ? <div className="empty">{ob.error || "order book unavailable"}</div>
          : !ob && loading ? <div className="empty">loading live order book…</div>
          : !hasBook ? <div className="empty">no resting orders (empty or closed book)</div>
          : (
            <table className="ladtbl"><thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead>
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
        ? <div className="ladfoot"><span>LIVE order book · refreshed {secsAgo}s ago</span><span>best bid {bestBid ?? "—"}¢ · ask {bestAsk ?? "—"}¢ · gross/top-of-book</span></div>
        : null}
    </>
  );
}
