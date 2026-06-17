# Master Backlog — Kalshi Sports Trading Workstation

**Status:** FROZEN consolidated catalog (v3 final, 2026-06-10). This is the master *backlog*, not the
roadmap. The roadmap is a separate dependency-ordered artifact derived from this document.
**Audience context:** users are professional traders accustomed to Bloomberg terminal, Trading
Technologies, and Excel — dense grids, keyboard workflows, watchlists, alerting, export-everywhere.

Tags: **(partial)** = exists in some form today, upgrade. **(probe)** = requires a dated live-probe
artifact before implementation. **(deferred)** = in the vision, explicitly out of near-term scope.

---

## 0. Non-negotiable invariants

### 0.1 Strict-engine isolation (the "non-classifying modeling/ranking layer" rule)
Probability, de-vig, EV, fee, depth, tape, historical, and model outputs may appear on cards and may
drive **explicit, user-selected ranking lenses inside speculative/research zones only**. They must
never alter: `consistency._classify`, `consistency.bucket_of`, `scanner._rank_key`, `tradable_now`,
strict Actionable/Blocked/Review routing, settlement-caveat severity, or buy-only action text.
Isolation tests enforce this (changing any model/fee/depth output ⇒ zero strict-output change).
The guard-doc rewrite (speculative-roadmap PR 0) precedes any modeling code.

### 0.2 Label discipline
| Label | Use |
|---|---|
| Executable inconsistency | Proven containment cross; firm quotes, size, active, exact cents |
| Dutch-book discrepancy | Proven MECE/floor relationship; settlement caveats visible |
| Hard-floor basket | Cardinality floor from format proof, not MECE |
| Synthetic bundle | Basket replicates a market under assumptions; review-only unless fully settlement-proven |
| Review-only signal | Has an expression; proof/settlement/execution incomplete |
| Risk-budget candidate | Can lose money; bounded downside + convex upside visible |
| Diagnostic signal | Useful context, not a trade idea |
| Research signal | Hypothesis needing calibration/backtest |
| Data-quality event | API/book/identity/rules inconsistency — never an opportunity |

Never "riskless" / "locked" / "true arbitrage." Edges are GROSS and TOP-OF-BOOK unless a separately
labeled net/depth view says otherwise.

### 0.3 $1 canonical basis
All math in the $1 Kalshi payout unit. $100/stake views are optional **derived display lenses**
(not purged — derived). Acceptance tests phrased in $1 terms.

### 0.4 Every new signal starts demoted — two-axis promotion
Birth state: data-quality / diagnostic / review-only / research. Promotion is **two-dimensional**:
**claim type** (exact relation | bounded-risk structure | probabilistic edge | signal) ×
**evidence level** (unproven → proof-gated → calibrated). Executable findings are *born* at proof —
they never pass through risk-budget; a risk-budget candidate is not an immature executable.
Promotion requires the StrategyTemplate proof contract, golden fixtures, isolation tests, and
outcome evidence where relevant.

### 0.5 Read-only boundary
Default-deny ALL POST endpoints: order placement, market creation, multivariate create-market,
API-key creation, portfolio/order endpoints. Any POST requires a separate critical-scope owner
decision. The app surfaces, ranks, explains, tracks — never places orders.

---

## 1. Kalshi data-plane & capability foundation

*Hard prerequisite for every new-endpoint feature below.*

- **`KalshiCapability` registry** — every endpoint-dependent feature declares: endpoint_family,
  read_only, auth_required (public/signed/conflicted/probe-required), token_cost_model, batch_limits,
  schema_version, freshness_semantics, failure_mode, probe_script, feature_flag,
  owner_signoff_required.
- **Live-probe artifact convention** — each capability ships a dated probe script + sanitized
  captured response under `scripts/probes/`, plus parser/schema-drift/failure-mode tests. "Verified
  live" becomes reproducible, not a commit-message claim.
- **`marketdata/` enrichment layer** — new package (capabilities, probes, discovery, targets,
  milestones, orderbooks, candlesticks, trades, fees, historical, live_data, exchange, enrichment).
  `scanner.py` receives typed enriched frames; detectors and UI never know endpoint details.
  `data.build_contracts` stays untouched by enrichment.
- **Token/request budget planner** — per scan: enabled sports + enrichments → expected calls, tokens,
  latency, batch sizes, TTL reuse, degraded-mode plan. Facts: token-based limits (Basic 200 read
  tokens/s ≈ 20 req/s; Advanced 300 ≈ 30 req/s); most requests cost 10 tokens; **batching saves HTTP
  round trips, NOT token budget** (per-item charging) (probe whether batch *reads* cost per-item).
- **Selective-enrichment rule** — depth/tape/candles are fetched for watched markets, top-N
  candidates, and open detail panels only; **never universally per scan**. Budget math makes
  universal depth impossible even at Advanced tier.
- **Authenticated read-tier experiment (probe, owner-gated)** — docs describe a *permanent* Advanced
  grant via `/account/api-tier-upgrade` (verify by probe; don't assert doubt the docs contradict).
  Conditions: read-scoped key only (creation defaults to full access if unscoped — scope explicitly),
  env-only private key, GET allowlist, no key in UI/exports, no order modules in the codebase,
  unauthenticated public mode as default fallback, verify tier via `/account/api-limits`.
  Would allow `MAX_RPS` 15 → ~22 (75% of 30).
- **Endpoint/auth decision matrix** — search filters/tags, structured targets, milestones, events,
  multivariate, orderbooks (single + batch ≤100 tickers), trades, candlesticks (single + batch ≤100
  tickers / 10k candles), historical (+ `/historical/cutoff` boundary), fee-changes, exchange
  status/schedule/announcements, game-stats — each row carries intended use + gate. Orderbook auth is
  documentation-conflicted → **(probe)**.
- **Fixed-point / subpenny hardening** — conformance sweep over every parsed field (`*_dollars` up to
  4dp, `*_fp` counts, fractional contracts); subpenny rows excluded from strict exact-cent detectors
  with a "not exact-cent eligible" badge **(partial: Decimal/cents discipline exists)**.
- **WebSocket boundary** — `QuoteSource` abstraction now; lifecycle-channel design doc only.
  **WebSockets require authenticated signing even for public channels** — streaming is never "free."
  No quote streaming, no private channels. **(deferred)**
- **Dropped:** `/exchange/user-data-timestamp` as a freshness oracle (it reports *user-portfolio*
  data validation, not market data). Freshness = market `updated_time` + scan timestamps + candle
  activity + exchange status **(probe)**.

---

## 2. Market coverage

### 2.1 Immediate / calendar-sensitive
- **World Cup convergence (URGENT — kickoff 2026-06-11):** merge wc-coverage-audit, GROUPBOTTOM
  basket, stage-of-elimination branches; verify `KXWC`/`KXMENWORLDCUP` winner ticker live; verify
  KXWCGAME/KXWCGROUPQUAL/KXWCGROUPORDER/KXWCSTAGEOFELIM current shapes; golden snapshots.
- **Tennis ITF merge** — branch built+verified; verify identity fields; lower-tour liquidity caveat.

### 2.2 Discovery & identity backbone
- **Official discovery** — replace prefix-guessing with `/search/filters/sports` + `/search/tags`;
  diff discovered series against owned `SportConfig`s; newly-listed-series alert; OI/volume-ranked
  coverage queue **(partial: audit script on branch)** **(probe)**.
- **Structured-target + milestone identity backbone** — caches, alias table, target→participant
  linker, cross-series identity confidence, collision detector ("same name different target" /
  "same target different name"), low-confidence dashboard. Unlocks UFC-style cross-series joins
  **(probe)**.
- **Multivariate combo/parlay market class (read-only)** — ingest `/events/multivariate` +
  collections; classify combos; parse selected legs; join combo↔legs; bound computations; coverage
  audit; lifecycle abstraction. **Never call the create-market POST** **(probe)**.

### 2.3 Sport additions (sequenced by market calendar, parallel to foundations — never serialized last)
- NCAAB men/women (plan exists; matters ~Feb 2027). UFC/MMA (plan exists; identity + settlement-basis
  gates; structured targets may unlock). College football (NFL-shaped; tie-proof). Boxing (after UFC
  abstraction). Soccer leagues/Champions League (reuse 3-way machinery). Esports v2 (qualifier
  ladders, opponent labels, tags). Cricket/rugby/darts/snooker/cycling/Olympics: audit-then-build by
  liquidity. Non-sports categories: defer `CategoryConfig` rename until one actually enters.
- **Market-class coverage matrix** — standing audit grid: binary participant / categorical MECE /
  one-winner field / cardinality basket / scalar-range ladder / exact order / exact score /
  multivariate combo / historical settled / live-data-driven — status × detector potential.

---

## 3. Strategy & proof framework

- **StrategyTemplate proof contract (mandatory before any new family):** template_id,
  relationship_type, claim_type, proof_source, allowed_buckets, actionability_allowed (default
  FALSE), quote_gates, size_gates, market_status_gates, settlement_caveat_policy, basis_label,
  required_endpoint_capabilities, required_card_fields, required_tests, promotion_path, failure_mode,
  forbidden_language.
- **ResearchSignal contract:** claim_type, ranking_scope (main / speculative zone / Research Lab /
  card attachment only), calibration_required, historical window, probability source, cannot-say
  language, promotion evidence, decay rate, confidence inputs, card-attachment behavior.
- **Opportunity identity & canonicalization spec** — versioned identity (normalized leg set, family,
  participant IDs, event/market tickers, settlement family, direction, recipe version) so one
  mispricing = one canonical card referenced from each qualifying strategy section; prerequisite for
  dedup, alert hygiene, scoring.
- **Complexity policy:** detection is template-gated (curated library grows deliberately);
  complexity *within* a template is uncapped and surfaced via the execution-complexity score, never
  silently filtered.

---

## 4. Exact / candidate-capable detector expansion

*All proof-gated per §0.4; "candidate-capable" ≠ candidate by default.*

- **Scalar ladder monotonicity** (vertical-spread analog) — spreads/totals/Top-N/thresholds:
  deeper must not price above broader; this is the **existing containment machinery** applied to
  scalar strikes (most de-risked new family). Buy-only expression where containment is proven;
  near-miss ladder watchlist.
- **CDF monotonicity + discrete PDF non-negativity** (option-surface no-arb analog) —
  `P(X≥k+1) ≤ P(X≥k)`; implied bucket `P(X=k) ≥ 0`; implied-CDF chart; fail-closed partition proof.
- **Same-event bucket-sum vs coarse range** (butterfly/condor analog) — fine-bucket union ≡ coarse
  range only under exact partition + settlement-sync proof; review-only until proven.
- **Combo-leg bound inconsistency** (NOT "dutch book") — for combo A∧B: upper bound
  `P(A∧B) ≤ min(P_i)`; n-leg Fréchet lower bound `≥ max(0, ΣP_i − (n−1))`. The provable upper-bound
  subtype is the existing containment family (combo ⊆ each leg → Buy NO combo + Buy YES leg, $1
  floor under aligned settlement) → candidate-capable. Fréchet-lower violations review-only.
  Product/implied-correlation comparisons are research-only, never equality.
- **YES/NO book parity check — data-quality ONLY** — asks are derived from opposing bids on-exchange,
  so a violation cannot be an edge by construction; it means snapshot skew or a parse bug.
- **Calendar containment** (calendar-spread analog) — qualify-by-earlier ⊆ qualify-by-later; same
  target + same settlement definition + proven expiry containment required.
- **Generalized hard-floor baskets** — exactly/at-least/at-most-k-of-n from format proof (group
  advancement, playoff slots, award finalist sets) **(partial: WC qualifier/bottom baskets)**.
- **Field underround — evidence-gated, not scheduled** — needs an exhaustiveness proof;
  `/events/{ticker}/metadata` + structured-target entrant lists are the candidate proof sources
  **(probe)**; until proven, winner fields stay overround-only.
- **Advance-field overround** — reach-stage fields, overround NO-basket on the safe subset.
- **Generalized synthetic replication** — umbrella detector `basket-of-states ≡ target` (exact-score
  → match winner; stage-elim tail → advancement rung; bucket union → range; combo → leg expression).
  Exact proof → candidate-capable; cross-family settlement sensitivity → review-only **(partial:
  tennis exact-score bundles, stage-elim tail-sum)**.
- **Duplicate/equivalent-market detector** — same target + event + settlement criteria under
  different tickers/series at different prices → review-only equivalence discrepancy; candidate only
  with rule-equivalence proof.
- **Settlement-rule divergence detector** — rules token diff, settlement-source diff, close-time
  mismatch, cancellation/no-contest/FMP clause mismatch → data-quality / caveat / block per template
  **(partial: light token diff exists)**.
- **Close-time & lifecycle sync detector** — per-template close-time tolerance; expiry-mismatch
  badge; early-close and stale-leg risk. Every replication template implicitly assumes this — now
  checked explicitly.
- **Cross-event relative value; conditional-probability candidates; event-tree/parlay consistency** —
  research/review-born; promotion per §0.4.
- **Stale-quote detector; liquidity-gap signals; low-cost optionality screen; combination bounds
  (A1); peer-implied fair value** — from the strategy-expansion plan; research/diagnostic-born.

---

## 5. Derivatives-inspired research layer → **Research Lab**

*All (R) = Research Lab surface only; research signals may attach to candidate cards as evidence and
may influence rank only via opt-in presets.*

- Implied distribution extraction from strike ladders (skew/kurtosis/fat-tail anomalies; the exact
  CDF-monotonicity violations graduate to §4).
- Probability term structure (price-by-stage curve; inversions are §4 containment; steepness is research).
- Binary "Greeks" panel — delta ≡ implied probability; event-time gamma proxy; theta analog (drift to
  0/1); capital-duration. Display/education layer.
- Favorite-longshot bias monitor — per-sport calibration curves from settlement history; price-band
  residuals; standing research signal once history exists.
- Dispersion signals — outright vs path-implied bracket probability (index-vs-components analog).
- Straddle/strangle analog — range-breakout screens, cheap-tail baskets, expensive-middle NO baskets;
  candidate only with exact range-union + buy-only payoff proof.
- Correlation monitor — combo price vs leg product → implied correlation premium/discount heatmap.
- Pairs/stat-arb watch — co-movement baselines for related participants; divergence z-scores.
- Momentum / mean-reversion screens on candlesticks; volume-confirmed moves; post-news drift.
- Tape/order-flow signals — taker-side imbalance, trade bursts, block trades, sweep-like behavior,
  quote-move-without-tape; feeds quote confidence.
- Book-pressure indicator — YES vs NO depth imbalance near touch; book thinning; fill-probability proxy.
- Expiry/pin dynamics — midrange prices near near-certain resolution (often stale quotes in disguise).
- In-play regime tagging — event time + `/live_data/game-stats`: in-play badge + freshness haircut in
  confidence **(probe — sport support varies)**.
- **Portfolio/risk aggregation** — same-participant/event/sport exposure across a trader's
  candidates; correlated-candidate and mutually-exclusive conflicts; **"don't take both" warnings**;
  settlement-correlated risk.
- Kelly/sizing — opt-in advanced view, user-supplied probability required, educational display,
  fractional-Kelly with caps; never a default recommendation.

---

## 6. Probability & modeling (non-classifying layer)

- **Probability provenance on every field:** raw price, basis (bid/ask/mid/last/candle/de-vig/model/
  user), timestamp, stale flag, source markets, calibration status, CI if model-derived. Fixes the
  basis-mismatch class of bugs (chance from midpoints vs cost from asks must never silently mix).
- **De-vig as refinement toggle:** proportional first; power/Shin/additive later; raw always shown;
  overround amount + method-sensitivity displayed; never in strict classification.
- **Conditional probability engine** — guarded ladder ratios **(partial: Phase 2G)** → full event
  trees; suppress on inversion/staleness; tree-consistency checks.
- **Scenario/Markov tree engine** — bracket/group/playoff trees; market-implied path probabilities;
  terminal payoff tables; mismatch-vs-outright (research until tree proofs exist).
- **Model registry** — name, version, owner, inputs, training window, calibration report, last
  validation, allowed ranking zones, assumptions card, disabled-by-default if uncalibrated.
- **Trader-supplied probabilities** — manual/CSV/API; per-market notes; timestamps; EV + break-even
  vs *their* number; private by default, shareable.
- **Historical calibration — backfill-bootstrap, forward-validated before promotion** — archived
  markets + candlesticks accelerate it by months, but backfilled detector outputs are reconstructed,
  not observed; Brier/log scores; reliability curves; "backfilled-only" warning.
- **Fees modeling** — estimated fee line from `/exchange/series-fee-changes` + event overrides;
  beside gross, never replacing it; never nets into strict actionability **(probe)**.
- **Depth-aware execution realism** — orderbook shape verified (yes/no bid arrays; asks derived;
  string fixed-point; client-side depth aggregation): effective fill price for N contracts; fillable
  units at max slippage **(probe: auth)**.
- **Realized probability-volatility metrics** from candlesticks — feeds confidence, stale detection,
  movers.
- External data: **none now; later = company-curated only** (interface stub permitted). **(deferred)**

---

## 7. Ranking, scoring & confidence

- **Decomposed confidence — 9 dimensions** (data, quote, liquidity, execution, settlement,
  strategy/proof, model, comparability, complexity) with subcomponents (data age, exchange status,
  endpoint health, spread, top size, depth-fillable units, leg count, rules diff, identity
  confidence, proof level, calibration status, realized vol). Components always shown.
- **Lens library first** — pure testable lenses: liquidity-first, confidence-first, immediacy,
  strict-only, settlement-safe, low-complexity, high-upside, bounded-risk, stale-monitor, low-cost
  optionality, research-strength, model-support, tape-confirmed, depth-confirmed, volatility-catalyst.
- **Observable-only "Execution-quality score"** — composite over observable components (quote
  quality, depth, spread, age, status, legs, caveat severity, identity confidence) with visible
  breakdown; may ship before calibration; never labeled "risk-adjusted EV."
- **Model-weighted composite — gated** behind calibration + forward validation + opt-in preset +
  visible decomposition + zone-limited scope. **(deferred until evidence)**
- **Objective + strategy presets**; weights = fixed defaults + advanced override; always
  "highest-ranked under selected lens," never "objectively best."
- **Readiness redesign via viewmodel strangler** — compute `primary_status` + `warning_badges`
  downstream; `bucket` stays byte-stable; golden-test zero routing change; core taxonomy migration
  only later if ever. The 8 draft labels are a placeholder to redesign.
- **Binding-constraint engine** — per card: price/size/status/quote-quality/settlement/proof/
  identity/staleness needed to become executable; powers one-click alerts and "what would improve."
- **Signal decay** — by quote age, book update, candle + trade activity, time-to-resolution, in-play.
- **Rank-cap rules** — research-only never outranks strict rows on the main dashboard; uncalibrated
  model scores create no top-priority badges; stale rows capped outside stale-monitor lens;
  caveated rows carry Review badges; low-confidence identity capped at diagnostic/review.
- Research-signal attachment + preset-controlled rank influence; merged canonical cards (per §3
  identity spec); marginal-candidate "show marginal" floor toggle (hidden by default).

---

## 8. Trade card & economics

- **Standard `TradeCard` schema** (one shape for every family): card/canonical IDs, template, label,
  bucket/status, proof source, legs, buy-only expression, cost per $1, payout floor, worst/best case,
  break-even probability, gross ROI/profit, fillable units, effective fill price, fee estimate,
  collateral estimate, execution complexity, settlement caveats, rules links/text, quote/depth/tape
  timestamps, probability source, confidence breakdown, why flagged, why ranked, what would improve,
  what can go wrong, evidence pack.
- **EvidencePack on every card/export** — scan ID, fetch timestamps, source endpoints + capability
  versions, quote/book/candle/fee timestamps, rules version, settlement source, identity +
  target/milestone IDs, model + calibration versions, template version, probe-artifact reference.
- **Depth ladder panel** — yes/no bid ladders + derived asks; effective cost at 1/10/50 contracts;
  max fill at current edge; slippage table; imbalance; timestamps.
- **Tape panel** — recent trades (price, size, taker side, time); imbalance; spike; stale-tape badge.
- **Estimated fee line** — beside gross, source + timestamp shown, never replacing gross.
- **Scenario payoff table** — terminal states × P&L per contract; rule-dependent states flagged;
  abnormal-resolution warning **(partial: viz chart data)**.
- **Rules panel** — side-by-side rules text, token diff highlighted, settlement-source/close-time/
  cancellation diffs, manual review checklist (assisted analysis: app gives a read with confidence,
  recommends human review on anything material).
- **Research-card variant** — hypothesis, why interesting, evidence for/against, required
  confirmation, promotion path, sample size, calibration status, "not a trade instruction."
- **Price-history sparkline** on every card (from candlesticks).
- Fix the 13 bounded-loss audit issues (basis mismatch + negative-chance-as-probability first).
- $1-unit normalization everywhere; $100/stake as derived views.

---

## 9. UI/UX — terminal-grade workstation

*Ground truth: main tables are Quasar `ui.table` (AG Grid only in diagnostics); Python-side
filtering; full row rebuild per rerender (build phase dominates; PR1b row-diff TODO exists); no
shortcuts/saved views/column persistence; URL-state exists; export = one ZIP; 1s snapshot-ID poll.*

### 9.1 Three surfaces
| Surface | Content |
|---|---|
| **Opportunity Dashboard** | strict executable, review, blocked, risk-budget, near-miss, watchlist |
| **Research Lab** | §5 analytics, distributions, backtests, calibration, model lenses |
| **Operations/Diagnostics** | endpoint health, probes, scan timings, data quality, coverage audit |

### 9.2 Grid & rendering
- **AG Grid migration — incremental Community pilot:** one table → prove selection/detail sync,
  filter persistence, row transactions → migrate the rest. **Clipboard/range-selection are likely
  Enterprise-only** → custom JS copy handler or server-side TSV; `.xlsx` server-side (openpyxl).
  Target: client-side sort/filter, virtualization, pinned columns, saved column state, row
  transactions, cell flashes, keyboard nav, grouping by sport/template/bucket **(probe wrapper
  feature support)**.
- **Row-diff incremental updates** — AG Grid transactions update changed rows only; per-cell change
  flashes; stale-row fading.
- **Trivial trust fixes (do immediately):** surface the ScanManager in-progress flag as a
  "Scanning…" indicator; clear `state["selected"]` when the selected row leaves the filtered universe.

### 9.3 Workstation features
- Summary landing page (Act-now / Review / New / Movers / stale / failed-series / exchange-paused
  tiles + top-by-lens). Dense/comfortable density tiers **(partial: dense props + a11y large-text)**.
- Keyboard workflow (`/` search, `j/k` rows, `Enter` card, `w` watch, `d` dismiss, `a` alert,
  `g a/r/b/l` section jumps, `?` overlay) + `Ctrl+K` command palette (markets, participants,
  templates, views, watchlists, alerts, probes).
- Multi-pane layout (grid | card | history/tape/depth; resizable; saved layouts; pop-out windows).
- Watchlist pane (pinned candidates/markets, distance-to-trigger, in-play badge, alert state).
- **Saved views** — named filter+sort+column+preset combos on top of the existing URL-state.
- Movers strip; sparklines in rows; quote board per market (TT-style ladder, display-only).
- **Timeline/replay view** — replay last N scans; card/price/rank/status evolution; "why it left
  Actionable."
- **Status/trust strip (always visible):** last scan, data age, scan status + phase, failed series,
  request/token estimate, exchange status + maintenance banner + announcements feed, DB size,
  auto-scan state, degraded flags. "Trading paused" ≠ "data stale."
- Consistent column vocabulary + glossary tooltips on every header/badge **(partial: glossary.py)**;
  basis labels on every probability/EV/depth/fee field; known-limits line visible.
- Accessibility: high-contrast, colorblind-safe icons, no color-only encoding **(partial)**;
  dark-theme verification (default dark exists).
- **Footgun removals:** no stale selected detail, no silent old data during scan, no research rows
  visually identical to executable rows, no unbounded scroll, no "edge" column without basis.
- **UI code-debt refactors:** split the 95-line `rerender()`; dedupe the 7 near-identical
  row-building comprehensions; `ColumnSet` class replacing 4 magic hidden-column lists; move 100+
  lines of inline Vue slot templates to a tested `slots.py`.
- Mobile/tablet view **(deferred)**.

---

## 10. Alerts & monitoring

- **Phase 1 — trusted-state alerts:** new Actionable, became executable, bucket changed, binding
  constraint crossed, watched market moved, exchange paused/resumed, data degraded, rules changed,
  series disappeared/failed.
- **Phase 2 — user rules:** saved-view match, price/size/depth thresholds, tape/candle spikes,
  in-play, model-edge thresholds (zone-limited).
- **Phase 3 — delivery:** browser, email, webhook (Slack/Discord/Teams-compatible), exportable feed;
  scheduled digest **(deferred until hygiene + outcome loop exist)**.
- **Alert hygiene (every rule):** dedupe key, severity, cooldown, stale suppression, "became" vs
  "still" distinction, reason text, card snapshot + EvidencePack, audit trail, degraded state.
- **Constraint alerts from any card:** alert-when-executable / size≥N / edge≥X / caveat clears /
  quote tightens / depth supports N.
- Near-miss → Monitor-tier lifecycle with distance-to-trigger **(partial: near-miss sections)**.
- `market_lifecycle` / `multivariate_lifecycle` websocket channels **(deferred; design doc only)**.

---

## 11. Outcome loop, history & backtesting

- **Time-series store** — master schema designed up front (series, events, markets,
  structured_targets, milestones, market_snapshots, orderbook_snapshots/levels, trades, candlesticks,
  historical_markets, fee_schedules, rules_snapshots, opportunity/signal_snapshots, scan_runs,
  probe_artifacts, capability_status, identity_links, strategy_templates, model_runs,
  calibration_bins, settlements, alert_events, watchlists, journals, saved_views) — but **tables land
  feature-by-feature with the first feature that reads them**, as migrations of the existing store
  (snapshots/frames/backlog), never an up-front platform build or rewrite. Migration/rollback/
  retention/idempotent-backfill defined per migration; large-fixture migration test.
- **Settlement recorder** — settled-market detector, final values, timestamps, rule snapshot,
  abnormal-resolution flag, manual correction path.
- **Opportunity outcome grading** — would the buy plan have paid; realized worst/best; realized gross
  edge; caveat materialized; fillable at top-of-book; lifetime before disappearing.
- **Historical backfill system** — archived markets + candlestick backfill jobs; live/archive
  boundary resolver (`/historical/cutoff`); idempotent cursors; gap detector; provenance table;
  "reconstructed, not observed" caveat **(probe)**.
- **Backtest/replay harness** — replay stored + archived data; detector-version and lens-version
  comparison; alert replay; visible-at-time simulation; no-lookahead checks; optional latency/fill/
  fee overlays.
- **Calibration dashboards** — implied vs realized by sport/strategy/price band/liquidity/quote
  quality/time-to-resolution/in-play; Brier/log scores; drift; favorite-longshot residuals.
- **Survival/time-to-edge analytics** — how long Actionable rows last; mean time-to-disappear;
  fillability and price decay by sport/template; alert-latency analysis; **"doing nothing was
  better" tracker**.
- Full lifecycle audit trail per opportunity **(partial: backlog intervals + lifecycle diffs)**.

---

## 12. Export, reporting & API surface

- Per-table WYSIWYG exports: CSV + typed XLSX (server-side), current filters/sort/columns,
  selected-row export. Grid range copy-as-TSV (custom JS if Enterprise-gated).
- Card exports: JSON, Markdown, PDF/print, text block, EvidencePack JSON, full legs/rules/depth/tape.
- Research reports: signal card + charts + history + backtest + assumptions + promotion status.
- Shareable shortlist links (snapshot-only, LAN).
- Keep the full-evidence ZIP **(partial: exists)**; add manifest schema versions, probe status, app/
  config/lens versions, cards, alerts, signals.
- **REST API as a product surface:** stable `/opportunities`, `/opportunities/{id}`, `/cards/{id}`,
  `/markets/{ticker}`, `/watchlist`, `/alerts`, `/signals`, `/research`, `/history`, `/coverage`,
  `/probes`; versioned OpenAPI; **Excel Power Query guide** + Python notebook examples
  **(partial: /opportunities etc. exist)**.

---

## 13. Backend, architecture & performance

*Ground truth: scan ≈3–4s, ~49 GETs @ 15 RPS (network-bound by design); sport fetch 3-wide, series
4-wide; per-sport detection serial (~1.5s); SQLite healthy (WAL, indexed, pruned).*

- **Merge pending perf branches** (parallel-sport-fetch, ui-instrumentation, read-path-opt) + the
  deferred title-cache and scan-parallelization PRs.
- **Profile-first baseline** — standing perf report: scan/fetch/parse/detect/write/render/row-build
  timings, request + token counts, DB size, memory.
- **Parallelize per-sport detection** — the 7 detector builders are independent over one contracts
  frame; fan out per-sport or per-detector with deterministic merge order + isolated failures.
- **Streaming detection/store writes** — rank/persist completed sports before the slowest finishes.
- **Caches:** series discovery (TTL + audit invalidation — re-fetched every scan today), titles,
  structured targets, milestones, fee schedules, event metadata.
- **Hot/cold incremental scanning** — scan more: near start, in-play, watched, recently moved,
  near-trigger, has Actionable; scan less: far from resolution, dead book, maintenance, no viewers,
  settled.
- **Batch endpoints** for orderbooks/candlesticks (latency, not token savings).
- **Store optimizations:** `executemany`, batch commits, partial indexes for hot reads, JSON
  compression for large frames, vacuum job, retention enforcement.
- **UI render optimizations:** AG Grid transactions, lazy card hydration, memoized viewmodels,
  stable row IDs, rebuild only changed card sections.
- **Bounded state:** expire `state["ever_seen"]` entries (grows unbounded with uptime).
- **Background-job framework** — scan, coverage audit, probes, backfills, settlement recorder, alert
  evaluation, DB maintenance, calibration rebuild — each with status table, health panel, retry
  policy, manual-run, concurrency gate.
- **Multi-process:** document single-worker as a hard constraint (+ startup assertion); externalize
  throttle/singleflight/presence only if deployment actually changes **(deferred)**.
- Config-as-data (presets, weights, template params versioned in DB/YAML); structured logging +
  metrics expansion **(partial: /metrics)**.
- **Framework triggers (don't switch preemptively):** Postgres when concurrent writers/real auth/DB
  size demand it; dedicated React/AG-Grid front end if the NiceGUI wrapper blocks core UX; Redis/job
  queue at multi-process; WebSocket/SSE channel when streaming is approved.

---

## 14. Data quality & robustness (standing subsystem)

- **Book invariants:** parity (data-quality only), crossed book, negative spread, zero-size quote,
  stale/no-quote/one-sided, orderbook-top vs market-top mismatch, missing book timestamp, subpenny
  strict exclusion.
- **Market/event invariants:** expected market counts, duplicate participants, missing tie row,
  wrong MECE flag, type/close-time/status/finalization mismatches, malformed custom strike.
- **Identity invariants:** same-target-multiple-names, same-name-multiple-targets, low-confidence
  fallback, malformed UUID, missing target/milestone, cross-series conflicts.
- **Rules/settlement invariants:** rules-text change alerts (versioned per scan), settlement-source
  change, no-contest/void/FMP clause mismatch, timing mismatch.
- **Candlestick cross-validation:** scan snapshots vs candle OHLC; missing candles during active
  markets; price outside bid/ask plausibility; archive/live boundary mismatch.
- **Endpoint/schema drift:** missing required fields, new-field logging, enum/fixed-point/pagination/
  auth-behavior/token-cost drift — per capability.
- **Graceful degradation states per section:** healthy / degraded / stale / endpoint-disabled /
  auth-required / probe-failed / no-markets / exchange-paused / maintenance / archive-boundary.

---

## 15. Per-user layer **(deferred until privacy preconditions explicit)**

- Local profile stub (picker, no credentials, LAN-only warning, private-by-default); identity/auth
  mechanism = decide later; build the user-scoped data model now.
- User-scoped objects: saved views, column states, watchlists, alert rules, dismissals, notes,
  journal, trader probabilities, model configs, research flags.
- **Action journal:** watched/dismissed/acted/passed + size + reason + notes + timestamps + later
  settlement outcome; feeds per-user views and calibration; read-only toward Kalshi.
- **Workflow primitives (engine-inert overlays):** send-to-watchlist, dismiss-for-me, snooze,
  mark-reviewed, needs-rules-check, waiting-for-size/price, export-to-desk-note, copy card summary,
  create-alert-from-constraint, attach-research-signal.
- Per-trader track record (P&L/hit-rate from journal + settlements): private, opt-in sharing
  **(deferred: needs recorder + journal + privacy model)**.
- Sharing: snapshot-only links first; broad sharing controls **(deferred)**.

---

## 16. Security, credentials & deployment

- Read-only credential policy (per §1 auth experiment): owner signoff, read scope, env-only, GET
  allowlist, no key in UI/exports, no private/portfolio endpoints, startup scope warning,
  unauthenticated fallback.
- **POST prohibition (default deny):** orders, market creation, multivariate creation, key creation,
  portfolio writes — any POST = separate critical-scope decision.
- LAN hardening: deployment health page, backup/restore, DB-size alert, storage-secret check
  **(partial: bind_safety)**, TLS reverse-proxy notes, single-worker assertion, config snapshot in
  diagnostics.

---

## 17. Process, tests & quality

- **Golden snapshots:** one fixture per sport, market class, strategy template, data-quality event,
  exact detector, research signal, multivariate event, scalar ladder, orderbook, fee schedule,
  historical market, settlement outcome.
- **Property tests:** buy-only language, exact cents only, no false Actionable, non-negative max
  payoff, no model/fee/depth leakage into strict buckets, no unproven MECE promotion, no "arbitrage"
  label on review-only rows, no silently parsed unknown series, subpenny strict exclusion.
- **Speculative-isolation tests:** strict outputs byte-identical under changes to model probability,
  de-vig method, fee schedule, depth, tape, volatility, research rank boosts.
- **Endpoint schema tests** per capability (required fields, optional tolerance, drift logging,
  fixed-point parsing, pagination, auth behavior, failure modes).
- **Browser/UI tests:** AG Grid renders, filters persist, selection clears, scanning indicator,
  stale banner, saved views, filtered exports, evidence panel, shortcuts, dark/large-text modes.
- **Performance budgets in CI:** scan duration, request/token counts, detector + store-write + API +
  row-update timings, memory, DB growth **(partial: benchmark script)**.
- **Release gates for high-risk features:** current-doc check + live probe + schema test + golden
  snapshot + property test + isolation test + manual smoke + trader-facing docs.
- **Trader task acceptance tests** ($1-unit phrasing): e.g. "a trader can identify the
  strongest current candidate under a chosen lens, see why it ranks there, check fillability/
  staleness/rules risk, and export it in under two minutes."
- Trader-facing manual (readiness tiers, confidence dimensions, label vocabulary) distinct from dev
  docs **(partial: glossary export)**.
- **Branch convergence precedes any roadmap execution** — WC/ITF/perf/top-two stacks merged or
  discarded first.

---

## 18. Removed, renamed & deferred registry

**Renamed:** combo-vs-legs dutch book → **combo-leg bound inconsistency**; YES/NO parity opportunity
→ **parity data-quality check**; risk-adjusted score → **execution-quality score** (until
calibrated); display-only modeling → **non-classifying modeling/ranking layer**; free Advanced
upgrade → **owner-approved authenticated read-tier experiment** (docs say permanent grant; probe).

**Removed/deferred from near-term:** CategoryConfig rename (until a non-sport category enters);
mobile/tablet view; broad sharing controls; per-trader track record (until recorder + journal +
privacy); scheduled digests (until hygiene + outcome loop); full WebSocket quote streaming
(abstraction + lifecycle design doc only); model-weighted main ranking (until calibration + forward
validation); external-data adapter implementation (stub only; company-curated data later);
multi-process locks (document single-worker); `/exchange/user-data-timestamp` (dropped — user-data
freshness only).

**Out of scope unless separately approved:** order placement, automated execution, any POST,
private account/portfolio data, private WebSocket channels, trading-bot behavior, net-of-fees
actionability, de-vig/model-driven strict actionability.

---

## 19. Sequencing notes (input to the roadmap, not the roadmap)

1. **Immediate + parallel:** WC branch convergence + `KXWC` verification (kickoff 2026-06-11); ITF
   merge; the two trivial UI trust fixes (scanning indicator, selection-clear). These share no
   dependencies with anything else.
2. **Foundation:** capability registry + probe convention + budget planner; StrategyTemplate +
   ResearchSignal contracts; opportunity identity spec; EvidencePack.
3. **Data platform (feature-by-feature):** time-series migrations as each consumer lands —
   candlesticks (sparklines/movers/stale), orderbooks (depth panels), trades (tape), historical
   (calibration bootstrap), fees (fee line).
4. **Trader-trust UI:** AG Grid pilot → migration; status strip; standardized card + EvidencePack;
   exports.
5. **Exact detector expansion:** scalar ladders → bucket/range → combo bounds → duplicates →
   close-time sync → replication generalization. Sports continue by calendar in parallel throughout.
6. **Alerts (phase 1) → outcome loop (recorder, grading, survival analytics, calibration).**
7. **Research Lab + non-classifying model layer;** model-weighted lenses last, behind calibration
   evidence.

*Crossing any line in §0 or §18 requires an explicit owner decision recorded in this file.*
