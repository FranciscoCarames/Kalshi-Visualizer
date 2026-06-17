---
milestone: m5-synthetic-bundle-detector
topic: full-tennis-coverage
shipped: 2026-06-04
status: shipped
---

# Milestone Summary: m5 — Synthetic exact-score / state-bundle detector

## What Shipped

A new N-leg check family (`synthetic_bundle.py`): a player's MECE exact-set-score contracts
({3-0,3-1,3-2} best-of-5 / {2-0,2-1} best-of-3) *replicate* "they win the match", priced against their
**match-winner** hedge to surface a **gross pricing discrepancy** in two directions (forward `< 100¢`,
reverse `< N×100¢`, exact cents). It is explicitly **not riskless** — an exact score ≠ the match-winner,
and on a retirement the score legs settle to Fair Market Price while the hedge settles cleanly (verified
live) — so every finding is `SETTLEMENT_CHECK_REQUIRED` / `tradable_now="Review rules"` and routed
**review/blocked, never Actionable**. Built end-to-end: detection → scanner → SQLite store → FastAPI API
→ both dashboards (NiceGUI legs iteration + a dedicated Streamlit section) → docs. The advance-hedge
variant (Task 3b) was deferred to a seed.

## Success Criteria

- [x] Pure `synthetic_bundle.py`, `EXECUTABLE_SYNTHETIC_BUNDLE`, exact cents, both directions — passed cleanly (PR #44).
- [x] Format **proven** from a verified signal (Grand-Slam + gender, not ATP/WTA alone); unprovable → no emit — passed (PR #43).
- [x] All emit gates (MECE, exhaustive by `player_key` UUID, hedge present + same-round, firm ask) — passed (PR #44).
- [x] Price/size policy (missing firm price → no emit; priced-but-no-size/inactive → blocked/review) — passed.
- [x] Two-tier rules; every emitted row review/blocked, **never Actionable** — passed.
- [partial] Hedge = spike-proven type first (✓ match-winner shipped); **the other hedge (advance) is a follow-up** — deferred to seed **S8** per the criterion's own wording.
- [x] Conservative labels ("gross pricing discrepancy", never "true arbitrage"); round parser fixed (PR #42) — passed.
- [x] Tests (bo5+bo3 both directions, completeness/format/round-mismatch/no-hedge/size/NaN), `pytest -q` green (263), ruff clean, headless 200, scanner→store→API legs round-trip verified — passed.

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Synthetic bundle is a SEPARATE N-leg module (`synthetic_bundle.py`), not an extension of `dutchbook.py` | N-leg, multi-family, always rule-caveated — bolting onto the 2-leg/no-caveat dutch-book module would erode its invariants (mirrors the dutchbook-vs-consistency split) | New module + status; detection isolated, routing = one `STATUS_GROUP`/`bucket_of` touch |
| Cross-family score bundles are ALWAYS settlement-caveated, never "true arbitrage" | The retirement hole (score legs → Fair Market Price while the hedge settles) is real and verified live; an exact score is not the match-winner | `rule_flag=SETTLEMENT_CHECK_REQUIRED` + `tradable_now="Review rules"` → review/blocked, never Actionable; "gross/top-of-book" labels |
| N-leg findings carry an additive `legs` list; `action_1/2_*` backfilled from the first two legs | Lets the N>2 plan flow through scanner/store/API/UI without breaking any 2-leg consumer | `legs`/`n_legs` in `UNIFIED_COLUMNS` + api.py `Opportunity` (declared so `extra="ignore"` keeps them) |
| Format proven from an INDEPENDENT signal (division + tournament), never the discovered markets | Deriving the expected set from the found markets makes the completeness check circular; ATP ≠ always bo5 | `score_format_fn`: men's Grand Slam = bo5, WTA + non-Slam ATP = bo3; unprovable → no emit |

(The settlement-caveat principle is broadly applicable → promoted to TOPIC.md Key Decisions.)

## Deferred

Captured as seeds:

- **S8** — Synthetic-bundle **advance hedge** (Task 3b): hedge the score bundle against the player's
  reach-next-round `KX*ADVANCE` market (a distinct order book). Trigger: thin/illiquid match-winner books,
  a need for the reach-round cross-check (roadmap #5), or concrete demand. Build via the gated middle-path
  (emit only when the round→node cross-event join is unambiguous, else skip — never a false hedge).

## Files Touched

- `synthetic_bundle.py` — NEW detector (`parse_scoreline`, `expected_states`, `find_synthetic_bundles`).
- `sports.py` — `SportConfig.state_bundles` + `score_format_fn`; tennis bo5/bo3 config; round-parser fix (all sports).
- `scanner.py` — `find_synthetic_bundles` wired in + `_to_unified_synthetic`; `legs`/`n_legs` in `UNIFIED_COLUMNS`.
- `consistency.py` — `STATUS_GROUP` + `bucket_of` entries. `api.py` — `legs`/`n_legs` on `Opportunity`.
- `glossary.py` — `BLOCKERS["synthetic_settlement"]` + "Synthetic bundle" term + COLUMN_HELP.
- `webui/dashboard.py` — `explanation_lines`/leg-links iterate `legs`. `app.py` — dedicated Streamlit section.
- `CLAUDE.md` / `dutchbook.py` docstring / `docs/GLOSSARY.md` — docs. Tests across `test_*`.

## Sessions

1 session logged in topic LOG.md (2026-06-04). Shipped via PRs **#42–#47** (all merged to `main`).

---
*Closed via complete-milestone on 2026-06-04*
