---
spike: terminal-pro-mockup
created: 2026-06-11
last_updated: 2026-06-11
status: decided
verdict: yes — promote to milestone
time_box: 1 session (mockup review, no production code)
---

# Spike: Is "Terminal Pro" a sound basis for the NiceGUI UI rebuild?

## Question

`ui-mockup-7-terminal-pro.html` is the owner-chosen unified direction (Bloomberg identity + Trading
Technologies docked layout + Hybrid usability). Does it actually work as a trader workstation and is it a
sound basis for the eventual NiceGUI rebuild? Specifically:
1. Does it answer the 6 decision-checklist questions?
2. Does it preserve the strict invariants (read-only / no-order-entry / label discipline /
   Actionable·Review·Blocked·Research separation / $1 basis / never "riskless/arbitrage")?
3. How cleanly does the paradigm map to MASTER_BACKLOG §9?
4. What's faked vs real, and what are the real gaps/risks for the rebuild?

## Approach

Read the mockup + its three ingredients (`ui-redesign-mockup.html`, `ui-mockup-2-terminal.html`,
`ui-mockup-3-workspace.html`), MASTER_BACKLOG §9, and the real UI layer (`webui/dashboard.py`,
`webui/viewmodel.py`) for fidelity. Drive the mockup in-browser (done during build: 0 JS errors at 1280px,
themes/lens/row→ladder+card/research-tab/simulate-scan all verified).

## Findings

### 1. Decision-checklist coverage — mostly YES
| # | Question | Verdict | Where / gap |
|---|---|---|---|
| 1 | What deserves attention now? | ✅ | Landing tiles (Act-now/Review/New/Movers/Stale) + blotter ranked by lens + Watch/Movers panel |
| 2 | Actionable vs review-only vs blocked? | ✅ | Blotter tabs + per-bucket colour+label+icon; Research kept visually distinct |
| 3 | Why was this row flagged? | ✅ | DES card "Why flagged / ranked / improve / risk" prose |
| 4 | Fill / liquidity limitation? | ⚠️ partial | MD ladder + fillable + eff-fill@50 — but the **depth is synthetic** and real orderbook depth is **not yet a proven data source** (see risk R1) |
| 5 | What changed since last scan? | ✅ (shallow) | NEW/▲/▼/↺ signals + green flash + Movers + alerts "became/bucket changed"; no timeline/replay yet (§9.3 deferred — fine) |
| 6 | Is the data fresh & trustworthy? | ✅ | Always-on status/trust line: scan age+phase, contracts/checks/req, exchange, failed-series, "trading-paused ≠ data-stale", the gross/read-only disclaimer |

### 2. Invariants — well preserved
- **Read-only / no order entry:** strong. MD ladder carries a permanent `READ-ONLY DEPTH VIEW — NO ORDERS`
  banner and has zero buy/sell/qty/ticket controls. Audit's #1 risk is handled.
- **Label discipline:** disclaimer reads `GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY ·
  NOT RISKLESS`; no "arbitrage/locked/riskless" anywhere. On-policy.
- **Bucket separation:** Actionable/Review/Blocked are distinct tabs with colour+text+icon; Research is
  violet + "research — not a trade" + no edge/ROI/tradable framing. Good — but see G3.
- **$1 basis:** canonical; $100 is a derived toggle on the DES card. On-policy.

### 3. Roadmap §9 mapping — clean
3 surfaces (OPP/RES/OPS via function codes + clickable tabs) · status/trust strip (§14) · standardized
TradeCard with legs/9-dim confidence/depth/tape/scenario/EvidencePack/why-blocks (§8/§3) · lens switcher =
seed of the lens library (§7) · alerts (§10) · watchlist (§9.3) · Research surface (§5/§11) · Operations
surface (§1/§13). Every roadmap region already has a slot — the paradigm scales.

### 4. Real-vs-mock fidelity — the honest gaps
- **Engine data exists for the blotter.** Real columns (`MAIN_COLUMNS`) and the 5 lenses (`RANK_MODES`)
  already exist; mapping the blotter to `scanner.unified_opportunities` is straightforward.
- **The aesthetic is NOT a Quasar reskin.** Today's UI is Quasar `ui.table` in `webui/dashboard.py`. The
  amber-CRT density, multi-panel **docking**, the **command-line/function-code parser**, and the **MD
  ladder** are all well beyond restyling Quasar — they imply heavy custom CSS + Vue slots / a grid lib +
  a JS command layer. Feasible in NiceGUI (arbitrary HTML/Vue) but a **substantial front-end build**, and
  it may be the thing that finally trips §13's "dedicated React/AG-Grid front end if the NiceGUI wrapper
  blocks core UX" trigger. This is the dominant technical unknown.
- **Much of the card is roadmap-future, not current engine output:** 9-dim confidence, EvidencePack,
  tape, scenario table, lens library beyond the 5 modes, RES/OPS surfaces, alerts. The mockup shows the
  destination; the rebuild must **phase** these and keep §0.1 isolation (any model/EV/confidence is
  display + opt-in sort only, never classify/bucket/rank).

### Risks / gaps
- **R1 (biggest): MD ladder depth data is unproven.** The DOM panel is the visual centrepiece, but Kalshi
  orderbook auth is documentation-conflicted → `(probe)` in §1, and the app is unauthenticated by default.
  Without proven depth access the ladder can only show **top-of-book**, not a real DOM. Don't commit the
  full ladder until the orderbook probe lands; ship a clearly-labelled top-of-book "depth preview" first.
- **R2: NiceGUI feasibility of the dense terminal shell** (docking + command line + amber grid) is
  unvalidated — see fidelity above. Needs its own thin feasibility spike before a full commit.
- **G3: Research appears in two places** — a blotter "Research" tab AND the RES surface. To honour §0.1
  separation strictly, research should live ONLY on the RES surface + as card-attached evidence, never as
  a row in the executable blotter (even if styled differently).
- **G4: default theme.** Amber-on-black is the signature but can fatigue; the HC toggle mitigates. Owner
  decision: balanced-dark default with amber as an opt-in "terminal" theme, or amber default?
- **G5: accessibility (§9.3)** — amber + colour coding needs colourblind-safe, non-colour-only cues
  carried through to the rebuild.

## Verdict

**Status:** decided — **yes — promote to milestone** (topic: `dashboard-usability`).

Terminal Pro is the strongest direction so far: it answers the decision questions, preserves every strict
invariant, and maps cleanly onto the whole §9 roadmap with a slot for each future family. It is a sound
**spec** for the rebuild — *as a phased build*, not a single drop.

**Do first (gating, before heavy build):**
1. **Probe orderbook depth (R1)** — decide whether the MD ladder is a real DOM or a labelled top-of-book
   preview. Gates the centrepiece.
2. **NiceGUI shell feasibility spike (R2)** — build ONE slice for real (amber theme + blotter as the grid +
   the command line + one docked panel) to confirm NiceGUI can carry the aesthetic, or trigger the
   dedicated-frontend decision.

**Then phase the rebuild milestone:**
- P1 — shell from real engine: command line + status/trust strip + tiles + blotter (real
  `unified_opportunities`, real lenses), full clickable nav (command line = accelerator, not required).
- P2 — DES trade-card from real fields (legs / quote / EvidencePack); confidence only for dimensions that
  actually exist; $1⇄$100.
- P3 — MD ladder (gated on R1).
- P4 — RES / OPS surfaces + alerts (roadmap-future; every metric behind §0.1 isolation tests).

**Refinements:** move Research off the executable blotter (G3); owner-pick default theme (G4); carry
accessibility cues (G5).

**Next command:**
`plan-milestone --from-spike .kss/spikes/20260611-terminal-pro-mockup/README.md`
(Holds to branch-only delivery; `main` frozen; preserve §0 invariants + the pure `viewmodel.py`/`filters.py`
split. Owner must approve the look before any production code.)

---
*Created via spike on 2026-06-11*
