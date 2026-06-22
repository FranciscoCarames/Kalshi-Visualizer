---
paths:
  - "consistency.py"
  - "scanner.py"
  - "data.py"
---

# Layer Consistency Checker — hard rules (do not regress)

Containment ladder broad→deep; a child (deeper) price must be ≤ its parent (broader). Adjacent
containment pairs use market contracts; **match-alignment** pairs (`Quarterfinal win ≡ Reach Semifinal`)
only when the round maps confidently. Unprovable → `UNKNOWN_RELATIONSHIP` (never a violation).

- **Call findings "executable inconsistencies", NEVER "arbitrage."** Settlement rules aren't
  auto-verified → match-alignment rows carry `RULE_CHECK_REQUIRED` (→ `RULE_MISMATCH` on a light
  `rules_primary` token diff).
- **Buy-only language (do not regress):** every opportunity is two BUYS — **Buy YES** broader/parent,
  **Buy NO** deeper/child — never "sell"/"long"/"short". `_classify` emits `action_1_*`/`action_2_*` (+
  `tradable_now`, `blockers`, `watchlist_note`); the Buy-NO price is the real `no_ask_c` (fallback
  `100 − yes_bid_c`). `tradable_now` is "Yes" only for `EXECUTABLE_VIOLATION` + both legs `active` + no
  rule flag ("Yes — rule-dependent" for equivalence). **`WIDE_QUOTE` gets no action.** Blocker/glossary
  text is single-sourced from `glossary.py`.
- **All comparison logic in exact integer cents** (`data.to_cents`, Decimal); floats are display-only.
- **Executable and display tests are independent.** Executable needs firm `yes_bid_c`/`yes_ask_c` **and
  positive sizes**; a missing display blocks only the display test.
- **`EXECUTABLE_VIOLATION` (firm child-bid > parent-ask, sizes > 0) is the ONLY "Broken" status.**
  `DISPLAY_VIOLATION` is "Warning"; a sizeless cross → `QUOTE_SIZE_MISSING`, **unless the display prices
  also cross** (then `DISPLAY_VIOLATION` — AUDIT-002). Crossed books (`ask < bid`) → "Crossed", never
  executable.
- Statuses: `CLEAN, EXECUTABLE_VIOLATION, DISPLAY_VIOLATION, WIDE_QUOTE, MISSING_QUOTE, MISSING_LAYER,
  QUOTE_SIZE_MISSING, UNKNOWN_RELATIONSHIP`. Groups: Broken=EXECUTABLE_VIOLATION; Warning=DISPLAY_VIOLATION/
  WIDE_QUOTE; Missing data=MISSING_QUOTE/MISSING_LAYER/QUOTE_SIZE_MISSING; Unknown=UNKNOWN_RELATIONSHIP.
  (For repeatable assertions use the unit tests, not live data.)

## Mapping audit & robustness invariants (do not regress)

- **Mapping confidence:** `build_contracts` stamps `mapping_confidence` ("high" = stable UUID; "low" =
  name fallback) + `mapping_reason`. No downstream row without `kind` + confidence.
- **Expected-vs-found:** `consistency.expected_nodes` makes a missing ladder layer explicit; the detail
  view exports a JSON snapshot + CSV.
- **Raw stage-ladder spreads:** `consistency.layer_spreads` returns per-adjacent-pair `spread_pct` (pp)
  and `spread_cents` (broader − deeper) — raw prices, not a probability model; reuse
  `consistency.representative`; `missing_layer` vs `missing_price` are both NaN-safe; a `quote` (worst
  leg) column; `inverted` is None-safe.
- **Group/select by `player_key`, not display name** (`build_checks` on `(player_key, tournament)`) — two
  same-named players never merge, and one player's tournaments never merge. `data.tournament_of` returns a
  **never-empty** key (cleaned `competition` → winner-ticker → title keyword → `Unknown · <id>`, with
  `tournament_source`) so a fallback never collapses to `""`.
- **Truthful evidence:** the `EXECUTABLE_VIOLATION` reason quotes the *winning* cross direction. **`tour_of`** classifies every `FO_WINNER_TICKERS` variant explicitly.
- **No silent truncation:** `get_paginated` raises if `MAX_PAGES` (100) is hit with a cursor pending. **Deterministic duplicates:** `build_player_nodes` picks a representative by a stable rule (`duplicate_node_sources` surfaces it).
