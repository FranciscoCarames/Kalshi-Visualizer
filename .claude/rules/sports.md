---
paths:
  - "sports.py"
  - "data.py"
  - "fetch.py"
---

# Multi-sport (`sports.py`) — do not regress

`sports.py` defines a `SportConfig` abstraction (`IdentityResolver`, `LadderSpec`,
`MarketClassification`); `sport_for_series()` resolves a series ticker to its config, returning the
explicit `UNKNOWN` sport when unrecognized — **never a silent tennis default**. Adding a sport = one
`register(SportConfig(...))` call. `build_contracts` includes **all events for all registered sports**;
ladders group by **(player_key, tournament)** per sport. Tournament is a client-side filter.
`data.tournament_of` **season-scopes** every non-tennis grouping key (`_season_token` → `· <season>`,
so co-loaded seasons never form a false cross-season ladder; tennis byte-for-byte unchanged).
`SportConfig.winner_label` gives the winner family per-sport wording ("Win the World Series" / "Win the
Stanley Cup" / default "Win the tournament").

| Sport | Identity | match_family | Ladder (broad→deep) / notes |
|---|---|---|---|
| Tennis | `tennis_competitor` UUID | `match` | Reach SF ⊇ Reach Final ⊇ Win Tournament |
| NBA | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Win Conference ⊇ Win Championship; `KX*GAME` games |
| WNBA | `basketball_team` UUID | `match` (series) | Reach Playoffs ⊇ Reach SF ⊇ Reach Finals ⊇ Win Championship; games |
| Golf | `golf_competitor` UUID | `""` (no dutch books) | `exact_series` Top20 ⊇ Top10 ⊇ Top5 ⊇ Win |
| Soccer | `soccer_team` UUID | `""` (3-way games) | `exact_series` `KXWCGAME` (Home/Away/Tie dutch books) + `KXWCROUND`/`KXWCGROUPQUAL` advance ladder Reach RO32 (=group qualifier) ⊇ RO16 ⊇ QF ⊇ SF ⊇ Final ⊇ Win the World Cup (outright = `KXMENWORLDCUP`, live-verified 2026-06-10; `KXWC`/`KXMWORLDCUP` have no open events). Plus `KXWCGROUPWIN` (win-group leaf), `KXWCGROUPQUAL`/`KXWCGROUPBOTTOM` cardinality baskets, `KXWCGROUPORDER` exact-order diagnostics, `KXWCSTAGEOFELIM` 7-bucket stage-of-elimination book (tail-sum layer Review-only), and 9 recognized-but-excluded `KXWC*` props (`_SOCCER_KNOWN_OTHER`) |
| MLB | `baseball_team` UUID | `""` | Reach Playoffs ⊇ Win League ⊇ Win World Series; `KXMLBGAME` games. `KXMLBSERIES` excluded as non-MECE (can tie 2-2) |
| NHL | `hockey_team` UUID | `match` | Reach Playoffs ⊇ Win Conference ⊇ Win Stanley Cup; `KXNHLSERIES` (clean bo7) + `KXNHLGAME` dutch books. Live series wording "1st/2nd Round" → no rung → `UNKNOWN_RELATIONSHIP` |
| Motorsport | multi-path (driver UUID / team UUID / constructor NAME), role-namespaced `player_key` | `""` | **field sport like golf**; one-winner FIELDS → overround; Top-N/Podium → finishing-position ladder |
| NFL | `football_team` UUID | `""` | Reach Playoffs (`KXNFLPLAYOFF`) ⊇ Win Conference (`KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`) ⊇ Win Super Bowl (`KXSB` winner field → overround); `KXNFLGAME` games are tie-capable → `game_mece_by_shape=False` gates the dutch book on `dutchbook._proves_fixed_sum` ($0.50-tie / no-tie proof). Props/totals/spreads/division/awards/draft → `other` |
| Esports | `esports_competitor` UUID | `""` | **field sport, NO ladder (v1)**; `exact_series` curated allow-list across CS2/LoL/Valorant/Dota2/CoD/R6/… `KX*GAME`+`KX*MAP` are 2-way DRAW-FREE → `"game"` family → ungated dutch books (`game_mece_by_shape=True`); per-title winner series (`KXCS2`, …) → overround. `divisions` per title. Totalmaps/qualifiers/props/legacy/dupes/event-majors → `other` (unowned → UNKNOWN, never fetched). Qualifier ladders / opponent labels / tag discovery = v2 |

Identity is `custom_strike.<key>`. Classification is an **allow-list** (`family_fn`), not a bare prefix —
MLB/NHL/motorsport lookalikes & props → `other`. Motorsport: `field_families`
(winner/race_winner/pole/fastest_lap/constructor/team) get the overround; Top-N/Podium → a per-competition
`ladder_fn`; grouping is per RACE INSTANCE (`tournament_key_fn` → `competition · session · token`);
`player_key` is role-namespaced so a constructor sharing the driver UUID path never merges.

## Fetch by family + the contract row (do not regress)

- **Fetch by family:** `fetch.py` (from the old `app.load_contracts`) pulls ONLY the series whose contract family is enabled (`data.series_for_families`) — **family toggles are the only control that changes what's fetched**. The hosted scan path `api.fetch_dep()` → core series only (`scan_all=False`; `True` would widen via `discover_tennis_series()`).
- **Contract row (`build_contracts`), key fields:** identity (`player`, `player_key`, `player_key_source`, `mapping_confidence`, `mapping_reason`), classification (`tour`, `kind`, `category`, `contract`, `stage`, `stage_rank`, `opponent`, `tournament`, `tournament_source`), pricing (`*_pct`, `*_c` cents, `*_size`, `spread_cents`, `quote_quality`, `subpenny`), `volume`, `open_interest`, `status`, `time_value`/`time_kind`, links (`kalshi_url`, `series`, `*_ticker`, `*_title`), `raw_*`, `rules_primary`.

`sports.py` and `data.py` MUST stay free of UI imports (no `nicegui`, no `streamlit`).
