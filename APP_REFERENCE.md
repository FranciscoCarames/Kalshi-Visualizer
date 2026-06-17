# Kalshi Visualizer — Complete App Reference

> **Purpose of this file.** A single, self-contained reference describing the entire application —
> its goal, domain, architecture, data model, detection logic, configuration, API, UI, conventions,
> and current state. Written to be handed to an LLM (e.g. ChatGPT) as a project file for validating
> plans and brainstorming. Everything needed to reason about the app is here; no other file is required.
>
> **Snapshot date:** 2026-06-17. **Source of truth:** `origin/main` — **PR #151 merged the full prior stack**
> (per-user authentication, the React SPA as the default UI, the audit-remediation fixes, the display-only
> per-market fee estimate, and the Scanner-rename / fees-in-$ / hide-fee-negative UI refinements) into
> `origin/main` on 2026-06-16. The old "`main` is frozen, branches stacked & unmerged" model is **retired** —
> always `git fetch` and branch off `origin/main` (see §14). **Newest code:** branch
> `feat/detector-audit-wave1-2` (off `origin/main`) — the **detector-soundness audit**: Wave 1 (A1–A8
> false-flag / silent-drop fixes), Wave 1b (staleness actionability gate + the fee-negative row-hide, default
> **OFF** per owner pref), and Wave 2 #10 (`KXWCTEAMH2H` recognized-not-detected). pytest **1215**, vitest
> **81**. All other Wave 2 items are live-probe gated (off-season / settlement-unproven) — see `WAVE2_STATUS.md`.
> **Repo:** `Kalshi-Visualizer` (private), default branch `main`, owner FranciscoCarames. **Platform:**
> Windows 11, PowerShell, Python 3.13.

---

## 1. What the app is (one paragraph)

A small, **read-only** trader dashboard (FastAPI app, launched via `serve.py`) over live
[Kalshi](https://kalshi.com) prediction-market data for **10 sports**: tennis (ATP/WTA), NBA, WNBA,
golf, soccer, MLB, NHL, motorsport (F1/NASCAR/IndyCar/MotoGP), NFL, and esports. It surfaces
**executable pricing inconsistencies** across a participant's related contracts (a deeper outcome
must not price above a prerequisite that contains it) and **dutch-book arbitrage** on mutually-exclusive
events — always framed as **buy-only** opportunities (Buy YES / Buy NO, never sell/long/short). Findings
are ranked best-first and split into **Actionable / Review / Blocked** with plain-English reasons for
whatever blocks a trade. A background scan refreshes a SQLite snapshot store under a process-wide rate
throttle; the browser re-reads the latest snapshot on a timer.

**Two UIs, one engine.** The **React "Kalshi Structured Scanner" SPA** (`frontend/`, built to
`frontend/dist`) is the **default UI at `/`**; the legacy **NiceGUI dashboard** is **retained (not
deleted) at `/dashboard`** as a read-only fallback. (The older Streamlit `app.py` was retired.) Both are
read-only views of the same engine — the SPA reads it solely through `GET /api/terminal/feed` (+ thin
`/api/terminal/*` parity views). The whole surface can be put behind **per-user login** (see §11.5).

**Long-term direction:** a real-time, ranked, lifecycle-aware opportunity engine for a small trader group.

### Scope guard — deliberately NOT in the app (do not add unless explicitly asked)
Trading, order placement, conditional-probability / de-vig models, and net-of-fees math are all **out of
scope** *as executable inputs* — i.e. they must never feed the gap / ranking / actionability. (A
**display-only fee ESTIMATE** is now shown — see §7 — but it is exactly that: display-only, never netted
into the gap or ranking.) Adding a **new sport** is in scope (a `SportConfig` drop-in). Non-sport-config
feature work is not assumed. **Per-user authentication is now IN SCOPE** (owner-requested 2026-06) — an
app-level login over the read-only surface, gated behind `AUTH_ENABLED`; see §11.5 / `docs/AUTH.md`. It must
**NOT** alter engine logic.

### Three product zones + the speculative-isolation invariant (product direction)
The dashboard is organized into three zones: **(1) Executable gross** — the strict detector
(Actionable / Review / Blocked), exact-cent, MECE/exhaustiveness-proven, unchanged; **(2) Speculative
candidates** — bounded-loss bets, visible but clearly labeled non-actionable / can-lose-money;
**(3) Derived diagnostics** — peer-relative value, conditional ratios, game-support, wide/stale signals.
**NON-NEGOTIABLE INVARIANT:** all probability / EV / de-vig / fee / depth / relative-value metrics are
**DISPLAY-ONLY** and may sort only inside zones 2–3 — they must NEVER feed `consistency._classify` /
`consistency.bucket_of`, `scanner._rank_key`, or any actionability label. So the de-vig / conditional-prob
scope line above means *never as an executable input*; a guarded, **Uncalibrated** conditional ratio shown
as a diagnostic is allowed. Every speculative-metric change ships an isolation test
(`tests/test_speculative_isolation.py` → `assert_executable_unchanged`).

---

## LLM usage rules

This file is the ChatGPT project source of truth for app reasoning, product decisions, architecture
decisions, and planning unless I upload newer files or provide newer instructions.

Treat this file as a dated snapshot, not as current truth for external facts. When an answer depends on
current Kalshi API behavior, market structure, fees, settlement rules, rate limits, listed markets, sports
schedules, package/library behavior, deployment behavior, or recent events, verify against current official
documentation or live evidence. For Kalshi facts, check https://docs.kalshi.com/llms.txt first when
relevant. If current verification is unavailable, mark the assumption as unverified.

Evaluate ideas from two perspectives:

1. **Architect lens** — correctness, architecture fit, maintainability, testability, layering, regression risk.
2. **Trader lens** — usefulness, actionability, risk/reward, liquidity, fill realism, time sensitivity, and
   whether the signal is better than doing nothing.

Do not treat "not riskless" as equivalent to "not useful." Risk is acceptable when it is visible, bounded,
compensated, and testable.

---

## 2. The two-and-a-half detection families

### 2.1 Layer-consistency (containment) violations — `consistency.py`
A **containment ladder** orders contracts broad → deep; a child (deeper) price must be **≤** its parent
(broader). Example tennis ladder: *Reach Semifinal ⊇ Reach Final ⊇ Win Tournament*. When a deeper outcome
prices above the prerequisite that contains it, that's an inconsistency.

- Framed as two buys: **Buy YES** on the broader/parent leg, **Buy NO** on the deeper/child leg.
- **Executable test:** firm YES bid/ask **and positive order sizes**, compared in **exact integer cents**.
  A child YES bid above the parent YES ask is `EXECUTABLE_VIOLATION` — the **only** "Broken" status.
- **Display test:** compares the display %; a breach is `DISPLAY_VIOLATION` (a "Warning", maybe not tradable).
- **Match-alignment** pairs (e.g. *Quarterfinal win ≡ Reach Semifinal*) are included **only** when the
  round maps confidently, and always carry a `RULE_CHECK_REQUIRED` / `RULE_MISMATCH` flag, because the two
  markets' settlement rules are not auto-verified.
- Findings are called **"executable inconsistencies", NEVER "arbitrage."**
- Unprovable relationships → `UNKNOWN_RELATIONSHIP` (never a violation).

### 2.2 Dutch-book / MECE detector — `dutchbook.py`
A **separate check family**. Covers EVERY outcome of a mutually-exclusive set for under the guaranteed
payout floor, in two directions, **both pairs of buys**:

- **Underround → Buy YES on all legs:** `Σ yes_ask < 100¢` (one outcome wins, pays 100¢).
- **Overround → Buy NO on all legs:** `Σ no_ask < (n−1)·100¢` (every loser's NO pays 100¢; `100 − yes_bid`
  fallback when `no_ask` absent).
- Mutually exclusive (`bid ≤ ask`) → at most one direction fires per event. Exact integer cents.
- Single status: `EXECUTABLE_DUTCH_BOOK`.

**Shapes handled:**
- **2-outcome** — head-to-head match (incl. ITF) / playoff series / single game (floor 100¢).
- **soccer 3-way** — Home/Away/Tie (`KXWCGAME`, via `prove_mece`).
- **winner field** — ≥3 "win" markets (overround-only: MECE but not provably exhaustive, so safe on any
  priceable subset since an untraded winner only pays more; `gap = Σ yes_bid(subset) − 100`).
- **stage-of-elimination book** (`stage_elim.find_stage_elim_books`) — a team's 7 `KXWCSTAGEOFELIM`
  elimination buckets are MECE+exhaustive → a clean n-way book (underround floor 100¢ / overround floor
  (n−1)·100¢). Status `EXECUTABLE_STAGE_ELIM_BOOK`. Fail-closed proof (all 7 buckets, one team UUID).

**Cardinality-floor group baskets** (`dutchbook.find_group_baskets`, status `EXECUTABLE_GROUP_BASKET`) —
NOT a dutch book (the set is not mutually exclusive). Per-group binary markets where the FORMAT fixes a
guaranteed YES/NO settle-count floor: `KXWCGROUPQUAL` (top-2 qualify → ≥2 YES / ≥1 NO, conditional
best-third ceiling) and `KXWCGROUPBOTTOM` (exactly one of 4 finishes bottom → EXACT 1 YES / 3 NO). Live
fact: both are `mutually_exclusive=False` (independent binaries), which is WHY they are baskets, not fields.

**Cross-family tail-sum** (`stage_elim.find_stage_elim_synthetics`, status `STAGE_ELIM_SYNTHETIC`) — a sum
of `KXWCSTAGEOFELIM` buckets replicates an advance rung (Reach Final = lost-Final + Winner; …), priced vs
the direct advance market. Settlement-sensitive → `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, **review-only,
never Actionable** (mirrors the synthetic bundle).

**Tie-capable games (do not regress):** NFL games can tie, so `game_mece_by_shape=False` gates the
`KXNFLGAME` book on `dutchbook._proves_fixed_sum` (exact proof a tie pays $0.50/side → 100¢ floor holds, or
no tie possible). Draw-free sports use the default `game_mece_by_shape=True` (ungated). A per-game
(`KX*GAME`/`KX*MAP`) book carries a **non-blocking** postponement `settlement_caveat` — advisory only,
never changes `tradable_now`/bucket.

**Conservative wording (single-sourced via `glossary.DUTCH_BOOK_BASIS`):** a *gross two-way pricing
discrepancy under normal one-winner settlement* — **never** "riskless" / "locked" / "true arbitrage".

### 2.3 Synthetic exact-score bundle — `synthetic_bundle.py` (the "half" — review-only)
A player wins their match iff one of a MECE set of set-scores occurs (bo5 {3-0,3-1,3-2} / bo3 {2-0,2-1}).
That bundle *replicates* "they win", priced against **two independent hedges** (the match-winner market,
and the advance / win-tournament node the match implies).

- **NOT a dutch book, NOT true arbitrage.** A score ≠ the match-winner: on a retirement the score legs
  settle to Fair Market Price while the hedge settles cleanly. So EVERY finding carries
  `rule_flag="SETTLEMENT_CHECK_REQUIRED"`, `tradable_now="Review rules"`, and is routed **review/blocked,
  NEVER Actionable**.
- Status: `EXECUTABLE_SYNTHETIC_BUNDLE` (grouped "Warning").
- Gated on: format proven from `SportConfig.score_format_fn` (men's Grand Slam bo5; WTA + non-Slam ATP bo3
  — NOT keyed off ATP/WTA alone); exhaustive (found == expected); hedge present + round aligned; firm ask
  per leg. Tennis-only in practice (config defaulted empty for other sports).

### 2.4 Speculative / derived display layer (zones 2–3 — NEVER executable)
These are **opt-in, NEVER-Actionable** families/metrics. They self-assign non-executable buckets and
`exec_gap_c=None` so they can never enter the strict edge rank — see the speculative-isolation invariant in §1.

- **NO-anchored structures — `no_structures.py`** ("Cheap bounded-loss NO fades"). Two tiers:
  **BAND** (`NO_STRUCTURE_BAND`) = Buy NO on the deeper rung + Buy YES on the parent that contains it —
  a defined-risk band paying an extra $1 in the "reaches broader but NOT deeper" window, loss capped at
  `cost − 100¢`; emitted only when `cost ≥ 100` (a `cost < 100` band IS the strict `EXECUTABLE_VIOLATION`
  the consistency checker already owns) and max-loss ≤ `config.NO_STRUCTURE_BAND_MAX_LOSS_C`. **OUTRIGHT**
  (`NO_STRUCTURE_OUTRIGHT`) = a single cheap Buy NO (directional fade watchlist), emitted only when Buy-NO
  cost ≤ `config.NO_STRUCTURE_OUTRIGHT_MAX_C`. Ranked on bounded downside / breakeven, **never** edge or
  arbitrage (a cheap NO is cheap because the market thinks the YES is very likely). Self-assigns
  `bucket="no_structure"`. Pure (imports `consistency`, so NOT pandas-free, but no UI/network).
- **Field-implied de-vig — `probability.py`** (pure, NO UI / NO pandas). Proportional (multiplicative)
  de-vig turning a MECE-ish set of YES prices into normalized field-implied probability **ESTIMATES**
  summing to the survivor-slot count `k` (`field_implied_i = p_i/Σp · k`). **Uncalibrated**, gross,
  top-of-book — NOT fair value, NOT net of fees/depth; the words "fair"/"true" are banned. **Never read by
  executable classification, bucketing, or ranking.** `k` comes from `SportConfig.node_survivors` (tennis
  Reach SF=4 / Reach Final=2 / Win=1; golf Top20/10/5=20/10/5, Win=1; team-sport champ k=1; soccer 3-way
  game k=1). Powers the detail-panel conditional-probability table (`consistency.devig_field_by_node` +
  `webui.viewmodel.conditional_probabilities`, raw P(deeper│parent) ratio shown beside the de-vigged
  estimate) and the bounded-loss likelihood columns.

---

## 3. Multi-sport engine — `sports.py`

One detection engine, swappable data per sport. Each sport is a `SportConfig` bundling: series prefixes
(or an `exact_series` allow-list), a structured `IdentityResolver` (stable competitor UUID → normalized
name fallback), a `MarketClassification` (family + ladder node + eligibility via an **allow-list**
`family_fn`, not a bare prefix), a `LadderSpec` (containment ladder), and labels. `sport_for_series()`
resolves a series ticker to its config, returning an explicit **`UNKNOWN`** sport when unrecognized —
**never a silent tennis default**. Adding a sport = one `register(SportConfig(...))` call.

- `build_contracts` includes **all events for all registered sports**; ladders group by
  **(player_key, tournament)** per sport. Tournament is a **client-side filter**, not a fetch gate.
- `data.tournament_of` **season-scopes** every non-tennis grouping key (`_season_token` → `· <season>`),
  so co-loaded seasons never form a false cross-season ladder (tennis byte-for-byte unchanged). It returns
  a **never-empty** key (cleaned `competition` → winner-ticker → title keyword → `Unknown · <id>`).
- Identity is `custom_strike.<key>`; the display name is `yes_sub_title`.
- `SportConfig.winner_label` gives per-sport winner wording ("Win the World Series" / "Win the Stanley
  Cup" / default "Win the tournament").

### Per-sport table

| Sport | Series ownership | Identity key | match_family | Ladder (broad→deep) / dutch-book shape |
|---|---|---|---|---|
| Tennis 🎾 | `KXATP*`, `KXWTA*` + `exact_series` (`KXITFWMATCH`/`KXITFMATCH` — ITF lower tour) | `tennis_competitor` UUID | `match` | Reach SF ⊇ Reach Final ⊇ Win Tournament; head-to-head matches (incl. ITF — ITF women → WTA, men → ATP) |
| NBA 🏀 | `KXNBA*` | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Win Conference ⊇ Win Championship; `KX*GAME` games |
| WNBA 🏀 | `KXWNBA*` | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Reach SF ⊇ Reach Finals ⊇ Win Championship; games |
| Golf ⛳ | `exact_series` (`KXPGATOP5/10/20`, `KXPGATOUR`) | `golf_competitor` UUID | `""` (no dutch books) | Top20 ⊇ Top10 ⊇ Top5 ⊇ Win; winner field only |
| Soccer ⚽ | `exact_series` (`KXWCGAME`, `KXWCROUND`, `KXWCGROUPQUAL`, `KXWCGROUPWIN`, `KXWCGROUPORDER`, `KXWCGROUPBOTTOM`, `KXWCSTAGEOFELIM`, live outright `KXMENWORLDCUP`; + 9 known-other `KXWC*` owned as `other`) | `soccer_team` UUID | `""` (3-way games) | Reach RO32 (=group qualifier) ⊇ RO16 ⊇ QF ⊇ SF ⊇ Final ⊇ Win the World Cup; 3-way games (Home/Away/Tie) + winner field + group baskets (qualifiers + `KXWCGROUPBOTTOM` 1-YES/3-NO) + `KXWCSTAGEOFELIM` 7-bucket MECE book & review-only cross-family tail-sum |
| MLB ⚾ | `KXMLB*` (allow-list) | `baseball_team` UUID | `""` | Reach Playoffs ⊇ Win League ⊇ Win World Series; `KXMLBGAME` games. `KXMLBSERIES` excluded as non-MECE (can tie 2-2) |
| NHL 🏒 | `KXNHL*` (allow-list) | `hockey_team` UUID | `match` | Reach Playoffs ⊇ Win Conference ⊇ Win Stanley Cup; `KXNHLSERIES` (clean bo7) + `KXNHLGAME` |
| NFL 🏈 | `KXNFL*` (allow-list) + `KXSB` | `football_team` UUID | `""` | Reach Playoffs (`KXNFLPLAYOFF`) ⊇ Win Conference (`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`) ⊇ Win Super Bowl (`KXSB` winner field → overround); `KXNFLGAME` games tie-gated. Props/totals/spreads/division/awards/draft → `other` |
| Motorsport 🏁 | `KXF1`/`KXNASCAR`/`KXINDY`/`KXMOTOGP` | driver/team UUID or constructor NAME (role-namespaced `player_key`) | `""` | **field sport like golf**; one-winner FIELDS → overround; Top-N/Podium → per-race finishing-position ladder |
| Esports 🎮 | `exact_series` (CS2/LoL/Valorant/Dota2/CoD/R6/Overwatch/…) | `esports_competitor` UUID | `""` | **field sport, NO ladder (v1)**; `KX*GAME`+`KX*MAP` 2-way DRAW-FREE → ungated dutch books; per-title winner series → overround |

**Motorsport specifics:** `field_families` (winner/race_winner/pole/fastest_lap/constructor/team) get the
overround; Top-N/Podium → per-competition `ladder_fn`; grouping is per RACE INSTANCE (`tournament_key_fn`
→ `competition · session · token`); `player_key` is role-namespaced so a constructor sharing the driver
UUID path never merges.

**Esports specifics:** curated exact-ownership allow-list (`series_prefixes=()`); `divisions` per title;
total-maps / qualifiers / props / legacy CSGO / dupes / event-majors → `other` (unowned → never fetched).
The allow-list is **maintained** (esports series churn fast). v2 deferred: qualifier ladders, opponent
action labels, tag-aware (`tags=Esports`) discovery, `/milestones` match grouping.

---

## 4. Kalshi API (verified live, 2026)

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market (outcome). Paginate via `cursor` until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `*_size_fp`; volume `volume_fp`, `open_interest_fp`. An
  **empty book is `0.00/1.00`** — never a real 50%.
- **NO-side prices** (`no_bid_dollars`, `no_ask_dollars`) read directly (the "Buy NO" price);
  `no_ask == 1 − yes_bid` on the unified book. There are **no NO-side size fields** — a Buy-NO leg's
  tradable size is `yes_bid_size`; fallback Buy-NO cents = `100 − yes_bid_c` when `no_ask_c` is absent.
- **Market `status`** (`active`/`finalized`/`settled`/…): only `active` is tradable → drives `tradable_now`.
  `get_events` passes `status="open"` so fully closed events are excluded at the API level.
- **Web URL (verified):** `https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`,
  `slug = data._slugify(series.title)`; titles from `/series/<ticker>` (`kalshi_client.get_series_titles`),
  falling back to the series page when missing.
- **Identity:** the stable `custom_strike.*` UUID is the per-sport join key; `yes_sub_title` is the display name.

### Relevant tennis series
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH`/`KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXATPADVANCE`/`KXWTAADVANCE` | reach a stage | `advance` | Stage advancement |
| `KXFOMEN`/`KXFOWOMEN` | win the tournament | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER`/`KXWTASETWINNER` | set winner | `set_winner` | Set winner |
| `KXITFWMATCH`/`KXITFMATCH` | ITF lower-tour match (exact-owned; women→WTA, men→ATP) | `match` | Match result |

Match events are head-to-head (2 markets, `mutually_exclusive`); winner/advance/set/score are single-sided.

---

## 5. Architecture — module map

```
config.py        # BASE_URL, series tickers, thresholds, rate-limit + refresh knobs (see §6)
sports.py        # SportConfig registry + sport_for_series (NO UI imports)
kalshi_client.py # read-only paginated GET, Retry-After/backoff, process-wide throttle, discovery
data.py          # parsing, to_cents/to_float, classify_kind/tour_of, pricing, tournament_of, build_contracts, fmt_time/age/stale
consistency.py   # nodes, representative, expected_nodes, layer_spreads, build_checks (groups [player_key,tournament]),
                 #   buy-only plan + tradable_now + blockers, bucket_of, STATUS_GROUP
dutchbook.py     # find_dutch_books — MECE detector (2-way / soccer n-way / winner field) + find_group_baskets; EXECUTABLE_DUTCH_BOOK / EXECUTABLE_GROUP_BASKET
synthetic_bundle.py # find_synthetic_bundles — N-leg exact-score bundle vs 2 hedges; EXECUTABLE_SYNTHETIC_BUNDLE
stage_elim.py    # WC KXWCSTAGEOFELIM 7-bucket MECE book + review-only cross-family tail-sum; EXECUTABLE_STAGE_ELIM_BOOK / STAGE_ELIM_SYNTHETIC
wc_groups.py     # WC group containment leaf + group-cardinality baskets (qualifiers / bottom / win-group)
exact_order.py / game_support.py # WC qualifier-setup diagnostics (exact-order top-two; 3-game ask-support)
no_structures.py # SPECULATIVE "Cheap NO fades" — NO-anchored BAND / OUTRIGHT structures (bucket=no_structure, never Actionable)
probability.py   # PURE field-implied de-vig (uncalibrated probability estimates); NEVER read by classify/bucket/rank
glossary.py      # GLOSSARY{short,long}, BLOCKERS, *_BASIS, help_for — single-sourced terms
filters.py       # apply_membership / apply_thresholds — the two-pass filter split
viz.py           # payoff_chart_data + ladder_prices (tidy chart frames)
fetch.py         # load_contracts (fetch-by-family) extracted from the old app
scanner.py       # cross-sport unified_opportunities + run_scan (dutch-book + synthetic + containment)
store.py         # SQLite snapshot store (schema v4); NO pandas import
lifecycle.py     # new / changed / recently-actionable diffs over the store
scan_manager.py / scan_scheduler.py / presence.py / ratelimit.py  # singleflight, background loop, viewer gate, limiter
api.py           # FastAPI: /healthz /readyz /opportunities /coverage /metrics /scan /alerts /backlog
                 #   + /api/terminal/* (SPA feed/detail/payoff/ladder/diagnostics/telemetry/orderbook/export)
auth.py          # session cookie (itsdangerous) + deny-by-default gate middleware + /auth router (NO UI/pandas)
auth_store.py    # SQLite credential backbone (auth.db): users + argon2id hashes + device tokens + preferences
manage_users.py  # admin CLI: add/passwd/list/disable/enable/unlock (passwords prompted, never logged)
serve.py         # entrypoint: FastAPI API + React SPA (/) + NiceGUI dashboard (/dashboard) on one app
webui/           # NiceGUI dashboard.py + pure viewmodel.py / diagnostics.py / engine.py / export.py / feed.py
frontend/        # React "Kalshi Structured Scanner" SPA (Vite/TS); built → frontend/dist (gitignored artifact)
scripts/         # build_deploy_repo, check_links, export_glossary, verify_sport, benchmark_scan, verify_e2e
tests/           # pytest: full suite (pure layers + engine + API + viewmodel + headless browser + auth/security)
```

**Purity rule (do not regress):** `sports.py`, `data.py`, `consistency.py`, `dutchbook.py`,
`synthetic_bundle.py`, `stage_elim.py`, `wc_groups.py`, `exact_order.py`, `game_support.py`,
`no_structures.py`, `probability.py`, `glossary.py`, `filters.py`, `viz.py` MUST stay **free of UI imports**
(no `nicegui`, no `streamlit`) — pure logic, independently testable. (`no_structures.py` imports
`consistency` so it is pure in the no-UI/no-network sense, NOT pandas-free; `probability.py` is pure with
no pandas.) `auth.py` / `auth_store.py` are likewise **UI-agnostic** (no `nicegui` / no `pandas`) and read
env only at request boundaries (`config.py` stays import-free).

### Data-flow per scan
1. **Fetch** the enabled contract families' series (`fetch.py` → `data.series_for_families`; family
   toggles are the only control that changes what's fetched). Hosted path `api.fetch_dep()` → core series
   only (`scan_all=False`).
2. **Classify** every market by type (family + stage + ladder node) via its `SportConfig`.
3. **Index** contracts by the participant's stable identity key (UUID, or low-confidence name fallback).
4. **Stamp** each contract with a never-empty `tournament` grouping key (`data.tournament_of`).
5. **Detect** containment violations, dutch books, synthetic bundles; rank; write a snapshot the dashboard reads.

### Fetch-by-family + auto-refresh + rate-limit invariants (do not regress)
- `fetch.py` pulls ONLY the series whose contract family is enabled — family toggles are the only fetch control.
- A process-local `scan_scheduler` runs background scans on a timer (on by default); the browser re-reads
  the latest snapshot on a `ui.timer`.
- Kalshi Basic read ≈ 20 req/s. `kalshi_client._throttle` caps issuance at `MAX_RPS` (15, ~75%); `_get`
  backs off on 429 (honoring `Retry-After`) via `MAX_RETRIES`/`BACKOFF_*`; fan-out `CONCURRENCY` (4).
  **The throttle is PROCESS-WIDE ONLY** — safe for ONE process; N processes each have their own limiter
  (aggregate = `MAX_RPS × N`). Full scan ≈ 49–51 GETs; polling floor ~1–3s (latency-bound). API keys do
  NOT speed public data (only the tier ceiling / WebSockets do).

---

## 6. Configuration — `config.py` (actual values)

**API & network:** `BASE_URL="https://external-api.kalshi.com/trade-api/v2"`,
`USER_AGENT="KalshiVisualizer/0.1 (read-only market data)"`, `REQUEST_TIMEOUT=15s`, `MAX_PAGES=100`.

**Series:** `TENNIS_SERIES_PREFIXES=("KXATP","KXWTA")`;
`DEFAULT_SERIES=["KXATPMATCH","KXWTAMATCH","KXATPADVANCE","KXWTAADVANCE","KXFOMEN","KXFOWOMEN"]`;
`FO_WINNER_TICKERS={KXFOMEN, KXFOWOMEN, KXFOMENSINGLES, KXFOWOMENSINGLES, KXFOPENMENSINGLE, KXFOPENWMENSINGLE}`;
`FO_KEYWORDS=["french open","roland garros","roland-garros"]`; `FO_WINDOW=("2026-05-18","2026-06-09")`
(⚠ year-specific — update for future tournaments).

**Price/edge thresholds:** `SPREAD_REASONABLE=0.20` ($; 20¢ midpoint-trust), `DISPLAY_TOL_C=1`
(layer-consistency noise floor), `NEAR_EDGE_MIN_C=-5` (watchlist band: gaps in [-5,0]).

**Risk-budget (beyond-strict-rule):** `RISK_BUDGET_MAX_LOSS_C=25`, `RISK_BUDGET_DEFAULT_MAX_LOSS_C=5`,
`RISK_BUDGET_DEFAULT_MIN_RATIO_TENTHS=0` (off), `RISK_BUDGET_DEFAULT_MIN_OUTRIGHT_C=0` (off),
`RISK_BUDGET_DEFAULT_MAX_SPREAD_RATIO_HUNDREDTHS=0` (off).

**Near-miss dutch book:** `NEAR_MISS_MAX_OVER_C=5`, `NEAR_MISS_DEFAULT_OVER_C=3`.

**NO-anchored structures (Cheap NO fades — speculative):** `NO_STRUCTURE_BAND_MAX_LOSS_C=40` (widest band
max-loss persisted, ¢), `NO_STRUCTURE_OUTRIGHT_MAX_C=25` (dearest Buy-NO persisted), default UI filters
`NO_STRUCTURE_DEFAULT_MAX_LOSS_C=15` / `NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C=15`.

**World Cup qualifier setups:** `WC_SUPPORT_SCORE_STRONG_C=400` (min 3-game ask-support score),
`WC_QUALIFIER_BAND_C=(35,80)` (qualify YES ask range ¢); exact-order top-two:
`MIN_SPECULATIVE_DISCOUNT_C=5`, `MIN_SPECULATIVE_TOP2_UNITS=5`.

**Rate limiting:** `MAX_RPS=15`, `CONCURRENCY=4`, `MAX_RETRIES=5`, `BACKOFF_BASE=1.0s`, `BACKOFF_MAX=30.0s`.

**Auto-refresh:** `REFRESH_OPTIONS=[60,120,300]`, `REFRESH_DEFAULT_SECONDS=120`, `FULL_SCAN_MIN_INTERVAL=120`,
`REFRESH_TTL=30`, `FRESHNESS_TICK_SECONDS=1`, `STALE_AFTER_SECONDS=300`.

**In-process auto-scan:** `AUTO_SCAN_INTERVAL_OPTIONS=[10,15,30,60,120]`, `AUTO_SCAN_DEFAULT_SECONDS=10`,
`AUTO_SCAN_DEFAULT_ENABLED=True`, `AUTO_SCAN_PAUSE_WHEN_IDLE=True` (env override `AUTO_SCAN_PAUSE_WHEN_IDLE=0`).

**Display/timezone:** `TIMEZONE_DEFAULT="Europe/Lisbon"` (+ UTC/London/Paris/New_York/Chicago/Los_Angeles).

**Snapshot store:** `SNAPSHOT_DB_PATH="snapshots.db"`, `SNAPSHOT_RETENTION_SECONDS=30h`,
`SNAPSHOT_BUSY_TIMEOUT_MS=5000`, `SNAPSHOT_FRAME_RETENTION_N=12`, `SNAPSHOT_FRAME_DB_BUDGET_BYTES≈500MB`,
`VOLATILITY_WINDOW_SECONDS=15min`.

**Lifecycle/backlog:** `BACKLOG_WINDOWS={"15 min","1 hour","4 hours","24 hours","This session"}`,
`BACKLOG_DEFAULT="1 hour"`, `BACKLOG_RETENTION_SECONDS=7 days`,
`BACKLOG_CATEGORY_BY_BUCKET={actionable→actionable, risk_budget→bounded_loss, near_miss→bounded_loss}`,
`ALERT_PERSISTENCE_OPTIONS={"Until next refresh", "5 minutes", "15 minutes"}`.

**FastAPI engine:** `API_HOST="127.0.0.1"`, `API_PORT=8000`, `SCAN_MIN_INTERVAL_SECONDS=8`,
`SCAN_WAIT_TIMEOUT_SECONDS=60`, `SCAN_BUDGET_MAX_SECONDS=120`, `SCAN_BUDGET_MAX_REQUESTS=2000`,
`SCAN_BUDGET_MAX_FAILED_SERIES=20`, `SCAN_BUDGET_COOLDOWN_SECONDS=300`, `SCAN_HTTP_MAX_PER_WINDOW=10`,
`SCAN_HTTP_WINDOW_SECONDS=60`.

**NiceGUI:** `NICEGUI_STORAGE_SECRET_FALLBACK="dev-only-..."`, `UI_POLL_SECONDS=1`, `UI_REFRESH_SECONDS=10`.

**Per-user auth (`auth_store.py` / `auth.py` — see §11.5):** `AUTH_DB_PATH="auth.db"` (separate from the
snapshot store), `AUTH_SESSION_IDLE_SECONDS=12h` (sliding), `AUTH_SESSION_ABSOLUTE_SECONDS=12h` (hard cap),
`AUTH_LOGIN_MAX_PER_WINDOW=5` / `AUTH_LOGIN_WINDOW_SECONDS=60` (per-(ip,username) before 429),
`AUTH_LOCKOUT_THRESHOLD=10` / `AUTH_LOCKOUT_SECONDS=15min`, `AUTH_COOKIE_NAME="kss_session"`,
`AUTH_REMEMBER_COOKIE_NAME="kss_remember"` / `AUTH_REMEMBER_MAX_AGE=30 days`, `AUTH_MAX_CRED_LEN=256`.
**Argon2id** (OWASP minimums): `AUTH_ARGON2_TIME_COST=2`, `AUTH_ARGON2_MEMORY_COST=19456` (KiB = 19 MiB),
`AUTH_ARGON2_PARALLELISM=1`. **Preferences:** `AUTH_PREFS_MAX_BYTES=32768` (32 KiB), `AUTH_PREFS_VERSION=1`,
allow-lists `PREFS_THEMES=(amber,hc)`, `PREFS_LAYOUT_PRESETS=(default,triage,inspect,research,blotterfull)`,
`PREFS_SPLITS`, `PREFS_AUTOREFRESH`, `PREFS_COL_KEYS`, `PREFS_SETTINGS_BOOL`. **Post-login action limits**
`AUTH_ACTION_LIMITS={password:(10,300s), preferences:(60,60s), device:(30,60s)}`.

---

## 7. Pricing model

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE=0.20`), else last trade,
  else blank. A `0.00/1.00` book is "No quote" (never a fake 50%). Every component is surfaced
  (mid / last / bid / ask / spread) so a price is never opaque.
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote / Crossed.
- **All comparison logic in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.
  **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`.
- **Known limits (single-sourced in `glossary.py` "Known limits"):** every edge is **GROSS and
  TOP-OF-BOOK**. **Fees are now ESTIMATED (display-only, never netted into the gap or ranking)** — see the
  fee-estimate block below; **position limits / collateral** and **full-depth execution** remain documented
  but NOT modeled. Treat edges as an upper bound.
- **Fee estimate (DISPLAY-ONLY) — `webui/viewmodel.py` `kalshi_fee_c` / `effective_coeffs` / `net_of_fees`,
  resolved per-leg in `webui/feed.py`:** Kalshi's published formula `fee = ceil(coeff · C · P · (1−P))` per
  fill, where `coeff = base × the market's fee_multiplier` (taker base `0.07`, maker base `0.0175`; config
  `FEE_TAKER_BASE_COEFF` / `FEE_MAKER_BASE_COEFF`). **`fee_multiplier` is a MULTIPLIER, not the coefficient**
  (most markets = 1; live-confirmed sports match/game series are `quadratic_with_maker_fees`, advance series
  plain `quadratic`). Each leg's effective fee resolves **event override → series fee → labeled fallback**:
  the series `fee_type`/`fee_multiplier` ride the `/series/{ticker}` call already made for titles
  (`kalshi_client.get_series_meta`, zero extra requests); event overrides come from ONE bounded, fail-closed
  `/events/fee_changes` sweep (`get_event_fee_overrides`) — the event object does NOT expose them. Both maps
  live in the snapshot `meta` (`fee_rates`, `event_fee_overrides`, `fee_data_status`); no schema bump. The
  feed surfaces **two execution scenarios** — **immediate-fill (taker, the primary number → drives the
  net-negative flag + breakeven)** and a separate, caveated **resting-order (maker)** (fills/queue/edge-decay
  NOT modeled) — plus a per-leg breakdown and a `flat`/unknown leg marked **incomplete, never faked**. It is
  a conservative pre-trade estimate (realized fee also involves centicent rounding, rebates, the fee
  accumulator, fragmentation). Tested in `tests/test_webui.py` (formula vs Kalshi's worked examples
  $1.75/$0.63 taker, $0.44 maker @ mult 1) + the no-rank isolation guard; manual live aid `scripts/verify_fees.py`.

---

## 8. Status & bucket taxonomy

### Statuses (the comparison verdicts)
`CLEAN`, `EXECUTABLE_VIOLATION`, `DISPLAY_VIOLATION`, `WIDE_QUOTE`, `MISSING_QUOTE`, `MISSING_LAYER`,
`QUOTE_SIZE_MISSING`, `UNKNOWN_RELATIONSHIP` (containment); `EXECUTABLE_DUTCH_BOOK` (dutch book);
`EXECUTABLE_GROUP_BASKET` (WC hard-floor group basket — qualifiers + `KXWCGROUPBOTTOM`);
`EXECUTABLE_SYNTHETIC_BUNDLE` (synthetic); `EXECUTABLE_STAGE_ELIM_BOOK` (WC stage-of-elim 7-way book);
`STAGE_ELIM_SYNTHETIC` (WC cross-family tail-sum, review-only);
`RISK_BUDGET_CANDIDATE`, `NEAR_MISS_DUTCH_BOOK` (opt-in beyond-strict);
`EXACT_ORDER_DIAGNOSTIC`, `SPECULATIVE_TOP2_RELATIVE_VALUE`, `GAME_SUPPORT_SIGNAL` (WC qualifier setups);
`NO_STRUCTURE_BAND`, `NO_STRUCTURE_OUTRIGHT` (speculative Cheap NO fades — never Actionable).

**Hard rule:** `EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, sizes > 0) is the ONLY "Broken"
containment status. `DISPLAY_VIOLATION` is "Warning"; a sizeless cross → `QUOTE_SIZE_MISSING`, **unless the
display prices also cross** (then `DISPLAY_VIOLATION` — AUDIT-002). Crossed books (`ask < bid`) → "Crossed",
never executable.

### STATUS_GROUP mapping
```
CLEAN→Clean; EXECUTABLE_VIOLATION/EXECUTABLE_DUTCH_BOOK/EXECUTABLE_GROUP_BASKET/EXECUTABLE_STAGE_ELIM_BOOK→Broken;
EXECUTABLE_SYNTHETIC_BUNDLE/STAGE_ELIM_SYNTHETIC/DISPLAY_VIOLATION/WIDE_QUOTE→Warning;
RISK_BUDGET_CANDIDATE→Risk-budget; NEAR_MISS_DUTCH_BOOK→Watchlist;
EXACT_ORDER_DIAGNOSTIC/SPECULATIVE_TOP2_RELATIVE_VALUE/GAME_SUPPORT_SIGNAL→Qualifier setup;
NO_STRUCTURE_BAND/NO_STRUCTURE_OUTRIGHT→NO fade;
MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING→Missing data; UNKNOWN_RELATIONSHIP→Unknown relationship
```

### Dashboard buckets (`consistency.bucket_of` → `DASHBOARD_BUCKETS`, in priority order)
`actionable` (0) → `review_signal` (1) → `blocked` (2) → `risk_budget` (3) → `near_miss` (4) →
`qualifier_setup` (5) → `no_structure` (6) → `near_edge` (7) → `display_signal` (8) → `wide_signal` (9) →
`data_quality` (10) → `clean` (11).

| Bucket | Meaning |
|---|---|
| `actionable` | firm executable cross, tradable now |
| `review_signal` | settlement-caveated (synthetic bundle / stage-elim tail-sum); review before trading |
| `blocked` | real cross but not tradable (no size / inactive leg) |
| `risk_budget` | containment near-miss, bounded loss, convex upside (opt-in) |
| `near_miss` | dutch-book near-miss, flat-payout watchlist (opt-in) |
| `qualifier_setup` | World Cup diagnostics (exact-order / game-support); review-only |
| `no_structure` | cheap bounded-loss NO fades (BAND / OUTRIGHT); speculative, opt-in, never Actionable |
| `near_edge` | consistent but close to crossing (within `NEAR_EDGE_MIN_C`) |
| `display_signal` / `wide_signal` | wide / very-wide quote; watchlist only |
| `data_quality` | missing quote / layer / size |
| `clean` | no inconsistency |

### Status display labels (UI wording; internal strings unchanged)
`EXECUTABLE_VIOLATION`→"Actionable gross edge"; `DISPLAY_VIOLATION`→"Display inconsistency";
`WIDE_QUOTE`→"Wide quote / watchlist"; `MISSING_QUOTE`→"Missing firm quote";
`QUOTE_SIZE_MISSING`→"Blocked: no size"; `CLEAN`→"Consistent". (No "Potential edge"; "edge" only for a
positive executable gap.)

---

## 9. Buy-only language & action plan (do not regress)

Every opportunity is two BUYS — **Buy YES** broader/parent, **Buy NO** deeper/child — never
"sell"/"long"/"short". `consistency._classify` emits `action_1_*`/`action_2_*` (+ `tradable_now`,
`blockers`, `watchlist_note`); the Buy-NO price is the real `no_ask_c` (fallback `100 − yes_bid_c`).
`tradable_now` is "Yes" only for `EXECUTABLE_VIOLATION` + both legs `active` + no rule flag ("Yes —
rule-dependent" for equivalence). **`WIDE_QUOTE` gets no action.** Blocker/glossary text is single-sourced
from `glossary.py`.

**Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
positive sizes**; a missing display blocks only the display test.

---

## 10. The contract row — `build_contracts` key fields

- **Identity:** `player`, `player_key`, `player_key_source`, `mapping_confidence` ("high" = stable UUID;
  "low" = name fallback), `mapping_reason`.
- **Classification:** `tour`, `kind`, `category`, `contract`, `stage`, `stage_rank`, `opponent`,
  `tournament`, `tournament_source`.
- **Pricing:** `*_pct`, `*_c` cents, `*_size`, `spread_cents`, `quote_quality`, `subpenny`.
- **Other:** `volume`, `open_interest`, `status`, `time_value`/`time_kind`, links (`kalshi_url`, `series`,
  `*_ticker`, `*_title`), `raw_*`, `rules_primary`.

No downstream row without `kind` + confidence. **Group/select by `player_key`, NOT display name**
(`build_checks` on `(player_key, tournament)`) — two same-named players never merge; one player's
tournaments never merge.

---

## 11. REST API — `api.py` (FastAPI)

| Method | Path | Model | Notes |
|---|---|---|---|
| GET | `/healthz` | `{status}` | liveness `{"status":"ok"}` |
| GET | `/readyz` | `ReadyZ` | readiness 200/503: `{status(ready/degraded/not_ready), reason, snapshot_age_seconds, last_scan_status, last_scan_error}` (DB writable + fresh snapshot) |
| GET | `/opportunities` | `list[Opportunity]` | filters `?sport`, `?bucket`, `?status` |
| GET | `/opportunities/{id}` | `Opportunity` | 404 if not in latest snapshot |
| GET | `/coverage` | `Coverage` | scan coverage metadata |
| GET | `/metrics` | `Metrics` | low-cardinality monitoring |
| GET | `/alerts` | `Alerts` | `{new_actionable, blocked_changes}`; `?persistence_s` |
| GET | `/backlog` | `list[BacklogItem]` | recently-actionable (default 1h); `?window_s` |
| GET | `/backlog/events` | `list[BacklogInterval]` | durable 7-day intervals; `?days`, `?category`, `?include_open` |
| POST | `/scan` | `ScanStatus` (202) | non-blocking; `?force`, `?wait`; header `X-Scan-Token`/`X-API-Token` when token env set; HTTP-rate-limited (10/60s → 429) |
| GET | `/scan/status` | `ScanStatus` | poll scan progress |

**SPA feed + parity views (`/api/terminal/*`)** — read-only, denormalized VIEWS of the latest snapshot for
the React SPA; thin adapters over the existing engine/viewmodel/viz/export (never a second engine, never a
re-bucket; parity asserted in `tests/test_feed.py`):

| Method | Path | Model | Notes |
|---|---|---|---|
| GET | `/api/terminal/feed` | dict | the SPA's primary read; `webui.feed.build_feed(store.latest())` + display-only fields (ripeness / conditional / per-market fee ESTIMATE: `fees_taker`/`fees_maker`/`net_edge`/`net_edge_maker`/`fee_breakeven`/`fee_legs`/`fee_source`/`taker_complete`/`maker_complete`, resolved event-override→series→fallback) + `meta` (`defaults`, `fee_rates`, `event_fee_overrides`, `fee_data_status`). Records a presence heartbeat (keeps the idle-gated scan alive while a terminal is open) |
| GET | `/api/terminal/detail` | `TerminalDetail` | per-opportunity detail (trade card / participant detail) |
| GET | `/api/terminal/payoff` | `TerminalPayoff` | payoff-scenario frame |
| GET | `/api/terminal/ladder` | `TerminalLadder` | layer-ladder frame |
| GET | `/api/terminal/diagnostics` | `TerminalDiagnostics` | OPS deep-diagnostics grids (row-capped ~2000) |
| GET | `/api/terminal/telemetry` | `TerminalTelemetry` | market-telemetry / RES panel |
| GET | `/api/terminal/orderbook` | `TerminalOrderbook` | LIVE Kalshi order book (`kalshi_client.get_orderbook`; depth 1..100, ~2s TTL cache, limiter, honest-degrade) |
| POST | `/api/terminal/export` | ZIP | snapshot export bundle (Origin-checked when cookie-authed) |

**Auth router (`/auth/*`, see §11.5):** `POST /auth/login`, `POST /auth/register`, `GET /auth/config`
(public entry points); `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`, `GET`/`PUT
/auth/preferences`, `GET /auth/devices`, `POST /auth/devices/{id}/revoke` (session-required).

**`Opportunity` model fields (full):** `opportunity_id, sport, sport_label, source
(containment|dutch_book|group_basket|synthetic_bundle|stage_elim|exact_order|game_support|no_structure),
name, detail, tournament,
tour, action_1_text, action_2_text, action_1_price_c, action_2_price_c, cost_c, exec_gap_c, exec_min_size,
exec_max_profit_dollars, payout_floor_c, roi_pct, edge_class (strict|risk_budget|near_miss),
worst_case_profit_c, best_case_profit_c, parent_display_c, child_display_c, display_spread_c,
spread_over_parent, spread_over_child, bucket, status, tradable_now, blocked_reason, market_status,
rule_flag, settlement_caveat, relationship_type, ticker_1, ticker_2, url, url_2, legs, n_legs,
participant_key, participant_keys, participant_labels, setup_family (wc_qualifier), setup_type
(qualifier_not_winner|qualifier_yes_basket|qualifier_no_basket|exact_order_top2_bundle|
exact_order_top2_relative_value|game_support_signal), qualifier_vs_top2_premium_c,
synthetic_top_two_cost_c, qualifier_yes_ask_c, ask_support_score_total_c, ask_support_score_per_game_c,
join_confidence, opportunity_class (diagnostic_top2_bundle|speculative_top2_bundle), top2_net_if_top2_c,
top2_loss_if_not_top2_c, top2_max_units, worst_bundle_quote_quality, wide_bundle_leg_count,
comparator_quote_quality`.

**Other models:** `Coverage{meta_present, fetched_at, data_age_seconds, stale, scanned, loaded, failed,
excluded, skipped_no_name, contracts_scanned, checks_tested, kalshi_requests, sport_errors, series_errors}`;
`Metrics{snapshot_id, snapshot_age_seconds, stale, opportunities, actionable, contracts_scanned,
checks_tested, kalshi_requests, scanned_series, failed_series, sport_error_count, scan_status, scan_since,
scan_in_progress_seconds, last_scan_error, viewer_count}`; `BacklogInterval{id, opportunity_id, category,
sport, name, url, first_seen_ts, last_seen_ts, left_ts, duration_s, is_open, last_bucket, last_status,
peak_roi_pct, best_case_profit_c, worst_case_profit_c, last_settlement_caveat, last_legs}`.

**Scan gating:** `POST /scan` requires a constant-time `X-Scan-Token` match when `SCAN_TOKEN` env is set
(legacy gate, independent of `AUTH_ENABLED`); HTTP rate limit 10 req / 60s → 429. When `AUTH_ENABLED` (the
`serve.py` default), the deny-by-default middleware ALSO gates `/scan` and every data route — see §11.5.

---

## 11.5 Authentication, sessions & hardening — `auth.py` / `auth_store.py` / `manage_users.py`

Per-user login over the read-only surface, for a **loopback + trusted-LAN** deployment. The protected asset
is the **data + scan controls**, not the public JS bundle. Everything is **gated behind `AUTH_ENABLED`**,
read from the env per-request: unset → pass-through (legacy open behaviour + the `SCAN_TOKEN`-only gate,
used by the test suite); `1` → deny-by-default, login required. **`python serve.py` is the supported secure
entrypoint**: `apply_runtime_defaults()` `setdefault`s **`AUTH_ENABLED=1`** and **`AUTH_ALLOW_SIGNUP=1`** at
startup (NOT at module import, so `import api` / `pytest` stay open-by-default). Opt out with
`AUTH_ENABLED=0` / `AUTH_ALLOW_SIGNUP=0`. Full doc: `docs/AUTH.md`. **The engine logic is untouched.**

**The gate (`auth.gate_and_harden`, one HTTP middleware):** deny-by-default; `auth.is_public()` is the only
allowlist. A dependency can't reach the StaticFiles SPA bundle or the NiceGUI sub-app, so a single
middleware covers them all. It also stamps **security headers** (`X-Content-Type-Options`,
`Referrer-Policy`, `X-Frame-Options: DENY`, `CSP frame-ancestors 'none'`, `Cache-Control: no-store` on data)
and **hides `/docs` `/redoc` `/openapi.json`** (404) when auth-on and not `APP_DEV=1`. `TrustedHostMiddleware`
applies `APP_ALLOWED_HOSTS` (default `*`).

| Surface | Access |
|---|---|
| `/`, `/index.html`, `/terminal/*`, `/assets/*`, `/static/*`, `/healthz`, `/favicon.ico` | **public** (SPA shell + login screen — no data/secrets) |
| `POST /auth/login`, `POST /auth/register`, `GET /auth/config` | **public** (entry points) |
| `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`, `GET/PUT /auth/preferences`, `GET /auth/devices`, `POST /auth/devices/{id}/revoke` | **session-required** (user-only → a machine token gets **403**) |
| `/opportunities(/{id})`, `/coverage`, `/metrics`, `/readyz`, `/scan(/status)`, `/alerts`, `/backlog(/events)`, all `/api/terminal/*` | **gated** (session OR machine token) |
| NiceGUI `/dashboard*` | **gated** (anon HTML nav → 303 redirect to `/`) |
| `/docs`, `/redoc`, `/openapi.json` | **disabled** (404) when auth-on & not `APP_DEV=1` |

- **Sessions:** signed `kss_session` cookie via `itsdangerous` (NOT Starlette `SessionMiddleware` — would
  collide with NiceGUI's); `httponly`, `SameSite=Strict`, `Secure` when `APP_TLS=1`/`TRUST_PROXY=1`. 12h
  idle (slides) + 12h absolute cap. **Real revocation:** every gated request reloads the user row; disabling
  a user or changing a password bumps `session_epoch`, instantly invalidating all their cookies + tokens.
- **Remember-me** (`kss_remember`, opt-in): DB-backed **rotating** token (OWASP selector+validator,
  single-use; a replay revokes the whole family). Issued **only when the cookie can be `Secure`** (or
  `AUTH_REMEMBER_ENABLED=1`). Managed from the SPA "trusted devices" panel.
- **Machine token** (`X-API-Token`, legacy `SCAN_TOKEN` still honored): reaches DATA routes (constant-time
  compare, CSRF-immune, skips the Origin check) but is **403** on user-only `/auth/*` endpoints.
- **Login defenses:** generic `401 "Invalid username or password"` (no enumeration) with a dummy argon2
  verify on the unknown-user path; rate-limited by (ip, username) **before** argon2; temporary 15-min
  lockout. Passwords hashed with **argon2id** (params pinned in `config.py`, opportunistic rehash on login).
- **CSRF:** `SameSite=Strict` + an Origin/Referer host check on cookie-authenticated state-changers (`POST
  /scan`, `/api/terminal/export`, the `/auth/*` writes). No CORS until/unless the SPA goes cross-origin.
- **Self-registration** (`AUTH_ALLOW_SIGNUP`, default ON under `serve.py`): `POST /auth/register` validates
  username (3–32 chars, `[A-Za-z0-9._-]`) + password strength, rejects a taken name (409 — registration is
  enumerable, login is not), logs the user straight in. Close it (`=0`) for admin-created accounts only.
- **Per-user profiles:** each account stores a private versioned-envelope profile — theme, settings,
  shown/ordered columns, band thresholds, the bounded-loss split, the layout preset — server-side in
  `auth.db`, restored on login (follows the account across devices). Identity is the cookie — **no `user_id`
  parameter anywhere**, so a user can only read/write their own row (proven by `tests/test_security_regression.py`).
  Transient *filters* are deliberately NOT saved. Server-sanitized + size-capped (`AUTH_PREFS_MAX_BYTES`).

**`auth_store.py` (`auth.db`, separate SQLite file):** `users` (argon2id `pw_hash`, `disabled`,
`session_epoch`, lockout counters, `force_pw_change`), `device_tokens` (rotating remember-me), `preferences`
(per-user JSON envelope). Migration **fails hard** rather than dropping a table (vs the snapshot store, which
self-resets); `PRAGMA foreign_keys=ON` cascades a deleted user to tokens + prefs. `auth.db` is gitignored
and excluded from the ZIP export.

**`manage_users.py` CLI:** `add` / `passwd` / `list` / `disable` / `enable` / `unlock` (passwords prompted,
never echoed/logged). One-shot first-admin seed via `APP_ADMIN_USER` + `APP_ADMIN_PASSWORD` (only when zero
users exist; never overwrites; rejects weak passwords) — applied by `serve.seed_admin_from_env()`.

**Deps:** `argon2-cffi` + `itsdangerous` (runtime); advisory `pip-audit` + `bandit` in `requirements-dev.txt`.

---

## 12. Cross-sport scanner — `scanner.py`

- `unified_opportunities(fetch_fn, *, store_writer=None, fetched_at=None, frames_out=None)` → `(pd.DataFrame, list[dict])`.
- `run_scan(fetch_fn, *, fetched_at=None, request_count=None)` → `(unified_df, coverage, frames)` — service entry.
- `UNIFIED_COLUMNS` is the stable ~75-column schema feeding the store + API (identity, action plan, edge
  metrics, bucket/status, tickers/urls, N-leg `legs`/`n_legs`, beyond-strict columns, WC-qualifier columns).
- `BUCKET_PRIORITY` orders the buckets (see §8).

---

## 13. Snapshot store — `store.py` (schema v4, no pandas)

**Tables:**
- `snapshots(id PK, fetched_at TEXT, fetched_ts REAL, meta TEXT)` — one per refresh.
- `opportunities(snapshot_id FK, opportunity_id, relationship_type, bucket, status, blocked_reason, data
  TEXT)` — full row as JSON.
- `snapshot_frames(snapshot_id FK, sport, frame_type, schema_version, rows_json, row_count)` — v3 per-sport
  evidence (contracts / checks / dutchbook).
- `backlog_intervals(id PK, opportunity_id, category, sport, name, url, first_seen_ts, last_seen_ts,
  left_ts, last_bucket, last_status, peak_roi_pct, best_case_profit_c, worst_case_profit_c,
  last_settlement_caveat, last_legs, data TEXT)` — v4 durable 7-day lifecycle.

**Public API:** `write_snapshot`, `latest`, `latest_two` (oldest→newest for diffing), `snapshots_since`,
`latest_snapshot_id`, `actionable_history_since`, `latest_rows_by_id`, `backlog_intervals`, `load_frames`,
`frame_status` (`present`/`expired`/`absent`), `db_writable` (migration-free probe for `/readyz`).

`lifecycle.py` diffs the store for new / changed / recently-actionable (powers `/alerts` + `/backlog`).

---

## 14. UI — React SPA (default) + NiceGUI dashboard (fallback)

Both UIs are mounted on the one FastAPI app by `serve.py` and are **read-only views of the same engine**.
Registration order is load-bearing (Starlette resolves in order, the `/` catch-all must be LAST): API
routes → NiceGUI → SPA at `/terminal` → SPA at `/`.

### 14.1 React "Kalshi Structured Scanner" SPA — `frontend/` (DEFAULT UI at `/`)
A client-side Vite/TypeScript SPA (built to `frontend/dist`, a gitignored artifact; an unbuilt tree leaves
`/` to NiceGUI and never breaks boot). It reads the engine **only** through `GET /api/terminal/feed` (+ the
thin `/api/terminal/*` parity views) — never a second engine, never a re-bucket. Key source
(`frontend/src/`): `App.tsx` (shell + section bars), `AuthGate.tsx` (login / register / 401 boot gate),
`Workspace.tsx`, `Blotter.tsx` (ranked tables — the panel is now LABELED **"SCANNER"**; the component/file/
ids keep the `blotter` name), `Inspector.tsx` (trade card + participant detail + the two-scenario fee
block), `Ladder.tsx` (LIVE order book), `Charts.tsx` (numeric ladder/payoff tables), `Palette.tsx`,
`MultiSelect.tsx`, `SidePanels.tsx`, `Keys.tsx`; pure helpers `feed.ts`, `filters.ts`, `sort.ts`,
`columns.ts`, `prefs.ts`, `auth.ts`, `alerts.ts`, `diff.ts`, `url.ts`, `detail.ts`, `csv.ts`, `http.ts`,
`context.tsx` (each with a `*.test.ts` under `vitest`). Server-side display VIEW logic lives in
`webui/feed.py` (`build_feed`) + the `/api/terminal/*` handlers in `api.py`. Per-user prefs (theme, columns,
band thresholds, layout preset, settings incl. `hideNetNegExec`) round-trip through `GET/PUT
/auth/preferences` when auth is on (server allow-list `config.PREFS_SETTINGS_BOOL`).

**Fee display & filter (display-only; see §7 for the math):** `Est. fees $` and `Est. net edge $` (per-unit)
render in DOLLARS via a shared `cmoney`/`centsToDollars` formatter (`columns.ts`), consistent with
`Max gross profit $`; the Inspector shows the immediate-fill (taker) and resting-order (maker) fee scenarios
in dollars + a per-leg breakdown + a taker breakeven. An **opt-in** SETTINGS toggle **"Hide fee-negative
(taker est.)"** (`hideNetNegExec`, default OFF) hides executable rows whose taker net-of-fees estimate is
negative — a pure view filter (`filters.hiddenByFee`, used by both the `rows` memo and `count()` so tile/tab
counts drop when on) keyed off the feed's `net_negative` flag (actionable-only, complete-only; Review/Blocked
+ incomplete-fee rows are never hidden). When on, an honest **"N hidden by fee filter · show"** chip keeps a
dropped ACTIONABLE count from implying zero opportunities. Nothing is re-bucketed; the row stays in the feed.

### 14.2 NiceGUI dashboard — `webui/` (RETAINED at `/dashboard`)
The legacy dashboard, retained as a read-only fallback. `viewmodel.py` + `diagnostics.py` are the pure
cores; `engine.py` drives scans (`run_scan_now`); `export.py` builds the ZIP/manifest; `feed.py` builds the
SPA feed view.

**Layout (top → bottom):** scope/freshness banner (snapshot age, staleness, poll status); membership
filters (Sport / Tournament / Participant); threshold filters (Min size / Active-only / Review / Blocked);
the ranked **Actionable** table and **Review Required** (both now **collapsible** sections, PR #149,
best→worst); **Blocked** (toggle-gated); opt-in **Risk-budget**, **Near-miss**, **Qualifier-setups**, and
**Cheap NO fades** (`no_structure`) sections — the watch-only sections were reordered (PR #148) and
**Cheap NO fades is now ON by default**, sitting below the Bounded-Loss view; a recently-actionable backlog;
a click-to-open explanation dialog + participant-detail panel; a collapsed Diagnostics & debug expander.
Settings: timezone, long/short wording toggle, text size, auto-scan cadence, manual "Scan now" (force=True).
A `wip/ui-preference-persistence` branch (NOT on `main`) persists per-user UI preferences via
`app.storage.user` — unverified, awaiting owner decision.

**Filter split (critical — do not regress):** `consistency.bucket_of(row)` routes each comparison;
`webui.viewmodel.filter_opps` reuses the two-pass `filters.py` split — **membership**
(sport/tournament/participant/min-volume) narrows **every section**; **thresholds** (min size, quote,
market status) spare **Actionable** but gate the others. Full diagnostics is built from the
**membership-filtered** set (NOT the thresholded set) so finalized markets stay visible there.

**`viewmodel.py` key functions:** `filter_opps`, `classify_changes` (up/down/new/returned),
`severity_badges`, `action_plan_summary` (summary/cost/floor/max_units/gross_edge/is_complete),
`opp_row`, `risk_budget_view`/`risk_budget_row`, `near_miss_view`/`near_miss_row`, `leg_rows`,
`order_qualifier_rows`/`qualifier_row`, `backlog_row`, `ts_disp`;
`no_structure_view`/`no_structure_row`/`no_structure_explainer` + `no_fade_ladder`/`no_fade_ladder_view`/
`cascaded_options` (Cheap NO fades, optionally grouped into cascade-scored ladder cards);
`conditional_probabilities` (detail-panel P(deeper│parent) raw + field-implied de-vig);
`ladder_chart_option`/`non_laddered_rows`. `webui.engine.tournament_field` supplies the field prices the
de-vig reads from the latest snapshot.

**Mapping audit (detail panel):** per-participant **expected-vs-found** progression ladder
(`consistency.expected_nodes` makes a missing layer explicit) + JSON-snapshot + CSV export; raw
stage-ladder spreads (`consistency.layer_spreads`: per-adjacent-pair `spread_pct` pp + `spread_cents`,
worst-leg `quote` column, NaN-safe); a **conditional-probability table** showing raw P(deeper│parent)
price ratios beside field-implied de-vig estimates (display-only, **Uncalibrated**).

---

## 15. Hosting / deployment — `serve.py` + `docs/DEPLOYMENT.md`

`serve.py` serves the API + SPA + dashboard on **one app** (default loopback `127.0.0.1:8000`).
**Env vars:** `API_HOST`, `API_PORT`, `SNAPSHOT_DB_PATH` (parent dir must exist), `NICEGUI_STORAGE_SECRET`,
`ALLOW_DEV_STORAGE_SECRET_ON_LAN`, `WEB_CONCURRENCY`, `AUTO_SCAN_PAUSE_WHEN_IDLE`, `SCAN_TOKEN`; **and the
auth set** (§11.5): `AUTH_ENABLED`, `AUTH_ALLOW_SIGNUP`, `APP_SESSION_SECRET`, `AUTH_DB_PATH`,
`APP_ADMIN_USER`/`APP_ADMIN_PASSWORD`, `APP_API_TOKEN`, `APP_TLS`, `TRUST_PROXY`, `AUTH_REMEMBER_ENABLED`,
`APP_ALLOWED_HOSTS`, `APP_DEV`.

**Bind safety (`serve.bind_safety`, pure/testable):**
- **No-auth dashboard exposure** — a non-loopback bind (0.0.0.0 / LAN IP) without `NICEGUI_STORAGE_SECRET`
  is **fatal** (the NiceGUI cookie is signed with it; the dev fallback is public) unless
  `ALLOW_DEV_STORAGE_SECRET_ON_LAN=1` (downgrades to a loud warn).
- **Auth-mode fail-closed** — when `AUTH_ENABLED` and the bind is non-loopback, startup is **fatal** unless
  ALL of: (1) a real `APP_SESSION_SECRET`/`NICEGUI_STORAGE_SECRET`; (2) ≥1 user account exists; (3) TLS
  (`APP_TLS=1`) or a declared HTTPS-terminating proxy (`TRUST_PROXY=1`) — else the session cookie travels
  cleartext.
- **Multi-worker** — `WEB_CONCURRENCY>1` (or `--workers`) **warns** normally but is **fatal in auth mode**
  (store + throttle + login rate-limiter + session state are all process-local → run ONE worker).

The guard protects `python serve.py`; running `uvicorn api:app` directly bypasses it (and the auth/signup
defaults) — set `AUTH_ENABLED=1` yourself if you do.

`POST /scan` is non-blocking (202) behind a process-local `scan_manager.ScanManager` singleflight (shared
with `webui.run_scan_now` → one upstream fetch); `?wait`/`?force` modify it, `GET /scan/status` polls; the
dashboard "Scan now" is non-force. Deploy artifact: `scripts/build_deploy_repo.py` + `deploy/` systemd
templates. Headless scanning supported (`AUTO_SCAN_PAUSE_WHEN_IDLE=0` keeps scanning with no viewer).

---

## 16. Run & verify

```bash
pip install -r requirements.txt                 # requests, pandas, tzdata, fastapi, uvicorn[standard], pydantic, nicegui (3.12,<4), argon2-cffi, itsdangerous
cd frontend && npm install && npm run build && cd ..   # build the DEFAULT SPA UI → frontend/dist (gitignored)
python serve.py                                 # SPA (/) + NiceGUI dashboard (/dashboard) + REST API (auth ON by default)
pip install -r requirements-dev.txt             # adds pytest, pytest-asyncio, ruff, httpx, pip-audit, bandit
pytest -q                                       # pure layers + in-process engine/API + headless NiceGUI smoke + auth/security
ruff check .                                    # lint  (frontend: cd frontend && npm test  → vitest; npx tsc)
python scripts/verify_e2e.py                    # end-to-end auth + serve smoke (boots serve.py, exercises login/gate/profile)
```

**Verify without a browser:** `pytest -q`; `python -c "import serve, api, webui.dashboard"`; a `serve.py`
boot — `GET /` (SPA when built, else NiceGUI), `/dashboard/`, `/healthz`, `/metrics` → 200, `/readyz` →
`ready`/`degraded`/`not_ready`. Headless NiceGUI smoke is `tests/test_browser.py` (`nicegui.testing`, no
selenium). The SPA's pure helpers are unit-tested under `vitest` (`frontend/src/*.test.ts`). Live Kalshi
calls, `pip`/`npm`, and `git push` need network (otherwise blocked).

**Test suite (`tests/`, 58 files, 1072 tests as of 2026-06-15):** pure data/consistency/dutchbook/
synthetic/stage_elim/probability/no_structures/viz/glossary/filters layers; per-sport
`test_{mlb,nhl,nfl,motorsport,esports,sports}`; engine `test_{scanner,store,lifecycle,scan_manager,
scan_scheduler,ratelimit,presence,read_path_opt}`; API `test_{api,readyz,serve,terminal_endpoints,feed,
client}`; UI `test_{viewmodel,diagnostics,webui,browser,export,filters,qualifier_*,bounded_loss_kind}`;
speculative-isolation `test_speculative_isolation`; World Cup `test_{wc_groups,wc_qualifier_tag,exact_order,
game_support,audit_coverage}`; **auth/security `test_{auth,auth_store,manage_users,routes_deny_by_default,
security_regression}`** (deny-by-default route guard + two-user profile isolation); deploy
`test_build_deploy_repo`. Plus `scripts/verify_e2e.py` (the live end-to-end auth check).

---

## 17. Conventions & gotchas

- **Never `float()` a raw price field** — use `data.to_float` (None-safe) or `data.to_cents` (Decimal, exact).
- **pandas truthiness:** never `row_a or row_b` on DataFrame rows; use explicit `is None` checks. The
  dutch-book detector consumes `df.to_dict("records")` so it is NaN-safe.
- **Empty results are valid** (between rounds → no open events), not errors.
- **Always loop the `cursor`;** `get_paginated` raises if `MAX_PAGES` (100) is hit with a cursor pending
  (no silent truncation).
- **Failed series are surfaced in the Debug expander, never silently dropped** (hard requirement).
- **The running server caches imported modules.** After editing a module while `serve.py` runs, fully stop
  and restart (no auto-reload); for a phantom `ImportError` clear bytecode: `rm -rf __pycache__ tests/__pycache__`.
- A **stale store.latest() snapshot** is the usual cause of "a sport is missing from the dashboard" — a
  rescan fixes it; it is not a bug.
- A stale `serve.py` keeps holding port 8000 (kill by PID via `Get-NetTCPConnection`/`Stop-Process` before
  trusting a boot smoke).
- The FO date window in `config.py` is year-specific — update it for future tournaments.
- The Kalshi **web** site is bot-throttled (429); `data.link_audit` proves link correctness
  deterministically, `scripts/check_links.py` does a best-effort live check from an unthrottled network.
- `.gitignore` covers `.env`, `*.pem`, `.venv`, `__pycache__`, `*.db`, `.claude/`, `.kss/`. Windows
  LF→CRLF warnings on commit are harmless.

---

## 18. Git workflow (strict — owner confirmed)

- **Never commit, push, or merge to `main`.** The owner merges manually.
- **Branch-only delivery (near-term policy, owner 2026-06-09 — supersedes "one PR per change"):** do NOT
  open a PR per change. Implement the **full scope** of a work item across **one or more feature branches**;
  verify (`pytest -q`, `ruff check .`, `serve.py` boot); then the owner **tests manually** and **merges to
  `main` only when satisfied**. `main` stays frozen until then. (Also in CLAUDE.md "Git workflow" +
  docs/AGENT_WORKFLOW.md §0.)
- Branch off the latest `main` — or off the unmerged branch a feature depends on since `main` is frozen
  (state the base in the handoff). Commit messages end with `Co-Authored-By: Claude ...`; a PR body, if one
  is opened for review, ends with the Claude Code footer.

---

## Review and PR protocol summary

For plan reviews, implementation reviews, or PR-readiness reviews, classify risk first:

- **Low** — docs, copy, tests, minor UI layout.
- **Medium** — sport-config additions, filters, exports, viewmodel changes.
- **High** — market-data fetching, pricing, actionability gates, settlement rules, dutch-book logic,
  synthetic bundles, scanner/API pipeline.
- **Critical** — trading, order placement, automated execution, net-of-fees actionability, de-vig models,
  live WebSocket feeds, or other non-read-only behavior (out of scope unless explicitly requested); **and
  any change to the auth layer** (`auth.py` / `auth_store.py` / the gate / session / CSRF / bind guard) —
  in scope and shipped, but critical-risk to review.

For reviews, use this structure:

- Risk class
- Review scope
- Assumptions checked
- Verdict: approve / approve with conditions / reject / needs more evidence
- Blockers
- Major issues
- Minor issues
- Missing tests
- Current-doc checks
- Regression risks
- Final recommendation

Never say "no issues." Say "no blockers found under this review scope" and state remaining uncertainty.

Blockers include:

- false actionable signal;
- wrong opportunity labeling;
- missing MECE / exhaustiveness proof;
- missing quote-size, market-status, or firm-price gate;
- weakened settlement caveat;
- float comparison logic in price paths;
- engine/UI boundary regression;
- failing tests or behavior change without test;
- scope-guard violation.

Before a PR is ready, expected checks are:

- targeted tests for behavior changes, or a written explanation of existing coverage;
- `pytest -q`;
- `ruff check .`;
- `python -c "import serve, api, webui.dashboard"`;
- `python serve.py` smoke on a non-default port;
- conditional deployment smoke if deployment/import graph/build artifact/runtime dependencies changed;
- documentation update when behavior, API assumptions, deployment, user-facing labels, or market logic changed.

---

## 19. Current state & approved next work (2026-06-16)

**Shipped engine (on `main` and every branch):** the engine + 3 detector families over the `SportConfig`
abstraction; 10 sports; the typed FastAPI API + SQLite snapshot store + cross-sport scanner + lifecycle
diffs; office-LAN hosting (`/readyz`, bind safety, in-process auto-scan, deploy-repo builder); a durable
7-day backlog (schema v4); World Cup group markets, the `KXWCSTAGEOFELIM` stage-of-elim book + tail-sum
(`stage_elim.py`), `KXWCGROUPBOTTOM` group basket, ITF tennis coverage, a 5-setup opt-in "Qualifier Setups"
diagnostic section, the bounded-loss likelihood/comparability metrics, the conditional-probability detail
panel (`probability.py`), and the NO-anchored "Cheap NO fades" (`no_structures.py`). The engine logic is
**unchanged** by everything below.

**Newest code — branch `feat/auth-and-hardening` (`4f66524`, pushed to `origin`, awaiting owner test/merge;
`main` is frozen and lags it):** two big additions, neither touching the engine —
- **React "Kalshi Structured Scanner" SPA as the default UI** (`de08b9c` `a148d71` `7f01401` + the
  preceding terminal-spa parity batches): `frontend/` Vite/TS app built to `frontend/dist`, served at `/`,
  reading the engine only through `GET /api/terminal/feed` + the `/api/terminal/*` parity views
  (`webui/feed.py` + the terminal handlers in `api.py`). NiceGUI is **retained at `/dashboard`**. Includes
  data-integrity fixes, the live Kalshi order book (`/api/terminal/orderbook`), numeric ladder/payoff
  tables, and URL/query-param state persistence.
- **Per-user authentication + hardening** (`256000e` → `4f66524`, Phases 1–5 + profiles): `auth_store.py`
  credential backbone (`auth.db`, argon2id, device tokens, preferences), `auth.py` deny-by-default gate
  middleware + session cookie + `/auth` router, `manage_users.py` CLI, the React login/register view +
  account bar + trusted-devices panel, **per-user profiles** (theme/columns/layout via `/auth/preferences`),
  secure defaults (`serve.py` turns auth + signup ON), fail-closed LAN bind guard, and a security
  regression suite. **Auth is ON by default under `python serve.py`** (opt out `AUTH_ENABLED=0`). See §11.5
  / `docs/AUTH.md`. Verified: 1072 pytest green + `scripts/verify_e2e.py`.

**Fee + audit branches that stacked above auth — now ALL MERGED into `origin/main` via PR #151 (2026-06-16);
engine still unchanged:**
- **`fix/fee-and-sort` (`98b5a12`):** audit + stress-test remediation — 3 stacked fix areas
  (security/robustness, perf/lag, fee-aware UI + gross deployable-profit sort). pytest 1092, e2e 42/42.
- **`feat/fee-estimation-v2` (`5239570`, pushed):** the **display-only per-market fee ESTIMATE** — live
  `fee_type`/`fee_multiplier` per series (event override → series → fallback), two execution scenarios
  (taker/maker), per-leg breakdown + breakeven. New `kalshi_client.get_series_meta` /
  `get_event_fee_overrides`; `fee_rates`/`event_fee_overrides`/`fee_data_status` in snapshot `meta` (no
  schema bump). Fees stay display-only (no-rank invariant held). See §7. pytest 1105, e2e 42/42, vitest 51.
- **`feat/scanner-fee-display` (`9c3e44c`, pushed — NEWEST):** UI refinements on the fee work — Blotter panel
  **renamed "SCANNER"** (labels only), **fees + per-unit net edge shown in $** (`cmoney`/`centsToDollars`),
  and an **opt-in "hide fee-negative executables"** toggle (`hideNetNegExec`, default OFF; when on, counts
  drop + a hidden-count chip; added to `config.PREFS_SETTINGS_BOOL` so auth profiles persist it). Formula-vs-schedule
  tests + `scripts/verify_fees.py` live aid. pytest **1107**, vitest **57**, ruff/tsc clean. (See §7 / §14.1.)

**Current branch — `feat/detector-audit-wave1-2` (off `origin/main`):** the detector-soundness audit.
- **Wave 1 (A1–A8) — detector soundness:** kill false flags + silent drops. MECE-phrasing fixes, coverage
  signals, allow-list hardening, and latent-bug fixes across `consistency.py` / `dutchbook.py` / `sports.py`
  / `data.py` / `synthetic_bundle.py`. Two new coverage diagnostics surface in the NiceGUI Diagnostics
  expander: **unmapped advance stages (A6)** (advance contracts mapping to no ladder rung) and **unknown
  motorsport series (A7)** (motorsport-tagged series outside the family allow-list — kept "other" until
  reviewed, so a prop can't false-fire).
- **Wave 1b — trust gates (both UIs):** (1) a **staleness actionability gate** — when the snapshot age
  exceeds `config.STALE_AFTER_SECONDS` (300s, optional per-sport override `STALE_AFTER_SECONDS_BY_SPORT`),
  an otherwise-actionable opportunity's `tradable_now` is downgraded to **"No — stale snapshot"** in the
  ACTIONABILITY field only — `bucket`/`status`/the executable math are untouched (`data.gate_stale_tradability`,
  applied at the live boundary in `api._opps` + `webui.feed.build_feed` with the SAME age so /opportunities ↔
  feed parity holds). (2) The **fee-negative row-hide** default — `hideNetNegExec` (SPA) / `hide_fee_neg_sw`
  (NiceGUI). Wave 1b briefly defaulted it ON; **reverted to default OFF per owner pref** (`61aed4d`) so all
  Actionable rows show by default. Still a taker-basis, display-only declutter that never re-buckets, with a
  hidden-count surface; persisted per-user, so the default only affects new/unsaved users.
- **Wave 2 #10 — `KXWCTEAMH2H` recognized (review-only):** the live probe corrected the plan — it is a
  **3-way** set (`<A> further` / `<B> further` / `Eliminated same stage`), not 2-way, not flagged
  `mutually_exclusive`. Routed as **recognized + "other"** (visible in coverage, never fetched/detected,
  never a false edge). Fixture `tests/fixtures/wc_team_h2h/`. All other Wave 2 items are **live-probe gated**
  (off-season / undiscovered tickers / settlement-unproven) — full gate outcomes in `WAVE2_STATUS.md`.
- pytest **1215**, vitest **81**, ruff clean.

**Planning artifacts:** detector-strategy roadmap docs (`DETECTOR_AUDIT_PLAN.md`, `DETECTOR_STRATEGIES_PLAN.md`,
`MASTER_BACKLOG.md`, `WAVE2_STATUS.md`) sit at the repo root (mostly planning, no code). The older
`wip/ui-preference-persistence` NiceGUI-prefs spike is **superseded** by the per-user profiles now in `origin/main`.

**Current limits:** every edge is **gross & top-of-book**; **fees are ESTIMATED (display-only, never netted
into the gap/ranking)**; position limits & collateral / full-depth execution are not modeled; field-implied
probabilities are **uncalibrated** display-only estimates. Read-only engine; single-process (throttle +
store + auth limiter are process-local → run ONE worker; auth mode makes multi-worker fatal). Auth targets a
**trusted loopback/LAN** model, not the public internet (see the §11.5 threat model).

**Next approved work (owner-gated, scoped not built):** field **underround** + the **advancement-field
detector** (both need an exhaustiveness proof); a **net-of-fees ACTIONABILITY** input (gross stays the
default ranking basis; the current fee estimate is display-only and never drives actionability); **execution
/ automated trading** (long-term only, behind the read-only guard).

**Where history lives:** `docs/STATUS.md` (shipped state + next work); `.kss/` topics + milestones
(detailed build history & decisions); `CLAUDE.md` (invariants that must not regress).

---

This file is the ChatGPT project reference snapshot. If repo files or live code conflict with this file,
prefer the current repo/live code and update this file.
