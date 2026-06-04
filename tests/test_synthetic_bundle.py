"""Unit tests for the synthetic-bundle parsing + format layer (Stage m5, Task 2). No network."""
from __future__ import annotations

import sports
import synthetic_bundle as sb


# --- parse_scoreline ------------------------------------------------------------------------
def test_parse_scoreline_from_structured_custom_strike():
    # Primary, verified-live source: custom_strike["Set Score"] (stamped as raw_custom_strike).
    row = {"raw_custom_strike": {"Set Score": "3-0", "tennis_competitor": "uuid-x"}}
    assert sb.parse_scoreline(row) == "3-0"
    assert sb.parse_scoreline({"raw_custom_strike": {"Set Score": " 2 - 1 "}}) == "2-1"


def test_parse_scoreline_falls_back_to_subtitle_regex():
    # No structured strike -> recover the score from the display subtitle.
    assert sb.parse_scoreline({"yes_sub_title": "Jakub Mensik wins 3-1"}) == "3-1"
    assert sb.parse_scoreline({"raw_custom_strike": {}, "player_name_raw": "X wins 2-0"}) == "2-0"


def test_parse_scoreline_none_when_absent_or_unparseable():
    assert sb.parse_scoreline({}) is None
    assert sb.parse_scoreline({"raw_custom_strike": None, "yes_sub_title": "no score here"}) is None
    assert sb.parse_scoreline({"raw_custom_strike": {"Set Score": ""}}) is None


# --- score_format resolver (the format must be PROVEN, not assumed from ATP/WTA alone) ------
def test_score_format_mens_grand_slam_is_best_of_5():
    assert sports.TENNIS.score_format("ATP", "French Open") == "tennis_bo5"
    assert sports.TENNIS.score_format("ATP", "Wimbledon") == "tennis_bo5"


def test_score_format_wta_and_non_slam_atp_are_best_of_3():
    assert sports.TENNIS.score_format("WTA", "French Open") == "tennis_bo3"   # women's Slam = bo3
    assert sports.TENNIS.score_format("ATP", "Rome Masters") == "tennis_bo3"  # ATP NON-Slam = bo3


def test_score_format_unprovable_tournament_returns_none():
    assert sports.TENNIS.score_format("ATP", "") is None
    assert sports.TENNIS.score_format("ATP", "Unknown · KXATPEXACTMATCH-26XYZ") is None


def test_score_format_absent_for_sports_without_bundles():
    # NBA/WNBA have no score_format_fn -> always None (so adding a sport stays one register() call).
    assert sports.NBA.score_format("ATP", "French Open") is None
    assert sports.NBA.state_bundles == {}


# --- expected_states (format-gated; independent of discovered markets) ----------------------
def test_expected_states_resolves_per_format():
    assert sb.expected_states(sports.TENNIS, "ATP", "French Open") == ("3-0", "3-1", "3-2")
    assert sb.expected_states(sports.TENNIS, "WTA", "French Open") == ("2-0", "2-1")
    assert sb.expected_states(sports.TENNIS, "ATP", "Rome Masters") == ("2-0", "2-1")


def test_expected_states_none_when_format_unprovable_or_unsupported():
    assert sb.expected_states(sports.TENNIS, "ATP", "Unknown · x") is None
    assert sb.expected_states(sports.NBA, "ATP", "French Open") is None


# --- detector: find_synthetic_bundles -------------------------------------------------------
def score_market(player_key, score, *, event="KXATPEXACTMATCH-26X", series="KXATPEXACTMATCH",
                 tour="ATP", tournament="French Open", stage="Semifinal", yes_ask_c=2, yes_bid_c=5,
                 no_ask_c=None, yes_ask_size=100, yes_bid_size=100, quality="Tight", status="active",
                 name="Pat", **extra):
    row = {
        "kind": "exact_score", "series": series, "event_ticker": event, "player_key": player_key,
        "tour": tour, "tournament": tournament, "stage": stage,
        "raw_custom_strike": {"Set Score": score, "tennis_competitor": player_key},
        "yes_ask_c": yes_ask_c, "yes_bid_c": yes_bid_c, "no_ask_c": no_ask_c,
        "yes_ask_size": yes_ask_size, "yes_bid_size": yes_bid_size,
        "quote_quality": quality, "status": status, "player": f"{name} wins {score}",
        "market_ticker": f"{event}-{player_key}-{score}", "kalshi_url": "http://x",
    }
    row.update(extra)  # market_type / close_time / rules_primary / … for the safety-gate tests
    return row


def match_market(player_key, *, event="KXATPMATCH-26X", series="KXATPMATCH", tour="ATP",
                 tournament="French Open", stage="Semifinal", yes_ask_c=50, yes_bid_c=48, no_ask_c=None,
                 yes_ask_size=100, yes_bid_size=100, quality="Tight", status="active", name="Pat", **extra):
    row = {
        "kind": "match", "series": series, "event_ticker": event, "player_key": player_key,
        "tour": tour, "tournament": tournament, "stage": stage,
        "yes_ask_c": yes_ask_c, "yes_bid_c": yes_bid_c, "no_ask_c": no_ask_c,
        "yes_ask_size": yes_ask_size, "yes_bid_size": yes_bid_size,
        "quote_quality": quality, "status": status, "player": name,
        "market_ticker": f"{event}-{player_key}", "kalshi_url": "http://m",
    }
    row.update(extra)
    return row


def _event(pk="P", opp="Q", scores=("3-0", "3-1", "3-2"), score_kw=None, hedge_kw=None):
    """P's score rows + a real 2-player match event (P & opp match-winner rows) so the hedge resolves."""
    rows = [score_market(pk, s, **(score_kw or {})) for s in scores]
    rows.append(match_market(pk, **(hedge_kw or {})))
    rows.append(match_market(opp))
    return rows


def test_forward_fires_with_settlement_caveat_and_four_legs():
    # forward cost = yes_ask(2)*3 + no_ask(90) = 96 < 100 -> gap 4.
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))
    assert len(f) == 1
    g = f[0]
    assert g["status"] == "EXECUTABLE_SYNTHETIC_BUNDLE"
    assert g["direction"] == "forward" and g["exec_gap_c"] == 4 and g["n_legs"] == 4
    assert [leg["side"] for leg in g["legs"]] == ["buy_yes", "buy_yes", "buy_yes", "buy_no"]
    # Always settlement-caveated, never Actionable.
    assert g["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED"
    assert g["tradable_now"] == "Review rules" and not g["tradable_now"].startswith("Yes")
    assert g["bucket"] == "blocked" and g["blocked_reason"]


def test_reverse_fires_at_n_times_100_threshold():
    # forward 40*3+90=210 (no); reverse no_ask(90)*3 + yes_ask(20) = 290 < 300 -> gap 10.
    rows = _event(score_kw={"yes_ask_c": 40, "no_ask_c": 90}, hedge_kw={"yes_ask_c": 20, "no_ask_c": 90})
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["direction"] == "reverse" and f[0]["exec_gap_c"] == 10


def test_single_exact_score_not_equivalent_to_match_winner():
    # A lone score (1 of 3) must never be treated as the winner -> incomplete -> no fire.
    rows = [score_market("P", "3-0", yes_ask_c=2), match_market("P", no_ask_c=90), match_market("Q")]
    assert sb.find_synthetic_bundles(rows) == []


def test_no_fire_on_missing_duplicate_or_extra_state():
    base = {"score_kw": {"yes_ask_c": 2}, "hedge_kw": {"no_ask_c": 90}}
    assert sb.find_synthetic_bundles(_event(scores=("3-0", "3-1"), **base)) == []              # missing
    assert sb.find_synthetic_bundles(_event(scores=("3-0", "3-1", "3-1"), **base)) == []        # duplicate
    assert sb.find_synthetic_bundles(_event(scores=("3-0", "3-1", "3-2", "2-1"), **base)) == []  # extra


def test_no_fire_on_unprovable_format():
    rows = _event(score_kw={"yes_ask_c": 2, "tournament": "Unknown · x"}, hedge_kw={"no_ask_c": 90})
    assert sb.find_synthetic_bundles(rows) == []


def test_no_fire_on_hard_rule_mismatch_different_round():
    # Scores are Semifinal but the hedge is Final -> hedge replicates a different event -> no emit.
    rows = _event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90, "stage": "Final"})
    assert sb.find_synthetic_bundles(rows) == []


def test_no_fire_without_a_match_winner_hedge():
    rows = [score_market("P", s, yes_ask_c=2) for s in ("3-0", "3-1", "3-2")]  # no match rows
    assert sb.find_synthetic_bundles(rows) == []


def test_missing_firm_price_does_not_emit():
    # Every leg's quote is "No quote" -> neither direction priceable -> no emit.
    rows = _event(score_kw={"yes_ask_c": 2, "quality": "No quote"},
                  hedge_kw={"no_ask_c": 90, "quality": "No quote"})
    assert sb.find_synthetic_bundles(rows) == []


def test_priced_but_no_size_emits_blocked():
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2, "yes_ask_size": 0},
                                         hedge_kw={"no_ask_c": 90}))
    assert len(f) == 1
    assert f[0]["tradable_now"] == "No" and f[0]["exec_min_size"] is None
    assert "0 contracts" in f[0]["blockers"]


def test_inactive_leg_emits_blocked():
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2, "status": "finalized"},
                                         hedge_kw={"no_ask_c": 90}))
    assert len(f) == 1
    assert f[0]["tradable_now"] == "No" and f[0]["market_status"] == "inactive"
    assert "finalized" in f[0]["blockers"]


def test_groups_by_player_key_two_players_independent():
    # Full event: P fires forward (6+90=96), Q does not (90+90=180 / reverse 285+50=335).
    rows = [score_market("P", s, yes_ask_c=2) for s in ("3-0", "3-1", "3-2")]
    rows += [score_market("Q", s, yes_ask_c=30, name="Quin") for s in ("3-0", "3-1", "3-2")]
    rows += [match_market("P", no_ask_c=90), match_market("Q", name="Quin", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["player_key"] == "P" and f[0]["direction"] == "forward"


def test_nan_safe_prices_and_sizes():
    nan = float("nan")
    rows = _event(score_kw={"yes_ask_c": 2, "yes_ask_size": nan}, hedge_kw={"no_ask_c": 90})
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["exec_min_size"] is None  # NaN size -> blocked, not a crash


# --- routing + API integration (Task 4) -----------------------------------------------------
def test_status_group_and_bucket_route_to_review_blocked():
    import consistency
    assert consistency.STATUS_GROUP[sb.EXECUTABLE_SYNTHETIC_BUNDLE] == "Warning"
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))[0]
    # "Review rules" never starts with "Yes" -> always blocked/review, never Actionable.
    assert consistency.bucket_of(f) == "blocked"


def test_opportunity_model_preserves_legs():
    from api import Opportunity
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))[0]
    o = Opportunity(**f)  # extra fields ignored; legs/n_legs are declared so they survive the boundary
    assert o.n_legs == 4 and isinstance(o.legs, list) and len(o.legs) == 4
    assert o.status == "EXECUTABLE_SYNTHETIC_BUNDLE" and o.rule_flag == "SETTLEMENT_CHECK_REQUIRED"


# --- Safety gates (synthetic hardening 2): prove the bundle settles as a clean MECE set -------
_FIRE = {"score_kw": {"yes_ask_c": 2}, "hedge_kw": {"no_ask_c": 90}}  # forward fires (96 < 100, gap 4)


def test_clean_bundle_with_safe_metadata_still_fires():
    # All legs binary, same close-time, same settlement rules -> no gate trips -> review-only finding.
    safe = {"market_type": "binary", "close_time": "2026-06-03T15:00:00Z",
            "rules_primary": "Settles on walkover or retirement."}
    rows = _event(score_kw={"yes_ask_c": 2, **safe}, hedge_kw={"no_ask_c": 90, **safe})
    diag: dict = {}
    f = sb.find_synthetic_bundles(rows, diag)
    assert len(f) == 1 and f[0]["n_legs"] == 4
    assert f[0]["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED" and f[0]["tradable_now"] == "Review rules"
    assert not diag.get("suppressed")  # nothing withheld


def test_gate_non_binary_leg_suppresses_and_records_diag():
    # A score leg that can settle scalar / fair-price breaks the 0-or-100¢ math -> suppress.
    rows = _event(score_kw={"yes_ask_c": 2, "market_type": "scalar"}, hedge_kw={"no_ask_c": 90})
    diag: dict = {}
    assert sb.find_synthetic_bundles(rows, diag) == []
    assert len(diag["suppressed"]) == 1 and "non-binary" in diag["suppressed"][0]["reason"]


def test_gate_binary_market_type_ignores_fractional_trading():
    # Live trap: fractional_trading_enabled=True is the NORM for exact-score markets -> NOT a gate.
    rows = _event(score_kw={"yes_ask_c": 2, "market_type": "binary", "fractional_trading_enabled": True},
                  hedge_kw={"no_ask_c": 90, "market_type": "binary", "fractional_trading_enabled": True})
    assert len(sb.find_synthetic_bundles(rows)) == 1


def test_gate_split_close_time_suppresses():
    # Hedge closes two days after the score legs -> they can't settle together -> suppress.
    rows = _event(score_kw={"yes_ask_c": 2, "close_time": "2026-06-03T15:00:00Z"},
                  hedge_kw={"no_ask_c": 90, "close_time": "2026-06-05T15:00:00Z"})
    diag: dict = {}
    assert sb.find_synthetic_bundles(rows, diag) == []
    assert "different times" in diag["suppressed"][0]["reason"]


def test_gate_close_time_within_tolerance_does_not_suppress():
    # A few minutes apart (< 6h tolerance) is the same match -> still fires.
    rows = _event(score_kw={"yes_ask_c": 2, "close_time": "2026-06-03T15:00:00Z"},
                  hedge_kw={"no_ask_c": 90, "close_time": "2026-06-03T15:05:00Z"})
    assert len(sb.find_synthetic_bundles(rows)) == 1


def test_gate_partial_close_time_does_not_suppress():
    # Only the hedge has a close-time -> unprovable divergence -> don't suppress (absent metadata passes).
    rows = _event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90, "close_time": "2026-06-05T00:00:00Z"})
    assert len(sb.find_synthetic_bundles(rows)) == 1


def test_gate_rule_token_divergence_suppresses():
    # Hedge voids on a walkover the score legs don't mention -> divergent settlement -> suppress.
    rows = _event(score_kw={"yes_ask_c": 2, "rules_primary": "Settles to the exact set score."},
                  hedge_kw={"no_ask_c": 90, "rules_primary": "Void on walkover."})
    diag: dict = {}
    assert sb.find_synthetic_bundles(rows, diag) == []
    assert "walkover" in diag["suppressed"][0]["reason"]


def test_gate_matching_rule_tokens_do_not_suppress():
    # Same nuance on every leg -> agreement, not divergence -> still fires (caveat carries the residual risk).
    shared = {"rules_primary": "Void on walkover or retirement."}
    rows = _event(score_kw={"yes_ask_c": 2, **shared}, hedge_kw={"no_ask_c": 90, **shared})
    assert len(sb.find_synthetic_bundles(rows)) == 1


def test_absent_safety_metadata_passes_all_gates():
    # No market_type / close_time / rules_primary on any leg -> nothing PROVEN unsafe -> fires (back-compat).
    assert len(sb.find_synthetic_bundles(_event(**_FIRE))) == 1


def test_format_proof_not_back_inferred_from_present_states():
    # Circularity guard: an ATP Slam (proven best-of-5 from metadata) shown only the BO3 set {2-0,2-1}
    # must NOT be re-read as best-of-3 -> expected stays {3-0,3-1,3-2} -> incomplete -> no fire.
    rows = _event(scores=("2-0", "2-1"), score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90})
    assert sb.find_synthetic_bundles(rows) == []
    assert sb.expected_states(sports.TENNIS, "ATP", "French Open") == ("3-0", "3-1", "3-2")
