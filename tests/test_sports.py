"""Unit tests for the sport abstraction + NBA engine support (no network).

Covers the M1 success criteria: unknown sport ≠ tennis; per-game NBA excluded from ladder checks;
unsupported markets surfaced with a reason; low-confidence identity flagged; tennis preserved; and an
NBA containment ladder built end-to-end through the (unchanged) detection engine.
"""
from __future__ import annotations

import pandas as pd

import consistency
import data
import sports


# --- (a) unknown sport does NOT resolve to tennis ------------------------------------
def test_unknown_series_resolves_to_unknown_not_tennis():
    assert sports.sport_for_series("KXFOO").sport_id == "unknown"
    assert sports.sport_for_series("").sport_id == "unknown"
    # Legacy `classify_kind` still yields "other" for an unrecognized ticker (back-compat),
    # but the sport is explicitly UNKNOWN — never silently tennis.
    assert data.classify_kind("KXFOO") == "other"
    assert sports.sport_for_series("KXATPMATCH").sport_id == "tennis"
    assert sports.sport_for_series("KXNBA").sport_id == "nba"


def test_registry_has_tennis_and_nba():
    ids = {c.sport_id for c in sports.all_sports()}
    assert {"tennis", "nba"} <= ids


# --- NBA classification (grounded in live discovery) ---------------------------------
def _mc(series, title):
    return sports.NBA.classify(series, {"title": title})


def test_nba_ladder_families_map_to_nodes():
    assert _mc("KXNBA", "Will the Boston win the 2026 Finals?").ladder_node == "Win Championship"
    assert _mc("KXNBAEAST", "Will Boston win the Eastern Conference Championship?").ladder_node == "Win Conference"
    finals = _mc("KXNBASERIES", "NBA Finals series winner?")
    assert finals.family == "match" and finals.ladder_node == "Win Championship"
    conff = _mc("KXNBASERIES", "Conference Finals series winner?")
    assert conff.ladder_node == "Win Conference"


# --- (b) per-game NBA market is ineligible and excluded from ladder checks ------------
def test_nba_per_game_is_ineligible_and_excluded():
    mc = _mc("KXNBAGAME", "Game 4: SAS at NYK Winner?")
    assert mc.family == "game"
    assert mc.eligible_for_ladder_checks is False
    assert mc.ladder_node is None
    # A per-game row never enters the ladder: node_of is None, build_player_nodes ignores it.
    game_row = {"series": "KXNBAGAME", "kind": "game", "stage": "", "ladder_node": None,
                "ladder_eligible": False}
    assert consistency.node_of(game_row) is None
    assert consistency.build_player_nodes([game_row]) == {}


# --- (c) unsupported contracts surface with a reason (in the row) ---------------------
def test_unsupported_markets_carry_reason():
    for series in ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL"):
        mc = _mc(series, "x")
        assert mc.eligible_for_ladder_checks is False
        assert mc.reason and "not a laddered market" in mc.reason


# --- (d) low-confidence (name-fallback) identity is marked low ------------------------
def test_nba_identity_uuid_high_else_name_low():
    high = sports.NBA.identity.resolve(
        {"yes_sub_title": "Boston", "custom_strike": {"basketball_team": "uuid-bos"}})
    assert high.confidence == "high" and high.participant_key == "uuid-bos"
    assert high.source_field == "competitor_uuid"
    low = sports.NBA.identity.resolve({"yes_sub_title": "Boston", "custom_strike": {}})
    assert low.confidence == "low" and low.participant_key == "boston"
    assert low.source_field == "name_fallback"


# --- (e) NBA ladder end-to-end through the unchanged engine ---------------------------
def _nba_market(ticker, team, uuid, bid, ask, title):
    return {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"basketball_team": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": "active", "title": title}


def _nba_event(event_ticker, markets):
    return {"event_ticker": event_ticker, "title": "NBA",
            "product_metadata": {"competition": "Pro Basketball (M)"}, "markets": markets}


def test_nba_build_contracts_stamps_ladder_fields():
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    rows = data.build_contracts("KXNBA", [champ])
    r = rows[0]
    assert r["player_key"] == "uuid-bos" and r["mapping_confidence"] == "high"
    assert r["kind"] == "winner" and r["ladder_node"] == "Win Championship"
    assert r["ladder_eligible"] is True
    assert r["tournament"] == "Pro Basketball (M)"           # grouping key from competition
    assert r["raw_custom_strike"] == {"basketball_team": "uuid-bos"}   # raw metadata preserved


def test_nba_containment_violation_is_flagged():
    # Champion (deeper) priced ABOVE conference (broader) → executable violation.
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.60", "0.62",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    conf = _nba_event("KXNBAEAST-26", [
        _nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.50", "0.55",
                    "Will the Boston win the Eastern Conference Championship?")])
    rows = data.build_contracts("KXNBA", [champ]) + data.build_contracts("KXNBAEAST", [conf])
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"]: c for _, c in checks.iterrows()}
    assert "Win Championship ≤ Win Conference" in chains
    row = chains["Win Championship ≤ Win Conference"]
    # child bid 60 > parent ask 55 → executable cross, sizes present.
    assert row["status"] == "EXECUTABLE_VIOLATION"
    assert row["exec_gap_c"] == 5


def test_nba_clean_when_ordered():
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    conf = _nba_event("KXNBAEAST-26", [
        _nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.55", "0.57",
                    "Will the Boston win the Eastern Conference Championship?")])
    rows = data.build_contracts("KXNBA", [champ]) + data.build_contracts("KXNBAEAST", [conf])
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Championship ≤ Win Conference")
    assert row["status"] == "CLEAN"


def test_nba_finals_series_aligns_with_championship():
    # A Finals SERIES winner (head-to-head) and the championship futures both map to Win Championship
    # for the same team → match-alignment equivalence row (rule-dependent, like tennis).
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    series = _nba_event("KXNBASERIES-26FIN", [
        _nba_market("KXNBASERIES-26FIN-BOS", "Boston", "uuid-bos", "0.44", "0.46",
                    "NBA Finals series winner?")])
    rows = data.build_contracts("KXNBA", [champ]) + data.build_contracts("KXNBASERIES", [series])
    checks = consistency.build_checks(pd.DataFrame(rows))
    eq = [c for _, c in checks.iterrows() if "≡ Win Championship" in c["chain"]]
    assert eq, "expected a Finals-series ≡ Win Championship equivalence row"
    assert eq[0]["rule_flag"] in ("RULE_CHECK_REQUIRED", "RULE_MISMATCH")   # rule-dependent, not arbitrage


def test_nba_early_round_series_is_unknown_relationship():
    # A 1st-round series doesn't map to a tracked ladder node → UNKNOWN_RELATIONSHIP, never a violation.
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    series = _nba_event("KXNBASERIES-26R1", [
        _nba_market("KXNBASERIES-26R1-BOS", "Boston", "uuid-bos", "0.60", "0.62",
                    "Boston 1st Round series winner?")])
    rows = data.build_contracts("KXNBA", [champ]) + data.build_contracts("KXNBASERIES", [series])
    checks = consistency.build_checks(pd.DataFrame(rows))
    assert "UNKNOWN_RELATIONSHIP" in [c["status"] for _, c in checks.iterrows()]


def test_nba_team_without_uuid_is_low_confidence():
    ev = _nba_event("KXNBA-26", [{
        "ticker": "KXNBA-26-XXX", "yes_sub_title": "Mystery Team", "custom_strike": {},
        "yes_bid_dollars": "0.10", "yes_ask_dollars": "0.12", "last_price_dollars": "0.11",
        "status": "active", "title": "Will the Mystery Team win the 2026 Pro Basketball Finals?"}])
    r = data.build_contracts("KXNBA", [ev])[0]
    assert r["mapping_confidence"] == "low"
    assert r["player_key_source"] == "name_fallback"
    assert r["player_key"] == "mystery team"


# --- tennis preservation (the abstraction didn't change tennis) ----------------------
def test_tennis_still_resolves_and_classifies():
    assert data.classify_kind("KXATPMATCH") == "match"
    assert data.classify_kind("KXFOMEN") == "winner"
    assert data.tour_of("KXWTAMATCH") == "WTA"
    assert consistency.NODE_ORDER == ("Reach Semifinal", "Reach Final", "Win Tournament")
