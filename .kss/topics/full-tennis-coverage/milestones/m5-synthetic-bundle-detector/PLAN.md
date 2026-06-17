---
milestone: m5-synthetic-bundle-detector
topic: full-tennis-coverage
created: 2026-06-04
last_updated: 2026-06-04
status: executing
---

# Milestone Plan: m5 — Synthetic exact-score / state-bundle discrepancy detector

> Full approved plan (with anchors + design detail): `~/.claude/plans/binary-jumping-fern.md`.
> This implements roadmap #5 (cross-family: exact-score↔reach-round) + the S6 seed (n-outcome).

## Goal (one sentence)

Detect gross pricing discrepancies where a **format-verified**, MECE-and-exhaustive bundle of
exact-score/state contracts replicates a player "wins/advances" outcome and is mispriced against a
rule-compatible broader hedge — both directions, completeness- and rule-gated, labelled conservatively as
gross/top-of-book, **never** actionable arbitrage.

## Success Criteria

- [ ] New pure `synthetic_bundle.py` emits `EXECUTABLE_SYNTHETIC_BUNDLE` per (player, event, direction),
      exact integer cents. Forward: `Σ YES_ask(states) + NO_ask(hedge) < 100¢`; reverse:
      `Σ NO_ask(states) + YES_ask(hedge) < N×100¢`. No success criterion implies a guaranteed payout.
- [ ] **Format proven, not assumed** — expected state set from a verified per-event match-format signal
      (spike-confirmed; NOT tour, since ATP ≠ always bo5). Unproven format → no emit.
- [ ] Emit gates ALL required: (1) MECE; (2) exhaustive (found == verified-expected); (3) hedge present,
      no hard rules-conflict; (4) firm executable ask per leg. Fail (1)–(3) → silent skip.
- [ ] Price/size: missing firm price → no emit (that direction); firm price but zero/missing size or
      inactive leg → emit **blocked/review** (visible, not dropped).
- [ ] Two-tier rules: hard mismatch → no emit; inherent settlement caveat → emit review/blocked,
      `rule_flag` set, `tradable_now="Review rules"`. Every emitted row review/blocked, never Actionable.
- [ ] State sets config-driven by sport/family/format (no `if sport==`). Hedge = spike-proven type first
      (match-winner OR advance); other hedge is a follow-up PR. Exact-score never == match-winner.
- [ ] Conservative labels ("gross pricing discrepancy", gross/top-of-book). Round parser fixed (Task 1.5).
- [ ] Tests: bo5+bo3 both directions; exact-score≠match-winner; missing/duplicate/non-exhaustive/
      unproven-format/hard-mismatch → no fire; missing-size → blocked. `pytest -q` green, ruff clean,
      headless 200.

## Out of Scope

- Pure same-event score field (no hedge) — sibling seed. N-outcome winner FIELDS (≥3) — core accepts later.
- Net-of-fees / full-depth sizing — labelled, not modeled. The 5-PR detection-correctness hardening —
  AFTER this milestone (spec: `../../../real-time-opportunity-engine/note-20260604-detection-correctness-audit.md`).

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 0 | kss bookkeeping (this) | ✓ |
| 1 | LIVE-DATA SPIKE — **✓ DONE** (`.kss/spikes/exact-score-bundle-feasibility/`): scoreline=`custom_strike["Set Score"]`; format=Grand-Slam+gender (bo5/bo3); hedge=match-winner first (UUID join), advance=3b; retirement caveat CONFIRMED required | ✓ |
| 1.5 | Round-parser bugfix (ALL sports) — **PR #42 MERGED** (f258922) | ✓ |
| 2 | Scoreline parser + format resolver + `SportConfig` `state_bundles` — **PR #43 MERGED** (ec5bcfb) | ✓ |
| 3a | `synthetic_bundle.py` detector — match-winner hedge, both directions, gates, rule tiers — **PR #44 MERGED** (c55c09c) | ✓ |
| 3b | Second hedge type (advance hedge) — **OPTIONAL / not started.** Match-winner hedge (3a) covers all live cases (every match has a `KX*MATCH` market); the advance hedge adds the distinct scores-vs-reach-round mispricing but needs the round→node cross-event join. Decide: build or seed. | ○ |
| 4 | N-leg plumbing (scanner `legs`/`n_legs` + API `Opportunity` + STATUS_GROUP/bucket_of) — **PR #45 open** (262 pass, ruff clean, live scanner 116 rows/0 err) | ✓ |
| 5 | UI surfaces (NiceGUI `explanation_lines`/links iterate legs; Streamlit dedicated section; glossary "Synthetic bundle" term) — **PR #46 open** (263 pass, ruff clean, Streamlit boot 200) | ✓ |
| 6 | Docs (CLAUDE.md synthetic section, dutchbook docstring, regenerate GLOSSARY.md) — **PR #47 open** (263 pass, ruff clean) | ✓ |

Legend: ○ pending · ◆ in-progress · ✓ done. Shippable core = 1.5 + 2 + 3a + 4. One PR per ✦ task off `main`.

## Open Questions

- Does Kalshi void exact-score on retirement? (spike) — sets whether the caveat is needed / refund semantics.
- Is the advance hedge join (exact_score↔advance shared UUID + stage map) reliable, or match-winner-first?
- `mutually_exclusive` real coverage (also informs the parked hardening PR C).

## Notes

- **Task 3a design note (verified in Task 2 smoke):** group exact-score rows by **`player_key` (UUID)**,
  NOT the display `player` field — the latter carries the scoreline subtitle ("Mensik wins 3-0"), which
  over-splits. Grouped by UUID, each FO player's found set `{3-0,3-1,3-2}` == expected bo5 (completeness OK).
- **Scoreline source (verified live):** `custom_strike["Set Score"]` (stamped as `raw_custom_strike`).
  Hedge: match-winner (`KXATPMATCH`) shares event suffix + UUID (trivial join, 3a); advance is 3b.

- Task 1.5 confirmed a real cross-sport bug (Tennis/NBA/WNBA all ordered a generic Final/Finals before a
  more-specific hyphenated round). Fixed + tested in PR #42.
- Deep design/anchors live in the approved plan file; session writeups → sibling `note-*.md`.

---
*Planned via plan-milestone (manual) on 2026-06-04*
