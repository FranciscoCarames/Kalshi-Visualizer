import { describe, it, expect } from "vitest";
import { fmtVal, centsToDollars, signalLabel, qualityOf, SIGNAL_LABELS } from "./columns";

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

describe("signalLabel — human-readable bounded-loss signal classes", () => {
  it("maps every known engine signal class (webui/viewmodel._signal_class)", () => {
    // The five raw values _signal_class can emit; all must have a friendly label.
    for (const raw of ["Candidate", "Breakeven", "Negative proxy", "Inverted / diagnostic", "Data quality"]) {
      expect(SIGNAL_LABELS[raw]).toBeTruthy();
      expect(signalLabel(raw)).toBe(SIGNAL_LABELS[raw]);
    }
    expect(signalLabel("Candidate")).toBe("Candidate setup");
    expect(signalLabel("Data quality")).toBe("Insufficient data");
  });
  it("falls through to the raw string for an unknown class (never blanks it)", () => {
    expect(signalLabel("Some New Class")).toBe("Some New Class");
  });
  it("renders an em-dash for empty / null", () => {
    expect(signalLabel("")).toBe("—");
    expect(signalLabel(null)).toBe("—");
    expect(signalLabel(undefined)).toBe("—");
  });
});

describe("qualityOf — single uncalibrated setup-quality diagnostic", () => {
  it("returns 'Insufficient data' (NOT Low) when ripeness is missing", () => {
    const q = qualityOf({ cond_child: 80 });
    expect(q.tier).toBe("n/a");
    expect(q.label).toBe("Insufficient data");
    expect(q.score).toBeNull();
  });
  it("returns 'Insufficient data' when the conditional is missing", () => {
    expect(qualityOf({ parent_over_maxloss: 5 }).tier).toBe("n/a");
  });
  it("blends ripeness × conditional fraction and tiers it", () => {
    expect(qualityOf({ parent_over_maxloss: 5, cond_child: 80 }).tier).toBe("High");   // 5 × 0.8 = 4.0
    expect(qualityOf({ parent_over_maxloss: 2, cond_child: 60 }).tier).toBe("Med");     // 2 × 0.6 = 1.2
    expect(qualityOf({ parent_over_maxloss: 1, cond_child: 50 }).tier).toBe("Low");     // 1 × 0.5 = 0.5
  });
  it("clamps a conditional above 100% to 1.0 (never amplifies)", () => {
    const q = qualityOf({ parent_over_maxloss: 3, cond_child: 140 });
    expect(q.score).toBe(3);                                                            // 3 × 1.0
  });
});
