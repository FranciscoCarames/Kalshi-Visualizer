import { describe, expect, it } from "vitest";
import { dollars } from "./paper";

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
