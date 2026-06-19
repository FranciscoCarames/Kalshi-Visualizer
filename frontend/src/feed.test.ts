import { describe, it, expect } from "vitest";
import { SUBTABS, SECTION_BUCKET, TILES, rowsFor, sectionCount } from "./feed";
import type { FeedRow, FeedMeta } from "./feed";

const row = (o: Partial<FeedRow>): FeedRow =>
  ({ id: Math.random().toString(), bucket: "x", zone: "spec", section: "specmodel", ...o });

describe("speculative_model section taxonomy", () => {
  it("is a SPEC subtab mapped to the speculative_model bucket", () => {
    const spec = SUBTABS.spec.find((t) => t[0] === "specmodel");
    expect(spec).toEqual(["specmodel", "SPEC-MODEL", "speculative_model"]);
    expect(SECTION_BUCKET.specmodel).toBe("speculative_model");
    expect(TILES.some((t) => t[2] === "specmodel" && t[1] === "spec")).toBe(true);
  });

  it("rowsFor selects only spec/specmodel rows", () => {
    const opps = [
      row({ id: "a", section: "specmodel" }),
      row({ id: "b", section: "cheapno" }),
      row({ id: "c", zone: "exec", section: "act" }),
    ];
    const got = rowsFor(opps, "spec", "specmodel").map((o) => o.id);
    expect(got).toEqual(["a"]);
  });

  it("sectionCount reads the speculative_model bucket total", () => {
    const meta = { totals: { speculative_model: 3, no_structure: 5 } } as unknown as FeedMeta;
    expect(sectionCount(meta, "spec", "specmodel")).toBe(3);
  });
});
