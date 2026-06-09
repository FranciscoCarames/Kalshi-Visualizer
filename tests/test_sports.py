"""Unit tests for the sport abstraction + NBA engine support (no network).

Covers the M1 success criteria: unknown sport ≠ tennis; per-game NBA excluded from ladder checks;
unsupported markets surfaced with a reason; low-confidence identity flagged; tennis preserved; and an
NBA containment ladder built end-to-end through the (unchanged) detection engine.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

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
    """A prefix-owned sport defaults exact_series to empty, so resolution is byte-identical to before.
    (Tennis now exact-owns ITF — see test_itf_* — so NBA is the empty-exact_series exemplar here.)"""
    assert sports.NBA.exact_series == frozenset()
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
    assert r["tournament"] == "Pro Basketball (M) · 26"      # competition + season token (event KXNBA-26)
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


def test_nba_categories_use_nba_labels_not_tennis():
    """PR 3: per-sport category dispatch — an NBA comparison row carries NBA category labels (resolved
    off each leg's own sport), never the tennis CATEGORY labels or a blank."""
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])
    conf = _nba_event("KXNBAEAST-26", [
        _nba_market("KXNBAEAST-26-BOS", "Boston", "uuid-bos", "0.55", "0.57",
                    "Will the Boston win the Eastern Conference Championship?")])
    rows = data.build_contracts("KXNBA", [champ]) + data.build_contracts("KXNBAEAST", [conf])
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Championship ≤ Win Conference")
    # child = Win Championship (kind "winner"); parent = Win Conference (kind "advance").
    assert row["child_category"] == "Championship"                  # NBA winner label
    assert row["parent_category"] == "Advancement (reach a stage)"  # NBA advance label
    assert row["child_category"] != "Tournament winner"             # NOT the tennis label (the bug)


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


def test_nba_transitive_containment_bridges_missing_conference():
    """PR 4: Reach Playoffs + Win Championship present, Win Conference ABSENT -> the broad-vs-deep cross
    still fires via the transitive bridge (it would be missed by adjacent-only comparisons)."""
    pf = _nba_event("KXNBAPLAYOFF-26", [
        _nba_market("KXNBAPLAYOFF-26-BOS", "Boston", "uuid-bos", "0.50", "0.55",
                    "Pro Basketball Playoff Qualifiers Winner?")])            # Reach Playoffs (broad) -> ask 55
    champ = _nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.60", "0.62",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])  # Win Championship (deep) -> bid 60
    rows = data.build_contracts("KXNBAPLAYOFF", [pf]) + data.build_contracts("KXNBA", [champ])
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Championship ≤ Reach Playoffs")
    assert row["relationship_type"] == "containment_transitive"
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5   # bid 60 − ask 55


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
    assert r["tournament"] == "Pro Basketball (W) · 26"      # competition + season token (event KXWNBA-26)


# --- tennis preservation (the abstraction didn't change tennis) ----------------------
def test_tennis_still_resolves_and_classifies():
    assert data.classify_kind("KXATPMATCH") == "match"
    assert data.classify_kind("KXFOMEN") == "winner"
    assert data.tour_of("KXWTAMATCH") == "WTA"
    assert consistency.NODE_ORDER == ("Reach Semifinal", "Reach Final", "Win Tournament")


# --- Golf (5th sport): finishing-position ladder, exact-series ownership, no head-to-head -----
def _golf_market(ticker, name, uuid, bid, ask, title="x"):
    return {"ticker": ticker, "yes_sub_title": name, "custom_strike": {"golf_competitor": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": "active", "title": title}


def _golf_event(event_ticker, markets, competition="U.S. Open"):
    return {"event_ticker": event_ticker, "title": "PGA",
            "product_metadata": {"competition": competition}, "markets": markets}


def _golf_ladder(t20, t10, t5, win=None, competition="U.S. Open"):
    rows = (data.build_contracts("KXPGATOP20", [_golf_event("KXPGATOP20-26USO", [_golf_market("KXPGATOP20-26USO-SCO", "Scheffler", "u", *t20)], competition)])
            + data.build_contracts("KXPGATOP10", [_golf_event("KXPGATOP10-26USO", [_golf_market("KXPGATOP10-26USO-SCO", "Scheffler", "u", *t10)], competition)])
            + data.build_contracts("KXPGATOP5", [_golf_event("KXPGATOP5-26USO", [_golf_market("KXPGATOP5-26USO-SCO", "Scheffler", "u", *t5)], competition)]))
    if win is not None:
        rows += data.build_contracts("KXPGATOUR", [_golf_event("KXPGATOUR-26USO", [_golf_market("KXPGATOUR-26USO-SCO", "Scheffler", "u", *win)], competition)])
    return consistency.build_checks(pd.DataFrame(rows))


def test_golf_registered_and_exact_only_ownership():
    assert {"tennis", "nba", "wnba", "golf"} <= {c.sport_id for c in sports.all_sports()}
    for tk in ("KXPGATOP5", "KXPGATOP10", "KXPGATOP20", "KXPGATOUR"):
        assert sports.sport_for_series(tk).sport_id == "golf", tk
    # False-positive guards: round-finishers / H2H / props share the golf_competitor UUID + competition
    # string but must NOT be owned by golf — exact_series ownership excludes them (resolve to unknown).
    for tk in ("KXPGAR1TOP5", "KXPGAR2TOP10", "KXPGAH2H", "KXPGATOURCHAMP", "KXPGAWIN"):
        assert sports.sport_for_series(tk).sport_id == "unknown", tk


def test_golf_classification_per_rung():
    g = sports.GOLF
    assert g.classify("KXPGATOP5", {"ticker": "KXPGATOP5-26USO-X"}).ladder_node == "Top 5"
    assert g.classify("KXPGATOP10", {"ticker": "KXPGATOP10-26USO-X"}).ladder_node == "Top 10"
    assert g.classify("KXPGATOP20", {"ticker": "KXPGATOP20-26USO-X"}).ladder_node == "Top 20"
    win = g.classify("KXPGATOUR", {"ticker": "KXPGATOUR-26USO-X"})    # winner by SERIES identity, not scope
    assert win.family == "winner" and win.ladder_node == "Win Tournament"
    assert all(g.classify(s, {"ticker": s + "-26USO-X"}).eligible_for_ladder_checks
               for s in ("KXPGATOP5", "KXPGATOP10", "KXPGATOP20", "KXPGATOUR"))


def test_golf_build_contracts_stamps_ladder_fields():
    top5 = _golf_event("KXPGATOP5-26USO", [
        _golf_market("KXPGATOP5-26USO-SCO", "Scheffler", "uuid-sco", "0.30", "0.32",
                     "Will Scheffler finish in the top 5 (including ties)?")])
    r = data.build_contracts("KXPGATOP5", [top5])[0]
    assert r["player_key"] == "uuid-sco" and r["mapping_confidence"] == "high"
    assert r["kind"] == "advance" and r["ladder_node"] == "Top 5" and r["ladder_eligible"] is True
    assert r["tournament"] == "U.S. Open · 26"                     # competition + season token (event …-26USO)
    assert r["raw_custom_strike"] == {"golf_competitor": "uuid-sco"}   # golf identity path


def test_golf_ladder_inversion_flagged():
    # Top 5 (deeper) bid 60 > Top 10 (broader) ask 55 → executable violation on "Top 5 ≤ Top 10".
    c = _golf_ladder(("0.80", "0.82"), ("0.50", "0.55"), ("0.60", "0.62"))
    row = next(r for _, r in c.iterrows() if r["chain"] == "Top 5 ≤ Top 10")
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5


def test_golf_ladder_clean_when_ordered():
    c = _golf_ladder(("0.80", "0.82"), ("0.50", "0.52"), ("0.30", "0.32"), win=("0.10", "0.12"))
    chains = {r["chain"]: r["status"] for _, r in c.iterrows()}
    assert chains["Top 10 ≤ Top 20"] == "CLEAN"
    assert chains["Top 5 ≤ Top 10"] == "CLEAN"
    assert chains["Win Tournament ≤ Top 5"] == "CLEAN"


def test_golf_categories_are_finish_position():
    c = _golf_ladder(("0.80", "0.82"), ("0.50", "0.55"), ("0.60", "0.62"))
    row = next(r for _, r in c.iterrows() if r["chain"] == "Top 5 ≤ Top 10")
    assert row["child_category"] == "Finish position"             # per-sport dispatch, not tennis/None
    assert row["parent_category"] == "Finish position"


def test_golf_competition_mismatch_does_not_pair():
    # Same golfer, but two rungs in DIFFERENT tournaments (different competition string) -> different
    # (player_key, tournament) groups -> no Top5-vs-Top20 comparison even though prices would cross.
    rows = (data.build_contracts("KXPGATOP20", [_golf_event("KXPGATOP20-26USO", [_golf_market("KXPGATOP20-26USO-SCO", "Scheffler", "u", "0.80", "0.82")], "U.S. Open")])
            + data.build_contracts("KXPGATOP5", [_golf_event("KXPGATOP5-26MEM", [_golf_market("KXPGATOP5-26MEM-SCO", "Scheffler", "u", "0.90", "0.92")], "The Memorial Tournament")]))
    checks = consistency.build_checks(pd.DataFrame(rows))
    assert not any("Top 5" in c and "Top 20" in c for c in checks["chain"])


# --- Soccer (6th sport): 3-way games + reach-stage ladder + participant typing ---------------
_SOCCER_FIX = Path(__file__).parent / "fixtures" / "soccer"


def _load_soccer(name):
    return json.loads((_SOCCER_FIX / name).read_text(encoding="utf-8"))


def _wcround(event_ticker, ticker, bid, ask, team="Brazil", uuid="u-bra"):
    return {"event_ticker": event_ticker, "title": "x",
            "product_metadata": {"competition": "2026 FIFA World Cup"},
            "markets": [{"ticker": ticker, "yes_sub_title": team,
                         "custom_strike": {"soccer_team": uuid},
                         "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
                         "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active", "title": "x"}]}


def test_soccer_registered_and_exact_only_ownership():
    assert {"tennis", "nba", "wnba", "golf", "soccer"} <= {c.sport_id for c in sports.all_sports()}
    # The owned tickers resolve to soccer: 3-way game, reach-stage, group-qualifier (Reach RO32), group-
    # winner (the "Win group" leaf), and the LIVE tournament outright KXMENWORLDCUP (a bare prefix never
    # shadows KXWCGAME/KXWCROUND/etc.).
    for tk in ("KXWCGAME", "KXWCROUND", "KXWCGROUPQUAL", "KXWCGROUPWIN", "KXMENWORLDCUP"):
        assert sports.sport_for_series(tk).sport_id == "soccer", tk
    # Field-shaped + not-live series must NOT be owned by soccer (resolve to unknown). KXWCGROUPWINNER
    # ("Group to Win") is a distinct contract; KXWC is the retired dormant guess; KXMWORLDCUP is a dead
    # lookalike with no open event (the live outright is KXMENWORLDCUP).
    for tk in ("KXWCSTAGE", "KXWCGROUPWINNER", "KXFIFAGAME", "KXFIFAADVANCE", "KXWCGOALLEADER",
               "KXWC", "KXMWORLDCUP"):
        assert sports.sport_for_series(tk).sport_id == "unknown", tk


def test_soccer_game_not_laddered_and_reach_stage_nodes():
    g = sports.SOCCER.classify("KXWCGAME", {"ticker": "KXWCGAME-26JUN11MEXRSA-MEX", "title": "x"})
    assert g.family == "game" and g.eligible_for_ladder_checks is False     # 3-way game: dutch-only
    # Full knockout ladder, broad → deep. Round of 32 is the KXWCGROUPQUAL "qualify from group" market.
    for series, tk, node in [
        ("KXWCGROUPQUAL", "KXWCGROUPQUAL-26L-PAN", "Reach Round of 32"),
        ("KXWCROUND", "KXWCROUND-26RO16-PAR", "Reach Round of 16"),
        ("KXWCROUND", "KXWCROUND-26QUAR-BRA", "Reach Quarterfinals"),
        ("KXWCROUND", "KXWCROUND-26SEMI-ARG", "Reach Semifinals"),
        ("KXWCROUND", "KXWCROUND-26FINAL-FRA", "Reach Finals"),
    ]:
        a = sports.SOCCER.classify(series, {"ticker": tk, "title": "x"})
        assert a.family == "advance" and a.ladder_node == node, tk


def test_soccer_winner_rung_live_outright():
    # The LIVE tournament outright (KXMENWORLDCUP-26) classifies as the deepest ladder rung "Win the World
    # Cup" (node == display label). The dead lookalike KXMWORLDCUP and the retired dormant guess KXWC are
    # NOT selected — a regression guard against re-introducing a ticker with no open event.
    win = sports.SOCCER.classify("KXMENWORLDCUP", {"ticker": "KXMENWORLDCUP-26-BRA", "title": "x"})
    assert win.family == "winner" and win.ladder_node == "Win the World Cup"
    assert sports.SOCCER.winner_label == "Win the World Cup"
    assert sports.sport_for_series("KXMWORLDCUP").sport_id == "unknown"
    assert sports.sport_for_series("KXWC").sport_id == "unknown"
    # The ladder spans all six rungs, deepest edge anchored on the winner node.
    assert sports.SOCCER.ladder.node_order[0] == "Reach Round of 32"
    assert sports.SOCCER.ladder.node_order[-1] == "Win the World Cup"
    assert ("Win the World Cup", "Reach Finals") in sports.SOCCER.ladder.adjacent_pairs


def test_soccer_group_winner_is_transitivity_excluded_leaf():
    # "Win group" (KXWCGROUPWIN) is a side-branch leaf: ⊆ "Reach Round of 32" only, and deliberately NOT in
    # node_order so the transitive bridge never linearises it against the incomparable deeper rungs.
    win = sports.SOCCER.classify("KXWCGROUPWIN", {"ticker": "KXWCGROUPWIN-26L-PAN", "title": "Group L Winner"})
    assert win.family == "group_winner" and win.ladder_node == "Win group"
    assert win.eligible_for_ladder_checks is True
    assert "Win group" not in sports.SOCCER.ladder.node_order
    assert ("Win group", "Reach Round of 32") in sports.SOCCER.ladder.adjacent_pairs
    assert "Win group" in sports.SOCCER.ladder.optional_children


def test_soccer_round_of_32_joins_full_ladder():
    # A team present at Reach RO32 (group qualifier) + Reach RO16 forms the bottom adjacent containment
    # pair in ONE (player_key, tournament) group — proving the new rung joins, not just classifies.
    rows = (data.build_contracts(
                "KXWCGROUPQUAL",
                [_wcround("KXWCGROUPQUAL-26L", "KXWCGROUPQUAL-26L-BRA", "0.88", "0.90")])
            + data.build_contracts(
                "KXWCROUND",
                [_wcround("KXWCROUND-26RO16", "KXWCROUND-26RO16-BRA", "0.50", "0.52")]))
    assert len({r["player_key"] for r in rows}) == 1                       # same team UUID
    assert len({r["tournament"] for r in rows}) == 1                       # same WC tournament group
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows()
               if c["chain"] == "Reach Round of 16 ≤ Reach Round of 32")
    assert row["status"] == "CLEAN"                                        # deeper (RO16 .51) ≤ broader (RO32 .89)


def _wc_group_rows(win_bid, win_ask, qual_bid, qual_ask, *, team="Brazil", uuid="u-bra"):
    """One team's Win-group (KXWCGROUPWIN) + group-qualifier (KXWCGROUPQUAL = Reach RO32) contracts."""
    return (data.build_contracts("KXWCGROUPWIN",
                [_wcround("KXWCGROUPWIN-26L", "KXWCGROUPWIN-26L-BRA", win_bid, win_ask, team, uuid)])
            + data.build_contracts("KXWCGROUPQUAL",
                [_wcround("KXWCGROUPQUAL-26L", "KXWCGROUPQUAL-26L-BRA", qual_bid, qual_ask, team, uuid)]))


def test_soccer_win_group_leaf_contains_qualify():
    # "Win group" ⊆ "Reach Round of 32" (qualify). Ordered prices (deeper Win group ≤ broader qualify) → CLEAN.
    rows = _wc_group_rows("0.30", "0.32", "0.88", "0.90")
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win group ≤ Reach Round of 32")
    assert row["status"] == "CLEAN"
    # Win group priced ABOVE qualify (firm child bid > parent ask) → EXECUTABLE_VIOLATION.
    rows = _wc_group_rows("0.60", "0.62", "0.50", "0.52")
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win group ≤ Reach Round of 32")
    assert row["status"] == "EXECUTABLE_VIOLATION"


def test_soccer_win_group_never_transitively_linearised():
    # A team with Win group + Reach RO16 but NO qualifier rung between them: the transitive bridge must NOT
    # compare "Win group" to "Reach Round of 16" (they are incomparable — a group winner can lose in the R32).
    rows = (data.build_contracts("KXWCGROUPWIN",
                [_wcround("KXWCGROUPWIN-26L", "KXWCGROUPWIN-26L-BRA", "0.60", "0.62")])
            + data.build_contracts("KXWCROUND",
                [_wcround("KXWCROUND-26RO16", "KXWCROUND-26RO16-BRA", "0.40", "0.42")]))
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"] for _, c in checks.iterrows()}
    assert not any("Win group" in ch and "Round of 16" in ch for ch in chains)


def test_soccer_win_group_optional_leaf_no_missing_layer():
    # A team with only the qualifier rung (Win group NOT fetched) must NOT emit a MISSING_LAYER for the
    # optional "Win group" leaf — it is opportunistic, not a required rung.
    rows = data.build_contracts("KXWCGROUPQUAL",
                [_wcround("KXWCGROUPQUAL-26L", "KXWCGROUPQUAL-26L-BRA", "0.88", "0.90")])
    checks = consistency.build_checks(pd.DataFrame(rows))
    missing = [c for _, c in checks.iterrows()
               if c["status"] == "MISSING_LAYER" and "Win group" in (c["chain"] or "")]
    assert missing == []


def test_soccer_winner_outright_is_subpenny_display_only():
    # KXMENWORLDCUP prices in deci-cent (e.g. 0.1620 = 16.2¢) → flagged `subpenny`, so consistency drops it
    # from integer-cent ladder checks: the "Win the World Cup" rung is display-only until it is whole-cent.
    rows = data.build_contracts("KXMENWORLDCUP", [{
        "event_ticker": "KXMENWORLDCUP-26", "title": "2026 Men's World Cup Winner",
        "product_metadata": {"competition": "2026 FIFA World Cup"},
        "markets": [{"ticker": "KXMENWORLDCUP-26-FR", "yes_sub_title": "France",
                     "custom_strike": {"soccer_team": "u-fra"}, "price_level_structure": "deci_cent",
                     "yes_bid_dollars": "0.1610", "yes_ask_dollars": "0.1620", "last_price_dollars": "0.1620",
                     "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active", "title": "x"}]}])
    assert rows[0]["subpenny"] is True and rows[0]["ladder_node"] == "Win the World Cup"


def test_soccer_group_winner_only_expected_nodes_empty():
    # A player with ONLY a group-winner row has no linear reach ladder → expected_nodes returns [] (the
    # gate stays kind in advance/winner; group_winner never produces an all-missing linear ladder).
    rows = data.build_contracts("KXWCGROUPWIN",
                [_wcround("KXWCGROUPWIN-26L", "KXWCGROUPWIN-26L-BRA", "0.30", "0.32")])
    assert consistency.expected_nodes(rows) == []


def test_soccer_tie_is_non_participant_with_per_event_key():
    rows = data.build_contracts("KXWCGAME", [_load_soccer("KXWCGAME-26JUN11MEXRSA.json")])
    by = {r["player"]: r for r in rows}
    assert by["Mexico"]["is_participant"] is True and by["Mexico"]["participant_type"] == "participant"
    assert by["Mexico"]["player_key"] == "8caf91d0-aafc-4d95-8788-72947e76e667"
    tie = by["Tie"]
    assert tie["is_participant"] is False and tie["participant_type"] == "tie"
    assert tie["player_key"] == "tie::KXWCGAME-26JUN11MEXRSA"               # per-event synthetic key
    assert all(r["mutually_exclusive"] is True for r in rows)              # MECE flag stamped from the event
    assert {r["tournament"] for r in rows} == {"2026 FIFA World Cup · 26"}  # WC key + season token
    assert all(r["kind"] == "game" for r in rows)


def test_soccer_reach_stage_ladder_violation():
    # Same team at Reach R16 (broad) + Reach QF (deep); QF bid 85 > R16 ask 82 → executable violation.
    rows = (data.build_contracts("KXWCROUND", [_wcround("KXWCROUND-26RO16", "KXWCROUND-26RO16-BRA", "0.80", "0.82")])
            + data.build_contracts("KXWCROUND", [_wcround("KXWCROUND-26QUAR", "KXWCROUND-26QUAR-BRA", "0.85", "0.87")]))
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Reach Quarterfinals ≤ Reach Round of 16")
    assert row["status"] == "EXECUTABLE_VIOLATION"
    assert row["child_category"] == "Stage advancement"


def test_soccer_groupqual_fixture_is_round_of_32():
    # Real captured KXWCGROUPQUAL event parses to the Reach Round of 32 rung. Live competition metadata is
    # "FIFA World Cup" (not the "2026 FIFA World Cup" of older fixtures) → tournament key "FIFA World Cup · 26".
    rows = data.build_contracts("KXWCGROUPQUAL", [_load_soccer("KXWCGROUPQUAL-26L.json")])
    assert {r["player"] for r in rows} == {"Panama", "Ghana"}
    assert all(r["kind"] == "advance" for r in rows)
    assert all(r["contract"] == "Reach Round of 32" for r in rows)         # ladder node = contract label
    assert {r["tournament"] for r in rows} == {"FIFA World Cup · 26"}
    assert all(r["is_participant"] is True for r in rows)                  # real teams, not a Tie leg


def test_soccer_game_fixture_shape():
    ev = _load_soccer("KXWCGAME-26JUN11MEXRSA.json")
    assert ev["mutually_exclusive"] is True and len(ev["markets"]) == 3
    assert {m["yes_sub_title"] for m in ev["markets"]} == {"Mexico", "South Africa", "Tie"}
    tie = next(m for m in ev["markets"] if m["yes_sub_title"] == "Tie")
    assert tie["custom_strike"]["soccer_team"] == sports.SOCCER_TIE_UUID
    assert "does not include extra time or penalties" in tie["rules_primary"]   # draw-excluded phrase


def test_participant_default_invariant_for_existing_sports():
    # Non-soccer rows are all real participants (additive fields don't regress tennis/NBA/WNBA/golf).
    r = data.build_contracts("KXNBA", [_nba_event("KXNBA-26", [
        _nba_market("KXNBA-26-BOS", "Boston", "uuid-bos", "0.40", "0.42",
                    "Will the Boston win the 2026 Pro Basketball Finals?")])])[0]
    assert r["is_participant"] is True and r["participant_type"] == "participant"


def test_golf_derived_indicators_in_contention_ratios_and_make_cut():
    out = sports.GOLF.derived_indicators({"Top 20": 18.0, "Top 10": 9.0, "Top 5": 4.0, "Win Tournament": 1.0})
    labels = [i["label"] for i in out]
    assert "In contention (Top 20)" in labels                       # broadest rung = in-contention
    floor = next(i for i in out if i["label"] == "Make the cut")     # golf-specific FLOOR still appended
    assert floor["comparator"] == "≥" and floor["value_pct"] == 18.0
    pw = next(i for i in out if i["label"] == "P(Win Tournament | Top 5)")   # conditional ratio 1/4*100
    assert pw["value_pct"] == 25.0
    # make-cut floor absent when Top 20 isn't listed (other rungs still yield conditional ratios)
    assert all(i["label"] != "Make the cut" for i in sports.GOLF.derived_indicators({"Top 10": 9.0, "Top 5": 4.0}))


def test_derived_indicators_generalized_to_all_laddered_sports_and_guarded():
    # PR G — every laddered sport gets the broad-rung "in contention" indicator (not just golf).
    assert any(i["label"] == "In contention (Reach Semifinal)"
               for i in sports.TENNIS.derived_indicators({"Reach Semifinal": 60.0}))
    assert any(i["label"] == "In contention (Reach Playoffs)"
               for i in sports.NBA.derived_indicators({"Reach Playoffs": 80.0}))
    assert sports.TENNIS.derived_indicators({}) == []                # no rung price -> nothing
    # conditional ratio SUPPRESSED on an inconsistent ladder (deeper priced above broader)...
    out = sports.TENNIS.derived_indicators({"Reach Semifinal": 30.0, "Reach Final": 10.0, "Win Tournament": 15.0})
    assert all(i["label"] != "P(Win Tournament | Reach Final)" for i in out)
    # ...but a consistent neighbour still emits: P(Reach Final | Reach Semifinal) = 10/30*100
    pf = next(i for i in out if i["label"] == "P(Reach Final | Reach Semifinal)")
    assert round(pf["value_pct"], 1) == 33.3


# --- ITF tennis (lower-tour head-to-head matches; exact-owned) -----------------------
_ITF_FIX = Path(__file__).parent / "fixtures" / "itf"


def test_itf_owned_classified_match_and_division():
    # ITF lives outside KXATP*/KXWTA* prefixes, so tennis must own it via exact_series.
    assert sports.sport_for_series("KXITFWMATCH").sport_id == "tennis"
    assert sports.sport_for_series("KXITFMATCH").sport_id == "tennis"
    # Both classify as the 2-way head-to-head "match" family.
    assert sports.TENNIS.classify("KXITFWMATCH", {"title": "x"}).family == "match"
    assert sports.TENNIS.classify("KXITFMATCH", {"title": "x"}).family == "match"
    # Division fix: ITF women -> WTA, ITF men -> ATP (women would otherwise mislabel as ATP).
    assert sports.TENNIS.division_of("KXITFWMATCH") == "WTA"
    assert sports.TENNIS.division_of("KXITFMATCH") == "ATP"
    # Fetched in the default scan (exact-owned series appended to default_series).
    assert "KXITFWMATCH" in sports.TENNIS.default_series and "KXITFMATCH" in sports.TENNIS.default_series


def test_itf_live_fixtures_flow_through_engine():
    """Real captured ITF events (live probe 2026-06-09): each is a 2-market head-to-head with
    custom_strike.tennis_competitor identity, and the 2-way dutch-book detector consumes them."""
    import dutchbook
    files = sorted(_ITF_FIX.glob("KXITF*MATCH-*.json"))
    assert len(files) >= 2, "expected a men's + a women's ITF fixture as D-probe evidence"
    for fp in files:
        ev = json.loads(fp.read_text(encoding="utf-8"))
        series = ev["series_ticker"]
        rows = data.build_contracts(series, [ev])
        assert len(rows) == 2, fp.name                                  # head-to-head: 2 markets
        assert all(r["kind"] == "match" for r in rows), fp.name
        assert len({r["player_key"] for r in rows}) == 2, fp.name       # distinct competitor UUIDs
        assert all(r["mapping_confidence"] == "high" for r in rows), fp.name  # tennis_competitor present
        # The 2-way detector consumes them NaN-safely (a book may or may not fire on live prices).
        out = dutchbook.find_dutch_books([{**r} for r in pd.DataFrame(rows).to_dict("records")])
        for f in out:
            assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK
