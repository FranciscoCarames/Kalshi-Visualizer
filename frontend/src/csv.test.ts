import { describe, it, expect } from "vitest";
import { csvCell, buildCsv } from "./csv";
import type { Col } from "./columns";
import type { FeedRow } from "./feed";

const col = (f: string, l: string, fmt: string): Col => ({ f, l, fmt: fmt as Col["fmt"] });
const row = (o: Record<string, unknown>): FeedRow => o as unknown as FeedRow;

describe("csvCell — money scaling", () => {
  it("scales cmoney (cents) to dollars to match the $ header", () => {
    const c = col("fees", "Est. fees $", "cmoney");
    expect(csvCell(c, row({ fees: 842 }))).toBe("8.42");
    expect(csvCell(c, row({ fees: -2 }))).toBe("-0.02");
    expect(csvCell(c, row({ fees: 0 }))).toBe("0.00");
    expect(csvCell(c, row({ fees: "175" }))).toBe("1.75");   // numeric string also scaled
  });
  it("does NOT scale already-dollar 'money' columns", () => {
    expect(csvCell(col("net_profit", "Est. net max profit", "money"), row({ net_profit: -2.96 }))).toBe("-2.96");
  });
  it("leaves cents '¢' and other numeric formats raw", () => {
    expect(csvCell(col("edge", "Gross edge ¢", "c"), row({ edge: 4 }))).toBe("4");
    expect(csvCell(col("roi", "ROI %", "pct"), row({ roi: 0.3 }))).toBe("0.3");
    expect(csvCell(col("units", "Max units", "num"), row({ units: 136.57 }))).toBe("136.57");
    expect(csvCell(col("convexity", "Payout÷cost", "x"), row({ convexity: 33.3 }))).toBe("33.3");
  });
  it("empty/null/undefined/NaN cmoney → empty cell (no 'NaN', no 0)", () => {
    const c = col("net_edge", "Est. net edge $", "cmoney");
    expect(csvCell(c, row({}))).toBe("");
    expect(csvCell(c, row({ net_edge: null }))).toBe("");
    expect(csvCell(c, row({ net_edge: undefined }))).toBe("");
    expect(csvCell(c, row({ net_edge: "" }))).toBe("");
    expect(csvCell(c, row({ net_edge: "abc" }))).toBe("");
  });
});

describe("csvCell — formula-injection defense (text cells only)", () => {
  const name = col("name", "Participant / market", "name");
  it("neutralises a leading formula trigger on text cells", () => {
    expect(csvCell(name, row({ name: "=cmd()" }))).toBe("'=cmd()");
    expect(csvCell(name, row({ name: "+1+1" }))).toBe("'+1+1");
    expect(csvCell(name, row({ name: "-2+3" }))).toBe("'-2+3");
    expect(csvCell(name, row({ name: "@SUM" }))).toBe("'@SUM");
    expect(csvCell(name, row({ name: "\tx" }))).toBe("'\tx");
  });
  it("leaves benign text untouched", () => {
    expect(csvCell(name, row({ name: "Boston vs Seattle" }))).toBe("Boston vs Seattle");
  });
  it("does NOT prefix numeric columns even when negative (they're our own safe values)", () => {
    expect(csvCell(col("net_edge", "Est. net edge $", "cmoney"), row({ net_edge: -2 }))).toBe("-0.02");
    expect(csvCell(col("edge", "Gross edge ¢", "c"), row({ edge: -3 }))).toBe("-3");
  });
});

describe("csvCell — synthetic basis_flags column", () => {
  it("emits the honesty chips", () => {
    const c = col("basis_flags", "Basis", "text");
    expect(csvCell(c, row({ midpoint_only: true, wide_basis: true }))).toBe("MID-ONLY WIDE");
    expect(csvCell(c, row({ midpoint_only: true }))).toBe("MID-ONLY");
    expect(csvCell(c, row({}))).toBe("");
  });
});

describe("buildCsv — full document (covers exportView AND exportSelected: both call this)", () => {
  const cols = [col("name", "Participant / market", "name"), col("fees", "Est. fees $", "cmoney"), col("caveat", "Caveat", "text")];
  it("header + scaled rows, with CSV quoting for commas and injection-guarded text", () => {
    const out = buildCsv([
      row({ name: "Boston vs Seattle", fees: 842, caveat: "postponement risk, review rules" }),
      row({ name: "=evil()", fees: -2, caveat: "ok" }),
    ], cols);
    const lines = out.split("\n");
    expect(lines[0]).toBe("Participant / market,Est. fees $,Caveat");
    expect(lines[1]).toBe('Boston vs Seattle,8.42,"postponement risk, review rules"');   // comma → quoted; cents → $
    expect(lines[2]).toBe("'=evil(),-0.02,ok");                                          // formula neutralised
  });
});
