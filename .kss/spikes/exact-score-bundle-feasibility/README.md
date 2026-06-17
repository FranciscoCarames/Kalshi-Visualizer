# Spike: exact-score / state-bundle feasibility (live data)

- **Date:** 2026-06-04
- **Topic/milestone:** full-tennis-coverage / m5-synthetic-bundle-detector (Task 1)
- **Verdict:** ✅ **GO** — data is clean and parseable; build Task 2 + Task 3a with the **match-winner
  hedge first** (trivial reliable join). The retirement settlement caveat is **confirmed required**.

## Q1 — Where does the scoreline live? → `custom_strike` (structured, no regex)

Live `KXATPEXACTMATCH-26JUN05MENZVE` markets:
```
custom_strike = {"Set Score": "3-0", "tennis_competitor": "63c46490-...-eff64bb6707e"}
yes_sub_title = "Jakub Mensik wins 3-0"
```
- Scoreline = **`custom_strike["Set Score"]`** ("3-0"/"3-1"/"3-2") — a clean structured field, NO title
  regex needed. Player = **`custom_strike["tennis_competitor"]`** (UUID).
- 6 markets/event = 3 scores × 2 players (bo5). `mutually_exclusive: True` IS populated on the event.

## Q2 — What proves the match format (bo5 vs bo3)? → competition string + score set

- `product_metadata.competition = "French Open Men Singles"`; `rules_primary` names the round
  ("…2026 French Open Men Singles **Semifinal** by a set score of 3-0…").
- Format signal = **Grand-Slam + gender** from the competition string → men's Slam = bo5 → expected per
  player `{3-0,3-1,3-2}`. This is **independent** of counting the discovered markets (avoids the
  circularity issue). Non-Slam ATP and all WTA = bo3 `{2-0,2-1}`.
- ⚠️ Residual: **no live WTA exact-score event** right now (`KXWTAEXACTMATCH` → 0 events), so the bo3 path
  is untested on live data — keep the bo3 config but flag it unverified until a WTA event appears.

## Q3 — Hedge joinability → match-winner = trivial/reliable; advance = possible, needs round→node

- **Match-winner (`KXATPMATCH`):** SAME match exists. Event suffix matches
  (`KXATPMATCH-26JUN05MENZVE` ↔ `KXATPEXACTMATCH-26JUN05MENZVE`) and **player UUIDs match exactly**
  (Mensik `63c46490…`, Zverev `dc4002ad…`). Firm, liquid (`Mensik no_ask 0.77`, sizes ~8k–96k).
  → **Implement this hedge first (Task 3a):** join on `tennis_competitor` UUID within the matching event.
- **Advance (`KXATPADVANCE-26FOFIN` "reach Final"):** lists the whole draw incl. Mensik (same UUID), but
  is keyed to a target stage (Final). Winning a **Semifinal** ≡ reaching the Final, so the join needs the
  **match-round → advance-node map** (round parsed from `rules_primary` — hence Task 1.5 matters).
  → **Task 3b** (more complex; per issue #6, after the reliable match-winner hedge).

## Q4 — Retirement settlement rule → CAVEAT CONFIRMED REQUIRED

Exact-score `rules_secondary` (verbatim):
> "If the match does not occur (signaled by a ball being played) … the market will resolve to a **fair
> price**… If a **retirement** occurs, all markets that can be unconditionally settled based on play
> already completed will resolve accordingly. **Any markets that cannot be unconditionally settled will
> resolve to Fair Market Price**, at the sole discretion of the Exchange."

Match-winner `rules_secondary` has the no-ball-played fair-price + postponement clauses but **NOT** the
retirement clause (a retirement always yields a match winner → unconditionally settled).

**Implication (the retirement hole, now proven):** on a mid-match retirement, the exact-score legs that
didn't complete resolve to **Fair Market Price** (discretionary, not 0/100) while the match-winner / advance
hedge settles cleanly. So `{3 scores YES} + {match-winner NO}` does **NOT** guarantee 100¢. The bundle is a
**gross pricing discrepancy with a settlement caveat**, never riskless. This is an *inherent caveat*, not a
*hard contradiction* (both legs are rule-governed) → per the two-tier rule: **emit as review/blocked**
(`rule_flag` set, `tradable_now="Review rules"`), do NOT suppress.

## Detection sanity-check on live prices (no live arb, logic validated)

Mensik bundle: `YES_ask` scores 0.06+0.09+0.10 = 0.25; `Mensik match NO_ask` = 0.77 → forward cost
**1.02 ≥ 1.00** (no discrepancy — efficient, as expected). Reverse: `NO_ask` scores ≈0.98+0.96+0.93=2.87
+ `Mensik match YES_ask` 0.24 = 3.11 ≥ 3.00 (N=3). Logic + thresholds line up with real quotes.

## Decisions locked for build

1. Parse scoreline from `custom_strike["Set Score"]`; player from `custom_strike["tennis_competitor"]`.
   (Keep a `yes_sub_title` regex only as a defensive fallback.)
2. Format resolver: Grand-Slam-men → `tennis_bo5` `{3-0,3-1,3-2}`; else `tennis_bo3` `{2-0,2-1}`. No proof
   → no emit. (bo3 untested live — flagged.)
3. Hedge: **match-winner first (3a)** via UUID join in the matching event; advance hedge **3b**.
4. Settlement caveat always on (retirement → Fair Market Price). MECE gate can also read the populated
   `mutually_exclusive` flag.
