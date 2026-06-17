---
session: 2026-06-04
milestone: —
topic: sport-generalization
slug: ufc-plan
---

# UFC (fight-centric MMA) new-sport plan — 12 review rounds

## Context

Designed a full plan to add UFC to the Kalshi dashboard. UFC is the **most distinctive sport planned so
far** — it is NOT a config drop-in, and it forced a core engine correction. Hardened over **12 adversarial
review rounds** with the owner. Full plan saved to `New Sports/UFC-plan.md` (working copy
`~/.claude/plans/frolicking-whistling-scott.md`). Analysis/design only — no code.

## Details

**Two value layers (unlike any shipped sport):**
1. **Dutch-book** — `KXUFCFIGHT` (2 markets) and `KXUFCMOV` (n-way method-of-victory).
2. **Cross-family containment** — `KXUFCMOV`/`KXUFCVICROUND` outcome ⊆ the fighter's `KXUFCFIGHT` win;
   `KXUFCROUNDS` is a cumulative "ends before round N" ladder (`ME=false`, NOT a dutch-book set).

**Engine correction:** the detector's "2 markets ⇒ MECE by construction" (`dutchbook._detect_pair`) is
**false for UFC** (draw/no-contest). Exhaustiveness becomes an explicit **per-family/event proof**;
`mutually_exclusive` only proves "at most one".

**Two HARD GATES block any user-facing signal:**
- **Gate A — identity join.** FIGHT keys fighters by `custom_strike.ufc_competitor` (UUID); MOV/VICROUND
  carry the fighter only as a **name** in `custom_strike.Participant`. Architecture catch (round 7): join
  must be a **post-flatten sport-level pass** `data.resolve_cross_series_identity(rows, cfg)` — because
  `build_contracts` is called **per-series** (fetch.py:40) and can't see FIGHT while building MOV. Builds
  `(fight_key, normalized_name)→ufc_competitor_uuid` from FIGHT rows, back-fills MOV/VICROUND. Join-fail →
  `UNKNOWN_RELATIONSHIP`, **never** low-confidence executable.
- **Gate B — settlement basis.** FIGHT is ME-but-**not exhaustive**; overround (Buy-NO-both) is draw-safe,
  underround is not. New **`CONDITIONAL_DUTCH_BOOK`** status (`is_locked=False`), per-family/event
  `settlement_basis` enum; **emits only when the basis proves a non-losing floor** (`unknown` AND
  known-but-unfavorable both suppress). "locked/true-arbitrage/guaranteed 100¢" wording (app.py:738/765,
  glossary.py:118) must branch on `is_locked`.

**Key design decisions:**
- `match_family="match"` (reuses `"match"` special-casing: occurrence-time data.py:555, stage app.py:280,
  source consistency.py:112) — NOT a fresh `"fight"` family.
- Own `KXUFCFIGHT/MOV/VICROUND/ROUNDS` via **`exact_series`** (prefix over-collects title/White-House/
  occurrence/retirement props). `KXUFCDISTANCE`/`KXUFCOCCUR` excluded.
- `default_families`/`dutchbook_families` hold family **KEYS** but `series_for_families` (data.py:635)
  filters on **LABELS** → convert keys→labels at the fetch boundary (Option A; round 10).
- `fight_key` from a config hook (`fight_key_fn`): strip family prefix, remainder after first hyphen;
  malformed → unique per-`event_ticker`, no joins, diagnostic.
- Cross-family containment keyed by `(fighter_key, fight_key)` (NOT `(player_key, tournament)` — a card has
  many bouts); non-participant Draw/No-Contest excluded from FIGHT containment.

**Phasing:** 0 discovery (throttled `kalshi_client`, fixtures, settlement text) → 1a foundation (no signal:
schema + join + `default_families={"match"}` + per-sport category dispatch) → 1b FIGHT overround dutch book
→ 2 cross-family containment → 3a n-leg schema migration + MOV n-way (widen families to `{"match","method"}`)
→ 3b sum-completeness `PARTITION_DEVIATION` (scoped, NOT engineering-ready). Committed slice = 0–3a.

## Process notes

- **Same hallucinated-read failure as the NCAAB session:** early `Read` of `sports.py`/`dutchbook.py`
  returned a **fabricated future version** (738-line `sports.py` with golf/soccer/`exact_series`/`tie_fn`;
  476-line `dutchbook.py` with `prove_mece`/`_detect_n_way`). Caught via `grep`/`wc`/`git` (real:
  532-line `sports.py`, only tennis/NBA/WNBA, no `exact_series`; 275-line 2-way-only `dutchbook.py`). The
  correction reset the plan onto the real (earlier) codebase. **Lesson: verify file contents with
  grep/wc/git on this checkout before trusting a Read.**
- One scoping question asked up front (AskUserQuestion): owner chose **"+ method/rounds"** scope and
  **conservative/draw-safe** handling — which drove the n-way + containment + CONDITIONAL_DUTCH_BOOK design.

## Outcome

Full plan at `New Sports/UFC-plan.md`. Memory updated ([[multi-sport-generalization]] + MEMORY.md index).
Scope = **UFC only, NOT broader MMA** (non-`KXUFC` series, other promotions, props) — flagged for owner
sign-off. Shares the `settlement_caveat`/`label_fn`/per-sport-category/`game_mece_by_shape` foundation with
MLB/NFL/NHL/NCAAB; ⚠ written against `feat/round-parser-fix` (tennis/NBA/WNBA only) — rebase onto
current `origin/main` (golf/soccer + settlement_caveat already merged) and reuse that infra before building.

## Followups

- Phase 0 live discovery is the gating prerequisite (confirm `ufc_competitor` identity, FIGHT 2-market
  shape, no-contest settlement → `settlement_basis`, MOV open-event availability, `fight_key` suffix).
- Phase 3b (`PARTITION_DEVIATION`) needs its own status/sizing/`_diag` spec before build.
