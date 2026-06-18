import { describe, it, expect } from "vitest";
import { sortRows, nextSort } from "./sort";
import type { FeedRow } from "./feed";
import type { Fmt } from "./columns";

const row = (id: string, o: Partial<FeedRow>): FeedRow => ({ id, bucket: "x", zone: "spec", section: "bounded", ...o });
const fmtOf = (f: string): Fmt => (f === "name" ? "name" : "num");

describe("sortRows", () => {
  const rows = [row("a", { edge: 3 }), row("b", { edge: 1 }), row("c", { edge: 2 }), row("d", {})];

  it("returns input unchanged when state is null (engine order)", () => {
    expect(sortRows(rows, null, fmtOf)).toBe(rows);
  });
  it("sorts numeric ascending with nulls last", () => {
    expect(sortRows(rows, { field: "edge", dir: "asc" }, fmtOf).map((r) => r.id)).toEqual(["b", "c", "a", "d"]);
  });
  it("sorts numeric descending with nulls STILL last", () => {
    expect(sortRows(rows, { field: "edge", dir: "desc" }, fmtOf).map((r) => r.id)).toEqual(["a", "c", "b", "d"]);
  });
  it("sorts strings case-insensitively, blanks last", () => {
    const r = [row("a", { name: "Beta" }), row("b", { name: "alpha" }), row("c", { name: "" })];
    expect(sortRows(r, { field: "name", dir: "asc" }, fmtOf).map((x) => x.id)).toEqual(["b", "a", "c"]);
  });
  it("does not mutate the input array", () => {
    const copy = [...rows];
    sortRows(rows, { field: "edge", dir: "asc" }, fmtOf);
    expect(rows).toEqual(copy);
  });
  it("sorts the DERIVED 'quality' column by its computed score (not the absent row field), blanks last", () => {
    // score = parent_over_maxloss × (cond_child/100): hi 5×0.8=4, mid 2×0.6=1.2, lo 1×0.5=0.5; n/a missing input
    const hi = row("hi", { parent_over_maxloss: 5, cond_child: 80 });
    const mid = row("mid", { parent_over_maxloss: 2, cond_child: 60 });
    const lo = row("lo", { parent_over_maxloss: 1, cond_child: 50 });
    const na = row("na", { cond_child: 90 });   // no ripeness → Insufficient data → last
    const rs = [mid, na, lo, hi];
    expect(sortRows(rs, { field: "quality", dir: "desc" }, fmtOf).map((r) => r.id)).toEqual(["hi", "mid", "lo", "na"]);
    expect(sortRows(rs, { field: "quality", dir: "asc" }, fmtOf).map((r) => r.id)).toEqual(["lo", "mid", "hi", "na"]);
  });
});

describe("nextSort (3-state cycle)", () => {
  it("none → asc → desc → none for the same field", () => {
    let s = nextSort(null, "edge");
    expect(s).toEqual({ field: "edge", dir: "asc" });
    s = nextSort(s, "edge");
    expect(s).toEqual({ field: "edge", dir: "desc" });
    s = nextSort(s, "edge");
    expect(s).toBeNull();
  });
  it("switching to a different field starts at asc", () => {
    expect(nextSort({ field: "edge", dir: "desc" }, "roi")).toEqual({ field: "roi", dir: "asc" });
  });
});
