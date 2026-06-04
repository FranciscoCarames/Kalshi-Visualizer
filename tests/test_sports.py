"""Unit tests for the sport abstraction + NBA engine support (no network).

Covers the M1 success criteria: unknown sport ≠ tennis; per-game NBA excluded from ladder checks;
unsupported markets surfaced with a reason; low-confidence identity flagged; tennis preserved; and an
NBA containment ladder built end-to-end through the (unchanged) detection engine.
"""
from __future__ import annotations

import dataclasses

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


# --- exact_series ownership (PR 2) ---------------------------------------------------
def test_exact_series_wins_over_broad_prefix_regardless_of_order(monkeypatch):
    """A sport's exact-owned ticker resolves to it even when another sport's broad prefix would also
    match AND is registered first — exact is the most specific signal (pass 1 beats pass 2)."""
    broad = dataclasses.replace(sports.NBA, sport_id="broadsport", series_prefixes=("KX",),
                                winner_tickers=frozenset(), exact_series=frozenset())
    exact = dataclasses.replace(sports.TENNIS, sport_id="exactsport", series_prefixes=(),
                                winner_tickers=frozenset(), exact_series=frozenset({"KXEXACT5"}))
    # broad registered FIRST: its "KX" prefix would grab KXEXACT5 if exact didn't win in pass 1.
    monkeypatch.setattr(sports, "_REGISTRY", {"broadsport": broad, "exactsport": exact})
    assert sports.sport_for_series("KXEXACT5").sport_id == "exactsport"   # exact wins despite order
    assert sports.sport_for_series("KXOTHER").sport_id == "broadsport"    # prefix still resolves (pass 2)
    assert sports.sport_for_series("ZZZ").sport_id == "unknown"           # owned by neither


def test_real_sports_unchanged_with_empty_exact_series():
    """Registered sports default exact_series to empty, so resolution is byte-identical to before."""
    assert sports.TENNIS.exact_series == frozenset()
    assert sports.sport_for_series("KXATPMATCH").sport_id == "tennis"
    assert sports.sport_for_series("KXNBA").sport_id == "nba"
    assert sports.sport_for_series("KXWNBA").sport_id == "wnba"   # prefix precedence still holds
    assert sports.sport_for_series("KXFOO").sport_id == "unknown"


# --- round parser: hyphenated rounds must NOT collapse to Final/Finals (all sports) --------
def _round(cfg, text):
    return sports.extract_round(cfg.round_patterns, text)


def test_round_parser_hyphenated_variants_not_final_tennis():
    # A hyphen is a word boundary, so a bare \bfinal\b used to swallow these → "Final". (sports.py)
    assert _round(sports.TENNIS, "Will X reach the Semi-final?") == "Semifinal"
    assert _round(sports.TENNIS, "Will X reach the Semi-finals?") == "Semifinal"
    assert _round(sports.TENNIS, "Will X win the Quarter-final?") == "Quarterfinal"
    assert _round(sports.TENNIS, "Will X win the Quarter-finals?") == "Quarterfinal"
    # Non-hyphenated forms and the genuine Final are unchanged.
    assert _round(sports.TENNIS, "Will X reach the Semifinal?") == "Semifinal"
    assert _round(sports.TENNIS, "Will X win the Quarterfinal?") == "Quarterfinal"
    assert _round(sports.TENNIS, "Will X win the Final?") == "Final"


def test_round_parser_hyphenated_variants_not_finals_nba():
    assert _round(sports.NBA, "Win the Conference Semi-finals?") == "Conference Semifinals"
    assert _round(sports.NBA, "Win the Conference Semifinals?") == "Conference Semifinals"
    assert _round(sports.NBA, "Win the Conference Finals?") == "Conference Finals"
    assert _round(sports.NBA, "Win the NBA Finals?") == "Finals"


def test_round_parser_hyphenated_variants_not_finals_wnba():
    assert _round(sports.WNBA, "Reach the Semi-finals?") == "Semifinals"
    assert _round(sports.WNBA, "Reach the Semifinals?") == "Semifinals"
    assert _round(sports.WNBA, "Reach the Finals?") == "Finals"


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


# --- 3-rung ladder: Reach Playoffs ⊇ Win Conference ⊇ Win Championship ----------------
def test_nba_reach_playoffs_rung_and_three_rung_ladder():
    pf = _nba_event("KXNBAPLAYOFF-26", [
        _nba_market("KXNBAPLAYOFF-26-BOS", "Boston", "uuid-bos", "0.84", "0.86",
                    "Pro Basketball Playoff Qualifiers Winner?")])
    conf = _nba_event("KXNBAEAST-26", [
        _nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.54", "0.56",
                    "Will the Boston win the Eastern Conference Championship?")])
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.39", "0.41",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    rows = (data.build_contracts("KXNBAPLAYOFF", [pf])
            + data.build_contracts("KXNBAEAST", [conf])
            + data.build_contracts("KXNBA", [champ]))
    pf_row = next(r for r in rows if r["series"] == "KXNBAPLAYOFF")
    assert pf_row["ladder_node"] == "Reach Playoffs" and pf_row["ladder_eligible"] is True
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"] for _, c in checks.iterrows()}
    assert "Win Championship ≤ Win Conference" in chains
    assert "Win Conference ≤ Reach Playoffs" in chains          # the new broad rung
    assert all(c["status"] == "CLEAN" for _, c in checks.iterrows())


def test_nba_reach_playoffs_inversion_is_flagged():
    # Win Conference (deeper) bid ABOVE Reach Playoffs (broader) ask → executable violation on the new rung.
    pf = _nba_event("KXNBAPLAYOFF-26", [
        _nba_market("KXNBAPLAYOFF-26-BOS", "Boston", "uuid-bos", "0.50", "0.55",
                    "Pro Basketball Playoff Qualifiers Winner?")])
    conf = _nba_event("KXNBAEAST-26", [
        _nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.60", "0.62",
                    "Will the Boston win the Eastern Conference Championship?")])
    rows = data.build_contracts("KXNBAPLAYOFF", [pf]) + data.build_contracts("KXNBAEAST", [conf])
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Conference ≤ Reach Playoffs")
    assert row["status"] == "EXECUTABLE_VIOLATION"
    assert row["exec_gap_c"] == 5                                # child bid 60 − parent ask 55


# --- WNBA: third sport, 4-rung reach-stage ladder, no conference ----------------------
def _wnba_market(ticker, team, uuid, bid, ask, title="x"):
    return {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"basketball_team": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": "active", "title": title}


def _wnba_event(event_ticker, markets):
    return {"event_ticker": event_ticker, "title": "WNBA",
            "product_metadata": {"competition": "Pro Basketball (W)"}, "markets": markets}


def test_wnba_registered_and_separated_from_nba():
    assert {"tennis", "nba", "wnba"} <= {c.sport_id for c in sports.all_sports()}
    # The critical prefix separation: "KXWNBA…" ≠ "KXNBA…".
    assert sports.sport_for_series("KXWNBA").sport_id == "wnba"
    assert sports.sport_for_series("KXWNBAPLAYOFF").sport_id == "wnba"
    assert sports.sport_for_series("KXNBA").sport_id == "nba"
    assert sports.sport_for_series("KXNBAPLAYOFF").sport_id == "nba"


def test_wnba_reach_stage_ladder_nodes():
    w = sports.WNBA
    assert w.classify("KXWNBAPLAYOFF", {"ticker": "KXWNBAPLAYOFF-26-ATL"}).ladder_node == "Reach Playoffs"
    assert w.classify("KXWNBASEMIFINAL", {"ticker": "KXWNBASEMIFINAL-26-ATL"}).ladder_node == "Reach Semifinals"
    assert w.classify("KXWNBAFINAL", {"ticker": "KXWNBAFINAL-26-ATL"}).ladder_node == "Reach Finals"
    assert w.classify("KXWNBA", {"ticker": "KXWNBA-26-ATL"}).ladder_node == "Win Championship"
    # per-game ineligible; the defunct conference market is not laddered (single-bracket format)
    assert w.classify("KXWNBAGAME", {"ticker": "KXWNBAGAME-26-ATL"}).eligible_for_ladder_checks is False
    assert w.classify("KXWNBAEAST", {"ticker": "KXWNBAEAST-26-ATL"}).eligible_for_ladder_checks is False


def _wnba_ladder(pf, sf, fn, ch):
    rows = (data.build_contracts("KXWNBAPLAYOFF", [_wnba_event("KXWNBAPLAYOFF-26", [_wnba_market("KXWNBAPLAYOFF-26-ATL", "Atlanta", "u", *pf)])])
            + data.build_contracts("KXWNBASEMIFINAL", [_wnba_event("KXWNBASEMIFINAL-26", [_wnba_market("KXWNBASEMIFINAL-26-ATL", "Atlanta", "u", *sf)])])
            + data.build_contracts("KXWNBAFINAL", [_wnba_event("KXWNBAFINAL-26", [_wnba_market("KXWNBAFINAL-26-ATL", "Atlanta", "u", *fn)])])
            + data.build_contracts("KXWNBA", [_wnba_event("KXWNBA-26", [_wnba_market("KXWNBA-26-ATL", "Atlanta", "u", *ch)])]))
    return consistency.build_checks(pd.DataFrame(rows))


def test_wnba_four_rung_ladder_clean():
    c = _wnba_ladder(("0.89", "0.91"), ("0.69", "0.71"), ("0.44", "0.46"), ("0.24", "0.26"))
    chains = {r["chain"]: r["status"] for _, r in c.iterrows()}
    assert chains["Reach Semifinals ≤ Reach Playoffs"] == "CLEAN"
    assert chains["Reach Finals ≤ Reach Semifinals"] == "CLEAN"
    assert chains["Win Championship ≤ Reach Finals"] == "CLEAN"


def test_wnba_ladder_inversion_flagged():
    # Reach Finals (deeper) bid above Reach Semifinals (broader) ask → executable violation.
    c = _wnba_ladder(("0.89", "0.91"), ("0.50", "0.55"), ("0.60", "0.62"), ("0.24", "0.26"))
    row = next(r for _, r in c.iterrows() if r["chain"] == "Reach Finals ≤ Reach Semifinals")
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5


def test_wnba_identity_is_basketball_team():
    r = data.build_contracts("KXWNBA", [_wnba_event("KXWNBA-26", [
        _wnba_market("KXWNBA-26-ATL", "Atlanta", "uuid-atl", "0.24", "0.26",
                     "Will Atlanta win the 2026 Women's Pro Basketball Championship?")])])[0]
    assert r["player_key"] == "uuid-atl" and r["mapping_confidence"] == "high"
    assert r["kind"] == "winner" and r["ladder_node"] == "Win Championship"
    assert r["tournament"] == "Pro Basketball (W)"


# --- tennis preservation (the abstraction didn't change tennis) ----------------------
def test_tennis_still_resolves_and_classifies():
    assert data.classify_kind("KXATPMATCH") == "match"
    assert data.classify_kind("KXFOMEN") == "winner"
    assert data.tour_of("KXWTAMATCH") == "WTA"
    assert consistency.NODE_ORDER == ("Reach Semifinal", "Reach Final", "Win Tournament")
