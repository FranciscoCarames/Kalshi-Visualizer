# Strategy Brainstorm & Audit — 2026-06-19

**Status:** ANALYSIS ONLY. No code written, nothing implemented, nothing committed by this
session. This file is the lossless record of an adversarial strategy-brainstorming session so it
can be resumed (here or in a ChatGPT project) without re-deriving anything.

**Owner ask that drove this:** act as a hostile-but-useful strategy reviewer for the Kalshi
Structured Scanner; catalog candidate strategies, audit them, and decide what to add. The owner is
explicitly interested in **entirely new strategy families**, not just execution-trust upgrades.

---

## 0. Verified facts (live Kalshi docs + repo, this session)

- **Orderbook endpoint returns FULL depth** (all price levels + sizes; YES/NO bid arrays, asks
  derived as `no_ask = 1 − yes_bid`). The app uses **top-of-book only** — a self-imposed limit, not
  an API limit. Source: `docs.kalshi.com/api-reference/market/get-market-orderbook`,
  `getting_started/orderbook_responses`.
- **Rate limits are a token bucket** (not req/s): Basic = 200 read tokens/s, most calls = 10 tokens
  ⇒ ~20 req/s. App `MAX_RPS=15` ≈ 75% of that. Fine for the batch scanner; far too slow for live
  multi-market arb. Source: `getting_started/rate_limits`.
- **Settlement doc is thin** — does NOT publicly enumerate void/postpone/FMV rules. So every dutch
  book / synthetic rests on a settlement assumption the docs won't fully confirm. App is right to
  never say "riskless." Source: `getting_started/market_settlement`.
- **Fee schedule** verified earlier (memory `fee-schedule-verified`): taker 0.07 / maker 0.0175 ×
  multiplier, single round-up per order, maker only on `quadratic_with_maker_fees`, no settlement
  fee. App already shows taker+maker fee bands + breakeven, display-only, never ranks, plus opt-in
  `hideNetNegExec` filter.
- **WebSocket auth claim (UNVERIFIED):** the external audit asserts WS public channels still need
  API-key auth. REST market data is keyless (confirmed); WS-auth was NOT verified this session —
  verify before it informs any deployment/security decision.
- **CALENDAR — load-bearing:** FIFA **World Cup 2026 is LIVE right now** (group stage underway,
  knockout bracket imminent). The app's richest already-built detector family (WC group baskets,
  stage-of-elimination, exact-order, per-game dutch books) is **validatable on real liquidity this
  month** — a window that closes ~mid-July 2026.

### Engine map (source-verified this session)
All detectors test **exact integer-cent** inequalities on **top-of-book only**; **fees never enter
classification/ranking** (display-only); **no order-book depth beyond top-1**; **no partial-fill
modeling**. `scanner.unified_opportunities` ranks by `(bucket_priority, −gap_c)` — i.e. **largest
gross gap first** (this is a known weakness; see W1 below). Detectors present today:
containment ladder (`consistency.py`, incl. transitive/all-pairs closure + match-alignment),
dutch-book 2-way/n-way/field-overround (`dutchbook.py`), group cardinality baskets
(`find_group_baskets`), synthetic exact-score bundle (`synthetic_bundle.py`, review-only),
no-structures cheap-NO fades (`no_structures.py`), exact-order top-2 + game-support (WC, diagnostic),
stage-of-elimination (`stage_elim`), numeric ladder (`numeric_ladder.py`, **diagnostic-only,
NOT wired to Actionable**).

---

## 1. The strategy catalog (#1–#29) — my list, with soundness tags

Tag key: **Airtight** = structurally guaranteed *gross*, only settlement breaks it ·
**Model** = depends on an estimate being right · **Overlay** = trader-risk feature, not an edge ·
**ExecTrust** = makes existing signals less misleading, not a new edge.

| # | Name | Class | Tag | One-line |
|---|---|---|---|---|
| 1 | Full-depth edge sizing | ExecTrust | — | Walk the book → edge-vs-size curve instead of top-of-book "max units". |
| 2 | Net-of-fees gate | ExecTrust | — | Show net/taker/maker; **already shipped as display** (don't re-gate). |
| 3 | Persistence / realized-edge backtester | ExecTrust | — | Log each opp's survival + settlement → which detectors are real. |
| 4 | Liveness / staleness scoring | ExecTrust | — | Score quote age + close-time; diagnostic first, not a hard block. |
| 5 | Settlement-rule corpus + matcher | Infra | — | Structured void/retire/walkover classifier; unblocks cross-family promotion. |
| 6 | Live in-game dutch book (WS) | Strategy | Model/speed | Real but fleeting, fee-fragile, bot-competed. Needs #3 first. |
| 7 | Cross-series duplicate-listing arb | Structural | Airtight* | Same outcome listed twice; *settlement-identity proof required. |
| 8 | Correlated-exposure netting | Overlay | — | Show true aggregate exposure across shared-participant findings. |
| 9 | No-vig fair value | Model | Model | De-vig = estimate, not truth. Diagnostic only. |
| 10 | Historical-candlestick RV | Model | Model | Overfit-prone; defer. |
| 11 | Bracket-coherence baskets | Structural | Airtight* | One team per draw-half reaches final → hidden MECE field. *bracket state. |
| 12 | Cardinality-constrained league baskets | Structural | Airtight* | "exactly k of n advance" → fixed-sum floor. *count must be proven. |
| 13 | Numeric range replication | Structural | Airtight* | Replicate any range from strikes; cross-check vs direct. |
| 14 | Synthetic outcome replication | Structural | Airtight* | e.g. runner-up = reach-final − win; vs direct. *settlement. |
| 15 | General arbitrage LP | Structural | Airtight* | Master detector: min-cost portfolio with payoff ≥0 in every outcome. |
| 16 | Implied-correlation / dispersion (parlay) | Structural/Model | Airtight at bounds | Fréchet bounds are arb; inside the bounds is a correlation bet. |
| 17 | Spread-capture market-making candidates | Strategy | Needs trading | Post maker orders inside wide stable books; inventory risk. |
| 18 | Settlement carry / stub-hunting | Strategy | Thin/risky | Buy known-winner <100¢, hold to settle; void risk eats it. |
| 19 | Advancement hazard term-structure | Structural/Model | Mixed | Monotonic part airtight; survival-curve comparison is model. |
| 20 | Live order-flow momentum | Model | Model | Noisy, competed; research only. |
| 21 | Box / partition arbitrage | Structural | Airtight* | Complete bucket partition must sum to 100¢. |
| 22 | Digital-surface no-arb | Structural | Airtight | Monotonicity on digital strikes. **DO NOT port vanilla convexity/butterfly ≥0** (false positives on digitals). |
| 23 | Conversion / cross-parity | Structural | Airtight* | Direct strike vs synthetic strip; *settlement-matched. |
| 24 | Vertical / credit-spread analog | Expression | Not an edge | Collapses to a range bet on binaries. |
| 25 | Butterfly / pin bet | Expression | Not an edge | Just buying a narrow bucket; no convexity on binaries. |
| 26 | Condor / band bet | Expression | Not an edge | Probability view over a band. |
| 27 | Strangle / long-vol tails | Expression | Not an edge | Buy both tails; model bet, capped payoff (no gamma). |
| 28 | Calendar / horizontal spread | Mixed | Airtight if nested | Nested dates = containment (airtight); non-nested = model. |
| 29 | Ratio / backspread | Expression | Not an edge | Custom payoff shaping; structural only if it completes a partition. |

**Options framing (key insight):** A Kalshi "X ≥ K" YES contract IS a digital (binary) call; a strike
ladder IS an options chain. **But binaries cap payoff at $1, so the convexity/gamma that makes most
options structures attractive does NOT exist here.** The entire options surface reduces to one law:
**a complete partition must price to 100¢.** Box spreads, parity, verticals, butterflies, condors are
all slices of that one constraint. Only the no-arb/box cases (#21–#23) are real edge; #24–#29 are
*expression*, not edge — never label them "low risk."

---

## 2. External audit (ChatGPT) — and my critical review of it

The owner pasted a long external audit of #1–#29 that also proposed expansions #30–#60. **It is
well-structured and directionally right (trust its taxonomy), but it audited the prose, not the repo.
Distrust its build/already-have calls and its sequencing.** Six corrections:

1. **It recommends rebuilding shipped detectors.** ~40% of its "new" expansions #30–#45 already
   exist: **#30 all-pairs/transitive containment closure** (you have `tests/test_ladder_closure.py`
   41-test proof + the `feat/s1-transitive-illiquid-bridge` branch), **#34 stage-of-elim partition**
   (`stage_elim`), **#35 exact-order top-2** (`exact_order.py`), **#41 match-score synthetic**
   (`synthetic_bundle.py`), **WC cardinality baskets** (`find_group_baskets`). VERIFY in-branch
   before building anything — note several live on UNMERGED branches (`feat/scanner-consolidated` =
   PR #152 open; S1 branch), so "built" ≠ "in origin/main".
2. **Fee critique is a strawman.** It warns against a "net-of-fees gate" and asks for fee bands —
   already shipped (taker+maker per-leg + breakeven + `hideNetNegExec`, display-only). The only real
   open fee question is a narrow one it never asks: an **opt-in net-edge SORT** (not a gate).
3. **It conflates two settlement classes and mis-sequences.** Cross-family ideas (#7/#14/#23) need a
   settlement corpus; **same-series numeric structure (#21/#22/#36/#37/#38) does NOT** (legs share
   identical rules by construction — only boundary parsing matters). Lumping them parks the safest,
   highest-value, already-scaffolded build behind the hardest infra. Backwards.
4. **WS-auth claim is load-bearing but unverified** (see §0). Deferral of #6/#20 is right regardless.
5. **It inflates my own caveats into "corrections"** (#16, #25–#29, "you overuse airtight/locked").
   My list already tagged these as expression-not-edge / settlement-dependent. Partial concession:
   product-COPY wording discipline is a genuine live issue (QA punch-list item M2 = banned "locked"
   string leaked into copy).
6. **It's calendar-blind** — misses that the World Cup is live now and is the proving ground for your
   biggest already-built family.

**What the audit gets right:** persistence/validation as priority #1; the four-class separation
(ExecTrust / Structural / Overlay / Speculative); "fail closed on cardinality changes"; boundary
semantics as a fake-edge source; "build small proven LP domains before a general LP."

**Genuinely-new, NOT-yet-built items worth keeping from its #30–#60:** #36 over/under complement
parity, #37 coarse/fine range parity, #38 at-least/exactly transform, #40 series-score partition
(buildable on NHL `KXNHLSERIES` clean bo7 / NBA series), #46 slippage-adjusted $100, #47 edge
half-life, #49 false-positive taxonomy, #53 scenario payoff matrix, #54 rule-risk badge.

---

## 3. TOP 5 things to do right now (the converged recommendation)

Ordered. Three of the five exploit the live World Cup window.

1. **Persistence + fillability tracker, pointed at live WC markets.** Extend `lifecycle.py` + snapshot
   store (not greenfield) to log per opp: first/last seen, top-of-book size at first seen,
   time-to-disappear, eventual settlement. Answers the only question that matters: do detectors
   produce *takeable* edges or stale flashes? *Example:* of 120 flagged WC `KXWCGAME` dutch books, 95
   vanish <5s, 18 have 1–2 contracts, 7 persist 20s+ with 30+ contracts (6 of them one market type)
   → real hit-rate ~6%, and you now know where. No settlement risk; pure measurement. Also the
   calibration substrate for strategy #3-new (longshot harvest).
2. **Wire the numeric-ladder structural family to Actionable.** `numeric_ladder.py` exists
   diagnostic-only. Promote monotonicity (#22) + complement parity (#36) + same-series box/partition
   (#21/#37) + at-least/exactly (#38) — all one family. **Needs NO settlement corpus** (same-series).
   Only real risk = boundary parsing (`≥` vs `>`, OT, push). *Example:* "Total ≥220"=60¢ but
   "≥230"=63¢ → impossible → Buy YES ≥220 / Buy NO ≥230. Behind the F0 evidence gate already planned.
3. **Bracket-coherence (#11) + advancement-field (#32) for the WC knockout.** Goes live the moment the
   round-of-32 sets (days away) — now-or-wait-a-year. *Example:* 16 half-bracket "Reach Final"
   contracts sum to 94¢; exactly one reaches the final → buy all 16 = 6¢ guaranteed floor. Ship as
   `review_signal`, fail closed if any leg missing.
4. **Full-depth edge curve (#1 + #46).** Extend the existing depth-ladder plumbing to a per-opp
   edge-vs-size curve. *Example:* "+5¢, max 100 units" → really "+5¢ on 5 units (~$0.25), gone past
   30." Do after #1 tells you which detectors deserve a depth model.
5. **Two cheap trust overlays: exposure netting (#8) + rule-risk badges (#54).** No engine-correctness
   risk. *Example (netting):* three "Brazil underperforms" fades shown as one combined −$X exposure,
   not three diversified edges. *Example (badge):* a tennis match-alignment edge tagged
   `⚠ retirement-risk` (win-match voids on retirement; reach-next-round pays on the walkover).

---

## 4. ENTIRELY NEW strategy families (the owner's actual interest)

**Framing (the real fork):** every genuinely new family requires LEAVING the structural-arb island —
trading a guarantee for a **model**, **time/speed**, **external data**, or **statistical
calibration**. Several breach the SPA scope guard (no cond-prob/de-vig models). This is a product
decision, not just a feature. Six families, ranked by new-ness × soundness × fit-with-DNA:

1. **Latent-strength joint model (triangulation outlier detection)** — *net-new, best fit.* Fit ONE
   strength value across ALL of a participant's contracts at once; flag the leg most inconsistent
   with the others (uses 4 markets to price the 5th — more info than any pairwise check). *Example:*
   joint fit of 4 legs implies "Win title" should be 14¢; it trades 22¢ → fade the outlier. **Catch:**
   relative value, NOT arbitrage (no guaranteed payout); if all legs are wrong together the fit
   centers on the wrong value; **breaches no-model guard** (but it's market-ANCHORED, so least
   speculative of the model family). **Verdict: the one new family worth pursuing**, behind a hard
   "speculative, never Actionable" wall — same lane as the saved conditional-opponent plan.
2. **Cross-contract latency / lag relative value** — *net-new (= live-archetypes #1–#3 sharpened).*
   When a shared shock hits one market, trade the correlated market that hasn't repriced yet. Sounder
   than momentum (relative, not predictive). *Example:* striker ruled out → "win today" 55→40¢ but
   "top the group" still 48¢ → fade the stale leg. **Catch:** must beat everyone else on the news;
   corr <1.0; needs live feed + correlation map. **Verdict: research, blocked on live infra.**
3. **Systematic favorite-longshot-bias harvest** — *net-new as a systematic basket strategy.* Fade
   cheap longshots / buy strong favorites across a calibrated, diversified basket. *Example:* 4¢
   longshots settle YES ~2% → buy NO at 4¢ across many. **Catch:** empirical (can vanish), fees
   brutalize thin fades, and **cannot calibrate without your own settled-outcome dataset = strategy
   #1 above.** **Verdict: backtest-first, blocked on persistence data.**
4. **External fair-value overlay (Elo / power ratings)** — *net-new, but a different product.* An
   INDEPENDENT win prob to find absolute mispricings. **Catch:** competes head-to-head with sharps
   (public Elo is already in the price); "differs from market" ≠ "market is wrong"; fully breaks the
   structural identity. **Verdict: don't build as a strategy; research only, and only if it shows
   out-of-sample CLOSING-LINE VALUE.**
5. **Event-driven catalyst pre-positioning** — *net-new (scheduled-info speed).* React in seconds to
   inactives/weather/rulings that drop at known times. **Catch:** latency race lost to bots on liquid
   markets; only thin overlooked markets; needs a catalyst calendar + fast execution (read-only
   today). **Verdict: defer.**
6. **Live in-game overreaction mean-reversion** — *= saved live-archetypes #1–#3.* Fade the overshoot
   after a score. **Catch:** needs a live in-game cond-prob model (scope breach), bot-competed,
   momentum can run you over. **Verdict: research, blocked on live+model infra (unchanged).**

**Decision forced:** exactly ONE new strategy is both novel AND faithful to the conservative DNA —
**#1 latent-strength joint model** (market-anchored relative value, never Actionable). #2 and #3 are
real but blocked on infra you'd have to build anyway (live correlation feed; settled-outcome dataset
— note #3 is *why the persistence tracker matters even if you only care about new strategies*).
#4–#6 are a different product (model-vs-sharps / speed-vs-bots) and a decision to stop being a
structural scanner.

---

## 5. Open decisions / next actions for a future session

- [ ] **Decide the product fork:** stay structural-only, or extend the scope guard to allow a
      market-anchored relative-value lane (required for new-strategy #1). Owner call.
- [ ] If yes to #1: take **latent-strength joint model** through the full hostile `<output_format>`
      critique — esp. the "confidently tells you nothing" failure mode, and how it differs from the
      saved conditional-opponent complement-gap detector.
- [ ] Build order if proceeding with structural work: **persistence tracker (top-5 #1)** →
      **numeric-ladder wiring (top-5 #2)** → **WC bracket-coherence (top-5 #3)** while the WC is live.
- [ ] **Verify-before-build:** confirm in-branch which audit "expansions" already exist (#30/#34/#35/
      #41/WC baskets) and whether they're in origin/main or only on unmerged branches.
- [ ] Verify the **WS public-channel auth** claim before any live-feed/deployment decision.
- [ ] Numeric-ladder F0 evidence gate (existing owner reminder, memory `s2-numeric-ladder-wiring`)
      governs promotion of top-5 #2.

## 6. Cross-references (existing memory / repo)

- `STRATEGY_NOTES_LIVE_ARCHETYPES.md` (repo root) — the 4 live-trading archetypes (this session's
  new-strategy #2/#6 overlap archetypes 1–3; archetype 4 = field-sum-live = the in-scope buildable
  one).
- `.claude/plans/concurrent-wandering-fairy.md` — saved conditional-opponent complement-gap detector
  plan (the speculative lane new-strategy #1 would join).
- memory: `s2-numeric-ladder-wiring`, `fee-schedule-verified`, `live-trading-archetypes`,
  `conditional-opponent-strategy-plan`, `detector-audit-plan`.
- `DETECTOR_AUDIT_PLAN.md` + `.claude/plans/optimized-swimming-badger.md` — prior 5-wave detector
  audit plan (41 issues).
