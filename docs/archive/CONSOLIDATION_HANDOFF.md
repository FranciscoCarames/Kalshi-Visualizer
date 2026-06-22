# Consolidation branch — handoff (resume here)

**Branch:** `feat/scanner-consolidated` (off `origin/main` @ `d5f8210`), **19 commits**, pushed to origin.
**Status:** the whole consolidation plan is DONE + verified. Owner reviews/merges to `origin/main` via PR.

## What's on the branch (per-commit, newest→oldest is in `git log`)
- **Wave 1** (6 commits): executable card economics, diagnostic-row gating, password floor removed
  (trusted-LAN, owner decision), real Buy-NO/book legs + participant chooser, deploy `update.sh` + docs,
  cheap-NO ladder-depth filters.
- **Novel detector stack** (cherry-picked from `feat/s2-numeric-diagnostic`): Wave 1 A1–A8 soundness,
  Wave 1b staleness gate (**fee-negative default kept OFF** in both UIs), `KXWCTEAMH2H` recognition,
  **S2 `numeric_ladder.py` — DIAGNOSTIC-ONLY, NOT wired** (see below). Skipped: the fee-neg-default commit
  (repeated) and the S1 illiquid bridge (subsumed by the closure below).
- **Stage 1 SSE** (`events.py`/`stream.ts`): snapshot push, auth-gated, polling fallback. Stage 2 (live
  WS) deferred on `experiment/realtime-sse-stage1`.
- **Full ladder closure** (`consistency.py`): recognizes EVERY (broader⊇deeper) pair, not just adjacent
  (RO16⊇SF, RO32⊇Final, …); excludes side-branch leaves; deduped; treated like adjacent pairs.
- **Wave 2** (SPA + engine): L1 bounded-loss legs (side/contract through the unifier → fixes "NO/NO" card
  + wrong-side links), T1 leg tickers, A4-fix chooser (teams only), PD-fix (ladder sections only with ≥2
  priced rungs), LENS-fix (zone-aware lens bar), C2 cheap-NO Event/Tournament/Championship scope sub-tabs,
  C3 `run.ps1` launcher (auth-safe).
- **AuthGate auth-off fix**: a 401 no longer bounces the open app to login when `AUTH_ENABLED=0`.
- **C1 independent pop-out workspaces**: `⧉` opens a window with Scanner+Inspector+Ladder under a NESTED
  `<TerminalProvider embedded={feed}>` — own selection/toggles, shared feed data, linked within the window.
- **Table-clarity** (experimental, BOTH UIs, NO hide-losing-bets): `capacity` $ column (top-book cost
  capacity, centralized in `vm.risk_budget_row`) + implied-EV default order for the bounded bucket.

## Verification (last run)
pytest **1241 passed**, vitest **85 passed**, `npm run build` clean, `ruff` clean on changed modules,
live browser + API checks green. (One browser test can flake with a `sqlite` lock if a `serve.py` is
running concurrently — passes in isolation.)

## To resume
- Run locally: `./run.ps1` (auth ON by default; `-AuthOff` for quick clicking; `-Rebuild` to rebuild SPA).
- Tests: `pytest -q`; `cd frontend && npm run build && npx vitest run`.
- The detector source branches still exist on origin (`feat/s2-numeric-diagnostic`, the realtime branch).

## Open follow-ups (NOT done — intentional)
- **S2 numeric ladders need wiring** to Actionable later, behind a future **F0 evidence gate** (settlement
  semantics / executable construction / false-positive control / isolation). Currently diagnostic-only.
  Reminder saved in memory + `WAVE2_STATUS.md`.
- **Realtime Stage 2** (live Kalshi WS) deferred — owner tests live before merging.
- `UI_ISSUES_BACKLOG.md` holds the original issue list (all addressed except the S2 wiring above).
