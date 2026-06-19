# SPA ↔ NiceGUI parity audit (Phase 2, step 1)

The plan's Phase 2 ("close the SPA↔NiceGUI gap") is **audit-first**: this is the prioritized gap list for
**owner prioritization**. The actual porting is a **separate workstream** (own branch/ticket per item) —
it is deliberately NOT bundled onto the conditional-blend detector branch. Generated 2026-06-19 from a
feature-by-feature comparison of the NiceGUI dashboard (`webui/dashboard.py` + `webui/viewmodel.py` cores)
vs the React SPA (`frontend/src/`).

## Headline
The React SPA is **~79% feature-complete** vs the NiceGUI dashboard. **All core scanning, filtering,
ranking, export, detail panels, and the display/firm conditional ratios are FULL parity.** Of ~180
features: **142 FULL · 27 PARTIAL · 11 MISSING.** Every missing item is non-critical/ops-only **except the
field-de-vig conditional-probability estimate.**

## Prioritized porting backlog
| Tier | Item | SPA status | Where (NiceGUI) | Effort | Priority |
|---|---|---|---|---|---|
| 1 | **Field-de-vig conditional-probability estimate** (the "field-implied est." column + partial-field floor warning) | PARTIAL — display/firm ratios shown; **no de-vig** | `dashboard.py:942-976`, `vm.conditional_probabilities`; compute exists in `consistency.devig_field_by_node` / `probability.py` but is NOT in the feed/detail adapter | L | **HIGH** |
| 2 | **Market telemetry on the main view** (most-liquid sports/contracts, tightest books, most-traded, most-volatile) | MISSING on main view (lives only in the research surface) | `dashboard.py:~1745`; `App.tsx:11-34` | M | High |
| 3 | **Recently-actionable backlog table** + window filter (3h/12h/1d/7d) and the 7-day event backlog | PARTIAL — data loaded (`loadBacklog`/`loadBacklogEvents`), not rendered | `dashboard.py:503-525, 760-761` | M | Med |
| 4 | **Cheap-NO advanced filters** (kind selector, max Buy-NO ¢, include-wide-quotes, group-by-participant + ladder-sort) | PARTIAL/MISSING — band filters exist, no UI controls | `dashboard.py:730-749` | M | Med |
| 5 | **Bounded-loss extra filters** (min child outright ¢, max spread÷outright ratio) | PARTIAL — fields exist, not wired to UI | `dashboard.py:711-720` | M | Low |
| 6 | **Diagnostics audit grids** (tournament/participant/contract-kind inventory, series/sport error detail, full comparisons, non-laddered/unmapped/motorsport coverage) | PARTIAL/MISSING — counts shown, detail tables not rendered | `dashboard.py:1621-1694` | L | Low (ops/debug) |
| 7 | **Accessibility polish** (comprehensive ARIA labels + focus-visible ring) | PARTIAL — semantic HTML + text-scaling present | `dashboard.py:39-50` | M | Low |
| 8 | Minor/deferred: new-watchlist toast; cheap-NO ladder-grouped (hierarchy) view; alert-persistence selector; render telemetry on diagnostics; raw-fields/link-audit debug tables | MISSING/PARTIAL | various | S–L | Low |

## Notes for prioritization
- **Tier 1 caveat:** the conditional-blend *detector* does NOT depend on the SPA de-vig panel — it computes
  its own blend independently. The de-vig panel is valuable on its own merits (and is the natural SPA home
  for the owner-approved cond-prob-in-SPA exception), but it is a **separate feature**, and porting it is a
  backend **detail-endpoint** change (`/api/terminal/detail`) + an `Inspector.tsx` change, not a feed-row
  change. Recommend its own branch.
- **Recommended sequencing:** pick items à la carte; each is independently shippable. Tiers 1–3 are the
  trader-facing wins; Tiers 6–8 are ops/polish. None block the conditional-blend detector.
- Full per-feature breakdown (180 rows) is available on request — this file is the actionable summary.
