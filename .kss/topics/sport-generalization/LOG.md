---
topic: sport-generalization
created: 2026-06-03
---

# Session Log: sport-generalization

Newest sessions at top. One entry per session, terse.

## 2026-06-10 — World Cup + ITF series-coverage expansion CONVERGED (kickoff eve)
**Milestone:** — (topic-level)
**Did:** Closed the app's biggest blind spot — soccer is exact-owned, so any `KXWC*` not in `_SOCCER_EXACT`
silently → UNKNOWN, never fetched. Plan `~/.claude/plans/jiggly-petting-cake.md` (4 phases). Built as 4
branches off `feat/bounded-loss-phase2` (`dd041c8`, the NEWEST code), **converged into
`feat/convergence-20260610`** with **`feat/ui-trust-fixes` stacked on top (tip `197bf07`)**. All pushed
(backup, no PRs); main frozen; awaiting owner test+merge of the TIP.
- **A `feat/wc-coverage-audit`** — own 9 out-of-scope `KXWC*` as `"other"` (`_SOCCER_KNOWN_OTHER`) so they
  show in audit/Debug but never fetch/detect; new `scripts/audit_series_coverage.py` (pure
  `classify_coverage`). Fractional BESTHOST/FURTHESTADVANCING stay `"other"` (would be a FALSE field book).
- **B `feat/wc-group-bottom`** (stacked on A) — `KXWCGROUPBOTTOM`. **Live FLIP from plan:** probe showed
  `mutually_exclusive=False` ⇒ NOT a flagged field; it's an EXACT cardinality basket via `find_group_baskets`
  (`GroupBasketRule.noun`). The live ME flag flipped False→True kickoff eve (behavior-neutral — basket
  routing is flag-independent; comments updated).
- **C `feat/wc-stage-of-elimination`** (high-risk) — new module **`stage_elim.py`** + family:
  standalone 7-bucket MECE book `EXECUTABLE_STAGE_ELIM_BOOK` (actionable-eligible, fail-closed) + cross-family
  tail-sum `STAGE_ELIM_SYNTHETIC` (REVIEW-ONLY, `SETTLEMENT_CHECK_REQUIRED`). Wired scanner/consistency/glossary.
- **D `feat/tennis-itf`** — own ITF `KXITFWMATCH`/`KXITFMATCH` via tennis `exact_series`; fixed
  `_tennis_division` (ITF women→WTA, men→ATP).
- **Trust fixes** (`feat/ui-trust-fixes`): scan-in-progress indicator + stale-selection clear + CLAUDE.md
  soccer/ITF rows + `HANDOFF-convergence-20260610.md`.
- **Live gates ALL passed** (kickoff eve): `KXMENWORLDCUP-26` sole open outright (`KXWC`/`KXMWORLDCUP` 0
  events — standing follow-up RESOLVED); stage-elim 48 events 7-bucket/1-UUID/ME=True; ITF 92+77 all
  2-market+UUID; scan smoke 93 series 0 failed, 1 actionable stage-elim book, synth 10 review+1 blocked,
  isolation 0 violations. **901 pytest**, ruff clean, boot green. Coverage audit surfaced **65 NEW unowned
  `KXWC*`** for kickoff (props mostly; notable KXWCSCORE / KXWCSPREAD / KXWCTOTAL / KXWCTEAMH2H) — report-only.
**Tasks moved:** — (no active milestone)
**Notes:** memory `wc-itf-series-coverage-expansion.md`, `wc-stage-of-elim-plan.md`

## 2026-06-08 — ESPORTS (10th sport) BUILT & MERGED — PR #129 (c1fe3d5)

**Milestone:** — (topic-level)
**Did:** Planned (4 external-audit rounds) then shipped esports as a clean `SportConfig` drop-in —
`sports.py` + `tests/test_esports.py` + docs only, **no engine edits** (reuses NFL's `game_mece_by_shape`,
default `True`). Grounded in a live throttled Kalshi `/series`+events probe
(`note-20260608-esports-probe.md`): identity `custom_strike.esports_competitor`; `KX*GAME` + `KX*MAP` are
2-way **draw-free** `mutually_exclusive` → `"game"` family → **ungated** dutch books (unlike NFL's
tie-gated games); per-title winner series (`KXCS2`, …) → field overround. **Curated exact-ownership
allow-list** (`series_prefixes=()`); totalmaps/qualifiers/props/MVP/rank/roster/legacy-CSGO/dupes/test/
event-majors → `"other"` (unowned → UNKNOWN, never fetched). Per-title `divisions` (`division_label=
"Title"`). **No containment ladder in v1.** Verified: pytest **663** (+12), ruff clean, `serve.py` boot on
NON-default port (all 200), live `verify_sport.py esports` → 302 contracts (258 game / 44 winner), 0 false
ladder rows; a real `KXCS2GAME` underround surfaced live. NFL (#128) confirmed merged → esports is the
10th sport. v2 deferred: qualifier ladders (+ `qualifier` family / UNKNOWN_RELATIONSHIP emission),
opponent action labels + map caveat wording, tag-aware (`tags=Esports`) discovery + live excluded-series
diagnostics, `/milestones` match grouping, event-specific majors (allow-list is maintained — esports
series churn fast).
**Tasks moved:** — (no active milestone)
**Notes:** `note-20260608-esports-probe.md`, `note-20260608-esports-built.md`

## 2026-06-05 — MOTORSPORT (8th sport, F1/NASCAR/IndyCar/MotoGP) BUILT: 2 PRs (#104 merged, #105 open)

**Milestone:** — (topic-level)
**Did:** Iterated the motorsport plan ~7 revs against owner/Codex findings (big correction: NOT "one
register call" — Streamlit/`app.py` RETIRED on main, NiceGUI-only; division chips moot). Verified every
engine anchor on `origin/main`, then shipped as **two non-stacked PRs**.
**PR1 #104 (MERGED) — engine adapter**, all hooks DEFAULTED (no-op for the 7 sports): `field_families`
(one-winner-field generalization in `dutchbook._is_field_row`), event-only `tournament_key_fn`, per-group
`ladder_fn`, family-derived role-namespaced `player_key` (build_contracts reorder: classify before key),
`IdentityResolver.id_validator` (per-value confidence), variable-tick subpenny guard (integral-cents test
`data.market_has_subpenny`; dutchbook + consistency skip flagged rows). `tests/test_adapter_hooks.py` (17).
**PR2 #105 (OPEN) — register Motorsport** (`feat/motorsport-register` off merged main), grounded in a live
read-only Phase-0 probe. Field sport (`match_family=""`). Identity multi-path racing_competitor(UUID)/
nascar_team(UUID)/Participant(NAME→low via validator); role-namespace driver/constructor/team. family_fn
series-only (each scope owns its series). field_families = winner/race_winner/pole/fastest_lap/constructor/
team (ME=True); Top-N/Podium ME=False → finishing ladder. Kalshi "Games"=race_winner (NOT app `game`).
Per-competition `ladder_fn` (F1/Cup/Truck/IndyCar; MotoGP+O'Reilly none). `tournament_key_fn` =
`competition · session · token` (raw competition_scope NEVER in key — would split a race's rungs). KXRACE
(Ferrari KPI) correctly excluded; H2H deferred→other. `tests/test_motorsport.py` (17) + scanner e2e test.
**Verified:** pytest 592, ruff clean, serve.py boot on NON-default port (/ /healthz /readyz /metrics 200),
+ LIVE e2e engine probe confirming classification, role namespacing (constructor:Red Bull Racing LOW vs
driver UUIDs HIGH), same-race grouping, per-competition ladders w/ real DISPLAY_VIOLATIONs on F1/NASCAR.
Docs → 8 sports.
**Tasks moved:** — (topic-level)
**Notes:** memory `motorsport-sport.md` (full detail); probe scripts in `.codex_tmp/` (untracked)
**Remaining (after #105 merge):** GDrive doc sync (owner); manual browser check; optional NiceGUI Series chip.

## 2026-06-05 — NHL (8th sport) BUILT + MERGED (PR #88)

**Milestone:** — (topic-level; not scoped as a kss milestone)
**Did:** Reconciled the stale rev-5 `New Sports/NHL-plan.md` against the MLB-merged `main` (its "repo
facts" predate golf/soccer/MLB), then **built NHL as ONE PR** off `main` (#87 already merged). Registered
NHL (`sports.py` — NBA-shape ladder Reach Playoffs(`KXNHLPLAYOFF`)⊇Win Conference(`KXNHLEAST`/`WEST`)⊇Win
Championship(`KXNHL`); identity `hockey_team`; `winner_label="Win the Stanley Cup"`; `match_family="match"`
→ `KXNHLSERIES` AND `KXNHLGAME` dutch books; exact-equality allow-list → lookalikes `other`; live series
rounds only "1st/2nd Round" → no rung → `UNKNOWN_RELATIONSHIP`). **Consumed the MLB shared foundation**
(winner_label, advance ladder-node labels, `non_other_families`, "Game time", backlog caveat) — old PR1
(category dispatch) + winner_label/game-time follow-ups were moot. **Two NHL-owned general fixes:**
`data.tournament_of` season-scopes non-tennis keys (`_season_token`→`· <season>`, single wrapper, tennis
unchanged; updated NBA/WNBA/golf/soccer grouping assertions) + `dutchbook._detect_pair` normalized strict
same-`series` guard. Swept docs to 7 sports (README ladder/registered/dutch tables were ALSO missing
golf/soccer/MLB — fixed; per-example TECHNICAL_DOC debt left for a docs-catchup). `tests/test_nhl.py`
(22) + NHL AppTest. **537 pass, ruff clean, py_compile OK, headless 200.** `feat/nhl-sport` (24f1c22) →
**PR #88 MERGED → `origin/main` `0aab982`**. Live Kalshi smoke NOT run (sandbox) — `KXNHLPLAYOFF` spelling
+ `hockey_team` path INDICATIVE, re-verify live.
**Tasks moved:** —
**Notes:** `note-20260605-nhl-built.md`

## 2026-06-05 — MLB (7th sport) BUILT + shipped (PR #87)

**Milestone:** — (topic-level; not scoped as a kss milestone)
**Did:** First rewrote `New Sports/MLB-plan.md` to **rev-2 single-PR** (old 2-PR split was moot — its
`settlement_caveat` plumbing + per-sport category dispatch already shipped via #48–#78). Then **built it**:
registered MLB (`sports.py` — NBA-shape futures ladder Reach Playoffs⊇Win League⊇Win World Series +
`KXMLBGAME` per-game dutch books; identity `baseball_team`; `match_family=""` → `KXMLBSERIES` excluded as
non-MECE; allow-list scope, not the `KXMLB` prefix). Cross-sport engine work: **`SportConfig.winner_label`**
+ sport-aware `data._contract_label` (advance now prefers the ladder node → fixed latent NBA "Reach
Conference"→"Win Conference" and golf "Reach Top 5"→"Top 5"; soccer/tennis unchanged); **`data.non_other_families`**
single-sourced fetch helper wired into `app.py` + `api.fetch_dep`; **`time_kind="Game time"`** for every
`kind=="game"` (NBA/WNBA/soccer/MLB); **backlog `last_settlement_caveat`** through lifecycle→`api.BacklogItem`
→Streamlit table/CSV→NiceGUI (the last caveat gap). New `tests/test_mlb.py` (21). **514 pass, ruff clean,
py_compile clean, headless Streamlit + serve.py boots 200.** Branch `feat/mlb-sport` (1b2bf9d) →
**PR #87 MERGED into `main`** (owner merged same session). Known: `test_app_renders_without_exception` is a pre-existing
`pytest-randomly` ordering flake (passes isolated/stable-order). Live Kalshi smoke NOT run (sandbox) —
plan market facts flagged INDICATIVE, re-verify live before relying on row presence.
**Tasks moved:** —
**Notes:** `note-20260605-mlb-built.md`

## 2026-06-04 — UFC (fight-centric MMA) sport planned

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned UFC over **12 adversarial review rounds**; no code. Saved to `New Sports/UFC-plan.md`
(working copy `~/.claude/plans/frolicking-whistling-scott.md`) + `note-20260604-ufc-plan.md`. **Most
distinctive sport yet** — NOT a config drop. **Two value layers:** dutch-book (`KXUFCFIGHT` 2-way +
`KXUFCMOV` n-way) AND **cross-family containment** (`KXUFCMOV`/`KXUFCVICROUND`⊆FIGHT win; `KXUFCROUNDS`
cumulative ladder). **Engine correction:** "2 markets ⇒ MECE" is false (draw/no-contest) → exhaustiveness
becomes a per-family/event proof. **Two HARD GATES:** (A) identity-join — FIGHT keys by `ufc_competitor`
UUID but MOV/VICROUND carry the fighter as a NAME (`custom_strike.Participant`) → NEW post-flatten
`data.resolve_cross_series_identity(rows,cfg)` (because `build_contracts` is per-series, fetch.py:40, can't
see FIGHT while building MOV); join-fail → `UNKNOWN_RELATIONSHIP`. (B) settlement-basis — FIGHT
ME-but-not-exhaustive → new **`CONDITIONAL_DUTCH_BOOK`** status, overround-only, emits ONLY when basis
proves a non-losing floor. `match_family="match"` (reuse special-casing); `exact_series`-owned (prefix
over-collects props); `default_families`/`dutchbook_families` KEYS→LABELS at fetch boundary; containment
keyed `(fighter_key, fight_key)`. **Phases 0/1a/1b/2/3a/3b** (committed slice 0–3a; 3b not eng-ready).
**Scope = UFC NOT broader MMA** (owner sign-off). **Process:** same hallucinated-Read failure as NCAAB
(fabricated 738-line sports.py) — caught via grep/wc/git; verify on this checkout before trusting Read.
**Tasks moved:** —
**Notes:** `note-20260604-ufc-plan.md`

## 2026-06-04 — NCAAB (college basketball, men's + women's) sport planned

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned NCAAB support over **~8 adversarial review rounds**; no code. Saved to
`New Sports/NCAAB-plan.md` (working copy `~/.claude/plans/nested-drifting-rainbow.md`). March Madness
single-elim bracket; **both divisions under ONE `SportConfig`** w/ Men/Women split (tennis ATP/WTA;
`app.py:245` division radio already generic). **Prefix + `family_fn` allow-list, NO `exact_series`**
(MLB/NFL convention): `series_prefixes=("KXMARMAD","KXWMARMAD")`; round `KXMARMADROUND`/`KXWMARMADROUND`
is ONE series, many event/market tickers (`R32/R16/R8/F4/T2`) → `stage_fn` parses the **market ticker**
(soccer-style exception to NBA series-derived stages). Ladder **Reach R32 ⊇ R16 ⊇ R8 ⊇ Semifinals ⊇
Championship Game ⊇ Win Championship** (no phantom R64/First Four; `T2`→Reach Championship Game distinct
from winner→Win Championship). Draw-free → `game_mece_by_shape=True` (no NFL rule-proof). **Two PRs:**
PR1 futures+round ladder (games UNKNOWN); PR2 `KXNCAAMBGAME`/`KXNCAAWBGAME` per-game dutch books after a
fixture gate. **Shares the cross-sport foundation** (`label_fn`, per-sport category dispatch,
`non_other_families` Other-fetch, season-aware `tournament_of`+`_two_digit_year`, `game_mece_by_shape`,
`settlement_caveat`) with MLB/NFL — whichever lands first introduces it (Q3). **Process note:** two early
file reads were **hallucinated** (a 738-line `sports.py` w/ golf/soccer/`exact_series`); verified against
disk that the checkout has only tennis/NBA/WNBA & no `exact_series` — that correction steered the plan onto
the prefix convention. **NCAA-specific:** sub-cent longshot futures (`to_cents("0.0010")→0¢`) → treat
positive sub-cent as `None` + `quote_quality="Sub-cent"` added to no-firm-quote exclusions in
consistency+dutchbook (open owner **Q1**); excluded `KXMAKEMARMAD`(→UNKNOWN)/`KXNCAAWB`/win-totals/
conference/seed/region props. **⚠ RECONCILE before building:** plan targets the stale
`feat/round-parser-fix` checkout; on `origin/main` golf/soccer + `settlement_caveat` + category dispatch
are already merged — rebase + reuse. Open: Q1 sub-cent, Q2 season-key text, Q3 merge order.
**Tasks moved:** —
**Notes:** —

## 2026-06-04 — NHL (hockey) sport planned; live-grounded, season-grouping fixed

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned NHL support across **six review rounds** + a live Kalshi probe; no code. Saved to
`New Sports/NHL-plan.md` (working copy `~/.claude/plans/mutable-gathering-kettle.md`; full evolution in
`note-20260604-nhl-plan.md`). NBA-shape ladder **Reach Playoffs (`KXNHLPLAYOFF`) ⊇ Win Conference
(`KXNHLEAST/WEST`) ⊇ Win Stanley Cup (`KXNHL`)**; identity `custom_strike.hockey_team`; prefix `KXNHL`
(no collision); `match_family="match"` → `KXNHLSERIES`/`KXNHLGAME` 2-market MECE dutch books. Live probe:
`KXNHLSERIES` rounds are only "1st/2nd Round" (text in title+rules, ticker `Rn`) — no Conf-Final/Cup-Final
series wording (championship is the `KXNHL` field), so series match-alignment is safely unhit → **killed
the wrong `FIN`/`CF` ticker fallback**. **Two PRs:** PR1 = per-sport category dispatch
(`consistency.py:566-567`, the empty-dashboard blocker); PR2 = register NHL + **season-aware
`tournament_of`** (new `_season_token`, fixes cross-season false-inconsistency — implemented, not
xfail+doc) + **dutchbook same-series guard**. Optional PR3 = sport-aware labels.
**⚠ RECONCILE before building:** plan targets the stale `feat/round-parser-fix` checkout (tennis/NBA/WNBA
only). On **origin/main** the **category dispatch is ALREADY FIXED** (golf merge) → **PR 1 is likely
MOOT, NHL collapses to one PR**; `settlement_caveat`/label/`non_other_families` infra already exists —
build on it, don't recreate. Verify before coding.
**Tasks moved:** —
**Notes:** `note-20260604-nhl-plan.md`

## 2026-06-04 — NFL (8th sport) planned; first TIE-settled sport → rule-proven dutch books

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned "initial NFL support" across **nine review rounds**; no code. Saved to
`New Sports/NFL-plan.md` (working copy `~/.claude/plans/streamed-sniffing-bird.md`). Futures map onto the
NBA-style ladder **Reach Playoffs (`KXNFLPLAYOFF`) ⊇ Win Conference (`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`) ⊇
Win Super Bowl (`KXSB`)**; identity `custom_strike.football_team`; `KXSB` is a winner ticker (not
`KXNFL`-prefixed; `KXSB*` siblings stay UNKNOWN); single-elim → `match_family=""` (head-to-head only in
`game` family `KXNFLGAME`); season-qualified `tournament_of` (`-NN`→"NFL 20NN", else `Unknown·<id>`).
Divisions deferred (`other`; unchecked `Win Division ⊆ Reach Playoffs`). **Crux: NFL is the first
TIE-settled sport** — `KXNFLGAME` ties settle **50/50** (live `rules_secondary`), a same-event fixed-sum
payout set NOT provable by shape. New: `SportConfig.game_mece_by_shape: bool=True` (NFL=False) + NaN-safe
`dutchbook._proves_fixed_sum`→`{proved,basis:tie_half|no_tie_winner,text}` (both legs same basis else skip;
one-finding-per-event preserved; skipped→`_diag` count+details + `api.ScanResult`); durable
**`settlement_caveat`** (48h postponement→fair-market) end-to-end; new `SportConfig.label_fn` for exact
labels (Win Super Bowl / Make playoffs / Win AFC / Win NFC / Beat {opp}).
**⚠ RECONCILE before building:** plan was written against the stale `feat/round-parser-fix` checkout
(only tennis/NBA/WNBA). On **origin/main** the `settlement_caveat` field is **already implemented**
end-to-end (Phase B PRs #58/#59 — UNIFIED_COLUMNS + mappers + store/webui + `BLOCKERS["game_settlement"]`),
and **golf + soccer are already merged** (+ n-outcome MECE detector). So NFL should build ON the existing
`settlement_caveat`/labels infra (don't recreate it); the genuinely-new NFL piece is the
`game_mece_by_shape` + `_proves_fixed_sum` **rule-proof gate** (more rigorous than #59's caveat-only,
non-blocking approach). Rebase the NFL plan onto current origin/main first.
**Tasks moved:** —
**Notes:** — (full plan in `New Sports/NFL-plan.md`)

## 2026-06-04 — MLB (7th sport) planned as TWO PRs; settlement-caveat must be a schema field

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned MLB across **six live-API-grounded review rounds**; no code. MLB futures map cleanly onto
the NBA-style ladder (**Reach Playoffs ⊇ Win League (AL/NL pennant) ⊇ Win World Series**), identity
`custom_strike.baseball_team`, grouping safe via event-level `competition="Pro Baseball"`. **Split into 2
PRs:** PR1 = futures ladder only (`KXMLBGAME`→`other`, no dutch books); PR2 = a durable **`settlement_caveat`
field end-to-end** (`dutchbook→scanner→store→api→webui`) + enable `KXMLBGAME` per-game dutch books. Key
reversals over the rounds: per-game dutch books for baseball are NOT pure-config (games can postpone/suspend
→ settle at last-fair-price, so the "locked/true-arbitrage" framing is wrong — needs a row-level caveat,
not copy); `KXMLBSERIES` excluded (regular-season series can tie 2-2 → 2 markets ≠ MECE); "zero engine
changes" was false (needs sport-aware category labels + sport-aware winner/advance contract labels +
`Other`-fetch fix on both Streamlit & API paths). Note: this checkout has only tennis/NBA/WNBA registered —
golf/soccer plans are NOT merged here.
**Tasks moved:** —
**Notes:** `note-20260604-mlb-plan.md`. Full plan saved at `New Sports/MLB-plan.md` (working copy
`~/.claude/plans/federated-sniffing-goose.md`).

## 2026-06-04 — Soccer / 2026 World Cup (6th sport) planned; n-outcome MECE detector designed

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned soccer (2026 FIFA World Cup) as a new sport across **six live-API-grounded audit
rounds**; no code. Acts on seed **S1**. Live finding: **`KXWCGAME` group games are 3-way MECE
(Home/Away/Tie)** → requires generalizing the dutch-book detector to **n-outcome** (overround threshold
`(n−1)·100`, not 100) — the previously-parked draw/MECE work. Ladder spine = **`KXWCROUND`** (per-team
reach-stage); **`KXWCSTAGE` excluded** (categorical region furthest-stage); identity
`custom_strike.soccer_team` (Tie = constant UUID → synthetic per-event key). Reuses golf's **`exact_series`**
ownership idea. Two design reversals vs earlier rounds: dropped the unsound per-team elimination heuristic
(can't distinguish elimination from a fetch gap on `status="open"`), and **decoupled `is_participant`
(entity typing) from opportunity routing (family-based)**.
**Tasks moved:** —
**Notes:** comprehensive 3-PR plan at `Concurrent Plans/soccer-world-cup-plan.md` (working copy
`~/.claude/plans/optimized-forging-octopus.md`). Gating prerequisite = **PR 0 live discovery/fixtures**:
confirm knockout-game shape (2-way vs 3-way) + the draw-excluded rule phrase, pin the D2 reject-token list,
verify nested-payload completeness, and confirm the outright-winner ticker (not yet live).

## 2026-06-04 — Golf (5th sport) planned: "simple" placement contracts

**Milestone:** — (topic-level; not yet scoped as a kss milestone)
**Did:** Planned golf as a new sport — a finishing-position containment ladder
(Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win) on the 4 Kalshi PGA-style series. Two live-API-grounded audit rounds
incorporated; corrected the "zero engine changes" assumption — golf needs **2 real engine changes**
(new `exact_series` exact-only ownership on `SportConfig` + per-row category dispatch in
`consistency._row`). No code written.
**Tasks moved:** —
**Notes:** comprehensive plan at `Concurrent Plans/golf-simple-contracts-plan.md` (working copy also at
`~/.claude/plans/audit-critical-issues-prefix-squishy-kettle.md`). Gating prerequisite = Step 0 live
discovery (confirm the 4 exact tickers, identical per-tournament `competition` strings across all 4
series, and `custom_strike.golf_competitor` identity).

## 2026-06-03 — Topic created; M1 + M2 shipped; M3 (WNBA) planned

- Scoped the whole topic (plan: `~/.claude/plans/rosy-percolating-frost.md`); chose NBA first (live-Finals,
  draw-free, exercises team identity).
- **M1 (engine, PR #23 — merged):** new `sports.py` abstraction (SportConfig/LadderSpec/IdentityResolver/
  MarketClassification/registry/sport_for_series, UNKNOWN explicit). Repointed data/consistency/kalshi_client.
  NBA registered from live discovery (identity `basketball_team`; Win Conference ⊇ Win Championship; per-game
  excluded). Tennis preserved (zero signature changes). Added `scripts/verify_sport.py`. 117 tests.
- **M2 (UI, PR #24 → M1 branch, then PR #25 → main):** sport selector, conditional division control (Tour
  hidden for NBA), unmapped/non-laddered table + family filter, "theoretical" vs "executable" relabel. NBA
  AppTest + 3 engine edge-cases. 121 tests, ruff clean, headless 200, live smoke both sports (tennis 353 /
  NBA 504 contracts).
- ⚠ Merge state: #23 on main; **#25 still open** (M2 → main). Merge #25 to complete.
- **NBA ladder deepened (PR #26, off main):** 2-rung → **3-rung** Reach Playoffs ⊇ Win Conference ⊇ Win
  Championship (`KXNBAPLAYOFF` new rung). Config-only; advance "stage" derived from the series. 123 tests;
  live comparisons 54→84. Excluded KXNBAECFQUAL (East-only) + play-in (not clean containment).
- **M3 (WNBA) SHIPPED — PR #27** (stacked on #26). Verified single-bracket format (conferences defunct);
  4-rung reach-stage ladder Reach Playoffs ⊇ Reach Semifinals ⊇ Reach Finals ⊇ Win Championship. Pure
  config drop, no engine changes. Identity `basketball_team`; KXWNBA/KXNBA no prefix collision. 128 tests.
  Live (in-season): 228 contracts, 168 per-game excluded, **4 real inconsistencies flagged on active data**.

### End-of-session state (2026-06-03)
- `main` = tennis + NBA(2-rung) + UI (#23, #25 merged). Open stacked PRs: **#26** (NBA 3-rung) → **#27** (WNBA). Merge #26 then #27.
- Three sports off one engine; adding a sport = a `SportConfig` drop. Topic between-milestones.
- All code committed/pushed (branches: feat/sport-abstraction-nba-engine, feat/nba-ui, feat/nba-ladder-depth, feat/wnba).
- Also this session (earlier topics): dashboard-usability m1 (payoff scenarios) shipped #22; revised
  `docs/ROADMAP.md`; verified Kalshi fee/WS facts.
