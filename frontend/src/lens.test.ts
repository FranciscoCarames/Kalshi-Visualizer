import { describe, it, expect } from "vitest";
import { rankKey, applyLens, lensesFor } from "./lens";
import type { FeedRow } from "./feed";

const row = (id: string, o: Partial<FeedRow>): FeedRow => ({ id, bucket: "x", zone: "exec", section: "act", ...o });

describe("liquidity lenses — TOP QUOTE SIZE (units) + TOP-BOOK GROSS $ (notional)", () => {
  it("ranks by top quote size; rows with no size sort last", () => {
    const big = row("big", { units: 500, edge: 1 });
    const small = row("small", { units: 50, edge: 6 });
    const none = row("none", { edge: 9 });                       // no units → -1e9 → last
    expect(rankKey(big, "units")).toBe(500);
    expect(rankKey(small, "units")).toBe(50);
    expect(rankKey(none, "units")).toBe(-1e9);
    expect(applyLens([small, none, big], "units").map((r) => r.id)).toEqual(["big", "small", "none"]);
  });

  it("notional = gross edge × top quote units (so size AND edge both count)", () => {
    const thinBig = row("thinBig", { units: 50, edge: 6 });      // 300
    const deepSmall = row("deepSmall", { units: 500, edge: 1 }); // 500
    expect(rankKey(thinBig, "notional")).toBe(300);
    expect(rankKey(deepSmall, "notional")).toBe(500);
    // deepSmall outranks thinBig on notional, the reverse of pure EDGE¢
    expect(applyLens([thinBig, deepSmall], "notional").map((r) => r.id)).toEqual(["deepSmall", "thinBig"]);
    // a row missing either factor sorts last
    expect(rankKey(row("x", { units: 100 }), "notional")).toBe(-1e9);
  });

  it("engine order is recoverable (no lens) and applyLens does not mutate input", () => {
    const rows = [row("a", { units: 10 }), row("b", { units: 99 })];
    expect(applyLens(rows, "")).toBe(rows);                      // no-op → engine order
    const copy = [...rows];
    applyLens(rows, "units");
    expect(rows).toEqual(copy);                                  // sorts a copy
  });

  it("both lenses are offered on exec/spec zones and withheld from diagnostic", () => {
    const exec = lensesFor("exec").map(([k]) => k);
    expect(exec).toEqual(expect.arrayContaining(["units", "notional"]));
    expect(lensesFor("diag").map(([k]) => k)).not.toEqual(expect.arrayContaining(["units"]));
  });
});
