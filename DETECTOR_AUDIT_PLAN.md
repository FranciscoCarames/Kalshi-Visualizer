# Plan: Resolve the full audit issue list (phased by value)

## Context

A comprehensive audit across this session surfaced **41 issues** with the Kalshi scanner, in five
buckets: detector **soundness bugs** (logic that flags wrong or silently drops real edges), **coverage
gaps** (whole sports, contract scopes, ladder rounds, and competitions Kalshi offers but the app
ignores), and **trust/UX** items. Cross-referencing Kalshi's authoritative taxonomy
(`/search/filters_by_sport`, `/search/tags_by_categories`) and a live `/events` probe (7,357 open
events / 2,634 series) confirmed the app registers **10 of Kalshi's 19 sports** and, within those,
covers a minority of contract scopes and ladder rounds.

**Owner decisions shaping this plan:**
- **Phase by value** — solve the *classes* first (engine fixes → reuse existing detectors → highest-value
  new ownership), then grind the long tail from a repeatable recipe. Not everything in one giant push.
- **Engine stays gross / exact-integer-cents / display-only** (unchanged philosophy). The only behavioral
  UX change approved: add a **quote-age/staleness gate** to `tradable_now` and **default-hide
  fee-negative** executables.
- **Deferred — no new whole sports.** Do NOT register any of Kalshi's 9 unregistered sports (MMA, Boxing,
  Rugby, Cricket, Aussie Rules, Lacrosse, Chess, Darts, Cities). Work stays within the **10 already-registered
  sports**. New *competitions* and *scopes* inside those 10 (e.g. club soccer, non-FO tennis winners) are
  still in scope — they are not new sports.
- **Out of scope (owner handles):** the live-capture *measurement* harness (24–48h opportunity-frequency
  logging); all git/branch/working-tree housekeeping. **NOTE:** this is distinct from the per-detector
  **correctness fixtures** added below (saved real Kalshi JSON + expected classification) — those are an
  in-scope test gate, not the declined measurement harness. Flagged for owner override if both were meant out.
- **Hard gate for any NEW ownership:** a live read-only `/series`+`/events` probe to confirm the
  **settlement shape** (MECE / tie / push / dead-heat conventions) *before* enabling — taxonomy proves a
  contract exists, not that it's safe to flag.

**Roadmap status (only Wave 1 is "ready to start").** This is a phased roadmap, not one approval. **Wave 1
+ 1b** can begin now (pure-logic fixes + the two approved UX guards; unit-tested). **Waves 2, 3, 4 each
require passing the per-wave acceptance gate** (below) *before* that wave starts — fixtures, payout-floor
test, duplicate-row test, scope-guard isolation, and (Wave 3/4) a request-budget estimate. No
settlement-sensitive detector or new ownership ships on taxonomy + format assumptions alone.

**Base branch — confirm before starting.** Branch off the *actual* newest in the stack, currently
**`feat/workspace-ladder-condtable`** (`82a4bcc`, **pushed**; chain: footprint-and-visibility →
dashboard-public-bypass → workspace-ladder-condtable). Verify with `git log` at start; do **not** trust
`APP_REFERENCE.md` (stale). State the exact base + dependency chain in the handoff.

**Code-currency check (done this session).** The plan's file:line anchors were read on
`feat/footprint-and-visibility`; the newest tip adds 6 commits (DASHBOARD_PUBLIC flag, depth-panel rung
picker, cond-prob LADDER PROBABILITY table, persistent workspace layout). Impact on the plan:
- **Engine cores UNCHANGED** (`dutchbook.py`/`consistency.py`/`synthetic_bundle.py`/`scanner.py`/`data.py`
  have zero diff) → **all Wave 1 + Wave 2 engine references are exact.**
- **`sports.py`** only gained a `"kind": absolute|conditional|bound` tag on derived-indicator dicts (≈+4
  lines after `:243`) → ladder/family references shift by a few lines; treat sports.py line numbers as
  *indicative* and re-confirm at edit time.
- **UI files moved** (`frontend/src/context.tsx`, `App.tsx`, `Ladder.tsx`, `Inspector.tsx`, `Workspace.tsx`,
  `webui/dashboard.py`, `webui/viewmodel.py`) — Wave 1b/parity anchors below are refreshed to the tip.

**Guiding principles** (do not regress): reuse existing detectors/ladders rather than writing new code;
keep pure logic modules UI-free; exact-integer-cent comparisons; conservative wording; branch-only
delivery off the current `feat/footprint-and-visibility` (state the base in handoff), `main` frozen;
`pytest -q` + `ruff check .` + a `serve.py` boot + `scripts/verify_sport.py <sport>` before each handoff.

**Dual-UI parity (owner-requested):** every coverage change must surface in **both** the React SPA (`/`)
**and** the legacy NiceGUI dashboard (`/dashboard`). Both are generic read-only views of the same engine
+ snapshot store, so the bulk is automatic:

- **AUTOMATIC in both** (no per-UI work): new **sports**, **competitions/series**, and **ladder rungs**,
  plus any new detector finding that reuses the standard fields (`action_1/2_*`, `exec_gap_c`, `bucket`,
  `status`). The NiceGUI dashboard derives Sport/Tournament/Participant filters from the data
  (`webui/viewmodel.derive_options`) and renders per-bucket dynamically; the SPA feed is a 1:1 view —
  parity is guarded by `tests/test_feed.py` (counts/IDs/buckets identical).
- **NEEDS PARALLEL WIRING in each UI** (the exceptions — budget for these explicitly):
  1. A **new UNIFIED_COLUMNS field** must be declared on `api.Opportunity` (`api.py:91`) or the SPA drops
     it (`extra="ignore"`); to *display* it in NiceGUI, reference it in `webui/viewmodel.opp_row` /
     the table column defs.
  2. A new detector family wanting **bespoke presentation** (a dedicated section or special evidence
     columns) follows the existing Risk-budget / Near-miss / Qualifier / No-structure precedent — each
     has its own `vm.*_row` + dashboard section **and** a React component. Both must be built.
  3. **Wave 1b fee-negative default-hide is SPA-only today** — the NiceGUI dashboard has a *"Show net of
     fees" column toggle* (`webui/dashboard.py`, near the opp-table column menus) but no row-hide filter.
     Achieving parity means adding an equivalent row-hide option to the dashboard (the `net_negative` signal
     is already single-sourced in `webui/viewmodel.py`).
  4. **New ladder UI on the current tip** (since the agents read the code): the cond-prob **LADDER
     PROBABILITY table** + **depth-panel rung picker** (`frontend/src/Ladder.tsx`/`Inspector.tsx`) render
     the ladder rungs and the `P(deeper|broader)` conditionals, fed by `SportConfig`'s derived-indicator
     dicts (now tagged `kind: absolute|conditional|bound` in `sports.py`). **Implication for Wave 2 rungs**
     (tennis bracket, NBA/NHL middle rungs): new rungs auto-extend this table + the picker — verify they
     render correctly there (extra SPA surface) and that the NiceGUI ladder view stays in parity.

---

## Wave 1 — Engine soundness fixes (kill false flags + silent drops)

These *reduce* flag count but are the trust foundation. Pure-logic modules; each gets unit tests.

| # | Fix | Touch point |
|---|---|---|
| A1 | Add `"One-sided"` to `_NO_FIRM_QUALITY` so a bid-only leg can't fabricate a `100−yes_bid` NO price that inflates an overround into firing. **Per-buy-leg, not a blanket label:** the gate must hold (a) the buy-side price exists, (b) the *executable* side has size, (c) status tradable, (d) the reciprocal NO fallback uses the correct side and doesn't conflict with a direct `no_ask_dollars`, (e) subpenny isn't rounded into a fake edge. For `synthetic_bundle.py` do **not** mirror blindly — apply per buy leg (a valid exact-score ask leg must not be suppressed because its *opposite* side is one-sided) | `dutchbook.py:74` + blocker lists in `_detect_pair/_n_way/_field`; `synthetic_bundle.py:68` per-leg |
| A2 | Stop the soccer ladder fragmenting: give SOCCER a `tournament_key_fn` that canonicalizes all WC series to one season key (mirror motorsport `_motor_tournament_key`), instead of relying on the divergent `competition` string | `sports.py` (new `_soccer_tournament_key`), wired via `SportConfig.tournament_key_fn`; consumed already by `data.tournament_of` |
| A3 | Let a subpenny leg into the **display** test while still excluded from the **executable** test, so "Win the World Cup" (deci-cent) stops vanishing as the deepest rung. **Required test:** a subpenny row can *never* become actionable via cent rounding. Keep display tolerance coarse + explicitly labelled (don't pretend deci-cent precision under integer cents) | `consistency.py:718-721` (don't drop the row; tag it display-only) |
| A4 | Add a `RULE_CHECK_REQUIRED`-style settlement-token flag on golf/motorsport finishing-position pairs (tie/dead-heat convention not verified). **Define concrete allowed/blocked rule tokens + fixture examples** before trusting a pair — ⚠ live-probe conventions first | `sports.py:735-741,1305`; reuse the match-alignment rule-flag path in `consistency._classify` |
| A5 | Broaden `prove_mece` draw-excluded gate from one literal string to a phrase set, and emit a coverage alert when a `mutually_exclusive` 3-team+tie event fails *only* the phrase check. **Fail closed** if structured fields can't prove the shape; store the rule-text hash that passed the probe. Negative tests: tie-not-100¢-third-outcome / void-or-half-pay draw / >3 markets / duplicate-alternate markets | `dutchbook.py:447` |
| A6 | Surface unmapped **advance** stages as a **diagnostics/coverage** signal (today they silently drop). **Route to diagnostics first, NOT the primary opportunity table** — these aren't trader-actionable and would just add noise to the scanner | `consistency.py:812` |
| A7 | Convert motorsport `family_fn` from substring+blocklist to an exact-ticker allow-list (current form can mis-route a new prop into a field dutch book). Pair with a **coverage alert for unknown motorsport-tagged series** (from `filters_by_sport`/`tags_by_categories`) so the allow-list doesn't silently rot | `sports.py:1313-1337` |
| A8 | Latent hardening — **split into 6 separate tickets/tests, not one change:** (1) NBA anchor "Finals"→title only on `KXSB`/conf qualifier; (2) NHL `_nhl_stage` explicit map (drop `else "Conference"`); (3) **same-event + same-family + same-settlement-rule-class + same-participant-universe + same-expiration** guard on `_detect_field`/`_detect_n_way` (same-series is necessary, not sufficient); (4) record ">2 two-way markets in event" rejects to `_diag`; (5) replace `sport_id=="soccer"` n-way dispatch with a capability flag; (6) align `viz.ladder_prices` inversion to engine-adjacent pairs | `sports.py:536,1136`; `dutchbook.py:627,288,947`; `viz.py:51-59` |

**Verify:** new tests in `tests/test_dutchbook.py` / `tests/test_consistency.py` / sport tests; `pytest -q`;
`scripts/verify_sport.py soccer|golf|motorsport`.

## Wave 1b — Trust UX guards (approved behavioral changes)

- **Age gate (lifecycle layer, not the price classifier):** keep `status`/`bucket` as pure
  price/settlement classifications; add the staleness downgrade in the **actionability** field —
  `tradable_now = "No — stale snapshot"` — fed by an explicitly-injected, tested age value (don't make the
  relationship logic depend on wall-clock state). **Snapshot age ≠ quote age:** prefer per-market
  `updated_time`/`last_updated_ts` where present over global snapshot age. The 5-min
  `STALE_AFTER_SECONDS` is a blunt global guard — make it **configurable by sport/scope** (5 min is loose
  for thin in-game books, fine for outrights) or at least label it as crude. Engine math untouched.
- **Default-hide fee-negative (both UIs) — taker-negative only, maker distinction visible:** you are often
  a *maker*, so default-hide must mean **hide taker-negative only**, never hide a *maker-positive* row.
  Surface taker net edge, maker net edge, a "maker-positive / taker-negative" badge, the fee-type source,
  and breakeven after maker/taker fees. Flip the SPA default at the `useState` initial in
  `frontend/src/context.tsx:108` (`hideNetNegExec: false → true`); `config.py:340 PREFS_SETTINGS_BOOL` is
  only the key allow-list, not the default. Toggle UI `App.tsx:154`, hidden-count reveal `App.tsx:336`,
  filter predicate `hiddenByFee` at `context.tsx:320/338`. **Persisted-prefs nuance (new since the auth
  work):** `hideNetNegExec` is saved per-user (`auth_store.sanitize_prefs`), so flipping the default only
  affects **new/unsaved** users — existing saved prefs persist; decide migrate-vs-accept. **And** add the
  matching row-hide to the NiceGUI dashboard (fee *columns* exist via the "Show net of fees" toggle near the
  opp-table column menus in `webui/dashboard.py`; no row-hide yet), reusing `net_negative` in
  `webui/viewmodel.py`. Confirm taker/maker coefficients against the live fee docs. **Verify:** vitest + a
  serve boot showing both `/` and `/dashboard` hide *taker*-negative by default while keeping maker-positive rows.

---

## Wave 2 — New CONTRACTS for already-owned competitions (reuse existing detectors)

**Scope boundary (do not cross):** the competition is *already scanned*; here we only add a new contract
family / scope / ladder rung to it — **no new competition is fetched.** (Onboarding a competition the app
doesn't yet own is Wave 3; enriching a *newly*-onboarded competition with extra contracts is Wave 4.) The
theme is "classify + wire", but several items need **new proof logic** (monotonicity, push handling,
same-line matching, settlement equivalence) — treat these as detectors, not trivial reuse. Each item
passes the per-wave acceptance gate before shipping.

1. **Scalar over/under ladders — one sport/scope FIRST, not a family.** `Win Totals` (team) vs game totals
   vs `Total Goals/Maps/Home Runs` (different entities) vs `1st Half Total` (different scope) are
   materially different universes with different push conventions; **Over** monotonicity and **Under**
   monotonicity run in *opposite* directions. Implement **one** scope first — pick a **half-point line with
   no push** (e.g. a single sport's game total) — reusing the golf Top-N `LadderSpec` pattern
   (`sports.py:735`); generalize only after fixtures pass. ⚠ push-rule live-verify per scope.
2. **Over/Under Σ=100 dutch pair — needs its OWN push proof** (a totals push ≠ an NFL tie; do not copy the
   tie gate). Prove from Kalshi rules whether the exact line settles push / half / void / clean binary,
   then route the pair into `dutchbook._detect_pair`. **Match the line via structured strike fields**
   (`floor_strike`/`cap_strike`/`functional_strike`/`custom_strike`), never title parsing.
3. **Tennis `Set Winner` detector — review-only first.** `set_winner` is classified (`sports.py:442`) but
   un-detected. It's settlement-sensitive (retirement / walkover / incomplete set / fair-market-price), so
   start it **review-only** until Kalshi rules prove clean binary settlement for incomplete matches —
   mirror the existing synthetic-bundle review-only posture.
4. **Tennis bracket rungs — per-tournament, draw-size-aware, NOT a fixed uniform ladder.** ATP/WTA draws
   vary (32/48/64/96, byes, round-robin finals); a hardcoded `R32→…→Win` chain is wrong for 96-draws and
   partial listings. Make the ladder/rungs **probe-driven per tournament** when extending `_TENNIS_LADDER`
   (`sports.py:418-422`). ⚠ live-verify `KXATPADVANCE`/`KXWTAADVANCE` carry the intermediate rounds and the
   draw shape per event.
5. **NBA / NHL middle-round rungs** — map the recognized `First Round`/`Conference Semifinals` (NBA) and
   `1st/2nd Round` (NHL) stages to nodes, but **only where the ticker + rule confirm the exact semantic**
   ("Reach 2nd round" ≠ "Win 1st round"); don't assume label equivalence (`sports.py:551,1109`).
6. **`KXWCSTAGEOFELIM` overround — keep in its dedicated detector, don't generalize into `field_families`.**
   A stage-elim detector + review-only tail-sum synthetic already exist; folding it into generic field
   overround risks duplicate rows, inconsistent labels, and accidental underround without exhaustiveness.
   If an overround is worth adding, add it *inside* the dedicated detector with its own payout-floor proof.
7. **`group_bottom` overround on a subset — define precedence to avoid dup.** `KXWCGROUPBOTTOM` is already
   modelled as an exactly-one-of-four basket; a generic subset overround overlaps it. Rule: **group basket
   first**, subset overround only if not a duplicate, under a distinct label.
8. **Division-winner containment — MLB/NFL only, never NBA blindly.** MLB (12-team) and NFL (14-team)
   division winners auto-qualify, so "Win Division ⊆ Reach Playoffs" holds; **NBA does NOT** (play-in;
   division winner is a tiebreak, not a guaranteed berth) — exclude NBA unless a specific Kalshi market
   rule proves the implication. Classify `division_winner` and hang it off `Reach Playoffs` as an
   `optional_children` leaf (mirror soccer "Win group").
9. **Synthetic bundle → NHL/NBA series-result — review-only, do NOT auto-promote to Actionable.** Fill
   `state_bundles`/`score_format_fn` for `{4-0,4-1,4-2,4-3}` (bo7) + a series-score parser. A bo7 *format*
   does not prove the exact-score market settles identically to the series-winner under postponement /
   forfeit / abandonment / amendment, so keep it **review-only** until per-market rules prove equivalence
   (drop the "promote via flag" idea). The series-score parser must resolve **which team / home-away order /
   series identity**, and reject duplicate / missing / closed / "series spread" vs "game count" lookalikes
   (`synthetic_bundle.py:413,421`).
10. **`KXWCTEAMH2H` ("Who Will Go Further") — new contract in the already-owned World Cup.** Not assumed a
    clean 2-way: two teams can exit the *same* round, so prove Kalshi's tiebreaker / split-settlement first.
    **Review-only** until same-stage-elimination handling is confirmed; then route to `_detect_pair`.
11. **Tennis non-FO winners — new winner contract for already-scanned tournaments.** ATP/WTA *matches*
    already flow by prefix; only the tournament-**winner** series (Wimbledon/US Open/Masters) are UNKNOWN.
    Add the winner family taxonomy-driven + fixture-backed per tournament (identity/tour/draw/settlement
    separated), retiring the stale FO date window — not a widened `KXFO*`/prefix match (`config.py:106`).
    *(This is a new contract, not a new competition: the tournaments' matches are already in scope.)*

**New-detector wiring (items 1-3, 9, 10) — fixed checklist:** `_to_unified_*` mapper + dispatch line in
`scanner.py` (~`:580`), `STATUS_GROUP` entry + `bucket_of` branch in `consistency.py` (`:63`,`:945`),
declare any new fields on `api.Opportunity` (`api.py:91`), tests under `tests/test_<detector>.py`.

---

## Wave 3 — Onboard NEW COMPETITIONS within owned sports (core market only)

**Scope boundary:** this wave only brings a competition the app doesn't currently scan into ownership, via
its **single core market** (e.g. the match result) — *not* its full contract suite. Enriching it with more
contract families is **Wave 4**, deliberately separated. No new sports (MMA/Boxing deferred). **Every
competition starts with its own live settlement-shape probe; do not enable on taxonomy alone.**

1. **Soccer club competitions — EACH competition is its own settlement model; never reuse another's rules.**
   This is the highest false-flag risk in the plan. Competition rules differ in ways that change the MECE
   shape and the payout floor: regulation draws vs ET/penalties in knockouts, **two-legged aggregate ties**
   (away-goals / aggregate / replay conventions), **group-stage tiebreakers**, abandoned-match/replay rules,
   and whether a "result" market is 90-min-only or includes ET. So:
   - **One competition at a time**, each independently probe-gated and fixture-backed (its own
     `rules_primary` captured), manually validated before the next — **no shared assumption across leagues.**
   - Onboard **only the core 90-min result market** (the clean 3-way Home/Away/Tie) in this wave. Do **not**
     blanket-route into `_detect_n_way` or pull in advance/group/totals contracts yet — those are Wave 4.
   - Start with the **single highest-liquidity** competition. Add the result series to `_SOCCER_EXACT` +
     `default_series`; map in `_soccer_family`/`_soccer_stage`. ⚠ probe its game-ticker + tie shape, every time.
2. **Lower-value new competitions in owned sports** (after the soccer pattern is proven): College FB/BB,
   intl basketball leagues, LIV / LPGA / majors golf — same one-at-a-time, core-market-only, probe-gated
   discipline. Capture the add-competition checklist as `docs/COVERAGE_RECIPE.md`.

**Deferred (new whole sports — owner decision, not in this plan):** MMA, Boxing, Rugby, Cricket, Aussie
Rules, Lacrosse, Chess, Darts, Cities. When revisited, each needs a new `SportConfig`, the tie/non-binary
settlement gate where applicable, high-confidence identity (no name-only matching), and a review-only start
until rules prove the 100¢ floor. Parked, not implemented.

---

## Wave 4 — New CONTRACTS for the newly-onboarded competitions + long-tail strategies

Once a competition is onboarded (Wave 3), layer in its additional contract families — kept **separate** from
onboarding so each contract gets its own probe + payout proof and a bad contract can't taint the core
result market. Each item gated on a live settlement-shape probe + the per-wave acceptance gate.

- **Contracts for the Wave-3 competitions:** advance/knockout ladders (per-competition stage shape —
  to-advance is 2-way via ET/penalties), group markets, totals/over-under, correct-score bundles. Add per
  competition, one family at a time.
- **Remaining scopes in long-owned competitions:** golf `3-Ball` (3-way MECE) + `Matchups` (2-way), soccer
  WC `Correct Score` (bundle), esports `*MAP` counterparts of owned titles, `KXMLBSERIES` playoff-series
  dutch books (⚠ verify odd-length).
- **New strategy families:** exact-order ⊆ group-winner (extend `exact_order.py`), cross-event containment
  (group-winner ⊆ reach-knockout; division ⊆ playoffs), calendar containment (close-time gate),
  duplicate/equivalent-market detector, combo Fréchet upper-bound (needs multivariate-event ingestion).

---

## Issue → wave coverage map

- **Soundness (A1–A8 / items 1–8):** Wave 1.
- **Trust UX (items 35–36):** Wave 1b. *(34 validation harness, 37 diagnostic surfacing — out of scope/owner.)*
- **New CONTRACTS for already-owned competitions** (scalar scopes, ignored families, rungs, WC H2H #15,
  non-FO tennis winners; items 13–28): **Wave 2.**
- **New COMPETITIONS in owned sports** (club soccer, College FB/BB, intl basketball, LIV/LPGA/majors golf;
  items 29–33): **Wave 3** onboards the core market; **Wave 4** adds their further contracts (the requested
  competition-vs-contract split).
- **New whole sports (items 9–12, MMA/Boxing/Rugby/…):** **DEFERRED** — parked in Wave 3 notes, not worked.
- **FO window (41):** folded into Wave 2 #11. *(38–40 git/branch/tree — out of scope, owner handles.)*

---

## Per-wave acceptance gate (Waves 2–4 — pass BEFORE the wave starts)

`verify_sport.py` proves classification coverage but **cannot** prove settlement equivalence, payout
floor, fee correctness, top-of-book size, duplicate-freeness, or UI parity. So each settlement-sensitive
detector / new ownership additionally requires:

1. **Checked-in redacted JSON fixtures** (real Kalshi responses, dated): `series`, `event`, nested
   markets (`with_nested_markets=true`), `rules_primary`/`rules_secondary`, market `status` set
   (`active`/`paused`/`closed`/`determined`/`finalized`), price fields (fixed-point dollar strings +
   subpenny structure), fee fields, and the **expected detector classification**. Store under
   `tests/fixtures/<sport>/`. *(This is the correctness harness — not the declined measurement harness.)*
2. **Fixture matrix per detector:** clean-MECE→none · underround→exec-only-if-full-coverage ·
   overround-subset→exec-only-if-ME-proof · missing-leg→data-quality · one-sided→blocked · no-size→blocked ·
   inactive/paused→blocked · stale-snapshot→not-tradable · settlement-caveat→review-only ·
   subpenny→display-only.
3. **Payout-floor brute-force test** (mandatory for dutch-book / group-basket / scalar / synthetic
   additions): enumerate every settlement state, compute the buy-bundle payoff, prove the minimum floor +
   worst-case profit, and prove the **label is not overstated**.
4. **Duplicate-opportunity test:** the same market set cannot emit two "actionable" rows with inconsistent
   labels (stage-elim / group-bottom / series-score / field overround can overlap).
5. **Scope-guard isolation test:** new fee/staleness/diagnostic signals must NOT affect `scanner._rank_key`,
   `consistency.bucket_of`, executable status, or the gross-edge calc.
6. **Request-budget estimate (Wave 3/4 only):** new ownership widens fetch; Kalshi rate limits are
   token-bucket and **429s carry no `Retry-After`** (rely on the existing backoff, not a Retry-After
   assumption). Wave 2 is classification-only → **zero** new requests.
7. **Docs gate:** update known-limits / detector-basis / settlement-caveats / new-coverage / review-only
   definitions / fee assumptions for any settlement-sensitive change.
8. **Lifecycle + store compatibility:** a new status must be classified by backlog / "recently-actionable"
   / changed-row logic (test it, or it silently misclassifies). New rows that only add JSON fields need no
   migration; if status-grouping, indexes, or frame-evidence shapes change, version the snapshot/frame.

## Verification (every wave, before handoff)

1. `pytest -q` (new + existing — full suite incl. headless browser).
2. `ruff check .`.
3. `serve.py` boot smoke: `GET /` (SPA), `/dashboard/`, `/healthz`, `/metrics` → 200, `/readyz` →
   ready/degraded/not_ready.
3b. **Dual-UI parity check:** confirm each new sport/scope/family appears in **both** `/` and
   `/dashboard` with matching opportunity counts; `tests/test_feed.py` stays green (1:1 feed↔engine).
   For any new bespoke section/column, verify it renders in both the React component and `viewmodel.opp_row`.
4. `python scripts/verify_sport.py <sport>` for every touched/added sport — confirms registration,
   classification, ladder rungs, and surfaces unmapped families with reasons.
5. **Live settlement-shape probe** (Bash, sandbox-disabled, read-only) before enabling any new ownership:
   confirm MECE / tie / push / dead-heat shape, not just ticker existence — capture the artifact into
   fixtures (gate #1), don't just cite it.
6. Frontend changes: `vitest`.

## Critical files

`dutchbook.py` · `consistency.py` · `synthetic_bundle.py` · `scanner.py` · `sports.py` · `data.py` ·
`config.py` · `api.py` · `viz.py` · `frontend/src/context.tsx` · `scripts/verify_sport.py` ·
`tests/test_{dutchbook,consistency,scanner,sports,<sport>}.py`.

## Risks / guardrails

- **#1 risk — settlement-shape assumptions** turning a feature into a false-money flag → the acceptance
  gate (fixtures + payout-floor test) is mandatory for all Wave 2 settlement-sensitive detectors and all
  Wave 3/4 ownership. Default new settlement-sensitive families to **review-only** until rules prove the floor.
- **Per-competition, never per-sport, for rules.** Adding a competition is NOT "add a ticker to an
  allow-list." Each competition carries its own `rules_primary`/settlement (esp. soccer: ET/penalties,
  two-legged aggregate, away-goals, group tiebreakers, replays) → each gets its own probe + captured
  fixtures, and **no rule is reused across competitions.** One competition at a time, independently gated.
- **Engine purity:** every scalar/dutch/bundle addition stays exact-integer-cents and gross-only; the age
  gate is market-lifecycle, the fee default is display — neither crosses the scope guard
  (no de-vig / conditional-probability / net-of-fees modeling).
- **More coverage can make the scanner worse:** low-liquidity sports/scopes can bury the few actionable
  rows. Mitigate with display diagnostics only (top-of-book size, max gross profit at top of book) — **do
  NOT** add liquidity-weighted ranking or a "$100-fillability" ranking view (scope-guard: engine ranking
  stays unchanged/gross). Deferred to a future product decision, not this plan.
- **Delivery:** branch-only off the confirmed newest base (currently `feat/workspace-ladder-condtable`,
  pushed — verify with `git log` first); separate branch per wave (and per new competition in Wave 3) to
  keep the owner's manual review reviewable; never commit/push/merge `main`.

---

# Appendix — source findings (durable reference; re-probe live data before acting)

*Captured 2026-06-16 from Kalshi's authoritative API + a live `/events` probe. The taxonomy (A/B/C) is
stable; the live snapshot (D) is time-sensitive — re-run the probe before implementing.*

## A. Kalshi sport taxonomy (`/search/tags_by_categories`, `/search/filters_by_sport`)
**19 sports; the app registers 10** (Tennis, NBA, WNBA, Golf, Soccer, MLB, NHL, Motorsport, NFL, Esports).
**Unregistered (9) — DEFERRED (no new whole sports):** MMA, Boxing, Rugby, Cricket, Aussie Rules,
Lacrosse, Chess, Darts, Cities. (Each `filters_by_sport` entry also lists that sport's contract *scopes* —
the authoritative per-sport contract menu used in §B.)

## B. Ignored-but-exploitable contract scopes within the 10 owned sports
- **Scalar over/under** (`Win Totals`, `Total Goals/Maps/Home Runs`, `Total Games`, `1st Half Total`) —
  exists across ~6 sports, **none covered** (→ W2 #1/#2, reuse golf Top-N ladder + a push proof).
- **Golf:** `3-Ball` (3-way MECE), `Matchups` (2-way), round-leader / round-finish ladders (→ W4).
- **Tennis:** `Set Winner` (classified, **no detector**), `Game Spread`, `Total Games`; non-FO tournament
  winners (FO-only today) (→ W2 #3/#4/#11).
- **Soccer (World Cup owned):** `Head to Head` (`KXWCTEAMH2H`), `Correct Score`; `stage_of_elim` overround
  (7-bucket per-team MECE); `group_bottom` subset overround (→ W2 #6/#7/#10, W4).
- **Division winners** — clean `Win Division ⊆ Reach Playoffs` for **MLB/NFL only** (NBA uses a play-in →
  unsafe) (→ W2 #8).
- **NHL/NBA series-result** synthetic bundles (`{4-0..4-3}` replicates series win; review-only) (→ W2 #9).

## C. Round/stage ladder coverage — only 2 of 10 sports complete
| Sport | Rungs covered | Missing |
|---|---|---|
| Soccer (WC) | RO32→RO16→QF→SF→Final→Win (all 6) | complete (modulo the A2 fragmentation bug) |
| WNBA | First Round→Semis→Finals | complete for its format |
| **Tennis** | only SF, Final, Win (3 of 7) | **R128/R64/R32/R16/QF reach rungs** — lower half of bracket unchecked (→ W2 #4) |
| NBA | Conf Finals, Finals only | First Round, Conf Semifinals (recognized-but-unmapped) (→ W2 #5) |
| NHL | Conf Finals, Cup Final only | 1st/2nd Round — match-alignment ~never fires (→ W2 #5) |
| MLB | 3 coarse rungs | Wild Card, Division Series collapsed |
| NFL | 3 coarse rungs | Wild Card, Divisional absent |
| Motorsport | F1/NASCAR/Indy finishing tiers | MotoGP/O'Reilly empty ladder |
| Esports | none | no ladder (v1) |

## D. Live coverage gaps (time-sensitive — 2026-06-16 snapshot, RE-PROBE before acting)
- Live probe found **449 sports series** open (266 recognized / **183 unrecognized**).
- **`KXWCTEAMH2H`** open (~11 events) — unrecognized; clean(ish) 2-way in an owned sport (W2 #10).
- **All club soccer** (EPL, Champions League, La Liga, MLS, Serie A, NWSL, Brasileirão …) → UNKNOWN;
  3-way games the `_detect_n_way` detector already handles (W3 #1) — but **per-competition rules differ**.
- **Off-season (cannot live-validate now):** NBA/NHL/MLB/NFL games+series, French Open tennis (`KXFO*`
  expired). World-Cup soccer is open. → parts of W2/W3 are blocked on those sports reopening.

## E. Full 41-issue → wave index
A1–A8 soundness → **W1**. Trust UX (fees-shown, no age gate) → **W1b**. Scalar scopes / ignored families /
missing rungs / `KXWCTEAMH2H` / non-FO tennis winners → **W2**. New competitions → **W3** (onboard) + **W4**
(their contracts). New strategy families → **W4**. New whole sports (MMA/Boxing/Rugby/…) → **DEFERRED**.
Out of scope (owner): live-capture measurement harness; git/branch/working-tree housekeeping.
