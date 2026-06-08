"""Single source of truth for the app's plain-language help text.

Pure module — NO Streamlit imports — so it can feed the UI (column tooltips + the in-app
"What do these terms mean?" expander), the consistency layer's human-readable blocker reasons, and
the documentation export all from one place. Keeping every definition here is what stops the in-app
help and the docs from drifting apart.

Two tiers per glossary term:
  - ``short`` : one line, shown in the app (tooltips + the collapsible glossary).
  - ``long``  : the in-depth version, exported on demand by ``scripts/export_glossary.py``
                (generated, not committed) and published to the Google Doc.

``BLOCKERS`` holds the reason templates for *why an opportunity is not tradable right now* (some take
``{leg}`` / ``{status}`` placeholders). ``WATCHLIST_NOTE`` is shown for consistent-but-wide rows that
are not opportunities to act on.
"""
from __future__ import annotations

# Canonical descriptor for a dutch-book finding — single-sourced so no copy drifts (the detector reason
# text and the UI captions reference it instead of inlining "locked"/"riskless"/"true arbitrage"). A dutch
# book is a gross pricing discrepancy that holds under NORMAL one-winner settlement; an abnormal resolution
# (a postponed / abandoned / no-contest game) can break it, which is why we never call it "riskless".
DUTCH_BOOK_BASIS = ("gross two-way pricing discrepancy, top-of-book, fees not modeled, under normal "
                    "one-winner settlement")

# Single-sourced evidence for a tie-capable game (game_mece_by_shape=False, e.g. NFL) that is still
# safe to dutch-book because its settlement rules prove a FIXED-SUM 2-way: a tie pays $0.50 to each
# side (so buying both legs still pays the 100¢ floor in EVERY state — A wins / B wins / tie), or no
# tie is possible. Stamped onto the finding's settlement_caveat so the UI shows WHY it was considered
# safe (truthful evidence). Conservative — never "riskless"/"locked"/"true arbitrage".
FIXED_SUM_BASIS = ("dutch-booked only because the settlement rules prove a fixed-sum two-way (a tie "
                   "pays $0.50 to each side, so the 100¢ floor holds in every outcome — or no tie is "
                   "possible); gross, top-of-book, fees not modeled")

# Single-sourced basis for a HARD-FLOOR GROUP BASKET (cardinality-floor set, e.g. World Cup group
# qualifiers): buying every leg of a per-group set pays a guaranteed floor (≥ k legs settle the bought
# side) derived from the tournament FORMAT, not a probability model. A structural hard floor — gross,
# top-of-book; conservative wording, never "riskless"/"locked"/"arbitrage" / "setup" / "model signal".
GROUP_BASKET_BASIS = ("hard-floor group basket: gross, top-of-book, fees not modeled; the guaranteed "
                      "settle-count floor is fixed by the tournament format")

# Exact-order top-two PROXY (#4) — single-sourced conservative wording. NOT an edge, NOT arbitrage: it is a
# diagnostic spread between the qualifier YES ask and a 12-leg exact-order top-two bundle, sensitive to
# stale/illiquid exact-order quotes and NOT settlement-proven.
GAME_SUPPORT_BASIS = ("ask-implied SUPPORT SCORE, NOT expected points and NOT a probability: 3·win_ask + "
                      "draw_ask summed over a team's 3 group games. Top-of-book asks are vig-biased UPWARD "
                      "(win+draw+lose > 100¢), so the score overstates — it is a heuristic ranking signal "
                      "only, gross, fees not modeled, never an edge and never executable")

EXACT_ORDER_BASIS = ("diagnostic PROXY only: the qualifier YES ask minus the cost of a 12-leg exact-order "
                     "top-two bundle. Summing one side of a 24-way book carries an OVERROUND bias (the legs "
                     "sum above fair), so the proxy is typically negative and is NOT a clean best-third "
                     "value. Gross, top-of-book, fees not modeled; 12-leg execution with thin / stale "
                     "exact-order quotes; settlement not verified — not arbitrage, never executable")

# Speculative top-two relative-value idea — single-sourced caveat. A 12-leg Buy-YES "finish top two"
# bundle, compared against the direct qualifier YES (a COMPARATOR, not a leg). Conservative wording: this
# is NOT arbitrage and NOT a qualifier replication/hedge — the best-third path breaks the equivalence.
SPECULATIVE_TOP2_BASIS = ("top-two bundle: Buy YES on the 12 exact-order outcomes where the team finishes "
                          "top two. The direct qualifier market is a comparator only, not a trade leg. This "
                          "is not arbitrage and not a qualifier replication or a hedge — best-third-place "
                          "qualification can make the direct qualifier pay while this top-two bundle pays "
                          "zero. Gross and top-of-book; fees, full depth, collateral and position limits "
                          "not modeled; 12-leg execution with thin / stale exact-order quotes; settlement "
                          "review required")

# --- Glossary terms (term -> {short, long}) ------------------------------------------
GLOSSARY: dict[str, dict[str, str]] = {
    "Tradable now": {
        "short": "Whether you could place both buys this second and lock the edge. ❌ means "
                 "something blocks it — the reason says what.",
        "long": "“Tradable now” asks a strict question: with the order book exactly as it is right "
                "this second, can you place BOTH legs of the trade and capture the edge? It is ✅ "
                "only when the inconsistency is a firm, executable price cross (real resting orders "
                "on both legs, with positive size), both markets are open for trading, and — for "
                "match-alignment pairs — the settlement rules are not in question. Anything else is "
                "❌ (or ⚠ “rule-dependent”), and the blockers list spells out exactly why.",
    },
    "Buy YES vs Buy NO": {
        "short": "Buy YES = bet the outcome happens. Buy NO = bet it does NOT happen. Every "
                 "opportunity here is two buys: Buy YES on the broader outcome and Buy NO on the "
                 "deeper one.",
        "long": "Each contract settles at $1 if its outcome happens and $0 if it doesn't. Buying "
                "YES is betting it happens; buying NO is betting it doesn't. This app only ever "
                "tells you to BUY (never “sell” or “short”). For a containment edge — where a deeper "
                "outcome (e.g. Win Tournament) is contained in a broader one (e.g. Reach Final) — "
                "the trade is: Buy YES on the broader contract and Buy NO on the deeper contract. "
                "Because the deeper event implies the broader one, that pair pays out at least $1 in "
                "every possible state, so if it costs less than $1 to assemble you have locked a "
                "risk-free gross edge.",
    },
    "Bid / Ask": {
        "short": "Bid = the best price someone will pay (where you can sell). Ask = the best price "
                 "someone will sell at (where you can buy).",
        "long": "An order book has two sides. The bid is the highest price a buyer is currently "
                "willing to pay — it's the price you'd receive if you sold right now. The ask (or "
                "offer) is the lowest price a seller is currently willing to accept — it's the price "
                "you'd pay if you bought right now. The gap between them is the spread. You buy at "
                "the ask and sell at the bid, so crossing a wide spread is a real cost.",
    },
    "Firm vs display price": {
        "short": "Firm = real resting orders you can hit now. Display = an estimate (midpoint or "
                 "last trade). “No firm cross” means only the estimate looks off — there's nothing "
                 "real to trade.",
        "long": "Every contract shows two kinds of price. The display price is an estimate — the "
                "midpoint of the bid/ask when the spread is reasonable, otherwise the last traded "
                "price. The firm price is an actual resting order (a live bid or ask with size) that "
                "you can execute against immediately. An edge is only tradable if the FIRM prices "
                "cross (a contract's firm bid is above another's firm ask). “No firm cross” means "
                "the displayed/estimated prices look inconsistent, but no real order exists to trade "
                "against — so it's a paper inconsistency, not money on the table.",
    },
    "Quote size": {
        "short": "How many contracts are available at a price. A size of 0 means a price is shown "
                 "but there's nothing actually there to fill against.",
        "long": "Each price level on the order book has a size: the number of contracts offered at "
                "that price. A book can display a price with zero size behind it (a stale or "
                "indicative quote). When that happens the prices may appear to cross, but there are "
                "no actual contracts to trade, so the edge can't be executed. A real, tradable edge "
                "needs positive size on both legs; the number of units you can fill is the smaller "
                "of the two sizes.",
    },
    "Book width": {
        "short": "The bid–ask gap. Tight ≤5¢ · OK ≤15¢ · Wide ≤30¢ · Very wide >30¢. Wide books are "
                 "illiquid and uncertain — an apparent edge can vanish once you cross the spread.",
        "long": "Book width is the spread between the best bid and best ask, graded Tight (≤5¢), OK "
                "(≤15¢), Wide (≤30¢) or Very wide (>30¢). A tight book is liquid and its midpoint is "
                "trustworthy. A wide book is illiquid: the true price is uncertain, the midpoint is "
                "unreliable, and the cost of crossing the spread to get in and out can be larger "
                "than any apparent edge. Wide-quote rows are flagged as watchlist-only rather than "
                "actionable.",
    },
    "Settlement rules / rule caveat": {
        "short": "Match-alignment compares two different markets that should be equivalent. A true "
                 "arbitrage needs identical payout rules; we can't auto-verify those, so such "
                 "findings are rule-dependent.",
        "long": "Some checks compare two DIFFERENT markets that should be logically equivalent — for "
                "example “win your quarterfinal match” and “reach the semifinal”. For these to form a "
                "true arbitrage, both markets must settle under identical conditions. But edge cases "
                "differ between markets: walkovers, retirements, withdrawals, “ball has been played” "
                "rules, cancellations. If those differ, the two contracts might not pay out together "
                "and the “edge” can break. The app does a light text comparison but cannot fully "
                "verify settlement rules automatically, so it flags these as rule-dependent: "
                "RULE_CHECK_REQUIRED (we did not confirm the rules match) or RULE_MISMATCH (the rules "
                "text visibly differs).",
    },
    "Executable inconsistency vs arbitrage": {
        "short": "We say “executable inconsistency,” not “arbitrage,” because true arbitrage also "
                 "requires the two markets' settlement rules to match — which we don't auto-verify.",
        "long": "An executable inconsistency is a firm, tradable price cross between two contracts "
                "whose probabilities have a logical ordering. We deliberately avoid the word "
                "“arbitrage”: a guaranteed arbitrage additionally requires that both markets settle "
                "on identical criteria, which we cannot verify automatically for cross-market "
                "(match-alignment) pairs. So findings are surfaced as inconsistencies you could "
                "trade — with a rule caveat where settlement compatibility is unconfirmed.",
    },
    "Containment ladder": {
        "short": "Reach Semifinal ⊇ Reach Final ⊇ Win Tournament: a deeper outcome can't be more "
                 "likely (or priced higher) than the broader outcome that contains it.",
        "long": "The app's core relationship. Reaching the semifinal contains reaching the final, "
                "which contains winning the tournament — each deeper outcome is a subset of the "
                "broader one. Because a subset can never be more probable than the set that contains "
                "it, a deeper contract must not price above its broader prerequisite. When it does — "
                "with firm, sized quotes — that's an executable inconsistency: buy YES on the broader "
                "contract and buy NO on the deeper one.",
    },
    "Dutch book": {
        "short": "A gross pricing discrepancy from covering EVERY outcome of a mutually-exclusive set for "
                 "under the payout floor — 100¢ for a 2-outcome book, (n−1)×100¢ for an n-way overround; "
                 "the gross gap per unit is the floor minus the total cost of all legs. Holds under normal "
                 "one-winner settlement (not a guaranteed lock — a postponed / abandoned game can break it).",
        "long": "A dutch book is the simplest kind of pricing discrepancy and needs no probability model. A "
                "mutually-exclusive-and-exhaustive (MECE) set of contracts has exactly one winner, so one "
                "contract settles at $1. If you can assemble a position that pays that $1 for less than its "
                "cost, the difference is a gross gap in every normal outcome. The 2-outcome case is a "
                "head-to-head match/series or a single game (draw-free sports have no third outcome). The "
                "n-outcome case is a soccer World Cup group game — three MECE outcomes (Home / Away / Tie). "
                "Two directions, each all BUYS of the SAME side: buy YES on EVERY leg when their YES asks "
                "sum to under 100¢ (an ‘underround’ — one leg pays 100¢), or buy NO on every leg when their "
                "NO asks sum to under the (n−1)×100¢ floor (an ‘overround’ — exactly one outcome wins, so "
                "the other n−1 NOs each pay 100¢). Because each market is priced on an independent order "
                "book, prices need not add to the floor, which is what creates the edge. It is a "
                + DUTCH_BOOK_BASIS + " — a gross gap, not a guaranteed lock. The legs are outcomes of the "
                "SAME event and normally settle together, but an abnormal resolution (a postponed / "
                "abandoned / no-contest game, settling to a fair price) can break that: a per-game (KX*GAME) "
                "book therefore carries a postponement settlement caveat. Match/series legs settle together "
                "under normal one-winner settlement. A fourth shape is a one-winner FIELD (many one-per-"
                "participant markets — championship, race winner, pole, fastest lap, top constructor/team — "
                "exactly one winner): it is mutually exclusive but not provably "
                "exhaustive (fewer markets than the draw), so only the overround is checked — buy NO on the "
                "priceable subset of entrants, which is safe because a winner outside that subset only pays "
                "more. Many field legs are illiquid, so these are usually only partly fillable.",
    },
    "Hard-floor group basket": {
        "short": "Buy every leg of one group's qualifier set (4 teams). The tournament format guarantees a "
                 "fixed settle-count floor, so the bundle pays at least that floor in every outcome: at "
                 "least 2 YES settle (top-2 always advance) → 200¢ floor; at least 1 NO settles (the "
                 "4th-placed team never advances) → 100¢ floor. Gross, top-of-book.",
        "long": "A group-qualifier set is NOT mutually exclusive — several teams qualify — so it is not a "
                "dutch book. It is a CARDINALITY-FLOOR basket: the World Cup format fixes how many of the "
                "four group teams can advance (top-2 automatically, plus a possible best-third; the "
                "4th-placed team never advances). So buying YES on all four legs pays at least 2×100¢ in "
                "every outcome (a 200¢ floor), and buying NO on all four pays at least 1×100¢ (a 100¢ "
                "floor). If the four firm asks for a side sum to under that side's floor, the difference is "
                "a gross gap in every outcome. This is a " + GROUP_BASKET_BASIS + ": a structural hard "
                "floor proven from the format (never inferred from prices), not a probability model and "
                "not a 'setup' or 'model signal'. All four legs must be firm to price-prove the floor; a "
                "missing-quote leg means there is simply no finding, not a blocked one. Conservative — "
                "never 'riskless' / 'locked' / 'arbitrage'.",
    },
    "Synthetic bundle": {
        "short": "A gross pricing discrepancy where a player's exact-set-score contracts (the MECE set"
                 "for them winning) are mispriced against their match-winner. NOT riskless — review the "
                 "settlement rules.",
        "long": "Unlike a dutch book (two outcomes of ONE market), a synthetic bundle spans two market "
                "families. A player wins their match iff one of the exact set scores occurs — best-of-5 "
                "{3-0, 3-1, 3-2}, best-of-3 {2-0, 2-1} — so that MECE set replicates 'they win', which is "
                "also what their match-winner market pays. Two directions: buy YES every score state + buy "
                "NO the match-winner (pays 100¢, a discrepancy when the legs cost < 100¢); or buy NO every "
                "state + buy YES the winner (pays N×100¢ for N states, a discrepancy when the legs cost < "
                "N×100¢). It is NOT true arbitrage: an exact score is not the match-winner, and on a "
                "retirement or a no-ball-played the exact-score legs resolve to Fair Market Price while the "
                "winner settles cleanly — so every finding carries a settlement caveat and is shown "
                "review-only, never actionable. The same bundle is also priced against a second hedge — the "
                "player's advance/win-tournament market at the round their match implies (winning a "
                "quarterfinal ≡ reaching the semifinal) — emitted independently, with an extra caveat "
                "(a player can advance on a walkover without winning a match). Gross of fees; sizes are "
                "top-of-book (full-depth fill not modeled).",
    },
    "Review signal": {
        "short": "A priced, sized, active discrepancy that is NOT auto-tradable because its legs are "
                 "settlement-caveated — review the rules before trading. Sits just below Actionable.",
        "long": "A review signal is a real, executable-looking pricing discrepancy whose legs may NOT "
                "settle together — currently the synthetic exact-score bundle, where an exact score is not "
                "the match-winner and a retirement / no-ball-played settles the score legs to Fair Market "
                "Price while the hedge settles cleanly. The numbers (cost, gross gap, ROI, size) are real "
                "and top-of-book, but the edge is conditional on the settlement rules, so the app never "
                "calls it Actionable: it gets its own bucket directly below Actionable to be reviewed, not "
                "executed blind. A bundle that is also un-executable now (no size / an inactive leg) drops "
                "to Blocked instead. Gross of fees; full-depth fill not modeled.",
    },
    "New actionable": {
        "short": "An opportunity that became actionable since the previous scan — it wasn't in the "
                 "last snapshot's actionable set. The banner keeps it flagged for the chosen window.",
        "long": "Opportunities are snapshotted each cross-sport scan. A 'new actionable' is an "
                "opportunity_id that is actionable in the current snapshot but was NOT actionable in the "
                "previous one — i.e. it just crossed into tradable territory. To avoid a flood on first "
                "load, nothing is flagged new until there is a prior snapshot to compare against. The "
                "banner persists a new flag for a configurable window (until next refresh / N minutes), "
                "computed from when the opportunity first became actionable, so a genuinely-new edge that "
                "stays actionable doesn't silently drop off the banner on the very next refresh.",
    },
    "Recently actionable": {
        "short": "An opportunity that WAS actionable within the selected window but isn't now — with "
                 "when it became/left actionable and why it left (went blocked / clean / leg inactive).",
        "long": "The backlog of opportunities that were actionable at some point inside the chosen "
                "window (15 min / 1 hour / 4 hours / 24 hours / this session) but are not actionable in "
                "the latest snapshot. For each, the app shows when it first became actionable, when it "
                "left, how long it lasted, the last known edge and prices, and the reason it left — "
                "derived from its current state: it disappeared, a leg went inactive, it went blocked, "
                "or it simply went clean (the edge closed). Useful for spotting opportunities you just "
                "missed and patterns in how long edges live.",
    },
    "Changed while blocked": {
        "short": "A blocked opportunity whose situation changed since the last scan — e.g. the blocker, "
                 "price, available size, market status, or rule flag moved. No change → no alert.",
        "long": "For opportunities entering, leaving, or sitting in the blocked bucket, the app diffs "
                "the two latest snapshots and labels WHAT changed: the blocker reason, the price/edge, "
                "the available size (liquidity), the market status (a leg going active↔inactive), "
                "tradability, or the settlement rule flag. An opportunity that is blocked in both "
                "snapshots with nothing changed raises no alert — only genuine movement is surfaced, so "
                "the list stays signal, not noise.",
    },
    "Gross quoted profit": {
        "short": "Profit from the displayed quotes and sizes — before fees, slippage, latency, and "
                 "partial-fill risk.",
        "long": "The edge computed straight from the quoted prices and sizes: gross edge per unit × "
                "tradable units. It is GROSS — it does not subtract exchange fees, account for "
                "slippage if the book moves while you trade, latency between placing the two legs, or "
                "the risk that only part of your order fills. Treat it as an upper bound on what the "
                "quotes imply, not a guaranteed take-home.",
    },
    "Known limits": {
        "short": "What the edges deliberately do NOT model: exchange fees, position/collateral limits, and "
                 "order-book depth beyond the top quote. Every number is gross and top-of-book — an upper "
                 "bound, not a guaranteed take-home.",
        "long": "The app reports GROSS, TOP-OF-BOOK edges and never silently nets execution costs into the "
                "actionability decision, so a finding can look positive yet be unprofitable in practice. "
                "Three limits are documented but NOT built (until the owner opts in): "
                "(1) Net-of-fees — Kalshi's trading / settlement fees are not subtracted; a thin gross gap "
                "can turn net-negative after fees. Fee metadata may be captured for honest caveats, but it "
                "never drives the gap ('gross-only' means 'don't silently net fees', not 'ignore fees'). "
                "(2) Position limits & collateral — sizes are the top-of-book quote size; the app does not "
                "model Kalshi's per-market position caps or the collateral required to hold every leg, so "
                "'Max units' and 'Gross profit' assume you can take the full quoted size. "
                "(3) Full-depth execution — prices and sizes are TOP-OF-BOOK only; filling more than the top "
                "resting size walks the book to worse prices, which is not modeled, so the displayed size is "
                "the max at the quoted price, not the total tradable edge. Treat every edge as an upper bound.",
    },
}

# --- Why-not-tradable reason templates (single-sourced, plain English) ---------------
# Some take {leg} ("broader"/"deeper") and/or {status} placeholders.
BLOCKERS: dict[str, str] = {
    "display_only": "Prices only cross on the estimated (mid/last) price — there's no real resting "
                    "order to trade against right now.",
    "size_missing": "A price shows but 0 contracts are available there — nothing to fill.",
    "no_quote": "The {leg} leg has no live order to trade against.",
    "crossed": "The {leg} leg's order book is crossed (sell price below buy price) — unreliable.",
    "inactive": "The {leg} market is {status} (not open for trading right now).",
    "rule": "These are two different markets that should be equivalent, but their settlement rules "
            "aren't confirmed to match — so this isn't guaranteed arbitrage.",
    "synthetic_settlement": "Gross discrepancy, not riskless: the exact-score legs and the match-winner "
                            "hedge are different markets. On a retirement / no-ball-played the score legs "
                            "resolve to Fair Market Price while the hedge settles cleanly — review the "
                            "settlement rules before trading.",
    "synthetic_settlement_advance": "Gross discrepancy, not riskless: the exact-score legs replicate "
                                    "winning THIS match, hedged against the reach-next-round / win-"
                                    "tournament market. Winning the match implies reaching the next round, "
                                    "but a player can also advance on a walkover/withdrawal WITHOUT a "
                                    "match — and on a retirement / no-ball-played the score legs resolve "
                                    "to Fair Market Price while the hedge settles cleanly. Review the "
                                    "settlement rules before trading.",
    "game_settlement": "Per-game settlement risk: if the game is postponed, delayed past its scheduled "
                       "start window, abandoned, ruled no-contest, or not played as originally scheduled "
                       "(some leagues then resolve to a fair market price), the legs may not settle "
                       "together and the gross gap need not hold — review the settlement rules before "
                       "trading.",
    "field_overround": "One-winner-field overround: this buys NO on the priceable subset of a "
                       "mutually-exclusive field (exactly one winner), not every entrant — safe because an "
                       "untraded or unlisted winner only pays more. Gross, top-of-book; many legs are "
                       "illiquid so the position is often only partly fillable.",
    "near_miss_flat": "Near-miss watchlist only — NOT an edge: this book costs MORE than its payout "
                      "floor, and a MECE book pays the floor in every outcome, so buying the whole "
                      "bundle now is a guaranteed gross loss. Watch it in case a leg is mispriced or it "
                      "crosses into a real discrepancy on the next tick.",
    "group_basket_settlement": "Group-stage settlement risk: if the group is restructured or abandoned, "
                               "or a team withdraws / is replaced, the qualifier set may not settle as "
                               "scheduled and the guaranteed settle-count floor need not hold — review "
                               "the settlement rules before trading.",
}

WATCHLIST_NOTE = (
    "Watchlist only — the ordering is consistent (no executable hierarchy violation); the quote is "
    "just wide."
)

# Universal "known limits" rendered as an always-visible strip above the opportunity tables, so the
# gross / top-of-book caveats are seen where rows are read (NOT repeated per-row). Authored DIRECTLY as the
# UI source of truth — short (label, tooltip) pairs — and kept aligned with the GLOSSARY["Known limits"]
# prose above (do not parse that prose). These apply to EVERY row; row-specific caveats get their own badge.
KNOWN_LIMIT_STRIP = (
    "All edge / profit / ROI / size values are GROSS and TOP-OF-BOOK — before fees, collateral, and "
    "full-depth execution. Treat every edge as an upper bound."
)
# Compact one-line variant (PR A declutter): the same honesty kept on screen without the 4-badge strip.
# The full per-aspect detail still lives in KNOWN_LIMIT_BADGES / GLOSSARY["Known limits"] for the help/
# glossary surfaces — this line is only the always-visible disclosure above the tables.
KNOWN_LIMIT_LINE = (
    "Gross, top-of-book estimates — fees / depth / collateral not fully modeled."
)
KNOWN_LIMIT_BADGES: list[tuple[str, str]] = [
    ("Gross", "Every edge / profit / ROI is GROSS — exchange trading/settlement fees are not subtracted."),
    ("Top-of-book", "Prices and sizes are TOP-OF-BOOK only; filling more than the top size walks the book "
                    "to worse prices (not modeled)."),
    ("Fees not modeled", "Kalshi fees are documented but never netted into the gap — a thin gross edge can "
                         "turn net-negative after fees."),
    ("Depth not modeled", "Order-book depth beyond the top quote isn't modeled, so 'Max units' is the top "
                          "resting size, not the total tradable edge."),
]

# Map a consistency column / concept to the glossary key whose `short` text explains it.
# Used by the dashboard so every tooltip is single-sourced, and by tests to catch orphan jargon.
COLUMN_HELP: dict[str, str] = {
    "Tradable now": "Tradable now",
    "Executable gap (¢)": "Executable inconsistency vs arbitrage",
    "Quote quality": "Book width",
    "Rule caveat": "Settlement rules / rule caveat",
    "Gross quoted profit ($)": "Gross quoted profit",
    "Buy YES": "Buy YES vs Buy NO",
    "Buy NO": "Buy YES vs Buy NO",
    "Gross edge (¢)": "Dutch book",
    "Bundle (all legs)": "Synthetic bundle",
    "Review signal": "Review signal",
    "New actionable": "New actionable",
    "Recently actionable": "Recently actionable",
    "Changed while blocked": "Changed while blocked",
}


def help_for(column_label: str) -> str:
    """Return the one-line `short` glossary text for a UI column label (or '' if none)."""
    key = COLUMN_HELP.get(column_label)
    return GLOSSARY[key]["short"] if key else ""
