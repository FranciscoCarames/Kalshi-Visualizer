"""Unit tests for the conditional-blend detector (pure, no network).

Scenario fixtures mimic ``data.build_contracts`` rows for a World Cup final-decider: A is locked into the
final ("Reach Finals" ≈ 100); B and C contest the other final slot; the target is A's "Win the World Cup"
price. Series resolve to the soccer config so the ladder + sport grouping work end-to-end.
"""
from __future__ import annotations

import conditional_blend as cb

_REACH = "Reach Finals"
_WIN = "Win the World Cup"
_TOURN = "World Cup 2026"


def _row(node, *, key, bid_c, ask_c, status="active", quality="Tight", size=100):
    """One contract row at a ladder node. 'Reach Finals' rides KXWCROUND (advance); 'Win the World Cup'
    rides KXMENWORLDCUP (winner) — both resolve to the soccer config."""
    series = "KXWCROUND" if node == _REACH else "KXMENWORLDCUP"
    no_ask = (100 - bid_c) if bid_c is not None else None
    return {
        "series": series, "event_ticker": f"{series}-{key}", "market_ticker": f"{series}-{key}-M",
        "player": key.upper(), "player_key": key, "kind": "advance", "market_family": "advance",
        "ladder_node": node, "stage": "", "tour": "",
        "yes_bid_c": bid_c, "yes_ask_c": ask_c, "no_ask_c": no_ask,
        "display_c": ask_c, "yes_bid_size": size, "yes_ask_size": size,
        "quote_quality": quality, "status": status, "tournament": _TOURN,
        "kalshi_url": "http://x", "time_value": "2026-07-19", "rules_primary": "winner settles yes",
    }


def _final_scene(a_win_ask=68):
    """A locked finalist (A) + complementary live contenders B (60/40 win-prob) and C.
    Blend ≈ 0.6·0.70 + 0.4·0.80 = 74¢; A's win ask is `a_win_ask` (cheap)."""
    return [
        _row(_REACH, key="a", bid_c=99, ask_c=100), _row(_WIN, key="a", bid_c=a_win_ask - 2, ask_c=a_win_ask),
        _row(_REACH, key="b", bid_c=58, ask_c=62), _row(_WIN, key="b", bid_c=16, ask_c=20),
        _row(_REACH, key="c", bid_c=38, ask_c=42), _row(_WIN, key="c", bid_c=6, ask_c=10),
    ]


_FEES = {"KXMENWORLDCUP": {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1}}


def _cands(rows, **kw):
    return [f for f in cb.find_conditional_blends(rows, **kw)
            if f["status"] == cb.MODEL_BLEND_CANDIDATE]


def test_final_decider_fires_with_correct_blend():
    out = _cands(_final_scene())
    assert len(out) == 1
    f = out[0]
    assert f["adjacency_proof"] == "closed_pair_final"
    assert f["A_key"] == "a" and {f["B_key"], f["C_key"]} == {"b", "c"}
    assert f["market_implied_blend_mid_c"] == 74
    assert f["model_gap_to_ask_mid_c"] == 6                 # 74 − 68
    assert f["A_beats_B_mid"] == 0.7 and f["A_beats_C_mid"] == 0.8
    assert f["exec_gap_c"] is None                          # never executable / never ranked


def test_gate_passes_only_when_conservative_gap_beats_fees_and_fee_known():
    # cheap A → big conservative gap; with known fees the gate clears
    cheap = _cands(_final_scene(a_win_ask=50), fee_rates=_FEES)
    assert cheap and cheap[0]["gate_pass"] is True and cheap[0]["fee_known"] is True
    # same prices but unknown fee metadata → gate blocked
    no_fee = _cands(_final_scene(a_win_ask=50))
    assert no_fee and no_fee[0]["gate_pass"] is False and no_fee[0]["fee_known"] is False
    # thin gap (A not cheap) → conservative lower gap below round-trip cost → no pass
    thin = _cands(_final_scene(a_win_ask=68), fee_rates=_FEES)
    assert thin and thin[0]["gate_pass"] is False


def test_candidate_id_stable_under_bc_ordering():
    a = _cands(_final_scene())[0]["candidate_id"]
    rev = list(reversed(_final_scene()))
    b = _cands(rev)[0]["candidate_id"]
    assert a == b


def test_extra_live_contender_skips_closed_field():
    rows = _final_scene()
    rows += [_row(_REACH, key="d", bid_c=20, ask_c=24), _row(_WIN, key="d", bid_c=5, ask_c=9)]
    assert _cands(rows) == []                               # 1 locked + 3 live ≠ 1 + 2


def test_eliminated_fourth_team_does_not_block():
    rows = _final_scene()
    rows += [_row(_REACH, key="d", bid_c=0, ask_c=1)]       # dead at the rung (ask ≤ DEAD_FLOOR)
    assert len(_cands(rows)) == 1


def test_no_locked_finalist_skips():
    rows = _final_scene()
    rows[0] = _row(_REACH, key="a", bid_c=70, ask_c=74)     # A no longer locked
    assert _cands(rows) == []


def test_non_complementary_bc_skips():
    rows = _final_scene()
    # make B and C both cheap to reach the final (sum far from 100)
    rows[2] = _row(_REACH, key="b", bid_c=30, ask_c=34)
    rows[4] = _row(_REACH, key="c", bid_c=30, ask_c=34)
    assert _cands(rows) == []


def test_inverted_ratio_skips():
    rows = _final_scene()
    rows[3] = _row(_WIN, key="b", bid_c=70, ask_c=74)       # B win > B reach-final (impossible ladder)
    assert _cands(rows) == []


def test_missing_or_crossed_quote_skips():
    rows = _final_scene()
    rows[1] = _row(_WIN, key="a", bid_c=66, ask_c=68, quality="No quote")  # A target unusable
    assert _cands(rows) == []


def test_inactive_leg_skips():
    rows = _final_scene()
    rows[2] = _row(_REACH, key="b", bid_c=58, ask_c=62, status="closed")
    assert _cands(rows) == []


def test_field_underround_emitted_separately_without_arb_language():
    # A 30 + B 20 + C 10 win-asks = 60 < 100 → underround diagnostic
    rows = _final_scene(a_win_ask=30)
    allf = cb.find_conditional_blends(rows)
    under = [f for f in allf if f["status"] == cb.FIELD_UNDERROUND_DIAGNOSTIC]
    assert len(under) == 1
    assert under[0]["field_underround_c"] == 40 and under[0]["exec_gap_c"] is None
    assert "arbitrage" not in under[0]["settlement_note"].lower()
