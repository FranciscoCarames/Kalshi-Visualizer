# Dashboard Column & Table Guide

A complete, plain-English usage guide to **every table and every column** in the new React SPA
("Kalshi Structured Scanner", the default UI at `/`). For each column you get its **meaning**, its
**formula** (in exact integer cents, the way the engine computes it), and the **units** it renders in.

> **Read this first — what every number is, and is not.**
> - Every figure is **GROSS** and **TOP-OF-BOOK**. Fees, position/collateral limits, and full-depth
>   execution are *documented but not modeled* — treat every edge as an **upper bound**.
> - The app is **read-only and buy-only**. There is no "sell"/"short" — every plan is a set of
>   **Buy YES** and **Buy NO** legs.
> - All comparison logic is done in **exact integer cents** (`¢`). Percentages and dollar displays are
>   derived for readability only.
> - The SPA **never recomputes** the engine's bucket/status/edge fields — it renders them verbatim from
>   `GET /api/terminal/feed`. The display-only derivations (conditional probabilities, fee estimates,
>   ripeness) are computed in the feed adapter and are flagged **"never ranks"**.
> - A `0.00 / 1.00` book is an **empty book ("No quote")**, never a real 50%.

---

## How the dashboard is organized

The scanner is split into **3 zones**, each with **sub-tabs (sections)**. Each section renders its **own
column catalog** (you can show/hide columns with the `⚙ columns ▾` chooser, drag to reorder, and click a
header to sort — sort is display-only and never re-buckets).

| Zone | Section (tab) | Engine bucket | What it is |
|---|---|---|---|
| **EXECUTABLE** | ACTIONABLE | `actionable` | Firm, gross edge — a tradable inconsistency right now |
| | REVIEW | `review_signal` | Same shape but rule/settlement-dependent |
| | BLOCKED | `blocked` | Real signal, blocked (no size, missing quote, etc.) |
| **SPECULATIVE** | BOUNDED-LOSS | `risk_budget` | Convex bets with a capped loss — *can lose money* |
| | NEAR-MISS | `near_miss` | Dutch books overpriced just above the payout floor (watchlist) |
| | QUALIFIER | `qualifier_setup` | Top-two / qualifier setups — review-only |
| | CHEAP-NO | `no_structure` | Cheap bounded Buy-NO fades |
| **DIAGNOSTIC** | DATA-QUALITY | `data_quality`, … | Review-only rows (display/wide/near-edge/clean) |

The catalog used by each section is chosen by `colKeyOf(zone, section)`:
`bounded→risk`, `nearmiss→nm`, `qual→qs`, `cheapno→no`, `diag→diag`, everything else (the three
EXECUTABLE tabs) → `opp`.

Display conventions used in every catalog:

| `fmt` code | Render | Example |
|---|---|---|
| `c` | rounded cents | `45¢` |
| `cmoney` | a cents value shown as display dollars | `$1.75`, `-$0.12` |
| `pct` | one-decimal percent | `12.3%` |
| `money` | dollars (2 dp) | `$3.00` |
| `x` | one-decimal "times" multiple | `2.4×` |
| `num` | integer or one-decimal number | `7`, `1.4` |
| `text` / `name` / `qh` / `trad` | text label / participant cell / quote-health chip / tradable chip | — |

---

## TABLE 1 — Scanner: EXECUTABLE catalog (`opp`)

Used by **ACTIONABLE, REVIEW, BLOCKED**. Source: `webui/viewmodel.opp_row`.

| Column | Meaning | Formula / source | Default |
|---|---|---|---|
| **Participant / market** (`name`) | Who/what the opportunity is on, with the tournament/leg sub-label. | `name` + `sub`/`detail`. The cell also shows change badges (`NEW`, `↶ returned`, `▲/▼ edge up/down since last scan`). | shown |
| **Sport** (`sport`) | Sport label. | `sport_label`. | shown |
| **Detail** (`detail`) | Short description of the legs / relationship. | `detail` (+ a compact setup badge). | hidden |
| **Action plan** (`action`) | One-line summary of the buy legs. | `action_plan_summary(o)` — the Buy-YES broader / Buy-NO deeper leg list. | hidden |
| **Gross edge ¢** (`edge`) | The headline gross edge. | `exec_gap_c` = **firm child bid − parent ask** (containment), or the **Σ-floor gap** for a dutch book (`Σ floor − Σ cost`). Positive = an edge. | shown |
| **ROI %** (`roi`) | Return on the cost of the bundle. | `roi_pct` = **max gross profit ÷ cost**. | shown |
| **Max units** (`units`) | How many units you can fill at top-of-book. | `exec_min_size` = the smallest leg's tradable size. | shown |
| **Max gross profit** (`profit`) | Total gross profit at `Max units`. | `exec_max_profit_dollars` = per-unit edge × units, in $. | shown |
| **Est. net edge $** (`net_edge`) | Per-unit edge after the **immediate-fill (taker)** fee estimate. | `gross edge − taker fee`; taker fee ≈ `0.07 × c × p × (1−p)` per leg × effective multiplier (event override → series → labeled fallback). Display-only; **never ranks**. | hidden |
| **Est. net max profit** (`net_profit`) | Total profit after taker fees. | taker net per-unit × units, in $. Immediate-fill estimate only — **not net P&L**. | hidden |
| **Est. fees $** (`fees`) | Estimated total taker fees for the bundle. | Σ per-leg taker fee, in $ (event override → series → fallback). | hidden |
| **Tradable** (`tradable`) | Whether it is placeable now. | `tradable_now`: "Yes" (both legs `active`, no rule flag), "Yes — rule-dependent", "Review rules", or "No". | shown |
| **Caveat** (`caveat`) | Severity chip + note. | `settlement_caveat` / `blocked_reason`. The chip is `Blocker` / `Review` / `Advisory` / `Fee: taker net-neg (est.)`. | shown |

> **Edge sign convention:** the engine only flags `EXECUTABLE_VIOLATION` when the firm child **bid** >
> parent **ask** with positive sizes — that is the only "Broken/Actionable" status. A sizeless cross →
> `QUOTE_SIZE_MISSING` (BLOCKED); a display-only cross → `DISPLAY_VIOLATION` (Warning).

---

## TABLE 2 — Scanner: BOUNDED-LOSS catalog (`risk`)

Used by **BOUNDED-LOSS** (`risk_budget`). Source: `webui/viewmodel.risk_budget_row`. These are **bets, not
edges** — they can lose money. Every metric here is gross, top-of-book, uncalibrated, and never affects
ranking/actionability.

| Column | Meaning | Formula / source | Default |
|---|---|---|---|
| **Signal** (`signal`) | Honesty class of the row. | `_signal_class`: `Data quality` (no display gap) / `Inverted / diagnostic` (deeper priced above broader) / `Candidate` (gap beats breakeven) / `Breakeven` / `Negative proxy`. | shown |
| **Flags** (`flags`) | Honesty badges. | `Midpoint-only` (positive on display midpoint but not on firm bid/ask) and/or `Wide basis` (a leg quote is Wide/Very-wide). | shown |
| **Kind** (`resolution`) | How the two legs resolve. | `Vertical` (simultaneously, one event) or `Calendar` (sequentially across rounds). | shown |
| **Cheap vs peers** (`cheap`) | Cheap relative to same-sport peers at a similar implied chance. | `cheap_cost` / `cheap_ratio` flags — set when the row is ≥ k robust z-scores (median/MAD) below the peer median; needs ≥ `PEER_MIN_COUNT` in-band peers. | shown |
| **Sport** (`sport`) | Sport label. | `sport_label`. | shown |
| **Participant / market** (`name`) | Participant + detail. | `name` + `detail`. | shown |
| **Detail** (`detail`) | Leg description. | `detail`. | hidden |
| **Wins if…** (`wins_if`) | The plain-English payoff zone. | `parent_node` happens **but not** `child_node` (e.g. "Reach Final but not Win Tournament"). | shown |
| **Cost ¢** (`cost`) | Bundle cost per unit. | `cost_c` = Σ leg ask. | hidden |
| **Max loss ¢** (`max_loss`) | Capped loss per unit. | `−worst_case_profit_c` (≥ 0). | shown |
| **Max profit ¢** (`max_profit`) | Best-case gross profit per unit. | `best_case_profit_c`. | shown |
| **Max units** (`max_units`) | Fillable size at top-of-book. | `exec_min_size`. | shown |
| **Max loss @ $100** (`loss_100`) | Gross max loss if you spend ~$100. | `_sized_at_budget`: `units = min($100 // cost, size)`, then `max_loss × units`, in $. | shown |
| **Best upside @ $100** (`upside_100`) | Gross best upside at the same $100 sizing. | `best_case × units`, in $. | shown |
| **Quote health** (`quote_health`) | Worst-leg quote quality. | `comp_quote_quality`: Tight / OK / Wide / Very wide / One-sided / No quote / Crossed. | shown |
| **Upside:risk** (`ratio`) | Reward-to-risk ratio. | `best_case ÷ max_loss` (`∞` when max loss is 0 — the premium case). | shown |
| **Implied EV ¢** (`ev`) | Chance-weighted ranking aid. | `_implied_ev_c` = `display_spread_c − overpay` (market-implied payoff chance minus the capped loss). Display proxy, gross, **not fair value, never ranks**. | shown |
| **Breakeven %** (`breakeven`) | Minimum payoff chance the bet needs. | `_breakeven_pct` = `max_loss ÷ (max_loss + max_profit) × 100`. | shown |
| **Basis** (`basis_flags`) | Honesty flags. | `MID-ONLY` = positive only on display basis; `WIDE` = rests on a wide quote. | shown |
| **Market gap (pp)** (`display_spread`) | The displayed parent−child gap. | `display_spread_c` (in pp; cents = %). | shown |
| **Success given reached % (display)** (`cond_success`) | P(success │ broader reached) on display prices. | `_cond_success_pct` = `spread_over_parent × 100` = `1 − child/parent`. Uncalibrated, gross. | shown |
| **Deeper given reached % (display)** (`cond_child`) | P(deeper │ broader reached) on display prices. | `_cond_child_pct` = `child/parent × 100` (complement of the above). | shown |
| **Success given reached % (firm)** (`cond_success_firm`) | Same, on the firm bid/ask. | feed adapter `_cond_pair(parent_yes_bid, child_yes_ask)`. **Diagnostic, not an executable edge.** | hidden |
| **Deeper given reached % (firm)** (`cond_child_firm`) | P(deeper│reached) on firm quotes. | same firm pair. Diagnostic only. | hidden |
| **Firm success gap ¢** (`firm_gap`) | Conservative tradable-side gap. | `_firm_spread_c` = `parent_yes_bid − child_yes_ask`. May be ≤ 0 — that *is* the signal a midpoint positive isn't tradable. | shown |
| **Gap vs breakeven (pp)** (`gap_vs_be`) | How far the market gap beats the breakeven it needs. | `_gap_vs_breakeven_pp` = `display_spread − breakeven`. Positive ⇒ displayed prices imply a better-than-needed chance. | shown |
| **Parent ÷ max loss** (`parent_over_maxloss`) | "Ripeness" lens — in-the-money chance per ¢ at risk. | `_parent_over_maxloss` = `parent_display_c ÷ (cost − 100)`. Higher = better. | shown |
| **Worst-case ROC %** (`roc`) | The (honestly negative) worst-case return on cost. | `roi_pct`. Labelled secondary. | hidden |
| **Spread÷parent** (`spread_over_parent`) | Display spread relative to the parent outright. | `spread_over_parent`. | hidden |
| **Spread÷child** (`spread_over_child`) | Display spread relative to the child outright. | `spread_over_child`. | hidden |
| **Parent outright ¢** (`parent_outright`) | Broader leg's display price. | `parent_display_c`. | hidden |
| **Child outright ¢** (`child_outright`) | Deeper leg's display price. | `child_display_c`. | hidden |
| **Caveat** (`caveat`) | Settlement/blocked note. | `settlement_caveat` / `blocked_reason`. | shown |

> The BOUNDED-LOSS tab also has a **split sub-tab row** (`All / Vertical / Calendar`) that partitions rows
> by `resolution_mode` — purely a view filter.

---

## TABLE 3 — Scanner: NEAR-MISS catalog (`nm`)

Used by **NEAR-MISS** (`near_miss`). Source: `webui/viewmodel.near_miss_row`. A dutch book priced **just
above** its payout floor — a guaranteed *loss* as a bundle, so it is watchlist-only.

| Column | Meaning | Formula / source |
|---|---|---|
| **Sport** (`sport`) | Sport label. | `sport_label`. |
| **Participant / market** (`name`) | The MECE event. | `name`. |
| **Direction** (`detail`) | Which side of the book. | `detail`. |
| **Cost ¢** (`cost`) | Bundle cost. | `cost_c`. |
| **Overpay ¢** (`overpay`) | How much over the floor it is priced. | `−exec_gap_c` (gap is negative for a near-miss; overpay = `1..max_over_c`). |
| **Note** (`note`) | Settlement caveat. | `settlement_caveat`. |

---

## TABLE 4 — Scanner: CHEAP-NO catalog (`no`)

Used by **CHEAP-NO** (`no_structure`). Source: `webui/viewmodel.no_structure_row`. A cheap convex fade —
either a single **Buy NO** outright (directional watchlist) or a **Buy NO deeper + Buy YES broader** band
(bounded loss = `cost − 100`). Not an edge.

| Column | Meaning | Formula / source | Default |
|---|---|---|---|
| **Kind** (`kind`) | Structure type. | `Band` (ladder-bounded) or `Outright` (single Buy-NO). | shown |
| **Sport** (`sport`) | Sport label. | `sport_label`. | shown |
| **Participant / market** (`name`) | Participant. | `name`. | shown |
| **Wins if…** (`wins_if`) | Payoff zone. | band: broader happens but not deeper; outright: "the outcome does NOT happen". | shown |
| **Buy NO ¢** (`buy_no`) | The cheap-NO anchor cost. | `action_2_price_c`. | shown |
| **Cost ¢** (`cost`) | Total cost per unit. | `cost_c`. | shown |
| **Max loss ¢** (`max_loss`) | Capped loss. | `max(0, −worst_case_profit_c)` (band: `cost−100`; outright: `cost`). | shown |
| **Breakeven %** (`breakeven`) | Min payoff chance needed. | `_breakeven_pct` = `max_loss ÷ (max_loss + max_profit) × 100`. | shown |
| **Win profit ¢** (`bonus_profit`) | Net gain in the win state. | `best_case_profit_c` (band: `200 − cost`). | shown |
| **Payout÷cost** (`convexity`) | Convexity multiple. | `best_payout ÷ cost` = `(best_case + cost) ÷ cost`. Secondary, not the headline. | shown |
| **Quote health** (`quote_health`) | Worst-leg quality. | `comp_quote_quality`. | shown |
| **Caveat** (`caveat`) | Settlement/blocked note. | `settlement_caveat` / `blocked_reason`. | shown |
| **Detail** (`detail`) | Leg description. | `detail`. | hidden |
| **Buy YES (bound) ¢** (`parent_yes`) | The bounding Buy-YES cost (bands only). | `action_1_price_c`. | hidden |
| **Max units** (`max_units`) | Fillable size. | `exec_min_size`. | hidden |
| **Max loss @ $100** (`loss_100`) | Gross max loss at ~$100 sizing. | `_sized_at_budget` × max loss, in $. | hidden |
| **Best upside @ $100** (`upside_100`) | Gross best upside at $100 sizing. | `_sized_at_budget` × best case, in $. | hidden |
| **Ladder depth** (`ladder_steps`) | # of rungs in the participant's ladder. | `ladder_steps` (triage band; only on band rows). | hidden |
| **Ladder bottom ¢** (`ladder_bottom_c`) | NO price at the deepest rung. | `ladder_bottom_c`. | hidden |
| **Bottom÷steps** (`ladder_step_ratio`) | Depth-normalized cheapness. | `ladder_step_ratio` = bottom ¢ ÷ steps. | hidden |

---

## TABLE 5 — Scanner: QUALIFIER catalog (`qs`)

Used by **QUALIFIER** (`qualifier_setup`). Source: `webui/viewmodel.qualifier_row`. A non-executable,
**Review-only** signal (no gross-edge/ROI/size). The "top-two bundle" replicates a qualifier outcome and
is priced against the qualifier market.

| Column | Meaning | Formula / source | Default |
|---|---|---|---|
| **Sport** (`sport`) | Sport label. | `sport_label`. | shown |
| **Participant / market** (`name`) | Participant. | `name`. | shown |
| **Setup** (`setup`) | Setup family label. | `setup_type` → readable label. | shown |
| **Qualifier YES ask ¢** (`qualifier`) | Cost to buy the qualifier directly. | `qualifier_yes_ask_c`. | shown |
| **Top-two bundle cost ¢** (`cost`) | Cost to replicate via the top-two bundle. | `synthetic_top_two_cost_c`. | shown |
| **Cheaper vs qualifier ¢** (`premium`) | How much cheaper the bundle is than buying the qualifier. | `qualifier_vs_top2_premium_c`. | shown |
| **If top two ¢** (`if_top2`) | Net profit if the two named finish top-two. | `top2_net_if_top2_c`. | shown |
| **If not top two ¢** (`if_not_top2`) | Loss if they do not. | `top2_loss_if_not_top2_c`. | shown |
| **Max units** (`max_units`) | Fillable size. | `top2_max_units`. | shown |
| **Worst leg quote** (`worst_leg_quote_label`) | Worst quote across bundle legs. | `worst_bundle_quote_quality` (sorts on rank, shows label). | shown |
| **Comparator quote** (`comparator_quote_label`) | Quote quality of the qualifier comparator market. | `comparator_quote_quality`. | shown |
| **Legs** (`legs`) | # of bundle legs. | leg count (`n_legs` for game-support rows). | shown |
| **Review status** (`review_status`) | Review label. | `tradable_now` or "Diagnostic only" (never "Actionable"). | shown |
| **Caveat** (`caveat`) | Settlement note. | `settlement_caveat`. | shown |
| **Support score ¢** (`support`) | Game-support heuristic (game-support rows only). | `ask_support_score_total_c`. | hidden |
| **Highest leg ask ¢** (`highest_leg`) | Most expensive bundle leg. | `_bundle_leg_price_stats`. | hidden |
| **Median leg ¢** (`median_leg`) | Median bundle-leg price. | `_bundle_leg_price_stats`. | hidden |
| **Tournament key** (`tournament_key`) | Grouping key. | `tournament`. | hidden |

---

## TABLE 6 — Scanner: DIAGNOSTIC catalog (`diag`)

Used by the **DATA-QUALITY** zone (`data_quality`, `display_signal`, `wide_signal`, `near_edge`, `clean`).
Source: `opp_row` projected to a small set. These rows are **not tradable** — review/data-quality only.

| Column | Meaning | Formula / source |
|---|---|---|
| **Sport** (`sport`) | Sport label. | `sport_label`. |
| **Participant / market** (`name`) | Participant. | `name`. |
| **Status** (`status`) | Engine status string. | `status` (e.g. `DISPLAY_VIOLATION`, `WIDE_QUOTE`, `MISSING_QUOTE`, `UNKNOWN_RELATIONSHIP`, `CLEAN`). |
| **Gross edge ¢** (`edge`) | Edge (often nil here). | `exec_gap_c`. |
| **ROI %** (`roi`) | Return on cost. | `roi_pct`. |
| **Tradable** (`tradable`) | Placeable? | `tradable_now` (typically No). |
| **Caveat** (`caveat`) | Note. | `settlement_caveat` / `blocked_reason`. |

---

## TABLE 7 — Inspector: ECONOMICS (per unit)

Shown in the trade card (`Inspector.tsx`) for any non-diagnostic row. A 2-column key/value block; the
`$1 ⇄ $100` toggle re-bases cents into a $100 allocation.

| Row | Meaning | Source |
|---|---|---|
| **Cost** | Cost per unit. | `cost`. |
| **Worst case** / **Max loss** | "Worst case" for executable rows, "Max loss" for speculative rows. | `max_loss`. |
| **Best case** / **Max profit** | Best-case profit. | `max_profit` (or `profit`). |
| **ROI** | Return on cost. | `roi`. |
| **Max units** | Fillable size. | `max_units` (or `units`). |
| **Quote** | Worst-leg quote quality. | `quote_health`. |
| **Tradable** | Placeable? | `tradable`. |
| **Ripeness (parent÷loss)** | In-the-money chance per ¢ at risk (shown only when present). | `parent_over_maxloss`. |

The **BUY-ONLY PLAN** block above it lists each leg as `YES/NO · contract · price¢ · ×size` (book-only
reference legs render as `BOOK · reference only`). A `LONG/SHORT` toggle relabels YES/NO when set.

---

## TABLE 8 — Inspector: FEES (two execution scenarios)

Shown when "show net" is on (`FeeScenarios`). All display-only; **never ranks**.

**Immediate-fill (taker)** and **Resting-order (maker)** blocks each show:

| Row | Meaning | Source |
|---|---|---|
| **Est. fees** | Estimated total fees for the bundle, in $. | `fees_taker` / `fees_maker` (incomplete if a flat/unknown leg). |
| **Est. net edge / unit** | Per-unit edge after that scenario's fees, in $. | `net_edge` / `net_edge_maker`. |
| **Breakeven gross gap** (taker only) | The gross gap at which fees eat the edge. | `fee_breakeven` (¢; flagged "approx" when estimated). |

**Per-leg fees** table — one row per leg:

| Cell | Meaning | Source |
|---|---|---|
| **Side** | YES / NO. | `side`. |
| **Series** | Series ticker the fee resolved from. | `series_ticker`. |
| **Price** | Leg price. | `price_c`. |
| **Fee type × multiplier** | The resolved fee schedule. | `fee_type` × `fee_multiplier`. |
| **t / m** | Per-leg taker (`t`) and maker (`m`) fee. | `fee_taker_c` / `fee_maker_c`. |
| **Source** | Where the fee type came from. | `fee_type_source` (event override / series / fallback). |

Kalshi taker fee model: `fee ≈ 0.07 × c × p × (1−p)` per leg × the effective multiplier, resolved
**event override → series → labeled general fallback**.

---

## TABLE 9 — Inspector ▸ Participant Detail: CONDITIONAL PROBABILITY

A 2×3 table (`Detail`). Market-implied, **uncalibrated, display-only, not fair value**.

| Cell | Meaning | Formula |
|---|---|---|
| **P(deeper │ broader reached)** — display | Chance the deeper outcome also happens, on the dashboard price. | `price(deeper) ÷ price(parent)` (`cdisp/pdisp`). |
| **P(deeper │ broader reached)** — firm | Same, on executable bid/ask. | `child ask ÷ parent bid` (`cask/pbid`). **Diagnostic, not an edge.** |
| **P(success │ broader reached)** — display | Complement of the above (broader happens but deeper does not). | `1 − price(deeper)/price(parent)`. |
| **P(success │ broader reached)** — firm | Same, firm basis. | `1 − cask/pbid`. |

A blank cell carries a **visible reason** (`no valid parent/child quote`, `empty book`, or
`inverted display (deeper above broader)`) — a ratio is never shown above 100%.

---

## TABLE 10 — Inspector ▸ Participant Detail: LADDER PROBABILITY

One row per containment rung, broad→deep (`condRungRows`). Market-implied display ratios.

| Column | Meaning | Formula |
|---|---|---|
| **Stage** | The rung label (e.g. "Reach Final"). | `layer`. |
| **Chance of reaching** | Absolute market-implied chance of reaching the rung. | `display_pct` (the rung's display price). |
| **Given prior stage** | Conditional chance given the previous (broader) rung. | `display_pct(this) ÷ display_pct(prev) × 100`; suppressed with a note when missing / `inverted — suppressed` / `broadest`. |
| **Quote** | Quote quality at the rung. | `quote`. |

`bound` indicators (e.g. golf make-cut) render below as notes, marked "(bound, not a traded market)".

---

## TABLE 11 — Inspector ▸ Participant Detail: CONTAINMENT CHAIN (broad → deep)

The raw ladder the checker walks (`bundle.chain`).

| Column | Meaning | Source |
|---|---|---|
| **Layer** | Rung name. | `layer`. |
| **Source** | How the rung was identified. | `source`. |
| **Disp %** | Display price. | `display_pct` (midpoint when spread reasonable, else last). |
| **Bid %** | Firm YES bid. | `bid_pct`. |
| **Ask %** | Firm YES ask. | `ask_pct`. |
| **Quote** | Quote quality. | `quote`. |

A blank rung = **missing layer** (no market), **missing quote** (no usable price), or an **unverifiable
round mapping** — never a violation.

---

## TABLE 12 — Inspector ▸ Participant Detail: RAW STAGE-LADDER SPREADS

Per-adjacent-pair raw price spreads (`bundle.spreads`), broader − deeper. Raw prices, not a probability
model.

| Column | Meaning | Source |
|---|---|---|
| **From** | Broader rung. | `from_layer`. |
| **To** | Deeper rung. | `to_layer`. |
| **Spread pp** | Price gap in percentage points. | `spread_pct` = broader% − deeper%. |
| **Spread ¢** | Same gap in cents. | `spread_cents`. |
| **Quote** | Worst-leg quote of the pair. | `quote`. |

---

## TABLE 13 — Inspector ▸ Participant Detail: EXPECTED VS FOUND

Makes a missing ladder rung explicit (`bundle.expected`).

| Column | Meaning | Source |
|---|---|---|
| **Layer** | Rung that should exist. | `layer`. |
| **Found** | Whether a market was loaded for it. | `found` (bool). |
| **Source** | Where it was (or would be) sourced. | `source`. |
| **If missing** | Why it's absent. | `reason`. |

A missing rung is a **coverage gap, not an error**.

---

## TABLE 14 — Inspector ▸ Participant Detail: ALL CONTRACTS

Every contract loaded for the participant (`bundle.contracts`).

| Column | Meaning | Source |
|---|---|---|
| **Contract** | Market/contract name. | `contract`. |
| **Stage** | Ladder stage it maps to. | `stage`. |
| **Disp %** | Display price. | `display_pct`. |
| **Bid %** | Firm YES bid. | `bid_pct`. |
| **Ask %** | Firm YES ask. | `ask_pct`. |
| **Quote** | Quote quality. | `quote`. |
| **Status** | Market status. | `status` (active/finalized/settled…). |

---

## TABLE 15 — Inspector ▸ Participant Detail: RAW FIELDS · IDs & codes

Shown only when "show IDs" is on (`bundle.raw_fields`).

| Column | Meaning | Source |
|---|---|---|
| **Series** | Series ticker. | `series`. |
| **Tournament** | Tournament/grouping key. | `tournament`. |
| **T-src** | How the tournament key was derived. | `tournament_source`. |
| **Player key** | Stable identity UUID. | `player_key`. |
| **Map conf** | Mapping confidence. | `mapping_confidence` ("high" = stable UUID, "low" = name fallback). |

---

## TABLE 16 — MD Ladder (live order book)

The right-rail depth panel (`Ladder.tsx`) — the **live Kalshi resting order book** for the selected leg /
rung, re-polled ~5s. Read-only; display-only depth (still gross / top-of-book — *not* net executable
capacity). Empty/closed books say "no resting orders" (never fabricated).

| Column | Meaning | Formula |
|---|---|---|
| **Bid size** | Resting YES buy size at that price. | YES bids verbatim from the book; bar width = `size ÷ max size`. |
| **Px¢** | Price level (cents). | The price; highlighted when it equals best bid or best ask. |
| **Ask size** | Resting YES sell size at that price. | NO bids inverted: `ask price = 100 − no price`; the best YES ask comes from the highest NO bid. |

Footer shows `best bid / best ask` and "refreshed Ns ago". A **rung picker** (broad→deep, with prices)
or **leg picker** selects which market's book to display.

---

## TABLE 17 — Multi-select: COMPARE view

When you Ctrl/Cmd/Shift-click multiple rows, the selection bar offers **Compare** (`panels.tsx`), a
transposed table: one **metric per row**, one **column per selected opportunity**.

| Metric row | Source field |
|---|---|
| Sport | `sport` |
| Section | `section` |
| Tournament | `sub` |
| Cost ¢ | `cost` |
| Max loss ¢ | `max_loss` |
| Max profit ¢ | `max_profit` |
| ROI % | `roi` |
| Edge ¢ | `edge` |
| Deeper\|reached % | `cond_child` |
| Ripeness | `parent_over_maxloss` |
| Quote | `quote_health` |
| Tradable | `tradable` |

The same selection bar also offers **Open ladders** (live books side-by-side), **Export selected** (CSV),
and **⚠ Don't-take-both** — a side-aware overlap check (same participant or shared market → flags
*doubling* vs *offsetting (hedge)* exposure). These are read-only heuristics and never change ranking.

---

## TABLE 18 — Side panels: WATCH & ALERTS

`SidePanels.tsx`. Not column tables, but worth noting:

- **Watch** — the current top Actionable rows (participant · sport · detail · `edge¢`) plus a few Review
  movers. Click to load into the Inspector.
- **Alerts** — *real* diffs since the previous scan (`new` / `edge up` / `edge down` / `returned`),
  derived from the snapshot diff — never fabricated. Each shows a kind label, a description, and the
  basis of the change.

---

## Cross-cutting reminders

- **"Edge" vs "bet":** only the EXECUTABLE zone carries a true gross *edge* (`exec_gap_c > 0`, firm,
  sized). SPECULATIVE rows are **bets with a capped loss** — their EV/conditional/ripeness numbers are
  display proxies that **never** feed bucketing or ranking.
- **Display vs firm:** "display" prices are midpoints (when the spread is reasonable, else last trade);
  "firm" prices are executable bid/ask. A positive display number that a firm number doesn't confirm gets
  a **MID-ONLY** badge.
- **Conditional probabilities are uncalibrated** price ratios, gross of vig — not fair value, never an
  executable edge (especially the firm-basis pair, which is a diagnostic).
- **Fees are an estimate**, taker (immediate-fill) by default with a maker (resting-order) alternate; they
  are display-only and never rank a row.
</content>
</invoke>
