---
slug: full-tennis-coverage
created: 2026-06-03
last_updated: 2026-06-03
status: active
---

# Topic: full-tennis-coverage

## What This Is

Make the dashboard work for — as close as possible to — **every contract in Kalshi's tennis category, at
any point in time**. This is a **breadth** track (distinct from `sport-generalization`, which proved the
multi-sport engine, and from the per-round depth work folded in here as the deep-ladder milestone).

The goal splits cleanly in two:

- **Coverage** — fetch, classify, price, and display *every* tennis contract.
- **Checking** — run a consistency check on *every contract whose relationships are provable*. (Not 100%
  of contracts: single-outcome props/futures like "Will Djokovic retire?", "Alcaraz next coach", or "#1
  ranked player" have no relationship to check — for those, "work for" means ingest + display only.)

## Goal

A tennis dashboard where (a) every tennis series/event/market is discovered, classified into a family, and
shown (laddered or explicitly non-laddered, never silently dropped), and (b) every provable relationship is
checked — not just the single SF⊇Final⊇Win containment ladder, but intra-event dutch-book/MECE sums,
cross-family implications, and the full per-round containment chain — robust as tournaments rotate.

## Success Bar

- Discovery captures all real tennis tournaments + families (AO, US Open, Wimbledon, Masters, Davis Cup,
  doubles, …) and **excludes** false-positives (table tennis, freestyle chess "grand slams", golf, movies).
- Every fetched contract lands in a known family; un-checkable ones are surfaced in a non-laddered view.
- A dutch-book/MECE check flags any mutually-exclusive-exhaustive market (each match's 2 players; each
  winner field) whose buy-side prices sum below ~100¢ — a guaranteed executable edge.
- No hardcoded single-tournament assumptions (FO date window / winner-ticker list) gate coverage.
- Tennis behaviour that already works is preserved; tests green, ruff clean, headless 200.

## Roadmap (milestone order)

| # | Milestone | Bucket | Priority |
|---|---|---|---|
| 1 | **MECE / dutch-book intra-event detector** — sum-to-100% across each match's 2 players and each tournament-winner field | Checking | **FIRST** (chosen 2026-06-03) |
| 2 | **Robust tennis discovery + sport tagging** — capture all tournaments/families; exclude table-tennis/chess/golf | Coverage | high |
| 3 | **Family taxonomy + non-laddered surfacing** — classify every family; ingest+show un-checkable props/futures | Coverage | high |
| 4 | **Deep per-round containment ladder** (the planned `m4-deep-tennis-ladder`, relocated here) | Checking | medium |
| 5 | **Cross-family implication checks** — set↔match, exact-score↔match, reach-round↔advance↔winner | Checking | medium |
| 6 | **Temporal robustness** — remove hardcoded FO date window + winner-ticker list; self-adjust as tournaments rotate | Coverage | medium |

(Order is a guide; #1 chosen first for the most coverage-per-effort. `KXATPROUND` "Will player reach round?"
discovered live — a *generic* reach-stage series that may simplify #4/#5; verify during #2.)

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-03 | Spin this off as its own topic, not more of `sport-generalization` | sport-generalization proved the engine across 3 sports (breadth of *sports*); this is breadth of *tennis contracts* — a different axis. |
| 2026-06-03 | "Work for every contract" = Coverage (all) + Checking (all *provable*) | Many tennis contracts (props/futures) have no logical relationship to check; conflating the two would overpromise. |
| 2026-06-03 | Dutch-book/MECE detector is milestone 1 | One generic check covers the largest share of tennis contracts (every match + every winner field) and is the single biggest untapped edge. |
| 2026-06-03 | Keep the deep per-round ladder (m4) as a milestone *within* this topic | It's a containment-family refinement (~5–10% of the goal), valid but small next to breadth + dutch-book. |
| 2026-06-03 (m1) | Dutch-book lives in a sibling `dutchbook.py` with one status `EXECUTABLE_DUTCH_BOOK` routed by a single `bucket_of` branch; rendered in its own UI section | Keep `consistency.py` containment-focused; a dutch book is two *same-side* buys, so it can't reuse the ladder's Buy-YES-broader/Buy-NO-deeper table. It's true arbitrage (same event) → no rule caveat. |
| 2026-06-04 (m5) | **Cross-family / synthetic-bundle findings are ALWAYS settlement-caveated, never "true arbitrage."** An exact score is not the match-winner; on a retirement the score legs settle to Fair Market Price while the hedge settles cleanly (verified live) | Every such finding carries `rule_flag=SETTLEMENT_CHECK_REQUIRED` + `tradable_now="Review rules"` → routed review/blocked, never Actionable; labelled gross/top-of-book. Applies to any future cross-family bundle (e.g. the S8 advance hedge). |

## Out of Scope

- Non-tennis sports (that's `sport-generalization`); the dutch-book detector is built sport-agnostically but
  validated on tennis here.
- Trading / auth / order placement / historical storage / conditional-probability models (standing guard).
- The real-time/WebSocket rearchitecture (parked `real-time-opportunity-engine`).
- 100% *checking* coverage — impossible by nature (standalone props have nothing to check); the bar is "all
  provable relationships," with everything else ingested + displayed.

---
*Created via new-topic on 2026-06-03*
