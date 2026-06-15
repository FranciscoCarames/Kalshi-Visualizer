import { describe, it, expect } from "vitest";
import { deriveAlerts, type ChangeFn } from "./alerts";
import type { FeedRow, FeedMeta } from "./feed";

const row = (id: string, section: string, name = id): FeedRow =>
  ({ id, section, name, bucket: section, zone: "exec", sport: "tennis" } as FeedRow);
const meta = (failed = 0): FeedMeta =>
  ({ snapshot_id: 1, fetched_at: null, n_total: 0, totals: {}, sports: {}, resolution_counts: {}, scope_counts: {}, failed } as FeedMeta);
const chg = (m: Record<string, "new" | "up" | "down" | "returned">): ChangeFn => (id) => m[id] ?? null;

describe("deriveAlerts", () => {
  it("first load (no baseline) emits no change rows — only current-state coverage", () => {
    const opps = [row("a", "act")];
    expect(deriveAlerts(opps, chg({ a: "new" }), meta(0), false)).toEqual([]);
    const partial = deriveAlerts(opps, chg({ a: "new" }), meta(2), false);
    expect(partial.map((x) => x.kind)).toEqual(["coverage_partial"]);
  });

  it("flags a newly-actionable row", () => {
    const al = deriveAlerts([row("a", "act")], chg({ a: "new" }), meta(0), true);
    expect(al.map((x) => x.kind)).toEqual(["new_actionable"]);
    expect(al[0].opportunity_id).toBe("a");
  });

  it("flags a returned-to-actionable row", () => {
    const al = deriveAlerts([row("a", "act")], chg({ a: "returned" }), meta(0), true);
    expect(al.map((x) => x.kind)).toEqual(["returned_actionable"]);
  });

  it("flags edge up / down movers with the right severity", () => {
    const al = deriveAlerts([row("a", "bounded"), row("b", "bounded")], chg({ a: "up", b: "down" }), meta(0), true);
    const byId = Object.fromEntries(al.map((x) => [x.opportunity_id, x]));
    expect(byId.a.kind).toBe("edge_up");
    expect(byId.a.severity).toBe("info");
    expect(byId.b.kind).toBe("edge_down");
    expect(byId.b.severity).toBe("review");
  });

  it("emits a coverage_partial warn when series failed", () => {
    const al = deriveAlerts([], chg({}), meta(3), true);
    expect(al).toHaveLength(1);
    expect(al[0].kind).toBe("coverage_partial");
    expect(al[0].severity).toBe("warn");
    expect(al[0].label).toContain("3");
  });

  it("returns [] when there is a baseline but nothing changed", () => {
    expect(deriveAlerts([row("a", "act")], chg({}), meta(0), true)).toEqual([]);
  });

  it("never throws on missing fields and only ever emits allowed kinds (no bucket-change)", () => {
    const allowed = ["new_actionable", "returned_actionable", "edge_up", "edge_down", "coverage_partial"];
    const messy = [{} as FeedRow, { id: "x" } as FeedRow];
    const al = deriveAlerts(messy, chg({ x: "up" }), null, true);
    expect(Array.isArray(al)).toBe(true);
    expect(al.every((a) => allowed.includes(a.kind))).toBe(true);
  });
});
