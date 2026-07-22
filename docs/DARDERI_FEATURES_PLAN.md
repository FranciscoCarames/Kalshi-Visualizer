# Plan: Port Darderi-inspired analytics into the Kalshi Visualizer (React SPA)

> Status: **Proposed — to be implemented in the future.** Target front-end: the React SPA (`main/frontend`) only.

## Context

The **Darderi** project (a sibling tennis-trade signal generator) is built around several ideas the Kalshi
Visualizer doesn't fully express:

1. **Per-scenario P&L** — show profit/loss in *every* terminal settlement state, not just a single locked floor.
2. **A live "what-if" sandbox** — type hypothetical prices, watch the verdict + arithmetic update.
3. **Hedge-ratio sizing** — solve for leg sizes that balance outcomes, instead of equal units.
4. (Adjacent) **EV under a probability** — `Σ πᵢ·pnlᵢ` to value an uncertain state.

The Visualizer is the far more mature tool — a multi-sport, read-only arbitrage/inconsistency engine with a React
SPA terminal. The goal here is to **graft the genuinely additive Darderi ideas onto the SPA**, where they fill real
gaps:

- The per-scenario payoff table (`<PayoffChart>` + `/api/terminal/payoff`) exists **only for containment rows**;
  dutch-book, synthetic-bundle, and cheap-NO opportunities show nothing.
- There is **no what-if sandbox** — a trader can't ask "what if the ask were 3¢ lower?"
- Multi-leg dutch-book **field sizing is equal-units `min(leg sizes)`**, producing the fractional "MAX UNITS 136.6"
  that QA flagged (C2) and leaving locked profit on the table.

**Target front-end: the React SPA only** (`main/frontend`). Explicitly NOT NiceGUI or Streamlit.

### Hard guardrails (from `CLAUDE.md` + `AGENTS.md`)

- **PRIME INVARIANT — the SPA is a read-only view, never an engine.** All payoff / sizing / EV math lives in
  backend Python (`viz.py`, `dutchbook.py`, `consistency.py`, `webui/`). The frontend renders only.
- **Scope guard.** No trading/order placement, no net-of-fees *actionability*, no new probability/de-vig models
  **except** display-only, default-OFF, never-ranked ones (precedent: `conditional_blend`'s `speculative_model`).
  → Feature 4 (EV) is gated by this and treated as owner-opt-in.
- **Cents-exact.** All price math in integer cents / `Decimal`; floats are display-only.
- **Tests required** for any behavior change: `pytest -q` (backend) + `npm run test` (Vitest, frontend).
- **Git.** Branch from `origin/main`; never push to main; commit footer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

The four features are independent and ordered by value/risk. Each is its own PR.

---

## Feature 1 — Per-scenario P&L for every structure type (highest value, lowest risk)

**Today:** `viz.payoff_chart_data()` + `consistency.scenario_payoffs()` enumerate terminal states for **containment
and equivalence** rows only. `/api/terminal/payoff` returns honest-empty for dutch-books and synthetic bundles, so
the SPA's `<PayoffChart>` is blank for them. This is the single biggest "Darderi has it, we don't" gap.

**Change:** Give every executable structure a scenario breakdown, mirroring Darderi's four-state table.

- Backend (engine, pure, cents-exact):
  - Add a per-structure scenario enumerator. Prefer **one dispatcher** — e.g. `scenario_payoffs_for(opp)` in a new
    pure module `payoffs.py` (or extend `viz.py`) — that routes by `relationship_type`/`source`:
    - **dutch-book 2-way / 3-way / field** (`dutchbook.py`): enumerate "outcome k wins" states; each buys the floor;
      reuse the existing `cost_c`, `payout_floor_c`, and per-leg prices already computed in `_direction_candidate` /
      `_n_direction_candidate`. For an overround field the floor is `(n−1)×100¢` — show the one loser state.
    - **synthetic bundle** (`synthetic_bundle.py`): enumerate per-score states + the retirement/no-play "risk" state
      with `None` payout (the same `is_risk` convention `consistency.scenario_payoffs` already uses).
    - **containment / equivalence**: delegate to the existing `consistency.scenario_payoffs()` unchanged.
  - Keep the existing scenario dict shape (`scenario`, `payout_c`, `profit_c`, `role`/`is_bonus`/`is_risk`/
    `is_guaranteed_floor`) so `viz.payoff_chart_data()` and the SPA need no schema churn.
  - Wire `engine.payoff_for_opp()` (`webui/engine.py`) to call the dispatcher instead of the containment-only path,
    so `/api/terminal/payoff` is populated for all sources.
- Frontend (render-only):
  - `<PayoffChart>` (`frontend/src/Charts.tsx`) already renders `scenario / settles / payout / profit`. Verify it
    handles the `None`-payout risk row gracefully (blank, not `0`) and N>3 rows. Add a one-line caption per kind
    pulled from `relationship_explanation` so the table reads like Darderi's verdict block.
  - No new endpoint; `loadPayoff()` (`frontend/src/detail.ts`) is unchanged.

**Files:** `viz.py` (or new `payoffs.py`), `dutchbook.py`, `synthetic_bundle.py` (expose a state list),
`webui/engine.py`, `api.py` (only if the response model needs a nullable-payout tweak), `frontend/src/Charts.tsx`,
`frontend/src/Inspector.tsx` (caption).

**Tests:** extend `tests/test_viz.py` + a new `tests/test_payoffs.py` (one case per structure: 2-way under/over,
field overround, synthetic with risk row); `frontend/src/Charts.test.ts` for the None-payout + N-row rendering.

---

## Feature 2 — What-if price sandbox (cheap, self-contained)

**Today:** none. A trader cannot probe how close a blocked/near-edge row is to firing.

**Change:** A panel (Darderi `ui.py` analogue) where the user overrides one or more leg prices and sees the
recomputed cost / floor / gap / verdict + the substituted arithmetic — **computed on the backend** per the PRIME
INVARIANT.

- Backend: new `POST /api/terminal/what-if` in `api.py` taking `{opportunity_id, leg_price_overrides: {ticker→cents}}`,
  re-running the **same** pure cost/floor/gap math the scanner uses (reuse `dutchbook` / `consistency` helpers; do
  **not** fork the formula) and returning the recomputed scenario payoffs + `cost_c`, `payout_floor_c`, `exec_gap_c`,
  and a boolean `clears`. Read-only; no store writes; integer cents.
- Frontend: `<WhatIfSandbox>` (new `frontend/src/WhatIf.tsx`, loader in `detail.ts`) rendered after `<PayoffChart>`
  in the PARTICIPANT DETAIL tab. Number inputs seeded from the live leg prices; on change, POST and re-render a
  second `<PayoffChart>` plus a green/red verdict line showing `cost vs floor` with values substituted in
  (Darderi's "the gate" block). Clearly labelled **hypothetical**.

**Files:** `api.py`, `frontend/src/WhatIf.tsx` (new), `frontend/src/detail.ts`, `frontend/src/Inspector.tsx`.

**Tests:** `tests/test_api.py` (what-if recompute matches a hand-worked example; override that flips
clears False→True); `frontend/src/WhatIf.test.ts` (input → POST payload shape, verdict formatting).

---

## Feature 3 — Integer / optimal leg sizing for multi-leg fields (fixes QA C2)

**Today:** `dutchbook._n_direction_candidate` / `_direction_candidate` size every leg at `min(leg sizes)` (equal
units). For tournament-winner overround fields this both produces the **fractional "MAX UNITS 136.6"** QA flagged
(C2) and under-fills legs that have more depth.

**Change:** Apply Darderi's "size the legs deliberately" idea. Replace equal-units with an **integer per-leg unit
solver** that maximizes locked profit subject to each leg's top-of-book size and the floor guarantee, returning
**integer** unit counts per leg (no fractional contracts).

- Backend (engine, `dutchbook.py`): add a pure `optimal_field_units(legs, floor_c)` helper; keep the simple 2-way
  path as-is (already integer). Surface a per-leg `units` plan on the finding (extends `legs`), and make
  `exec_min_size` / `exec_max_profit_dollars` integer-consistent with it. Preserve the existing
  `payout_floor_c = (n−1)×100¢` semantics and the overround-only rule for not-provably-exhaustive fields.
- Frontend (render-only): show per-leg integer units in the TRADE CARD leg list and the depth ladder
  (`frontend/src/Inspector.tsx`, `Ladder.tsx`); the fractional MAX UNITS display disappears as a consequence.

**Files:** `dutchbook.py`, `webui/feed.py` (carry per-leg units onto `FeedLeg`), `frontend/src/feed.ts` (type),
`frontend/src/Inspector.tsx`, `frontend/src/Ladder.tsx`.

**Tests:** extend `tests/test_dutchbook.py` (integer plan, profit ≥ equal-units baseline, never exceeds per-leg
depth, 2-way unchanged); `frontend/src/inspector.test.ts` if leg rendering is asserted.

---

## Feature 4 — EV under probability for caveated rows (OWNER-GATED; do last, or defer)

**Today:** the engine is deliberately probability-free; `ev` exists only as an uncalibrated display proxy.
Darderi's `EV = Σ πᵢ·pnlᵢ` would value the unverified "risk" settlement state (synthetic bundle, match-alignment).

**Change (only with owner sign-off, mirroring the `conditional_blend` exception):** for caveated rows that already
carry a `None`-payout risk state, let the user supply a single probability for that state and display an EV beside
the floor — **display-only, default-OFF, never ranked, walled off to caveated rows.** It must never feed bucketing
or ranking and must be visually marked speculative.

- Backend: a pure `ev_for_scenarios(scenarios, p_risk)` in the payoffs module; expose via the what-if endpoint
  (reuse Feature 2's plumbing) rather than persisting to the feed.
- Frontend: an optional EV line in `<WhatIfSandbox>` gated behind a default-off toggle.

**Files:** payoffs module, `api.py`, `frontend/src/WhatIf.tsx`. **Tests:** EV equals the state-weighted sum
(Darderi cross-check); default-OFF; absent on non-caveated rows.

> Recommendation: ship Features 1–3 first; treat Feature 4 as a separate proposal requiring the owner's explicit
> opt-in, since it brushes the scope guard.

---

## Verification (end-to-end)

1. **Backend:** from repo root, `pytest -q` (full suite incl. new `test_payoffs.py`, extended dutchbook/api/viz
   tests) and `ruff check .`.
2. **Frontend:** from `frontend/`, `npm run test` (Vitest) and `npm run build` (type-check clean).
3. **Live smoke:** `python serve.py`, open the SPA, trigger a scan, then for a representative row of **each** source
   (containment, 2-way dutch, field dutch, synthetic) confirm the PARTICIPANT DETAIL tab now shows a populated
   per-scenario payoff table (Feature 1); open the what-if panel, drop a leg ask, confirm the verdict flips and the
   arithmetic updates (Feature 2); confirm a winner-field row shows **integer** per-leg units and no fractional MAX
   UNITS (Feature 3).
4. **Invariant check:** confirm `/api/terminal/feed` ranking/buckets are byte-identical before/after for Features
   1–3 (these add display data only) — diff a snapshot to prove no actionability/ranking drift.

## Sequencing

PR1 = Feature 1 → PR2 = Feature 2 → PR3 = Feature 3 (independently mergeable; 3 also closes QA C2). Feature 4 only
after owner opt-in.
