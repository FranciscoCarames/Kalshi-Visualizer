---
topic: sport-generalization
created: 2026-06-03
---

# Seeds: sport-generalization

Parked items. **Every seed must have a trigger condition.**

| ID | Item | Trigger | Captured |
|---|---|---|---|
| S1 | ~~Soccer / World Cup as the next sport (forces dutch-book/MECE detector + draw handling)~~ **PLANNED 2026-06-04** → `Concurrent Plans/soccer-world-cup-plan.md` (3-PR plan; not started) | When NBA generalization is shipped and the dutch-book detector is on the table | 2026-06-03 |
| S7 | Soccer outright "Win the World Cup" series wiring (the ladder's top rung) | When the outright-winner series lists live on Kalshi (absent as of 2026-06-04; ladder declares the node now, market missing until then) | 2026-06-04 |
| S8 | n-outcome **field** MECE — group-winner (`KXWCGROUPWINNER`, 12-way) + region furthest-stage fields | After soccer PR 2 (single-game n-outcome) ships AND field-level grouping + completeness proof are designed (event_ticker grouping is insufficient for fields) | 2026-06-04 |
| S9 | Broaden Kalshi fetch to settled/finalized events for elimination diagnostics | When soccer is live AND missing-layer/diagnostics noise from eliminated teams proves a real problem (open-only fetch can't distinguish elimination from a fetch gap) | 2026-06-04 |
| S2 | Generalize `is_french_open_event`/date-window logic into per-sport tournament filtering | When a third sport needs date-window disambiguation that the tournament key doesn't cover | 2026-06-03 |
| S3 | Golf phase 2: Make Cut rung + multi-tour (DP World cut+winner, LIV Top 5/10) | After golf v1 (PGA Top-X ladder) ships and a same-competition cut+placement+winner ladder is proven live | 2026-06-04 |
| S4 | Golf H2H (`KXPGAH2H`, ~37 events) + dutch-book on golf | When golf is live AND tie/settlement-rule semantics of golf H2H are verified (draws/ties break the 2-outcome MECE assumption) | 2026-06-04 |
| S5 | Sport-dispatch `data._contract_label` so golf reads "Finish Top 5 / Win tournament" not "Reach Top 5" | When the golf v1 ladder is shipped and the "Reach Top 5" wording is judged too ugly in the trader UI | 2026-06-04 |
| S6 | Normalize `tournament_of` competition strings (casefold/punct-insensitive) | When live data shows competition-string drift splitting a golf (or other) ladder across rungs | 2026-06-04 |
