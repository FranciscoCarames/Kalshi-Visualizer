# Bake-off component spec (identical in every prototype)

Each app implements the **Terminal Pro Opportunity-surface slice** — the perf-critical core where lag shows —
using the shared `tokens.css` class contract, the shared `data.ts` rows, the shared `stream.ts` UpdateSource,
and the shared `perf.ts` overlay. The ONLY thing that differs per app is the framework's reactivity wiring.

Layout (top → bottom): `.tp-cmd` command line · `.tp-scanbar` · `.tp-stat` trust line (with the full
`GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS` disclaimer) · `.tp-bar2`
surface tabs + lens switcher · `.tp-tiles` · `.tp-ws` workspace:
- **Blotter** (`.tp-bl`): the streaming dense grid — **AG Grid** (`apps/react|solid|svelte|vue`) or
  **Glide canvas** (`apps/react-canvas`). Bucket tabs (`.tp-bt`). Lens re-sorts. Cell-flash on streamed change.
- **MD ladder** (`.tp-la`): `READ-ONLY DEPTH VIEW — NO ORDERS` banner; depth around the selected row's touch.
- **DES trade card** (`.tp-de`): legs · 9-dim confidence (`.cf`) · scenario · evidence · $1⇄$100.
- **Watch/Movers** (`.tp-wa`) + **Alerts** (`.tp-al`).

Wiring contract (the measured part):
1. Subscribe to `stream`. On each `Batch`, apply ONLY `batch.changed` to the grid (transaction/fine-grained
   update — never a full re-render), flash the changed cells, then call `perf.recordLatency(performance.now() - batch.t0)`
   and `perf.recordBatch()`.
2. On `batch.reset` (stress/source change), replace the full row set.
3. `perf.mount(onStress, onMode)` → `onStress(rows, rate)` calls `stream.setStress`; `onMode` calls `stream.setMode`.
4. Row select → render ladder + card from that row.

Invariants (visual): read-only, no order-entry controls, label discipline, Actionable/Review/Blocked/Research
separation, $1 basis. Real data via the Vite `/api` proxy (read-only) in poll mode; synthetic stream is the default.
