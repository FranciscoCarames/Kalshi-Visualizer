# **Kalshi Opportunity Engine Project Brief**

## **Purpose**

The Kalshi Opportunity Engine is a read-only tool that scans related prediction-market contracts on Kalshi. It surfaces pricing relationships that may deserve trader review, especially where related outcomes appear inconsistent or where a proven set of outcomes can be covered for less than its payout floor.

The project began as a dashboard for evaluating a single player or team across all relevant contracts at once. This includes match, advancement, game, series, and tournament-winner markets. It has since evolved into a multi-sport opportunity engine that scans ten sport groups, consolidates results into a single ranked view, maintains a running history of findings, and exposes that history through an API.

The primary goal is to support trading review by answering four practical questions: what appears actionable now, what is blocked but close, what appeared recently, and what changed since the last scan.

## **Where The Project Stands**

The engine covers ten sport groups: tennis, NBA, WNBA, golf, soccer, MLB, NHL, motorsport (including F1, NASCAR, IndyCar, and MotoGP), NFL, and esports (CS2, League of Legends, Valorant, Dota 2, and more via a curated allow-list). Adding another sport is usually a matter of configuration through the existing sport abstraction, as long as the required contract families, participant identifiers, ladder relationships, and settlement assumptions can be described clearly.

Currently, the engine can:

* Scan ten sport groups in a single pass.  
* Group related contracts by participant, event, tournament or season, and market family.  
* Flag containment inconsistencies, such as “Win the tournament” pricing above “Reach the final,” and separate executable findings from display-only signals.  
* Detect Dutch-book / MECE pricing discrepancies across two-outcome matches, series, per-game and per-map markets, soccer three-way games, and overround-only tournament-winner fields, with tie-capable games (such as NFL) gated on a fixed-sum settlement proof.  
* Detect synthetic exact-score bundles where a full set of scorelines replicates a player winning, while routing those findings to review because settlement rules require caution.  
* Sort findings into actionable, review, blocked, near-edge, watchlist, data-quality, and clean categories.  
* Explain why a finding is blocked, such as missing size, inactive markets, wide quotes, incomplete coverage, or settlement-rule uncertainty.  
* Track opportunities over time with stable IDs.  
* Save each scan as a local SQLite snapshot.  
* Read scan history for lifecycle signals, including newly actionable, changed while blocked, and recently actionable findings.  
* Serve the engine through a REST API with opportunities, coverage, alerts, backlog, health, readiness, metrics, and scan endpoints.  
* Present the results in a cross-sport NiceGUI dashboard, run with `python serve.py`, with ranked tables, freshness and coverage indicators, alerts, backlog, explanation panels, participant detail, diagnostics, and debug views.

Throughout its development, the tool remains read-only. It does not place trades, access accounts, or automate execution.

## **Current Architecture**

The codebase keeps a clean line between the pure engine and the interface that presents it.

The engine handles fetching, parsing, sport classification, consistency checks, Dutch-book detection, synthetic-bundle detection, cross-sport scanning, lifecycle comparison, and snapshot storage. The pure-logic layers do not import the UI and are tested independently against stubbed data.

The app is exposed through a single FastAPI service. The NiceGUI dashboard is mounted on the same service and is now the sole user interface. The original Streamlit dashboard has been retired.

## **Near-Term Direction**

The opportunity-first dashboard is now in place, including blocked-reason breakdowns, snapshot export, and edge-age / lifecycle signals (newly actionable, changed while blocked, recently actionable). The near-term focus is on a small set of owner-gated improvements that widen detection coverage and make edges easier to act on. Each is scoped but not yet built:

* **Advancement-field detector** — investigate whether reach-a-stage ("advance") fields can be proven mutually exclusive and exhaustive, then build an n-outcome detector on top of that proof.  
* **Field underround** — test whether any winner or advancement fields have enough coverage to safely support underround logic (the winner-field detector is overround-only today because it is mutually exclusive but not exhaustive).  
* **Net-of-fees edge math** — capture Kalshi's fee schedule and surface a net edge alongside the gross one, with gross staying the default so fees never silently drive actionability.  
* **Execution / automated trading** — long-term only, and explicitly out of scope until the owner lifts the read-only guard.

## **Expansion Ideas**

These ideas represent potential directions for growth rather than firm commitments. Each moves the project beyond simple opportunity detection toward becoming a more robust decision support tool.

### **Richer Decision Trees**

Currently, the engine reasons about direct relationships, such as one outcome containing another or an event being fully covered below its payout. A future version could model the entire decision tree. This would involve viewing several related contracts as different paths through a tournament or game, allowing the engine to reason about multi step positions, conditional outcomes, and state dependent hedges.

### **Dynamic Win Probabilities**

Market price is only one part of the equation. The engine could incorporate independent probability estimates from live scores, team strength, player form, and injuries. Displaying several estimates together would help distinguish a genuine mispricing from model uncertainty.

### **Hidden Arbitrage In Wide Spreads**

Some edges might be hidden within very wide bid ask spreads. The engine is currently conservative with these because wide quotes are often unreliable. A future version could evaluate whether a wide spread is noise or a realistic entry point for a trader willing to post liquidity and wait for fills.

### **Real-Time Strategy Adjustment**

The most compelling arbitrage often spans multiple game states. A trader might hold positions tied to intermediate states while hedging the final result. As a game progresses, a strategy module could update recommended positions in real time by dropping excluded states and recomputing exposure. This evolution would shift the project from spotting opportunities to supporting live decisions, which requires higher standards for latency and data quality.

### **Visualization of Decision Trees**

Provide a graphical interface that maps the multi-step positions and conditional outcomes, allowing traders to intuitively grasp the complex relationships modeled by the Richer Decision Trees engine.

### **Messaging App Integration for Alerts**

Extend the current alert system to push real-time notifications for newly actionable opportunities to external platforms, such as a dedicated Telegram channel, ensuring traders are instantly aware of short-lived edges even when not viewing the dashboard.

## **Current Limitations**

* The tool is read-only and does not execute trades.  
* Edge calculations are gross and top-of-book.  
* The engine does not account for fees, position limits, collateral, or the slippage of filling past the top size.  
* The engine does not currently model win probabilities.  
* Quote data can be thin, stale, wide, one-sided, crossed, or missing, particularly in quieter markets.  
* Certain checks rely on the quality of metadata and the alignment of settlement rules.  
* Per-game markets and synthetic bundles carry explicit settlement caveats for abnormal resolution, such as postponements, retirements, walkovers, or no-contests.  
* A default scan covers a curated set of core series rather than the entire Kalshi universe.

## **World Cup Implementation**

- Group Stage: 3 games, players qualify by group ranking, not points (I must be in the top 2 of my group or in the top 8 of third-place teams).  
- Round of 32: Win the match  
- Round of 16: Win the match  
- Round of 8: Win the match  
- Round of 4: Win the match  
- Round of 2: Win the match  
- Winner: Win the match

Guaranteed Pass: 7-9 points

## **World Cup Qualifier Setup Ideas**

### 1\. Qualifier-not-winner spread

* Trade shape: buy YES on “team qualifies from group” and buy NO on “team wins group.”  
* Thesis: the team is good enough to qualify, but unlikely to win the group.  
* Best outcome: team qualifies but does not win the group.  
* Risk: loses if the team fails to qualify or wins the group.  
* App label: `Qualifier-not-winner spread`.  
* Use as: review/setup signal, not arbitrage.

### 2\. Group qualifier YES floor basket

* Trade shape: buy YES on all four teams qualifying from the same group.  
* Logic: in World Cup 2026, at least two teams from each group qualify for the Round of 32\.  
* Minimum payout: 2 YES contracts pay.  
* Upside: if a third-place team from the group also qualifies, 3 YES contracts pay.  
* App label: `Group qualifier YES floor basket`.  
* Use as: low-risk group-level basket if total YES cost is near or below the two-qualifier payout floor.

### 3\. Group qualifier NO floor basket

* Trade shape: buy NO on all four teams qualifying from the same group.  
* Logic: at least one team from each group fails to qualify.  
* Minimum payout: 1 NO contract pays.  
* Upside: if only two teams qualify from the group, 2 NO contracts pay.  
* App label: `Group qualifier NO floor basket`.  
* Use as: low-risk group-level basket if total NO cost is near or below the one-failure payout floor.

### 4\. Exact-order-derived top-two synthetic

* Trade shape: diagnostic only at first.  
* Logic: exact group-order markets can be used to estimate the market-implied cost of a team finishing top two.  
* For a four-team group, there are 24 exact orders; a given team finishes top two in 12 of them.  
* Compare: `Qualifier YES price` versus `Synthetic top-two cost`.  
* If qualifier YES is cheaper than the top-two synthetic, the qualifier may be cheap, but the exact-order basket may be stale or illiquid.  
* App label: `Top-two synthetic support`.  
* Use as: diagnostic/ranking signal, not an actionable trade initially.

### 5\. Game-market support signal

* Trade shape: diagnostic only.  
* Logic: use the team’s three group-stage game markets to estimate expected group points.  
* Formula: `expected points = 3 × win price + 1 × draw price` for each game.  
* Sum across the three group games.  
* If expected group points are high but qualifier YES is still moderately priced, flag the team as a possible qualifier setup.  
* App label: `Game-supported qualifier setup`.  
* Use as: ranking/support signal, not arbitrage.

