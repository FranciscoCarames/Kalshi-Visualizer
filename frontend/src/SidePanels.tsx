/* Watch / Movers + Alerts side panels — ported from the mockup's watch()/alerts().
 * Watch is a read-only view of the current top rows. Alerts shows REAL changes since the previous scan,
 * derived by the pure `deriveAlerts` helper from the existing `changeOf` diff (never fabricated). */
import type { FeedRow } from "./feed";
import { useTerminal } from "./context";
import { deriveAlerts, ALERT_LABEL, type AlertSeverity } from "./alerts";

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

const SEV_COLOR: Record<AlertSeverity, string> = { info: "green", review: "amber", warn: "red" };

export function Alerts() {
  const { opps, changeOf, meta, hasBaseline, settings, hiddenByFeeCount } = useTerminal();
  const alerts = deriveAlerts(opps, changeOf, meta, hasBaseline, settings.hideNetNegExec);
  // L4: when the fee filter suppresses executable rows, say so explicitly so the alert list (and badge) are
  // never silently shorter than reality — the rows are revealable via the chip/Settings.
  const feeNote = hiddenByFeeCount > 0
    ? <div className="note" style={{ padding: 6 }}>{hiddenByFeeCount} executable row{hiddenByFeeCount > 1 ? "s" : ""} hidden by the fee filter — reveal via the chip / Settings.</div>
    : null;
  if (!alerts.length) {
    return <>{feeNote}<div className="note" style={{ padding: 6 }}>
      {hasBaseline ? "No changes since last scan." : "No prior scan baseline yet — alerts appear after the next scan."}
    </div></>;
  }
  return (
    <>
      {feeNote}
      {alerts.map((a, i) => (
        <div className="arow" key={i}>
          <span className="ic" style={{ background: `var(--${SEV_COLOR[a.severity]})` }} />
          <div><div><b className="white">{ALERT_LABEL[a.kind]}</b> — {a.label}</div><div className="meta">{a.basis}</div></div>
        </div>
      ))}
    </>
  );
}
