import { describe, it, expect } from "vitest";
import { encodeUrl, decodeUrl, type UrlState } from "./url";

const state = (o: Partial<UrlState> = {}): UrlState =>
  ({ surface: "opp", zone: "exec", section: "act", lens: "", sports: [], tours: [], part: "", ...o });

describe("encodeUrl / decodeUrl", () => {
  it("encodes nothing for the default state", () => {
    expect(encodeUrl(state())).toBe("");
  });
  it("omits default surface/zone/section but keeps non-defaults", () => {
    expect(encodeUrl(state({ surface: "ops" }))).toBe("?surface=ops");
    expect(encodeUrl(state({ zone: "spec", section: "bounded" }))).toContain("section=bounded");
  });
  it("round-trips multi-selects + participant", () => {
    const s = state({ sports: ["NBA", "NFL"], tours: ["FIFA World Cup · 26"], part: "ghana", lens: "edge", surface: "res" });
    const decoded = decodeUrl(encodeUrl(s));
    expect(decoded.sports).toEqual(["NBA", "NFL"]);
    expect(decoded.tours).toEqual(["FIFA World Cup · 26"]);
    expect(decoded.part).toBe("ghana");
    expect(decoded.lens).toBe("edge");
    expect(decoded.surface).toBe("res");
  });
  it("decode returns only present keys (partial)", () => {
    const d = decodeUrl("?sport=NBA");
    expect(d.sports).toEqual(["NBA"]);
    expect(d.part).toBeUndefined();
    expect(d.lens).toBeUndefined();
  });
  it("tolerates empty / junk", () => {
    expect(decodeUrl("")).toEqual({});
    expect(decodeUrl("?sport=").sports).toEqual([]);
  });
});
