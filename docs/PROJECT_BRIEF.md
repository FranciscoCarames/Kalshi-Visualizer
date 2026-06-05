# Kalshi Structured Market Visualizer — Project Brief

## 1. Project Goal

The Kalshi Structured Market Visualizer is a tool for spotting **executable pricing inconsistencies and
arbitrage opportunities** in related prediction-market contracts on Kalshi. It covers multiple sports —
currently tennis, NBA, WNBA, golf, soccer, MLB, NHL, and motorsport (F1/NASCAR/IndyCar/MotoGP) — where a single player or team can appear across
several contract types at once: match-result contracts, advancement contracts (reaching a given round),
and tournament-winner contracts. Viewing these side by side makes it possible to see when the same
participant is priced inconsistently across related contracts, and to identify cases where a set of
mutually-exclusive outcomes can all be bought for less than the guaranteed payout.

The long-term goal is to turn this into a **real-time, multi-category opportunity engine** for a small
trader group — scanning every supported sport at once, tracking opportunities over time, and surfacing
the most actionable edges in a single ranked view.

## 2. Current Version

The current version is a **read-only dashboard**. It loads and organizes prediction-market contracts from
Kalshi across multiple sports and lets the user view related contracts side by side, flagging pricing
inconsistencies and guaranteed-arbitrage situations.

Current capabilities:

- **Multi-sport coverage** — tennis (all tournaments the platform can find), NBA, WNBA, golf, soccer, MLB,
  NHL, and motorsport (F1/NASCAR/IndyCar/MotoGP), off one shared engine. Adding another sport is designed to be a small configuration step.
- **Participant and team selection** — filter down to one player or team and see all their related
  contracts together.
- **Filters** — by sport, tournament, contract type, outcome status, and volume/liquidity.
- **Pricing inconsistency detection** — flags where a deeper-outcome contract is priced higher than a
  broader contract that contains it (e.g. "Win the tournament" priced above "Reach the final"), labelled
  as executable (firm prices + available size) or display-only (price signals only).
- **Dutch-book / guaranteed-arbitrage detector** — separately flags when the two sides of a
  head-to-head match or series can both be bought for less than 100¢ total, locking in a guaranteed
  payout regardless of outcome. This is genuine arbitrage, not just a pricing signal.
- **Actionable, Blocked, and Near-edge sections** — opportunities sorted by gross edge, with plain-English
  explanations of what blocks a trade (missing size, wide quotes, finalized markets, rule caveats).
- **Trader-facing fields** — prices, quotes, volume, spread, and status for each contract.
- **Dashboard clarity** — a timezone selector (defaults to Lisbon), a live data-freshness indicator,
  a toggle to reveal underlying contract codes, and diagnostics tucked behind an "Advanced" toggle.
- **Debug/raw fields** — the underlying raw data is available on demand.

## 3. Current Development Focus

The current version (Stage 0 of a six-stage roadmap) has just completed a **clarity overhaul**: cleaning
up the dashboard layout, adding always-visible data freshness, removing a misleading ranking chart, and
generally making the tool more trustworthy and easier to read before adding new capabilities.

What was completed in Stage 0:

- Timezone selector, live data-freshness indicator ticking every second.
- A toggle to show or hide underlying contract identifiers.
- Diagnostics and debug information moved behind an "Advanced" toggle.
- Removal of an opportunity-ranking bar chart that was found to be misleading.

Stages 1–6 (below) are the forward plan.

## 4. Future Development Plan

The agreed direction is to evolve this into a real-time, multi-category opportunity engine. The plan is
structured in six stages, to be delivered in order:

| Stage | Goal | Description |
|---|---|---|
| 1 | Stable opportunity identity + history snapshots | Give every flagged opportunity a stable identifier and begin saving lightweight snapshots over time, so changes can be tracked. |
| 2 | Single cross-sport ranked view | A unified scanner that ranks every opportunity across all sports in one table, replacing the current per-section layout. |
| 3 | Lifecycle tracking | Highlight newly-actionable opportunities, flag when a blocked one becomes actionable, and keep a "recently actionable" backlog. |
| 4 | Web API | Expose the engine through a proper API so other tools or users can query it. |
| 5 | New dashboard and UI | Rebuild the dashboard on a more capable web-based UI framework, opportunity-first, replacing the current one. |
| 6 | Export overhaul | Improve and standardize all data exports. |

Net-of-fees edge math, real-time streaming, and multi-user hosting are explicitly planned for later —
gross edge first.

## 5. Current Limitations

- It does not execute trades.
- It does not yet calculate net-of-fees edge — gross edge only.
- It does not include advanced probability modeling.
- Some grouping and matching depends on the quality of Kalshi's metadata; gaps are surfaced rather than
  hidden, but they do occur.
- Quote data can be incomplete or missing for less-active contracts.
- The UI and the classifications it shows are still being refined as the roadmap progresses.

At this stage the project has a **reliable multi-sport read-only foundation** — discovering, grouping,
and clearly presenting related contracts, and flagging executable inconsistencies and genuine arbitrage
situations — and is now building toward a real-time, ranked, lifecycle-aware opportunity engine.
