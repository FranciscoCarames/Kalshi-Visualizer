---
session: 2026-06-04
milestone: —
topic: sport-generalization
slug: nhl-plan
---

# NHL (sport) — plan + the six review rounds that shaped it

## Context

Planned NHL (hockey) as a new sport. Full implementation plan at **`New Sports/NHL-plan.md`** (working
copy `~/.claude/plans/mutable-gathering-kettle.md`). This note captures *why* the plan looks the way it
does — it survived **six adversarial review rounds** plus a live Kalshi probe, each round correcting a
wrong assumption. Not yet implemented.

## ⚠ Repo-state caveat / RECONCILE before building (important)

The plan was written against the **stale `feat/round-parser-fix` Internship checkout**, which registers
**only tennis/NBA/WNBA** (`sports.py:311/409/514`), still has the **tennis-only category dispatch**
(`consistency.py:566-567` → `from data import CATEGORY`), and **no golf / no `exact_series`**.

But per the project `.kss/STATE.md`, **`origin/main` is far ahead** (unified-plan-build Phases A–D
merged): golf + soccer are registered, the **per-sort category dispatch is ALREADY FIXED** (golf
required it), the end-to-end **`settlement_caveat`** field + **n-outcome MECE** detector exist, and
sport-aware label infra was added. **Consequence for NHL on origin/main:**
- **PR 1 (category dispatch) is likely MOOT** — already done by the golf merge. Verify
  `consistency._row` resolves `child/parent_category` per-row before writing PR 1; if so, NHL collapses to
  a single PR.
- Build NHL **on top of** the existing `settlement_caveat`/label/`non_other_families` infra — do NOT
  recreate it.
- The season-grouping fix (below) may already be partly handled by MLB/NFL's `tournament_of`
  season-qualification work if those merged — check before re-implementing.

## Live-verified facts (Kalshi `external-api.kalshi.com`, read-only, 2026-06-04)

- Identity `custom_strike.hockey_team` (stable UUID across a team's series — like NBA `basketball_team`).
- Series: `KXNHL` = Stanley Cup winner field (`KXNHL-26`, 32 markets, ME=true); `KXNHLEAST`/`KXNHLWEST`
  = conference fields (16 each, = reach the Final); `KXNHLPLAYOFF` = qualifier field (32, ME=false);
  `KXNHLSERIES` = playoff series head-to-head (2 markets, ME=true); `KXNHLGAME` = single game (2, ME=true,
  active). Prefix `KXNHL` does NOT collide with `KXNBA`/`KXWNBA`.
- **Ladder = NBA shape:** Reach Playoffs (`KXNHLPLAYOFF`) ⊇ Win Conference (`KXNHLEAST/WEST`) ⊇ Win
  Championship (`KXNHL`).
- **`KXNHLSERIES` round wording** is in BOTH `market.title` and `rules_primary` ("… 2026 **2nd Round**
  series", "… **1st Round** series in the 2026 NHL playoffs"); ticker suffix `R1`/`R2` (2026; 2025 had no
  suffix). **Only "1st/2nd Round" appear** — no Conference-Final / Stanley-Cup-Final SERIES wording
  exists; the championship is carried by the `KXNHL` winner field. So series match-alignment maps to **no
  ladder node today** (safely `UNKNOWN_RELATIONSHIP`). NHL's ladder value = advance+winner; the
  series/game value = **dutch books**.

## Plan shape (final, rev 5)

- **PR 1** (only if not already on origin/main): per-sport category dispatch in `consistency.py:566-567`
  (`_sport_for_row(...).category_labels`) — the proven blocker (else `app.py:216` family filter +
  `filters.py:44-45` drop NHL rows → **empty dashboard**). Drop the now-unused `CATEGORY` import.
- **PR 2:** register `NHL = register(SportConfig(...))` mirroring NBA (identity `hockey_team`,
  `match_family="match"`, `series_prefixes=("KXNHL",)`); round parser uses **text only** (no `FIN`/`CF`
  ticker fallback — that was WRONG; grammar is `Rn` and the championship isn't a series), with
  semifinal/conference guards and **no bare `\bfinals?\b`** (miss-not-misclassify).
  - **Season-grouping FIX** (implemented, NOT just documented — supersedes an earlier "guard+document"
    choice): `data.tournament_of` becomes season-aware for non-tennis via a new `_season_token(series,
    event_ticker)` that **normalizes case, only strips when `event.upper().startswith(series.upper())`,
    then `^[-_]?(\d+)`** on the remainder (`KXNHL-26`→`"26"`). Key → `"{competition} · {token}"`. Prevents
    cross-season false inconsistencies. Updates NBA/WNBA grouping tests (keys are "Pro Basketball (M)/(W)"
    → "… · 26").
  - **Dutch-book guard** (real `dutchbook.py` change): `_detect_pair` also requires both rows share the
    same `series` (defensive vs event-ticker collisions); update the "game" comment to incl. NHL (scoped).
- **Follow-up PR 3 (optional, NOT in scope):** sport-aware winner label + series-vs-match `time_kind`
  (needs a new `SportConfig` field — `time_kind="Match time"` keys off `kind=="match"` but tennis also
  uses `match_family="match"`). ← likely already covered by merged MLB/NFL label infra on origin/main.

## The six review rounds (what each corrected)

1. Caught that the repo had **no golf / no category fix** (a concurrent session had transiently shown a
   phantom "golf-merged" tree); the category dispatch is the **real blocker** → NHL is not a pure drop.
2. Forced the **engine prerequisite** + two-PR split; surfaced the full test/doc breakage
   (`test_scanner.py` counts, `test_sports.py` registered-set, DEPLOYMENT/PROJECT_BRIEF docs).
3. Corrected my **incorrect claims** (`data.CATEGORY` has no consumer post-fix; webui already generic);
   pulled readability fixes into a follow-up; chose the round-parser failure mode (miss-not-misclassify).
4. Pushed **fix-not-accept**: season grouping must be FIXED (not xfail+doc), dutchbook needs a real
   same-series guard + comment update, AppTest needs precise `scan_all_toggle=False`. Declined prefix-
   ownership "uncleanliness" with reasoning (semantically correct; cross-sport fetch-cost only).
5. **Live Step 0 probe** embedded → killed the wrong `FIN`/`CF` ticker fallback (grammar is `Rn`), proved
   only 1st/2nd-Round series wording exists, confirmed `hockey_team` identity + 2-market MECE shapes.
6. Tightened `_season_token` (the "leading digit-run" was wrong since `KXNHL-26`→`-26` starts with `-`);
   added case-normalization, prefix-guarded slicing, and explicit helper tests; fixed the NBA/WNBA test
   labels ("Pro Basketball (M)/(W)", not "NBA"/"WNBA").

## Followups (seeds)

- Verify on origin/main whether PR 1 (category dispatch) and season-qualified `tournament_of` are already
  merged → collapse NHL to one PR if so.
- Step 0 re-probe the deeper rounds (Conference Final / Stanley Cup Final series) once 2026 playoffs reach
  them, to confirm whether `match_stage_to_node` ever gets hit (currently best-effort/unhit).
