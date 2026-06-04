# Kalshi Opportunity Engine - Project Brief

## Purpose

The Kalshi Opportunity Engine is a read-only market-scanning tool for finding pricing inconsistencies
and arbitrage opportunities across related Kalshi prediction-market contracts.

The project began as a dashboard for comparing sports contracts, especially cases where the same player
or team appears across match, advancement, game, series, and tournament-winner markets. It has evolved
into a broader opportunity engine: it scans multiple sports, normalizes the results into one ranked view,
persists snapshots over time, and exposes the engine through an API for future interfaces.

The long-term goal is to support a small trader group with a fast, trustworthy view of the best available
opportunities: what is actionable now, what is blocked but close, what recently appeared, and what changed
since the last scan.

## Where The Project Stands

The current system has a solid multi-sport foundation covering tennis, NBA, and WNBA markets. The core
engine is designed so adding another sport is mostly a configuration problem: define the sport's contract
families, ladder relationships, participant identity fields, and display labels.

Current capabilities include:

- Multi-sport scanning across tennis, NBA, and WNBA.
- Contract grouping by participant, event, tournament or season, and market family.
- Containment checks, such as detecting when a deeper outcome is priced above a broader outcome that
  contains it.
- Two-outcome dutch-book detection, such as buying both sides of a head-to-head market for less than the
  guaranteed payout.
- Opportunity buckets for actionable, blocked, near-edge, watchlist, data-quality, and clean rows.
- Plain-English blockers explaining why something is not tradable now, such as missing size, inactive
  markets, wide quotes, or rule caveats.
- Stable opportunity IDs, so the same opportunity can be tracked across scans.
- SQLite snapshots, preserving opportunity history locally.
- Lifecycle logic for newly actionable opportunities, blocked-opportunity changes, and recently
  actionable opportunities.
- A FastAPI service that exposes the engine through REST endpoints.
- A NiceGUI cross-sport, opportunity-first dashboard mounted on the FastAPI service (run via
  `python serve.py`): a live freshness/coverage strip, ranked Actionable/Blocked tables, a
  recently-actionable backlog, a clickable explanation panel, and newly-actionable / changed-while-blocked
  alerts.
- A Streamlit dashboard that remains available for per-sport views, diagnostics, and deeper inspection.

The project is still intentionally read-only. It does not place trades, manage accounts, or automate
execution.

## Current Architecture

The codebase is split between a pure engine layer and presentation layers.

The engine modules handle fetching, parsing, consistency checks, dutch-book detection, cross-sport
scanning, lifecycle diffs, and snapshot persistence. These modules avoid Streamlit and are unit-tested
offline with stubbed data.

The FastAPI layer exposes the engine boundary: latest opportunities, coverage, alerts, backlog, and an
on-demand scan endpoint. The **NiceGUI dashboard is now built and mounted on that FastAPI service**
(`python serve.py`) as the opportunity-first, cross-sport interface, calling the engine in-process. The
Streamlit app (`streamlit run app.py`) remains as a per-sport, diagnostic, and fallback surface until the
NiceGUI dashboard has enough parity to retire it.

## Near-Term Direction

The opportunity-first push has largely shipped in the NiceGUI dashboard:

- A single cross-sport, opportunity-first dashboard. (done)
- Clear freshness and coverage indicators, so the user knows when data is stale or partially loaded. (done)
- Alerts for newly actionable opportunities and changed blocked opportunities. (done)
- A recently actionable backlog, so short-lived edges are not lost immediately. (done)
- Better explanation panels for each opportunity, showing legs, prices, status, blockers, links, and
  why the row matters. (done)

What remains near-term:

- Cleaner exports for analysis and review (the next stage).
- Retiring Streamlit once the NiceGUI dashboard reaches parity (porting the per-player deep-dive first),
  and adding a full-scan scope toggle to the dashboard.

The project should continue to label scope honestly. A core-series scan should not be described as "all
Kalshi markets" (the dashboard's scan is explicitly labelled core-series), and gross edge should remain
clearly marked as gross before fees, slippage, latency, and partial-fill risk.

## Expansion Ideas

The following ideas are candidates for future development. They are not all immediate roadmap items, but
they point toward a more advanced decision-support system.

### Richer Decision Trees

The current logic focuses on relatively direct relationships: one outcome contains another, or a
two-outcome event can be fully covered below the payout. A future version could model more complex
decision trees, where several related contracts represent different paths through a tournament, game, or
event.

This would let the system reason about multi-step positions, conditional outcomes, and state-dependent
hedges instead of only one-shot opportunities.

### Dynamic Win Probabilities

The engine could add probability estimates from external data and internal models. Instead of relying
only on market prices, it could compare Kalshi prices with independently calculated win probabilities.

Those probabilities could come from multiple methods, such as live scores, team strength, player form,
injuries, schedule context, historical performance, or custom statistical models. Showing several
probability estimates side by side would help separate true pricing opportunity from model uncertainty.

### Hidden Arbitrage In Wide Spreads

Some opportunities may be hidden inside very wide bid-ask spreads. The current system is conservative
because wide quotes are usually unreliable and may not be executable.

A future version could analyze whether a wide spread is merely noise or whether it creates a realistic
entry point if the trader can post liquidity, wait for fills, or combine the contract with another leg.
This would require careful handling so the tool does not present theoretical spread math as guaranteed
execution.

### Real-Time Strategy Adjustment

More complex arbitrage may involve several game states rather than a single static pair of trades. For
example, a trader might buy positions tied to intermediate game states while also hedging or selling the
final result.

As the game progresses, some outcomes become impossible and others become more likely. A future strategy
module could update the recommended position in real time, removing excluded states, recalculating
remaining exposure, and suggesting how to rebalance as the event changes.

This would move the project from opportunity detection toward live decision support. It would also raise
the bar for latency, data quality, risk controls, and clear communication about what is executable versus
modeled.

## Current Limitations

- The project is read-only and does not execute trades.
- Edge calculations are gross, not net of fees.
- The system does not yet include advanced probability modeling.
- Quote data can be thin, stale, wide, or missing, especially in less active markets.
- Some relationship checks depend on Kalshi metadata and settlement-rule compatibility.
- The current UI is still in transition from Streamlit toward a more opportunity-first dashboard.

Overall, the project has moved beyond a simple visualizer. It now has the core pieces of an opportunity
engine: multi-sport scanning, stable opportunity identity, persisted history, lifecycle tracking, and an
API boundary. The next work is to make that engine faster to use, clearer to trust, and more capable of
supporting complex trading decisions.
