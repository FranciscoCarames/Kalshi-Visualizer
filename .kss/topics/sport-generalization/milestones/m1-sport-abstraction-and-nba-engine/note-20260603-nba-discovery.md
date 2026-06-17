# Stage 0 — NBA schema discovery (live, keyless, 2026-06-03)

Probed `https://external-api.kalshi.com/trade-api/v2` (no auth). 10,610 total series; 173 `KXNBA*`.
Live context: the **2026 Finals (New York vs San Antonio)** are active — real ladder data available now.

## Identity (the key unknown — RESOLVED)
- **Field: `custom_strike.basketball_team`** — a stable UUID, exact analog of tennis's `tennis_competitor`.
- Display name: `yes_sub_title` (city, e.g. "Boston", "Oklahoma City", "Los Angeles L").
- IdentityResolver(NBA): candidate path `["custom_strike.basketball_team"]`, display `yes_sub_title`,
  normalized-name fallback → low confidence. Same UUID→name ladder as tennis.

## Containment ladder (broad → deep) — live-validated
| Node | Series | Market shape | Notes |
|---|---|---|---|
| **Win Conference** (= reach the Finals) | `KXNBAEAST`, `KXNBAWEST` | single-sided, 1 market/team | title "Will <team> win the … Conference Championship?" |
| **Win Championship** | `KXNBA` | single-sided, 1 market/team | event `KXNBA-26` "Pro Basketball Finals: NY vs SAS 2026"; title "Will the <team> win the 2026 Pro Basketball Finals?" |

Containment: `Win Championship ⊆ Win Conference` (to win it all you must win your conference). Adjacent pair
`(child="Win Championship", parent="Win Conference")`.

## Match-alignment (series head-to-head) — like tennis `match`
- `KXNBASERIES` — events like `KXNBASERIES-26LALOKCR2` ("Series Winner: LAL vs OKC", sub "LAL vs OKC (R2 - 2026)"),
  **2 mutually-exclusive team markets**. Round in title/sub: "1st/2nd Round", "R1/R2", "Conference Finals", "Finals".
  Map: Finals series → Win Championship; Conference Finals series → Win Conference; earlier rounds → unmapped
  (UNKNOWN_RELATIONSHIP, safe). Eligible for ladder only when the round maps confidently.

## Unsupported / non-laddered (must be ineligible, surfaced in unmapped table)
- `KXNBAGAME` — per-game (`product_metadata.competition_scope == "Game"`), 2 markets/event. **Ineligible** (a single game ≠ series outcome).
- Spreads/totals (`KXNBASPREAD/TOTAL/...Q.../...H...`), player props (`KXNBAPTS/REB/AST/...`), awards
  (`KXNBAMVP/ROY/FINMVP/...`), draft (`KXNBADRAFT*`), division winners, All-Star, futures props — all **ineligible** with reasons.

## Useful signal
- `product_metadata.competition` = "Pro Basketball (M)"; `competition_scope` ∈ {"Series Winner", "Game"} —
  a clean laddered-vs-game discriminator to lean on in `classify`.

## NBA SportConfig shape (for Stage B)
- `sport_id="nba"`, `label="NBA"`, `emoji="🏀"`.
- `series_prefixes=("KXNBA",)`; `default_series=("KXNBA","KXNBAEAST","KXNBAWEST","KXNBASERIES")` (core ladder; `KXNBAGAME` optional to demo the unmapped table).
- `identity` → `custom_strike.basketball_team`.
- LadderSpec: `node_order=("Win Conference","Win Championship")`, adjacent `("Win Championship","Win Conference")`.
- `classify`: KXNBA→winner/Win Championship/eligible; KXNBAEAST|WEST→conf_winner/Win Conference/eligible;
  KXNBASERIES→series(match) + round→node (Finals/Conf Finals) else unmapped; KXNBAGAME→game/ineligible;
  else→prop/other/ineligible (with reason).
- `divisions={}` for M1 (conference filter deferred to M2 UI).

## Design implication (carried into Stage A)
NBA's ladder node comes from the **series**, not a title-extracted stage (KXNBA always = championship,
KXNBAEAST/WEST always = conference) — unlike tennis where node = kind+stage. So `classify()` must set
`ladder_node` directly per sport, and `build_contracts` stamps it on the row; `consistency.node_of(row)`
prefers `row["ladder_node"]` when present, else falls back to the resolved sport's kind+stage computation
(tennis back-compat for test rows that lack the field). This keeps the 107 tennis tests green.
