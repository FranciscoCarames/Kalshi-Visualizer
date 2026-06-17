# Note 2026-06-04 — NiceGUI hosted workflow-parity plan (design only, no code) + Stage 0 LAN access shipped

Session deliverable: a fully-reviewed plan to bring the NiceGUI dashboard (`webui/dashboard.py`, shipped s5
#41) to the same information as the Streamlit `app.py`, **so IT can host it for the whole office network**.
Plus the LAN-access groundwork was implemented this session.

## Where the plan lives (full text)
- **`Concurrent Plans/nicegui-hosted-parity-plan.md`** — the complete, self-contained, handoff-ready plan
  (context, architecture + rationale, 5 spec checklists, staged PRs, verification, open decisions).
- `~/.claude/plans/jiggly-chasing-bachman.md` — working copy (same plan).

Plan version: **v4**. Store schema it introduces: **v3**.

## What this milestone IS
This is the long-deferred **"per-player deep-dive port → Streamlit retirement"** follow-up (see STATE
"deferred follow-up"), now fully designed AND expanded with a **hosting** requirement. Success metric =
**hosted workflow parity**, not section-cloning (trader workflow stays front; analyst/debug secondary).

## Central architecture decision (with reasoning)
**Store-everything-per-scan; zero view-time network.** Rejected per-viewer live-fetch (the obvious "hybrid")
because a trading UI must show ONE consistent truth — a snapshot table + a live-fetched detail = two
timestamps. Also rejected store-only (not parity). Chosen model: each scan persists raw contracts + the full
`build_checks` frame + dutch-book findings + unified rows + coverage; the dashboard renders **every** section
from one pinned `snapshot_id`; **the only network fetch is the scan** (one scheduled job → rate-safe for many
concurrent viewers; no stampede/event-loop/control-spam).

## Locked deployment decisions (owner)
IT-hosted; reachable by any office device; **no auth** (internal, read-only public data); **scheduled
`POST /scan`** keeps data fresh. Verified live this session: a user opened the dashboard on an **Android over a
phone hotspot** (office WiFi blocked it via client isolation — hosting must be on a routable server segment).

## Stage 0 LAN access — IMPLEMENTED this session (UNCOMMITTED)
- `serve.py`: `API_HOST`/`API_PORT` now env-overridable (default loopback `127.0.0.1`); warns/(plan: fails)
  on non-loopback bind without `NICEGUI_STORAGE_SECRET`; prints LAN URL.
- New: `docs/LAN_ACCESS.md`, `docs/DEPLOYMENT.md` (IT hand-off), `serve_lan.ps1` (one-command LAN launcher).
- Verified: bound `0.0.0.0:8010`, `/healthz` ok, `/` renders.
- **Not committed** — shared working tree with the parallel m5 session (PR #42 open). Commit Stage 0 +
  open PR once the tree is clear. (Owner rule: do concurrent work in an isolated git worktree.)

## Prerequisite correctness bug found (Stage 0.5)
`scanner.py:89–91` (`_to_unified_consistency`): `ticker_1=parent`/`ticker_2=child` but `url=child_url` first,
`url_2=parent_url` → the live NiceGUI panel's "Leg 1 market" link points at the CHILD while Leg 1 text
describes the parent. **Fix:** `url = parent_url or child_url`, `url_2 = child_url`; regression tests for BOTH
containment and dutch-book row shapes. Land as a standalone PR before any dashboard expansion. (Coordinate:
`scanner.py` is also edited by the m5 session.)

## Staged PRs (small, single-purpose, off `main`, never stacked)
Stage 0 (LAN, commit pending) · 0.5 (leg/URL fix) · 1a (store schema v3: `snapshot_frames`, per-frame schema
versions, WAL/busy_timeout/txn, migration+backup) · 1b (two-tier retention: lean opps 30h + heavy latest-N
under size budget) · 2 (scanner persistence + ScanManager singleflight + non-blocking `/scan` 202 + injectable
scope + forced scan-all benchmark + `kalshi_client` request counter) · 3 (`viewmodel.py` + controls +
opportunity-first tables) · 4 (export → ZIP CSV+manifest) · 5 (participant/team detail; charts optional/last) ·
6 (diagnostics via AG Grid server-side data source + debug by sport/family + JSON `/metrics`) · 7 (hardening,
responsive, browser smoke tests, docs).

## Two named volume counters to thread through (coverage → banner → /metrics → export)
`contracts_scanned` (normalized contract rows loaded) and `checks_tested` (candidate consistency + dutch-book
checks evaluated — NOT opportunities found).

## Open decisions (owner / IT)
1. Scheduled scan scope + interval — **gated on the Stage-2 forced scan-all benchmark** (duration / requests /
   failed-series rate / row counts). 2. Heavy-frame retention N (evidence window) vs DB size budget.
3. Scan-token on `/scan` for non-loopback (operational hardening, not auth) — off until owner confirms.

## How it was produced
Designed + hardened over 4 adversarial review rounds (60+ issues triaged: adopted/refined/declined with
reasons — see the plan's review history reflected in the spec). No code beyond Stage 0.
