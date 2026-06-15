/* MD ladder — top-of-book + DERIVED depth around the selected row's touch. Ported from the mockup's
 * ladderBook()/ladder(). READ-ONLY, no order controls. The depth bars are DERIVED from the firm touch
 * price+size (the engine stores no full book yet) — labelled as such, never presented as a real DOM. */
import { useState } from "react";
import type { FeedRow, FeedLeg } from "./feed";

function legLabel(l: FeedLeg, i: number): string {
  const side = String(l.side || "").includes("yes") ? "YES" : "NO";
  return `${side} · ${l.c || "leg " + (i + 1)} @ ${l.p != null ? l.p + "¢" : "—"}`;
}

function book(leg: FeedLeg | undefined) {
  if (!leg || leg.p == null) return null;
  const base = Math.round(leg.p), fill = Math.max(20, Math.round(leg.sz || 40)), maxsz = fill * 3.2;
  const rows: { p: number; bid: number; ask: number }[] = [];
  for (let p = Math.min(99, base + 6); p >= Math.max(1, base - 6); p--) {
    rows.push({
      p,
      bid: p <= base ? Math.round(fill * (1 + (base - p) * 0.7)) : 0,
      ask: p >= base ? Math.round(fill * (1 + (p - base) * 0.6)) : 0,
    });
  }
  return { base, fill, maxsz, rows };
}

export default function Ladder({ row }: { row: FeedRow | null }) {
  const [leg, setLeg] = useState(0);
  if (!row) return <div className="empty">—</div>;
  const legs = row.legs ?? [];
  if (!legs.length) return (<>
    <div className="lh"><div className="t">{row.name}</div><div className="s">no executable book</div></div>
    <div className="empty">research / field — no single-contract book</div>
  </>);
  const idx = Math.min(leg, legs.length - 1);
  const b = book(legs[idx]);
  return (
    <>
      <div className="ladhdr">
        <div className="t">{row.name} {legs.length > 1 ? <span className="dim">· {legs.length} contracts</span> : null}</div>
        {legs.length > 1
          ? <select className="in" value={idx} onChange={(e) => setLeg(+e.target.value)} style={{ marginTop: 2, maxWidth: "100%" }}>
              {legs.map((l, i) => <option key={i} value={i}>{legLabel(l, i)}</option>)}
            </select>
          : <div className="s">{legs[0]?.tk || ""}</div>}
      </div>
      <div className="pbody">
        {b ? (
          <table className="ladtbl"><thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead>
            <tbody>{b.rows.map(({ p, bid, ask }) => (
              <tr key={p}>
                <td className="bidc">{bid ? <><span className="fill" style={{ width: Math.min(100, bid / b.maxsz * 100) + "%" }} /><span>{bid}</span></> : null}</td>
                <td className={"px" + (p === b.base ? " touch" : "")}>{p}</td>
                <td className="askc">{ask ? <><span className="fill" style={{ width: Math.min(100, ask / b.maxsz * 100) + "%" }} /><span>{ask}</span></> : null}</td>
              </tr>
            ))}</tbody></table>
        ) : <div className="empty">No top-of-book for this contract.</div>}
      </div>
      {b ? <div className="ladfoot"><span>Touch {b.base}¢ · YES bids · NO asks (derived)</span><span>top size {b.fill} · fill realism</span></div> : null}
    </>
  );
}
