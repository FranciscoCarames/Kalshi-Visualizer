# Engineering Plan — Kalshi Layer-Spread Tool (simple-first)

> **Scope guard:** read-only only. No trading, account access, or order execution. Keep it read-only
> until/unless that guard is explicitly lifted.
>
> **Approach:** start with the simplest useful math (raw calendar spreads between adjacent stage
> contracts) and add probability models / features **only if needed**. Nothing below the "v1" line is
> committed scope — it's an optional menu, not a gated roadmap.

## Repository state

`main` is reconciled and current: PR #6 merged the full iteration-4 code, and PR #4 merged the agent
guides (`CLAUDE.md`/`AGENTS.md`). The only pending code PR is **PR #7** — mapping-audit hardening + the
first unit tests — on branch `feat/mapping-audit-hardening` (the canonical latest code). (PR #5, an
earlier `kalshi-plan.md` rewrite, is superseded by this document.)

## What exists now

A read-only Streamlit app that discovers French Open per-player contracts across market types (match
result, stage advancement, tournament winner; opt-in full scan adds set-winner / exact-score), shows a
transparent price breakdown per contract (Display % + YES mid/last/bid/ask + spread + quote-quality),
and runs a **Layer Consistency Checker** that flags when a deeper outcome prices above a prerequisite it
is contained in. PR #7 adds per-contract mapping confidence, an explicit expected-vs-found layer view,
a per-player export, and `pytest` unit tests. No probability model, signals, alerts, or trading.

## v1 — Calendar spread math (raw spreads)

The simplest useful next step: for each player, the **raw price gap between adjacent contracts** on the
existing progression ladder `Reach Semifinal → Reach Final → Win Tournament`:

```
spread_SF→Final  = price(Reach Semifinal) − price(Reach Final)
spread_Final→Win = price(Reach Final)     − price(Win Tournament)
```

- Pure arithmetic on prices the app already has — **no conditional probabilities, no de-vig, no models.**
- Reuse the per-player nodes already built (`consistency.build_player_nodes` / the chain in `app.py`);
  use the existing layer price (`display_pct`, and/or cent-exact `display_c`). Show in cents and/or %.
- A **missing layer → spread shown as N/A** (not zero). A **negative spread** (deeper priced above
  broader) is exactly what the Layer Consistency Checker already flags — cross-reference it, don't
  recompute.
- **Definition of done:** for a selected player, the raw spread between each adjacent *available* layer
  is displayed; missing layers are explicit; no new network calls; no models introduced.
- **Test:** a unit test for the spread helper over synthetic chains (incl. a missing layer); headless app
  shows the spreads in the player-detail view.

## Expand later (optional — only if a real need appears)

Each is independent and unordered; pick up only when justified:

- Conditional advance probabilities (deeper ÷ broader) and de-vig/normalization of overround.
- Spread-edge signals (flag a next stage that looks cheap/expensive vs the implied step).
- Skill/Elo-adjusted probabilities — **needs an external rating source** (ATP/WTA ranking or Elo).
- Scenario / bracket trees — **needs a draw-structure source** (Kalshi doesn't expose the full draw).
- Confidence & liquidity scoring; quote-freshness/stale flags.
- Real-time updates (polling/WebSocket); in-app alerts.
- Trading (paper, then live) — **out of scope** unless the read-only guard is explicitly lifted.

## Verification & housekeeping

- Run: `streamlit run app.py` (after editing imported modules, fully restart the server — Streamlit
  caches imported modules in the running process, so a browser "rerun" alone won't pick up changes).
- Tests: `pip install -r requirements-dev.txt && pytest -q`.
- The French Open date window in `config.py` is year-specific — update for future tournaments.
