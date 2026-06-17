---
milestone: m1-sport-abstraction-and-nba-engine
topic: sport-generalization
shipped: 2026-06-03
status: shipped
---

# Milestone Summary: m1 — Sport abstraction + NBA engine

## What Shipped

The engine is now multi-sport: adding a sport = registering a `SportConfig` (series prefixes, structured
`IdentityResolver`, `MarketClassification`, containment `LadderSpec`, labels). Tennis behavior is fully
preserved — zero public-signature changes, zero test edits. NBA is registered from live keyless discovery
and parses/classifies/ladders correctly through the unchanged detection engine. UI is unchanged (NBA not
yet selectable — that's M2). Shipped as PR #23 (`feat/sport-abstraction-nba-engine`), awaiting merge.

## Success Criteria

- [x] `sports.py` with `SportConfig`/`LadderSpec`/`IdentityResolver`/`MarketClassification`/registry/`sport_for_series` (UNKNOWN explicit).
- [x] Tennis registered verbatim; back-compat aliases; **107 existing tests green, no edits, no signature changes**.
- [x] `data.py` resolves sport from ticker; identity via resolver; stamps `market_family`/`ladder_node`/`ladder_eligible`/`classification_reason`; raw metadata preserved.
- [x] `consistency.py` resolves `LadderSpec` from `row["series"]`; ladder gated on eligibility; ineligible → excluded.
- [x] NBA `SportConfig` from discovery; per-game/props classify ineligible.
- [x] Engine tests (10 new): unknown≠tennis, per-game excluded, unsupported has reason, low-confidence flagged, NBA ladder (clean + violation), tennis preserved.
- [x] `pytest` 117 green; ruff clean; headless 200; live NBA load (184 open / 504 incl. settled; 420 per-game excluded).

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| No global tennis default — UNKNOWN is explicit | A foreign ticker must be visibly unsupported, not mis-parsed as tennis | `sport_for_series` returns UNKNOWN; legacy `kind` "other" preserved |
| NBA reuses tennis family names (match/advance/winner) + game/other; ladder node set by the SERIES (classify stamps `ladder_node`) | NBA's node comes from the series (KXNBA=championship, KXNBAEAST/WEST=conference), not a title stage | Minimal consistency change; `node_of` prefers stamped node |
| Team identity = `custom_strike.basketball_team` | Live-discovered; exact analog of `tennis_competitor`, shared across a team's series | IdentityResolver candidate path |

## Deferred (seeds)

- Reach-Playoffs / Conference-Finals-qualifier as extra NBA ladder layers (currently 2-node: Win Conference ⊇ Win Championship).

## Files Touched

- `sports.py` (new), `data.py`, `consistency.py`, `kalshi_client.py`, `tests/test_sports.py`, `scripts/verify_sport.py` (manual verification tool).

## Sessions

Completed in one working session, 2026-06-03 (Stage 0 discovery → A refactor → B NBA config → tests → PR #23).

---
*Closed via complete-milestone on 2026-06-03*
