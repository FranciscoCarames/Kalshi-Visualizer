"""The Qualifier-setups diagnostic display row + table parity (webui.viewmodel).

Covers the top-two table-parity cleanup: the expanded `qualifier_row` (two row-families), the custom
quote-quality sort rank, the multi-key default sort, the pure leg-price-stats / tri-state leg-health
helpers, comparator evidence, stale 13-leg handling, and conservative Review-only wording.
"""

from webui import viewmodel

_FORBIDDEN = ("riskless", "locked", "hedge", "arbitrage")


def _legs(prices, sizes=None, base="KXWCGROUPORDER-B26"):
    sizes = sizes or [100] * len(prices)
    return [{"side": "buy_yes", "contract": f"outcome {i}", "price_c": p, "size": s,
             "ticker": f"{base}-{i}", "url": "", "text": f"Buy YES — outcome {i} @ {p}¢"}
            for i, (p, s) in enumerate(zip(prices, sizes))]


def _exact_order_opp(**kw):
    o = {"opportunity_id": "eo1", "bucket": "qualifier_setup", "sport_label": "Soccer (World Cup)",
         "sport": "soccer", "name": "Egypt", "source": "exact_order",
         "setup_type": "exact_order_top2_bundle", "status": "EXACT_ORDER_DIAGNOSTIC",
         "tradable_now": "Diagnostic only", "tournament": "2026 World Cup",
         "qualifier_yes_ask_c": 74, "synthetic_top_two_cost_c": 164, "qualifier_vs_top2_premium_c": -90,
         "top2_net_if_top2_c": -64, "top2_loss_if_not_top2_c": 164, "top2_max_units": 50,
         "worst_bundle_quote_quality": "Wide", "wide_bundle_leg_count": 1,
         "comparator_quote_quality": "OK", "ticker_2": "KXWCGROUPQUAL-26B-EGY",
         "legs": _legs([10, 20, 30, 40], [50, 60, 70, 80]), "n_legs": 4,
         "settlement_caveat": "top-two bundle ... not arbitrage; best-third-place qualification ..."}
    o.update(kw)
    return o


def _game_support_opp(**kw):
    o = {"opportunity_id": "gs1", "bucket": "qualifier_setup", "sport_label": "Soccer (World Cup)",
         "sport": "soccer", "name": "Japan", "source": "game_support", "setup_type": "game_support_signal",
         "status": "GAME_SUPPORT_SIGNAL", "tradable_now": "Diagnostic only", "qualifier_yes_ask_c": 79,
         "ask_support_score_total_c": 470, "n_legs": 3,
         "legs": _legs([60, 55, 50]),   # heuristic win tickers — NOT buy prices
         "settlement_caveat": "ask-implied support score, NOT expected points ..."}
    o.update(kw)
    return o


# --- exact-order row mapping ------------------------------------------------------------------------
def test_exact_order_row_core_economics():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    assert r["name"] == "Egypt" and r["setup"] == "Diagnostic top-two bundle"
    assert r["qualifier"] == 74 and r["cost"] == 164
    assert r["premium"] == -90 and r["premium_display"] == "-90¢ more expensive"
    assert r["if_top2"] == -64 and r["if_not_top2"] == 164 and r["max_units"] == 50
    assert r["legs"] == 4                              # len(_bundle_legs), not raw n_legs
    assert r["review_status"] == "Diagnostic only"
    assert r["support"] is None                        # game-support column blank for exact-order


def test_numeric_columns_are_raw_numbers_not_strings():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    for f in ("qualifier", "cost", "premium", "if_top2", "if_not_top2", "max_units", "legs",
              "highest_leg", "median_leg", "range_leg"):
        assert isinstance(r[f], (int, float)), f


def test_quote_columns_sort_on_rank_show_label():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    assert r["worst_leg_quote_rank"] == viewmodel.quote_quality_rank("Wide") == 3
    assert r["worst_leg_quote_label"] == "Wide"
    assert r["comparator_quote_rank"] == viewmodel.quote_quality_rank("OK") == 2
    assert r["comparator_quote_label"] == "OK"


def test_leg_price_stats_over_bundle_legs():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())   # prices 10/20/30/40
    assert r["highest_leg"] == 40 and r["range_leg"] == 30 and r["median_leg"] == 25


def test_caveat_badges_replace_note_in_order():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    assert "note" not in r
    assert [b["label"] for b in r["caveat_badges"]] == [
        "Comparator only", "Top-two only", "Settlement caveat"]


def test_speculative_row_label_and_premium_display():
    o = _exact_order_opp(setup_type="exact_order_top2_relative_value",
                         status="SPECULATIVE_TOP2_RELATIVE_VALUE", qualifier_vs_top2_premium_c=10,
                         tradable_now="Review execution")
    r = viewmodel.qualifier_row(o, new_ids=set())
    assert r["setup"] == "Speculative top-two bundle"
    assert r["premium"] == 10 and r["premium_display"] == "+10¢ cheaper"
    assert r["review_status"] == "Review execution"


def test_row_has_no_executable_columns():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    for forbidden in ("edge", "roi", "units", "profit", "tradable"):   # 'max_units' key is fine (!= 'units')
        assert forbidden not in r


def test_review_status_never_actionable():
    for opp in (_exact_order_opp(), _exact_order_opp(tradable_now="Review execution"),
                _game_support_opp()):
        assert "actionable" not in str(viewmodel.qualifier_row(opp, new_ids=set())["review_status"]).lower()


# --- game-support row preserved, top-two columns blank ----------------------------------------------
def test_game_support_row_blanks_top_two_columns():
    r = viewmodel.qualifier_row(_game_support_opp(), new_ids=set())
    assert r["setup"] == "Game support (heuristic)"
    assert r["support"] == 470 and r["qualifier"] == 79 and r["legs"] == 3
    for blank in ("cost", "premium", "if_top2", "if_not_top2", "max_units", "highest_leg",
                  "median_leg", "range_leg", "inactive_legs", "no_quote_legs", "worst_leg_spread"):
        assert r[blank] is None, blank
    assert r["premium_display"] == "" and r["worst_leg_quote_label"] == ""
    assert r["worst_leg_quote_rank"] == viewmodel.quote_quality_rank("Unknown") == 8
    assert r["all_legs_active"] == "Unknown"
    # No structural top-two badges on a game-support row.
    assert [b["label"] for b in r["caveat_badges"]] == ["Settlement caveat"]


# --- leg-price stats: empty / partial / never crash ------------------------------------------------
def test_leg_price_stats_blank_on_empty_or_no_prices():
    assert viewmodel._bundle_leg_price_stats({"legs": []}) == {
        "highest_leg": None, "median_leg": None, "range_leg": None}
    no_price = {"legs": [{"contract": "x", "ticker": "t"}]}    # leg without price_c
    assert viewmodel._bundle_leg_price_stats(no_price)["highest_leg"] is None


def test_leg_price_stats_handles_partial_legs():
    legs = _legs([10, 20]) + [{"contract": "x", "ticker": "t9"}]   # one leg has no price
    stats = viewmodel._bundle_leg_price_stats({"source": "exact_order", "legs": legs})
    assert stats["highest_leg"] == 20 and stats["range_leg"] == 10


# --- leg-health tri-state ---------------------------------------------------------------------------
def _lookup(*statuses_quals_spreads):
    """Build a ticker->contract lookup for the 4 default legs (KXWCGROUPORDER-B26-0..3)."""
    lk = {}
    for i, (st, qq, sp) in enumerate(statuses_quals_spreads):
        lk[f"KXWCGROUPORDER-B26-{i}"] = {"status": st, "quote_quality": qq, "spread_cents": sp}
    return lk


def test_leg_health_blank_without_lookup():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())   # no leg_lookup
    assert r["inactive_legs"] is None and r["no_quote_legs"] is None
    assert r["worst_leg_spread"] is None and r["all_legs_active"] == "Unknown"


def test_leg_health_all_active():
    lk = _lookup(("active", "Tight", 2), ("active", "OK", 6), ("active", "Tight", 3), ("active", "Wide", 20))
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set(), leg_lookup=lk)
    assert r["inactive_legs"] == 0 and r["no_quote_legs"] == 0
    assert r["all_legs_active"] == "Yes" and r["worst_leg_spread"] == 20


def test_leg_health_counts_inactive_and_no_quote_narrowly():
    # One inactive, one "No quote", one "Crossed" (NOT counted as no-quote), one fine.
    lk = _lookup(("finalized", "OK", 5), ("active", "No quote", None), ("active", "Crossed", None),
                 ("active", "Tight", 4))
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set(), leg_lookup=lk)
    assert r["inactive_legs"] == 1 and r["no_quote_legs"] == 1     # Crossed excluded
    assert r["all_legs_active"] == "No"


def test_leg_health_partial_lookup_is_unknown_not_false():
    lk = {"KXWCGROUPORDER-B26-0": {"status": "active", "quote_quality": "OK", "spread_cents": 5}}
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set(), leg_lookup=lk)
    assert r["inactive_legs"] == 0          # among resolved
    assert r["all_legs_active"] == "Unknown"   # not all legs resolved → never "Yes"/"No" fabricated


# --- comparator evidence ----------------------------------------------------------------------------
def test_comparator_spread_and_status_from_ticker_2():
    cc = {"spread_cents": 8, "status": "active", "quote_quality": "Tight"}
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set(), comparator_contract=cc)
    assert r["comparator_spread"] == 8 and r["qualifier_market_status"] == "active"
    # Quote-quality column still comes from the opp-level field, not the lookup.
    assert r["comparator_quote_label"] == "OK"


def test_comparator_blank_when_unresolved():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set(), comparator_contract=None)
    assert r["comparator_spread"] is None and r["qualifier_market_status"] == ""


# --- stale 13-leg snapshot (legacy comparator leg dropped) -----------------------------------------
def test_stale_thirteenth_comparator_leg_excluded():
    legs = _legs([10, 20, 30, 40]) + [{"contract": "Egypt qualify YES", "price_c": 74,
                                       "ticker": "KXWCGROUPQUAL-26B-EGY", "text": "qualify"}]
    r = viewmodel.qualifier_row(_exact_order_opp(legs=legs, n_legs=5), new_ids=set())
    assert r["legs"] == 4                       # the 'qualify' comparator leg is filtered out
    assert r["highest_leg"] == 40               # stats exclude it too


# --- quote-quality comparator (rank) ----------------------------------------------------------------
def test_quote_quality_rank_orders_best_to_worst():
    ranks = [viewmodel.quote_quality_rank(q) for q in viewmodel.QUOTE_QUALITY_SORT_ORDER]
    assert ranks == sorted(ranks) == list(range(1, 9))
    assert viewmodel.quote_quality_rank("") == viewmodel.quote_quality_rank("???") == 8   # blank/unknown


# --- default sort -----------------------------------------------------------------------------------
def test_order_qualifier_rows_tier_then_five_keys():
    spec = _exact_order_opp(opportunity_id="spec", status="SPECULATIVE_TOP2_RELATIVE_VALUE",
                            setup_type="exact_order_top2_relative_value")
    diag_cheap = _exact_order_opp(opportunity_id="d_cheap", qualifier_vs_top2_premium_c=20)
    diag_dear = _exact_order_opp(opportunity_id="d_dear", qualifier_vs_top2_premium_c=-5)
    game = _game_support_opp(opportunity_id="game")
    ordered = [o["opportunity_id"]
               for o in viewmodel.order_qualifier_rows([game, diag_dear, diag_cheap, spec])]
    # Speculative tier first, then diagnostics (cheaper premium first), then game-support last.
    assert ordered == ["spec", "d_cheap", "d_dear", "game"]


def test_order_qualifier_rows_quote_tiebreak_when_premium_equal():
    a = _exact_order_opp(opportunity_id="tight", worst_bundle_quote_quality="Tight",
                         qualifier_vs_top2_premium_c=5)
    b = _exact_order_opp(opportunity_id="wide", worst_bundle_quote_quality="Wide",
                         qualifier_vs_top2_premium_c=5)
    ordered = [o["opportunity_id"] for o in viewmodel.order_qualifier_rows([b, a])]
    assert ordered == ["tight", "wide"]        # equal premium → better worst-leg quote first


# --- conservative Review-only wording (visible cells/badges only) -----------------------------------
def test_visible_cells_and_badges_have_no_arbitrage_wording():
    for opp in (_exact_order_opp(), _game_support_opp()):
        r = viewmodel.qualifier_row(opp, new_ids=set())
        visible = [str(r[f]) for f in ("sport", "name", "setup", "premium_display",
                                       "worst_leg_quote_label", "comparator_quote_label",
                                       "review_status", "all_legs_active")]
        visible += [b["label"] for b in r["caveat_badges"]]
        blob = " ".join(visible).lower()
        for word in _FORBIDDEN:
            assert word not in blob, (word, blob)
    # The hidden full-caveat prose is intentionally allowed to say "not arbitrage" as a disclaimer.
    assert "arbitrage" in viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())["caveat"].lower()
