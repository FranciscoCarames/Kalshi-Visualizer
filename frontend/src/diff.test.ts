import { describe, it, expect } from "vitest";
import { diffSnapshot, edgeMap } from "./diff";
import type { FeedRow } from "./feed";

const row = (id: string, edge?: number): FeedRow =>
  ({ id, bucket: "x", zone: "exec", section: "act", ...(edge === undefined ? {} : { edge }) });

describe("diffSnapshot (change-signal)", () => {
  it("first load flashes NOTHING (no all-NEW)", () => {
    const { change, flash } = diffSnapshot(new Map(), [row("a", 5), row("b", 3)], true);
    expect(change.size).toBe(0);
    expect(flash.size).toBe(0);
  });
  it("flags genuinely new ids as NEW", () => {
    const prev = edgeMap([row("a", 5)]);
    const { change, flash } = diffSnapshot(prev, [row("a", 5), row("b", 2)], false);
    expect(change.get("b")).toBe("new");
    expect(change.has("a")).toBe(false);          // unchanged edge → no signal
    expect(flash.has("b")).toBe(true);
    expect(flash.has("a")).toBe(false);
  });
  it("classifies edge up / down", () => {
    const prev = edgeMap([row("a", 5), row("b", 5)]);
    const { change } = diffSnapshot(prev, [row("a", 7), row("b", 2)], false);
    expect(change.get("a")).toBe("up");
    expect(change.get("b")).toBe("down");
  });
  it("a missing/NaN edge never produces a false up/down", () => {
    const prev = edgeMap([row("a", 5), row("b")]);     // b had no edge (NaN)
    const { change } = diffSnapshot(prev, [row("a"), row("b", 4)], false);
    expect(change.has("a")).toBe(false);               // a lost its edge → NaN compares false, no signal
    expect(change.has("b")).toBe(false);               // b prev was NaN → no signal
  });
  it("disappeared rows are not flashed (only current rows are considered)", () => {
    const prev = edgeMap([row("a", 5), row("gone", 9)]);
    const { change, flash } = diffSnapshot(prev, [row("a", 5)], false);
    expect(change.has("gone")).toBe(false);
    expect(flash.has("gone")).toBe(false);
  });
});
