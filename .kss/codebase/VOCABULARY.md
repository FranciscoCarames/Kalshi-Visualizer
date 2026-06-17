---
last_updated: 2026-06-04
---

# Vocabulary

Project-specific domain terms. The compressed names for concepts you use repeatedly when describing this work. Append-only — new terms are added; existing ones are refined manually, not auto-edited.

### Executable inconsistency

**Means:** A firm, tradable price cross between two contracts whose probabilities have a logical ordering — the deeper outcome prices above the broader one, with real resting orders and positive size on both legs.
**Not:** "Arbitrage" — true arbitrage additionally requires identical settlement rules, which the app cannot auto-verify for cross-market pairs.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Containment ladder

**Means:** The logical hierarchy `Reach Semifinal ⊇ Reach Final ⊇ Win Tournament`; a deeper (more specific) outcome is a subset of the broader one and must not price higher.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Buy YES / Buy NO

**Means:** The two legs of every opportunity: Buy YES on the broader/parent contract, Buy NO on the deeper/child contract. The app never recommends selling or shorting.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Tradable now

**Means:** Whether both legs of a trade can be placed this second — requires `EXECUTABLE_VIOLATION` status, both markets `active`, positive sizes, and (for match-alignment pairs) no rule flag.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Firm price

**Means:** A real resting order (live bid or ask with positive size) that can be executed immediately, as opposed to an estimated display price (midpoint or last trade).
**Not:** Display price — midpoint or last trade shown when firm quotes are absent.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Book width / Quote quality

**Means:** The bid–ask spread, graded Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide (>30¢) / One-sided / No quote / Crossed. Drives whether a finding is actionable or watchlist-only.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Gross quoted profit

**Means:** Edge per unit × tradable units, computed from quoted prices before fees, slippage, latency, or partial-fill risk. An upper bound, not a guaranteed take-home.
**Source:** auto-scan (verify) — also defined in `glossary.py`

### Player key

**Means:** The `custom_strike.tennis_competitor` UUID — stable cross-series identifier for a player used as the join key and grouping key (never the display name).
**Source:** auto-scan (verify)

### Tournament grouping

**Means:** The `tournament` column produced by `data.tournament_of()` — a never-empty string that groups a player's ladder across events within one tournament (cleaned `competition` → winner-ticker → title keyword → `Unknown · <id>`).
**Source:** auto-scan (verify)

### Contract family

**Means:** A logical category of Kalshi tennis contracts (match winner, stage advancement, tournament winner, set winner, exact score). The only sidebar control that changes what is fetched from the API.
**Source:** auto-scan (verify)

### Near-edge

**Means:** A `CLEAN` comparison row whose firm executable gap is within `NEAR_EDGE_MIN_C` cents below zero — "almost actionable" and surfaced as a watchlist signal, never a buy instruction.
**Source:** auto-scan (verify)

### Match-alignment

**Means:** A consistency check pairing a match-winner market with a stage-advancement market that should be logically equivalent (e.g. "win your Quarterfinal match" ≡ "Reach Semifinal") — always carries `RULE_CHECK_REQUIRED` because settlement-rule compatibility cannot be auto-verified.
**Source:** auto-scan (verify)

### Layer

**Means:** One node in the containment ladder for a player (e.g. "Reach Semifinal", "Reach Final", "Win Tournament"); a missing layer is explicitly surfaced as `MISSING_LAYER`.
**Source:** auto-scan (verify)

### Stage rank

**Means:** Integer sort key for tournament progression: Round of 128 = 1 … Champion = 8. Used to order a player's contracts and to drive adjacency in the ladder.
**Source:** auto-scan (verify)

### Mapping confidence

**Means:** "high" if a contract was linked to a player via the stable `tennis_competitor` UUID; "low" if only a name fallback was used. Stamped on every contract row.
**Source:** auto-scan (verify)

### Synthetic bundle

**Means:** A gross pricing discrepancy where a player's MECE exact-set-score set (bo5 {3-0,3-1,3-2} / bo3 {2-0,2-1}) replicates "they win the match" and is mispriced against their match-winner hedge. N legs; two directions (forward `< 100¢`, reverse `< N×100¢`). NOT riskless — always settlement-caveated (review-only, never Actionable), because an exact score ≠ the match-winner and a retirement settles the score legs to Fair Market Price.
**Not:** A dutch book — that's two outcomes of ONE market with no settlement caveat; a synthetic bundle spans two market families (exact-score ↔ match-winner).
**Source:** distill: full-tennis-coverage/m5-synthetic-bundle-detector — also in `glossary.py` + `synthetic_bundle.py`

### Match format (best-of-5 / best-of-3)

**Means:** Which exact-set-score states are possible for a player win: best-of-5 = {3-0, 3-1, 3-2}, best-of-3 = {2-0, 2-1}. Resolved per event from a verified signal (Grand-Slam keyword + gender/division), NOT from the tour — only men's Grand Slam singles are bo5. Held in `SportConfig.state_bundles` keyed by a `score_format` key; an unprovable format → no bundle emitted.
**Source:** distill: full-tennis-coverage/m5-synthetic-bundle-detector

---
*Refreshed by map-codebase on 2026-06-02*
