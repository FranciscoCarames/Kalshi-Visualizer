# WNBA discovery (live, keyless, 2026-06-03)

55 `KXWNBA*` series. **WNBA is in-season and LIVE now** (e.g. `KXWNBAGAME-26JUN04GSMIN` — Golden State
vs Minnesota, Jun 4) → a real **active** ladder is available for validation (unlike end-of-season NBA).

## Identity — SAME as NBA
- Field: **`custom_strike.basketball_team`** (UUID). Display: `yes_sub_title` (city). Reuse the NBA
  IdentityResolver verbatim.

## Ladder-relevant series
| Series | Title | Likely family / node |
|---|---|---|
| `KXWNBA` | WNBA Championship | winner → Win Championship (event `KXWNBA-26`, scope "Future") |
| `KXWNBAFINAL` | Finals Qualifiers | advance → **Reach Finals** (clean prerequisite for the title) |
| `KXWNBASEMIFINAL` | Semifinals Qualifiers | advance → Reach Semifinals (optional broader layer) |
| `KXWNBAEAST` / `KXWNBAWEST` | Conference Champion | advance → Win Conference *(see caveat)* |
| `KXWNBASERIES` | Professional Women's Basketball Series | match (series head-to-head) |
| `KXWNBAGAME` | Game (scope "Game") | game → **ineligible** |
| `KXWNBAPLAYOFF` | Playoff Qualifiers | advance → Reach Playoffs (optional broadest layer) |

competition = "Pro Basketball (W)" → tournament grouping key (distinct from NBA's "Pro Basketball (M)").

## ⚠ Design nuance — NOT a pure NBA clone
WNBA's modern playoff format is a **single bracket** (top-8 seeding), not a conference-based East-vs-West
final. So NBA's "Win Conference ⊇ Win Championship" containment **may not hold** for WNBA. The cleaner,
format-agnostic ladder is **Reach Finals (`KXWNBAFINAL`) ⊇ Win Championship (`KXWNBA`)**, optionally
extended with Reach Semifinals (`KXWNBASEMIFINAL`) and Reach Playoffs (`KXWNBAPLAYOFF`) as broader layers.
**Verify the actual format / what `KXWNBAEAST/WEST` settle on before mapping conferences to the ladder.**

## Proposed WNBA SportConfig (starting point)
- `sport_id="wnba"`, `label="WNBA"`, `emoji="🏀"`.
- `series_prefixes=("KXWNBA",)` (no collision: "KXWNBA" doesn't prefix-match NBA's "KXNBA", nor vice-versa).
- `identity` = `custom_strike.basketball_team` (reuse NBA's resolver).
- LadderSpec: `node_order=("Reach Finals","Win Championship")`, adjacent `("Win Championship","Reach Finals")`;
  family map: `KXWNBA`→winner/Win Championship, `KXWNBAFINAL`→advance/Reach Finals, `KXWNBASERIES`→match,
  `KXWNBAGAME`→game(ineligible), else→other. (Conference series: hold pending format check.)
- `default_series=("KXWNBA","KXWNBAFINAL","KXWNBASERIES","KXWNBAGAME")` (+ semifinal/playoff/conference once verified).
