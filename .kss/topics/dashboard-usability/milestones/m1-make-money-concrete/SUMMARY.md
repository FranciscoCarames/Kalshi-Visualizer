---
milestone: m1-make-money-concrete
topic: dashboard-usability
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: m1 — Make the money concrete

## What Shipped

Each detected opportunity now shows its full settlement-state P&L: a per-unit payoff table (cost,
payout, profit in every terminal state), the guaranteed floor, return-on-capital and total capital
required, a sortable time-to-resolution column, a payoff bar chart, and a containment price-ladder chart
that makes inversions visible. All arithmetic lives in the Streamlit-free modules and is unit-tested; no
fees and no new data sources were added. Shipped as PR #22 (`feat/scenario-payoffs` → `main`), awaiting
the owner's manual merge.

## Success Criteria

- [x] 3-scenario containment payoff table with a Cost/unit column; worst-case row **== `exec_gap_c`** — passed cleanly (independent-derivation test).
- [x] Middle "broader-only" state surfaces the **+$1/unit bonus**, labelled as a bonus not the edge — passed.
- [x] Equivalence pairs show 2 aligned states **+ a "rules diverge" risk row** tied to `RULE_CHECK_REQUIRED` — passed.
- [x] **ROC%** + **total capital required** per opportunity — passed (per-unit `roc_pct`; `capital_c`/`total_floor_profit_c` with units).
- [x] Sortable **time-to-resolution** column from `time_value` — passed ("Resolves in (h)" in Actionable).
- [x] **Payoff bar chart** + **ladder price chart** (inversion visible) — passed.
- [x] All new math in pure modules, unit-tested; `pytest -q` green; headless boot 200 — passed (**107 tests**, ruff clean).

## Caveat (not a gap vs. criteria)

Verified by unit tests + headless boot, **not** against a live actionable book — network is sandboxed
here and there may be no live cross right now. The success criteria did not require live validation; live
spot-checking is roadmap item NS-3 if/when a live cross is available before the FO window closes (2026-06-09).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Worst-case payoff row must equal the engine's `exec_gap_c` | Cross-checks new scenario math against an independently-derived number | Enforced by test; cost/unit is always `100 − gap` |
| Keep all new arithmetic in `consistency.py`/`viz.py`; `app.py` only formats | Repo rule: no math in the Streamlit layer; keeps the eventual framework migration cheap | `scenario_payoffs`, `payoff_chart_data`, `ladder_prices`, `resolve_time` all pure |
| **Real-time is the goal → the framework change (backend decouple) is now critical path, not "later"** | The higher API tier removes the rate ceiling; Streamlit's REST-poll/rerun architecture (not the tier) is what blocks true real-time | Next direction: un-park `real-time-opportunity-engine`, plan a tennis-only WebSocket backend spike (promoted to TOPIC Key Decisions) |

## Deferred

Captured as seeds (in SEEDS.md):

- SEED-S1 — "Resolving within [today / 7d / any]" time filter (trigger: urgency column shipped, users want to narrow by it). **Now unblocked** — `resolve_time` exists.
- SEED-S2 — Copyable trade ticket (trigger: payoff/cost batch shipped, acting speed becomes the bottleneck). **Now unblocked.**

## Files Touched

- `consistency.py` — `scenario_payoffs()`, `resolve_time` on each check row
- `viz.py` — `payoff_chart_data()`, `ladder_prices()`
- `app.py` — `_payoff_block()`, payoff/ladder charts, "Resolves in (h)" column
- `tests/test_consistency.py`, `tests/test_viz.py` — 13 new tests

## Sessions

Work completed in a single working session on 2026-06-03 (LOG.md not used per-session this milestone).

---
*Closed via complete-milestone on 2026-06-03*
