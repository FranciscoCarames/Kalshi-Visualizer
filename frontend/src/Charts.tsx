/* Participant-Detail data tables (replaced the old cramped inline-SVG bar charts — owner preferred exact
 * numbers over bars). Pure display of the viz.py JSON: no charting lib, no SVG. Reuses the `.condtbl`
 * table style already used elsewhere in the inspector. DISPLAY-ONLY (gross, top-of-book, uncalibrated). */
import type { PayoffData, LadderData } from "./detail";

const pct = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1));
const signed = (c: number) => (c > 0 ? "+" : "") + Math.round(c) + "¢";

/** Per-unit payoff by settlement scenario — exact payout + profit (= payout − cost), profit colored.
 * "Settles" names the role (floor / bonus) instead of a bar colour you have to decode. */
export function PayoffChart({ data }: { data: PayoffData | null }) {
  const recs = (data?.scenarios || []).filter((s) => s.role !== "Risk" && s.payout_c != null);
  if (!recs.length) return <div className="note">No payoff scenarios (dutch-book / non-containment row).</div>;
  const cost = data?.cost_c ?? null;
  return (
    <>
      {cost != null ? <div className="note">Cost <span className="white">{Math.round(cost)}¢</span> · per unit · gross</div> : null}
      <table className="condtbl"><tbody>
        <tr><th>Scenario</th><th>Settles</th><th>Payout</th><th>Profit</th></tr>
        {recs.map((r, i) => {
          const profit = r.profit_c != null ? r.profit_c : (cost != null && r.payout_c != null ? r.payout_c - cost : null);
          return (
            <tr key={i}>
              <td>{r.scenario}</td>
              <td className="dim">{r.role || "—"}</td>
              <td className="white">{r.payout_c != null ? Math.round(r.payout_c) + "¢" : "—"}</td>
              <td className={profit == null ? "" : profit >= 0 ? "green" : "red"}>{profit == null ? "—" : signed(profit)}</td>
            </tr>
          );
        })}
      </tbody></table>
    </>
  );
}

/** Containment step-down check (broad → deep): a deeper layer must price ≤ its broader parent. Shows the
 * exact display %, the Δ vs the broader neighbour, and an explicit step verdict — an inversion (deeper
 * priced ABOVE broader, the violation signature) reads "↑ INVERTED" in red, no chart needed. */
export function LadderChart({ data }: { data: LadderData | null }) {
  const recs = (data?.layers || []).filter((l) => l.display_pct != null);
  if (recs.length < 2) return <div className="note">No priced ladder (need ≥2 priced layers).</div>;
  let prev: number | null = null;
  return (
    <>
      <div className="note" style={{ marginTop: 4 }}>Step-down check — Δ is this layer minus its broader parent (negative = consistent).</div>
      <table className="condtbl"><tbody>
        <tr><th>Layer</th><th>Disp %</th><th>Δ parent</th><th>Step</th></tr>
        {recs.map((l, i) => {
          const v = l.display_pct as number;
          const delta = prev == null ? null : v - prev;
          prev = v;
          const step = l.inverted
            ? <span className="red">↑ INVERTED</span>
            : delta == null ? <span className="dim">broadest</span> : <span className="green">↓ ok</span>;
          return (
            <tr key={i}>
              <td>{l.layer}</td>
              <td className="white">{pct(v)}%</td>
              <td className={delta == null ? "dim" : l.inverted ? "red" : "green"}>{delta == null ? "—" : (delta > 0 ? "+" : "") + pct(delta)}</td>
              <td>{step}</td>
            </tr>
          );
        })}
      </tbody></table>
    </>
  );
}
