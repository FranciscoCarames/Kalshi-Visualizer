---
milestone: m1-diagnostics-and-cleanup
topic: audit-hardening
created: 2026-06-02
last_updated: 2026-06-02
status: planned
---

# Milestone Plan: m1 — Diagnostics, Tests, and Cleanup

## Goal (one sentence)

Ship the eleven remaining audit items (7–17): inline a product-decision comment, add two debug counters, add an AppTest smoke test, investigate and document the event-fetch status policy, fix expected-nodes noise, add ruff, slim AGENTS.md, and move stale docs out of the root.

## Success Criteria

What must be true to call this shipped:

- [ ] `pytest -q` passes with the AppTest smoke test included (expected: ~95+ tests)
- [ ] AUDIT-002 product decision documented with a comment in `consistency.py:327–333` and one explicit sentence in `CLAUDE.md`
- [ ] Debug expander shows: skipped-market count (missing `yes_sub_title`) and excluded-series count (unrecognized kind)
- [ ] `expected_nodes()` no longer flags `MISSING_LAYER` for players who have no advancement/winner contracts
- [ ] H3 investigated: `kalshi_client.get_events` event-fetch status policy confirmed and documented in `CLAUDE.md` (behavior change optional — documentation is the minimum)
- [ ] `ruff check .` runs without error from the project root
- [ ] `AGENTS.md` is a delta-only doc (agent-specific differences + pointer to CLAUDE.md); no duplicated content
- [ ] Root is clean: `AUDIT_REPORT.md` and `PROJECT_EXPLANATION_AND_ROADMAP.md` moved to `docs/audit/`; `kalshi-plan.md` moved to `docs/historical/`
- [ ] `.kss/CANONICAL-KB.md` populated from `CONTEXT.md` via `/kss:distill`

## Out of Scope

- Refactoring `app.py` into smaller modules (M5) — needs explicit ask
- Half-cent rounding regression tests (L1) — theoretical, penny-granularity API
- Series title fetch failure tracking (L2) — links already degrade gracefully
- Malformed numeric field counters (M3) — API format stable and tested
- Any new product features or non-tennis scope

## Task Breakdown

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1 | Document AUDIT-002 product decision inline | `consistency.py:327–333`, `CLAUDE.md` | ✓ |
| 2 | Add debug counter: markets skipped (missing `yes_sub_title`) | `data.py`, `app.py` Debug expander | ✓ |
| 3 | Add debug counter: series excluded (unrecognized kind) | `data.py` or `app.py`, Debug expander | ✓ |
| 4 | Add AppTest smoke test with mocked `load_contracts` | `tests/test_app.py` | ✓ |
| 5 | Investigate H3: does `kalshi_client.get_events` pass `status=open`? | `kalshi_client.py` | ✓ |
| 6 | Document H3 finding in `CLAUDE.md` (and fix if needed) | `kalshi_client.py`, `CLAUDE.md` | ✓ |
| 7 | Fix `expected_nodes()` to gate on kinds present in player rows | `consistency.py` | ✓ |
| 8 | Add `ruff` to `requirements-dev.txt` + minimal `pyproject.toml` | `requirements-dev.txt`, `pyproject.toml` | ✓ |
| 9 | Slim `AGENTS.md` to delta-only + CLAUDE.md pointer | `AGENTS.md` | ✓ |
| 10 | Move `AUDIT_REPORT.md` + `PROJECT_EXPLANATION_AND_ROADMAP.md` → `docs/audit/` | repo root, `docs/` | ✓ |
| 11 | Move `kalshi-plan.md` → `docs/historical/` | repo root, `docs/` | ✓ |
| 12 | Run `/kss:distill` on `CONTEXT.md` → `CANONICAL-KB.md`, then archive `CONTEXT.md` | `.kss/CANONICAL-KB.md`, `CONTEXT.md` | ✓ |

Status legend: ○ pending · ◆ in-progress · ✓ done

## Open Questions

- **H3:** Does `get_events()` pass `status=open` to the Kalshi API, or is the status filter only client-side? If API-level, should we also fetch `status=settled` events for diagnostics? (Cost: more GETs per tick — weigh against benefit.)
- **Task 7:** What's the right gate for expected nodes? Options: (a) only expect advancement nodes if any `advance`/`winner` kind row exists for that player, (b) expose a per-kind expected set. Option (a) is simpler and avoids breaking existing tests.
- **Task 12:** After distilling CONTEXT.md, should the file be deleted or moved to `docs/historical/`? Lean toward moving, not deleting.

## Notes

(deep-dive session writeups go to sibling `note-YYYYMMDD-*.md` files, not here)

---
*Planned via plan-milestone on 2026-06-02*
