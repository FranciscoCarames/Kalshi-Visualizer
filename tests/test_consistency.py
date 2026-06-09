"""Unit tests for the layer-consistency classifier (no network)."""
from __future__ import annotations

import consistency


def leg(display_c=None, bid_c=None, ask_c=None, bid_size=100, ask_size=100,
        quality="Tight", rules="", status="active", no_ask_c=None, contract="C"):
    """Build a minimal contract row as consumed by consistency._classify/_leg."""
    return {
        "display_c": display_c,
        "yes_bid_c": bid_c,
        "yes_ask_c": ask_c,
        "yes_bid_size": bid_size,
        "yes_ask_size": ask_size,
        "quote_quality": quality,
        "rules_primary": rules,
        "status": status,
        "no_ask_c": no_ask_c,
        "contract": contract,
    }


def test_executable_violation_requires_cross_and_size():
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["status_group"] == "Broken"
    assert out["executable_gap"] == 2


# --- v1.2: executable-inconsistency profit / trade-construction context --------------
def test_forward_violation_exposes_profit_and_long_broad_short_deep():
    # child bid 37 > parent ask 35 -> long the broader (parent), short the deeper (child).
    child = leg(display_c=37, bid_c=37, ask_c=38, bid_size=80)
    parent = leg(display_c=35, bid_c=34, ask_c=35, ask_size=120)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["exec_gap_c"] == 2                       # 37 − 35
    assert out["exec_min_size"] == 80                   # min(child bid 80, parent ask 120)
    assert out["exec_max_profit_dollars"] == round(2 * 80 / 100, 2)  # 1.6
    assert out["exec_direction_label"] == "Long broader / short deeper"
    assert out["exec_long_side"] == "parent" and out["exec_long_ask_c"] == 35
    assert out["exec_short_side"] == "child" and out["exec_short_bid_c"] == 37


def test_reverse_equivalence_violation_is_long_deep_short_broad():
    # No forward cross (child bid 19 vs parent ask 40); reverse crosses (parent bid 37 vs
    # child ask 35) -> long the deeper (child), short the broader (parent).
    child = leg(display_c=30, bid_c=19, ask_c=35, ask_size=50)
    parent = leg(display_c=30, bid_c=37, ask_c=40, bid_size=90)
    out = consistency._classify(child, parent, equivalence=True)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["exec_gap_c"] == 2                       # 37 − 35
    assert out["exec_min_size"] == 50                   # min(parent bid 90, child ask 50)
    assert out["exec_direction_label"] == "Long deeper / short broader"
    assert out["exec_long_side"] == "child" and out["exec_long_ask_c"] == 35
    assert out["exec_short_side"] == "parent" and out["exec_short_bid_c"] == 37


def test_profit_fields_blank_for_clean_row():
    child = leg(display_c=20, bid_c=10, ask_c=12)
    parent = leg(display_c=50, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "CLEAN"
    for k in ("exec_gap_c", "exec_min_size", "exec_max_profit_dollars", "exec_direction_label",
              "exec_long_side", "exec_long_ask_c", "exec_short_side", "exec_short_bid_c"):
        assert out[k] is None


# --- m1: scenario payoffs (per-unit P&L in each terminal settlement state) -------------
def _check(child, parent, equivalence=False,
           child_node="Win Tournament", parent_node="Reach Final"):
    """A consistency-check row as scenario_payoffs consumes it: _classify output plus the node
    labels and contract names that build_checks/_row would attach."""
    comp = consistency._classify(child, parent, equivalence)
    return {**comp, "child_node": child_node, "parent_node": parent_node,
            "child_contract": "Deeper", "parent_contract": "Broader"}


def test_display_outright_helpers_spread_and_ratios():
    # spread = broader(parent) − deeper(child) display outright; ratios relative to each leg's outright.
    parent = leg(display_c=30)
    child = leg(display_c=20)
    assert consistency._disp_spread(parent, child) == 10
    assert consistency._disp_ratio(parent, child, "parent") == 10 / 30
    assert consistency._disp_ratio(parent, child, "child") == 10 / 20
    # A missing display leg -> spread/ratios None (no probability context).
    assert consistency._disp_spread(parent, leg(display_c=None)) is None
    assert consistency._disp_ratio(parent, leg(display_c=None), "child") is None
    # A zero (No-quote/degenerate) denominator -> that ratio is None, not a divide-by-zero.
    assert consistency._disp_ratio(leg(display_c=0), child, "parent") is None


def test_row_emits_display_outright_context():
    child = leg(display_c=20, bid_c=19, ask_c=21)
    parent = leg(display_c=30, bid_c=29, ask_c=31)
    row = consistency._row("Alcaraz", "key-a", "Win ≤ Final", child, parent,
                           consistency._classify(child, parent, equivalence=False),
                           child_node="Win Tournament", parent_node="Reach Final", tournament="T")
    assert row["parent_display_c"] == 30 and row["child_display_c"] == 20
    assert row["display_spread_c"] == 10
    assert row["spread_over_parent"] == 10 / 30 and row["spread_over_child"] == 10 / 20


# --- resolution mode (PR B): Vertical (simultaneous) vs Calendar (sequential) — presentation only ------
def _res_row(*, relationship_type, simultaneous):
    child, parent = leg(display_c=20, bid_c=19, ask_c=21), leg(display_c=30, bid_c=29, ask_c=31)
    return consistency._row("P", "k", "chain", child, parent,
                            consistency._classify(child, parent, equivalence=(relationship_type == "match_alignment")),
                            child_node="c", parent_node="p", tournament="T",
                            relationship_type=relationship_type, simultaneous=simultaneous)


def test_resolution_mode_finishing_ladder_is_vertical():
    # A finishing-position ladder pair (golf Top-N / motorsport) settles all rungs at one event -> vertical.
    assert _res_row(relationship_type="containment_adjacent", simultaneous=True)["resolution_mode"] == "vertical"


def test_resolution_mode_sequential_ladder_is_calendar():
    # A stage-advancement pair (reach final ⊇ win) settles across rounds -> calendar (the conservative base).
    assert _res_row(relationship_type="containment_adjacent", simultaneous=False)["resolution_mode"] == "calendar"


def test_resolution_mode_match_alignment_is_vertical_regardless_of_flag():
    # "QF win ≡ Reach SF" resolves at ONE match -> vertical even on a sequential-base sport.
    assert _res_row(relationship_type="match_alignment", simultaneous=False)["resolution_mode"] == "vertical"


def test_resolution_mode_defaults_to_calendar():
    child, parent = leg(display_c=20), leg(display_c=30)
    row = consistency._row("P", "k", "chain", child, parent,
                           consistency._classify(child, parent, equivalence=False),
                           child_node="c", parent_node="p", tournament="T")   # no rel / flag -> default
    assert row["resolution_mode"] == "calendar"


def test_scenario_payoffs_containment_three_states_and_floor_equals_gap():
    # child bid 37 / ask 38 > parent ask 35 → forward containment executable violation, gap 2.
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    row = _check(child, parent, equivalence=False)
    pay = consistency.scenario_payoffs(row)
    assert pay is not None
    assert pay["kind"] == "containment"
    # Buy YES parent @ 35 + Buy NO child @ (100−37)=63 → cost 98/unit.
    assert pay["cost_c"] == 98
    assert [s["payout_c"] for s in pay["scenarios"]] == [100, 200, 100]
    assert [s["profit_c"] for s in pay["scenarios"]] == [2, 102, 2]
    # Worst-case floor equals the engine's exec_gap_c (independent derivation — the key invariant).
    assert pay["worst_case_profit_c"] == row["exec_gap_c"] == 2
    assert pay["best_case_profit_c"] == 102
    # The broader-but-not-deeper middle state is the +$1/unit bonus.
    bonus = [s for s in pay["scenarios"] if s["is_bonus"]]
    assert len(bonus) == 1 and bonus[0]["profit_c"] == 102
    assert pay["roc_pct"] == round(2 / 98 * 100, 1)
    assert pay["has_rule_risk"] is False


def test_scenario_payoffs_two_floor_rows_flagged_bonus_excluded():
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    pay = consistency.scenario_payoffs(_check(child, parent))
    floors = [s for s in pay["scenarios"] if s["is_guaranteed_floor"]]
    assert len(floors) == 2 and all(s["profit_c"] == 2 for s in floors)
    assert all(not s["is_bonus"] for s in floors)


def test_scenario_payoffs_equivalence_has_rule_risk_row():
    # Reverse equivalence cross: parent bid 37 vs child ask 35 → gap 2 (long deeper / short broader).
    child = leg(display_c=30, bid_c=19, ask_c=35)
    parent = leg(display_c=30, bid_c=37, ask_c=40)
    row = _check(child, parent, equivalence=True,
                 child_node="Reach Semifinal", parent_node="Reach Semifinal")
    pay = consistency.scenario_payoffs(row)
    assert pay["kind"] == "equivalence"
    assert pay["has_rule_risk"] is True
    risk = [s for s in pay["scenarios"] if s["is_risk"]]
    assert len(risk) == 1
    assert risk[0]["payout_c"] is None and risk[0]["profit_c"] is None
    assert risk[0]["is_guaranteed_floor"] is False
    aligned = [s for s in pay["scenarios"] if not s["is_risk"]]
    assert len(aligned) == 2 and all(s["payout_c"] == 100 for s in aligned)
    # Floor still equals exec_gap_c on the winning (reverse) direction.
    assert pay["worst_case_profit_c"] == row["exec_gap_c"] == 2


def test_scenario_payoffs_units_scale_capital_and_total_floor():
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    pay = consistency.scenario_payoffs(_check(child, parent), units=80)
    assert pay["units"] == 80
    assert pay["capital_c"] == 98 * 80               # cost/unit × units
    assert pay["total_floor_profit_c"] == 2 * 80     # worst-case/unit × units
    # Per-unit numbers are unchanged by units.
    assert pay["cost_c"] == 98 and pay["worst_case_profit_c"] == 2
    # Missing units leaves the totals None.
    bare = consistency.scenario_payoffs(_check(child, parent))
    assert bare["capital_c"] is None and bare["total_floor_profit_c"] is None


def test_scenario_payoffs_none_for_non_action_row():
    child = leg(display_c=20, bid_c=10, ask_c=12)
    parent = leg(display_c=50, bid_c=58, ask_c=60)
    assert _check(child, parent)["status"] == "CLEAN"
    assert consistency.scenario_payoffs(_check(child, parent)) is None


def test_scenario_payoffs_missing_price_keeps_structure_drops_money():
    # Display-only inconsistency with no firm ask to buy at: payouts are structural, money is None.
    parent = leg(display_c=40, bid_c=None, ask_c=None, quality="One-sided")
    child = leg(display_c=50, bid_c=None, ask_c=None, quality="One-sided")
    row = _check(child, parent)
    assert row["status"] == "DISPLAY_VIOLATION"
    pay = consistency.scenario_payoffs(row)
    assert pay is not None and pay["cost_c"] is None
    assert [s["payout_c"] for s in pay["scenarios"]] == [100, 200, 100]
    assert all(s["profit_c"] is None for s in pay["scenarios"])
    assert pay["worst_case_profit_c"] is None and pay["roc_pct"] is None


def test_row_resolve_time_is_earliest_leg():
    child = {"time_value": "2026-06-08T13:00:00Z", "contract": "Deeper"}
    parent = {"time_value": "2026-06-07T11:00:00Z", "contract": "Broader"}
    comp = {"status": "CLEAN", "status_group": "Clean", "reason": "", "quote_quality": "Tight"}
    row = consistency._row("P", "k", "chain", child, parent, comp)
    assert row["resolve_time"] == "2026-06-07T11:00:00Z"      # the earlier of the two legs
    # No times anywhere → None, never an error.
    row2 = consistency._row("P", "k", "chain", {"contract": "D"}, {"contract": "B"}, comp)
    assert row2["resolve_time"] is None


def test_spread_certainty_label():
    assert consistency.spread_certainty_label("") == "Gross top-book spread"
    assert consistency.spread_certainty_label("RULE_MISMATCH") == "Rule-dependent gross spread"
    assert consistency.spread_certainty_label("RULE_CHECK_REQUIRED") == "Rule-dependent gross spread"
    # Honest wording invariant (CLAUDE.md): user-facing certainty text never says "locked".
    for flag in ("", "RULE_MISMATCH", "RULE_CHECK_REQUIRED"):
        assert "locked" not in consistency.spread_certainty_label(flag).lower()


def test_cross_without_size_downgrades_to_quote_size_missing():
    child = leg(display_c=30, bid_c=37, ask_c=38, bid_size=0)   # no firm size behind the bid
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "QUOTE_SIZE_MISSING"
    assert out["status_group"] == "Missing data"


def test_display_violation_is_warning_not_broken():
    child = leg(display_c=50, bid_c=20, ask_c=22)
    parent = leg(display_c=40, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "DISPLAY_VIOLATION"
    assert out["status_group"] == "Warning"


def test_missing_quote_when_no_firm_book():
    child = leg(display_c=10, bid_c=0, ask_c=100, quality="No quote")  # empty 0/1 book
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "MISSING_QUOTE"


def test_missing_quote_when_no_display():
    child = leg(display_c=None, bid_c=10, ask_c=12)
    parent = leg(display_c=40, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "MISSING_QUOTE"


def test_wide_quote_when_ordered_but_wide():
    child = leg(display_c=20, bid_c=10, ask_c=30, quality="Wide")
    parent = leg(display_c=50, bid_c=40, ask_c=60, quality="Wide")
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "WIDE_QUOTE"
    assert out["status_group"] == "Warning"


def test_clean_when_ordered_and_tight():
    child = leg(display_c=20, bid_c=10, ask_c=12)
    parent = leg(display_c=50, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "CLEAN"
    assert out["status_group"] == "Clean"


def test_equivalence_checks_both_directions():
    # No forward cross (child_bid 19 vs parent_ask 40), but reverse crosses
    # (parent_bid 37 vs child_ask 35) -> executable violation via the equivalence path.
    child = leg(display_c=30, bid_c=19, ask_c=35)
    parent = leg(display_c=30, bid_c=37, ask_c=40)
    out = consistency._classify(child, parent, equivalence=True)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["executable_gap"] == 2


def test_equivalence_sets_rule_flag():
    child = leg(display_c=30, bid_c=10, ask_c=12, rules="match resolves after a ball has been played; walkover voids")
    parent = leg(display_c=50, bid_c=58, ask_c=60, rules="market resolves when player qualifies")
    out = consistency._classify(child, parent, equivalence=True)
    assert out["rule_flag"] in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH")
    # differing settlement-nuance tokens -> mismatch
    assert out["rule_flag"] == "RULE_MISMATCH"

    same = consistency._classify(
        leg(display_c=30, bid_c=10, ask_c=12, rules="plain rules"),
        leg(display_c=50, bid_c=58, ask_c=60, rules="plain rules"),
        equivalence=True,
    )
    assert same["rule_flag"] == "RULE_CHECK_REQUIRED"
    # containment pairs carry no rule flag
    assert consistency._classify(leg(display_c=20, bid_c=10, ask_c=12),
                                 leg(display_c=50, bid_c=58, ask_c=60),
                                 equivalence=False)["rule_flag"] == ""


def test_expected_nodes_marks_missing_layer():
    # A player with only a winner market -> Reach SF / Reach Final missing.
    rows = [{"kind": "winner", "stage": "Champion"}]
    nodes = {n["layer"]: n for n in consistency.expected_nodes(rows)}
    assert nodes["Win Tournament"]["found"] is True
    assert nodes["Win Tournament"]["source"] == "market"
    assert nodes["Reach Semifinal"]["found"] is False
    assert nodes["Reach Final"]["found"] is False


# --- raw stage-ladder spreads (v1) ---------------------------------------------------
def _node_row(kind, stage, display_pct, display_c):
    """A minimal contract row as consumed by build_player_nodes / layer_spreads."""
    return {"kind": kind, "stage": stage, "display_pct": display_pct, "display_c": display_c}


def _full_chain(sf=60.0, final=30.0, win=10.0, sf_c=60, final_c=30, win_c=10):
    return [
        _node_row("advance", "Semifinal", sf, sf_c),
        _node_row("advance", "Final", final, final_c),
        _node_row("winner", "Champion", win, win_c),
    ]


def test_layer_spreads_full_chain():
    spreads = {(s["from_layer"], s["to_layer"]): s for s in consistency.layer_spreads(_full_chain())}
    sf_final = spreads[("Reach Semifinal", "Reach Final")]
    final_win = spreads[("Reach Final", "Win Tournament")]
    assert sf_final["status"] == "ok"
    assert sf_final["spread_pct"] == 30.0          # 60 - 30 percentage points
    assert sf_final["spread_cents"] == 30          # 60c - 30c
    assert sf_final["inverted"] is False
    assert final_win["spread_pct"] == 20.0 and final_win["spread_cents"] == 20


def test_layer_spreads_missing_layer():
    rows = [_node_row("advance", "Semifinal", 60.0, 60), _node_row("winner", "Champion", 10.0, 10)]
    spreads = {(s["from_layer"], s["to_layer"]): s for s in consistency.layer_spreads(rows)}
    # Reach Final absent -> both adjacent pairs are missing_layer, None, not inverted, no crash.
    assert spreads[("Reach Semifinal", "Reach Final")]["status"] == "missing_layer"
    assert spreads[("Reach Final", "Win Tournament")]["status"] == "missing_layer"
    for s in spreads.values():
        if s["status"] == "missing_layer":
            assert s["spread_pct"] is None and s["spread_cents"] is None and s["inverted"] is False


def test_layer_spreads_inverted():
    # Reach Final priced ABOVE Reach Semifinal -> negative spread, inverted True.
    rows = _full_chain(sf=30.0, final=40.0, sf_c=30, final_c=40)
    sf_final = next(s for s in consistency.layer_spreads(rows)
                    if (s["from_layer"], s["to_layer"]) == ("Reach Semifinal", "Reach Final"))
    assert sf_final["spread_pct"] == -10.0
    assert sf_final["inverted"] is True


def test_layer_spreads_existing_layers_missing_price():
    # Layers present but a display price is unavailable (e.g. empty book) -> missing_price, not a crash.
    rows = [
        _node_row("advance", "Semifinal", None, None),   # present, no usable display price
        _node_row("advance", "Final", 30.0, 30),
        _node_row("winner", "Champion", 10.0, 10),
    ]
    spreads = {(s["from_layer"], s["to_layer"]): s for s in consistency.layer_spreads(rows)}
    sf_final = spreads[("Reach Semifinal", "Reach Final")]
    assert sf_final["status"] == "missing_price"
    assert sf_final["spread_pct"] is None and sf_final["inverted"] is False
    # the fully-priced pair below still computes
    assert spreads[("Reach Final", "Win Tournament")]["status"] == "ok"


def test_representative_prefers_market():
    market_row = {"kind": "advance", "stage": "Final"}
    match_row = {"kind": "match", "stage": "Final"}
    assert consistency.representative({"market": market_row, "match": match_row}) is market_row
    assert consistency.representative({"match": match_row}) is match_row
    assert consistency.representative(None) is None
    assert consistency.representative({}) is None


# --- NaN-safety: the real app path is df.to_dict("records"), where None -> float NaN ----
def test_layer_spreads_missing_price_via_dataframe_records():
    """Regression: a missing display price arrives as NaN (not None) through pandas, and must
    still be classified `missing_price` — never `ok` with a NaN spread."""
    import math

    import pandas as pd

    rows = [
        _node_row("advance", "Semifinal", None, None),  # no usable price
        _node_row("advance", "Final", 30.0, 30),
        _node_row("winner", "Champion", 10.0, 10),
    ]
    records = pd.DataFrame(rows).to_dict("records")          # <-- None becomes float NaN here
    assert any(isinstance(r["display_pct"], float) and math.isnan(r["display_pct"]) for r in records)

    spreads = {(s["from_layer"], s["to_layer"]): s for s in consistency.layer_spreads(records)}
    sf_final = spreads[("Reach Semifinal", "Reach Final")]
    assert sf_final["status"] == "missing_price"            # not "ok"
    assert sf_final["spread_pct"] is None                   # not NaN
    assert sf_final["inverted"] is False
    assert spreads[("Reach Final", "Win Tournament")]["status"] == "ok"


def test_layer_spreads_reports_worst_quote():
    rows = [
        {"kind": "advance", "stage": "Semifinal", "display_pct": 60.0, "display_c": 60, "quote_quality": "Wide"},
        {"kind": "advance", "stage": "Final", "display_pct": 30.0, "display_c": 30, "quote_quality": "Tight"},
        {"kind": "winner", "stage": "Champion", "display_pct": 10.0, "display_c": 10, "quote_quality": "No quote"},
    ]
    spreads = {(s["from_layer"], s["to_layer"]): s for s in consistency.layer_spreads(rows)}
    assert spreads[("Reach Semifinal", "Reach Final")]["quote"] == "Wide"        # worse of Wide/Tight
    assert spreads[("Reach Final", "Win Tournament")]["quote"] == "No quote"     # worse of Tight/No quote


def test_classify_nan_display_c_behaves_like_missing():
    """A NaN display_c (from the records path) must not look like a present display price."""
    child = leg(display_c=float("nan"), bid_c=0, ask_c=100, quality="No quote")
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "MISSING_QUOTE"
    assert out["display_gap"] is None


# --- AUDIT-001: consistency groups by stable player_key, never display name ----------
def _ckey_row(player, key, kind, stage, display_c):
    return {
        "player": player, "player_key": key, "kind": kind, "stage": stage,
        "contract": f"{kind}-{stage}", "display_pct": float(display_c), "display_c": display_c,
        "yes_bid_c": max(display_c - 1, 0), "yes_ask_c": min(display_c + 1, 100),
        "yes_bid_pct": float(max(display_c - 1, 0)), "yes_ask_pct": float(min(display_c + 1, 100)),
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
        "market_ticker": f"TICK-{key}-{stage}", "kalshi_url": "x",
    }


def test_build_checks_groups_by_player_key_not_display_name():
    import pandas as pd
    # Two DIFFERENT competitors share the display name "Alex Smith".
    rows = [
        _ckey_row("Alex Smith", "uuid-one", "advance", "Final", 30),
        _ckey_row("Alex Smith", "uuid-two", "advance", "Semifinal", 60),
    ]
    checks = consistency.build_checks(pd.DataFrame(rows))
    # No comparison should pair one person's Final with the other person's Semifinal.
    cross = checks[(checks["child_ticker"] == "TICK-uuid-one-Final")
                   & (checks["parent_ticker"] == "TICK-uuid-two-Semifinal")]
    assert cross.empty
    # Each emitted row carries its player_key, and no row mixes the two keys.
    assert "player_key" in checks.columns
    assert set(checks["player_key"]) <= {"uuid-one", "uuid-two"}


# --- AUDIT-003: equivalence reason names the actual winning cross direction -----------
def test_equivalence_reverse_cross_reason_names_correct_legs():
    # Forward (child bid 19 vs parent ask 40) does not cross; reverse (parent bid 37 vs
    # child ask 35) crosses by 2c -> reason must describe parent bid / child ask.
    child = leg(display_c=30, bid_c=19, ask_c=35)
    parent = leg(display_c=30, bid_c=37, ask_c=40)
    out = consistency._classify(child, parent, equivalence=True)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["executable_gap"] == 2
    assert "parent bid 37c > child ask 35c" in out["reason"]
    assert "child bid 19c" not in out["reason"]


# --- AUDIT-005 (consistency side): a Crossed leg never feeds the executable test -------
def test_crossed_leg_is_not_executable():
    # Child looks like a huge cross (bid 90 > parent ask 35) but its book is Crossed.
    child = leg(display_c=50, bid_c=90, ask_c=10, quality="Crossed")
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] != "EXECUTABLE_VIOLATION"


# --- AUDIT-006: duplicate node/source rows resolve deterministically -----------------
def test_build_player_nodes_duplicate_is_deterministic():
    # Two winner rows for the same player (e.g. two winner series under a full scan).
    a = {"kind": "winner", "stage": "Champion", "display_pct": 5.0, "display_c": 5,
         "volume": 10, "market_ticker": "T-A", "quote_quality": "Tight"}
    b = {"kind": "winner", "stage": "Champion", "display_pct": 6.0, "display_c": 6,
         "volume": 99, "market_ticker": "T-B", "quote_quality": "Tight"}
    pick_ab = consistency.build_player_nodes([a, b])["Win Tournament"]["market"]
    pick_ba = consistency.build_player_nodes([b, a])["Win Tournament"]["market"]
    # order-independent, and higher volume wins the tie-break
    assert pick_ab["market_ticker"] == pick_ba["market_ticker"] == "T-B"
    assert consistency.duplicate_node_sources([a, b]) == [
        {"node": "Win Tournament", "source": "market", "count": 2}
    ]


# --- v1.3: buy-only action plan + "tradable now" + blockers --------------------------
def test_executable_containment_is_buy_yes_parent_buy_no_child():
    # child bid 37 > parent ask 35 -> Buy YES on the broader (parent), Buy NO on the deeper (child).
    child = leg(display_c=37, bid_c=37, ask_c=38, bid_size=80, no_ask_c=63)
    parent = leg(display_c=35, bid_c=34, ask_c=35, ask_size=120)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    # Two BUYS, in the required order.
    assert out["action_1_side"] == "buy_yes" and out["action_1_leg"] == "parent"
    assert out["action_2_side"] == "buy_no" and out["action_2_leg"] == "child"
    # Buy YES at the parent's ask; Buy NO at the child's real no_ask.
    assert out["action_1_price_c"] == 35          # parent_yes_ask_c
    assert out["action_2_price_c"] == 63          # child no_ask_c (real)
    # Tradable now, gross edge and units unchanged from the executable-gap math.
    assert out["tradable_now"] == "Yes"
    assert out["blockers"] == ""
    assert out["exec_gap_c"] == 2                 # child_yes_bid_c - parent_yes_ask_c
    assert out["exec_min_size"] == 80             # min(parent ask size 120, child bid size 80)
    assert out["watchlist_note"] == ""


def test_buy_no_price_falls_back_to_100_minus_child_bid():
    # No real no_ask_c on the child -> Buy NO price = 100 - child_yes_bid_c.
    child = leg(display_c=37, bid_c=37, ask_c=38, no_ask_c=None)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["action_2_price_c"] == 63          # 100 - 37


def test_tradable_now_no_when_a_leg_is_inactive():
    child = leg(display_c=37, bid_c=37, ask_c=38, no_ask_c=63)
    parent = leg(display_c=35, bid_c=34, ask_c=35, status="finalized")
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"  # firm cross + size
    assert out["tradable_now"] == "No"              # but a leg isn't open for trading
    assert "not open for trading" in out["blockers"]


def test_tradable_now_no_when_size_missing():
    child = leg(display_c=30, bid_c=37, ask_c=38, bid_size=0)  # price cross, no size behind bid
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "QUOTE_SIZE_MISSING"
    assert out["tradable_now"] == "No"
    assert "0 contracts are available" in out["blockers"]
    # still expressed as Buy YES parent / Buy NO child (the direction holds; it's just not fillable)
    assert out["action_1_side"] == "buy_yes" and out["action_1_leg"] == "parent"
    assert out["action_2_side"] == "buy_no" and out["action_2_leg"] == "child"


def test_tradable_now_no_for_display_only_violation():
    child = leg(display_c=50, bid_c=20, ask_c=22)   # display crosses, firm bid/ask don't
    parent = leg(display_c=40, bid_c=58, ask_c=60)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "DISPLAY_VIOLATION"
    assert out["tradable_now"] == "No"
    assert "estimated (mid/last) price" in out["blockers"]
    assert out["action_1_side"] == "buy_yes" and out["action_2_side"] == "buy_no"


def test_tradable_now_rule_dependent_for_equivalence_executable():
    child = leg(display_c=37, bid_c=37, ask_c=38, no_ask_c=63)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=True)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["tradable_now"] == "Yes — rule-dependent"
    assert "settlement rules" in out["blockers"]


def test_wide_quote_is_watchlist_only_no_action():
    child = leg(display_c=20, bid_c=10, ask_c=30, quality="Wide")
    parent = leg(display_c=50, bid_c=40, ask_c=60, quality="Wide")
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "WIDE_QUOTE"
    assert out["action_1_side"] is None and out["action_2_side"] is None
    assert out["watchlist_note"]                    # non-empty watchlist note
    assert out["tradable_now"] == "No"


# --- AUDIT-002 (decided: keep current behavior) --------------------------------------
def test_sizeless_cross_with_display_cross_stays_display_violation():
    """Owner decision: a sizeless price-cross that ALSO crosses on display is DISPLAY_VIOLATION
    (a Warning), not QUOTE_SIZE_MISSING."""
    child = leg(display_c=50, bid_c=37, ask_c=38, bid_size=0)   # price cross, no size behind bid
    parent = leg(display_c=40, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "DISPLAY_VIOLATION"


# --- v1.4: dashboard bucketing (bucket_of) -------------------------------------------
def crow(status, tradable_now="No", executable_gap=None, comp_quote_quality="Tight"):
    """A minimal consistency-check row as consumed by consistency.bucket_of."""
    return {
        "status": status,
        "tradable_now": tradable_now,
        "executable_gap": executable_gap,
        "comp_quote_quality": comp_quote_quality,
    }


def test_bucket_executable_actionable_vs_blocked():
    assert consistency.bucket_of(crow("EXECUTABLE_VIOLATION", tradable_now="Yes")) == "actionable"
    assert consistency.bucket_of(
        crow("EXECUTABLE_VIOLATION", tradable_now="Yes — rule-dependent")) == "actionable"
    assert consistency.bucket_of(crow("EXECUTABLE_VIOLATION", tradable_now="No")) == "blocked"


def test_bucket_quote_size_missing_is_blocked():
    assert consistency.bucket_of(crow("QUOTE_SIZE_MISSING")) == "blocked"


def test_bucket_display_and_wide_are_signals_not_blocked():
    assert consistency.bucket_of(crow("DISPLAY_VIOLATION")) == "display_signal"
    assert consistency.bucket_of(crow("WIDE_QUOTE")) == "wide_signal"


def test_bucket_data_quality_statuses():
    for s in ("MISSING_QUOTE", "MISSING_LAYER", "UNKNOWN_RELATIONSHIP"):
        assert consistency.bucket_of(crow(s)) == "data_quality"


def test_bucket_near_edge_window_and_quote_gate():
    # within [-5, 0] on Tight/OK -> near_edge (boundaries inclusive)
    assert consistency.bucket_of(crow("CLEAN", executable_gap=0, comp_quote_quality="Tight")) == "near_edge"
    assert consistency.bucket_of(crow("CLEAN", executable_gap=-5, comp_quote_quality="OK")) == "near_edge"
    assert consistency.bucket_of(crow("CLEAN", executable_gap=-2, comp_quote_quality="Tight")) == "near_edge"
    # just outside the window -> clean
    assert consistency.bucket_of(crow("CLEAN", executable_gap=-6, comp_quote_quality="Tight")) == "clean"
    # wide quote disqualifies near-edge
    assert consistency.bucket_of(crow("CLEAN", executable_gap=-2, comp_quote_quality="Wide")) == "clean"
    # no firm gap (None or NaN) -> clean
    assert consistency.bucket_of(crow("CLEAN", executable_gap=None, comp_quote_quality="Tight")) == "clean"
    assert consistency.bucket_of(crow("CLEAN", executable_gap=float("nan"), comp_quote_quality="Tight")) == "clean"


def test_bucket_covers_all_returns_are_known():
    for s in ("CLEAN", "EXECUTABLE_VIOLATION", "DISPLAY_VIOLATION", "WIDE_QUOTE",
              "MISSING_QUOTE", "MISSING_LAYER", "QUOTE_SIZE_MISSING", "UNKNOWN_RELATIONSHIP"):
        assert consistency.bucket_of(crow(s, tradable_now="Yes")) in consistency.DASHBOARD_BUCKETS


# --- v1.4: containment ladders grouped by (player_key, tournament) --------------------
def test_build_checks_groups_by_player_and_tournament():
    import pandas as pd
    # Same competitor (uuid-x) in two tournaments. FO has Reach Final + Win Tournament (a real pair);
    # Wimbledon has only Reach Semifinal. The FO ladder must NOT be completed from Wimbledon rows.
    fo_final = _ckey_row("Player X", "uuid-x", "advance", "Final", 30)
    fo_final["tournament"] = "French Open"
    fo_champ = _ckey_row("Player X", "uuid-x", "winner", "Champion", 20)
    fo_champ["tournament"] = "French Open"
    wim_sf = _ckey_row("Player X", "uuid-x", "advance", "Semifinal", 60)
    wim_sf["tournament"] = "Wimbledon"
    checks = consistency.build_checks(pd.DataFrame([fo_final, fo_champ, wim_sf]))
    assert set(checks["tournament"]) <= {"French Open", "Wimbledon"}
    # FO formed a real (non-missing) comparison; Wimbledon (only SF) is all missing-layer — no cross-fill.
    fo = checks[checks["tournament"] == "French Open"]
    wim = checks[checks["tournament"] == "Wimbledon"]
    assert (fo["status"] != "MISSING_LAYER").any()
    assert (wim["status"] == "MISSING_LAYER").all()


# --- Stage 1: opportunity schema (relationship_type / opportunity_id / blocked_reason) ----
def test_build_checks_stamps_relationship_type_and_stable_unique_id():
    import pandas as pd
    rows = [
        _ckey_row("Player X", "uuid-x", "advance", "Semifinal", 60),
        _ckey_row("Player X", "uuid-x", "advance", "Final", 40),
        _ckey_row("Player X", "uuid-x", "winner", "Champion", 20),
    ]
    df = pd.DataFrame(rows)
    checks = consistency.build_checks(df)
    assert {"relationship_type", "opportunity_id", "bucket", "blocked_reason"} <= set(checks.columns)
    assert not checks.empty
    assert set(checks["relationship_type"]) <= {"containment_adjacent", "match_alignment"}
    assert (checks["opportunity_id"].str.len() == 16).all()
    assert checks["opportunity_id"].is_unique                      # unique within the snapshot
    again = consistency.build_checks(df)                           # deterministic across rebuilds
    assert list(again["opportunity_id"]) == list(checks["opportunity_id"])


def test_unmapped_match_rows_get_unique_ids_not_colliding():
    import pandas as pd
    # Two early-round matches (R16, R32) map to no ladder node -> UNKNOWN_RELATIONSHIP. Their ids must
    # NOT collide (the node-only recipe yields empty nodes for both). An `advance` row is included so
    # the player has at least one mapped node (build_checks skips a player with no laddered nodes).
    def match_row(stage, event):
        return {"player": "P", "player_key": "uuid-p", "kind": "match", "stage": stage,
                "contract": f"match {stage}", "event_ticker": event, "quote_quality": "Tight",
                "market_ticker": f"T-{event}"}
    rows = [_ckey_row("P", "uuid-p", "advance", "Final", 40),
            match_row("Round of 16", "E-R16"), match_row("Round of 32", "E-R32")]
    checks = consistency.build_checks(pd.DataFrame(rows))
    unknown = checks[checks["status"] == "UNKNOWN_RELATIONSHIP"]
    assert len(unknown) == 2
    assert unknown["opportunity_id"].is_unique


def test_blocked_reason_nonempty_iff_bucket_blocked():
    import pandas as pd
    # A firm executable cross (child bid > parent ask, sizes > 0) with no "status" field -> the legs
    # are not "active" -> not tradable now -> EXECUTABLE_VIOLATION routed to bucket "blocked".
    child = _ckey_row("P", "uuid-p", "winner", "Champion", 40)     # bid 39 / ask 41
    parent = _ckey_row("P", "uuid-p", "advance", "Final", 35)      # bid 34 / ask 36
    checks = consistency.build_checks(pd.DataFrame([child, parent]))
    for r in checks.to_dict("records"):
        blocked = r["bucket"] == "blocked"
        assert bool(r["blocked_reason"]) == blocked         # iff invariant, every row
    assert (checks["bucket"] == "blocked").any()            # the scenario actually produced a blocked row


# --- transitive containment: bridge a missing middle rung (PR 4) ---------------------
def test_transitive_containment_bridges_missing_middle():
    """Reach Semifinal (broad) + Win Tournament (deep) present, Reach Final ABSENT. The adjacent loop
    can't compare them, so the deep-above-broad cross would be missed without the transitive bridge."""
    import pandas as pd
    semi = _ckey_row("P", "uuid-p", "advance", "Semifinal", 40)   # Reach Semifinal -> ask 41
    champ = _ckey_row("P", "uuid-p", "winner", "Champion", 70)    # Win Tournament  -> bid 69
    checks = consistency.build_checks(pd.DataFrame([semi, champ]))
    by_chain = {c["chain"]: c for _, c in checks.iterrows()}
    assert "Win Tournament ≤ Reach Semifinal" in by_chain         # the transitive bridge exists
    row = by_chain["Win Tournament ≤ Reach Semifinal"]
    assert row["relationship_type"] == "containment_transitive"
    assert row["status"] == "EXECUTABLE_VIOLATION"                # bid 69 > ask 41
    # the missing middle is still surfaced as a data-quality signal, not hidden by the bridge
    assert "MISSING_LAYER" in {c["status"] for _, c in checks.iterrows()}


def test_transitive_not_emitted_when_all_nodes_present():
    """All three rungs present -> the adjacent chain already covers it; no duplicate transitive row."""
    import pandas as pd
    rows = [
        _ckey_row("P", "uuid-p", "advance", "Semifinal", 60),
        _ckey_row("P", "uuid-p", "advance", "Final", 40),
        _ckey_row("P", "uuid-p", "winner", "Champion", 20),
    ]
    checks = consistency.build_checks(pd.DataFrame(rows))
    assert "containment_transitive" not in [c["relationship_type"] for _, c in checks.iterrows()]
