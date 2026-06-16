import { describe, it, expect } from "vitest";
import { condRungRows } from "./Inspector";

const chain = (rows: { layer: string; display_pct: number | null; quote?: string }[]) =>
  rows as unknown as Record<string, unknown>[];

describe("condRungRows — readable LADDER PROBABILITY table (absolute + conditional)", () => {
  it("broadest rung has no conditional; adjacent ratios compute as deeper/broader×100", () => {
    const r = condRungRows(chain([
      { layer: "Reach R32", display_pct: 75.5 },
      { layer: "Reach R16", display_pct: 33.6 },
      { layer: "Reach QF", display_pct: 13.5 },
    ]));
    expect(r[0]).toMatchObject({ stage: "Reach R32", reaching: 75.5, given: null, note: "broadest" });
    expect(r[1].given).toBeCloseTo(33.6 / 75.5 * 100, 5);   // ~44.5%
    expect(r[2].given).toBeCloseTo(13.5 / 33.6 * 100, 5);
  });
  it("a missing price suppresses the conditional with a 'no quote' note (never silent)", () => {
    const r = condRungRows(chain([
      { layer: "A", display_pct: 50 },
      { layer: "B", display_pct: null },   // missing → its own conditional blank
      { layer: "C", display_pct: 10 },     // prev missing → also blank
    ]));
    expect(r[1]).toMatchObject({ reaching: null, given: null, note: "no quote" });
    expect(r[2]).toMatchObject({ given: null, note: "no quote" });
  });
  it("an inverted ladder (deeper above broader) shows a visible suppression, never a >100% ratio", () => {
    const r = condRungRows(chain([{ layer: "A", display_pct: 30 }, { layer: "B", display_pct: 40 }]));
    expect(r[1].given).toBeNull();
    expect(r[1].note).toBe("inverted — suppressed");
  });
  it("carries the quote-quality per rung", () => {
    const r = condRungRows(chain([{ layer: "A", display_pct: 50, quote: "Wide" }]));
    expect(r[0].quote).toBe("Wide");
  });
});
