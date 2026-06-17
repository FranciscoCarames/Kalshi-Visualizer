---
milestone: m1-make-money-concrete
topic: dashboard-usability
created: 2026-06-03
last_updated: 2026-06-03
status: executing
---

# Milestone Plan: m1 — Make the money concrete

## Goal (one sentence)

Make each detected opportunity self-explanatory — show per-unit cost, profit in every settlement
scenario (worst case = the guaranteed floor), return on capital, and time to resolution — using only
arithmetic on contract data already loaded (no fees, no new data sources).

## Success Criteria

What must be true to call this shipped:

- [ ] Each executable (containment) opportunity shows a **3-scenario payoff table** with a **Cost/unit**
      column; the worst-case profit row **equals the existing `exec_gap_c`** (cross-checked in a test).
- [ ] The middle "broad-only" scenario surfaces the **+$1/unit** directional bonus, labelled as a bonus,
      not as the edge.
- [ ] **Equivalence** pairs render the 2 normal states **plus a "rules diverge" risk row** tied to the
      existing `RULE_CHECK_REQUIRED` / `RULE_MISMATCH` flag.
- [ ] **Return-on-capital %** (`gap/(100−gap)`) and **total capital required** (`(100−gap)×units`) shown
      per opportunity.
- [ ] **Time-to-resolution / urgency** column present and sortable, derived from existing `time_value`.
- [ ] **Payoff bar chart** (3 bars; all above zero = locked) and **ladder price bar chart** (inversion
      visible) render for the selected opportunity/player.
- [ ] All new math lives in `consistency.py` / `viz.py` (no Streamlit import); unit tests assert
      worst-case == `exec_gap_c` and the +$1 middle state. `pytest -q` green; headless app boot returns 200.

## Out of Scope

Explicit boundaries (prevents scope creep mid-milestone):

- **Trading fees** / net-of-fees edge (parked in `real-time-opportunity-engine` roadmap as NS-1).
- **New API data sources** — everything is arithmetic on fields already in the contract rows.
- **Copyable trade ticket** (parked: seed S2) and **"resolving within" time filter** (parked: seed S1).
- Backend/WebSocket/real-time, non-tennis categories, historical storage.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `scenario_payoffs()` in `consistency.py` — containment 3-state + equivalence 2-state+rule-risk; returns cost/unit, per-state payout & profit, worst-case floor | ✓ |
| 2 | Unit tests: worst-case == `exec_gap_c`; middle state == gap+100¢; cost/unit == 100−gap; equivalence rule-risk row present | ✓ |
| 3 | ROC% + total-capital-required fields (derive in `consistency.py`; display in app) | ✓ |
| 4 | Time-to-resolution / urgency formatting (e.g. "3h", "2d") + sortable column from `time_value` | ✓ |
| 5 | Render payoff + cost table in `app.py` (Actionable row expander and/or player-detail action cards) | ✓ |
| 6 | `viz.py` payoff bar chart helper (3 scenarios) + render | ✓ |
| 7 | `viz.py` ladder price bar chart helper (chain prices, inversion visible) + render | ✓ |
| 8 | Verify: `pytest -q` + ruff + headless boot (`/_stcore/health` 200); branch + PR per repo git workflow | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

(resolve as you go; promote stable answers to TOPIC.md "Key Decisions" at milestone close)

- Where to surface the payoff table primarily — an expander under each **Actionable** row, or only in the
  per-player detail action cards? (Leaning: expander per Actionable row, mirrored in player detail.)
- Urgency display format and whether to colour by soonness (e.g. red < 6h).
- Equivalence "rules diverge" row: show as unknown/voided payout, or as a flagged caveat row with no
  numeric payout? (Must not imply a guaranteed number where rules are unverified.)
- Should the ladder chart overlay the monotonic-expectation ceiling so the inversion is unmistakable?

## Notes

(deep-dive session writeups go to sibling `note-YYYYMMDD-*.md` files, not here)

---
*Planned via plan-milestone on 2026-06-03*
