/* RES (research) + OPS (operations) surfaces — the function-tab surfaces beside OPP.
 * Built entirely from the feed meta (snapshot coverage / per-sport / bucket distribution / resolution +
 * scope counts). Read-only; RES is "research — not a trade" and never feeds actionability. */
import { useTerminal } from "./context";
import type { FeedMeta } from "./feed";

function seriesErrorRows(meta: FeedMeta | null): [string, string][] {
  const se = meta?.series_errors;
  if (Array.isArray(se)) return se.slice(0, 10).map((e: unknown) => {
    const d = e as { series?: string; sport?: string; error?: string };
    return [[d.series, d.sport].filter(Boolean).join(" · ") || "?", String(d.error || "").slice(0, 60)];
  });
  if (se && typeof se === "object") return Object.entries(se as Record<string, unknown>).slice(0, 10).map(([k, v]) => [k, String(v).slice(0, 60)]);
  return [];
}

export function OpsSurface() {
  const { meta } = useTerminal();
  const m = meta;
  const cov: [string, string | number][] = [
    ["Opportunities", (m?.n_total ?? 0).toLocaleString()], ["Contracts scanned", (m?.contracts ?? 0).toLocaleString()],
    ["Checks tested", (m?.checks ?? 0).toLocaleString()], ["Kalshi requests", m?.requests ?? 0],
    ["Series scanned", m?.scanned ?? 0], ["Failed series", m?.failed ?? 0], ["Retry count", m?.retry ?? 0],
    ["Fetched at", m?.fetched_at ?? "—"],
  ];
  const sports = Object.entries(m?.sports ?? {}).sort((a, b) => b[1] - a[1]);
  const buckets = Object.entries(m?.totals ?? {}).sort((a, b) => b[1] - a[1]);
  const errs = seriesErrorRows(m);
  return (
    <div className="surf-grid">
      <div className="rp"><div className="h">SCAN COVERAGE — SNAPSHOT #{m?.snapshot_id ?? "—"}</div>
        <table className="tp-tbl"><tbody>{cov.map(([k, v]) => <tr key={k}><td>{k}</td><td className="r amber">{v}</td></tr>)}</tbody></table></div>
      <div className="rp"><div className="h">PER-SPORT COVERAGE</div>
        <table className="tp-tbl"><thead><tr><th>Sport</th><th className="r">Opps</th></tr></thead>
          <tbody>{sports.map(([s, n]) => <tr key={s}><td>{s}</td><td className="r">{n.toLocaleString()}</td></tr>)}</tbody></table></div>
      <div className="rp"><div className="h">BUCKET DISTRIBUTION</div>
        <table className="tp-tbl"><tbody>{buckets.map(([b, n]) => <tr key={b}><td>{b}</td><td className="r">{n.toLocaleString()}</td></tr>)}</tbody></table></div>
      <div className="rp"><div className="h">SERIES ERRORS / DATA-QUALITY</div>
        <table className="tp-tbl"><tbody>{errs.length
          ? errs.map(([k, v], i) => <tr key={i}><td>{k}</td><td className="red">{v}</td></tr>)
          : <tr><td className="green" colSpan={2}>no series errors this scan</td></tr>}</tbody></table></div>
    </div>
  );
}

export function ResSurface() {
  const { meta } = useTerminal();
  const m = meta;
  const sports = Object.entries(m?.sports ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const mx = Math.max(1, ...sports.map((s) => s[1]));
  const res = m?.resolution_counts ?? {};
  const scope = m?.scope_counts ?? {};
  return (
    <div className="surf-grid">
      <div className="rp"><div className="h violet">RESEARCH LAB — read-only over derived data<span className="resb">P5 · FUTURE</span></div>
        <div className="c"><div className="note"><b>Research is read-only</b> — derived data only, never new scoring, never feeds actionability. Distributions / calibration / backtests are roadmap-future.</div></div></div>
      <div className="rp"><div className="h violet">OPPORTUNITIES BY SPORT</div>
        <div className="c"><div className="resbars">{sports.map(([s, n]) => (
          <div className="b" key={s} style={{ height: Math.round((n / mx) * 100) + "%" }}><span>{s.slice(0, 4)}</span></div>
        ))}</div></div></div>
      <div className="rp"><div className="h violet">BOUNDED-LOSS MIX</div>
        <div className="c"><div className="note">Vertical <b>{res.vertical || 0}</b> · Calendar <b>{res.calendar || 0}</b></div></div></div>
      <div className="rp"><div className="h violet">CHEAP-NO SCOPE</div>
        <div className="c"><div className="note">Championship <b>{scope.championship || 0}</b> · Tournament <b>{scope.tournament || 0}</b> · Event <b>{scope.event || 0}</b></div></div></div>
    </div>
  );
}
