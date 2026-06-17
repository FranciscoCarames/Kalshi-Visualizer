# Detector Strategies Plan — additions to the opportunity engine

**Status:** Planning artifact (no code), 2026-06-12. Derived from `MASTER_BACKLOG.md` §4–§5 and §19
sequencing, `docs/STATUS.md`, and the strategy-expansion memory. Companion to the FROZEN
`MASTER_BACKLOG.md` — this doc *explains each strategy with an example*; the backlog is the catalog.

This is a catalog of **detection strategies** (the families of edges the engine can surface), grouped
into three tiers by how close each can get to "Actionable," which is also roughly the de-risk / build
order.

---

## Governing rules (backlog §0 — shape the whole plan)

- **Strict-engine isolation.** Nothing here may alter `consistency._classify`, `bucket_of`,
  `scanner._rank_key`, or `tradable_now`. Probability/EV/model outputs only drive *opt-in ranking
  lenses inside speculative/research zones*. Isolation tests enforce zero strict-output change.
- **Every new signal is born demoted** (data-quality → diagnostic → review-only → research) and is
  promoted on two axes: **claim type** (exact relation → bounded-risk → probabilistic → signal) ×
  **evidence level** (unproven → proof-gated → calibrated). An executable finding is *born at proof* —
  it never passes through risk-budget.
- **Label discipline / $1 basis / gross top-of-book.** Never "riskless" or "arbitrage."

---

## Tier 1 — Exact, proof-gated detectors (can become Actionable)

Reuse machinery already shipped. The "edge" is a provable price relation in exact cents, not a model.

### 1. Scalar-ladder monotonicity (vertical-spread analog) — *most de-risked new family*
- **What:** The containment ladder ("deeper ⊆ broader") applied to **numeric strike ladders** instead
  of tournament rounds. A higher bar must never price above a lower bar.
- **Example:** NFL/NBA spreads & totals — `Team wins by ≥7` ≤ `wins by ≥3`; `Total ≥220` ≤ `≥210`. If
  `≥7` asks 42¢ while `≥3` bids 38¢, that's an executable cross (Buy YES the ≥3, Buy NO the ≥7) —
  same shape as today's "child bid > parent ask." (Golf Top-5 ⊆ Top-10 ⊆ Top-20 already exists.)
- **Surface/gate:** candidate-capable where containment is proven (same series, monotone strikes);
  near-miss ladder → watchlist.

### 2. CDF monotonicity + discrete-PDF non-negativity (option-surface no-arb analog)
- **What:** Across a full ladder, `P(X≥k+1) ≤ P(X≥k)`, and implied bucket `P(X=k) ≥ 0`. A negative
  implied bucket is a structural mispricing.
- **Example:** "Total goals" ladder where `≥2` bids 55¢ but `≥1` asks 50¢ implies negative P(exactly 1
  goal) — buyable inconsistency between two real markets.
- **Surface/gate:** implied-CDF chart in card; monotonicity violations exact → candidate-capable;
  smoothness/shape → research. Fail-closed partition proof (complete exhaustive partition).

### 3. Same-event bucket-sum vs coarse range (butterfly / condor analog)
- **What:** A union of fine buckets must equal the coarse range containing them — only under exact
  partition + settlement-sync proof.
- **Example:** buckets "0–1"+"2–3" should equal a separate "≤3" market; buy the fine pair for less than
  the coarse "≤3" sells = butterfly.
- **Surface/gate:** review-only until partition + identical settlement proven, then candidate-capable.

### 4. Combo-leg bound inconsistency (Fréchet bounds — *not* a "dutch book")
- **What:** For combo A∧B: upper bound `P(A∧B) ≤ min(P_A,P_B)`; n-leg lower bound `≥ max(0, ΣP_i −
  (n−1))`. The upper-bound subtype is containment (combo ⊆ each leg).
- **Example:** "Team X wins AND Over 2.5 goals" at 48¢ while "Team X wins" bids 40¢ → Buy NO combo +
  Buy YES leg, $1 floor under aligned settlement.
- **Surface/gate:** provable upper-bound → candidate-capable; Fréchet-lower → review-only; product/
  implied-correlation comparisons → research. Prereq: multivariate ingestion (backlog §2.2).

### 5. Calendar containment (calendar-spread analog)
- **What:** "Qualify by an earlier date" ⊆ "qualify by a later date" — same target, same settlement,
  proven expiry containment.
- **Example:** "Reach the WC Round of 16" ≤ "Reach the Quarterfinal happens-by a later cutoff" for the
  same team.
- **Surface/gate:** candidate-capable once expiry containment + identical settlement proven; else the
  close-time mismatch detector (#11) blocks it.

### 6. Generalized hard-floor baskets (exactly / at-least / at-most-k-of-n)
- **What:** Cardinality floors from a **format proof** (not MECE). Generalize the existing WC
  group-qualifier / group-bottom baskets.
- **Example:** "Exactly 2 of these 4 teams advance from Group F"; playoff-slot counts; award-finalist
  sets; "how many seeds make the conference finals."
- **Surface/gate:** hard-floor basket label; candidate-capable where the format proof is exact.

### 7. Advance-field overround + field underround
- **What:** Extend winner-field overround to **reach-stage fields** (overround NO-basket on safe
  subset). Field **underround** (Buy-YES-all) needs an exhaustiveness proof → stays gated.
- **Example:** Overround — across all "Reach the WC Final" markets, firm YES bids on a priceable
  subset summing > 100¢ → Buy NO each. Underround needs `/events/{ticker}/metadata` + structured-target
  entrant lists (a **probe** item).
- **Surface/gate:** advance-overround → candidate-capable on the safe subset; underround overround-only
  until exhaustiveness proven.

### 8. Generalized synthetic replication (umbrella detector)
- **What:** One detector for "basket-of-states ≡ target": exact-score → match winner (exists),
  stage-elim tail → advancement rung (exists), **bucket-union → range** (new), **combo → leg
  expression** (new).
- **Example:** union of "loses in R16/QF/SF/…" replicates "does NOT win the tournament," priced
  against the outright winner as two independent hedges.
- **Surface/gate:** exact partition + settlement-sync → candidate-capable; cross-family settlement
  sensitivity → review-only (like tennis bundles today).

---

## Tier 2 — Cross-cutting correctness detectors (review-only / data-quality)

Mostly validate or **block** the edges above. Cheap insurance, high trust.

### 9. Duplicate / equivalent-market detector
- Same target + event + settlement under **different tickers/series** at different prices → review-only
  equivalence discrepancy; candidate-capable only with a rule-equivalence proof.
- **Example:** a match listed under an ATP main series and a duplicated event ticker, 61¢ vs 58¢.

### 10. Settlement-rule divergence detector
- Rules-token diff, settlement-source diff, close-time mismatch, cancellation/no-contest/FMP-clause
  mismatch. First-classes today's *light* token diff. **Keeps synthetic bundles honest.**
- **Example:** two "Team X wins the series" markets, one settles on official-result, one voids on
  suspension → caveat/block, not an edge.

### 11. Close-time & lifecycle-sync detector
- Per-template close-time tolerance + expiry-mismatch badge. Every replication template implicitly
  assumes synced expiry — now checked explicitly.
- **Example:** a calendar pair where the "earlier" leg closes *after* the later leg → early-close /
  stale-leg risk → block.

### 12. YES/NO book-parity check — **data-quality only**
- Asks are derived from opposing bids on-exchange → a parity violation *cannot* be an edge by
  construction; it means snapshot skew or a parse bug. Label explicitly so it's never mistaken for an
  opportunity.

### 13. Stale-quote detector  *(pull forward — no new endpoints)*
- Quotes unchanged across N scans / candle activity while the event repriced; midrange prices near
  near-certain resolution are often stale quotes in disguise.
- **Example:** a market pinned 0.50/0.50 with no recent trades while the live game is 3–0 → flag stale,
  haircut confidence, never rank Actionable.

---

## Tier 3 — Research Lab signals (research-born, calibration-gated)

Can **lose money**; require calibration/backtest history before influencing ranking. Live in the
Research Lab surface; may only *attach to* candidate cards as evidence.

- **14. Implied-distribution extraction** — implied distribution from a strike ladder; skew/kurtosis/
  fat-tail anomalies. (Exact CDF violations graduate to Tier-1 #2; *shape* stays research.)
- **15. Probability term structure** — price-by-stage curve (Reach R16→QF→SF→Win); inversions are
  Tier-1 containment, *steepness/shape* is research.
- **16. Favorite–longshot bias monitor** — per-sport calibration curves from settlement history.
  Depends on the outcome loop (§11).
- **17. Dispersion / index-vs-components** — outright winner vs path-implied bracket probability.
- **18. Straddle / strangle / cheap-tail screens** — range-breakout, cheap-tail baskets,
  expensive-middle NO baskets. Candidate only with exact range-union + buy-only payoff proof.
- **19. Correlation & pairs / stat-arb monitors** — combo price vs leg-product implied-correlation
  heatmap; co-movement baselines + divergence z-scores.
- **20. Tape / order-flow + book-pressure** *(probe-gated on data)* — taker imbalance, bursts, sweeps,
  quote-move-without-tape; YES-vs-NO depth imbalance near touch. Feed quote confidence, not trades.
- **21. Momentum / mean-reversion + expiry-pin dynamics** — candlestick screens; pin behavior near
  resolution. Depend on candlestick backfill.
- **22. Portfolio / risk aggregation** *(pull forward — no new endpoints)* — same-participant/event/
  sport exposure across a trader's candidates; **"don't take both" warnings** for correlated or
  mutually-exclusive candidates.
- **23. Kelly / sizing** — opt-in, user-supplied probability required, fractional-Kelly with caps,
  educational; never a default recommendation.

---

## Gating & recommended sequencing

Most Tier-2/3 items depend on backlog §1 (Kalshi capability + probe foundation) and §11 (outcome loop:
settlement recorder → grading → calibration). **Tier 1 mostly does not** — it rides on shipped
machinery. Recommended order:

1. **Tier 1 first** (backlog §19.5): scalar ladders → CDF/PDF → bucket-sum/butterfly → combo bounds →
   calendar → replication generalization.
2. **Tier 2 alongside Tier 1** — settlement-divergence (#10) and close-time-sync (#11) are
   *prerequisites* for trusting calendar/replication; build in the same wave.
3. **Foundation (§1) + outcome loop (§11)** before any Tier-3 signal is promoted past "research."
4. **Tier 3 as the data platform fills in** — candlesticks → momentum/pin; trades → tape; orderbooks →
   depth/book-pressure; settlements → calibration/favorite-longshot.

**Pull forward (no new endpoints, high trust, low cost):** #22 portfolio "don't take both" warnings and
#13 stale-quote detection.

---

## Possible next artifacts (not yet done)

- Dependency-ordered **roadmap doc** (phases, per-strategy proof contracts, capability-probe blockers) —
  the artifact backlog §19 describes.
- Expand any single strategy into a full **StrategyTemplate** spec (proof source, allowed buckets,
  quote/size gates, required card fields, forbidden language).
