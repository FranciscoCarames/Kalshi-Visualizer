---
slug: real-time-opportunity-engine
created: 2026-06-02
last_updated: 2026-06-03
status: active
---

# Topic: real-time-opportunity-engine

## What This Is

Generalize the Kalshi app from a French Open / tennis viewer into a **real-time, multi-category
structural-opportunity engine** for a small private group of traders. Longer-term vision in
[`docs/ROADMAP.md`](../../../docs/ROADMAP.md); the **concrete, approved build path** is the 6-stage roadmap
in `~/.claude/plans/make-me-a-multi-atomic-tower.md`.

**UN-PARKED 2026-06-03 — build started.** Detection groundwork already shipped (on `main` via PR #35): a
sport-agnostic dutch-book/MECE detector (incl. per-game) + multi-sport (tennis/NBA/WNBA) — i.e. part of the
"category-agnostic detector subsumes the containment ladder" success-bar item. The roadmap now drives the
rest: stable opportunity IDs + SQLite snapshot store → cross-sport scanner → lifecycle (alerts + recently-
actionable) → **FastAPI REST API** → **NiceGUI dashboard** (Streamlit retired) → export overhaul.

## Goal

A shared, push-based (WebSocket) engine that scans the whole Kalshi universe slowly via REST to find
where structural edges *could* exist, then streams only the hot subset to confirm them live, ranks
**net-of-fees** opportunities, and presents them to multiple traders in a dense, flash-on-change blotter.
General **detection** across all sports + all Kalshi categories — not streaming every market.

## Success Bar

- Opportunities ranked by **net edge after Kalshi fees** (never gross).
- A **category-agnostic dutch-book / sum-to-one detector** subsumes the tennis containment ladder.
- A **shared async backend** holds the Kalshi WS subscriptions + detection engine; multiple traders
  connect as thin clients (one upstream subscription, fan-out — fixes the per-process rate limiter).
- Latency: opportunities surface within **a few seconds**, and important new edges are **visually
  unmissable**.
- Read-only throughout; fully-automated execution is explicitly very-long-term (P4.4).

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-02 | Audience = small private group; latency target = a few seconds; read-only now, auto-execution only very-long-term; scope = all sports + all Kalshi categories | User-set roadmap parameters (AskUserQuestion) |
| 2026-06-02 | Decouple into one shared backend + thin clients | Multi-user + few-second + all-categories each break the Streamlit monolith; WS requires API keys + shared state |
| 2026-06-02 | Net-of-fees edge + dutch-book detector come BEFORE any rearchitecture (Phase 0) | Cheap, pure-module, fix the real credibility gaps, validate the general engine first |
| 2026-06-02 | Two-tier funnel: scan-wide-slow (REST) + stream-narrow-fast (WS) | Cannot poll or stream the whole ~10.5k-series universe; Basic tier ~20 GET/s |
| 2026-06-02 | Frontend: NiceGUI first, full React/SolidJS + AG Grid + TradingView Lightweight Charts as end-state | Reuse Python core, get real flash-on-change blotter without a JS build; pay for React only when group grows / toward execution |
| 2026-06-03 | Un-park; execute the 6-stage roadmap (`make-me-a-multi-atomic-tower.md`). Confirmed **NiceGUI mounted on FastAPI**; FastAPI also exposes the engine as REST | Owner approved a concrete, scoped build path; the parallel `dashboard-usability` topic closed pointing here ("backend change is critical path now") |
| 2026-06-03 | **First phase is pragmatic: FastAPI REST + polling (not WebSocket yet) + gross-edge first (net-of-fees deferred).** WS push + net-of-fees remain the end-state success bar | Engine-first, ship value incrementally; polling is fine for a few-second target now; fees add complexity without near-term payoff |
| 2026-06-03 | Engine-first sequencing: schema+store, cross-sport scanner, lifecycle built on the existing Streamlit app (UI-agnostic); UI migrates to NiceGUI at Stage 5 | Avoids throwaway Streamlit polish; the pure engine + SQLite store + FastAPI API survive the UI swap |
| 2026-06-03 | `opportunity_id` is node/stage-based (one shared `data.opportunity_id` sha1 helper), NOT market-ticker based; unmapped-match rows disambiguate on event ticker | Node-based id survives a representative-market flip → tracks the same *logical* opportunity across refreshes (needed for Stage-3 lifecycle); ticker-based would churn. (s1) |
| 2026-06-03 | `store.py` is pandas-free (DataFrame duck-typed) with deterministic time — retention/windows measured from the newest stored snapshot, not wall-clock | Keeps the store standalone/unit-testable and reproducible; full-row JSON blob (NaN→null) + promoted indexed columns. (s1) |
| 2026-06-03 | Engine modules stay UI/network-free via DEPENDENCY INJECTION — `scanner.unified_opportunities(fetch_fn, store_writer, ...)`; app passes cached `load_contracts` + `store.write_snapshot`, tests pass stubs | Pure modules survive the NiceGUI swap and are offline-testable; no `scanner`→`app`/`streamlit`/`kalshi_client` import. (s2; the pattern lifecycle/api will follow) |
| 2026-06-03 | Interim Streamlit surfacing is ADDITIVE + toggle-gated, never a rebuild; new engine views slot in as opt-in sections, single-sport dashboard untouched | Stage 5 replaces the UI with NiceGUI — don't polish throwaway Streamlit. (s2; lifecycle UI follows the same rule) |
| 2026-06-03 | Lifecycle/history features DERIVE from the persisted snapshot history — no extra mutable state/tables | first-seen / new / recently-actionable are all computable from snapshots; avoids migrations. Mutable "until acknowledged" state deferred to the UI layer (s3) |
| 2026-06-04 | The store is the source of truth: API/UI read the latest persisted snapshot; a single guarded `POST /scan` (store-backed TTL) is the only fetch trigger; coverage persisted in snapshot `meta`, reported honestly (`meta_present`) | Fast/deterministic/decoupled reads, sane after restart, honest coverage across mixed writers. (s4) |
| 2026-06-04 | The store evolves via real VERSIONED migrations (fresh DB created at current schema; older versions get incremental `ALTER` steps); both paths tested | A naive version bump marks a fresh DB current without the new column — must test fresh + upgrade. (s4) |

## Out of Scope

- Streaming the entire exchange at once (impossible; detection is general, streaming is narrow).
- Showing any edge **gross** of fees.
- Fully-automated order placement (deferred to P4.4, separate design doc, trading-scoped keys + risk
  controls).
- A conditional-probability / de-vig pricing model (structural inconsistencies only).

---
*Created via new-topic on 2026-06-02*
