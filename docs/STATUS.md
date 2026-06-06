# Status

Where the project stands today: what's shipped, what it deliberately does not model, and the approved
next work. (For how the code is structured and the invariants that must not regress, see
[`CLAUDE.md`](../CLAUDE.md); for hosting, [`DEPLOYMENT.md`](DEPLOYMENT.md).)

## What this is

A read-only, multi-sport dashboard that spots **executable pricing inconsistencies** and **dutch-book
edges** across a participant's related Kalshi contracts. The same player or team often appears across
several contract types at once — match result, advancement (reach a round), and tournament winner —
and viewing them together exposes when one is priced inconsistently with another, or when a set of
mutually-exclusive outcomes can all be bought for less than the guaranteed payout. Opportunities are
ranked best-first and split into Actionable / Review / Blocked with plain-English reasons for whatever
blocks a trade. The long-term direction is a real-time, ranked, lifecycle-aware opportunity engine for
a small trader group.

## Shipped

- **Engine + two detectors over one abstraction.** `sports.py` `SportConfig` registry; the containment
  ladder + match-alignment classifier (`consistency.py`); the dutch-book / MECE detector
  (`dutchbook.py` — 2-way, soccer 3-way, tournament-winner field); and the synthetic exact-score bundle
  detector (`synthetic_bundle.py`, review-only).
- **8 sports:** tennis, NBA, WNBA, golf, soccer, MLB, NHL, and motorsport (F1/NASCAR/IndyCar/MotoGP).
  Adding another is one `register(SportConfig(...))` call.
- **Engine behind a typed API.** A SQLite **snapshot store** (`store.py`) persists each scan; a
  cross-sport `scanner.py` produces a unified ranked table; `lifecycle.py` diffs new / changed /
  recently-actionable; a **FastAPI** REST API (`api.py`: `/healthz`, `/readyz`, `/opportunities`,
  `/coverage`, `/metrics`, `/scan`, `/alerts`, `/backlog`) exposes it. `POST /scan` is non-blocking
  behind a singleflight + per-process rate-limit + an env-gated `SCAN_TOKEN`.
- **NiceGUI dashboard** (`webui/`, mounted on FastAPI via `serve.py`) — the **sole UI** (the legacy
  Streamlit `app.py` was retired): ranked Actionable / Review / Blocked, a participant-detail panel,
  diagnostics/debug AG-Grids, truthful empty states, snapshot export, and live freshness.
- **Office-LAN hosting.** `/readyz` readiness, env-driven `SNAPSHOT_DB_PATH`, a non-force "Scan now",
  in-process auto-scan, bind safety, and a clean deploy-repo builder (`scripts/build_deploy_repo.py`) +
  `deploy/` systemd templates. See [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Current limits (documented, not modeled)

Every reported edge is **gross and top-of-book** — an upper bound on what the quotes imply, not a
guaranteed take-home. Three costs are deliberately not modeled until the owner opts in (single-sourced
in `glossary.py`, term "Known limits"):

- **Fees / net edge** — trading and settlement fees are not subtracted; a thin gross gap can turn
  net-negative.
- **Position limits & collateral** — sizes are the top-of-book quote size; per-market caps and the
  collateral to hold every leg are not accounted for.
- **Full-depth execution** — prices/sizes are top-of-book only; filling past the top resting size walks
  the book.

Other standing constraints:

- **Read-only** — no trading, authentication, or order placement.
- **Single process** — the Kalshi request throttle and the snapshot store are process-local; run one
  worker (aggregate rate = `MAX_RPS × process count`).
- Some grouping depends on the quality of Kalshi's metadata; gaps are surfaced, not hidden.

## Next approved work

Owner-gated; each item below is scoped but not yet built.

- **Field underround** and the **advancement-field detector** (n-outcome "reach a stage" fields) — both
  need an exhaustiveness proof before they can fire.
- **Net-of-fees edge math** — capture Kalshi's fee schedule and surface a net edge alongside the gross
  one (gross stays the default; fees never silently drive actionability).
- **Execution / automated trading** — long-term only, explicitly out of scope until the owner lifts the
  read-only guard.

Detailed build history and per-milestone decisions live in `.kss/` (topics + milestones).
