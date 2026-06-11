/* Pluggable UpdateSource — the no-lag stress engine. Frame-agnostic.
   sources: synthetic (default) · poll(GET /api/opportunities) · sse-stub(GET /api/stream).
   The real SSE (backend perf plan Phase 4) drops in behind this interface with zero view change. */
import { genRows, loadReal, type Row } from "./data";

export type Mode = "synthetic" | "poll" | "sse";
export interface Batch { t0: number; changed: Row[]; reset?: boolean; }
type Cb = (b: Batch) => void;

export interface Stream {
  rows: Row[];
  subscribe(cb: Cb): () => void;
  start(): void;
  stop(): void;
  setStress(nRows: number, rate: number): void;
  setMode(m: Mode): void;
  mode: Mode;
}

export function createStream(initialRows = 200, initialRate = 30): Stream {
  let rows = genRows(initialRows);
  let rate = initialRate;
  let nRows = initialRows;
  let mode: Mode = "synthetic";
  let timer: any = null;
  const subs = new Set<Cb>();
  const emit = (b: Batch) => subs.forEach(cb => cb(b));

  // deterministic-ish counter (no Math.random in hot loop, keeps it cheap + reproducible)
  let tickN = 0;
  function syntheticTick() {
    tickN++;
    const k = Math.min(rows.length, Math.max(1, Math.round(rows.length * 0.02))); // ~2% of rows/tick
    const changed: Row[] = [];
    for (let i = 0; i < k; i++) {
      const idx = (tickN * 2654435761 + i * 40503) % rows.length;
      const r = rows[idx];
      const dir = (tickN + i) % 2 === 0 ? 1 : -1;
      r.edge = Math.max(0, +(r.edge + dir) );
      r.touch = Math.min(99, Math.max(1, r.touch + dir));
      r.chg = dir > 0 ? "up" : "down";
      r.spark = r.spark.slice(1).concat(r.touch);
      changed.push(r);
    }
    emit({ t0: performance.now(), changed });
  }

  function schedule() {
    stop();
    if (mode === "synthetic") {
      const ms = Math.max(4, Math.round(1000 / rate));
      timer = setInterval(syntheticTick, ms);
    } else if (mode === "poll") {
      timer = setInterval(async () => {
        try { const fresh = await loadReal(); rows = fresh; emit({ t0: performance.now(), changed: rows, reset: true }); }
        catch { /* backend not up — ignore */ }
      }, 2000);
    } else if (mode === "sse") {
      // forward-compat stub for the backend plan's Phase 4 GET /api/stream
      try {
        const es = new EventSource("/api/stream");
        es.onmessage = async () => { try { rows = await loadReal(); emit({ t0: performance.now(), changed: rows, reset: true }); } catch {} };
        timer = { close: () => es.close() };
      } catch { /* no SSE endpoint yet */ }
    }
  }

  return {
    get rows() { return rows; },
    get mode() { return mode; },
    subscribe(cb) { subs.add(cb); return () => subs.delete(cb); },
    start() { schedule(); },
    stop() { if (timer) { if (timer.close) timer.close(); else clearInterval(timer); timer = null; } },
    setStress(n, r) {
      nRows = n; rate = r;
      if (mode === "synthetic") { rows = genRows(n); emit({ t0: performance.now(), changed: rows, reset: true }); }
      schedule();
    },
    setMode(m) { mode = m; if (m === "synthetic") rows = genRows(nRows); schedule(); emit({ t0: performance.now(), changed: rows, reset: true }); },
  };
}
