import { describe, expect, it } from "vitest";
import { dollars, money } from "./paper";

describe("paper.dollars", () => {
  it("formats positive cents as a signed dollar string", () => {
    expect(dollars(5)).toBe("+$0.05");
    expect(dollars(125)).toBe("+$1.25");
    expect(dollars(0)).toBe("+$0.00");
  });
  it("formats negative cents with a leading minus", () => {
    expect(dollars(-5)).toBe("-$0.05");
    expect(dollars(-1234)).toBe("-$12.34");
  });
  it("renders null/undefined as an em dash", () => {
    expect(dollars(null)).toBe("—");
    expect(dollars(undefined)).toBe("—");
  });
});

describe("paper.money (unsigned cost)", () => {
  it("formats cents as an unsigned dollar string", () => {
    expect(money(95)).toBe("$0.95");
    expect(money(0)).toBe("$0.00");
  });
  it("renders null/undefined as an em dash", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
  });
});
