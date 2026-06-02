# Kalshi Structured Market Visualizer — Project Brief

## 1. Project Goal

The Kalshi Structured Market Visualizer is a tool for analyzing **related** prediction-market
contracts on Kalshi — contracts that describe the same underlying participant or event from different
angles. The initial focus is tennis, where a single player can appear across several contract types at
once: match-result contracts, advancement contracts (reaching a given round), and tournament-winner
contracts. Viewing these side by side makes it possible to see how a player is priced across the whole
structure of an event rather than one contract in isolation.

The long-term goal is to generalize the tool beyond tennis — first to other sports that have a similar
nested structure (for example soccer tournaments), and eventually to other kinds of structured event
markets — so the same analysis applies wherever related contracts share a common participant or outcome.

## 2. Current Version

The current version is a **read-only visualizer**. It loads and organizes sports prediction-market
contracts from Kalshi, currently focused on tennis, and lets the user view the related contracts for a
single player or participant across different contract types (match-result, advancement, and
tournament-winner) when those contracts are available.

Current UI capabilities:

- **Participant/player selection** — pick a player and see their contracts together.
- **Filters** — by event/cup, contract type, outcome status, and volume/liquidity.
- **Side-by-side tables** — related contracts for the selected participant shown together for easy comparison.
- **Trader-facing fields** — prices, quotes, volume, and status for each contract.
- **Debug/raw fields** — the underlying raw data is available on demand when a closer look is needed.

## 3. Current Development Focus

The current focus is improving **contract organization and dashboard clarity** before adding any
advanced pricing or probability logic. The aim is a clean, trustworthy foundation that presents
related contracts clearly.

Active work:

- Improving contract discovery so the relevant contracts are found reliably.
- Grouping contracts by stable participant identifiers where Kalshi provides them, so the same player
  is matched correctly across contract types.
- Avoiding silent missing data — gaps are surfaced rather than hidden.
- Separating trader-useful information from debug information so the main view stays uncluttered.
- Keeping the app read-only and simple.
- Making sure the UI supports clear comparison across related contracts.

## 4. Future Development Plan

| Stage | Goal | Description |
|---|---|---|
| 1 | Improve the tennis visualizer and participant grouping | Strengthen contract discovery and participant matching, and refine how related contracts are displayed together. |
| 2 | Add simple spread / calendar-spread math | Introduce basic comparisons of prices between related contracts (e.g. gaps between adjacent stages). |
| 3 | Add clearer edge classification | Label where the structure looks inconsistent or noteworthy, in clear and conservative terms. |
| 4 | Add scenario and probability-chain modeling | Model how outcomes across related contracts connect, to reason about implied probabilities. |
| 5 | Generalize to other sports | Extend the same structure to other sports with nested events, such as soccer tournaments. |
| 6 | Generalize beyond sports | Evolve into a broader structured prediction-market analysis tool across event types. |

## 5. Current Limitations

- It does not execute trades.
- It is not a full arbitrage engine.
- It does not yet include advanced probability modeling.
- It is currently tennis-focused.
- Some grouping depends on the quality of Kalshi's metadata.
- Quote data can be incomplete or missing for less-active contracts.
- Generalization beyond tennis has not yet been implemented.
- The UI and the classifications it shows are still being refined.

At this stage the project is intentionally focused on building a **reliable read-only foundation** —
discovering, grouping, and clearly presenting related contracts — before layering on more advanced
modeling and broader generalization.
