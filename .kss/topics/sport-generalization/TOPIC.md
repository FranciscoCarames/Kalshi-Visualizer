---
slug: sport-generalization
created: 2026-06-03
last_updated: 2026-06-03
status: active
---

# Topic: sport-generalization

## What This Is

Gradually generalize the Kalshi dashboard from tennis-only to multi-sport, **on the current Streamlit
stack** (no backend/real-time rearchitecture — that's the parked `real-time-opportunity-engine`). First
sport: **NBA**. Approach: extract a Sport abstraction from the tennis code without changing tennis
behavior, then add sports as additive, discovery-grounded config.

## Goal

A sport-agnostic engine where adding a sport = registering a `SportConfig` (series prefixes, structured
identity resolver, market classification, containment ladder, labels) — with the detection engine, HTTP,
pricing, filters, and viz unchanged. Unsupported/non-laddered markets are first-class (surfaced, never
silently mis-handled).

## Success Bar

NBA markets parse, classify, and ladder-check correctly alongside tennis; tennis behavior is fully
preserved (existing tests green); a new sport is a config drop, not an engine change.

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-03 | NBA is the first new sport | Same containment-ladder shape as tennis, live June 2026 Finals for validation, draw-free, team-identity exercises the abstraction cleanly. Better than soccer (draws + group MECE = parked dutch-book work). |
| 2026-06-03 | Abstraction-first: tennis stays green, zero public-signature changes | De-risks via the trusted existing test suite; sport resolved internally from the series ticker/row. |
| 2026-06-03 | Structured `IdentityResolver` + `MarketClassification`; no global tennis default (UNKNOWN is explicit); unsupported markets first-class | Teams have no `tennis_competitor` UUID; per-game/props must never enter ladder checks; unknown series must be visible, not silently treated as tennis. |
| 2026-06-03 | Basketball ladder node comes from the **series**, not a title stage; multiple advance series map to distinct rungs by deriving the advance "stage" from the series ticker (`advance_stage_to_node`) | NBA/WNBA have no round in the title (KXNBA=championship, KXNBAPLAYOFF=reach playoffs). Enabled the NBA 3-rung and WNBA 4-rung ladders with zero engine change. |
| 2026-06-03 | WNBA is its own sport with a **single-bracket reach-stage ladder** (Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship), NOT conference-based | Modern WNBA has no conference final; `KXWNBAEAST/WEST` are defunct/empty; qualifier rules say "qualifies for X". Separate `wnba` config (not an NBA division). |
| 2026-06-03 | Abstraction **proven**: 3 sports (tennis/NBA/WNBA) off one engine; adding a sport = a `SportConfig` drop | M1–M3 shipped with zero engine changes between sports; tennis's original tests never edited. |
| 2026-06-04 | Golf v1 = the 4 exact Kalshi PGA-style series (`KXPGATOP20/10/5` + `KXPGATOUR`); ladder **Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win**. Make Cut / H2H (`KXPGAH2H`) / dutch-book / other tours (DP World, LIV) deferred. | "Simple" placement contracts share tennis's containment shape. One static ladder per sport can't model differing per-tour rung sets, so scope to one coherent set. |
| 2026-06-04 | Golf needs **2 real engine changes** (NOT a pure config drop) | (1) Prefix `startswith` ownership is unsafe for golf's ticker space (`KXPGA*` would grab props / round-finishers / H2H that share the same `golf_competitor` + competition) → add an **`exact_series`** field (last on `SportConfig`; exact-checked first across all sports, globally precedence-safe) with empty prefixes/winner_tickers. (2) `consistency._row` category is hardcoded to `data.CATEGORY` (tennis) → resolve per-row off the row's sport with an `"Other"` default. |
| 2026-06-04 | Soccer (2026 World Cup) is the next sport AND the trigger for **n-outcome MECE**; scoped to a 3-PR plan (`Concurrent Plans/soccer-world-cup-plan.md`) | `KXWCGAME` group games are **3-way (Home/Away/Tie)**, breaking the 2-outcome dutch-book assumption. Acts on seed S1. PR 0 (fixtures/verification, gating) → PR 1 (`soccer` config + participant typing) → PR 2 (n-outcome detector + `legs` schema migration). |
| 2026-06-04 | MECE proof is **per-family/structural**, dispatched on `sport_id`; `mutually_exclusive` flag alone is insufficient | ME ≠ MECE: underround (Buy-YES-all) needs **exhaustiveness**, overround (Buy-NO-all, threshold `(n−1)·100`) needs only ME + a settlement-sanity gate. Legacy draw-free 2-way (tennis match, NBA/WNBA series **and per-game**) keeps its by-construction proof, untouched. Formalized as a `MeceProof` object. |
| 2026-06-04 | Soccer ladder spine = **`KXWCROUND`** (per-team reach-stage); **`KXWCSTAGE` excluded** | Live: `KXWCROUND` = "team qualifies for round X" (monotone, `soccer_team`). `KXWCSTAGE` = categorical region-aggregated "furthest stage" (`Sporting Outcome`) — NOT monotone, NOT per-team. Group-winner / region furthest-stage are n-outcome **fields** → deferred. |
| 2026-06-04 | **Entity typing decoupled from opportunity routing** (corrected mid-session) | `is_participant ≡ real competitor (team/player)`, independent of family → drives the selector (keeps tennis set/exact-score players selectable; excludes Tie/categorical). Opportunity eligibility is **family-based** (`opportunity_families`) → that, not the selector, stops prop-leak. Tie = constant UUID → synthetic per-event key, never a global participant. |
| 2026-06-04 | **No per-team elimination heuristic** (reversed an earlier round) | On `status="open"` fetch, an eliminated team's market is simply absent — indistinguishable from a fetch gap. So missing-layer noise is controlled only by tournament-scope node-presence suppression + the Active-only default. Broadening the fetch to settled events is a deferred option. |

## Out of Scope

- Backend / WebSocket / real-time (parked `real-time-opportunity-engine`).
- Trading fees / net-of-fees (parked roadmap NS-1; gross-only, caveats added for n-leg books).
- ~~Soccer/draws and the dutch-book/MECE detector~~ → **now planned** (2026-06-04; see Key Decisions + `Concurrent Plans/soccer-world-cup-plan.md`).
- n-outcome **field** MECE (group-winner 12-way, furthest-stage region fields) — deferred even within the soccer plan.
- Sports beyond the planned set (NHL etc. added one at a time later).

---
*Created via new-topic on 2026-06-03*
