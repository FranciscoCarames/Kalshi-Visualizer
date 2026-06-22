---
name: add-a-sport
description: Add a new sport to the Kalshi scanner via a SportConfig drop-in. Use when the user wants to onboard a new sport/league (its match, advance/round, winner, game, or prop series) into sports.py so its contracts are fetched, classified, laddered, and checked for inconsistencies/dutch books.
---

# Add a sport to the Kalshi scanner

Adding a sport is **the one owner-blessed extension** to the engine (see CLAUDE.md "Scope guard"). The whole
design goal is that it stays **one `register(SportConfig(...))` call** in `sports.py` and every other module
is a byte-for-byte no-op. Read `.claude/rules/sports.md` first — it has the per-sport table and the
identity/classification invariants. Keep `sports.py`/`data.py` **free of UI imports**.

## 0. Confirm scope and gather the series

This is read-only market plumbing — **never** add trading, de-vig, or net-of-fees while doing it.

Find the real Kalshi series for the sport (base URL `https://external-api.kalshi.com/trade-api/v2`, no auth
for market data). For each series you intend to own, note: the **ticker prefix**, what each market means
(match/head-to-head, advance/round, outright winner, per-game, prop), the **MECE shape** (2-way game?
n-way? winner field?), and the stable **`custom_strike.<key>` identity** (the per-sport join key — e.g.
`basketball_team`, `hockey_team`). `yes_sub_title` is the display name. Verify live before encoding —
don't trust a prefix's name.

## 1. Decide the four design axes

| Axis | Question | Where it lands in `SportConfig` |
|---|---|---|
| **Identity** | What stable UUID/name joins a participant's contracts? | `identity` (`IdentityResolver`); `custom_strike.<key>` |
| **Classification** | Which series/markets do we OWN vs ignore? (allow-list, not bare prefix) | `family_fn`, `ladder_families`, `match_family`, `field_families`, `exact_series` |
| **Ladder** | The containment chain broad→deep (e.g. Reach Playoffs ⊇ Win Conference ⊇ Win Title) | `ladder` (`LadderSpec`), `stage_rank`, `stage_fn`, `node_fn`; or `ladder_fn` for field sports |
| **Grouping** | What makes a tournament/season key (so co-loaded seasons don't merge)? | `tournament_key_fn`; `data.tournament_of` season-scopes non-tennis |

Pick the closest existing sport as a template (all live in `sports.py`):
- **Ladder sport with games** (NBA/NHL/MLB): `match_family` set, `KX*GAME` two-way dutch books, a stage ladder.
- **Field sport** (golf/motorsport/esports/NFL winner): one-winner FIELD → overround; `field_families`;
  Top-N/Podium via `ladder_fn`. No `match_family` ladder.
- **n-way games** (soccer Home/Away/Tie): needs `prove_mece`; `match_family=""`.
- **Tie-capable games** (NFL): set `game_mece_by_shape=False` so the game dutch book is gated on a fixed-sum proof.

For multi-path identity (a driver UUID **and** a constructor NAME, like motorsport) namespace `player_key`
by role (`role_fn`) so they never merge.

## 2. Write the `register(SportConfig(...))` call

Add one `register(SportConfig(...))` near the other sports in `sports.py`. Required fields include
`sport_id`, `label`, `emoji`, `series_prefixes`, `default_series`, `winner_tickers`, `identity`, `ladder`,
`match_family`, `ladder_families`, `family_fn`, `stage_fn`, `node_fn`, `division_fn`. Set
`winner_label` for the per-sport wording ("Win the World Series" / default "Win the tournament"). Anything
not owned must classify to `other` (and unowned series must resolve to `UNKNOWN`, never be fetched).
**Never introduce a silent default** — an unrecognized series must reach `UNKNOWN`, not fall through to tennis.

## 3. Verify live with `verify_sport.py`

```bash
python scripts/verify_sport.py <sport_id>            # open events, core series
python scripts/verify_sport.py <sport_id> --all      # widen discovery
python scripts/verify_sport.py <sport_id> --status open
```

Read the output critically: series loaded, contracts by family, **ladder-eligible** count, the
**unmapped/ineligible** families (confirm props/lookalikes are *correctly* excluded, not accidentally),
ladder comparisons by status, and any flagged inconsistencies. Empty results are valid between
seasons/rounds — not an error. If a family is misclassified, fix `family_fn`, not a downstream module.

## 4. Add a per-sport test (required — do not skip)

Mirror an existing `tests/test_<sport>.py` (e.g. `test_nhl.py`, `test_nfl.py`, `test_mlb.py`). Pin the
behaviors that matter with **synthetic fixtures, not live data**: identity/`player_key` joins, family
classification (owned vs `other`), ladder containment ordering, and the MECE/dutch-book shape (2-way /
n-way / field overround / tie-gated). A new sport with no test is a blocker.

## 5. Final checks before handoff

```bash
pytest -q                 # full suite (pure layers + engine + API + per-sport + headless browser)
ruff check .
python -c "import serve, api, webui.dashboard"   # import smoke; pure modules stay UI-import-free
```

Then follow the project git workflow (CLAUDE.md "Git workflow"): a dedicated feature branch off
`origin/main`, explicit `git add <paths>`, push to origin for the owner to review/merge. State in the
handoff: which series you own, the identity key, the ladder, and what `verify_sport.py` showed live.
