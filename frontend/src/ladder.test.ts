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
