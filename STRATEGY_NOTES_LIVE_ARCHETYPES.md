# Strategy notes — elimination↔qualify synthetic + 4 live-trading archetypes

**Status: ANALYSIS / DISCUSSION ONLY — no code changes. Forward-looking; most of this is NOT
implemented in the default app.** Captured 2026-06-18 from a deep-dive conversation. Self-contained.

---

## Part A — World Cup: "being eliminated" ↔ "qualifying / advancing" (IMPLEMENTED)

Lives in `stage_elim.py`. Two separate checks over a team's `KXWCSTAGEOFELIM` event.

### The contracts (per team, e.g. Spain)
- **Elimination event** `KXWCSTAGEOFELIM-26ESP` — 7 mutually-exclusive, exhaustive buckets, exactly one
  settles YES: `GS, R32, R16, QF, SF, FL (runner-up/lost final), FW (winner)`. Stamped `kind="stage_of_elim"`.
- **Reach/advance markets** — single-sided, `kind="advance"`, with a `ladder_node`:
  - `KXWCGROUPQUAL-26<grp>-ESP` → **"Reach Round of 32"** (qualifying from the group = reaching R32)
  - `KXWCROUND-26RO16-ESP` → "Reach Round of 16" … up to "Win the World Cup".

### The core identity
`"Reach stage S"  ⟺  "eliminated at S or any LATER stage"  =  tail-sum of buckets from S onward.`
Encoded in `stage_elim.py:50` (`_RUNG_TAILS`):

| Reach rung | = these elimination buckets |
|---|---|
| Reach Round of 32 | R32+R16+QF+SF+FL+FW |
| Reach Round of 16 | R16+QF+SF+FL+FW |
| Reach Quarterfinals | QF+SF+FL+FW |
| Reach Semifinals | SF+FL+FW |
| Reach Finals | FL+FW |
| Win the World Cup | FW (single bucket) |

Note: being eliminated **in** the R16 still counts as **reaching** the R16 — that's why R16 is in its own tail.

### Two detectors
1. **`find_stage_elim_books`** — standalone 7-bucket MECE dutch book (within the one event only).
   Underround = Buy YES all 7 < 100¢ floor; overround = Buy NO all 7 < 600¢ floor. **Actionable-eligible**
   (clean single-family settlement, no cross-family risk).
2. **`find_stage_elim_synthetics`** — the cross-family tail-sum vs the direct reach market. Joins on
   `(team UUID, ladder_node)` via `_advance_index` (`stage_elim.py:205`). **REVIEW-ONLY, never Actionable**
   (`tradable_now="Review rules"`, `SETTLEMENT_CHECK_REQUIRED`): a walkover/withdrawal can make the reach
   market settle YES without the elimination buckets resolving to a matching bucket → the constant-payoff
   guarantee breaks → not arbitrage.

### Payoff walkthrough — Direction B ("reverse"), "Reach Round of 16" rung
6 legs: Buy NO each of the 5 tail buckets {R16,QF,SF,FL,FW} + Buy YES the reach market. Floor = 5×100 = 500¢.
Illustrative prices: NO asks 82/80/84/86/86 (=418) + reach YES ask 78 → cost 496¢ → **+4¢ gross/unit**.

- **Spain out in R16:** R16 bucket YES → its NO leg pays 0; other 4 NO legs pay 400; reach YES pays 100
  (Spain DID reach R16). Total 500¢. Profit +4¢.
- **Spain out in group stage (GS):** GS isn't one of the legs; none of the 5 tail buckets hit → all 5 NO
  legs pay 500; reach YES pays 0 (didn't reach R16). Total 500¢. Profit +4¢.
- **General rule:** exactly **5 of 6 legs pay 100¢ in every outcome** → constant 500¢ floor. Cost < 500 = edge.

(Forward direction: Buy YES the tail + Buy NO the reach market, floor 100¢; only one direction can fire
since bid ≤ ask.)

### Generality (Part A follow-ups)
- **Other sports?** The scanner runs the detectors for every sport (`scanner.py:610-611`) but only soccer
  emits `kind="stage_of_elim"` (`sports.py:1006`, `KXWCSTAGEOFELIM`), so it's effectively soccer/WC-only.
  Also hardwired to the WC: `_BUCKETS` from `sports.WC_STAGE_ELIM_BUCKETS`, `_RUNG_TAILS` literal WC rungs.
  To support another bracket sport you'd need such a market on Kalshi + lifting `_BUCKETS`/`_RUNG_TAILS`
  into `SportConfig`.
- **Different YES leg?** Yes — the YES leg can be ANY market equal to a subset of the MECE partition.
  Already variable (any `advance`/`winner` rung). The **"Win the World Cup" outright** (`KXMENWORLDCUP` =
  single FW bucket) is the cleanest, noted in `stage_elim.py:48-49` but disabled (sub-cent → subpenny guard).
  Non-tail subsets (e.g. "fail to qualify" = {GS,R32} prefix) also valid, just not enumerated.
- **The strongest sibling:** `synthetic_bundle.py` is the SAME pattern with a different partition + YES
  legs — tennis exact-score states {3-0,3-1,3-2} replicate "win the match", hedged against the
  match-winner market AND the advance node (`hedge_kind ∈ {match, advance}`). Same constant-floor build,
  same review-only settlement caveat.

---

## Part B — Four LIVE-TRADING archetypes (FORWARD-LOOKING, mostly NOT built)

**Unifying idea:** the fair price of a SLOW (outright) leg is a straight line in a FAST (live) leg's
price, because the slope/coefficients are frozen by something that doesn't move during the live event.
Signal = the slow leg falling off that line (it lags the fast leg).

### Archetype 1 — Conditional-opponent blend
- **Logic.** Contender A locked into the final; opponent decided by a live B-vs-C semifinal.
  `A_title = P(C reaches final)·P(A beats C) + P(B reaches final)·P(A beats B)`. The matchup terms are
  about the future final (unchanged by B vs C playing now) and are **market-implied**:
  `P(X beats A) = X_title / X_reach_final`. Only the live SF price moves → A_title is linear in it.
- **Example (tennis, French Open).** Alcaraz (A) in final; Sinner (C) vs Djokovic (B) live.
  Sinner 10¢ title / 50¢ reach-final → P(Alcaraz beats Sinner)=80%. Djokovic 20¢/50¢ → P(Alcaraz beats
  Djok)=60%. SF 50/50 → fair A_title = 0.5·80+0.5·60 = 70¢. Sinner surges to 75% → fair = 0.75·80+0.25·60
  = 75¢. If Alcaraz outright still 70¢ → buy, target 75¢.
- **Lies:** a third path to the final exists (field not closed) → blend incomplete; or outright is
  illiquid not stale → spread eats the edge.
- **Model risk: LOW** (conditionals fully market-implied).

### Archetype 2 — Series-state ↔ live game
- **Logic.** Best-of-N. `Win_series = P(win game)·P(series|win) + P(lose game)·P(series|lose)`. The
  conditionals are pinned by the SCOREBOARD (doesn't change mid-game) → series outright linear in live
  game price.
- **Example (NBA).** Celtics up 3-2, Game 6. Win→clinch (100%); lose→Game 7 ~50/50 (50%). Live Game 6
  Celtics 60% → fair Win_series = 0.6·100+0.4·50 = 80¢. Outright 75¢ → buy, target 80¢.
- **Lies:** `P(series|lose)=50%` is a combinatorial assumption — wrong with home/away or pitcher/goalie
  splits. MLB excluded: `KXMLBSERIES` non-MECE (can sit 2-2). NFL/tennis/golf have no series.
- **Model risk: HIGH** (market-anchored but not market-implied).

### Archetype 3 — Containment-ladder-live
- **Logic.** The existing static `consistency.py` ladder (broad ⊇ deep) but the shallow rung is LIVE.
  Hard cap always: `Win_tournament ≤ Win_this_match`. Ratio stability short-term:
  `Win_tournament / Advance = P(win title | advance)` ≈ constant. Archetype 1's ratio pointed INWARD
  (one participant's own ladder).
- **Example (tennis).** Live QF. "Win this match"(≈reach SF)=70%, "win tournament"=21% → fraction
  21/70=30%. Live match jumps to 90% → fair win-tournament = 0.9·30% = 27%. Outright still 21% → buy,
  target 27% (cap holds: 27 ≤ 90).
- **Lies:** the fraction genuinely shifts (brutal next-round opponent emerges); or rung mapping wrong
  (NHL "1st/2nd Round" wording → `UNKNOWN_RELATIONSHIP`).
- **Model risk: MEDIUM.**

### Archetype 4 — Field-sum-live
- **Logic.** One-winner field. `Σ Win_outright(all contenders) ≈ 100¢ + overround`. The DYNAMIC version
  of `dutchbook._detect_field`. One leg reprices fast on live action, laggards slow to give back points →
  field transiently sums < 100¢ → buy whole field for <100, collect ≥100 at settlement.
- **Example (golf, final round).** Scheffler 50 / McIlroy 30 / Rahm 20 = 100. Scheffler bogeys 17th live
  50→40, others static → field = 90. 10¢ gap → laggards too cheap; trade the side that hasn't caught up
  (or buy all 3 for 90¢ → guaranteed ≥100¢).
- **Lies:** overround isn't constant — vig widens in fast markets (sum<100 may be a quote artifact); or a
  contender's market missing/closed → sum over an incomplete (non-MECE) field.
- **Model risk: LOWEST** (pure accounting). **Only one whose STATIC form the app already computes
  (`_detect_field`) → natural first to build live.**

### Scope reality (why 1-3 aren't in the default app)
1. **No live leg by default** — scanner reads a periodic SQLite snapshot, not a stream. Real-time feed
   exists only on experimental `experiment/realtime-sse-stage1` (DEFAULT-OFF, `KALSHI_LIVE_ENABLED`).
2. **Conditional-probability math is out of SPA scope** — CLAUDE.md scope guard keeps de-vig/cond-prob out
   of the React SPA (display-only); it lives only in the legacy NiceGUI `/dashboard` de-vig panel by owner
   exception. Archetypes 1-3 require it; **Archetype 4 (pure overround) is the in-scope exception.**

**Practical read:** Archetype 4 = continuous re-run of an existing in-scope detector (cheapest, most
robust). Archetypes 1-3 = genuinely new, each needs a live feed + the conditional-probability layer the
SPA deliberately omits. #1 is the highest-value new idea (conditionals fully market-implied).
