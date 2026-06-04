"""Single source of truth for the app's plain-language help text.

Pure module — NO Streamlit imports — so it can feed the UI (column tooltips + the in-app
"What do these terms mean?" expander), the consistency layer's human-readable blocker reasons, and
the documentation export all from one place. Keeping every definition here is what stops the in-app
help and the docs from drifting apart.

Two tiers per glossary term:
  - ``short`` : one line, shown in the app (tooltips + the collapsible glossary).
  - ``long``  : the in-depth version, rendered into the Google Doc / docs/GLOSSARY.md.

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
                "under normal one-winner settlement.",
    },
    "Synthetic bundle": {
        "short": "A gross pricing discrepancy where a player's exact-set-score contracts (the MECE set "
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
                "review-only, never actionable. Gross of fees; sizes are top-of-book (full-depth fill not "
                "modeled).",
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
}

WATCHLIST_NOTE = (
    "Watchlist only — the ordering is consistent (no executable hierarchy violation); the quote is "
    "just wide."
)

# Map a consistency column / concept to the glossary key whose `short` text explains it.
# Used by app.py so every tooltip is single-sourced, and by tests to catch orphan jargon.
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
    "New actionable": "New actionable",
    "Recently actionable": "Recently actionable",
    "Changed while blocked": "Changed while blocked",
}


def help_for(column_label: str) -> str:
    """Return the one-line `short` glossary text for a UI column label (or '' if none)."""
    key = COLUMN_HELP.get(column_label)
    return GLOSSARY[key]["short"] if key else ""
