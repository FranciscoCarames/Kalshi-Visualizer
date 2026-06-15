/* Watch / Movers + Alerts side panels — ported from the mockup's watch()/alerts().
 * Derived from the live feed rows (read-only). Real new-actionable/bucket-change alerts via engine.alerts
 * land in Phase C; here they are derived from the current snapshot, clearly a snapshot view. */
import type { FeedRow, FeedMeta } from "./feed";

export function Watch({ opps, onPick }: { opps: FeedRow[]; onPick: (r: FeedRow) => void }) {
  const act = opps.filter((o) => o.section === "act").slice(0, 7);
  const rev = opps.filter((o) => o.section === "rev").slice(0, 4);
  return (
    <>
      {act.map((o) => (
        <div className="wrow" key={o.id} onClick={() => onPick(o)}>
          <span className="green">●</span>
          <div className="n3">{o.name}<div className="sub">{o.sport} · {o.detail || o.sub || ""}</div></div>
          <span className="green">{typeof o.edge === "number" ? Math.round(o.edge) + "¢" : ""}</span>
        </div>
      ))}
      <div className="wrow" style={{ borderTop: "1px solid var(--line2)" }}>
        <span className="dim" style={{ fontSize: 8.5 }}>REVIEW MOVERS</span>
      </div>
      {rev.map((o) => (
        <div className="wrow" key={o.id} onClick={() => onPick(o)}>
          <span className="amber">◐</span>
          <div className="n3">{o.name}<div className="sub">{o.sport} · rule-dep</div></div>
        </div>
      ))}
    </>
  );
}

export function Alerts({ opps, meta }: { opps: FeedRow[]; meta: FeedMeta | null }) {
  const firstAct = opps.find((o) => o.section === "act");
  const firstBounded = opps.find((o) => o.section === "bounded");
  const A: [string, string, string, string][] = [
    ["became executable", firstAct?.name || "—", "firm both legs", "green"],
    ["bucket changed", "→ Review · rule-check", "settlement check", "amber"],
    ["series failed", (meta?.failed || 0) + " series", "coverage partial", meta?.failed ? "red" : "green"],
    ["new bounded-loss", firstBounded?.name || "—", "watchlist", "cyan"],
  ];
  return (
    <>
      {A.map((a, i) => (
        <div className="arow" key={i}>
          <span className="ic" style={{ background: `var(--${a[3]})` }} />
          <div><div><b className="white">{a[0]}</b> — {a[1]}</div><div className="meta">{a[2]}</div></div>
        </div>
      ))}
    </>
  );
}
