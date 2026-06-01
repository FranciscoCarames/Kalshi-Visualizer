"""Unit tests for the layer-consistency classifier (no network)."""
from __future__ import annotations

import consistency


def leg(display_c=None, bid_c=None, ask_c=None, bid_size=100, ask_size=100,
        quality="Tight", rules=""):
    """Build a minimal contract row as consumed by consistency._classify/_leg."""
    return {
        "display_c": display_c,
        "yes_bid_c": bid_c,
        "yes_ask_c": ask_c,
        "yes_bid_size": bid_size,
        "yes_ask_size": ask_size,
        "quote_quality": quality,
        "rules_primary": rules,
    }


def test_executable_violation_requires_cross_and_size():
    child = leg(display_c=37, bid_c=37, ask_c=38)
    parent = leg(display_c=35, bid_c=34, ask_c=35)
    out = consistency._classify(child, parent, equivalence=False)
    assert out["status"] == "EXECUTABLE_VIOLATION"
    assert out["status_group"] == "Broken"
    assert out["executable_gap"] == 2


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
