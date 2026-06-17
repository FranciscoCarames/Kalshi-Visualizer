---
session: 2026-06-04
milestone: —
topic: sport-generalization
slug: mlb-plan
---

# MLB (7th sport) — plan + the six review rounds that shaped it

## Context

Planned MLB as the next sport. The full implementation plan lives at **`New Sports/MLB-plan.md`**
(working copy `~/.claude/plans/federated-sniffing-goose.md`). This note captures *why* the plan looks
the way it does — it went through **six adversarial review rounds**, each of which corrected a wrong
assumption. Without this trace the plan reads as obvious; it wasn't.

## Repo-state caveat (important)

This checkout (`feat/round-parser-fix`, off the Internship tree) registers **only tennis, NBA, WNBA**
(`sports.py:311/409/514`). **No golf, no `exact_series`** here — the golf/soccer plans in
`Concurrent Plans/` and the golf mention in CLAUDE.md are **unmerged**. MLB needs no `exact_series`
(prefix `"KXMLB"` + exact `family_fn` allow-list suffices), so this doesn't block MLB.

## Live-verified facts (Kalshi `external-api.kalshi.com`, read-only)

- Identity `custom_strike.baseball_team` (UUID shared across a team's series — like NBA `basketball_team`).
- Grouping safe: **event-level** `product_metadata.competition = "Pro Baseball"` across the futures
  series → one stable `tournament_of` key → a team's rungs pair.
- `KXMLB` = WS champion future (event `KXMLB-26`, 30 markets, ME=true); `KXMLBAL`/`KXMLBNL` = pennant =
  reach WS; `KXMLBPLAYOFFS` = playoff qualifiers (ME=false, many Yes → reach-market, not dutch-eligible);
  `KXMLBGAME` = single game.
- ~120 `KXMLB*` series total; ~110 are props/leaders/awards/`KXMLBWINS-*` → must be `other`.

## How the plan evolved (the meat)

1. **R0 (initial):** "MLB is a pure NBA-style config drop, zero engine changes; ladder + games + series
   dutch books." Chosen via AskUserQuestion: 3-rung ladder + games-and-series.
2. **R1:** golf/exact_series assumed present — **false** (verified). Also `consistency._row:566-567`
   stamps categories from tennis `data.CATEGORY` → MLB `winner`→"Tournament winner" / `game`→None. So
   **not zero-engine**. `KXMLBSERIES` is regular-season (can tie 2-2) → **2 markets ≠ MECE** → reversed
   to games-only, isolated via `match_family=""` + `KXMLBSERIES`→`other` (avoids `build_checks:663`
   UNKNOWN_RELATIONSHIP spray).
3. **R2:** the dutch-book "guaranteed/locked/true arbitrage" wording is overstated for per-game baseball
   (postpone/suspend → last-fair-price). Found it's **not single-sourced** — also `app.py:738/763`
   caption/column, `dutchbook.py:199` reason text, `scanner.py:107` & `consistency.py:811` comments,
   glossary, README/CLAUDE hard rules, `TECHNICAL_DOCUMENTATION.md:518` ("exactly-2 guard is the real
   MECE safety net" — false in general). Distinguished **rule-mismatch caveat (kept)** from
   **settlement-contingency caveat (new)**.
4. **R3:** the caveat is **not** copy — the finding flows `dutchbook→scanner→store→api→webui/NiceGUI`,
   and `scanner.py:95` drops `reason`, `api.py:33` has no caveat field, `webui/dashboard.py:50` reads
   `blocked_reason` (blank for actionable). **Decision: split into two PRs** — PR1 ladder-only
   (`KXMLBGAME`→`other`, no caveat surface), PR2 a durable `settlement_caveat` schema field end-to-end +
   enable games. Also `verify_sport.py:52` `--all` bypasses `series_for_families` (doesn't prove fetch
   filter); category fix must reuse stamped `row["category"]` with robust fallback.
5. **R4/R5:** hardened PR boundaries: one shared `non_other_families(cfg)` helper for **both** fetch
   paths (`app.py:539` + `api.py:124`); evidence-based `_mlb_stage` (returns `""` without ticker
   evidence, not a false "League"); precise caveat wording ("…including last fair market price", no
   blanket "void"); the field is **separate from `blocked_reason`** (actionable rows keep it, invariant
   preserved); propagate into lifecycle/backlog (`lifecycle.py:155`) + `api.BacklogItem`; both scanner
   mappers set it (`_to_unified_consistency`→`""`); fixtures-first testing, live = smoke-only.
6. **R6 (last real miss):** sport-aware **contract labels** — `data._contract_label:362` hardcodes
   winner→"Win the tournament" AND advance→"Reach {stage}" for all sports. MLB `KXMLBAL/NL` (stage
   "League")→"Reach League" is wrong (node is "Win League"); latent NBA `KXNBAEAST/WEST`→"Reach
   Conference" too. Fix: add defaulted `winner_label` (LAST SportConfig field) + pass `mc.ladder_node`
   and prefer it for `advance`. Tennis/WNBA unchanged (their advance nodes already equal `Reach {stage}`).

## Outcome

Two-PR plan, owner-approved. **PR1 = MLB futures ladder** (small, no dutch-book/caveat work). **PR2 =
cross-sport `settlement_caveat` schema field + enable `KXMLBGAME`** (also fixes NBA/WNBA game gap). No
code written yet. Plan + this note are the durable record; nothing is in the codebase.

## Followups (seeds)

- Win Division branch (needs `layer_spreads` `zip(node_order)`→`adjacent_pairs`).
- `KXMLBSERIES` dutch books (needs PDF tie/void modeling + event-level regular-vs-postseason split;
  `match_family` is sport-wide so not a one-field flip).
- `stage_fn` signature lacks `series_ticker` (inherited NBA weakness).
