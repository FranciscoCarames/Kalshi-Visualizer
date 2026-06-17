/* Live feed subscription (real-time Stage 1): push via Server-Sent Events, with a polling fallback after
 * repeated stream errors. The browser's EventSource carries the same-origin session cookie, so it
 * authenticates exactly like loadFeed()'s fetch. This keeps Stage 1 a strict SUPERSET of polling — if the
 * stream never connects (or dies), the UI still refreshes on the same cadence it does today.
 *
 * Extracted from the provider so the transport logic is unit-testable: EventSource is injectable via
 * opts.makeES, and the poll/fallback transitions are exercised without rendering React. */
import { loadFeed, type Feed } from "./feed";

export interface StreamHandle {
  close: () => void;
}

export interface StreamOpts {
  pollMs: number;                              // fallback polling cadence (the auto-refresh interval)
  errorThreshold?: number;                     // consecutive SSE errors before falling back to polling (default 3)
  url?: string;                                // override the stream URL (tests)
  makeES?: (url: string) => EventSource;       // inject a fake EventSource (tests)
}

/* Subscribe to the live terminal feed. Returns a handle whose close() tears down the stream and any
 * fallback poll. onFeed receives each fresh Feed; onError receives an error string, or null to clear. */
export function subscribeFeed(
  onFeed: (f: Feed) => void,
  onError: (e: string | null) => void,
  opts: StreamOpts,
): StreamHandle {
  const threshold = opts.errorThreshold ?? 3;
  const url = opts.url ?? "/api/terminal/stream";
  const make = opts.makeES ?? ((u: string) => new EventSource(u));
  let closed = false;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let errors = 0;

  const pull = () =>
    loadFeed()
      .then((f) => { if (!closed) { onFeed(f); onError(null); } })
      .catch((e) => { if (!closed) onError(String(e)); });

  const startPolling = () => { if (!pollTimer && !closed) pollTimer = setInterval(pull, opts.pollMs); };
  const stopPolling = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } };

  es = make(url);
  es.addEventListener("feed", (e: MessageEvent) => {
    if (closed) return;
    errors = 0;                                // a healthy push cancels the fallback (no double-update)
    stopPolling();
    try { onFeed(JSON.parse(e.data) as Feed); onError(null); }
    catch (err) { onError(String(err)); }
  });
  es.onerror = () => {
    // EventSource auto-reconnects on transient errors; only after the connection is repeatedly unhealthy
    // do we give up on it and fall back to polling so the feed still refreshes.
    if (closed) return;
    errors += 1;
    if (errors >= threshold && !pollTimer) {
      es?.close();
      es = null;
      pull();                                  // immediate refresh, then keep polling on the cadence
      startPolling();
    }
  };

  return {
    close: () => { closed = true; es?.close(); es = null; stopPolling(); },
  };
}
