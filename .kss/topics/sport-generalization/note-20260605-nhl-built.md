---
session: 2026-06-05
milestone: —
topic: sport-generalization
slug: nhl-built
---

# NHL (8th sport) built & merged — PR #88

## Context

NHL was the lowest-risk remaining planned sport (NBA-shape). This session: a **plan-reconciliation
discussion first** (does the rev-5 NHL plan still hold after MLB merged?), then a full single-PR build,
verify, and merge. The interesting parts weren't the registration boilerplate — they were (1) realizing
how much of the rev-5 plan was made obsolete by MLB's shared foundation, (2) two NHL-owned general
correctness fixes that touch every non-tennis sport, and (3) discovering the docs were stale all the way
back to **pre-golf/soccer/MLB**, not just pre-NHL.

## Details

**Reconciliation (why NHL collapsed to one PR).** The rev-5 `New Sports/NHL-plan.md` "verified repo facts"
were false against current `main` (claimed `sports.py` = tennis/NBA/WNBA only, no golf/`exact_series`).
After MLB (#87) merged, NHL **consumes** rather than builds: `SportConfig.winner_label`
(`"Win the Stanley Cup"`), the sport-aware `data._contract_label` advance fix (so `KXNHLEAST/WEST`→
"Win Conference", `KXNHLPLAYOFF`→"Reach Playoffs" for free), `data.non_other_families` fetch scope,
`time_kind="Game time"`, and the backlog `last_settlement_caveat`. Old "PR 1" (per-sport category dispatch)
was already on `main` → dropped. The rev-5 winner-label/game-time follow-up PRs → obsolete.

**Two NHL-owned general fixes (each touches all non-tennis sports):**
- **Season-scoped grouping** — `data.tournament_of` now appends `· <season>` to every non-tennis key via a
  new `data._season_token(series, event)` (case-normalized; strips the prefix ONLY when the event ticker
  starts with the series ticker; reads `^[-_]?(\d+)`). Implemented as a **single wrapper around the return**
  (compute `(key, source)` exactly as before through all four branches, then suffix at the one exit point)
  rather than per-branch — robust to future branches. Tennis is `sport_id == "tennis"` → skipped → byte-
  for-byte unchanged (preserves the tennis regression guarantee). This blast-radiused the existing
  NBA/WNBA/golf/soccer grouping assertions (they gained `· 26`); audited and updated each to the suffix its
  fixture actually produces. The cross-season test guards that `KXNHL-26` vs `KXNHL-27` no longer form a
  false `EXECUTABLE_VIOLATION` (the original assertion was wrong — the chain STRING still appears as a
  within-season `MISSING_LAYER` diagnostic; the real guarantee is "no false executable violation + both
  tournaments processed separately").
- **Same-series dutch guard** — `dutchbook._detect_pair` now requires normalized strict same-`series`
  equality (`str(a.series).upper() != str(b.series).upper()` → skip). Errs toward NOT firing (the safe
  direction); two genuinely series-less rows still match (`"" == ""`).

**NHL specifics.** Identity `custom_strike.hockey_team`; ladder Reach Playoffs(`KXNHLPLAYOFF`)⊇Win
Conference(`KXNHLEAST`/`WEST`)⊇Win Championship(`KXNHL`); `match_family="match"` so BOTH `KXNHLSERIES`
(playoff series) and `KXNHLGAME` (game) are dutch-book eligible (unlike MLB, whose `KXMLBSERIES` is
excluded as tie-prone — an NHL best-of-7 can't tie). Exact-equality `family_fn` allow-list → lookalikes
(`KXNHLSERIESGAMES`, `KXNHLFINALSEXACT`, props) resolve to `other`. Live `KXNHLSERIES` wording is only
"1st/2nd Round" (no Conference-Final/Stanley-Cup-Final SERIES text — the championship is the `KXNHL`
field), so `_NHL_ROUND_PATTERNS` carries best-effort finals patterns but they're currently unhit →
series → no ladder rung → `UNKNOWN_RELATIONSHIP`. NHL's value = the advance+winner ladder + series/game
books.

**Docs debt discovered.** The README registered-sports + ladder tables and `docs/TECHNICAL_DOCUMENTATION.md`
top-level "supported sports" were still **tennis/NBA/WNBA** — they'd been left stale through golf, soccer,
AND MLB. Brought the high-level claims + every NHL-relevant section (identity list, `match_family`,
dutch-book eligibility, ladder/registered tables) to the full seven sports. **Residual debt left:** the
per-EXAMPLE NBA/WNBA-only paragraphs in TECHNICAL_DOCUMENTATION.md (pre golf/soccer/MLB) — flagged in the
PR body for a separate docs-catchup rather than expanding NHL's scope.

## Outcome

PR #88 (`feat/nhl-sport`, commit `24f1c22`) **MERGED → `origin/main` `0aab982`**. `tests/test_nhl.py`
(22 cases) + NHL AppTest smoke. **537 pytest pass, ruff clean, py_compile OK, headless Streamlit boot
health 200.** Worked in-place on the primary tree (no concurrent session); scratch dirs (`New Sports/`,
`Concurrent Plans/`, `tmp_kalshi_docs/`) NOT committed. Live Kalshi smoke NOT run (sandbox) — `KXNHLPLAYOFF`
spelling + `hockey_team` path flagged INDICATIVE in the plan; re-verify live before trusting row presence.

## Followups

- **GDrive docs refresh** (standing rule) — now two merged sports behind (MLB + NHL).
- **TECHNICAL_DOCUMENTATION.md per-example catch-up** — NBA/WNBA-only example paragraphs predate
  golf/soccer/MLB/NHL; a focused docs PR.
- Remaining planned sports unchanged: NFL, NCAAB, UFC (each should now consume the shared foundation +
  rebase onto current `main`; NFL/UFC carry genuinely-new engine work — `game_mece_by_shape`/
  `_proves_fixed_sum`, identity-join/`CONDITIONAL_DUTCH_BOOK`).
