import { describe, it, expect } from "vitest";
import { buildReference } from "./clipboard";
import type { FeedRow } from "./feed";

const base = (o: Partial<FeedRow>): FeedRow => ({
  id: "op1", bucket: "actionable", zone: "exec", section: "act", name: "A vs B", sport: "NFL",
  cost: 96, max_loss: -4, max_profit: 4, roi: 4.2, units: 50, quote_health: "Tight", tradable: "Yes",
  legs: [{ side: "yes", c: "Team A", p: 48, sz: 50, tk: "KXX-A" },
         { side: "no", c: "Team B", p: 48, sz: 60, tk: "KXX-B" }],
  ...o,
});
const opts = { basis: 1, snapshotId: 1088, capturedAt: "2026-06-22 12:00 UTC" };

describe("buildReference — read-only copy ticket", () => {
  it("is read-only and carries the stale-quote guard + snapshot", () => {
    const t = buildReference(base({}), opts);
    expect(t).toContain("read-only");
    expect(t).toContain("Not an order");
    expect(t).toContain("VERIFY THE CURRENT BOOK BEFORE TRADING");
    expect(t).toContain("Snapshot #1088");
    expect(t).toContain("captured 2026-06-22 12:00 UTC");
    expect(t).toContain("opportunity_id: op1");
  });

  it("lists every leg as buy-only YES/NO (never sell/short), with ticker + top quote size", () => {
    const t = buildReference(base({}), opts);
    expect(t).toContain("BUY YES Team A [KXX-A] @ 48¢  (top quote 50)");
    expect(t).toContain("BUY NO  Team B [KXX-B] @ 48¢  (top quote 60)");
    expect(t).not.toMatch(/\b(sell|short|arbitrage|riskless|locked|guaranteed)\b/i);
  });

  it("respects the $100 basis for prices", () => {
    const t = buildReference(base({}), { ...opts, basis: 100 });
    expect(t).toContain("@ $0.48");
    expect(t).toContain("Cost $0.96");
  });

  it("excludes book-only legs and keeps real legs", () => {
    const t = buildReference(base({ legs: [
      { side: "yes", c: "Team A", p: 48, sz: 50, tk: "KXX-A" },
      { side: "", c: "ref market", bo: true, tk: "KXX-REF" },
    ] }), opts);
    expect(t).toContain("Team A");
    expect(t).not.toContain("ref market");
    expect(t).toContain("1 leg");
  });

  it("includes settlement / rule / blocked caveats when present", () => {
    const t = buildReference(base({ settlement_caveat: "postponement risk", rule: "RULE_CHECK_REQUIRED", blk: "no size" }), opts);
    expect(t).toContain("CAVEATS:");
    expect(t).toContain("postponement risk");
    expect(t).toContain("RULE_CHECK_REQUIRED");
    expect(t).toContain("no size");
  });

  it("labels non-structural shapes honestly", () => {
    expect(buildReference(base({ zone: "diag" }), opts)).toContain("DIAGNOSTIC ONLY");
    expect(buildReference(base({ zone: "spec", section: "bounded" }), opts)).toContain("can lose money");
    expect(buildReference(base({ section: "nm" }), opts)).toContain("WATCHLIST");
  });
});
