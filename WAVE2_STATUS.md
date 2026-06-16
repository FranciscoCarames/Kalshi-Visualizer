# Wave 2 — implementation status (live-probe gated)

Branch `feat/detector-audit-wave1-2`. Wave 1 (A1–A8) + Wave 1b shipped & verified (see commits).
Wave 2 items are each gated by the plan's **per-wave acceptance gate** — a live read-only
`/series`+`/events` probe confirming the **settlement shape** (MECE / tie / push / floor) *before*
enabling, plus checked-in fixtures + a payout-floor test. This file records the gate outcomes from a
live probe run on **2026-06-16** (read-only, no auth — market data is public).

## Live season snapshot (2026-06-16 probe)

| Series | Open events | In scope now? |
|---|---|---|
| `KXWCGAME` / `KXWCGROUPQUAL` / `KXWCGROUPBOTTOM` / `KXWCSTAGEOFELIM` | 55 / 12 / 12 / 48 | ✅ World Cup in-season |
| `KXWCTEAMH2H` | 11 | ✅ probed → **#10 shipped (recognized, review-only)** |
| `KXATPMATCH` / `KXWTAMATCH` | 13 / 13 | ✅ tennis in-season |
| `KXATPSETWINNER` / `KXWTASETWINNER` | 26 / 26 | ✅ live → **#3 probed: gate FAILED (see below)** |
| `KXNBASERIES` / `KXNHLSERIES` / `KXMLBSERIES` | 0 / 0 / 0 | ❌ off-season (cannot validate) |
| Non-FO tennis winners (Wimbledon/US Open/Masters) | n/a | ❌ series tickers unknown (need discovery probe) |

## Per-item status

- **#10 `KXWCTEAMH2H` — SHIPPED (gate-compliant).** Probe **corrected the plan**: it is a **3-way** set
  (`<A> further` / `<B> further` / `Eliminated same stage`), **not** the 2-way the plan assumed, with
  markets **not** flagged `mutually_exclusive` and a tournament-long same-stage-tie settlement. Routed as
  **recognized + "other"** (visible in coverage, never fetched/detected, never a false edge). Fixture:
  `tests/fixtures/wc_team_h2h/`. Promotion to a review-only 3-way detector is gated on Kalshi flagging
  `mutually_exclusive` + confirming same-stage exhaustiveness.

- **#3 Tennis Set Winner — GATE FAILED (do not detect yet).** A per-set pair `{A wins set N, B wins set N}`
  looks like a 2-way MECE, but the live rules (`KXATPSETWINNER-…`) do **not** establish the 100¢ floor for
  an **unplayed set** (a best-of-3 ending 2-0, or a retirement before set N): both legs may settle **No**,
  so buying both YES could lose everything — not a floor. Until the rules prove an unplayed set
  **voids/refunds**, even a review-only dutch book would be unsafe. Stays classified-but-undetected (the
  existing safe state).

- **#1 / #2 Scalar over/under (+ Σ=100 dutch pair) — GATED.** Needs a concrete half-point, no-push scope +
  a per-scope live push-rule probe + structured-strike line matching. Not started (no verified scope).

- **#4 Tennis bracket rungs — GATED (probe-driven per tournament).** Needs live `KXATPADVANCE`/`KXWTAADVANCE`
  round + draw-shape confirmation per event; draws vary (32/48/64/96, byes) so no fixed ladder.

- **#5 NBA/NHL middle rungs — BLOCKED (off-season).** No open `KX*SERIES`/playoff events to confirm the
  exact stage semantics ("Reach 2nd round" ≠ "Win 1st round"). A6 already surfaces these as unmapped-advance
  coverage when they reappear.

- **#6 `KXWCSTAGEOFELIM` overround / #7 `group_bottom` precedence — DESIGN GUIDANCE (nothing to build yet).**
  Both are conditional ("*if* an overround is worth adding…") + dedup/precedence guidance. No overround is
  emitted on these today (group_bottom is correctly out of `field_families`), so there is nothing to
  de-duplicate against until such a detector is proposed with its own payout-floor proof.

- **#8 Division-winner containment (MLB/NFL) — BLOCKED (off-season + no series).** No `division_winner`
  series exists in code, and MLB/NFL are off-season — the real ticker + rule need a live probe to onboard.
  The `optional_children` ladder-leaf mechanism (used by soccer "Win group") is ready for it.

- **#9 NHL/NBA series-result synthetic bundles — BLOCKED (off-season).** `KXNBASERIES`/`KXNHLSERIES` have 0
  open events; review-only by design once in-season.

- **#11 Tennis non-FO winners — GATED (series discovery).** Probed guesses (`KXWIMBLEDONMEN`, `KXUSOPENMEN`,
  `KXATPWINNER`) all return 0 — the real per-tournament winner tickers must be discovered live. Retiring the
  stale `config.FO_WINDOW` is deferred to this item (removing it without the replacement would regress FO
  classification).

## Bottom line

The two in-season detector candidates (#10, #3) were taken through the acceptance-gate probe; both correctly
resolve to **"not safe to detect on current evidence"** (#10 shipped as recognition; #3 left undetected).
Every other Wave 2 item is blocked on off-season live data, undiscovered series tickers, or a settlement
proof the live rules don't currently establish. Shipping any of them on taxonomy/format assumptions would
violate the plan's #1 guardrail (settlement-shape assumptions → false-money flags). They resume the moment
the relevant competition is in-season and a live probe + fixtures pass the gate.
