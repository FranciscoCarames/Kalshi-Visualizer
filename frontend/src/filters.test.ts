import { describe, it, expect } from "vitest";
import { passAll, passThreshold, applyBand, emptyFilters, emptyBand, defaultBand, isDefaultBand, type FilterState, type BandState } from "./filters";
import type { BandDefaults, FeedRow } from "./feed";

const row = (o: Partial<FeedRow>): FeedRow =>
  ({ id: Math.random().toString(), bucket: "x", zone: "spec", section: "bounded", ...o });

describe("two-pass filter (membership vs threshold)", () => {
  it("thresholds spare Actionable + Diagnostics, gate others", () => {
    const f: FilterState = { ...emptyFilters(), tradableOnly: true };
    const act = row({ section: "act", zone: "exec", tradable: "No" });
    const diag = row({ section: "diag", zone: "diag", tradable: "No" });
    const bounded = row({ section: "bounded", zone: "spec", tradable: "No" });
    expect(passThreshold(act, f)).toBe(true);     // Actionable spared
    expect(passThreshold(diag, f)).toBe(true);    // Diagnostics spared
    expect(passThreshold(bounded, f)).toBe(false); // others gated
  });
  it("membership narrows every section", () => {
    const f: FilterState = { ...emptyFilters(), sports: new Set(["NBA"]) };
    expect(passAll(row({ section: "act", zone: "exec", sport: "NBA" }), f)).toBe(true);
    expect(passAll(row({ section: "act", zone: "exec", sport: "NFL" }), f)).toBe(false);
  });
});

describe("applyBand (fail-open on missing fields)", () => {
  const base = (): BandState => emptyBand();

  it("max-loss cap drops rows over the cap but KEEPS rows with a missing value", () => {
    const b = { ...base(), maxLoss: 5 };
    const rows = [row({ max_loss: 3 }), row({ max_loss: 9 }), row({})];
    expect(applyBand(rows, "bounded", b).length).toBe(2); // 3¢ kept, 9¢ dropped, missing kept (fail-open)
  });
  it("min upside:risk floor keeps rows with a missing ratio (fail-open)", () => {
    const b = { ...base(), minRatio: 2 };
    const rows = [row({ ratio: 3 }), row({ ratio: 1 }), row({})];
    expect(applyBand(rows, "bounded", b).length).toBe(2); // 3 kept, 1 dropped, missing kept
  });
  it("cheap-NO kind selector filters by row type, not price", () => {
    const rows = [row({ section: "cheapno", kind: "Band" }), row({ section: "cheapno", kind: "Outright" })];
    expect(applyBand(rows, "cheapno", { ...base(), cheapKind: "band" }).map((r) => r.kind)).toEqual(["Band"]);
    expect(applyBand(rows, "cheapno", { ...base(), cheapKind: "outright" }).map((r) => r.kind)).toEqual(["Outright"]);
    expect(applyBand(rows, "cheapno", { ...base(), cheapKind: "all" }).length).toBe(2);
  });
  it("near-miss max-overpay caps; off (0) is a no-op", () => {
    const rows = [row({ overpay: 2 }), row({ overpay: 8 })];
    expect(applyBand(rows, "nearmiss", { ...base(), maxOverpay: 5 }).length).toBe(1);
    expect(applyBand(rows, "nearmiss", base()).length).toBe(2);
  });
});

describe("defaultBand (old-UI parity, per-section, from meta.defaults)", () => {
  const D: BandDefaults = { bounded_max_loss_c: 5, nearmiss_overpay_c: 3, cheapno_max_loss_c: 15, cheapno_max_buy_no_c: 15 };
  it("seeds bounded max-loss 5¢, near-miss overpay 3¢, cheap-NO 15¢/15¢ (no collision on maxLoss)", () => {
    expect(defaultBand("bounded", D).maxLoss).toBe(5);
    expect(defaultBand("nearmiss", D).maxOverpay).toBe(3);
    expect(defaultBand("cheapno", D).maxLoss).toBe(15);
    expect(defaultBand("cheapno", D).maxBuyNo).toBe(15);
  });
  it("falls back to the config literals when meta.defaults is absent", () => {
    expect(defaultBand("bounded").maxLoss).toBe(5);
    expect(defaultBand("cheapno").maxLoss).toBe(15);
  });
  it("isDefaultBand detects an untouched vs edited band", () => {
    expect(isDefaultBand("bounded", defaultBand("bounded", D), D)).toBe(true);
    expect(isDefaultBand("bounded", { ...defaultBand("bounded", D), maxLoss: 9 }, D)).toBe(false);
  });
});
