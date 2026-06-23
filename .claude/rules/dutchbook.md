---
paths:
  - "dutchbook.py"
  - "scanner.py"
---

# Dutch-book / MECE detector — `dutchbook.py` (do not regress)

A **separate check family** from the containment ladder. A dutch book covers EVERY outcome of a MECE set
for under the guaranteed payout floor. **2-outcome** = head-to-head match/game (floor 100¢);
**n-outcome** = soccer 3-way (Home/Away/Tie via `prove_mece`); **winner field** = ≥3 "win" markets.
`find_dutch_books` dispatches soccer → `_detect_n_way`, winner fields → `_detect_field`, else the 2-way
`_detect_pair`; ≤1 finding/event; consumes `df.to_dict("records")` so it is **NaN-safe**.

- **Two directions, both pairs of BUYS** (never "sell"): **underround** Buy YES all (`Σ yes_ask < 100`);
  **overround** Buy NO all (`Σ no_ask < (n−1)·100`, with the `100 − yes_bid` fallback). Mutually
  exclusive (`bid ≤ ask`) → only one fires. Exact integer cents.
- **Sport-agnostic via `_is_two_way_row`:** eligible families are the sport's `match_family` AND the
  `"game"` family (`KX*GAME`). Props/winner/advance are not two-way → ignored; `UNKNOWN` sport excluded.
  `_detect_pair` enforces a normalized **same-series guard** (both legs must share a series).
- **Tie-capable games (do not regress):** `game_mece_by_shape=False` (NFL — games can tie) GATES the
  `"game"` book on `dutchbook._proves_fixed_sum` (exact proof a tie pays `$0.50`/side → 100¢ floor holds,
  or no tie possible); unproven ⇒ skipped, basis stamped on the finding. Default `True` = identical elsewhere.
- **One status `EXECUTABLE_DUTCH_BOOK`** carrying `tradable_now` + `blockers`. Routing is the only
  `consistency.py` touch (`bucket_of` + a `STATUS_GROUP` entry; the status string is a guarded literal).
  **Conservative wording — never "riskless"/"locked"/"true arbitrage"** (single-sourced via
  `glossary.DUTCH_BOOK_BASIS`): a **gross two-way pricing discrepancy under normal one-winner
  settlement**. A **per-game (`KX*GAME`) book carries a non-blocking postponement `settlement_caveat`**
  (`BLOCKERS["game_settlement"]`) — advisory, never changes `tradable_now`/bucket.
- **Winner FIELD is overround-only** (`prove_field_mece` sets `exhaustive=False`): MECE-but-not-exhaustive, safe on any priceable subset (`_field_overround_subset`: firm no-side + `yes_bid>0`) since an untraded winner only pays more. `gap = Σ yes_bid(subset) − 100`; the id keys on the EVENT; non-blocking `field_overround` caveat. **Out of scope (seed):** advance fields; field underround (needs exhaustiveness).
