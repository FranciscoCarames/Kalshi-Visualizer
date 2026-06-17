---
milestone: s1-opportunity-schema-store
topic: real-time-opportunity-engine
created: 2026-06-03
last_updated: 2026-06-03
status: planned
---

# Milestone Plan: s1 — Opportunity schema + SQLite snapshot store

> Stage 1 of the 6-stage roadmap (`~/.claude/plans/make-me-a-multi-atomic-tower.md`). The durable,
> UI-agnostic backbone. Stage 0 already shipped (PR #35).

## Goal (one sentence)

Give every opportunity a stable identity and a persisted history substrate — a deterministic
`opportunity_id`, a `relationship_type`, a required `blocked_reason`, and a standalone SQLite snapshot
`store.py` — so later stages (scanner, lifecycle, alerts, backlog, REST API) have something to build on.

## Success Criteria

- [ ] `opportunity_id` is deterministic and stable across runs (same inputs → identical id) for both
      consistency rows and dutch-book rows, via one shared `data.py` helper (sha1).
- [ ] `relationship_type` stamped on every row: `containment_adjacent` | `match_alignment` | `dutch_book`.
- [ ] `blocked_reason` present on every opportunity row; **non-empty iff** the row's bucket is `blocked`,
      "" otherwise — invariant holds across synthetic actionable / blocked / clean rows (test).
- [ ] `store.py` writes a snapshot per call and reads back via `latest_two()` / `snapshots_since(window)`;
      schema-versioned (pragma) with a forward migration; retention cap drops old snapshots. Unit-tested
      standalone against a tmp sqlite file.
- [ ] **No on-screen change** — the Streamlit app still renders; whole suite green (158+), ruff clean.

## Out of Scope

- Multi-user / server / locking (single-writer local SQLite is fine).
- Cross-sport fetch/aggregation (that's Stage 2 — the scanner is the store's first caller).
- Any app wiring / UI / FastAPI / NiceGUI (no behaviour change this milestone).
- Fees / net-edge; `unblock_condition` text (later).

## Task Breakdown

| # | Task | Status |
|---|------|--------|
| 1 | `data.opportunity_id(...)` shared helper (`hashlib.sha1`, no randomness/Date) | ✓ |
| 2 | `consistency.py`: stamp `relationship_type` (in `build_checks`) + `opportunity_id` + required `blocked_reason` (from `blockers`, fallback) in `_row` | ✓ (also stamps `bucket`) |
| 3 | `dutchbook.py`: stamp the same three on `_detect_pair`; bucket = actionable if `tradable_now` startswith "Yes" else blocked | ✓ |
| 4 | `store.py`: SQLite schema + `write_snapshot`/`latest_two`/`snapshots_since` + version pragma/migration + retention cap | ✓ |
| 5 | `config.py`: `SNAPSHOT_DB_PATH` (+ retention window constant) | ✓ |
| 6 | Tests: new `test_store.py`; extend `test_consistency`/`test_dutchbook`/`test_data`; suite green + ruff | ✓ (180 pass, +22) |
| 7 | Verify (`pytest -q`, ruff, headless 200) → PR off `main` | ✓ → **PR #37** |

Status legend: ○ pending · ◆ in-progress · ✓ done

**SHIPPED 2026-06-03 via PR #37** (awaiting owner merge). All 7 tasks done; 180 tests pass, ruff
clean, headless 200, no on-screen change. Open questions resolved: id recipe is node/stage-based
(survives representative flips) with event-ticker disambiguation for unmapped-match rows (uniqueness
test added); full-row JSON blob carries every §9 field; `dutchbook → data` confirmed acyclic.

## Open Questions

- Match-alignment id uniqueness: is `relationship_type|player_key|tournament|child_node|parent_node`
  unique for equivalence pairs, or must it include the match round/stage? Validate with a uniqueness test.
- Final persisted-row field set for `store.py` (the §9 change-classifier needs: id, bucket, status,
  blocked_reason, gross gap, buy prices, sizes, leg status, rule_flag, missing-leg flag, sport, label,
  tournament) — confirm all are present on the unified row before persisting.
- Shared-helper home: `data.py` (pure utils; `dutchbook` imports it — no cycle). Confirm no import cycle.

## Notes

(deep-dive session writeups go to sibling `note-YYYYMMDD-*.md` files)

- Roadmap context (Stages 2–6) + the §7–§10 definitions: `~/.claude/plans/make-me-a-multi-atomic-tower.md`.

---
*Planned via plan-milestone on 2026-06-03*
