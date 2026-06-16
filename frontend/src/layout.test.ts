import { describe, it, expect } from "vitest";
import { cleanLayout, presetSnapshot, PANEL_IDS, DEFAULT_COLS } from "./layout";

describe("cleanLayout — defensive validation of a saved/hostile layout", () => {
  it("returns null for non-objects (caller fails open to a preset)", () => {
    expect(cleanLayout(null)).toBeNull();
    expect(cleanLayout("nope")).toBeNull();
    expect(cleanLayout(42)).toBeNull();
  });
  it("clamps colW (60..1000) and basis (24..2000)", () => {
    const c = cleanLayout({ colW: { M: 99999, R: 5 }, st: { "p-ladder": { basis: 9000 } } })!;
    expect(c.colW.M).toBe(1000);
    expect(c.colW.R).toBe(60);
    expect(c.st["p-ladder"].basis).toBe(2000);
  });
  it("drops unknown panel ids and DEDUPES (singleton) across columns", () => {
    const c = cleanLayout({ cols: { L: ["p-blotter", "p-blotter", "evil"], M: ["p-ladder", "p-blotter"], R: [] } })!;
    expect(c.cols.L[0]).toBe("p-blotter");            // first occurrence kept
    expect(c.cols.L).not.toContain("evil");           // unknown removed
    expect(c.cols.M).toEqual(["p-ladder"]);           // the 2nd p-blotter (dup) dropped — already placed in L
    // every known id appears EXACTLY ONCE across all columns (singleton invariant; missing ones restored)
    const all = [...c.cols.L, ...c.cols.M, ...c.cols.R];
    expect(new Set(all).size).toBe(all.length);
    expect(all.filter((x) => x === "p-blotter").length).toBe(1);
  });
  it("restores any known panel missing from cols to its default column (never vanishes)", () => {
    const c = cleanLayout({ cols: { L: ["p-blotter"], M: [], R: [] } })!;
    const all = [...c.cols.L, ...c.cols.M, ...c.cols.R].sort();
    expect(all).toEqual([...PANEL_IDS].sort());
    expect(c.cols.M).toContain("p-ladder");           // p-ladder restored to its home column M
  });
  it("coerces collapse/max/hidden to booleans and keeps a valid snapshot", () => {
    const c = cleanLayout({ st: { "p-des": { collapsed: 1, maxed: true, hidden: "yes" } } })!;
    expect(c.st["p-des"]).toMatchObject({ collapsed: false, maxed: true, hidden: false });
  });
});

describe("presetSnapshot", () => {
  it("default places all panels in their home columns", () => {
    const s = presetSnapshot("default");
    expect(s.cols).toEqual(DEFAULT_COLS);
    expect(Object.keys(s.st).sort()).toEqual([...PANEL_IDS].sort());
  });
  it("blotterfull hides the inspector and the M/R columns", () => {
    const s = presetSnapshot("blotterfull");
    expect(s.st["p-des"].hidden).toBe(true);
    expect(s.colHidden).toEqual({ M: true, R: true });
  });
  it("unknown name → default", () => {
    expect(presetSnapshot("zzz").colW).toEqual({ M: 330, R: 290 });
  });
});
