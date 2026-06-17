# UI / Engine issues to solve later

Captured 2026-06-17 from an owner walkthrough of the running `origin/main` SPA (`d5f8210`).
Each item has a verified root cause + file:line. Grouped by confidence. Fix on a feature branch
off `origin/main` (not on this detached HEAD).

## Confirmed bugs (root cause verified in code)

1. **Executable/Actionable trader card: Cost, Worst case, Quote render blank.**
   - Root cause: `opp_row` (`webui/viewmodel.py:276-297`) — the builder for executable rows —
     does NOT emit `cost`, `max_loss`, or `quote_health`. `Inspector.tsx:128/129/133` reads exactly
     `row.cost` / `row.max_loss` / `row.quote_health`, so all three show `—`.
   - Side effect: `rankWhy` (`frontend/src/lens.ts:41-43`) keys "tight quote" / "wide" on
     `quote_health`, so the **WHY RANKED HERE → Promotes/Demotes** quote reasons never fire on
     executable rows either.
   - Fix: add `"cost": o.get("cost_c")`, `"max_loss": …(-worst_case_profit_c)`,
     `"quote_health": str(o.get("comp_quote_quality") or "")` to `opp_row` (mirror the speculative
     builders, which already set them — that's why bounded-loss/cheap-NO cards are fine).

2. **"Buy NO" price never shows in the trade card.**
   - Root cause: the Inspector ECONOMICS block (`Inspector.tsx:126-139`) has no NO/`buy_no` field;
     `buy_no` exists only as a Blotter *column* (`columns.ts:43`). The detail card never renders it.
   - Fix: surface the per-leg NO leg in the card (data is present: `action_2_price_c` →
     `no_structure_row` `buy_no`, `webui/viewmodel.py:753`).

3. **Economics block shows only Cost / Max units / Tradable for some participants (e.g. Switzerland).**
   - Root cause: same family as #1. Qualifier-setup rows (`qualifier_row`) populate `cost`
     (only when `is_exact`), `max_units`, `tradable`, but not `max_loss` / `max_profit` /
     `quote_health`. Inconsistent field coverage across the row builders in `webui/viewmodel.py`.
   - Fix: normalize the Economics field set across all row builders (or have Inspector hide rows
     that legitimately lack a field, instead of leaving a half-populated block).

## Requested changes

4. **Remove the password-size restriction for new (self-registered) users.**
   - Location: `auth_store.py:103` (`PASSWORD_MIN_LEN = 10`) and the `< PASSWORD_MIN_LEN` check at
     `auth_store.py:108-109` inside `validate_password_strength()` (single-sourced — also used by the
     CLI seed and password-change). The `_WEAK_PASSWORDS` blocklist (`:101`) and the max-length DoS
     cap (`:110`, `config.AUTH_MAX_CRED_LEN`) are separate — decide whether those stay.
   - Note: this loosens auth security; confirm intent before shipping.

5. **Cheap-NO section: add ladder-aware filtering + the NiceGUI three-way split.**
   - Today the SPA cheap-NO filters are only Kind (all/band/outright), Max loss ¢, Max Buy-NO ¢,
     and "Group by ladder" (`frontend/src/App.tsx:251-258`, `columns.ts:42-48`).
   - Requested: filter by ladder depth / bottom-of-ladder price / (bottom ÷ number of steps), and
     expose the three cheap-NO options the NiceGUI dashboard (`webui/`) has. Needs the engine to
     expose ladder-depth/step-count fields on no-structure rows.

6. **Bounded-loss: per-leg outright price is hidden by default.**
   - The columns exist (`parent_outright` / `child_outright`, `columns.ts:38`) but are `hide:true`.
     That's why "I can't see the outright price for each leg." Make them visible or add a toggle.

## Confirmed UX inconsistency

9. **Participant Detail self-contradicts on game/field rows (e.g. Argentina vs Austria):**
   it shows "No parent/child containment node on this row… Conditional probability applies to
   ladder rows only" AND THEN loads the participant drill-down tables below it.
   - Root cause: the two sub-blocks use different gating predicates.
     - Conditional-probability block gates on the containment **node** (`row.pnode`/`row.cnode`,
       `frontend/src/Inspector.tsx:271-280`) → "no containment node" for a game/field row.
     - Drill-down tables (ladder / chain / spreads / expected / contracts) gate on
       `detailKey(row)` = **sport + player_key + tournament** (`frontend/src/detail.ts:22-28`,
       used at `Inspector.tsx:282`).
     - A soccer game row HAS a `player_key` + `tournament` (so `detailKey` is non-null and the
       tables load) but has NO containment parent/child node (so the conditional block declares it
       inapplicable). The two disagree → the contradictory display.
   - Owner's preferred fix (pick one):
     a. **Let the user choose a participant** for a multi-side row (e.g. Argentina or Austria) and
        render that participant's view, OR
     b. **Omit Participant Detail entirely** for rows with no single-participant containment anchor
        (hide/disable the tab, or render only the one explanatory note — never the half-loaded mix).
   - Either way: make the conditional block and the drill-down block share ONE predicate so they
     can't contradict each other.

## Popout window is a dead static clone

10. **Pop-out scanner window: tab buttons (Executable/Speculative/Diagnostic) do nothing, dock
    buttons (maximize/collapse/minimize) do nothing, no live updates, can't link panels.**
    - Root cause: `popOut` (`frontend/src/Workspace.tsx:108-118`) opens a blank window and
      `doc.importNode(node, true)` clones the panel's **static DOM** into it. A cloned DOM node has
      NO React fibers/event handlers attached — so every onClick (section tabs, ⧉/▢/▁/✕ dock, row
      clicks) is dead, and nothing re-renders or re-polls. It's a frozen snapshot, by construction.
    - Requested behavior (none of which the clone can do):
      a. Switch sections (Executable / Speculative / Diagnostic) inside the popout.
      b. Minimize/maximize/collapse the popout panel.
      c. Open **multiple panels in one popout** (e.g. Scanner + Inspector together) with **linked
         selection** — click a row in the popped-out Scanner → the popped-out Inspector updates.
    - Fix direction: mount a REAL React root into the popout window (e.g. `ReactDOM.createRoot` on
      `w.document.body`, or `createPortal`) rendering live components, and share the selected-row
      state (lift it to a store/context both windows read) so scanner→inspector linking works.
      Carrying stylesheets over (already done at `:114`) is fine; the DOM clone is the problem.

11. **Diagnostic → Soccer: duplicate "Haiti" rows, and clicking a diagnostic row shows a full
    buy-only trader card (plan + economics) that makes no sense; the order book panel errors.**
    - Confirmed parts:
      - *Trader card not zone-aware:* the Inspector renders the ECONOMICS block + action-plan
        summary for ANY selected row regardless of bucket/zone (`frontend/src/Inspector.tsx`
        ECONOMICS at :126-139, action plan via `opp_row`). A diagnostic/review-only row therefore
        shows a "buy-only plan" as if it were actionable. The card should adapt to the row's zone
        (hide the buy plan / economics for diagnostic-only rows, or label them clearly).
      - *Order book error:* the live MD-ladder panel (`frontend/src/Ladder.tsx:92-97,136-140`)
        fetches `GET /api/terminal/orderbook` for the row's ticker and, on any failure / `ok:false`,
        shows "order book unavailable" (or "rate-limited"). For a diagnostic row whose market is
        closed/finalized or non-tradable, that fetch legitimately fails → the error. The panel
        probably shouldn't attempt a live book for a non-actionable diagnostic row at all.
    - Needs a live repro to finish:
      - *Duplicate Haiti rows:* two seemingly-identical diagnostic entries. Likely either two
        distinct `opportunity_id`s that render with the same display name (different node pair /
        setup_type but same participant label), or a genuine dedup gap in the diagnostic feed.
        ACTION: click both, capture their `Opp id` (EVIDENCEPACK) + status/setup_type to tell
        "real distinct rows that look alike" from "true duplicate."

## Needs a concrete repro (could NOT reproduce a code error)

7. **"Fee formula is fully wrong."**
   - Verified the formula is dimensionally CORRECT and matches Kalshi's published schedule:
     `kalshi_fee_c` = `ceil(coeff · C · (P/100) · (1−P/100) · 100)` (`webui/viewmodel.py:1651-1663`,
     `config.py:165-171`). Worked example: 100 contracts @ 50¢ → 175¢ = $1.75, which equals Kalshi's
     `ceil(0.07·100·0.5·0.5)` = $1.75. The earlier "off by 100×" diagnosis was wrong (it forgot the
     published formula is dollar-denominated).
   - If displayed fees still look wrong, the likely culprits are elsewhere: which leg price is fed,
     per-leg aggregation across a multi-leg plan, taker-vs-maker selection, or a $/¢ label mismatch
     in the SPA. ACTION: capture one concrete market + the fee the app showed vs. the fee Kalshi
     charged, then trace that specific row.

8. **"Success given reached" blank for some contracts (e.g. Qatar).**
   - By design fail-closed: `_cond_success_pct` (`webui/viewmodel.py:1852-1857`) returns None when
     `spread_over_parent` is missing or ≤ 0 — i.e. the row isn't a standard containment ladder, a leg
     has no display price, or the display is inverted. For a World-Cup group team like Qatar the most
     likely cause is "no laddered containment node / missing quote on a leg," not a bug. ACTION:
     inspect the live Qatar row to confirm it's missing-quote vs. non-ladder before deciding if any UX
     change (an explicit "why blank" note) is wanted.

## Deployment / upgrade smoothness (from lisbon-114 ops notes, 2026-06-16)

Source: `structured-scanner-update-notes-2026-06-16.txt` — a `git pull` to `d5f8210` broke the
systemd service on the prod box (lisbon-114, also lisbon-113). Root issue: a bare `git pull` updates
CODE but not the two things the code now needs (installed Python deps + a rebuilt `frontend/dist`),
and one behavioral change (auth default) silently broke an existing LAN deployment. The box was fixed
manually; these are the REPO changes so the next pull is smooth. None block the app for local dev —
they're for operators deploying via `git pull`.

12. **Ship a one-command update script.** Add `deploy/update.sh` (or a Makefile `update` target):
    `git pull` → `uv pip install -r requirements.txt` → `(cd frontend && npm ci && npm run build)`
    → `sudo systemctl restart structured-scanner`. Today an operator must *know* to install new deps
    and rebuild the SPA — neither is obvious from "git pull". This is the biggest win. (A
    `scripts/build_deploy_repo.py` + `deploy/` already exist per CLAUDE.md — extend that, don't
    duplicate.)

13. **Document the AUTH_ENABLED breaking change (CHANGELOG / UPGRADING note).** The React rewrite
    flipped `AUTH_ENABLED` from off → on by default (via `serve.apply_runtime_defaults()`), and the
    fail-closed bind guard then refuses to bind `0.0.0.0` without a seeded user + TLS/declared HTTPS
    proxy + `APP_ALLOWED_HOSTS`. That broke the prior auth-less "WireGuard is the perimeter"
    deployment. Add an UPGRADING note: *"enables auth by default; existing trusted-LAN deployments
    must either configure TLS + a user, or set `AUTH_ENABLED=0` to keep the old open behavior."* The
    guard messages are good but are buried in `journalctl` under systemd. (See `docs/AUTH.md`,
    `docs/DEPLOYMENT.md`.)

14. **Make `frontend/dist` freshness explicit.** It's gitignored and is what prod serves, so every
    deploy that pulls frontend changes MUST rebuild it (`npm run build`). Document this explicitly
    (and fold it into the #12 script so it's automatic). A stale/absent `dist` leaves `/` serving old
    or no SPA without any error.

15. **Pin/document the toolchain assumptions.** Python venv is uv-managed (Python 3.13), no `pip`
    inside — deps install via `uv pip install -r requirements.txt`; `requirements.txt` is the source
    of truth (a new import must be added there — argon2-cffi was, the gap was only that pull ≠
    install). Node: document the expected version and that deploys use `npm ci` (not `npm install`)
    for reproducibility.

16. **README: dev-vs-prod run model (minor).** Add a short section: *Dev = `npm run dev` (Vite :5180)
    + backend on :8000; Prod = build the SPA, run `serve.py` on one port.* Prevents the "ran
    `npm run dev` without the backend, all data fetches fail" confusion. The `vite.config.ts` comment
    is clear but easy to miss.
