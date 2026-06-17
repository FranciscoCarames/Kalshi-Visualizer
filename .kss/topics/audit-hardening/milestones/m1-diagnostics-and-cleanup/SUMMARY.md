---
milestone: m1-diagnostics-and-cleanup
topic: audit-hardening
shipped: 2026-06-02
status: shipped
---

# Milestone Summary: m1 — Diagnostics, Tests, and Cleanup

## What Shipped

The eleven remaining items (7–17) from the June 2026 dual audit (Claude + Codex). Inline documentation of the AUDIT-002 product decision; two new Debug-expander counters (markets skipped for a blank `yes_sub_title`; discovered series excluded for an unrecognised kind); the project's first Streamlit AppTest smoke test running the real pipeline on mocked network; a fix to `expected_nodes` so players without advancement/winner contracts no longer show spurious MISSING_LAYER rows; the H3 investigation (event fetch is `status=open` at the API level) with the finding documented in CLAUDE.md; `ruff` added and the codebase made lint-clean; `AGENTS.md` slimmed to a delta-only doc; root docs reorganised; and CONTEXT.md distilled into CANONICAL-KB then archived.

(Items 1–6 — the text/wording fixes — were shipped directly before this milestone was scoped.)

## Success Criteria

- [x] `pytest -q` passes with the AppTest smoke test included — passed cleanly (95 tests, was 94)
- [x] AUDIT-002 product decision documented in `consistency.py` + `CLAUDE.md` — passed
- [x] Debug expander shows skipped-market and excluded-series counts — passed
- [x] `expected_nodes()` no longer flags MISSING_LAYER for players with no advance/winner contracts — passed
- [x] H3 investigated + documented in `CLAUDE.md` — passed (confirmed `get_events` passes `status="open"`; behaviour unchanged, docs clarified)
- [x] `ruff check .` runs without error — passed (fixed 7 findings, all pre-existing, none from this milestone's logic changes)
- [x] `AGENTS.md` is delta-only with a CLAUDE.md pointer — passed (270 → ~40 lines)
- [x] Root clean: audit docs → `docs/audit/`, `kalshi-plan.md` → `docs/historical/` — passed
- [x] `.kss/CANONICAL-KB.md` populated from `CONTEXT.md` — passed (9 insights; CONTEXT.md archived to `docs/historical/`)

## Decisions Worth Remembering

| Decision | Rationale | Outcome |
|---|---|---|
| Event fetch stays `status="open"` (no behaviour change for H3) | Fetching settled events would add GETs per tick for little benefit; "finalized markets in diagnostics" only ever meant finalized markets inside still-open events | Documented the real scope in CLAUDE.md instead of changing the fetch |
| `expected_nodes` gates on kinds present (option a) | Simplest fix; only expect the advancement ladder when the player actually has `advance`/`winner` contracts | Removed MISSING_LAYER noise without breaking the existing winner-only test |

(Both promoted to TOPIC.md Key Decisions.)

## Deferred

Captured as seeds:

- SEED-S4 — Fetch settled/closed events for richer Full-diagnostics history (trigger: users report finalized markets they expect are missing from diagnostics)

## Files Touched

- `consistency.py` — AUDIT-002 comment; `expected_nodes` kind-gating; docstring de-FO
- `data.py` — `_diag` skipped-market counter; docstring + `_contract_label` de-FO
- `kalshi_client.py` — docstring de-FO (H3 confirmed, no behaviour change)
- `app.py` — title; failed-series warning; per-player caption; load_contracts 7-tuple + two debug counters; expected_nodes empty-guard; scan-all help; `l`→`lbl`; import sort
- `config.py` — docstring de-FO
- `CLAUDE.md` — AUDIT-002 note; H3 scope note; `ruff check .` in verify steps
- `AGENTS.md` — slimmed to delta-only
- `tests/test_app.py` — new AppTest smoke test
- `tests/test_consistency.py` — semicolon splits (lint)
- `requirements-dev.txt`, `pyproject.toml` — ruff
- `docs/audit/`, `docs/historical/` — relocated AUDIT_REPORT, PROJECT_EXPLANATION_AND_ROADMAP, kalshi-plan, CONTEXT
- `.kss/CANONICAL-KB.md` — 9 distilled insights

## Sessions

1 session logged (2026-06-02).

---
*Closed via complete-milestone on 2026-06-02*
