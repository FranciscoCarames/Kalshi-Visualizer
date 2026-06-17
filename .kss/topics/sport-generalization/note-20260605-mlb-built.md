---
session: 2026-06-05
milestone: —
topic: sport-generalization
slug: mlb-built
---

# MLB (7th sport) built and shipped — PR #87

## Context

The MLB plan was written 2026-06-04 against the old `feat/round-parser-fix` checkout (only tennis/NBA/WNBA
registered). By 2026-06-05 `main` had the full UNIFIED-PLAN merges (#48–#78), so the plan's two-PR split —
whose whole reason to exist was *building* the `settlement_caveat` field end-to-end — was obsolete. This
session re-pinned the plan to current `main` (single PR), then implemented it. This note records the
decisions future sports (NFL/NHL/NCAAB/UFC plans) will reuse.

## Details

**Already-shipped on `main` (struck from the plan, do NOT redo for any future sport):**
- Per-sport category dispatch: `consistency.py:597-598` resolves `child/parent_category` per-row via
  `_sport_for_row`; the tennis `CATEGORY` import is gone (`consistency.py:23`).
- `settlement_caveat`: durable field on opportunity/scanner/`api.Opportunity`/store/NiceGUI rows,
  **family-keyed** in `dutchbook._settlement_caveat` (`dutchbook.py:159`) → any `kind=="game"` row inherits
  the `BLOCKERS["game_settlement"]` caveat automatically. No per-sport wiring needed to enable game books.
- Conservative dutch-book wording (`glossary.DUTCH_BOOK_BASIS`, "Dutch book" entry) — #58.

**What this PR actually changed (the still-pending work):**
1. `SportConfig.winner_label: str = "Win the tournament"` (defaulted, appended after `tie_fn`). NBA/WNBA →
   "Win the Championship", MLB → "Win the World Series"; tennis/golf/soccer keep the default.
2. `data._contract_label(kind, market, opponent, stage, cfg, ladder_node)` — winner uses
   `cfg.winner_label`; **advance prefers `ladder_node`** else `f"Reach {stage}"`/"Reach next stage". This
   is a GLOBAL change with cross-sport blast radius (verified by tests):
   - MLB `KXMLBAL/NL` → "Win League"; `KXMLBPLAYOFFS` → "Reach Playoffs".
   - NBA `KXNBAEAST/WEST` → "Win Conference" (latent fix; was the wrong "Reach Conference").
   - Golf `KXPGATOP5/10/20` → "Top 5/10/20" (improvement; node == stage, was "Reach Top 5").
   - Soccer `KXWCROUND` → unchanged "Reach Round of 16" (node already carries "Reach").
   - Tennis/WNBA advance + tennis winner → unchanged (the regression guarantee held; 514 pass).
3. `data.non_other_families(cfg)` — single-sourced fetch scope excluding the `"other"` family key, wired
   into BOTH `app.py:581` (cross-sport) and `api.py:210` (`fetch_dep`) so they can't drift. The two paths
   previously each did `tuple(sorted(set(cfg.category_labels.values())))` which INCLUDED "Other" — latent,
   matters at MLB's ~110-prop scale.
4. `data.py:592` time stamping: `kind in ("match","game")` uses occurrence time; `time_kind="Game time"`
   for `game`. Latent fix for NBA/WNBA/soccer games too (they showed "Close time").
5. Backlog caveat gap (the only remaining `settlement_caveat` hole): `last_settlement_caveat` added to
   `lifecycle.recently_actionable` (`:184-201`), `api.BacklogItem` (`:141`), the Streamlit backlog table +
   `recently_actionable.csv` (`app.py:686-700`), and NiceGUI `_BACKLOG_COLUMNS` (`webui/dashboard.py:77`) +
   `vm.backlog_row` (`webui/viewmodel.py:136`).

**MLB config specifics:** `series_prefixes=("KXMLB",)`, allow-list `family_fn` (KXMLB→winner,
KXMLBAL/NL/PLAYOFFS→advance, KXMLBGAME→game, else other), `match_family=""`, `winner_label="Win the
World Series"`, identity `custom_strike.baseball_team`, `advance_stage_to_node={"Playoffs":"Reach
Playoffs","League":"Win League"}`. `_mlb_stage` is evidence-based (no ticker evidence → "", not a false
"League" guess). `KXMLBSERIES` excluded — a regular-season series can tie 2-2, so 2 markets are NOT MECE.

## Outcome

- Branch `feat/mlb-sport` (commit `1b2bf9d`) → **PR #87 open**, awaiting owner merge.
- 13 files, +449/−26; `tests/test_mlb.py` = 21 cases. Full suite 514 pass, ruff clean, py_compile clean,
  headless Streamlit (`/_stcore/health` 200) + `serve.py` (`/`,`/metrics` 200).
- In-repo docs updated (CLAUDE.md, README.md, docs/DEPLOYMENT.md, scanner.py/app.py sport-list strings).
  `docs/PROJECT_BRIEF.md` + `docs/TECHNICAL_DOCUMENTATION.md` left for the manual GDrive-sync pass (already
  behind on golf/soccer).

## Followups

- Owner: merge PR #87. Then GDrive Project Brief + Technical Documentation refresh (standing rule).
- Pre-existing flake: `test_app_renders_without_exception` fails intermittently under `pytest-randomly`
  (passes isolated and with `-p no:randomly`). Not MLB-caused; worth a separate hardening pass.
- Live re-verification: the MLB market facts (tickers, `competition="Pro Baseball"`, identity path,
  excluded list) are 2026-06-04 probes flagged INDICATIVE — re-probe live before trusting row presence.
- The cross-sport foundation (winner_label, ladder-node advance labels, non_other_families, game-time,
  backlog caveat) is now in place, so NFL/NHL/NCAAB/MLB-sharing items in those plans can be struck too.
