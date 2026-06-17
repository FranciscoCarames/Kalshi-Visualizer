---
topic: full-tennis-coverage
created: 2026-06-03
---

# Seeds: full-tennis-coverage

Parked items. **Every seed must have a trigger condition.** Items without triggers rot — capture demands one.

| ID | Item | Trigger | Captured |
|---|---|---|---|
| S1 | `KXATPROUND` ("Will player reach round?") may be a generic reach-stage series that directly populates deeper ladder rungs (R16/QF) — could simplify the deep-ladder + reach↔advance↔winner work | When planning milestone #2 (discovery) or #4 (deep ladder), inspect KXATPROUND events/markets live | 2026-06-03 |
| S2 | Doubles & Davis Cup use a different participant identity (pairs / teams, not a single `tennis_competitor` UUID) | When discovery (#2) starts pulling KX*DOUBLES / KXDAVISCUP* | 2026-06-03 |
| S3 | Reliable "is this tennis?" classifier — category is just "Sports"; need to exclude table tennis (KXITTF*/KXTABLETENNIS/KXTTELITE*), freestyle chess "grand slams", golf, entertainment | When building discovery (#2) | 2026-06-03 |
| S4 | Dutch-book detector is sport-agnostic — once proven on tennis, it applies to NBA/WNBA match/winner fields and unblocks the soccer/draws work noted in sport-generalization | After milestone #1 ships | 2026-06-03 |
| S5 | **Extend dutch-book to per-game 2-outcome markets** (`KXNBAGAME`/`KXWNBAGAME`/`KXATPGAME`). m1 scopes to `match_family` (series), but NBA's 2-outcome liquidity is mostly per-game — valid MECE books we currently skip. High value for NBA/WNBA. | When picking up a dutch-book follow-up, or when NBA/WNBA coverage matters | 2026-06-03 |
| S6 | **n-outcome winner-field dutch book** (≥3 outcomes): needs field-completeness proof + multi-leg representation (deferred from m1). | After m1 closes / when winner-field coverage matters | 2026-06-03 |
| S7 | **Near-edge dutch-book watchlist** — surface books whose sum is within a few cents of 100¢ (mirrors the containment near-edge bucket; Open Q #4 from m1). | When adding watchlist polish to the dutch-book section | 2026-06-03 |
| S8 | **Synthetic-bundle advance hedge (Task 3b, deferred from m5).** Hedge the exact-score bundle against the player's reach-next-round `KX*ADVANCE` market (a distinct order book from the match-winner) — catches a mispricing 3a can't see, and is the only hedge when a match-winner market is absent/illiquid. Needs a cross-event join: match round → advance node via `LadderSpec.match_stage_to_node` → the player's market in the matching advance event. Build with the **gated middle-path**: emit a separate "vs reach-round" finding ONLY when the round→node join is unambiguous (player in exactly one matching advance event at the mapped node), else skip — so it never produces a false hedge. Same retirement caveat as 3a. | When match-winner books are thin/illiquid, or you want the reach-round cross-check (roadmap #5), or a concrete demand for advance-hedged discrepancies appears | 2026-06-04 |
