# Engineering Plan — Kalshi Layer-Spread Tool (simple-first)

> **Scope guard:** read-only only. No trading, account access, or order execution. Keep it read-only
> until/unless that guard is explicitly lifted.
>
> **Approach:** start with the simplest useful math (raw calendar spreads between adjacent stage
> contracts) and add probability models / features **only if needed**. Nothing below the "v1" line is
> committed scope — it's an optional menu, not a gated roadmap.

## Repository state

`main` is current and canonical: the full app (multi-contract discovery, transparent pricing, Layer
Consistency Checker), the mapping-audit hardening + first tests, **v1 raw ladder spreads**, and the
spread NaN-fix/Quote column are all merged (PRs #6, #7, #9, #11; agent guides via #4). Test suite ~36
`pytest` cases. (PR #5 superseded by this document.)

## What exists now

A read-only Streamlit app that discovers French Open per-player contracts across market types (match
result, stage advancement, tournament winner; opt-in full scan adds set-winner / exact-score), shows a
transparent price breakdown per contract (Display % + YES mid/last/bid/ask + spread + quote-quality),
runs a **Layer Consistency Checker** (flags when a deeper outcome prices above a prerequisite it
contains), and — beneath the per-player ladder — shows **raw stage-ladder spreads** with a Quote column.
Per-contract mapping confidence, an expected-vs-found layer view, a per-player export, and a `pytest`
suite are in place. No probability model, signals, alerts, or trading.

## v1 — Calendar spread math (raw spreads)  ✅ DONE / shipped

Per player, the **raw price gap between adjacent contracts** on the ladder
`Reach Semifinal → Reach Final → Win Tournament` (`spread_pct` in percentage points, `spread_cents` in
cents; broader − deeper). Pure arithmetic on existing prices — no probabilities, no de-vig, no models.
Implemented in `consistency.layer_spreads` (reusing `representative`/`build_player_nodes`), rendered
beneath the ladder with a Quote column; `missing_layer` vs `missing_price` are distinguished and shown
blank; inverted (negative) spreads cross-reference the consistency table. NaN-safe after the
DataFrame→records fix.

## v1.1 — Correctness hardening (from external audit)  ✅ DONE

Tier-1 fixes from `audit_report.md` (verified, with regression tests):
- **Key-based grouping (AUDIT-001):** consistency checks and the player selector group by stable
  `player_key`, not display name, so two players sharing a name are never merged.
- **Truthful equivalence reason (AUDIT-003):** the executable-violation reason quotes the actual winning
  cross direction (forward or reverse).
- **Winner-ticker tour map (AUDIT-004):** all `FO_WINNER_TICKERS` variants classify to the correct tour
  (e.g. `KXFOPENWMENSINGLE` → WTA).
- **Crossed-book guard (AUDIT-005):** `ask < bid` books are "Crossed" quality — no Tight label, no
  midpoint display price, never fed to the executable test.
- **JSON safety:** a non-JSON 200 body raises `KalshiError`, not a raw decode error.
- **AUDIT-002 decision:** *keep* current behavior — a sizeless price-cross that **also** crosses on
  display is `DISPLAY_VIOLATION` (not `QUOTE_SIZE_MISSING`); docs clarified.

## Expand later (optional — only if a real need appears)

Each is independent and unordered; pick up only when justified:

- Conditional advance probabilities (deeper ÷ broader) and de-vig/normalization of overround.
- Spread-edge signals (flag a next stage that looks cheap/expensive vs the implied step).
- Skill/Elo-adjusted probabilities — **needs an external rating source** (ATP/WTA ranking or Elo).
- Scenario / bracket trees — **needs a draw-structure source** (Kalshi doesn't expose the full draw).
- Confidence & liquidity scoring; quote-freshness/stale flags.
- Real-time updates (polling/WebSocket); in-app alerts.
- Trading (paper, then live) — **out of scope** unless the read-only guard is explicitly lifted.

**Deferred audit items (Tier-2, only if a need appears):** surface pagination truncation instead of
silent partial data (AUDIT-007); deterministic handling of duplicate node/source rows under full scan
(AUDIT-006); require a tennis/competition signal before the date-window FO fallback, or flag it
low-confidence (AUDIT-008); a deterministic sample-data mode for offline app smoke tests (AUDIT-009);
clearer expected-layer semantics for early-round-only players (AUDIT-010); a minimal lint config
(AUDIT-011, needs a dep decision); plus the broader regression-test matrix from the audit.

## Verification & housekeeping

- Run: `streamlit run app.py` (after editing imported modules, fully restart the server — Streamlit
  caches imported modules in the running process, so a browser "rerun" alone won't pick up changes).
- Tests: `pip install -r requirements-dev.txt && pytest -q`.
- The French Open date window in `config.py` is year-specific — update for future tournaments.
