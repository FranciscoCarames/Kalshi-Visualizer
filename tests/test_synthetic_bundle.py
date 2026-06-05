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
    # Always settlement-caveated, never Actionable -> the review_signal bucket (PR 18).
    assert g["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED"
    assert g["tradable_now"] == "Review rules" and not g["tradable_now"].startswith("Yes")
    assert g["bucket"] == "review_signal" and g["blocked_reason"]


def test_forward_payout_floor_is_100():
    # PR 13: forward bundle pays 100¢ in every covered state.
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))[0]
    assert f["payout_floor_c"] == 100


def test_reverse_fires_at_n_times_100_threshold():
    # forward 40*3+90=210 (no); reverse no_ask(90)*3 + yes_ask(20) = 290 < 300 -> gap 10.
    rows = _event(score_kw={"yes_ask_c": 40, "no_ask_c": 90}, hedge_kw={"yes_ask_c": 20, "no_ask_c": 90})
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["direction"] == "reverse" and f[0]["exec_gap_c"] == 10
    assert f[0]["payout_floor_c"] == 300                     # reverse floor = N states × 100¢ (3×100)


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
def test_priced_bundle_routes_to_review_signal():
    import consistency
    assert consistency.STATUS_GROUP[sb.EXECUTABLE_SYNTHETIC_BUNDLE] == "Warning"
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))[0]
    # PR 18: a priced/sized/active bundle ("Review rules") -> the dedicated review_signal bucket, both on
    # the finding's own field and via the router; never Actionable, no longer lumped with Blocked.
    assert f["tradable_now"] == "Review rules"
    assert f["bucket"] == "review_signal" and consistency.bucket_of(f) == "review_signal"


def test_blocked_bundle_stays_blocked_not_review():
    import consistency
    # A bundle that is un-executable now (no size) is "No" -> Blocked, not review_signal.
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2, "yes_ask_size": 0},
                                         hedge_kw={"no_ask_c": 90}))[0]
    assert f["tradable_now"] == "No"
    assert f["bucket"] == "blocked" and consistency.bucket_of(f) == "blocked"


def test_review_signal_ranks_just_below_actionable():
    import consistency
    import scanner
    # The bucket exists in both the router's list and the ranking priority, and sits below actionable,
    # above blocked (DASHBOARD_BUCKETS and BUCKET_PRIORITY stay in sync).
    assert "review_signal" in consistency.DASHBOARD_BUCKETS
    assert set(consistency.DASHBOARD_BUCKETS) == set(scanner.BUCKET_PRIORITY)
    assert scanner.BUCKET_PRIORITY["actionable"] < scanner.BUCKET_PRIORITY["review_signal"] \
        < scanner.BUCKET_PRIORITY["blocked"]


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


# --- Advancement hedge (PR 27a): score bundle vs the advance/win-tournament market it implies --------
# Winning a Quarterfinal ≡ Reach Semifinal; winning the Final ≡ Win Tournament (match_stage_to_node).
# The advance/winner markets are single-sided; the join is node-based, not a 2-participant match.
def advance_market(player_key, *, node="Reach Semifinal", event="KXATPADVANCE-26X",
                   series="KXATPADVANCE", tour="ATP", tournament="French Open", stage="Semifinal",
                   kind="advance", yes_ask_c=50, yes_bid_c=48, no_ask_c=None, yes_ask_size=100,
                   yes_bid_size=100, quality="Tight", status="active", name="Pat", **extra):
    row = {
        "kind": kind, "series": series, "event_ticker": event, "player_key": player_key,
        "tour": tour, "tournament": tournament, "stage": stage, "ladder_node": node,
        "yes_ask_c": yes_ask_c, "yes_bid_c": yes_bid_c, "no_ask_c": no_ask_c,
        "yes_ask_size": yes_ask_size, "yes_bid_size": yes_bid_size,
        "quote_quality": quality, "status": status, "player": name,
        "market_ticker": f"{event}-{player_key}", "kalshi_url": "http://a",
    }
    row.update(extra)
    return row


def _qf_scores(pk="P", **kw):
    """P's three best-of-5 score rows at the Quarterfinal (implies Reach Semifinal)."""
    return [score_market(pk, s, stage="Quarterfinal", **kw) for s in ("3-0", "3-1", "3-2")]


def test_advance_hedge_forward_fires_with_own_caveat():
    # forward cost = yes_ask(2)*3 + no_ask(advance 90) = 96 < 100 -> gap 4. No match-winner present.
    rows = _qf_scores(yes_ask_c=2) + [advance_market("P", node="Reach Semifinal", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1
    g = f[0]
    assert g["hedge_kind"] == "advance" and g["direction"] == "forward" and g["exec_gap_c"] == 4
    assert "Reach Semifinal" in g["hedge"] and g["n_legs"] == 4
    assert g["bucket"] == "review_signal" and g["rule_flag"] == "SETTLEMENT_CHECK_REQUIRED"
    assert "walkover" in g["blocked_reason"]  # the advance-specific settlement caveat


def test_advance_hedge_reverse_fires_at_n_times_100():
    # reverse: no_ask(score 90)*3 + yes_ask(advance 20) = 290 < 300 -> gap 10. (forward 40*3+90=210, no.)
    rows = _qf_scores(yes_ask_c=40, no_ask_c=90) + [advance_market("P", yes_ask_c=20, no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["hedge_kind"] == "advance"
    assert f[0]["direction"] == "reverse" and f[0]["exec_gap_c"] == 10 and f[0]["payout_floor_c"] == 300


def test_both_hedges_emit_independently_with_distinct_ids():
    # P has BOTH a match-winner hedge and an advance hedge, both firing forward (96 < 100) -> 2 findings.
    rows = _qf_scores(yes_ask_c=2)
    rows += [match_market("P", stage="Quarterfinal", no_ask_c=90), match_market("Q", stage="Quarterfinal")]
    rows += [advance_market("P", node="Reach Semifinal", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 2
    assert {g["hedge_kind"] for g in f} == {"match", "advance"}
    assert len({g["opportunity_id"] for g in f}) == 2          # distinct ids, no collision
    assert all(g["bucket"] == "review_signal" for g in f)
    by_kind = {g["hedge_kind"]: g for g in f}
    # The advance hedge leg is self-describing (carries the node); the match hedge leg is unchanged.
    assert "(Reach Semifinal)" in by_kind["advance"]["legs"][-1]["text"]
    assert "(" not in by_kind["match"]["legs"][-1]["text"]


def test_advance_hedge_winner_family_covers_the_final():
    # Winning the Final ≡ Win Tournament -> a winner-family market hedges a Final score bundle.
    rows = [score_market("P", s, stage="Final", yes_ask_c=2) for s in ("3-0", "3-1", "3-2")]
    rows += [advance_market("P", node="Win Tournament", series="KXFOMEN", event="KXFOMEN-26X",
                            kind="winner", stage="", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["hedge_kind"] == "advance" and "Win Tournament" in f[0]["hedge"]


def test_advance_hedge_wrong_node_does_not_fire():
    # A QF bundle implies Reach Semifinal; an advance market at Reach Final must NOT hedge it.
    rows = _qf_scores(yes_ask_c=2) + [advance_market("P", node="Reach Final", stage="Final", no_ask_c=90)]
    assert sb.find_synthetic_bundles(rows) == []


def test_advance_hedge_respects_safety_gates():
    # A non-binary advance leg breaks the 0-or-100¢ math -> suppressed, recorded with the hedge kind.
    rows = _qf_scores(yes_ask_c=2) + [advance_market("P", no_ask_c=90, market_type="scalar")]
    diag: dict = {}
    assert sb.find_synthetic_bundles(rows, diag) == []
    assert any("advance" in s["reason"] and "non-binary" in s["reason"] for s in diag["suppressed"])


def test_advance_hedge_no_size_emits_blocked():
    rows = _qf_scores(yes_ask_c=2, yes_ask_size=0) + [advance_market("P", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)
    assert len(f) == 1 and f[0]["hedge_kind"] == "advance"
    assert f[0]["tradable_now"] == "No" and f[0]["bucket"] == "blocked"


def test_match_hedge_opportunity_id_recipe_unchanged():
    # Regression: the match-winner id recipe stays 4-part so lifecycle tracking is continuous.
    import data
    f = sb.find_synthetic_bundles(_event(score_kw={"yes_ask_c": 2}, hedge_kw={"no_ask_c": 90}))[0]
    assert f["hedge_kind"] == "match"
    assert f["opportunity_id"] == data.opportunity_id(
        "synthetic_bundle", "KXATPEXACTMATCH-26X", "P", "forward")


def test_advance_hedge_opportunity_id_recipe_encodes_hedge_and_node():
    import data
    rows = _qf_scores(yes_ask_c=2) + [advance_market("P", node="Reach Semifinal", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)[0]
    assert f["opportunity_id"] == data.opportunity_id(
        "synthetic_bundle", "KXATPEXACTMATCH-26X", "P", "advance", "Reach Semifinal", "forward")


def test_scanner_round_trips_advance_finding():
    import scanner
    rows = _qf_scores(yes_ask_c=2) + [advance_market("P", node="Reach Semifinal", no_ask_c=90)]
    f = sb.find_synthetic_bundles(rows)[0]
    u = scanner._to_unified_synthetic(f, sports.TENNIS)
    assert "reach-next-round" in u["detail"]
    assert u["legs"] and u["n_legs"] == 4 and u["opportunity_id"] == f["opportunity_id"]


def test_advance_hedge_later_close_time_does_not_suppress():
    # Verified-live shape: an advance market's SCHEDULED close is the later stage's date, but it settles
    # on THIS match (Reach Semifinal ≡ winning the QF). The score-vs-advance gap must NOT suppress.
    rows = [score_market("P", s, stage="Quarterfinal", yes_ask_c=2, close_time="2026-06-19T12:30:00Z")
            for s in ("3-0", "3-1", "3-2")]
    rows += [advance_market("P", node="Reach Semifinal", no_ask_c=90, close_time="2026-06-22T12:30:00Z")]
    diag: dict = {}
    f = sb.find_synthetic_bundles(rows, diag)
    assert len(f) == 1 and f[0]["hedge_kind"] == "advance" and not diag.get("suppressed")


def test_advance_hedge_score_legs_split_close_time_still_suppresses():
    # The close-time gate still fires when the SCORE legs themselves close far apart (a real divergence).
    rows = [score_market("P", "3-0", stage="Quarterfinal", yes_ask_c=2, close_time="2026-06-19T12:30:00Z"),
            score_market("P", "3-1", stage="Quarterfinal", yes_ask_c=2, close_time="2026-06-19T12:30:00Z"),
            score_market("P", "3-2", stage="Quarterfinal", yes_ask_c=2, close_time="2026-06-26T12:30:00Z")]
    rows += [advance_market("P", node="Reach Semifinal", no_ask_c=90, close_time="2026-06-19T12:30:00Z")]
    diag: dict = {}
    assert sb.find_synthetic_bundles(rows, diag) == []
    assert "different times" in diag["suppressed"][0]["reason"]


def test_advance_hedge_different_tournament_does_not_join():
    # A player's advance market in another tournament must never hedge this tournament's score bundle.
    rows = _qf_scores(yes_ask_c=2)  # French Open
    rows += [advance_market("P", node="Reach Semifinal", tournament="Wimbledon", no_ask_c=90)]
    assert sb.find_synthetic_bundles(rows) == []


def test_advance_finding_renders_through_unified_api_and_webui():
    # End-to-end: a firing advance finding survives scanner -> unified row -> API model -> webui panel,
    # with the hedge leg self-describing and the advance caveat present.
    import scanner
    from api import Opportunity
    from webui import viewmodel
    g = sb.find_synthetic_bundles(_qf_scores(yes_ask_c=2)
                                  + [advance_market("P", node="Reach Semifinal", no_ask_c=90)])[0]
    assert "Pat (Reach Semifinal)" in g["legs"][-1]["text"]      # hedge leg self-describing
    u = scanner._to_unified_synthetic(g, sports.TENNIS)
    assert "reach-next-round" in u["detail"]
    o = Opportunity(**u)                                          # API boundary (extra=ignore) keeps legs
    assert o.source == "synthetic_bundle" and o.n_legs == 4 and len(o.legs) == 4
    assert o.bucket == "review_signal"
    lines = viewmodel.explanation_lines(u)                        # webui panel lists all 4 legs
    assert sum(1 for ln in lines if ln.startswith("Leg ")) == 4
    assert any("Reach Semifinal" in ln for ln in lines)
