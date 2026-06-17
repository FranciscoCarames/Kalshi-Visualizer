---
slug: audit-hardening
created: 2026-06-02
last_updated: 2026-06-02
status: active
---

# Topic: audit-hardening

## What This Is

Address the remaining open items from the June 2026 dual audit (Claude + Codex) — robustness hardening, diagnostics, test coverage, and documentation cleanup.

## Goal

Close every open audit finding across four areas: inline code correctness (product-decision docs, skipped-market counters), test coverage (AppTest smoke test), UX robustness (expected-nodes noise, per-player section), and project hygiene (lint tooling, AGENTS.md reduction, docs reorganisation, KSS distillation).

## Success Bar

- All items 7–17 from the consolidated audit list are either shipped or explicitly deferred with a recorded reason.
- `pytest -q` still passes with the AppTest smoke test added.
- H3 (event-fetch status policy) is investigated and documented.
- `.kss/CANONICAL-KB.md` contains the durable decisions from `CONTEXT.md`.

## Key Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-02 | Items 1–6 (text/wording fixes) shipped directly without a milestone | Too small to warrant KSS overhead; list was fully specified |
| 2026-06-02 | M5 (refactor app.py) explicitly deferred | Violates project no-refactor principle; needs explicit future request |
| 2026-06-02 | Event fetch stays `status="open"` (H3) | Fetching settled events adds GETs for little benefit; "finalized in diagnostics" only ever meant finalized markets within open events. Documented scope instead of changing behaviour |
| 2026-06-02 | `expected_nodes` gates on kinds present | Only expect the advancement ladder when the player has `advance`/`winner` contracts; removes MISSING_LAYER noise without breaking the winner-only test |

## Out of Scope

- Refactoring `app.py` into smaller modules (M5) — deferred, needs explicit ask
- Half-cent rounding tests (L1) — theoretical edge case for penny-granularity API
- Series title fetch failure tracking (L2) — links degrade gracefully already
- Malformed numeric field counters (M3) — API format stable and tested
- Any non-tennis sports or trading features

---
*Created via new-topic on 2026-06-02*
