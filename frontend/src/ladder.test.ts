import { describe, it, expect } from "vitest";
import { levelsFrom, firstBookableLeg, legLabel } from "./Ladder";
import type { OrderbookData } from "./detail";
import type { FeedLeg } from "./feed";

const ob = (yes: number[][], no: number[][]): OrderbookData =>
  ({ ticker: "TK", yes, no, ok: true, error: null, age_s: 0 });

describe("levelsFrom — real Kalshi book → YES ladder (no synthetic rungs)", () => {
  it("renders YES bids verbatim and YES asks = NO bids inverted (100 − no price)", () => {
    // NO bids at 37¢ and 39¢ → YES asks at 63¢ and 61¢. YES bids at 58¢, 60¢.
    const { rows, bestBid, bestAsk } = levelsFrom(ob([[58, 100], [60, 40]], [[37, 80], [39, 25]]));
    const byPrice = Object.fromEntries(rows.map((r) => [r.p, r]));
    expect(byPrice[60].bid).toBe(40);
    expect(byPrice[63].ask).toBe(80);    // 100 − 37
    expect(byPrice[61].ask).toBe(25);    // 100 − 39
    // best bid = highest YES bid; best ask = lowest YES ask = from the HIGHEST NO bid (39¢ → 61¢)
    expect(bestBid).toBe(60);
    expect(bestAsk).toBe(61);
  });
  it("rows are sorted high → low price", () => {
    const { rows } = levelsFrom(ob([[58, 1], [60, 1]], [[37, 1]]));
    expect(rows.map((r) => r.p)).toEqual([63, 60, 58]);
  });
  it("empty book → no rows, no touch (honest empty, never fabricated)", () => {
    const { rows, bestBid, bestAsk } = levelsFrom(ob([], []));
    expect(rows).toEqual([]);
    expect(bestBid).toBeNull();
    expect(bestAsk).toBeNull();
  });
  it("null book → empty", () => {
    expect(levelsFrom(null).rows).toEqual([]);
  });
});

describe("firstBookableLeg — skip no-ticker comparator legs, keep real markets incl. Tie", () => {
  const L = (tk?: string, side = "buy_no"): FeedLeg => ({ side, tk });
  it("returns the first leg with a non-empty ticker", () => {
    expect(firstBookableLeg([L(""), L("KX-A")])).toBe(1);     // outright: leg 0 empty, leg 1 bookable
    expect(firstBookableLeg([L("KX-H"), L("KX-TIE"), L("KX-A")])).toBe(0);
  });
  it("keeps a real Tie/Draw market (it has a ticker)", () => {
    expect(firstBookableLeg([L(""), L("KX-TIE", "buy_no")])).toBe(1);
  });
  it("falls back to 0 when no leg has a ticker", () => {
    expect(firstBookableLeg([L(""), L("")])).toBe(0);
  });
});

describe("legLabel — book-only pseudo-legs read as 'book · …', not a trade side", () => {
  it("labels a book-only leg without a YES/NO side or price", () => {
    expect(legLabel({ bo: true, c: "Deeper market", tk: "KX-C" }, 0)).toBe("book · Deeper market");
    expect(legLabel({ bo: true, tk: "KX-C" }, 0)).toBe("book · KX-C");
  });
  it("labels a real leg with side + contract + price", () => {
    expect(legLabel({ side: "buy_no", c: "No fade", p: 12 }, 0)).toBe("NO · No fade @ 12¢");
  });
});

import { chainRungs } from "./detail";
import { resolveBookTicker } from "./Ladder";
import type { DetailBundle } from "./detail";

const bundle = (chain: Record<string, unknown>[]): DetailBundle =>
  ({ chain, indicators: [], spreads: [], expected: [], contracts: [], raw_fields: [], link_audit: [], duplicates: [], rules: [] });

describe("chainRungs — selectable ladder rungs with a real ticker, broad→deep", () => {
  it("keeps only ticker-bearing rungs and preserves chain order", () => {
    const r = chainRungs(bundle([
      { layer: "Reach R32", market_ticker: "KX-R32", display_pct: 75.5 },
      { layer: "Reach R16", market_ticker: "", display_pct: 33.6 },       // no ticker → dropped
      { layer: "Win", market_ticker: "KX-WIN", display_pct: 0.4 },
    ]));
    expect(r.map((x) => x.layer)).toEqual(["Reach R32", "Win"]);
    expect(r[0]).toEqual({ layer: "Reach R32", ticker: "KX-R32", display_pct: 75.5 });
    expect(r[1].display_pct).toBe(0.4);
  });
  it("null bundle / empty chain → no rungs", () => {
    expect(chainRungs(null)).toEqual([]);
    expect(chainRungs(bundle([]))).toEqual([]);
  });
  it("non-numeric display_pct → null", () => {
    expect(chainRungs(bundle([{ layer: "X", market_ticker: "KX-X", display_pct: null }]))[0].display_pct).toBeNull();
  });
});

describe("resolveBookTicker — picked rung overrides leg, else leg, else first rung", () => {
  const rungs = [{ layer: "R32", ticker: "KX-R32", display_pct: 75 }, { layer: "Win", ticker: "KX-WIN", display_pct: 1 }];
  it("a picked rung wins", () => {
    expect(resolveBookTicker("KX-WIN", "KX-LEG", rungs)).toBe("KX-WIN");
  });
  it("no pick → the row's own leg ticker", () => {
    expect(resolveBookTicker(null, "KX-LEG", rungs)).toBe("KX-LEG");
  });
  it("no pick and no leg → the first rung", () => {
    expect(resolveBookTicker(null, "", rungs)).toBe("KX-R32");
  });
  it("nothing available → empty", () => {
    expect(resolveBookTicker(null, "", [])).toBe("");
  });
});
