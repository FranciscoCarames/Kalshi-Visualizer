import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { subscribeFeed } from "./stream";
import type { Feed } from "./feed";

// loadFeed is the polling-fallback path; mock it so no network is touched.
const loadFeed = vi.fn<[], Promise<Feed>>();
vi.mock("./feed", () => ({ loadFeed: () => loadFeed() }));

const FEED = (id: number): Feed => ({ meta: { snapshot_id: id } as Feed["meta"], opps: [] });

/* Minimal fake EventSource: captures the named "feed" listener + onerror, and lets the test drive them. */
class FakeES {
  url: string;
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  private listeners: Record<string, (e: MessageEvent) => void> = {};
  constructor(url: string) { this.url = url; FakeES.last = this; }
  addEventListener(type: string, fn: (e: MessageEvent) => void) { this.listeners[type] = fn; }
  close() { this.closed = true; }
  emitFeed(data: unknown) { this.listeners["feed"]?.({ data: JSON.stringify(data) } as MessageEvent); }
  emitError() { this.onerror?.({}); }
  static last: FakeES | null = null;
}

describe("subscribeFeed (SSE transport + polling fallback)", () => {
  beforeEach(() => { vi.useFakeTimers(); loadFeed.mockReset().mockResolvedValue(FEED(99)); FakeES.last = null; });
  afterEach(() => { vi.useRealTimers(); });

  it("delivers a pushed feed event to onFeed (no polling while healthy)", () => {
    const onFeed = vi.fn(); const onError = vi.fn();
    const h = subscribeFeed(onFeed, onError, { pollMs: 1000, makeES: (u) => new FakeES(u) as unknown as EventSource });
    FakeES.last!.emitFeed(FEED(7));
    expect(onFeed).toHaveBeenCalledWith(expect.objectContaining({ meta: { snapshot_id: 7 } }));
    expect(onError).toHaveBeenLastCalledWith(null);
    // healthy stream → no poll scheduled → loadFeed never called by the fallback
    vi.advanceTimersByTime(5000);
    expect(loadFeed).not.toHaveBeenCalled();
    h.close();
    expect(FakeES.last!.closed).toBe(true);
  });

  it("falls back to polling after the error threshold and closes the stream", async () => {
    const onFeed = vi.fn(); const onError = vi.fn();
    subscribeFeed(onFeed, onError, { pollMs: 1000, errorThreshold: 3, makeES: (u) => new FakeES(u) as unknown as EventSource });
    const es = FakeES.last!;
    es.emitError(); es.emitError();
    expect(es.closed).toBe(false);                 // below threshold → still trusting the stream
    expect(loadFeed).not.toHaveBeenCalled();
    es.emitError();                                 // 3rd error → give up, poll instead
    expect(es.closed).toBe(true);
    expect(loadFeed).toHaveBeenCalledTimes(1);       // immediate refresh on fallback
    await vi.advanceTimersByTimeAsync(2000);          // two more poll ticks
    expect(loadFeed).toHaveBeenCalledTimes(3);
  });

  it("a healthy push after errors cancels the fallback poll (no double-update)", async () => {
    const onFeed = vi.fn(); const onError = vi.fn();
    subscribeFeed(onFeed, onError, { pollMs: 1000, errorThreshold: 2, makeES: (u) => new FakeES(u) as unknown as EventSource });
    const es = FakeES.last!;
    es.emitError(); es.emitError();                  // → fallback polling started (one immediate pull)
    expect(loadFeed).toHaveBeenCalledTimes(1);
    es.emitFeed(FEED(3));                            // a fresh push arrives → stop polling
    expect(onFeed).toHaveBeenCalledWith(expect.objectContaining({ meta: { snapshot_id: 3 } }));
    await vi.advanceTimersByTimeAsync(3000);
    expect(loadFeed).toHaveBeenCalledTimes(1);        // polling stopped — no further ticks after the push
  });

  it("close() stops everything and ignores later events", () => {
    const onFeed = vi.fn(); const onError = vi.fn();
    const h = subscribeFeed(onFeed, onError, { pollMs: 1000, makeES: (u) => new FakeES(u) as unknown as EventSource });
    const es = FakeES.last!;
    h.close();
    es.emitFeed(FEED(1));
    es.emitError();
    expect(onFeed).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5000);
    expect(loadFeed).not.toHaveBeenCalled();
  });
});
