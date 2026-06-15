/* Hand-rolled inline-SVG charts (no charting lib — the bundle is already ~1.5MB and the spark()/Ladder
 * patterns already prove inline SVG fits the terminal aesthetic). Pure display of viz.py JSON. */
import type { PayoffData, LadderData } from "./detail";

/** Per-unit payoff: a bar per settlement scenario vs a dashed cost reference line (clears cost = profit). */
export function PayoffChart({ data }: { data: PayoffData | null }) {
  const recs = (data?.scenarios || []).filter((s) => s.role !== "Risk" && s.payout_c != null);
  if (!recs.length) return <div className="note">No payoff scenarios (dutch-book / non-containment row).</div>;
  const cost = data?.cost_c ?? null;
  const max = Math.max(...recs.map((r) => r.payout_c as number), cost ?? 0, 1);
  const W = 280, H = 120, pad = 20, bw = (W - pad * 2) / recs.length;
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" preserveAspectRatio="xMidYMid meet">
      {cost != null ? (
        <>
          <line x1={pad} x2={W - pad} y1={y(cost)} y2={y(cost)} stroke="#ff453a" strokeDasharray="3 3" />
          <text x={W - pad} y={y(cost) - 2} textAnchor="end" className="cl">cost {Math.round(cost)}¢</text>
        </>
      ) : null}
      {recs.map((r, i) => {
        const x = pad + i * bw + 2;
        const yy = y(r.payout_c as number);
        const h = Math.max(0, (H - pad) - yy);
        return (
          <g key={i}>
            <rect x={x} y={yy} width={bw - 4} height={h} fill={r.role === "Bonus" ? "#43d9ff" : "#33ff7a"} opacity={0.85} />
            <text x={x + (bw - 4) / 2} y={H - 6} textAnchor="middle" className="cl">{r.scenario.slice(0, 7)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Containment ladder display prices (broad→deep). Bars should step DOWN; a layer priced above its
 * broader neighbour is flagged red (the visual signature of a consistency violation). */
export function LadderChart({ data }: { data: LadderData | null }) {
  const recs = (data?.layers || []).filter((l) => l.display_pct != null);
  if (recs.length < 2) return <div className="note">No priced ladder (need ≥2 priced layers).</div>;
  const W = 280, rowH = 18, pad = 4, labelW = 120, barMax = W - labelW - pad * 2 - 26;
  const H = recs.length * rowH + pad * 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" preserveAspectRatio="xMidYMid meet">
      {recs.map((l, i) => {
        const yy = pad + i * rowH;
        const w = Math.max(1, ((l.display_pct as number) / 100) * barMax);
        return (
          <g key={i}>
            <text x={pad} y={yy + 12} className="cl" style={{ textAnchor: "start" }}>{l.layer.slice(0, 17)}</text>
            <rect x={labelW} y={yy + 3} width={w} height={rowH - 7} fill={l.inverted ? "#ff453a" : "#43d9ff"} opacity={0.85} />
            <text x={labelW + w + 3} y={yy + 12} className="cl">{(l.display_pct as number).toFixed(0)}%</text>
          </g>
        );
      })}
    </svg>
  );
}
