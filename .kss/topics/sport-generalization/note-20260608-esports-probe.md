# Phase-0 probe — Esports (10th sport) — 2026-06-08

Read-only, keyless, throttled probe via `kalshi_client.get_paginated` against
`https://external-api.kalshi.com/trade-api/v2`. `/series` returned **10,712** total series; **114**
matched an esports filter (`tags=['Esports']` for the real ones, plus a handful of keyword false
positives like `KXGOOGLEBREAKUP`/`KXGOLDCARD` that are NOT esports).

## Confirmed facts

- **Identity:** `custom_strike.esports_competitor` (stable UUID) on every game / map / winner market;
  `yes_sub_title` is the team name. → `mapping_confidence="high"`.
- **Game & map markets are 2-way `mutually_exclusive`, DRAW-FREE.** Verified live on `KXCS2GAME`,
  `KXCS2MAP`, `KXLOLGAME`, `KXLOLMAP`, `KXVALORANTGAME`, `KXVALORANTMAP`, `KXR6GAME` — each event has
  exactly 2 distinct-competitor markets, `rules_secondary` is **empty**, `rules_primary` = "If <team>
  wins (the match | map N) ... resolves to Yes" with **no tie / $0.50 clause** (overtime breaks ties).
  → `game_mece_by_shape=True` (default; **no** `_proves_fixed_sum` gate, unlike NFL). Dota2/COD/RL games
  follow the identical pattern (their probe calls only hit the `MAX_PAGES` cap because 0 *open* events
  existed at probe time, so the fallback pulled full settled history).
- **Winner fields → overround.** `KXCS2` event `KXCS2-IEMCOL26` ("IEM Cologne Champion") = 32 ME markets
  with `esports_competitor`. Generic per-title winner series (`KXCS2`, `KXDOTA2`, …) CONTAIN the live
  tournament event, so owning them captures the current "win the tournament" field without owning the
  event-specific majors.

## v1 ownership (exact allow-list — `exact_series`)

**game/map → family `"game"` (dutch books):** `KXCS2GAME KXCS2MAP KXLOLGAME KXLOLMAP KXVALORANTGAME
KXVALORANTMAP KXDOTA2GAME KXDOTA2MAP KXCODGAME KXCODMAP KXR6GAME KXR6MAP KXOWGAME KXRLGAME KXRLMAP`

**winner → family `"winner"` (overround):** `KXCS2 KXDOTA2 KXCOD KXVALORANT KXR6 KXOVERWATCH KXPUBG
KXBRAWLSTARS KXCROSSFIRE KXROCKETLEAGUE KXLEAGUEWORLDS`

**default_series (bounded hosted-scan subset):** the 6 big-title games+maps (CS2/LoL/Valorant/Dota2/COD/R6)
+ `KXCS2 KXVALORANT KXDOTA2 KXR6 KXCOD KXLEAGUEWORLDS`.

## Excluded (NOT owned → resolve to UNKNOWN, never fetched; rationale here, not the live dashboard)

- **Total-maps (not participant markets):** `KXCS2TOTALMAPS KXCODTOTALMAPS KXDOTA2TOTALMAPS
  KXLOLTOTALMAPS KXLOLTOTAL KXRLTOTALMAPS`.
- **Legacy CSGO:** `KXCSGO KXCSGOADVANCE KXCSGOGAME KXCSGOMAP`.
- **Dupes / stale:** `KXCS2GAMES KXCS2MAPWINNER KXLOLGAMES KXROCKETLEAGUEGAME KXOW` (vs `KXOVERWATCH`),
  `KXLEAGUE` (`Video games` tag vs `KXLEAGUEWORLDS`).
- **Qualifiers (v2):** `KXCS2QUALIFIER KXCS2QUALIFIERS KXCS2QUALIFY`.
- **Props / MVP / rank / roster:** `KXCHOVYMVP* KXZYWOOMVP* KXWORLDSMVP KXNIKOAWPMAJOR KXRANKLISTCS2*
  KXROSTERT1 KXLCKAHRIPICK KXCHARCOUNTLOLWORLDS KXFIRSTTIMEWINNER KXLOL1STTIMEWIN KXSPORTSIGNINSPIRED`.
- **Test:** `KXESPORTSTEST`.
- **Event-specific futures (deferred — maintenance-heavy):** `KXIEMCHEN KXPGLBUCH KXPGLMASTERSBUCHAREST
  KXSTARLADDERBUDAPESTMAJOR KXVALORANTMASTERSFINALS KXVCCHAMPIONSPARIS KXMIDSEASONINVITATIONAL*
  KXVALGCSEOUL KXVALPL* KXPUBGGC KXAUSTINMAJOR KXBLASTRIVALS2 KXBOUNTY2025S2 KXESLPROS1
  KXTORONTOULTRACHAMPIONSHIP KXODINVCTFINALS KXCS2IEMCOLOGNE KXEWC* KXEWCCHESS KXEWCSTARCRAFTII
  KXVALORANTGAMETEAMVSMIBR`.
- **Keyword false positives (not esports):** `KXGOOGLEBREAKUP KXGOLDCARD KXGOV* KXUHC2 MCBLACKOPS6`.

## v1 config shape

`sport_id="esports"`, `series_prefixes=()` (exact-only), identity `esports_competitor`,
`match_family=""` (games ride the `"game"` family), `field_families={"winner"}`, `game_mece_by_shape=True`,
empty ladder / `ladder_families=frozenset()`, per-title `divisions` (`division_label="Title"`). Qualifiers
+ ladders + opponent labels + tag discovery + `/milestones` grouping are v2.
