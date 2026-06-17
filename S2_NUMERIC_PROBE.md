# S2 numeric-strike family — live-probe proof note

**Branch:** `feat/s2-numeric-diagnostic` (off `feat/s1-transitive-illiquid-bridge`). **Scope:** S2 v1 is
**DIAGNOSTIC ONLY** — `numeric_ladder.py` builds ladders; nothing reaches Actionable until the F0
launch-state gate lands AND a separate owner-approved promotion. This note records the live evidence that
the chosen shape is real (the live-probe gate).

## Probe (read-only, 2026-06-17, `external-api.kalshi.com/trade-api/v2`)

- 10,907 series total; **186 candidate numeric-in-sport series** (ticker/title hints: TOTAL, SPREAD,
  POINTS, RUNS, GOALS, …) across ATP/WTA, NBA, WNBA, MLB, NHL, CS2/LoL, etc. Large untapped universe.
- Hit **429s** on rapid raw requests — production discovery MUST go through `kalshi_client`'s throttle.

## Chosen first family: `KXATPGTOTAL` (ATP Total Games) — in-season (grass season, June)

Live markets for event `KXATPGTOTAL-26JUN17MEDHUM`:

| ticker | market_type | strike_type | floor_strike | cap_strike | yes_sub_title |
|---|---|---|---|---|---|
| …-20 | binary | greater | 19.5 | null | Over 19.5 games |
| …-25 | binary | greater | 24.5 | null | Over 24.5 games |
| …-30 | binary | greater | 29.5 | null | Over 29.5 games |

- **Containment (model-free):** `{X > 29.5} ⊆ {X > 24.5} ⊆ {X > 19.5}` ⇒ YES price must fall as
  `floor_strike` rises. Direction read from `strike_type=greater` + `floor_strike` — **never the subtitle**.
- **Identity = `event_ticker`**: every market in the event is the same scalar (total games, full match,
  same unit). Chosen as the first family precisely because identity is event-level and single-direction.

## Reject cases — verified live, enforced in `parse_numeric_strike`

- `KXATPEXACTMATCH` → `strike_type=custom` (exact score) → excluded.
- `KXLEADERMLBKS` (and other leaders) → `strike_type=structured` (who-leads field) → excluded.
- `between` (bracket markets) → excluded from the *monotonic* ladder (that's S3 territory).
- Missing/non-numeric strike value → excluded.

## Identity caveat (do not regress)

`KXATPGSPREAD` is **per-participant** (e.g. "Medvedev -6.5", "Atmane -1.5" in one event) — two different
scalars. The default `(series, event)` key would WRONGLY merge them; a per-participant family must pass a
`group_key_fn` that includes the participant. Covered by `test_per_participant_family_needs_a_richer_group_key`.

## Status / next

`numeric_ladder.py` (pure, 14 tests) is the proven core. NOT yet wired into the engine. Next: F0 lean
launch-state/diagnostic routing, then emit `KXATPGTOTAL` ladders as **diagnostic-only** rows (never
Actionable), with the existing `consistency` containment comparison reused read-only. Actionable promotion
of this family is a SEPARATE, owner-gated step requiring a full proof note (settlement/push behavior of
"Over N games", quote firmness, sizes).
