import { describe, it, expect } from "vitest";
import { fmtVal, centsToDollars } from "./columns";

describe("cmoney formatter — cents value rendered as display dollars", () => {
  it("renders positive cents as dollars", () => {
    expect(fmtVal(175, "cmoney")).toBe("$1.75");      // taker fee at 50c x100
    expect(fmtVal(63, "cmoney")).toBe("$0.63");
    expect(fmtVal(5, "cmoney")).toBe("$0.05");        // per-unit net edge in $
  });
  it("renders negatives with the sign BEFORE the $ (not $-0.12)", () => {
    expect(fmtVal(-12, "cmoney")).toBe("-$0.12");
    expect(centsToDollars(-175)).toBe("-$1.75");
  });
  it("never shows -$0.00 and treats sub-rounding values as $0.00", () => {
    expect(fmtVal(-0.4, "cmoney")).toBe("$0.00");
    expect(fmtVal(0, "cmoney")).toBe("$0.00");
  });
  it("null / NaN / blank render as the em-dash placeholder", () => {
    expect(fmtVal(null, "cmoney")).toBe("—");
    expect(fmtVal("", "cmoney")).toBe("—");
    expect(fmtVal(undefined, "cmoney")).toBe("—");
  });
});
