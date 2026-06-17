---
topic: real-time-opportunity-engine
created: 2026-06-02
---

# Seeds: real-time-opportunity-engine

Parked items. **Every seed must have a trigger condition.** Roadmap phases live here as backlog until
promoted to a milestone. Full detail in `docs/ROADMAP.md`.

| ID | Item | Trigger | Captured |
|---|---|---|---|
| S1 | **Phase 0** — net-of-fees edge + dutch-book/sum-to-one detector + honest sizing + read-only API-key client | When you sit down to start building this topic (first milestone) | 2026-06-02 |
| S2 | **Phase 1** — async shared backend (FastAPI + httpx + websockets), WS ingestion, in-memory order books, scan-wide/stream-narrow funnel, shared rate limiter | After Phase 0 ships and the general detector is validated offline | 2026-06-02 |
| S3 | **Phase 2** — trader-grade frontend: pick view tier (NiceGUI first), dense flash-on-change blotter sorted by net edge, book-depth drill-down, unmissable new-edge treatment | After Phase 1 backend serves snapshot+delta over WS | 2026-06-02 |
| S4 | **Phase 3** — category breadth: detector-as-strategy plugin model, sports/politics/econ/weather adapters, settlement-rule equivalence hardening | After Phases 1–2 prove the engine on tennis end-to-end | 2026-06-02 |
| S5 | **Phase 4** — history (DuckDB / edge-persistence backtest), alerting, cross-platform (Polymarket) identity matching, and very-long-term execution (P4.4) | When the read-only engine is stable and a specific extension is wanted | 2026-06-02 |
| S6 | Verify Kalshi **fee formula** (current schedule, per-category diffs) | Before coding net-of-fees edge (start of Phase 0) | 2026-06-02 |
| S7 | Verify **WS max-subscriptions/connection** and whether WS is metered separately from REST buckets | Before designing the stream-narrow side of Phase 1 | 2026-06-02 |
| S8 | Update CLAUDE.md **scope guard** (it currently forbids auth/all-sports/etc.) to match each phase as approved | When a phase is promoted to a milestone | 2026-06-02 |
| ~~S9~~ | **Doc reconciliation** — ✅ DONE & MERGED 2026-06-03 (**PR #36**, `main`@aae8990). 4 docs reconciled to tennis+NBA+WNBA+dutch-book+Stage 0; roadmap labelled planned; m1.1 #5 per-game flip folded in. **STILL PENDING (manual, owner-only):** re-publish the 2 Google Docs from the updated `docs/` mirrors (connector read-only). | merged; gdocs re-publish pending | 2026-06-03 |
