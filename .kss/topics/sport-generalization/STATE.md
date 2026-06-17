---
topic: sport-generalization
status: executing
active_milestone: null
last_session: 2026-06-10
last_updated: 2026-06-11
---

# Topic State: sport-generalization

## Current Position

**2026-06-10 — World Cup + ITF series-coverage expansion CONVERGED (NOT merged, awaiting owner).** Closed
the soccer exact-ownership blind spot (`KXWC*` not in `_SOCCER_EXACT` silently → UNKNOWN). 4 branches off
`feat/bounded-loss-phase2` (`dd041c8`) **converged into `feat/convergence-20260610`**, with
`feat/ui-trust-fixes` stacked (tip **`197bf07`** = the owner-preferred merge tip). A `_SOCCER_KNOWN_OTHER`
(9 props) + `scripts/audit_series_coverage.py`; B `KXWCGROUPBOTTOM` cardinality basket (live ME flip,
behavior-neutral); C new `stage_elim.py` 7-bucket book + tail-sum synthetic; D ITF tennis ownership. All
live gates passed kickoff eve (`KXMENWORLDCUP-26` sole open outright — standing follow-up RESOLVED), **901
tests**, ruff clean, boot green. 65 NEW unowned `KXWC*` listed report-only. All pushed (no PRs); main
frozen. See LOG 2026-06-10; memory `wc-itf-series-coverage-expansion.md`. **Note:** the WC/ITF stack sits
on the bounded-loss branch lineage (dashboard-usability topic) — the single merge tip 197bf07 carries both.

**✅ ESPORTS (10th sport) BUILT & MERGED 2026-06-08 — PR #129 merged to `main` (`c1fe3d5`).** See memory
`esports-sport-built.md` + `note-20260608-esports-{probe,built}.md`. A **field sport with a game layer,
NO ladder (v1)**. Clean `SportConfig` drop-in — `sports.py` + `tests/test_esports.py` + docs only, **no
engine edits** (reuses NFL's `game_mece_by_shape`, default `True`). Identity
`custom_strike.esports_competitor`. `KX*GAME` (match winner) + `KX*MAP` (map winner) are 2-way **draw-free**
`mutually_exclusive` → `"game"` family → **ungated** dutch books (unlike NFL's tie-gated games); per-title
winner series (`KXCS2`, …) → field overround. **Curated exact-ownership allow-list** (`series_prefixes=()`,
`exact_series` = game/map + per-title winner across CS2/LoL/Valorant/Dota2/CoD/R6/OW/RL/PUBG/Brawl/
Crossfire); totalmaps/qualifiers/props/MVP/rank/roster/legacy-CSGO/dupes/test/event-majors → `"other"`
(unowned → UNKNOWN, never fetched). Per-title `divisions` (`division_label="Title"`). Verified: **pytest
663** (+12), ruff, `serve.py` boot on NON-default port (200s), live `verify_sport.py esports` → 302
contracts (258 game / 44 winner), 0 false ladder rows; real `KXCS2GAME` underround surfaced live. **v2
deferred:** qualifier ladders (+ a `qualifier` family / `UNKNOWN_RELATIONSHIP` emission in consistency.py),
opponent action labels + map caveat wording (data.py/glossary.py), tag-aware (`tags=Esports`) discovery +
live excluded-series diagnostics (kalshi_client.py), `/milestones` match grouping, event-specific majors.
**Allow-list is MAINTAINED — esports series churn fast.** NFL (#128) confirmed merged → esports = 10th sport.

**✅ NFL (9th sport) BUILT & MERGED 2026-06-08 — PR #128 merged to `main` (`34d0d96`).** Core futures
ladder Reach Playoffs(`KXNFLPLAYOFF`)⊇Win Conference(`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`)⊇Win Super Bowl(`KXSB`
winner field→overround); `KXNFLGAME` games are tie-capable → new `SportConfig.game_mece_by_shape=False`
GATES the 2-way book on `dutchbook._proves_fixed_sum` ($0.50-tie / no-tie proof). Identity `football_team`;
strict exact-equality `family_fn` allow-list → props/totals/spreads/division/awards/draft `other`.
`tests/test_nfl.py`. This is the field esports reuses (untouched, default `True`).

**✅ MOTORSPORT (F1/NASCAR/IndyCar/MotoGP) BUILT 2026-06-05 — PR1 #104 MERGED, PR2 #105 OPEN.** See memory
`motorsport-sport.md` + LOG. A **field sport like golf** (`match_family=""`). Crucially NOT "one register
call": Streamlit/`app.py` is RETIRED on main (NiceGUI-only), so the engine needed an **adapter first**.
**PR1 #104 (merged) = engine adapter**, all hooks DEFAULTED (no-op for the 7 sports): `SportConfig.
field_families` (one-winner-field generalization → `dutchbook._is_field_row`), event-only
`tournament_key_fn`, per-group `ladder_fn`, `role_fn` (family-derived role-namespaced `player_key`;
build_contracts reorder = classify before key), `IdentityResolver.id_validator` (per-value confidence),
variable-tick subpenny guard (`data.market_has_subpenny`, integral-cents test; dutchbook+consistency skip).
**PR2 #105 (open, `feat/motorsport-register` off merged main) = register Motorsport**, grounded in a LIVE
read-only Phase-0 probe (`/search/filters_by_sport` + nested markets). Identity multi-path
racing_competitor(driver UUID)/nascar_team(UUID)/Participant(constructor NAME→low via validator);
role-namespace driver/constructor/team. family_fn series-only (each scope owns its series). field_families
= winner/race_winner/pole/fastest_lap/constructor/team (ME=True one-winner fields → overround); **Top-N/
Podium ME=False → finishing ladder, NOT fields**. Kalshi "**Games**"=race_winner (NOT app `game`).
Per-competition `ladder_fn` (F1 Top10⊇Top5⊇Podium⊇WinRace; Cup +Top20/Top3; Truck/IndyCar Top10⊇Top3⊇Win;
MotoGP+O'Reilly none). `tournament_key_fn` = `competition · session · token` (raw competition_scope NEVER
in key — would split a race's rungs). KXRACE(Ferrari KPI) excluded; H2H deferred. Verified: **pytest 592**,
ruff, serve.py boot on NON-default port (200s), + live e2e engine probe (constructor:Red Bull Racing LOW vs
driver UUIDs HIGH; same-race grouping; real DISPLAY_VIOLATIONs). Docs→8 sports. **After #105 merges:**
GDrive sync (owner), manual browser check, optional NiceGUI Series chip. (52 motorsport series found, ~27
in default_series; probe scripts `.codex_tmp/` untracked.)

**✅ NHL (8th sport) BUILT & MERGED 2026-06-05 — PR #88 merged → `origin/main` `0aab982` (`feat/nhl-sport`,
commit `24f1c22`).** See `note-20260605-nhl-built.md`. Single PR off the MLB-merged `main`: NBA-shape ladder
Reach Playoffs(`KXNHLPLAYOFF`)⊇Win Conference(`KXNHLEAST`/`WEST`)⊇Win Championship(`KXNHL`); identity
`hockey_team`; `winner_label="Win the Stanley Cup"`; `match_family="match"` → `KXNHLSERIES` + `KXNHLGAME`
dutch books; exact-equality allow-list → lookalikes `other`; live series rounds only "1st/2nd Round" → no
rung → `UNKNOWN_RELATIONSHIP`. **Consumed** the MLB shared foundation (so old PR1 + winner_label/game-time
follow-ups were moot). **Two NHL-owned general fixes (now on `main`, affect all non-tennis sports):**
`data.tournament_of` season-scopes non-tennis grouping keys via `data._season_token` (`· <season>`, single
wrapper, tennis byte-for-byte unchanged — updated the existing NBA/WNBA/golf/soccer grouping assertions);
`dutchbook._detect_pair` normalized strict same-`series` guard. 537 pytest pass, ruff clean, headless 200.
Docs swept to 7 sports (README/TECHNICAL_DOC top-level were stale back to pre-golf/soccer/MLB — fixed;
per-EXAMPLE TECHNICAL_DOC debt left for a docs-catchup). Live Kalshi smoke NOT run (sandbox) — re-verify
`KXNHLPLAYOFF`/`hockey_team` live.

**✅ MLB (7th sport) BUILT & MERGED 2026-06-05 — PR #87 merged into `main` (`feat/mlb-sport`, commit
`1b2bf9d`; owner merged same session).** See `note-20260605-mlb-built.md`. This was the first new sport actually
implemented since the topic's NBA/WNBA work — done as ONE PR (the plan's old 2-PR split was moot once the
`settlement_caveat` + category-dispatch infra landed via #48–#78). It also introduced the **shared
cross-sport foundation the other plans assume**: `SportConfig.winner_label`, ladder-node-aware advance
labels in `data._contract_label` (fixed latent NBA "Reach Conference"→"Win Conference" + golf "Reach Top
5"→"Top 5"), `data.non_other_families` single-sourced fetch helper, `time_kind="Game time"` for all
`kind=="game"`, and backlog `last_settlement_caveat`. So NFL/NHL/NCAAB/UFC plans can strike those shared
items — verify what's on `main` before rebuilding. 514 tests pass; live Kalshi smoke NOT run (sandbox).

**Still planned-not-started: UFC (fight-centric MMA), NCAAB college basketball, NFL.** ⚠ Note: golf +
soccer + MLB + NHL are now merged/shipped; the older plans were written against the stale
`feat/round-parser-fix` checkout, so **rebase onto current origin/main before building** and reuse the
existing caveat/label/winner_label/non_other_families/season-scoped-`tournament_of`/same-series-guard infra.

**UFC (this session)** — full plan at `New Sports/UFC-plan.md` (working copy
`~/.claude/plans/frolicking-whistling-scott.md` + `note-20260604-ufc-plan.md`), hardened over **12
adversarial review rounds**. The **most distinctive sport yet — NOT a config drop.** TWO value layers:
dutch-book (`KXUFCFIGHT` 2-way + `KXUFCMOV` n-way method-of-victory) AND **cross-family containment**
(`KXUFCMOV`/`KXUFCVICROUND` outcome ⊆ the fighter's FIGHT win; `KXUFCROUNDS` cumulative ladder). Core engine
correction: the "2 markets ⇒ MECE" assumption is **false** (draw/no-contest) → exhaustiveness is a
per-family/event proof. **Two HARD GATES block any user-facing signal:** (A) **identity-join** — FIGHT keys
fighters by `custom_strike.ufc_competitor` UUID but MOV/VICROUND carry the fighter only as a NAME
(`custom_strike.Participant`) → NEW **post-flatten** `data.resolve_cross_series_identity(rows,cfg)` (because
`build_contracts` is per-series, fetch.py:40, can't see FIGHT while building MOV); join-fail →
`UNKNOWN_RELATIONSHIP`, never low-confidence executable. (B) **settlement-basis** — FIGHT is
ME-but-not-exhaustive → new **`CONDITIONAL_DUTCH_BOOK`** status (`is_locked=False`), overround-only, **emits
ONLY when basis proves a non-losing floor** (`unknown` AND known-but-unfavorable suppress). `match_family=
"match"` (reuse occurrence/stage/source special-casing); **`exact_series`-owned** (`KXUFCFIGHT/MOV/VICROUND/
ROUNDS`; prefix over-collects title/White-House/occurrence/retirement props; `KXUFCDISTANCE`/`OCCUR`
excluded); `default_families`/`dutchbook_families` are KEYS converted to LABELS at the fetch boundary
(`series_for_families` filters on labels); containment keyed `(fighter_key, fight_key)`. **Phases 0/1a/1b/
2/3a/3b** (committed slice 0–3a; 3b `PARTITION_DEVIATION` scoped but not eng-ready). **Scope = UFC only, NOT
broader MMA** — owner sign-off. ⚠ Same hallucinated-Read failure as NCAAB (fabricated 738-line `sports.py`)
— caught via grep/wc/git.

**NCAAB college basketball (this session)** — two-PR plan at `New Sports/NCAAB-plan.md` (working copy
`~/.claude/plans/nested-drifting-rainbow.md`), hardened over **~8 adversarial review rounds**. March
Madness single-elim; **men's + women's under ONE `SportConfig`** w/ Men/Women division split (tennis
ATP/WTA pattern; `app.py:245` division radio already generic). **Prefix + `family_fn` allow-list, NO
`exact_series`** (MLB/NFL convention): `series_prefixes=("KXMARMAD","KXWMARMAD")`; winner
`KXMARMAD`/`KXWMARMAD`, round `KXMARMADROUND`/`KXWMARMADROUND` = ONE series w/ many event/market tickers
(`R32/R16/R8/F4/T2`) → `stage_fn` parses the **market ticker** (soccer-style exception). Ladder **Reach
R32 ⊇ R16 ⊇ R8 ⊇ Semifinals ⊇ Championship Game ⊇ Win Championship** (`T2`→Reach Championship Game ≠
winner→Win Championship; no phantom R64/First Four). Identity `custom_strike.basketball_team`. Draw-free
→ `game_mece_by_shape=True` (no NFL rule-proof). **PR1** = futures+round ladder (games UNKNOWN); **PR2** =
`KXNCAAMBGAME`/`KXNCAAWBGAME` per-game dutch books after a fixture gate proves two-team moneyline shape.
**Shares the cross-sport foundation** (`label_fn`, per-sport category dispatch, `non_other_families`
Other-fetch, season-aware `tournament_of`+`_two_digit_year`, `game_mece_by_shape`, `settlement_caveat`)
with MLB/NFL — whichever lands first introduces it (**Q3 merge order**). **NCAA-specific:** sub-cent
longshot futures (`to_cents("0.0010")→0¢`) → treat positive sub-cent as `None` + `quote_quality=
"Sub-cent"` added to no-firm-quote exclusions in consistency+dutchbook (open owner **Q1**; or a finer
pricing unit as a larger separate effort); exclude `KXMAKEMARMAD`(→UNKNOWN, `KXMAKE…` stem)/`KXNCAAWB`/
win-totals/conference/seed/region props. **Process note:** two early file reads were **hallucinated**
(a 738-line `sports.py` w/ golf/soccer/`exact_series`); a disk re-verify (only tennis/NBA/WNBA, no
`exact_series`) corrected course onto the prefix convention. **⚠ Plan targets the stale
`feat/round-parser-fix` checkout — rebase onto origin/main (golf/soccer + `settlement_caveat` + category
dispatch already merged) and reuse.** Open: **Q1** sub-cent, **Q2** season-key text (`"NCAA 2027 (M)"` vs
`"NCAA 2026-27 (M)"`), **Q3** merge order.

**NHL (prior session)** — full plan at `New Sports/NHL-plan.md` (working copy
`~/.claude/plans/mutable-gathering-kettle.md`), hardened over **six review rounds + a live Kalshi probe**
(evolution in `note-20260604-nhl-plan.md`). NBA-shape ladder **Reach Playoffs (`KXNHLPLAYOFF`) ⊇ Win
Conference (`KXNHLEAST/WEST`) ⊇ Win Stanley Cup (`KXNHL`)**; identity `custom_strike.hockey_team`; prefix
`KXNHL` (no collision, no `exact_series`); `match_family="match"` → `KXNHLSERIES`/`KXNHLGAME` 2-market
MECE dutch books. Live probe pinned `KXNHLSERIES` rounds = only "1st/2nd Round" (text in title+rules,
ticker `Rn`); no Conf-Final/Cup-Final series wording (championship = the `KXNHL` field) → series
match-alignment safely unhit, **wrong `FIN`/`CF` ticker fallback dropped**. **Two PRs:** PR1 = per-sport
category dispatch (`consistency.py:566-567`, the empty-dashboard blocker), PR2 = register NHL +
**season-aware `tournament_of`** (new `_season_token`, fixes cross-season false-inconsistency, IMPLEMENTED
not xfail+doc) + **dutchbook same-series guard**; optional PR3 = sport-aware labels. **⚠ On origin/main the
category dispatch is ALREADY FIXED (golf merge) → PR 1 likely MOOT, NHL collapses to one PR**; build on the
existing caveat/label infra.

**NFL (this session)** — full plan at `New Sports/NFL-plan.md` (working copy
`~/.claude/plans/streamed-sniffing-bird.md`), hardened over **nine review rounds**. NBA-style futures
ladder **Reach Playoffs (`KXNFLPLAYOFF`) ⊇ Win Conference (`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`) ⊇ Win Super
Bowl (`KXSB`)**; identity `custom_strike.football_team`; `KXSB` = winner ticker (not `KXNFL`-prefixed);
single-elim → `match_family=""` (head-to-head only in `game` family `KXNFLGAME`); season-qualified
`tournament_of`. Divisions deferred (`other`, unchecked branch). **NFL is the first TIE-settled sport**:
`KXNFLGAME` ties settle **50/50**, a same-event fixed-sum payout NOT provable by shape → new
`game_mece_by_shape` flag (NFL=False) + `dutchbook._proves_fixed_sum` rule-proof (basis tie_half/
no_tie_winner; both legs same basis or skip; skipped→`_diag`/`api.ScanResult`) gating game-book emission;
new `label_fn` for exact labels. **Reconcile with the MLB plan AND with the already-merged
`settlement_caveat` infra** — NFL's rule-proof is the more rigorous shared design; build it on top of the
existing field rather than recreating it.

**Three older sports also planned-not-started here: MLB (7th, newest), SOCCER / 2026 World Cup
(6th), and GOLF (5th).**

**MLB (7th) — ✅ BUILT & MERGED 2026-06-05 (PR #87, merged into `main`).** Plan rewritten to **rev-2
single-PR** (`New Sports/MLB-plan.md`) then implemented. NBA-style ladder **Reach Playoffs ⊇ Win League
(AL/NL pennant) ⊇ Win World Series**; identity `custom_strike.baseball_team`; grouping via event-level
`competition="Pro Baseball"`; `KXMLBGAME` per-game dutch books (inherits the family-keyed
`settlement_caveat`); `KXMLBSERIES` excluded (regular-season can tie 2-2 → not MECE); allow-list scope, no
`exact_series`. Branch `feat/mlb-sport` (`1b2bf9d`), `tests/test_mlb.py` (21), 514 pass / ruff clean /
headless boots 200. Details + reusable cross-sport decisions in `note-20260605-mlb-built.md`. (The old
2-PR plan and `note-20260604-mlb-plan.md` are superseded — PR2's `settlement_caveat` plumbing was already
on `main`.) Live Kalshi market facts in the plan flagged INDICATIVE — re-verify live.

**Soccer (this session)** — comprehensive 3-PR plan at `Concurrent Plans/soccer-world-cup-plan.md`
(working copy `~/.claude/plans/optimized-forging-octopus.md`), refined over **six live-API-grounded audit
rounds**. Acts on seed **S1**. This is the sport that finally forces the **n-outcome MECE / dutch-book**
work the topic deferred from day one — `KXWCGAME` group games are **3-way** (Home/Away/Tie). Shape:
- **PR 0** (gating, no code): fixtures + settlement verification — confirm knockout-game shape (2-way vs
  3-way) + the exact draw-excluded rule phrase, pin the D2 reject-token list, verify nested-payload
  completeness, confirm the outright-winner ticker (not yet live).
- **PR 1**: register `soccer` `SportConfig` (identity `custom_strike.soccer_team`; reach-stage ladder
  `Reach R32 ⊇ R16 ⊇ QF ⊇ SF ⊇ Final ⊇ Win` built from **`KXWCROUND`**) + participant typing + minimal
  consumer-gating. **`KXWCSTAGE` excluded** (categorical region furthest-stage); **`KXWCGAME` is
  dutch-only, never laddered**.
- **PR 2**: generalize the dutch-book detector to **n-outcome** (overround threshold `(n−1)·100`) behind
  a first-class `MeceProof` object + a `legs` schema migration (scanner/api/lifecycle/store/app/webui).
Reuses golf's **`exact_series`** ownership field. Two reversals locked: no per-team elimination heuristic
(unsound on `status="open"`); `is_participant` (entity typing) is **decoupled** from family-based
opportunity routing.

---

**Golf (5th sport) is planned, not started — no code written.** A comprehensive plan is saved at
`Concurrent Plans/golf-simple-contracts-plan.md` (working copy: `~/.claude/plans/audit-critical-issues-
prefix-squishy-kettle.md`). Golf = a "simple" finishing-position containment ladder
**Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win** over the 4 exact Kalshi PGA-style series
(`KXPGATOP20/10/5` + `KXPGATOUR`).

**Key correction this session:** adding golf is NOT a pure config drop (unlike NBA/WNBA). It needs **2
real engine changes**: (1) a new **`exact_series`** ownership field on `SportConfig` (prefix `startswith`
is unsafe — `KXPGA*` would grab props / round-finishers `KXPGAR1TOP5` / `KXPGAH2H` that share the same
`golf_competitor` + competition); (2) per-row category dispatch in `consistency._row` (currently
hardcoded to tennis `data.CATEGORY`). Both audited in detail (Appendix A of the plan).

**Next action:** Step 0 **live discovery before any code** — confirm the 4 exact tickers, that all 4
series carry an **identical per-tournament `competition` string** (the #1 grouping risk), and the
`custom_strike.golf_competitor` identity field. Then Step 1 (engine: `exact_series`) → Step 3 (register
`GOLF`) → tests → verify (`python -m streamlit`, `verify_sport.py golf`) → PR.

(The deep per-round tennis ladder — briefly planned here as `m4` — was relocated to the
`full-tennis-coverage` topic on 2026-06-03.)

**Three sports built: tennis + NBA + WNBA**, all off one engine — adding a sport is a `SportConfig` drop
with zero engine changes. ⚠ **Merge state (corrected 2026-06-03):** #23/#25/#26 are on `main` (tennis +
NBA 3-rung + UI); **WNBA #27 merged into `feat/nba-ladder-depth`, NOT `main`** — WNBA is not yet on main.
Land it via a `feat/nba-ladder-depth → main` PR. 128 tests on the WNBA branch (136 on the m1 branch).

- M1 (engine) #23, M2 (UI) #25, NBA 3-rung #26, WNBA 4-rung #27 — **all merged** to `main`.
- NBA ladder: Reach Playoffs ⊇ Win Conference ⊇ Win Championship. WNBA ladder: Reach Playoffs ⊇ Reach
  Semifinals ⊇ Reach Finals ⊇ Win Championship (single bracket; conferences defunct).
- Tennis ladder TODAY: Reach Semifinal ⊇ Reach Final ⊇ Win Tournament (the cap m4 deepens). Live FO 2026
  confirms Kalshi lists advance markets only at SF/Final — m4 uses the match contract to reach deeper.

## Possible next moves

- ~~Implement NFL~~ **✅ DONE — PR #128 MERGED to `main`.**
- ~~Implement Esports~~ **✅ DONE — PR #129 MERGED to `main`.** Optional v2 (named in Current Position):
  qualifier ladders, opponent labels, tag-aware discovery + excluded-series diagnostics, `/milestones`
  grouping, event-specific majors. Maintain the curated allow-list as esports series churn.
- ~~Implement Motorsport~~ **✅ BUILT — PR1 #104 MERGED; PR2 #105 OPEN (awaiting owner merge).** After
  merge: GDrive doc sync + manual browser check; optional follow-up = dedicated NiceGUI Series filter chip
  + (beyond plan) a race-postponement settlement caveat for race-winner fields.
- ~~Implement MLB~~ **✅ DONE — PR #87 MERGED into `main`.** Next: `git checkout main && git pull` (the
  local `feat/mlb-sport` branch can be deleted); GDrive docs refresh (standing rule) + live re-verify the
  indicative market facts.
- **Implement soccer** per the saved plan — starts with **PR 0 live discovery/fixtures** (the hard
  sequencing gate before any PR 2 detector code). ← queued (biggest, unlocks n-outcome MECE)
- **Implement golf v1** per the saved plan (Step 0 live discovery first). ← queued
- ~~Implement NHL~~ **✅ DONE — PR #88 MERGED into `origin/main` (`0aab982`).** Season-aware
  `tournament_of` + dutchbook same-series guard shipped with it (now shared infra). Working plan:
  `~/.claude/plans/floating-sleeping-ripple.md`; `New Sports/NHL-plan.md` rev-5 is stale/superseded.
- **Implement NCAAB** per `New Sports/NCAAB-plan.md` — PR1 futures+round ladder (prefix + `family_fn`
  allow-list, division split, market-ticker round parse, season grouping); PR2 draw-free per-game dutch
  books after a fixture gate. Resolve Q1/Q2/Q3 + rebase onto origin/main (reuse merged label/caveat/
  category infra) first. ← queued (config-drop on the shared foundation)
- The richer **per-round series ladder** (KXNBASERIES / KXWNBASERIES) — deferred (bigger modeling change).
- Pivot to the parked **real-time-opportunity-engine** (WS backend).

## Seeds

- Per-round series containment ladder (most granular; series currently equivalence-only).
- "Basketball" super-sport with NBA/WNBA as a division (alternative to separate configs).
- Max-spread / confidence filters; soccer/draws → dutch-book detector.
