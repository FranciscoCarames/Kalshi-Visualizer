---
milestone: m1-dutch-book-detector
topic: full-tennis-coverage
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: m1 — Dutch-book / MECE detector

> Milestone numbers in this topic map to the **roadmap position** in `TOPIC.md` (1=dutch-book,
> 2=discovery, 3=taxonomy, 4=deep-ladder, 5=cross-family, 6=temporal). So `m1` and the queued `m4`
> coexisting (with m2/m3/m5/m6 to come) is intentional, not a gap.

## Goal (one sentence)

Add a new check — independent of the containment ladder — that flags a **dutch book** on any
mutually-exclusive-and-exhaustive set of binary markets: if you can cover *every* outcome for less than the
guaranteed $1 payout, that's a locked executable edge. Committed scope: the **2-outcome case (every
head-to-head match)**, which is provably exhaustive and reuses the existing Buy-YES/Buy-NO action plumbing.

## Why this first

One generic check covers the **largest share of tennis contracts** — every live match, across every
tournament — and is the single biggest untapped edge (the two players' books are priced independently, so
they need not sum to 100¢). It's sport-agnostic (NBA/WNBA head-to-head series too) and unblocks the parked
soccer/draws work later.

## The math (exact integer cents, both directions)

For a match with two independent player markets A and B (exactly one wins — no draw):

- **Underround → Buy YES both.** Cost `yes_ask_A + yes_ask_B`; payout is exactly 100¢ (one side wins).
  Edge when `yes_ask_A + yes_ask_B < 100 − tol`. Guaranteed profit/unit = `100 − (yes_ask_A + yes_ask_B)`.
- **Overround → Buy NO both.** Cost `no_ask_A + no_ask_B`; exactly one NO pays 100¢. Edge when
  `no_ask_A + no_ask_B < 100 − tol`. (Identically: `yes_bid_A + yes_bid_B > 100 + tol`, since
  `no_ask = 100 − yes_bid`.) Guaranteed profit/unit = `100 − (no_ask_A + no_ask_B)`.

Both are real and distinct. Sizes: a **Buy-YES** leg's tradable size is `yes_ask_size`; a **Buy-NO** leg's
is `yes_bid_size` (Kalshi has no NO sizes — buying NO hits resting YES bids). Executable size = min over the
two legs; executable only when both legs are firm, `active`, and sized > 0.

## Success Criteria

- [ ] New pure module (no Streamlit/pandas import in the logic) — e.g. `dutchbook.py` — that groups markets
      by their mutually-exclusive event and returns dutch-book findings, in exact integer cents.
- [ ] For a 2-outcome match: flags **both** directions; `EXECUTABLE` only with firm quotes + positive sizes;
      degrades to a blocked/near status when size or a firm quote is missing (mirrors the containment
      precedence rules); reports correct Buy-YES/Buy-NO legs, per-unit guaranteed profit, and min tradable size.
- [ ] **Exhaustiveness is explicit and safe**: the YES-underround arb is only emitted when the outcome set is
      provably exhaustive (true by construction for a 2-market match). Non-exhaustive / single-sided /
      >2-outcome sets do NOT produce a 2-leg YES-underround claim. (Documented; see Open Q #2.)
- [ ] **No false positives**: a market with an empty/one-sided/crossed book, an event with only one market,
      or a non-MECE family never yields an arb. Covered by tests.
- [ ] Dashboard integration: dutch-book opportunities surface in **Actionable now / Blocked** alongside
      containment ones, with Buy-YES/Buy-NO action text + per-unit profit (reusing `scenario_payoffs`-style
      output), clearly **labelled as a dutch book**, not a containment cross.
- [ ] Sport-agnostic: validated on tennis matches **and** NBA/WNBA head-to-head series; no regressions to
      existing containment checks (all current tests green).
- [ ] New unit tests (underround hit, overround hit, both-clean, size-missing, one-sided book, crossed book,
      single-market event, exhaustiveness guard); `pytest -q` green, `ruff` clean, headless boot 200.

## Out of Scope

- **n-outcome winner-field dutch book** (≥3 outcomes, e.g. `KXFOMEN` draw). Deferred to a follow-up milestone:
  it needs (a) provable field-completeness before the YES-underround is valid, and (b) a multi-leg action
  representation the current 2-leg `action_1/action_2` schema can't hold. The detector will be written so the
  field case slots in later, but it is **not** delivered here. (See Open Q #2/#3.)
- Discovery breadth (milestone #2) — this works on whatever matches are already fetched; it does not change
  what's fetched.
- Trading/fees/auth; conditional-probability modelling. Standing scope guard.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | ~~Decide module placement + finding schema~~ — **RESOLVED, see Decision D1** | ✓ |
| 2 | Implement 2-outcome detector (`dutchbook.py`): group by event, both directions in exact cents, legs/sizes/profit, executable-vs-blocked via `tradable_now` | ✓ |
| 3 | Exhaustiveness/false-positive guards: exactly-2-distinct-participant markets; reject single/>2-outcome, non-match, unknown-series, No-quote/Crossed legs | ✓ |
| 4 | ✅ Dashboard surfacing (**PR #29**): `bucket_of` branch routes `EXECUTABLE_DUTCH_BOOK` actionable/blocked; dedicated "Dutch-book arbitrage" section (same-side buys → own table); same tournament/event/participant membership; thresholds spare it | ✓ |
| 5 | ✅ Sport-agnostic validation (**PR #30**): NBA/WNBA series tests fire; per-game/props ignored; live check confirmed exclusion half (no series events open to test firing live) | ✓ |
| 6 | Tests (16 in `tests/test_dutchbook.py`) + ruff + live smoke + headless 200 — all ✓ | ✓ |
| 7 | ✅ Glossary (**PR #30**): "Dutch book" term (short+long), wired to the "Locked edge (¢)" column via COLUMN_HELP, `docs/GLOSSARY.md` regenerated (11 terms) | ✓ |
| 8 | PRs #28/#29/#30 (#28/#29 merged; #30 open). **Remaining:** CLAUDE.md note (new check type + where it lives + MECE assumption) + `complete-milestone` | ◆ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

1. ~~**Module placement + schema reuse.**~~ **RESOLVED → Decision D1 (below).**

2. **Is "dutch book" the right word, and the exhaustiveness contract.** For a 2-outcome match it IS a true
   arbitrage (same event, exhaustive, both legs firm, no rule-mismatch) — so unlike containment we MAY call it
   locked/guaranteed. Confirm the exhaustiveness predicate: rely on exactly-2-markets-in-event + `tennis` no-draw
   (and the market `mutually_exclusive`/exhaustive metadata if present). Anything else → not a YES-underround arb.

3. **Winner-field follow-up shape.** Sketch (not build) how the n-outcome case proves completeness (Σ of all
   listed YES mids ≈ 100? explicit "Field/Other" market? event metadata?) and how a multi-leg position renders.
   Capture so milestone-#? can pick it up. Possibly its own milestone.

4. **Tolerance + near-edge.** Reuse `DISPLAY_TOL_C`/`NEAR_EDGE_MIN_C` or add a `DUTCH_TOL_C`? A near-dutch-book
   (sum within a few cents of 100) is a useful watchlist signal mirroring the existing near-edge bucket.

## Decisions

### D1 — Module placement, status, and routing (resolves Open Q #1, 2026-06-03)

Agreed with an external (ChatGPT) suggestion, with three refinements for clean composition:

- **New sibling pure module `dutchbook.py`** (no Streamlit/pandas in the logic), NOT an extension of
  `consistency.py`. Dutch-book is a separate generic check family; `consistency.py` stays containment-only.
- **One new status: `EXECUTABLE_DUTCH_BOOK`** — distinct from `EXECUTABLE_VIOLATION` so the ladder's
  "violation" semantics aren't muddied. *Refinement 1:* it **carries `tradable_now` + `blockers`** exactly
  like the containment row, so a single status covers both actionable (firm + sized + both legs `active`)
  and blocked (cross exists but size missing / a leg inactive) — no separate blocked status needed.
- **Routing via one new branch in `bucket_of`** (consistency.py). *Refinement 2:* `bucket_of` is already the
  shared dashboard **router** (reads fields only, no detection), so adding an `EXECUTABLE_DUTCH_BOOK` case
  there routes it to the same high-priority **Actionable / Blocked** sections as containment edges while
  keeping all *detection* in `dutchbook.py`. This honors "keep consistency.py focused" — routing ≠ detection.
- `dutchbook.py` emits rows in the **existing two-leg schema** (leg A=`action_1` Buy-YES/NO, leg B=`action_2`)
  so `scenario_payoffs`-style profit output and the action-text rendering are reused unchanged.
- *Refinement 3:* **≤ 1 finding per event.** Since bid ≤ ask, the underround (asks sum < 100) and overround
  (bids sum > 100) tests are mutually exclusive — emit whichever fires; never both.

Scope confirmed narrow per the suggestion: exactly two MECE outcomes; tennis match-winner events to start;
both directions (YES underround / NO overround); NO n-outcome winner fields; NO discovery/deep-ladder changes.

## Build progress

- **2026-06-03 — tasks #2/#3/#6 done, PR #28 opened.** Added `dutchbook.py` (pure) + `tests/test_dutchbook.py`
  (13 tests). Branch re-based onto the WNBA-containing branch (owner wanted main+WNBA+task2 in one PR), so
  `feat/wnba-and-dutch-book → main` (#28) is additive: WNBA (`sports.py`/`test_sports.py`) + dutch-book
  (`dutchbook.py`/`test_dutchbook.py`). Full suite **141 green** (128 + 13), ruff clean, `import app` OK.
  app.py untouched (integration = task #4). Awaiting owner manual merge.
- **2026-06-03 — task #4 done, PR #29** (`feat/dutch-book-dashboard → main`, off the #28-merged main).
  `bucket_of` branch + `STATUS_GROUP` (consistency.py); `dutchbook.py` findings gained `player_key_a/b` +
  `resolve_time`; `app.py` renders a dedicated "Dutch-book arbitrage" section (same-side buys → own table,
  refining D1's "same section"). Membership-filtered like the rest; thresholds spare it. Suite **144 green**,
  ruff clean, **headless 200**, non-empty render path validated on synthetic findings. Awaiting owner merge.
- **2026-06-03 — robustness pass, PR #31** (`feat/dutch-book-hardening-tests`). Before extending to S5,
  audited coverage and found the **production DataFrame→records path untested** (missing prices/sizes arrive
  as float NaN, not None) plus the 100¢ boundary and one-sided books. Added 6 tests; **no code bug** — the
  detector already handled them, now proven. Detector tests 19→25, suite **153 green**. Verdict: robust.
- **Live smoke (FO 2026):** all 5 current ATP/WTA matches priced with YES-ask sum = **101¢** (NO-ask
  ~101–102¢) — i.e. the ~1¢ vig over 100, so 0 dutch books (correct, not a field bug; detector read real
  prices 22/79/63/38/… fine). They sit 1¢ from firing → strong motivation for the near-edge watchlist
  (Open Q #4) in a later pass.

## Notes

- Grounding (live 2026-06-03): match events carry exactly 2 player markets with independent books; winner
  events (`KXFOMEN-26`) carry the full(ish) draw. `no_ask = 100 − yes_bid` holds within a single market, so
  the overround test has the two equivalent forms above — implement off the real `no_ask_c` with the
  `100 − yes_bid_c` fallback (same pattern as `consistency._buy_no_c`).
- Reuse, don't reinvent: `data.to_cents` for exact math; the `_leg`/`_buy_no_c`/size conventions from
  `consistency.py`; `scenario_payoffs` shape for the per-unit profit table.
- Deep-dive writeups → sibling `note-YYYYMMDD-*.md`.

---
*Planned via plan-milestone on 2026-06-03*
