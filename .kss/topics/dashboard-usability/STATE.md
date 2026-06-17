---
topic: dashboard-usability
status: executing
active_milestone: null
last_session: 2026-06-11
last_updated: 2026-06-11
---

# Topic State: dashboard-usability

## Current Position

**2026-06-11 — Bounded-loss trader likelihood metrics, Phase 1 (current branch, NOT merged).** On
`feat/bounded-loss-likelihood-metrics` (`36c4ca2`, **off `feat/ui-trust-fixes` 197bf07** — the
owner-preferred original, NOT the parked ui-table-clarity). Added **display-only, fail-closed** Bounded-Loss
columns — "Chance if reached %" (conditional P(success|reached)), "Firm success gap ¢" (conservative
parent-bid − child-ask), Midpoint-only / Wide-basis badges, "Cost per implied pp" — + firm-quote
passthrough (`parent_yes_bid_c`/`child_yes_ask_c`, REST parity, no migration) + new pure `probability.py`
(de-vig MATH only). **922 tests**, ruff clean, boot green, 0 console errors. Never touches
classify/bucket/rank. Owner: phased / experimental (no CLAUDE.md scope-guard change) / open to a
win-loss-likelihood table reorg only via a previewable mockup. **Awaiting owner test+merge.**

**Lineage of unmerged bounded-loss branches (all off main, branch-only delivery, main frozen):**
`feat/bounded-loss-phase1` (perf+lag fix + implied-metric decomposition) → `feat/bounded-loss-phase2`
(`9d7b977`, B+E+F+G speculative suite, 863 tests) → `feat/convergence-20260610` + `feat/ui-trust-fixes`
(197bf07, WC+ITF — see sport-generalization) → `feat/bounded-loss-likelihood-metrics` (current). The
comparability suite **A #143 / C #144 / B #145 / D #146 ARE merged to main**; everything past them is
branch-only awaiting owner test. The earlier `feat/ui-table-clarity` (ad6e024) clarity pass is **PARKED —
owner prefers the original** (`bounded-loss-clarity-rejected.md`).

**Approved scope expansion (planning-only):** the **Speculative Decision-Support Layer** roadmap
(`~/.claude/plans/turn-this-into-a-drifting-anchor.md`) — 3 product zones, hard invariant = prob/EV/de-vig
metrics are display + opt-in sort ONLY (isolation test per PR); PR 0 = scope-guard rewrite is a hard
predecessor. Phase 2 field-implied de-vig (scanner `build_fair_prob_table` + `SportConfig.survivors_for_node`
+ `FieldStatus`) is a later branch gated on a field-completeness audit.

**2026-06-07 — Ranking follow-on (PR #107 OPEN).** "Outright + spread" rank mode (probability-LED) +
min-child-outright / max-ratio filters; 5 display-outright fields plumbed consistency→scanner→api. 599
tests. `feat/risk-budget-spread-outright-ranking`, awaiting owner merge.

**✅ 15-feature dashboard batch + Streamlit retirement + near-real-time perf — DONE & FULLY MERGED
2026-06-05** (`origin/main` `c2f2d4b`). Shipped as 15 PRs off `main` (#89–#103), each isolated worktree,
each pytest+ruff+compileall+serve.py-boot verified; suite 532→**557**. See LOG.md (2026-06-05) for the
per-PR map and `~/.claude/plans/peppy-bubbling-neumann.md` for the design. Headline: NiceGUI is now the
**sole UI** (Streamlit retired); the poll loop is split (`reload_data`/`rerender`/`poll`, 1s poll, 10s
scans, presence-gated) so filters are instant and a scan surfaces within ~1s; plus ranking modes (payoff
geometry, **no probability/EV**), participant multi-select, resolution-criteria toggle, change-color
markers, accessibility, and "most liquid / most volatile now" lines.

## Recent Decisions

- 2026-06-05 — Ranking = gross **payoff geometry only, NO probability/EV** (the `p_bonus`/`expected_profit_c`
  approach was designed then explicitly DROPPED mid-plan).
- 2026-06-05 — `.env` API keys NOT built (#8): public market-data needs no auth; only a tier ceiling /
  WebSockets change throughput. Documented in `docs/DEPLOYMENT.md`.
- 2026-06-05 — Volatility (#12b) = lightweight **blob scan over retained contract frames**, NOT a
  time-series schema migration (scope-guarded).
- 2026-06-05 — Streamlit `app.py` retired; NiceGUI on FastAPI is the sole UI.

## Blockers

None.

## Next Action

(1) **Manual browser checks** in BOTH light/dark — selected-row highlight, larger-text on dense tables,
change-color across two scans, participant multi-select, ranking-mode switching, resolution-criteria
toggle, live liquidity/volatility lines (headless can't drive row-select / read client-rendered cells).
(2) **GDrive doc sync** (standing rule) — now behind the Streamlit retirement + every new surface; finish
the `docs/TECHNICAL_DOCUMENTATION.md` prose refresh and drop its temporary "Streamlit retired" banner.
