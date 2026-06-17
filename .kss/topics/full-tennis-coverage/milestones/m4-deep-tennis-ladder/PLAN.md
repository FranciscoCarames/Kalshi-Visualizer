---
milestone: m4-deep-tennis-ladder
topic: full-tennis-coverage
created: 2026-06-03
last_updated: 2026-06-03
status: queued
---

> **Relocated 2026-06-03** from `sport-generalization` into `full-tennis-coverage` (roadmap milestone #4).
> Not the active milestone — the topic's milestone 1 is the MECE/dutch-book detector. This plan is a
> containment-family refinement; keep it queued until breadth + dutch-book land. Numbering kept as `m4`
> for continuity.

# Milestone Plan: m4 — Full per-round tennis ladder

## Goal (one sentence)

Make a player's current-round match contract a first-class ladder check at **every** round (R128…Final),
comparing it against **all** strictly-deeper contracts the player has (Reach SF, Reach Final, Win
Tournament) — so the consistency engine "considers the whole tournament," not just SF→Final→Win — without
regressing the existing adjacent-market and co-located match-alignment mechanisms.

## Background (why the cap exists today)

Verified live (FO 2026, 2026-06-03):
- Kalshi publishes **"reach a stage" advance markets only at Semifinal and Final** (`KX*ADVANCE-…SF/…FIN`).
  There is **no** "reach QF / R16 / R32" contract — so deeper *advance* rungs can never have a market.
- Each player has **one** live match contract per round (`KX*MATCH-…`), plus the always-present winner
  market (`KXFO*`).
- The engine compares **adjacent market rungs** + **co-located match≡reach** equivalence. A match whose
  round isn't in `match_stage_to_node` (i.e. R128…R16) is dropped as `UNKNOWN_RELATIONSHIP`
  (`consistency.py:633`) — never compared to anything.

The unused lever is the **match contract**: winning your current match is a prerequisite for the entire
downstream ladder, so `P(win this match) ≥ P(reach SF) ≥ P(reach Final) ≥ P(win title)`. That containment
is checkable at any round using only data that already exists.

## Success Criteria

What must be true to call this shipped:

- [ ] A player's current match at **any** round (R128…Final) produces containment checks against every
      strictly-deeper contract they hold (Reach SF, Reach Final, Win Tournament) — verified on a constructed
      fixture and, where the live draw allows, on live FO data.
- [ ] An early-round match (e.g. R32) priced **below** the winner market surfaces as an
      `EXECUTABLE_VIOLATION` (firm cross + sizes) / `DISPLAY_VIOLATION` (display-only), with the correct
      Buy-YES (match) / Buy-NO (deeper) action plan.
- [ ] These match→deeper rows are flagged **rule-dependent** (`RULE_CHECK_REQUIRED`, never "arbitrage") —
      the walkover/retire nuance means winning a match and advancing aren't identical events.
- [ ] **No new duplicate rows**: the equal-rank node (match's reach-node, e.g. SF match ↔ Reach Final) stays
      handled by the existing co-located equivalence check; the new loop only covers *strictly deeper* nodes.
- [ ] **No regression**: all existing `test_consistency` assertions stay green; existing adjacent-market and
      co-located equivalence rows are byte-for-byte unchanged; NBA/WNBA produce no new rows (their match maps
      are unchanged this milestone).
- [ ] `UNKNOWN_RELATIONSHIP` still fires for genuinely unmappable match rounds (unparsed / qualifying), as a
      safety net.
- [ ] `pytest -q` green (with new tests), `ruff check .` clean, headless boot returns 200.

## Out of Scope

- **Extending NBA/WNBA early-round series** (First Round / Conf Semis playoff series → deeper). The engine
  change will be sport-agnostic, but only **tennis's** `match_stage_to_node` is extended this milestone;
  basketball depth is a clean follow-up.
- Any dependency on Kalshi adding early-round advance markets (they don't exist; we don't wait for them).
- `layer_spreads` / `expected_nodes` redesign — those stay on the market-bearing rungs (see Open Q #1); we
  don't want permanent `MISSING_LAYER` noise for rungs that can never carry a market.
- Conditional-probability / de-vig modelling, set/score markets, doubles — unchanged scope guard.

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | Decide representation for sub-SF reach rungs (Open Q #1) — node_order vs rank-driven | ○ |
| 2 | `sports.py`: extend tennis `match_stage_to_node` to all rounds (R128→Reach R64 … Final→Win); add node→rank (or market-bearing-node) data per the Q#1 decision | ○ |
| 3 | `consistency.py`: decouple rule-flag from bidirectional check in `_classify` (add `rule_dependent` param; equivalence behaviour unchanged) | ○ |
| 4 | `consistency.py`: new match→all-strictly-deeper-market-node containment loop in `build_checks` (forward-only, rule-dependent, no double-count with co-located equivalence) | ○ |
| 5 | Keep `UNKNOWN_RELATIONSHIP` fallback for still-unmappable rounds | ○ |
| 6 | Tests: early-round match vs winner (exec violation / clean / display); rule flag present; no duplicate vs equivalence; NBA/WNBA unaffected; existing rows unchanged | ○ |
| 7 | Verify: `pytest -q`, `ruff`, headless 200, live FO smoke (rows appear, sane) | ○ |
| 8 | Glossary/labels: chain label for new rows ("{round} win ⊇ {deeper}"), confirm rule-dependent wording | ○ |
| 9 | PR off `main` (not stacked); CLAUDE.md "hard rules" note updated; wrap-up | ○ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

(resolve as you go; promote stable answers to TOPIC.md "Key Decisions" at milestone close)

1. **How to represent the sub-SF reach rungs?** Two designs:
   - **(A) Extend `node_order`** to all 7 rungs. Simplest conceptually, but every new rung is permanently
     market-less → pollutes `adjacent_pairs` (all new pairs = `MISSING_LAYER`), `layer_spreads`, and
     `expected_nodes` ("expected" a market that can't exist) with noise.
   - **(B, recommended) Keep `node_order`/`adjacent_pairs` = market-bearing rungs (SF/Final/Win)**; extend
     `match_stage_to_node` so every round's match still gets a *node name* for bucketing; drive the new
     match→deeper containment off a **node→rank** (or `stage_rank`) comparison rather than node_order
     membership. No empty rungs, no spread/expected-node noise; the new code path owns the depth logic.
     Likely needs a small `LadderSpec` addition (e.g. `node_rank: dict[str,int]` or `market_nodes` set).
   - *Leaning B.* Confirm at task #1.

2. **Is `match ⊇ deeper` truly rule-dependent?** Yes — a walkover/retire lets a player *advance* without
   "winning" a played match, so the containment can be broken by settlement nuance, not arbitrage. Same
   caveat as today's equivalence rows → carries `RULE_CHECK_REQUIRED`, never called arbitrage. (Confirms the
   `rule_dependent` decoupling in task #3 is the right move.)

3. **`_classify` change shape.** Add `rule_dependent: bool=False` *separately* from `equivalence`:
   `equivalence` keeps enabling the reverse-direction (parent-bid > child-ask) cross; `rule_dependent`
   independently attaches `_rule_flag`. Match→deeper is `equivalence=False, rule_dependent=True`
   (forward-only — deeper>broader is the only inconsistency; broader>deeper is expected/clean). Verify the
   two existing callers (`False,—` adjacent; `True,—` co-located) are unchanged when `rule_dependent`
   defaults to mirror old behaviour (equivalence implied rule-check before — preserve that).

4. **Generic vs tennis-only.** Engine loop is sport-agnostic (reads ladder + rank off `cfg`). Because only
   tennis's `match_stage_to_node` gains early rounds, NBA/WNBA naturally produce no new rows. Confirm via a
   regression test on both. Basketball depth = explicit follow-up.

5. **Action direction for new rows.** Buy YES the match (broader, prerequisite) / Buy NO the deeper leg —
   the existing forward-default in `_classify` already does this when there's no firm cross. Confirm the
   firm-cross path picks the right legs for a match-vs-winner cross.

## Notes

- Live probe (2026-06-03) that grounds this: `KX*ADVANCE` → only `…FOSF` / `…FOFIN`; `KX*MATCH` → one
  current-round event per player; `KXFOMEN/WOMEN` → one winner market. (Captured in the session, not a file.)
- Containment semantics recap (broad→deep, child ≤ parent): the match (broader) must not price *below* any
  deeper leg. A deeper leg pricing **above** the match = the inconsistency. The match's *equal*-rank node
  (reach-next) is the existing equivalence; everything strictly deeper is the new containment.
- Deep-dive writeups, if any, go to sibling `note-YYYYMMDD-*.md`, not here.

---
*Planned via plan-milestone on 2026-06-03*
