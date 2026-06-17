---
slug: dashboard-usability
created: 2026-06-03
last_updated: 2026-06-03
status: active
---

# Topic: dashboard-usability

## What This Is

Simple, high-value usability improvements to the **shipped** Kalshi tennis dashboard. Explicitly a
"keep it simple" track, distinct from (and parallel to) the parked `real-time-opportunity-engine` topic.
No fees, no rearchitecture. Focus: make detected executable inconsistencies **concrete and actionable**
for the trader.

## Goal

Turn each detected opportunity from an abstract "there's an edge" into a transparent, self-verifying
picture: what you stake, what you get back in every terminal state, the guaranteed floor, the return on
capital, and how soon it resolves — without adding new data sources, fee math, or backend complexity.

## Success Bar

A user looking at any Actionable opportunity can see, at a glance: the per-unit cost, the profit in each
of the three settlement scenarios (with the worst case = guaranteed floor), the return on capital, and
time to resolution — and can copy the trade to act. All new logic lives in the Streamlit-free modules and
is unit-tested.

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-03 | Pursue simple dashboard-usability wins **instead of** Phase 0 (net-of-fees + dutch-book) for now | Owner wants to keep the project simple; fees add complexity without near-term payoff. The big-engine roadmap stays parked under `real-time-opportunity-engine`. |
| 2026-06-03 | Payoff table worst-case row must equal the existing `exec_gap_c` | Cross-checks the new scenario math against the number the engine already computes (cost/unit is always `100 − gap`). |
| 2026-06-03 | All new logic in `consistency.py` / `viz.py` (Streamlit-free, unit-tested) | Preserves the repo's hard rule that math stays out of `app.py` and is independently testable. |
| 2026-06-03 | **Real-time is the goal → backend framework change is now critical path, not "later."** Next: un-park `real-time-opportunity-engine`, plan a tennis-only WebSocket backend spike. | The higher API tier removes the rate ceiling; Streamlit's REST-poll/rerun architecture (not the tier) is what blocks true real-time. Backend before broad sport-generalization (sport detection logic ports, but fetch/UI would be rebuilt on a WS backend). |

## Out of Scope

Explicit boundaries to prevent re-adding:

- **Trading fees** / net-of-fees edge (deliberately deferred — lives in the parked roadmap as NS-1).
- Backend decouple, WebSocket, real-time push (that's the `real-time-opportunity-engine` topic).
- Non-tennis categories, historical/time-series storage, alerts, probability/de-vig modelling.
- New API data sources — everything here is pure arithmetic on contract fields already loaded.

---
*Created via new-topic on 2026-06-03*
