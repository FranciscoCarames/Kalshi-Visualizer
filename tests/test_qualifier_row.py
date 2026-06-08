"""PR6 — the Qualifier-setups diagnostic display row (webui.viewmodel.qualifier_row)."""

from webui import viewmodel


def _exact_order_opp():
    return {"opportunity_id": "eo1", "bucket": "qualifier_setup", "sport_label": "Soccer (World Cup)",
            "name": "Egypt", "setup_type": "exact_order_top2_proxy", "qualifier_yes_ask_c": 74,
            "qualifier_vs_top2_premium_c": -90, "n_legs": 13,
            "settlement_caveat": "diagnostic PROXY only ... not arbitrage, never executable"}


def _game_support_opp():
    return {"opportunity_id": "gs1", "bucket": "qualifier_setup", "sport_label": "Soccer (World Cup)",
            "name": "Japan", "setup_type": "game_support_signal", "qualifier_yes_ask_c": 79,
            "ask_support_score_total_c": 470, "n_legs": 3,
            "settlement_caveat": "ask-implied support score, NOT expected points ..."}


def test_exact_order_row_populates_premium_only():
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    assert r["name"] == "Egypt"
    assert r["setup"] == "Exact-order top-two (proxy)"
    assert r["qualifier"] == 74 and r["premium"] == -90
    assert r["support"] is None                 # the game-support column stays blank
    assert r["legs"] == 13 and "proxy" in r["note"].lower()


def test_game_support_row_populates_support_only():
    r = viewmodel.qualifier_row(_game_support_opp(), new_ids=set())
    assert r["setup"] == "Game support (heuristic)"
    assert r["support"] == 470 and r["qualifier"] == 79
    assert r["premium"] is None                 # the exact-order column stays blank
    assert "not expected points" in r["note"].lower()


def test_row_has_no_executable_columns():
    # A diagnostic row must never carry gross-edge / ROI / size / profit fields.
    r = viewmodel.qualifier_row(_exact_order_opp(), new_ids=set())
    for forbidden in ("edge", "roi", "units", "profit", "tradable"):
        assert forbidden not in r


def test_unknown_setup_type_falls_back():
    o = dict(_exact_order_opp(), setup_type="")
    assert viewmodel.qualifier_row(o, new_ids=set())["setup"] == "Diagnostic"
