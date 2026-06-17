# Research-gates findings — §7 Q1/Q2/Q3 (2026-06-04)

Source: `research-gates` workflow (4 agents, live Kalshi reads + code analysis). Answers the UNIFIED-PLAN
§7 gating questions. **Caveated claims flagged** at the bottom.

## Q1 — Golf ladder: ✅ GO (narrow ladder)

All gating facts confirmed live. Register the v1 ladder; the one real engine requirement is exact-series
scope (which our `exact_series` ownership from PR 2 already provides — golf owning only the 4 tickers means
round-finishers never enter golf rows).

- **Series (broad→deep):** `KXPGATOP20 ⊇ KXPGATOP10 ⊇ KXPGATOP5`, plus `KXPGATOUR` (win).
- **Identity:** `custom_strike.golf_competitor` (UUID). **Pairing key:** `product_metadata.competition`.
  `KXPGATOUR` `competition_scope="Game"` (key winner by series, not scope).
- **Settlement:** Top-5/10/20 all "including ties" → strict containment confirmed live (USO26: all 106
  Top5 ⊆ Top10 ⊆ Top20).
- **Competition strings captured:** `"U.S. Open"`, `"The Memorial Tournament"` (byte-identical across the 4
  series per tournament).
- **Exclusion neighbors (guard tests must reject → must resolve UNKNOWN, not golf):** `KXPGAR1TOP5`,
  `KXPGAR2TOP10` (round finishers), `KXPGAH2H` — these share the SAME `golf_competitor` UUID + competition
  string, so they would false-positive if golf owned them. `exact_series` (PR 2) excludes them for free;
  the mismatch/guard tests in the golf plan stay mandatory.
- **⚠ Caveat:** competition-string consistency confirmed on only **2 tournaments** — add a test on ≥3 more
  before trusting the string match across the full PGA calendar (does NOT block v1 register).

## Q2 — Soccer World Cup: ✅ GREEN; structures confirmed; fixtures capturable

- **Register ONLY the live series** in `exact_series`: **`KXWCGAME`** (3-way Home/Away/Tie,
  `mutually_exclusive=true`, MECNET) and **`KXWCROUND`** (per-team reach-stage, ME=false: RO16/QUAR/SEMI/
  FINAL). **Exclude** `KXWCSTAGE` (regional furthest-stage, `Sporting Outcome` field) and
  `KXWCGROUPWINNER` (12-outcome `Participant` field) — field-shaped, not laddered.
- **⚠ REVISION vs UNIFIED-PLAN:** `KXFIFAGAME` has **0 live markets**; `KXFIFAADVANCE` was **not found**
  live. Do NOT register either yet — keep as seeds. (The plan's exact_series set must drop them.)
- **Constant Tie UUID (pin as a named constant):**
  `custom_strike.soccer_team = 111193d4-9b1f-4bd8-ab7c-9de252737f05` — reused across ALL KXWCGAME events; a
  placeholder, NOT a team. The n-outcome detector treats it as the draw leg (non-participant), and proves
  completeness against the event `mutually_exclusive` flag, not the UUID set.
- **Pinned reject tokens:** `cancelled`, `rescheduled` (>2 weeks), `fair price`, `withdraws`/`forfeits`/
  `disqualified`.
- **Draw-excluded phrases:** group game = **"does not include extra time or penalties"** (what makes it a
  true 3-way MECE); knockout reach (`KXWCROUND`) = **"qualify" / "one of the teams to qualify for the
  [Stage]"** (pure binary reach, no draw).
- **Fixtures to snapshot into `tests/fixtures/soccer/`:** `KXWCGAME-26JUN11MEXRSA` (full 3-outcome, incl.
  Tie UUID); `KXWCROUND-26RO16` + `-PAR` market; `KXWCSTAGE-26EUR` + `-FW`; `KXWCGROUPWINNER-26` + `-A`;
  the A–L group roster table (from `rules_secondary`) for completeness proofs.

## Q3 — POST /scan contract: ⚠ OWNER DECISION (no unilateral pick)

`/scan` is synchronous today (200 + full `ScanResult`; `api.py:217-232`). Two paths:
- **Option A — hard break (202 default):** non-blocking from day 1, honest HTTP. **Breaks all 3 existing
  scan tests** (`test_scan_writes_via_stub_fetch`, `test_scan_ttl_guard_skip_and_force` assert on the 200
  body) → ~8–12 new + 4–6 rewritten tests; external callers must poll. Adds `GET /scan_status/{id}` +
  `GET /scan_result/{id}` + task tracking.
- **Option B — `?wait=true` back-compat (default blocking):** **0 existing tests break** (additive ~6–8
  new); same two new endpoints behind an opt-in `?wait=false`. Imperfect HTTP honesty; needs a later
  migration to flip the default. `webui/engine.run_scan_now` (in-process) is unaffected either way.
- Gates **nicegui Phase E PR 21** only — not Phase C/D.

## Phase readiness
- **Phase C — Golf register:** 🟢 GREEN (exact_series + the mismatch guard test; competition-string caveat).
- **Phase C — Soccer register:** 🟢 GREEN (register KXWCGAME + KXWCROUND only).
- **Phase D — n-outcome detector:** 🟢 GREEN (3-way MECE fully characterized; Tie-UUID-as-draw-leg pinned).

## Caveated / unverifiable-live
1. Golf competition strings: only 2 tournaments checked.
2. `KXFIFAGAME`: 0 live markets — mirror-of-KXWCGAME is assumed, not observed.
3. `KXFIFAADVANCE`: not found live — speculative seed only.
4. Golf `KXPGATOURCHAMP`/`KXPGAWIN`: exist but no open events (low collision risk only because no live data).
