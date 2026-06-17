---
slug: unified-plan-build
created: 2026-06-04
last_updated: 2026-06-04
status: active
---

# Topic: unified-plan-build

## What This Is

A coordinating topic to implement `Concurrent Plans/UNIFIED-PLAN.md`, which merges the four concurrent
plans — **golf** (placement-ladder sport), **soccer World Cup** (n-outcome dutch book), **synthetic-bundle
correctness hardening**, and **NiceGUI hosted parity** — into one PR-sequenced roadmap (~28 PRs across
Phases A–F). It supersedes the four standalone plans by sequencing and de-conflicting them, and it owns the
cross-cutting "collision core" (shared foundation) that no single existing topic owns.

This topic coordinates work that crosses `sport-generalization` (golf/soccer), `full-tennis-coverage`
(synthetic m5 follow-on), and `real-time-opportunity-engine` (NiceGUI parity). Those topics hold the
original per-plan context; this one owns the merged execution.

## Goal

Ship the merged roadmap to `main` as small, single-purpose PRs (off `origin/main`, never stacked):
correctness hardening (transitive containment, conservative dutch-book labeling, per-sport categories, the
leg/URL fix), two new sports (golf, soccer WC), the n-outcome dutch-book architecture, the hardened
synthetic exact-score bundle detector, and NiceGUI workflow parity — with a wide test battery including the
explicit false-positive / false-negative **actionability** tests the owner asked for.

## Success Bar

- Phases A–E PRs merged to `main`; Phase F (known-limits/follow-ons) documented or owner-gated.
- Golf + soccer registered as sports via `exact_series`; n-outcome dutch book live; synthetic bundle
  detector **hardened** (safety gates from the 55-issue register applied to the existing `synthetic_bundle.py`).
- NiceGUI dashboard at hosted *workflow* parity with Streamlit (store-backed, non-blocking `/scan`).
- Full suite green, including the actionability false-positive/false-negative tests for every detector.
- No regression to tennis/NBA/WNBA detection or to the legacy 2-leg dutch-book IDs.

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-04 | Baseline = `origin/main` (#47); PR 0 is a **sync, not a merge** | Remote already has s1–s5 + m5; local refs were 15 behind / checkout at #42 |
| 2026-06-04 | Implement in worktree `C:\Users\Batata\Desktop\kalshi-impl` | Keeps the dirty planning tree (UNIFIED-PLAN.md + uncommitted LAN work) untouched; satisfies the worktree rule |
| 2026-06-04 | Synthetic Phase D = **harden existing `synthetic_bundle.py`**, not greenfield | The m5 detector already exists on #47; the plan is the 55-issue hardening pass over it |
| 2026-06-04 | Collision-core foundation (exact_series, category dispatch, leg/URL fix) done **once** | Golf/soccer/nicegui all re-derive it; one PR each avoids merge conflicts |
| 2026-06-04 | F10 (soccer tournament-scope missing-layer suppression) = **owner decision** (PR 11, default off) | Sound but noise-control only; diverges from soccer source plan — owner picks |

## Out of Scope

- Trading, auth, order placement (read-only engine).
- **Net-of-fees modeling** for actionability (gross-only; fee *metadata* is captured, not modeled) —
  known-limit unless the owner opts in (PR 28).
- WebSocket / streaming; conditional-probability / de-vig models.
- F10 tournament-scope suppression unless the owner elects PR 11.
- Phase F follow-on detectors (n-outcome FIELDs, advancement hedge) until the match-winner bundle is proven.

---
*Created via new-topic on 2026-06-04*
