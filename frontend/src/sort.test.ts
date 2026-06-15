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
