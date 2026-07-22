# Comprehensive UI + Strategy QA Audit — Kalshi Structured Scanner (SPA)

> **Purpose of this file:** a complete, self-contained QA report **plus a resume guide** so a new
> Claude Code session can pick up and finish the **untested / low-confidence** areas (§10) without
> re-deriving context. Read §0 (Resume guide) first, then §10 for the remaining work.
>
> - **Date:** 2026-06-18 · **Branch/commit:** `feat/scanner-bugfixes` @ `4e3d285`
> - **Scope:** comprehensive test of the React SPA at `/` (the default UI). Report-only — **no code changes were made.**
> - **Status:** **Three passes complete (§12 + §13 added 2026-06-18).** Pass 1 ~22 pass · 6 partial · 6 fail · ~14 not-tested;
>   pass 2 cleared the §10 not-tested list (16 items) + **live Kalshi API cross-check**; pass 3 cleared 12 previously-uncovered
>   areas (auth, SSE, dark detectors, per-sport depth, reorder/text-size/export/deep-links/quote-states/pop-out, backlog perf).
>   **C2 resolved** (Kalshi reports fractional sizes — not a bug); **M1 resolved** (prefs persist under auth); **C1 + H1 stand**;
>   new: **N1** (layout floor), **N2** (CSV cents mis-scale). Only-known open defects: **C1** (gross-led ranking), **H1**
>   (28.7 MB backlog), **N1/N2**. See **§12** (pass 2) and **§13** (pass 3). Still uncovered: NiceGUI `/dashboard`, real mobile.

---

## 0. RESUME GUIDE (read this first)

### 0.1 How to run the app exactly as it was tested
```bash
cd "C:/Users/Batata/Desktop/Projects/Kalshi Visualizer/main"
AUTH_ENABLED=0 API_PORT=8011 API_HOST=127.0.0.1 python serve.py    # SPA at http://127.0.0.1:8011/
```
- Serves the SPA from `frontend/dist` (already built) reading the persisted `snapshots.db` (1.8 GB).
- **No live Kalshi network is required to boot** — it boots from the snapshot store. BUT: the browser's
  feed poll counts as a "viewer" and triggers **background auto-scans** (presence gate), which DO hit
  Kalshi live and advance the snapshot id. So data changes under you while testing.

### 0.2 Critical environment facts (so you don't get fooled)
- **Data is volatile across scans.** Observed snapshot ids 969 → 972 within ~20 min; sports present went
  `{Motorsport, Esports}` → 8 sports; **ACTIONABLE count swung 2 → 3 → 11**. This is caused by HTTP 429
  rate-limits (see Finding H2), not a bug per se — each scan covers a *different* partial subset.
- **To freeze the DOM for testing:** open ⚙ SETTINGS → set **Auto-refresh = off**. Otherwise refs churn
  every ~10s and Playwright refs go stale (re-snapshot before each click, or use CSS/text selectors).
- **Staleness gate:** with auto-refresh off, after ~5 min the snapshot ages and `Tradable` flips from
  `● Yes` to `○ No — stale snapshot`. Force a fresh scan with the `▷ SCAN` / `⚡` buttons to re-arm.
- **Prefs don't persist** with `AUTH_ENABLED=0`: `GET`/`PUT /auth/preferences` both 401 (Finding M1), so
  any setting/column/layout change is session-only and resets on reload.

### 0.3 Tooling note (important)
- **Playwright MCP was used for ALL browser interaction** (`mcp__plugin_playwright_playwright__*`).
- The **Claude-in-Chrome extension is NOT wired into the session** (registry checked; no bridge tool).
  The user has it installed but it isn't exposed as a connector here. If a future session has it
  connected, prefer it for tests that need the user's real logged-in Chrome (e.g. `AUTH_ENABLED=1`).
- Useful read-only verification without a browser:
  ```bash
  curl -s http://127.0.0.1:8011/api/terminal/feed -o feed.json          # full opportunity feed
  curl -s "http://127.0.0.1:8011/api/terminal/orderbook?ticker=TICKER"   # raw book for a leg
  curl -s http://127.0.0.1:8011/api/terminal/diagnostics                 # coverage + 429 failures
  ```

### 0.4 Key code locations (from frontend map)
- `frontend/src/App.tsx` — Shell, surfaces (OPP/RES/OPS/ALRT), SettingsMenu, SecBar (band controls)
- `Workspace.tsx` — drag splitters (`dragV`/`dragH`), pop-out (`PopoutPortal`), panel show/hide
- `Blotter.tsx` — scanner table, column chooser, sorting; `columns.ts` — COLS catalog + `qualityOf`
- `Inspector.tsx` — trade card / FORMULAS / PARTICIPANT DETAIL; `Ladder.tsx` — depth ladder + rung picker
- `filters.ts` — membership vs threshold split; `feed.ts` — ZONES/SECTIONS/TILES taxonomy
- `detail.ts` — `/api/terminal/{detail,ladder,orderbook,payoff,diagnostics,telemetry}` + `/backlog*`
- Backend size parse (Finding C2): `data.py:747` `bid_size = to_float(market.get("yes_bid_size_fp"))`
- Orderbook parse (integer sizes): `kalshi_client.py:254 get_orderbook` (reads `orderbook_fp`)

### 0.5 Verdict carried forward
**Ship only after fixes.** Engine math is correct (dutch-book, fees, ladder all validated). Problems are
in **defaults, data completeness, performance, one wording slip** — see §7. Priority fix order in §11.

---

## 1. Executive summary
The SPA is unusually disciplined about conservative framing (gross/top-of-book banners, net-edge columns,
thorough caveats, an in-UI formula tab). Verified engine math is **correct**. Problems concentrate in
defaults, data completeness, performance, and one wording slip — not the detector logic.

**Critical / highest-risk:**
- **C1** — Every "ACTIONABLE / executable now" dutch book in every snapshot was **net-negative after fees**,
  yet ranked #1 by **gross** edge (Motorsport, Soccer, Esports, NBA). Disclosure exists; default posture is wrong.
- **C2** — **Fractional contract sizes** ("MAX UNITS 136.6", "89.58 avail") feed headline economics and
  disagree with the integer order book the same app shows in the depth ladder.
- **H1** — ALRT surface downloads **~26 MB** (`/backlog/events?days=7`) → **~2.1 MB DOM**, multi-second hang.
- **H2** — **39–66 of ~158 series fail per scan (HTTP 429)**; snapshots are partial and counts swing 2→3→11.

---

## 2. Environment tested
| Field | Value |
|---|---|
| App URL | `http://127.0.0.1:8011/` (SPA at `/`) |
| Branch / commit | `feat/scanner-bugfixes` @ `4e3d285` (footer `· 4e3d285 · 2026-06-18`) |
| Launch | `AUTH_ENABLED=0 API_PORT=8011 python serve.py` |
| Browser | Chromium via Playwright MCP |
| Date | 2026-06-18 ~14:36–14:55 UTC |
| Data mode | Live, served from persisted snapshot store; browser poll triggers background scans (#969→#972) |
| Tools | Playwright MCP, repo code inspection, WebFetch (`docs.kalshi.com`) |
| Tool caveat | Claude-in-Chrome extension NOT available as a tool; all browser work via Playwright |

---

## 3. Coverage matrix (sport × opportunity type)
Types emitted: **DUTCH_BOOK** (field-overround / soccer 3-way / 2-way game), **CONTAINMENT/bounded** (RISK_BUDGET),
**NEAR-MISS**, **CHEAP-NO** (outright/band), **QUALIFIER** (synthetic bundle), **DATA-QUALITY**.
`EXECUTABLE_VIOLATION` (containment cross) and `EXECUTABLE_SYNTHETIC_BUNDLE` produced **no actionable instances**.

Legend: ✅ tested live · 🟡 present, lightly checked · ➖ no instance this session · ❌ sport absent (429/off-season)

| Sport | Dutch | Containment/bounded | Near-miss | Cheap-NO | Qualifier | Data-quality |
|---|---|---|---|---|---|---|
| Motorsport | ✅ field overround (NASCAR Truck) | ✅ "Win Race ≤ Top 10" | 🟡 | 🟡 | ➖ | ✅ |
| Soccer (WC) | ✅ 3-way game (ARG v AUT) | ➖ | 🟡 | 🟡 | ➖(0) | ✅ |
| Esports | ✅ 2-way game (COD, R6) | 🟡 | 🟡 | 🟡 | n/a | ✅ |
| NBA | ✅ winner field | 🟡 | 🟡 | 🟡 | n/a | ✅ |
| Tennis | ➖ | ➖ | 🟡 | ✅ (Vergara ITF) | ➖ | ✅ |
| WNBA | ➖ | ➖ | 🟡 | 🟡 | n/a | ✅ |
| NFL | ➖ | ➖ | 🟡 | 🟡 | n/a | ✅ |
| MLB | ➖ | ➖ | 🟡 | 🟡 | n/a | ✅ |
| NHL | ❌ (429) | — | — | — | — | — |
| Golf | ❌ (not seen) | — | — | — | — | — |

Untested combos are mostly "No available opportunity" (season / 429 coverage gaps). Synthetic QUALIFIER and
containment `EXECUTABLE_VIOLATION` families could NOT be exercised live — revisit in-season.

---

## 4. UI test matrix
| Area | Feature | Action | Expected | Actual | Result | Sev |
|---|---|---|---|---|---|---|
| Load | Initial render | Open `/` | Clean | Renders; **2 console errors** `401 /auth/preferences` | Fail | Med |
| Prefs | Persist | Toggle any setting | Saved | `PUT /auth/preferences` 401; no persistence | Fail | Med |
| Filter | Hide fee-negative | Settings toggle | Hide net-neg | Both rows hidden, "2 hidden by fee filter", tiles→0 | Pass | — |
| Filter | Auto-refresh off | Set "off" | Stop polling | Snapshot stopped advancing | Pass | — |
| Theme | Toggle | Click ◐ | amber↔hc | `data-theme` amber→hc | Pass | — |
| Tiles | Section nav | Click BOUNDED-LOSS | Show section | URL `?zone=spec&section=bounded`; **0 of 2** (5¢ band hides all) | Partial | Med |
| Scanner | Sorting | Click "Buy NO ¢" | Sort asc | `sort buy_no ▲`, 3,5,7,9,9,10 | Pass | — |
| Scanner | Cheap-NO subtabs | — | All/Event/Tournament/Championship | Present | Pass | — |
| Filter | Participant | Type "Vergara" | Narrow | 1 of 1, URL `&part=Vergara` | Pass | — |
| Palette | Ctrl-K | Press | Open+focus | SURFACE/LENS/SECTION cats | Pass | — |
| Inspector | Trade card | Select row | Legs+econ+fees+evidence | Full 20-leg render, per-leg fees | Pass | — |
| Inspector | FORMULAS tab | Click | Formula breakdown | Real numbers, fee formula shown | Pass | — |
| Inspector | "Best case" wording | Read | Conservative | **"+3¢ locked gross"** — banned word "locked" | Fail | Med |
| Ladder | Depth book | Select leg | Match Kalshi book | **Exact match** to raw `/orderbook` | Pass | — |
| Econ | Max units | Read | Integer | Fractional ("136.6", "89.58") — **matches Kalshi `*_size_fp` (§12.1); faithful, not a bug** | Pass* | Low |
| OPS | Coverage | Open | Failures listed | 39–66 series 429-failed, surfaced | Pass | — |
| ALRT | Backlog | Open | Table | Renders but **26 MB / 2.1 MB DOM / multi-s hang** | Fail | High |
| Status | Volatility | Re-scan | Stable | actionable 2→3→11 across scans | Partial | High |
| API | Endpoints | curl | 200 | telemetry/payoff/ladder/health 200; backlog slow | Partial | — |

---

## 5. Strategy audits

### A — Motorsport / Dutch field-overround / `34abf8ce1031da52` (NASCAR Truck NAV26 winner field)
Buy NO on every priceable driver in a one-winner field. 20 legs @69–99¢, cost **1897¢**, gross **+3¢**,
**max units 1** (two legs only 1 contract deep), fees $0.22, **net −$0.19**, tradable "Yes".
- Worst/best case both ≈+3¢ gross ("field ≥"); after fees the whole $18.97 position nets **−19¢**.
- **Verdict: Mostly correct but misleading-by-ranking.** Math right & well-caveated, but a 1-unit,
  fee-negative, 20-leg position is the #1 ACTIONABLE item. Also uses banned word "locked gross" (M2).

### B — Soccer / Dutch 3-way game / `Argentina vs Austria` (`KXWCGAME-26JUN22ARGAUT`)
MECE {Argentina, Austria, Tie}. Buy NO all three. **Verified vs live book:** ARG 37¢ (YES bid 63),
AUT 85¢ (YES bid 15), TIE 77¢ (YES bid 23) → Σ199¢, payout 200¢ → **gross +1¢ ✓**. Max units 134,
fees **$5.06**, **net −$3.72**. Fee math reproduced exactly:
`0.07 × 134 × (0.37·0.63 + 0.85·0.15 + 0.77·0.23)` per-leg round-up = **$5.06 ✓**.
- **Verdict: Correct math, misleading actionability** (guaranteed net loss). Postponement caveat correct;
  June 22 is group stage so Tie is legit (3-way MECE).

### C — Esports / Dutch 2-way game / `FaZe Vegas vs Riyadh Falcons` (`KXCODGAME…`)
Buy YES both (underround) 59+40=99¢, gross +1¢, max units 101, fees $3.42, **net −$2.41**. Draw-free →
2-way MECE valid. **Verdict: Correct math, net-negative, disclosed-but-toppled.**

### D — Motorsport / Containment bounded-loss / "Adam Andretti — Win Race ≤ Top 10" (`RISK_BUDGET_CANDIDATE`)
Buy Top-10 YES 24¢ + Buy "Win race" NO 99¢. cost 123¢, max loss 23¢, max profit 77¢, **legs `sz:0`**,
tradable "No — stale", `RULE_CHECK_REQUIRED`. **Verdict: Not executable (zero size); correctly routed to
bounded-loss, not ACTIONABLE.** Hidden by default 5¢ band (M3).

### (Also observed) NBA winner field — net −$2.96, MAX UNITS **136.6** (fractional → C2), fees $8.42.

---

## 6. Kalshi data validation (vs docs.kalshi.com + live /orderbook)
- **`no_ask = 1 − yes_bid`**: ✅ confirmed by docs and ladder math (Buy NO 99¢ ↔ YES bid 1¢).
- **Order book bids-only both sides**: ✅ matches `get_orderbook` (`orderbook_fp.yes/no_dollars`) + ladder legend.
- **Fee model `0.07·c·p·(1−p)`, per-order round-up**: ✅ reproduced exactly ($5.06 soccer, $8.42 NBA,
  $0.22 NASCAR); FORMULAS tab prints the formula. Consistent with prior fee-schedule verification.
- **Fixed-point `*_fp` → ÷10⁸ (per docs)**: app uses `to_float(yes_bid_size_fp)` at `data.py:747` with **no
  documented conversion** and shows **fractional** sizes (89.58, 136.6, 51069.61), while `/orderbook`
  returns **integers** (ANPE live = `yes:[[1,90]]`). → **C2 app units inconsistency.** Root cause is
  medium-confidence (no raw market payload accessible from sandbox); the *internal* panel inconsistency is high-confidence.
- **Cause classification:** 429 failures = Kalshi rate-limit (surfaced correctly); net-negative "actionable"
  = app UX/ranking; fractional size = app data/units.

---

## 7. Bugs and issues

### Critical
- **C1 — Net-negative dutch books ranked #1 in "ACTIONABLE · executable now."** Ranking = gross edge;
  `hideNetNegExec` off by default. *Fix:* default to net-aware ranking or default-enable hide. **Required.**
- **C2 — Fractional contract sizes in economics & buy-plan.** ~~Inspector "Max units 136.6" / leg "89.58 avail".~~
  **RESOLVED 2026-06-18 (§12.1): NOT a SPA bug.** The live Kalshi API returns these sizes fractional itself
  (`KXNBA-27-ATL yes_bid_size_fp="872.46"`, `KXNASCARRACE-NAV26-ANPE "89.58"`); `data.py:747 to_float(...)` is
  faithful — the `*_fp` suffix is a decimal string, **not** a ×10⁸ fixed-point integer. **Downgraded to LOW /
  optional:** round-or-floor fractional sizes for display readability, and note that the trade-card size
  (market `*_size_fp`) vs depth-ladder size (`/orderbook` levels) are two Kalshi feeds that can disagree. **No
  longer a required data fix.**

### High
- **H1 — ALRT fetches ~26 MB (`/backlog/events?days=7`) → ~2.1 MB DOM, multi-s hang.** Unbounded 7-day
  backlog over bloated 1.8 GB `snapshots.db`. *Fix:* paginate/cap endpoint, run `compact_store.py`, lazy-load.
- **H2 — Partial, volatile coverage.** 39–66/158 series 429-fail; actionable count swings 2→3→11. *Fix:*
  lower concurrency / honor Retry-After / spread series; add a "coverage N%" badge near the count.

### Medium
- **M1 — `401 /auth/preferences` … no persistence.** **RESOLVED 2026-06-18 (§13.1 item 1): a no-auth-mode
  artifact only.** Under `AUTH_ENABLED=1` the per-user profile (theme/settings/columns/layout) persists
  server-side in `auth.db` and **restores on login** (verified: `theme=hc`, `textSize=large` round-tripped +
  survived re-login). The 401s are expected when auth is off (no session to attach prefs to).
- **M2 — "locked gross" wording** in inspector best-case (project bans "locked/riskless/true arbitrage").
- **M3 — Default bands silently zero whole categories** (BOUNDED-LOSS tile "0" despite 2 in-scope; 5¢ band).
- **M4 — "Payout÷cost 33.3×" framing** on cheap-NO longshots invites lottery-ticket misreading.
- **N1 — First workspace column has no min-width floor** (`Workspace.tsx` `1fr`); the first vsplit drags to
  ~0 and hides Scanner+Inspector until RESET. Only the M/R columns clamp `[60,1000]`. *(Found 2026-06-18, §12.4.)*
- **N2 — Client ⬇ CSV mis-scales cents columns.** `csv.ts` dumps raw values, so `Est. net edge $`/`Est. fees $`
  (`"cmoney"`) export as un-scaled cents under `$` headers (e.g. `842` = $8.42) alongside true-dollar columns.
  Server ZIP CSV is fine. *Fix: apply the column `fmt`. (Found 2026-06-18, §12.4.)*

### Low
- **L1** — Empty-state copy says "section / band filters" even when the **fee** filter hid the rows.
- **L2** — Section lenses not fully tailored (RIPENESS/SETUP QUALITY offered on cheap-NO outrights).
- **L3** — Row click drops URL query params (`?…section=act` → `/`).
- **L4** — ALRT badge count vs ALERTS panel list inconsistency when fee-negative hidden.

---

## 8. UX & product concerns
- Biggest concern is the **ACTIONABLE default** (gross-led, fee-losers on top, "Tradable: Yes").
- **Coverage opacity:** with up to 42% of series failing, the count reflects *what got scanned*, not the market.
- Counts are **post-band** (tiles = scanner subtabs, internally consistent) while `meta.totals` is raw —
  combined with M3, users can conclude "nothing here" when defaults are simply hiding everything.
- **Preserve the good:** GROSS/NOT-RISKLESS banner, per-leg fee breakdown, FORMULAS tab, stale gating,
  settlement caveats, the ladder's correct YES/NO inversion legend.

---

## 9. Default column assessment
- Executable defaults (11) are reasonable — **net columns are present**. Flaw is **ordering/sort**: Gross
  edge ¢ leads and is the sort key. **Recommend default sort = Est. net edge $ desc.**
- Add a **liquidity hint (min leg depth)** to expose the "Max units = 1" trap without opening the inspector.
- Cheap-NO: demote "Payout÷cost" below Breakeven % / Max loss ¢.
- Bounded-loss (26 cols) fine as opt-in; pair with a more permissive default band or clearer "0 (filtered)" tile.

---

## 10. UNTESTED / LOW-CONFIDENCE AREAS  ← **NEXT-SESSION WORK LIST**
Each item: what to test + concrete steps/selectors. Use §0.2 (freeze DOM) first.

1. **Draggable / resizable layout** (`Workspace.tsx`): drag vertical splitters (`.vsplit`) & horizontal
   (`.hsplit`); verify clamp (60–1000px / 24–2000px), persistence (won't persist under no-auth → M1),
   overlap/clip states. Use `browser_drag`.
2. **Pop-out window** ("⧉" dock button): opens independent workspace; verify it shares feed data but own
   view state, theme inherits, auto-closes. (Playwright multi-window via `browser_tabs`.)
3. **Layout presets** (LAYOUT dropdown: Default/Triage/Inspect/Research/Scanner full) + `⟲ RESET` +
   `＋ ADD ▾` / `▦ ELEMENTS ▾` show/hide panels. Verify each preset renders the expected panel set.
4. **Panel dock buttons** per panel: `A↕` text-size cycle, `▢` maximize, `▁` collapse, `✕` remove.
5. **Column chooser** (`⚙ columns ▾`): toggle non-default columns on/off, "reset to defaults", verify
   each optional column renders correct values; column reorder/resize if supported.
6. **CSV / ZIP export** (`⬇ CSV`, `⬇ ZIP`): trigger download, validate file contents vs on-screen rows
   (units, rounding, headers). ZIP = filtered snapshot + evidence frames + manifest.
7. **Remaining filters:** Tournament multiselect (cascades to selected sports), MIN SIZE spinbutton,
   Tradable-only checkbox — drive each and confirm membership vs threshold behavior (`filters.ts`).
8. **RES surface** content (telemetry: top sports/contracts/tightest/most-traded/volatility) — visually validate.
9. **Inspector PARTICIPANT DETAIL tab + ladder rung picker for a true containment row** — needs an
   `EXECUTABLE_VIOLATION` / containment row (none live this session). Force in-season or seed a snapshot.
   Verify rung dropdown (`select.in`), participant chooser (`.pchooser`), chain rungs.
10. **Keyboard nav:** `J/K` row move, `1-6` lens, `/` palette, `Esc` close; multi-select `Ctrl/Shift-click`
    → CompareView / OverlapView / LaddersView (`panels.tsx`).
11. **Tooltips/hover** (book-depth "avail" tip, ticker tips, quote-health) — content + positioning + overlap.
12. **Mobile / responsive** (`browser_resize` to phone widths) — the LAN runbook implies phone access.
13. **Error/empty states:** simulate `/orderbook` failure (closed market), empty book, crossed/one-sided
    book; confirm honest degrade (endpoint already returns `ok:false` not 500).
14. **Golf / NHL** — entirely absent; revisit when 429s clear / in-season.
15. **C2 root cause** — obtain a raw Kalshi `/markets` payload to confirm whether `yes_bid_size_fp` needs
    ÷10⁸ or is genuinely fractional; decide display rounding.
16. **Synthetic QUALIFIER bundles** and **field-underround / advancement-field** detectors — no live
    instances; need tennis Grand Slam window (synthetic) or owner-gated detectors.

---

## 11. Recommended next actions (priority)
1. Fix **C1** (net-aware ACTIONABLE ranking / default-on hide-fee-negative).
2. Fix **C2** (confirm `yes_bid_size_fp` fixed-point, round display, reconcile with order-book sizes).
3. Fix **H1** (bound/paginate `/backlog/events`; `compact_store.py`; lazy-load ALRT).
4. Mitigate **H2** (coverage% badge; throttle/concurrency tuning to cut 429s).
5. Quick wins: M1 (prefs under no-auth), M2 ("locked" wording), L1/L3.
6. Finish §10 testing (ideally in-season so synthetic + containment families can be audited live).

---

## 12. SECOND-PASS RESULTS — §10 coverage (2026-06-18, Chrome-extension session)

> Second pass run the same day on the **same branch/commit** (`feat/scanner-bugfixes` @ `4e3d285`), this
> time with the **Claude-in-Chrome extension connected** (so the SPA could be driven *and* cross-checked
> against the **live Kalshi API**, which the first pass could not do). Snapshots observed: **#975 → #979**
> (data volatile as before — actionable swung 7↔8; **NHL and Golf each appeared in some snapshots and were
> absent in others**, see H2). Auto-refresh set to **off** to freeze the DOM. Still **report-only — no code
> changes.**

### 12.1 Headline correction — C2 is NOT a SPA bug (prior hypothesis refuted)
**Verified against the live Kalshi API** (`GET external-api.kalshi.com/.../markets/<ticker>`):
- `KXNBA-27-ATL` → `yes_bid_size_fp = "872.46"` — **Kalshi itself returns a fractional size**, matching the
  SPA's `sz=872.46` **exactly**. Also `yes_ask_size_fp="164367.38"`, `volume_fp="24171.89"`,
  `open_interest_fp="23971.52"` — all fractional decimal strings.
- `KXNASCARRACE-NAV26-ANPE` → `yes_bid_size_fp="89.58"` (= SPA `89.58`). `KXMLBGAME-…BOSSEA-SEA` →
  `"3.00"` (integer; = SPA `3.0`).
- **Conclusion:** the `*_fp` suffix is **NOT** a ×10⁸ fixed-point integer — it is a **decimal string that
  Kalshi may report fractional** (872.46, 89.58) or integer ("3.00"). `data.py:747 to_float(yes_bid_size_fp)`
  is **faithful**. The first pass's "needs ÷10⁸ / app misparse" theory is **wrong**. **C2 downgrades from a
  required data-bug fix to an optional display-rounding nicety** (the engine math is correct; fractional
  *availability* is real Kalshi data).
- The remaining real nuance: the **trade-card size** (market top-of-book `*_size_fp`, fractional) and the
  **depth-ladder size** (the `/orderbook` levels, integer) come from **two different Kalshi feeds** and can
  disagree (ATL showed `yes_bid_size_fp=872.46` but an **empty** `/orderbook`). That inconsistency is on
  **Kalshi's side**, faithfully mirrored — worth a one-line UI note, not a parse fix.

### 12.2 End-to-end price/edge cross-check — SPA is exactly correct
`Boston vs Seattle` (`KXMLBGAME-26JUN202210BOSSEA`) dutch book, SPA vs live Kalshi:

| leg | Kalshi `no_ask` | Kalshi size_fp | SPA leg |
|---|---|---|---|
| Buy NO Boston | 0.55 (55¢) | 100.00 | buy_no, sz 100 |
| Buy NO Seattle | 0.44 (44¢) | 3.00 | buy_no, sz 3 |

Cost 55+44 = **99¢** (SPA `cost=99`), gross edge 100−99 = **+1¢** (SPA `edge=1`), max units min(100,3) = **3**
(SPA), `net_edge=-3` (−$0.03 after fees), settlement caveat present. **Every number matches.** The Buy-NO
price = `no_ask` exactly, sizes mirror `yes_bid_size_fp`, the dutch-book floor/edge math is correct. **The
information the app displays is accurate.**

*(**Visual website confirmation (after granting site permission):** the live Kalshi page for this market shows
**Seattle No 44¢ / Boston No 55¢** — identical to the API and SPA. Prices now verified **three ways** — SPA,
Kalshi API, and the Kalshi website.)*

### 12.3 §10 item-by-item outcomes
| § | Area | Result | Notes |
|---|---|---|---|
| 10.1 | Drag/resize splitters | **Pass + new finding N1** | vsplit resize precise (649→549px); RESET restores. **N1:** only the M/R columns clamp `[60,1000]` (`Workspace.tsx:179`); the **flexible first column (`1fr`) has no min-width floor** → dragging the first splitter fully left collapses the Scanner+Inspector column to ~2px (lost until RESET). hsplit clamps `[24,2000]` both ends. |
| 10.2 | Pop-out window | **Pass (tooling-limited)** | `⧉` fires cleanly (no console error). Child window is a **separate OS window** via `window.open(...,900×840)` — outside the MCP tab group, so not screenshot-drivable here. (Programmatic `window.open` is popup-blocked without a user gesture; the real button click is a gesture, so it opens.) |
| 10.3 | Layout presets | **Pass** | Default / Triage / Inspect / Research / Scanner-full — verified 3 distinct arrangements (Default balanced, Triage scanner-wide, Inspect inspector+ladder). RESET works. |
| 10.4 | Panel dock buttons | **Pass** | Every panel has `A↕`/`⧉`/`▢`/`▁`/`✕` with correct tooltips; **maximize** verified (fills workspace, exposes full net columns); **ELEMENTS** show/hide verified (toggling RESEARCH hides/restores + reflows). |
| 10.5 | Column chooser | **Pass** | "COLUMNS · ACT" lists all 13 cols; defaults match code (`Detail`, `Action plan` off). Toggle + **reset-to-defaults** verified. |
| 10.6 | CSV export | **Pass + new finding N2** | Captured the real Blob: header + 7 rows. **N2:** `downloadCsv` dumps **raw field values** without the column formatter, so the two `"cmoney"` columns export **un-scaled cents under `$` headers** — `Est. fees $ = 842` (really $8.42), `Est. net edge $ = -2` (really −$0.02) — mixed in the same file with correct dollar columns (`Max gross profit 5.46`, `Est. net max profit -2.96`). Also exports raw fractional `Max units 136.57`. *Fix: apply the column `fmt` (or /100 the cmoney cols) in `csv.ts`.* |
| 10.6 | ZIP export | **Pass** | `POST /api/terminal/export` → 200, 414 KB. Full structure: `opportunities.csv` + per-sport `{contracts,checks,dutchbook}` frames + `backlog.csv` + `manifest.json`. Server CSV uses **explicit unit suffixes** (`*_c`/`*_dollars`/`*_pct`) — **no N2 problem**; valid UTF-8. (NHL frames present even when NHL has 0 opps — the store has the data.) |
| 10.7 | Filters | **Pass — invariant confirmed** | **MIN SIZE=100** (threshold): ACTIONABLE stays 7, DATA-QUALITY stays 1674 (both spared), SPECULATIVE 211→69 / CHEAP-NO 68→48 / BOUNDED 23→21. **Tradable-only** (threshold): ACTIONABLE stays 7 (spared *despite* all rows "No — stale"), CHEAP-NO 68→0. **Sport=NHL** (membership): narrows **every** section incl. ACTIONABLE 7→1, DATA-QUALITY→64. **Tournament** dropdown **cascades** to the selected sport. Exactly matches `filters.ts`. |
| 10.8 | RES telemetry surface | **Pass** | All 5 sections render real data (`/telemetry`): MOST LIQUID sports/contracts, TIGHTEST BOOKS, MOST TRADED, MOST VOLATILE — each with `CONTEXT`/`DISPLAY-ONLY`/"not a tradable signal" framing. |
| 10.9 | Inspector detail + rung picker | **Pass** | PARTICIPANT DETAIL = conditional-probability table P(deeper│broader) on display + bid/ask bases, badged `UNCALIBRATED · DISPLAY-ONLY · NOT FAIR VALUE`. Ladder **rung picker** exposes the full chain (Australia WC: RO16 37.5% ⊇ QF 9.5% ⊇ SF 2.5% ⊇ Final 1.5% ⊇ Win 0.2%); switching a rung repoints the depth book. No `.pchooser` in this build (participant chosen via row). No live `EXECUTABLE_VIOLATION` cross existed — exercised via the RISK_BUDGET ladder (same machinery). |
| 10.10 | Keyboard + multi-select | **Pass** | `J/K` row nav (loads trade card + ladder), `/` and Ctrl-K palette (full SURFACE+LENS catalog), `Esc` close, `1-6` lens (`2`→EDGE¢, URL `?lens=edge`). Ctrl/Shift-click → selbar "▣ N selected" → **Compare** (side-by-side metrics), **Don't-take-both/Overlap** (shared-participant heuristic, correctly "independent"), **Ladders** (N books side-by-side). *Minor:* CompareView shows `Tradable: Yes` without the staleness gate the scanner applies. *(Tooling note: the extension's synthetic ctrl-click didn't set `e.ctrlKey`; native event dispatch confirmed the feature works — real Chrome ctrl-click is fine.)* |
| 10.11 | Tooltips/hover | **Pass** | All 11 column headers carry `title` tips (sort/reorder hint + semantic tip, e.g. "Gross edge ¢" → "firm child bid − parent ask"); 61 titled elements; 5 book/avail tips. |
| 10.12 | Mobile/responsive | **Pass w/ note** | Window floors at ~509px (a min-width); below that it **reflows** tiles/panels into a scrollable **desktop-terminal** layout — **no dedicated mobile breakpoint**. The LAN runbook implies phone access; usable but horizontal-scroll heavy on a phone. |
| 10.13 | Error/empty states | **Pass** | Empty book → "no resting orders (empty or closed book)"; empty section → "No opportunities in this section for the current filters."; API: bogus ticker → `200 {yes:[],no:[],ok:true}` (graceful), empty ticker → `400`, bad detail → `422` — **never a 500**. *(Low note: an unknown ticker returns `ok:true` empty, indistinguishable from a genuinely empty book.)* |
| 10.14 | Golf / NHL | **Resolved — both DO surface, intermittently** | NHL was the **#1 actionable** in #977 (`NHL · 27 winner field`, net −$0.19); Golf had 1079 contracts in #975. Both were **absent** in #979. Confirms **H2**: coverage is a per-scan 429 lottery, not a missing sport. |
| 10.15 | C2 root cause | **Resolved** | See §12.1 — Kalshi natively reports fractional `*_size_fp`; SPA faithful. |
| 10.16 | Synthetic / field-underround | **Still no live instance** | QUALIFIER, `EXECUTABLE_VIOLATION`, `EXECUTABLE_SYNTHETIC_BUNDLE` = **0** across #975–#979 (season/event-gated; needs a tennis Grand Slam window). Unchanged from first pass. |

### 12.4 New findings this pass
- **N1 (Medium-UX)** — first workspace column has **no min-width floor**; the first vertical splitter can be
  dragged to ~0, hiding Scanner+Inspector with no recovery but RESET. *Fix: clamp the `1fr` column or give
  the panel a `min-width`.*
- **N2 (Medium — export correctness)** — client **⬇ CSV** emits raw field values without the column `fmt`, so
  the `"cmoney"` columns (`Est. net edge $`, `Est. fees $`) export as **un-scaled cents under `$` headers**
  (100× off) and mixed with true-dollar columns. The server **ZIP** CSV is fine (explicit unit suffixes).
  *Fix in `csv.ts`: format with the column's `fmt` (or divide cmoney by 100).*
- **N3 (Low)** — CompareView prints `Tradable: Yes` without applying the snapshot-staleness gate that the
  scanner/inspector use (so it can disagree with the row it came from).

### 12.5 Net effect on the verdict
The engine remains **correct** and now **independently price-verified against the live Kalshi API** (12.2).
The first pass's two "Critical" items move apart: **C1 stands** (every actionable dutch book in #975–#979 is
net-negative after fees yet gross-ranked #1 — fix the default ranking), while **C2 is downgraded** to a
display-rounding nicety (not a data bug — Kalshi's own sizes are fractional). New export bug **N2** and layout
nit **N1** are the only fresh defects; everything else in §10 passed.

---

## 13. THIRD-PASS RESULTS — previously-uncovered areas (2026-06-18)

> Owner asked to cover the 12 uncovered areas the post-pass-2 summary listed (items 1,3,4,5,6,7,8,9,10,11,12,14;
> NiceGUI `/dashboard` and real-mobile-device were not requested). Tools: Chrome extension + Playwright +
> curl/pytest. A **second server instance** was started for auth: `AUTH_ENABLED=1 API_PORT=8012` with an
> **isolated throwaway `auth_qa.db` + `snapshots_qa.db`, auto-scan off** (no real `auth.db` touched, no Kalshi
> calls). Throwaway QA account `qauser` (disposable password). Still **report-only — no app code changed.**

### 13.1 Item-by-item

| # | Area | Result | Evidence |
|---|---|---|---|
| 1 | **Auth flows** | **PASS — and resolves M1** | Auth-on instance: gate is deny-by-default (`/api/terminal/feed` → **401** unauth, **200** with session cookie; SPA shell + `/auth/*` entry points public). Login screen renders (username/password/SIGN IN/"create one"). Full flow via curl: `register`→200 (session set), `/auth/me`→qauser, `PUT/GET /auth/preferences` round-trip persists `{theme:hc,textSize:large}`, `/auth/devices`→`[]`, password change→200, re-login with new pw→200 + **profile restored**, wrong pw→generic `401` (non-enumerable). Browser round-trip: login → identity "qauser ▦ logout" shown → **persisted profile applied** (`data-theme=hc`, `data-textsize=large` confirmed in DOM) → logout returns to gate. **M1 ("prefs don't persist / 401") was a no-auth-mode artifact — under auth they persist + follow the account.** `remember_available:false` on plain HTTP (correct — needs TLS). |
| 3 | **SSE stream + live gating** | **PASS** | `GET /api/terminal/stream` streams `event: feed\ndata:{…full snapshot…}` with `content-type: text/event-stream; charset=utf-8`, `cache-control:no-cache`, `connection:keep-alive` → browser EventSource gets push updates (the comment at `api.py:449` notes it auto-gates under auth via the session cookie). The **live overlay (Stage 2A–2D) is correctly gated OFF** by default: `KALSHI_LIVE_ENABLED` unset, no live meta keys, 0 opps with live fields. The live WS collector needs an RSA Kalshi key (no credentials → not live-testable; documented). |
| 4 | **Dark detectors (no live instances)** | **PASS (unit-validated)** | `pytest tests/test_dutchbook.py tests/test_synthetic_bundle.py tests/test_consistency.py tests/test_ladder_closure.py` → **255 passed**. Named coverage of the exact dark statuses: containment cross (`test_executable_violation_requires_cross_and_size`, `…forward_violation_exposes_profit`, `…reverse_equivalence_violation`, `…cross_without_size_downgrades_to_quote_size_missing`), field both-directions (`test_underround_yes_sum_below_100_is_executable`, `test_overround_no_sum_below_100_is_executable`, zero-size + one-sided guards), synthetic-bundle format gates (bo5/bo3, exhaustiveness). |
| 5 | **Per-sport opportunity depth** | **PASS — matrix filled** | Snapshot #981/#983 per-sport sections: **Golf containment 47 bounded** (Top20⊇Top10⊇Top5⊇Win — was 🟡/❌), **NBA 6 / WNBA 5 containment** (playoff ladders), **Soccer 1 + cheapno 46**, **Tennis** dutch + 16 cheapno + 33 nearmiss, **Esports/MLB/Motorsport** dutch+nearmiss+cheapno. Spot-checked a Golf containment row (Echavarria, PGA Top-20 USO26): sound shape (parent_outright 8¢ ≥ child_outright 2¢, routed to bounded diagnostics as "Negative proxy"). A live re-price of that specific golf leg was blocked by event volatility + a Kalshi 429, but price-correctness is already established 3 ways (§12.2). |
| 6 | **Column reorder / resize** | **Reorder PASS; resize = not a feature** | Real header drag (extension) reordered "Sport" from index 1 → after "Max units" and it **persisted** (HTML5 DnD via `Blotter.tsx` `draggable th` → `onDrop` → `setColOrder`). Column **width-resize does not exist** (`th { resize:none }`, no resizer, no `col-resize` cursor) — by design; only panel splitters resize. |
| 7 | **ADD menu / drop-zones** | **ADD PASS; panel-relocate code-verified, automation-blocked** | `＋ ADD ▾` opens the command palette (`setPaletteOpen`; palette itself verified in §12.3 via `/`). Panel relocation: 9 `.dropslot`s + `draggable .ph` → `move(col,idx)` (code-sound). The drag could **not be automated** — extension synthetic drag selects text; JS-dispatched + Playwright drags don't fire React's `onDragStart` (the dropslots never activate). This is the known HTML5-native-DnD automation limitation (the same family **does** work for the user — column reorder in item 6 succeeded), **not a product bug.** |
| 8 | **Text size (per-panel + global)** | **PASS** | Per-panel `A↕`: real click cycled "inherit"→"normal" and the panel got `data-textsize="normal"`. Global selector (Settings → Text size): options **Compact / Normal / Large / X-Large**; setting Large flips `documentElement.data-textsize` to "large". |
| 9 | **Export selected** | **PASS (N2 also present)** | Multi-select 2 rows → selbar "Export selected" → captured CSV of exactly those 2 rows, correct 11-col header. Same `csv.ts` path so it carries the **same N2 mis-scaling** (`Est. fees $ = 1511` = $15.11, `Est. net edge $ = -2` = −$0.02). |
| 10 | **Deep-link URL restore** | **PASS** | Loading `?zone=spec&section=bounded&lens=spread` rebuilt the view: BOUNDED-LOSS subtab active (11 rows), **SPREAD** lens highlighted, "lens spread" in footer. (Transient filters like `sport` are deliberately not URL-persisted, per `docs/AUTH.md`; surface/zone/section/lens restore.) |
| 11 | **Crossed / one-sided book** | **PASS (handled + excluded by design)** | `data.py:358 quote_quality` classifies **No quote / One-sided / Crossed** (Crossed = "malformed/locked book — ask below bid; never trust as a price") plus Tight/OK/Wide/Very wide. Benign states render in the cheap-NO "Quote health" column (live: Tight 189/OK 20/Wide 8/Very wide 1; plus a live "No quote" — Marco Penge). One-sided/Crossed correctly **never become opportunities** (unit-tested `test_one_sided_leg_cannot_fabricate_overround`), so a live crossed *opportunity* is not expected — that exclusion is the honest behavior. Empty book → "no resting orders (empty or closed book)" (§12.3). |
| 12 | **Pop-out child window** | **PASS (via Playwright)** | The first audit's tooling-blocked item: Playwright's trusted click opened the child window **"Scanner workspace — popout"**, which renders the independent **Scanner + Inspector + Depth Ladder** workspace, **inherits theme (amber) + textsize (normal)**, and **shares feed data** (table rows rendered). |
| 14 | **ALRT/backlog perf + DB** | **H1 CONFIRMED (worse)** | `/backlog/events?days=7` → **28.7 MB in 13.8 s** (pass-1: ~26 MB); default `/backlog` is fine (36 KB, 1.7 s). The unbounded 7-day events query over the **1.84 GB** `snapshots.db` is the ALRT hang. `compact_store.py` compaction still **pending** (not run — rewrites the data file; needs owner OK). |

### 13.2 Net effect
- **M1 resolved** (preferences persist under auth — it was purely a no-auth-mode artifact). Auth, SSE, dark
  detectors, per-sport depth, column reorder, text-size, export-selected, deep-links, quote-state handling,
  and **pop-out** all pass.
- **N2 reconfirmed** in the Export-selected path (shared `csv.ts`).
- **H1 stands and is slightly larger** (28.7 MB / 13.8 s) — the one open performance defect; pair the fix with
  the pending `snapshots.db` compaction.
- Two items are **mechanism-verified but automation-limited** (panel-relocate DnD; the live WS overlay needs an
  RSA key) — neither is a defect.
- Still-uncovered by request scope: the **NiceGUI `/dashboard/`** legacy UI and a **real mobile device**.

---

## Appendix — reusable evidence snippets
- Feed shape: `{meta:{snapshot_id, fetched_at, n_total, sports, totals, resolution_counts}, opps:[…]}`.
  Opp keys incl: `opportunity_id, sport, status, bucket, zone, section, cost, edge, roi, max_profit,
  max_loss, fees, net_edge, net_profit, tradable, caveat, nlegs, legs[…], pbid, cask, …`.
- Buckets→tiles: DATA-QUALITY tile = data_quality+wide_signal+near_edge+display_signal+clean (raw);
  tiles/scanner-subtabs show **post-band** counts; `meta.totals` is **raw**.
- Example tickers used: `KXNASCARRACE-NAV26-*`, `KXWCGAME-26JUN22ARGAUT-{ARG,AUT,TIE}`,
  `KXCODGAME-26JUN191500FAZRIYF-*`, `KXR6GAME-26JUN201700NIPFAZE-*`.
- Screenshots saved this session: `qa-01-baseline.png`, `qa-02-ops.png` (repo root, untracked scratch).
