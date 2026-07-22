# Terminal Pro SPA mockup — working notes / handoff

> Resume point for refining `ui-mockup-final-spa.html`. This is a **non-functional design mockup**
> (the design source-of-truth) for the Kalshi Visualizer SPA. The agreed plan is to keep iterating it
> here, then port the settled design into the real React app under `frontend/`. **Display-only — never
> change engine/functionality** (CLAUDE.md scope guard: no new financial models / de-vig / net-of-fees logic;
> only surface fields the data already has).

## Files (all in `main/`, all gitignored scratch — do NOT commit)
- `ui-mockup-final-spa.html` — the mockup (single self-contained file: HTML + CSS + JS).
- `tp-final-data.js` — baked sample data (`REAL_META` + `REAL_OPPS`). Regenerable.
- `_export_mockup_data.py` — regenerates `tp-final-data.js` from `snapshots.db` via the real `webui.viewmodel` row-builders.
- `scratch/ui-mockup-final-spa.v4-checkpoint.html` — frozen v4 copy (revert/compare baseline).

## How to view (file:// is blocked in the browser tools — must serve over HTTP)
```bash
cd main && py -m http.server 8899 --bind 127.0.0.1
# then open http://127.0.0.1:8899/ui-mockup-final-spa.html
```

## How to refresh the sample data
```bash
cd main && py _export_mockup_data.py     # rewrites tp-final-data.js from the latest snapshot
```

## The brief (from owner, refined via /grilling 2026-06-28)
- Audience = **professional traders** → keep it **dense and powerful**, do not dumb down.
- Problem = the **default** showed the firehose (too much at once); hard to see just what you want.
- Two levers only: **(1) curate DEFAULT options** (what's on out of the box) and **(2) add more elements** to opt into.
- Everything removed from the default must stay reachable (ELEMENTS / ADD / ⚙ columns / palette).
- Mockup stays the design playground; settled design later ported to `frontend/` React.

## What's done (v4)
- **Focused-triad default**: Blotter + Inspector + Depth Ladder; right rail OFF by default
  (`applyPreset("default")` on init hides `#colR`). New `Full · all panels` layout preset restores everything.
- **Blotter**: long Caveat demoted to opt-in (compact ⚠ `.cvflag` on name cell instead); Cost + Max loss added
  to default columns; magnitude emphasis on edge/ROI (`td.hot` / `td.strong` / `td.faint`); optional
  **group-by sport/tournament** (collapsible `tr.grphdr`).
- **Glance strip** `#glance` above the workspace (best edge / # actionable / best ROI / top sport / updated / alerts);
  default-on, toggleable in ELEMENTS.
- **Inspector payoff diagram** (`payoffDiagram()` SVG, IF WINS / IF LOSES bars) replaced the horizontal risk:reward bar.
- Earlier (v3): proportional **text-size system** (`--fs` + `--f0..--f11`, scales row/header heights too) with a
  Settings → DISPLAY control + Ctrl +/−/0; compact horizontal tiles; richer inspector (metric chips, 4-col economics).

## Key code anchors (search these in the .html)
- `let S={` — UI state (incl. `fs`, `group`, `groupClosed`, `cols`, `showNet`).
- `const COLS={` / `opp:[` — column catalog + default visibility (`hide:true` = opt-in).
- `function blotter(` — table render + grouping. `function cell(` — per-cell formatting/emphasis.
- `function des(` — inspector trade card. `function payoffDiagram(` — the payoff SVG.
- `function glance(` — summary strip. `function tiles(` — section tiles.
- `function applyPreset(` — layout presets (incl. `default` = focused triad, `full` = all panels).
- `function openSetMenu(` — settings incl. text-size control (`setFs`). `const CHROME=[` — toggleable strips.
- `:root{` — design tokens (colors + `--fs`/`--f*` font scale + `--rowh`/`--phh`).

## Gotchas
- **`quote_health` is 0% populated for actionable/review rows** (only bounded-loss) — do NOT default it into the opp blotter.
- Files are gitignored scratch; if lost, see the `mockup-recovery` memory (reconstruct HTML from transcript
  `a8866b12-…` under the `…-Internship` project dir; regenerate data via the export script).

## Deferred / candidate next steps
- Dedicated **global color-hierarchy / polish pass** (calmer chrome, clearer color roles so data wins).
- New elements not yet built: **opportunity heatmap**, **watchlist / pinned** panel.
- Open question for next pass: keep the 2-bar payoff diagram or revert to the proportional risk:reward bar?
- Persist user prefs (text size, default layout, columns) across reloads (currently in-memory only).
