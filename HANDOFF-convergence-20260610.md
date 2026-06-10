# Handoff — WC/ITF convergence + UI trust fixes (2026-06-10, kickoff eve)

**Deliverable:** two stacked branches, ready for owner test + merge. Nothing pushed; `main` untouched.

## Branch graph

```
origin/main (1c522dd, PR #146)
  └─ feat/bounded-loss-phase2 (dd041c8)          ← base, already pending owner test
       └─ feat/convergence-20260610               ← NEW: merges the 4 WC/ITF branches
            └─ feat/ui-trust-fixes                ← NEW: scanning indicator + selection-clear + docs
```

Merge `feat/ui-trust-fixes` (the tip) to get everything; it contains the full stack
(bounded-loss phase 1+2, the two perf commits, and this convergence). The four source branches
(`feat/wc-coverage-audit`, `feat/wc-group-bottom`, `feat/wc-stage-of-elimination`,
`feat/tennis-itf`) are left intact for individual inspection.

## Merge order + conflicts

A (`wc-coverage-audit`) → B (`wc-group-bottom`): **fast-forwards** (B was stacked on A).
C (`wc-stage-of-elimination`): real merge — conflicts in `sports.py` (3 hunks) +
`tests/test_sports.py` (1 hunk), all resolved by **union** (both new families coexist; no
registration or hard exclusion dropped). D (`tennis-itf`): auto-merged.

Post-merge checklist verified programmatically: 17 soccer series owned (8 fetched + 9
recognized-but-excluded `_SOCCER_KNOWN_OTHER`); fractional co-winner series (`KXWCBESTHOST`,
`KXWCFURTHESTADVANCING`) classify `"other"`; `group_bottom`/`stage_of_elim`/`exact_order`
families correct; `winner_tickers == {KXMENWORLDCUP}`; `field_families == {winner}` (group_bottom
correctly NOT a field); ITF owned by tennis without widening ATP/WTA parsing.

## Test results

| Point | Result |
|---|---|
| After merge C | 892 passed |
| After merge D | 894 passed |
| After UI fixes (tip) | **901 passed**, `ruff check .` clean |

## Live verification (2026-06-10, kickoff eve — all gates PASS, nothing demoted)

- **Winner ticker (standing follow-up — RESOLVED):** `KXMENWORLDCUP-26` is the sole open
  outright. `KXWC`: 0 open events (the dormant guess never listed). `KXMWORLDCUP`: 0 open events.
- **Group-bottom (B gate):** 12 open events, every one 4 markets / 4 distinct `soccer_team`
  UUIDs. ⚠️ The `mutually_exclusive` flag **flipped False→True** since the 2026-06-09 probe.
  Behavior-neutral: basket routing is flag-independent (format-derived cardinality floor) and
  `group_bottom` is not in `field_families`, so no double-detection. Comments updated in
  `sports.py` + `tests/test_dutchbook.py` to record the flip. (Possible future upgrade: with
  ME=True it could qualify as a 4-outcome MECE field — left as-is, conservative.)
- **Stage-of-elimination (C gate):** 48 open events, all exactly 7 buckets / 1 constant UUID /
  `mutually_exclusive=True`. Matches fixtures.
- **ITF (D gate):** `KXITFMATCH` 92 events, `KXITFWMATCH` 77 — all 2-market head-to-head with
  full `tennis_competitor` UUID identity.

## Live scan smoke (serve.py boot on the convergence branch)

`GET /` 200, `/healthz` ok, `/readyz` ready. Fresh scan: **93 series scanned, 0 failed**,
2042 opportunities. Soccer 427 rows incl. **1 actionable stage-elim book**; stage-elim synth
rows: 10 `review_signal` + 1 `blocked` — **never actionable**. ITF flows (228 mentions in the
opportunity set). **Isolation assertion: 0 violations** (no stage-elim-synth / exact-order /
game-support row in the actionable bucket).

## Coverage audit — new unowned `KXWC*` series (report-only, NOT owned)

**65 new `KXWC*` series listed for kickoff**, all currently unowned → `UNKNOWN` (never fetched).
Mostly per-game props (1H markets, BTTS, corners, shots, first-goal, hat-tricks). Structurally
interesting for future work: `KXWCSCORE` (exact score), `KXWCSPREAD`/`KXWCTOTAL` (scalar
ladders), `KXWCTEAMH2H`, `KXWC3RDPLACE`, and `KXWCWINGROUP` (possible duplicate/equivalent of
owned `KXWCGROUPWIN` — worth a probe). Full list: run `python scripts/audit_series_coverage.py`.

## UI trust fixes (`feat/ui-trust-fixes`)

1. **"Scanning — new data shortly…"** label next to the freshness banner — visible for every
   scan source (scheduler, other LAN viewers, `POST /scan`), driven by the existing 1s tick via
   `engine.scan_status()` (no store/network read; pushes only on transition).
2. **Stale-selection clear** — when a filter removes the selected opportunity from the
   membership-filtered view: highlight drops in all 8 tables, the click-panel dialog closes if
   open, Selected Detail collapses with a truthful placeholder. Bucket toggles / band thresholds
   do NOT clear (opp still in scope). Pure predicate `vm.selection_left_view` (unit-tested; the
   headless suite can't drive row selection — manual check added to `docs/DEPLOYMENT.md` §4b).
3. `CLAUDE.md`: stale "dormant KXWC guess" soccer row replaced with verified facts; ITF row added.

## Follow-on branch: `feat/ui-table-clarity` (off feat/ui-trust-fixes)

Bounded-loss table clarity pass — 8 display-layer changes from the two UI audits (engine, buckets,
`tradable_now`, `scanner._rank_key`, API schema all untouched):

1. **Negative-margin/diagnostic rows hidden by default** behind a "Show negative-margin / diagnostic
   rows" switch, with an honest amber hidden-count line. Live impact at build time: 299 rb rows → 57
   shown (242 were Negative proxy).
2. **Default (Blended) ordering for the risk bucket now chance-weighted** (delegates to the implied-EV
   order) — a negative-margin 49:1 longshot can no longer outrank a positive-margin candidate by
   default; the explicit "Spread upside"/"Outright + spread" geometry modes are unchanged. Live: the
   two genuine Candidates (+21¢/+18¢ display EV) now lead.
3. **Five opaque labels renamed:** Implied bonus chance (pp) / Bonus breakeven % / Margin vs breakeven
   (pp) / Display EV ¢ (uncalibrated) / Top-book units; $100 columns now say "(size-capped)" (the math
   was always capped — the label now admits it).
4. **Default-visible columns trimmed** (cheap, detail, display_spread, caveat → hidden; all available
   via each table's Columns button). Caveated rows still show their severity chip.
5. **NEW column: Top-book capacity $** = cost × top-book units / 100 (dollars to take the whole
   visible book; explicitly NOT full-depth tradability).
6. **Coloured Signal chips** (green Candidate / grey Breakeven / amber Negative proxy / blue-grey
   diagnostic) — colour + text, never colour alone.
7. **Section renamed** "Bounded-Loss Candidates"; explainer paragraph rewritten to the new vocabulary.
8. **Peer-cheapness is toggle-independent** (computed on the full band-filtered set BEFORE the
   visibility filter, per audit amendment) — flipping the switch never changes a row's badge.

Verified: **904 tests pass** (3 new: capacity math incl. the 102×49→$49.98 case, signal filter,
blended-vs-geometry ordering), ruff clean, imports clean, boot smoke on **non-default port 8010**
(/, /healthz, /readyz, /metrics OK), live-data check of filter/ordering/capacity above. Manual
browser checks added to docs/DEPLOYMENT.md §4b ("Bounded-loss clarity" line).

## Manual checks before merging (owner)

- `docs/DEPLOYMENT.md` §4b "Before hosting" — especially the new stale-selection + scan-indicator
  line (needs a real browser).
- Dashboard eyeball on live WC data: stage-elim section, group-bottom baskets, ITF matches.
