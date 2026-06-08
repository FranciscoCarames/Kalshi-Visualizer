"""Unit tests for NFL (9th sport) — registration, the strict family allow-list (NFL-owned `other` vs the
UNKNOWN sport), the core futures ladder (Reach Playoffs ⊇ Win Conference ⊇ Win Super Bowl), identity,
season-scoped grouping incl. same-team cross-series laddering, fetch scope, the Super Bowl one-winner
FIELD overround, and the gated KXNFLGAME full-game dutch book (game_mece_by_shape=False +
dutchbook._proves_fixed_sum on the real $0.50-tie settlement text). Pure — crafted fixtures, no network.

Grounding (live probe 2026-06-08): identity custom_strike.football_team; KXSB (winner, 32 ME markets),
KXNFLPLAYOFF (advance, mutually_exclusive=False), KXNFLAFCCHAMP/KXNFLNFCCHAMP (advance), KXNFLGAME (2-way
game; rules_secondary "If the game ends in a tie, the market will resolve to $0.50 for each team").
"""
from __future__ import annotations

import pandas as pd

import consistency
import data
import dutchbook
import sports

# Real KXNFLGAME settlement wording (the $0.50-tie + 48h/fair-market clauses), shared by both legs.
TIE_HALF_RULES = (
    "The following market refers to the team who wins the professional football game. If the game ends "
    "in a tie, the market will resolve to $0.50 for each team. If the game is postponed but begins within "
    "48 hours from its originally scheduled start time, the market will remain open and resolve based on "
    "the official final result. If the game is not started within 48 hours, the market will resolve to a "
    "fair market price."
)


# ============================================================================================
# Fixtures
# ============================================================================================
def _mkt(ticker, team, uuid, bid, ask, title="x", *, status="active",
         rules_primary="", rules_secondary="", mutually_exclusive=False):
    return {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"football_team": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": status, "title": title, "rules_primary": rules_primary,
            "rules_secondary": rules_secondary, "mutually_exclusive": mutually_exclusive}


def _event(event_ticker, markets, competition="Pro Football"):
    meta = {"competition": competition} if competition is not None else {}
    return {"event_ticker": event_ticker, "title": "NFL", "product_metadata": meta, "markets": markets}


# ============================================================================================
# Registration + resolution
# ============================================================================================
def test_nfl_registered():
    ids = {c.sport_id for c in sports.all_sports()}
    assert {"tennis", "nba", "wnba", "golf", "soccer", "mlb", "nhl", "motorsport", "nfl"} <= ids
    nfl = sports.get_sport("nfl")
    assert nfl.label == "NFL" and nfl.winner_label == "Win the Super Bowl"
    assert nfl.game_mece_by_shape is False          # NFL games can tie → gated


def test_nfl_family_allowlist():
    cfg = sports.get_sport("nfl")
    assert cfg.family_of("KXSB") == "winner"
    assert cfg.family_of("KXNFLPLAYOFF") == "advance"
    assert cfg.family_of("KXNFLAFCCHAMP") == "advance" and cfg.family_of("KXNFLNFCCHAMP") == "advance"
    assert cfg.family_of("KXNFLGAME") == "game"
    # Strict exact-equality: every real KXNFL* prop/award/division/derivative lookalike → "other".
    for excluded in ("KXNFLPLAYOFFS", "KXNFLAFCEAST", "KXNFLAFCWEST", "KXNFLNFCNORTH", "KXNFLMVP",
                     "KXNFLSPREAD", "KXNFLTOTAL", "KXNFL1HWINNER", "KXNFL1QWINNER", "KXNFLDRAFTPICK",
                     "KXNFLEXACTWINSKC", "KXNFLWINS-KC", "KXNFLSBMVP", "KXNFLCOACH"):
        assert cfg.family_of(excluded) == "other", excluded


def test_nfl_owned_other_vs_unknown_sport():
    # (a) NFL-OWNED but family `other`: a KXNFL* lookalike resolves to NFL by prefix, then `other`.
    for t in ("KXNFLPLAYOFFS", "KXNFLAFCEAST", "KXNFLMVP", "KXNFLSPREAD"):
        assert sports.sport_for_series(t).sport_id == "nfl", t
        assert sports.get_sport("nfl").family_of(t) == "other", t
    # KXSB is NFL-owned via winner_tickers (not the KXNFL prefix).
    assert sports.sport_for_series("KXSB").sport_id == "nfl"
    # (b) UNKNOWN sport: non-KXNFL* football series are NOT NFL at all (no silent default).
    for t in ("KXAFC", "KXNFC", "KXTEAMSINSB", "KXNFCAFCSB"):
        assert sports.sport_for_series(t).sport_id == "unknown", t


def test_nfl_excluded_ticker_is_other_through_build_contracts():
    evt = _event("KXNFLMVP-26", [_mkt("KXNFLMVP-26-X", "Some QB", "u-x", "0.10", "0.12")])
    rows = data.build_contracts("KXNFLMVP", [evt])
    assert rows and all(r["kind"] == "other" and r["ladder_eligible"] is False for r in rows)
    assert consistency.build_checks(pd.DataFrame(rows)).empty
    assert dutchbook.find_dutch_books(rows) == []


# ============================================================================================
# Contract labels
# ============================================================================================
def _label(cfg, series, market):
    mc = cfg.classify(series, market)
    return data._contract_label(mc.family, market, "", mc.stage, cfg, mc.ladder_node)


def test_nfl_contract_labels():
    nfl = sports.get_sport("nfl")
    assert _label(nfl, "KXSB", {"ticker": "KXSB-27-KC"}) == "Win the Super Bowl"
    assert _label(nfl, "KXNFLAFCCHAMP", {"ticker": "KXNFLAFCCHAMP-27-KC"}) == "Win Conference"
    assert _label(nfl, "KXNFLNFCCHAMP", {"ticker": "KXNFLNFCCHAMP-27-SF"}) == "Win Conference"
    assert _label(nfl, "KXNFLPLAYOFF", {"ticker": "KXNFLPLAYOFF-27-KC"}) == "Reach Playoffs"


# ============================================================================================
# Categories + ladder end-to-end
# ============================================================================================
def _ladder_rows(sb_bid, sb_ask, conf_bid, conf_ask, season="27"):
    sb = _event(f"KXSB-{season}", [_mkt(f"KXSB-{season}-KC", "Kansas City", "u-kc", sb_bid, sb_ask,
                                        "Will Kansas City win the 2027 Super Bowl?")])
    conf = _event(f"KXNFLAFCCHAMP-{season}", [_mkt(f"KXNFLAFCCHAMP-{season}-KC", "Kansas City", "u-kc",
                                                   conf_bid, conf_ask, "Win the AFC Championship")])
    return data.build_contracts("KXSB", [sb]) + data.build_contracts("KXNFLAFCCHAMP", [conf])


def test_nfl_categories_and_ladder_violation():
    # Win Super Bowl (deeper) priced ABOVE Win Conference (broader) → executable violation.
    rows = _ladder_rows("0.60", "0.62", "0.50", "0.55")
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"]: c for _, c in checks.iterrows()}
    assert "Win Super Bowl ≤ Win Conference" in chains
    row = chains["Win Super Bowl ≤ Win Conference"]
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5
    assert row["child_category"] == "Super Bowl"
    assert row["parent_category"] == "Advancement (reach a stage)"


def test_nfl_ladder_clean_when_ordered():
    rows = _ladder_rows("0.40", "0.42", "0.55", "0.57")
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Super Bowl ≤ Win Conference")
    assert row["status"] == "CLEAN"


def test_nfl_same_team_ladders_across_series_by_uuid_and_season():
    # One team's Reach Playoffs / Win Conference / Win Super Bowl rows (3 distinct series) share a
    # (player_key, tournament) group → they ladder together; correctly priced → CLEAN, no false violation.
    sb = data.build_contracts("KXSB", [_event("KXSB-27", [
        _mkt("KXSB-27-KC", "Kansas City", "u-kc", "0.30", "0.32", "Win the 2027 Super Bowl")])])
    conf = data.build_contracts("KXNFLAFCCHAMP", [_event("KXNFLAFCCHAMP-27", [
        _mkt("KXNFLAFCCHAMP-27-KC", "Kansas City", "u-kc", "0.45", "0.47", "Win the AFC Championship")])])
    play = data.build_contracts("KXNFLPLAYOFF", [_event("KXNFLPLAYOFF-27", [
        _mkt("KXNFLPLAYOFF-27-KC", "Kansas City", "u-kc", "0.70", "0.72", "Reach the playoffs")])])
    rows = sb + conf + play
    assert {r["ladder_node"] for r in rows} == {"Win Super Bowl", "Win Conference", "Reach Playoffs"}
    assert {r["tournament"] for r in rows} == {"Pro Football · 27"}     # one group by UUID + season
    checks = consistency.build_checks(pd.DataFrame(rows))
    assert not (checks["status"] == "EXECUTABLE_VIOLATION").any()       # ordered prices → clean


def test_nfl_afc_and_nfc_both_win_conference_without_collapsing():
    afc = data.build_contracts("KXNFLAFCCHAMP", [_event("KXNFLAFCCHAMP-27", [
        _mkt("KXNFLAFCCHAMP-27-KC", "Kansas City", "u-kc", "0.30", "0.32", "Win the AFC Championship")])])
    nfc = data.build_contracts("KXNFLNFCCHAMP", [_event("KXNFLNFCCHAMP-27", [
        _mkt("KXNFLNFCCHAMP-27-SF", "San Francisco", "u-sf", "0.28", "0.30", "Win the NFC Championship")])])
    assert {r["player_key"] for r in afc + nfc} == {"u-kc", "u-sf"}
    assert all(r["ladder_node"] == "Win Conference" for r in afc + nfc)


# ============================================================================================
# Identity + season-scoped grouping
# ============================================================================================
def test_nfl_identity_uuid_high_else_name_low():
    r = data.build_contracts("KXSB", [_event("KXSB-27", [
        _mkt("KXSB-27-KC", "Kansas City", "u-kc", "0.40", "0.42")])])[0]
    assert r["player_key"] == "u-kc" and r["mapping_confidence"] == "high"
    m = _mkt("KXSB-27-KC", "Kansas City", "u-kc", "0.40", "0.42")
    m["custom_strike"] = {}
    r2 = data.build_contracts("KXSB", [_event("KXSB-27", [m])])[0]
    assert r2["mapping_confidence"] == "low"


def test_nfl_season_token_and_grouping():
    assert data._season_token("KXSB", "KXSB-27") == "27"
    assert data._season_token("KXNFLPLAYOFF", "KXNFLPLAYOFF-27") == "27"
    g27 = data.tournament_of("Pro Football", "KXSB", "KXSB-27", "Super Bowl")[0]
    g28 = data.tournament_of("Pro Football", "KXSB", "KXSB-28", "Super Bowl")[0]
    assert g27 == "Pro Football · 27" and g28 == "Pro Football · 28" and g27 != g28


def test_nfl_grouping_fallback_when_competition_missing():
    r = data.build_contracts("KXSB", [_event("KXSB-27", [
        _mkt("KXSB-27-KC", "Kansas City", "u-kc", "0.40", "0.42")], competition=None)])[0]
    assert r["tournament"].startswith("Unknown")    # never blank → never silently mis-pairs


# ============================================================================================
# Fetch scope
# ============================================================================================
def test_nfl_fetch_scope_includes_ladder_game_excludes_props():
    nfl = sports.get_sport("nfl")
    fams = data.non_other_families(nfl)
    assert "Other" not in fams
    all_series = ["KXSB", "KXNFLPLAYOFF", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXNFLGAME",
                  "KXNFLPLAYOFFS", "KXNFLMVP", "KXNFLSPREAD", "KXNFLAFCEAST"]
    fetched = set(data.series_for_families(all_series, fams))
    assert {"KXSB", "KXNFLPLAYOFF", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXNFLGAME"} <= fetched
    assert fetched.isdisjoint({"KXNFLPLAYOFFS", "KXNFLMVP", "KXNFLSPREAD", "KXNFLAFCEAST"})


# ============================================================================================
# Super Bowl one-winner FIELD overround (KXSB winner + default field_families={"winner"})
# ============================================================================================
def _sb_winner(team, uuid, yes_bid_c, no_ask_c):
    return {"series": "KXSB", "event_ticker": "KXSB-27", "kind": "winner", "mutually_exclusive": True,
            "player": team, "player_key": uuid, "contract": f"Win the Super Bowl ({team})",
            "tournament": "Pro Football · 27", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_bid_c + 2,
            "no_ask_c": no_ask_c, "yes_bid_size": 100, "yes_ask_size": 100,
            "quote_quality": "Tight", "status": "active", "market_ticker": f"KXSB-27-{uuid}",
            "kalshi_url": "https://kalshi.com/markets/kxsb", "event_title": "Super Bowl LXI"}


def test_nfl_super_bowl_field_overround_fires_when_mispriced():
    # 3 mutually-exclusive winner legs with Σ no_ask (180) < (k-1)*100 (200) → overround dutch book.
    rows = [_sb_winner("Kansas City", "u-kc", 40, 60),
            _sb_winner("San Francisco", "u-sf", 40, 60),
            _sb_winner("Baltimore", "u-bal", 40, 60)]
    out = dutchbook.find_dutch_books(rows)
    assert len(out) == 1
    assert out[0]["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and out[0]["direction"] == "overround"


def test_nfl_conference_advance_field_gets_no_overround():
    # AFC champ rows are classified `advance` (not in field_families) → never a field dutch book.
    rows = [{**_sb_winner("Kansas City", "u-kc", 40, 60), "series": "KXNFLAFCCHAMP",
             "event_ticker": "KXNFLAFCCHAMP-27", "kind": "advance"},
            {**_sb_winner("Buffalo", "u-buf", 40, 60), "series": "KXNFLAFCCHAMP",
             "event_ticker": "KXNFLAFCCHAMP-27", "kind": "advance"},
            {**_sb_winner("Cincinnati", "u-cin", 40, 60), "series": "KXNFLAFCCHAMP",
             "event_ticker": "KXNFLAFCCHAMP-27", "kind": "advance"}]
    assert dutchbook.find_dutch_books(rows) == []


# ============================================================================================
# Gated KXNFLGAME full-game dutch book (the central safety invariant)
# ============================================================================================
def _game(team, uuid, *, yes_bid_c, yes_ask_c, rules_secondary=TIE_HALF_RULES, no_ask_c=None):
    return {"series": "KXNFLGAME", "event_ticker": "KXNFLGAME-26SEP14DENKC", "kind": "game",
            "player": team, "player_key": uuid, "contract": f"Beat opponent ({team})",
            "tournament": "Pro Football · 26", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c,
            "no_ask_c": no_ask_c, "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight",
            "status": "active", "market_ticker": f"KXNFLGAME-{team[:3].upper()}",
            "kalshi_url": "https://kalshi.com/markets/nfl", "event_title": "DEN vs KC",
            "rules_primary": f"If {team} wins the game, the market resolves to Yes.",
            "rules_secondary": rules_secondary}


def test_nfl_game_underround_fires_with_proof_and_caveat():
    out = dutchbook.find_dutch_books([_game("Kansas City", "u-kc", yes_bid_c=43, yes_ask_c=45),
                                      _game("Denver", "u-den", yes_bid_c=46, yes_ask_c=48)])
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and f["direction"] == "underround"
    assert f["series"] == "KXNFLGAME"
    # Proof evidence is wired into the finding (truthful "why it's safe") + the per-game caveat present.
    assert f["settlement_basis"] == "tie_half"
    assert "$0.50" in f["settlement_caveat"] and f["settlement_caveat"]


def test_nfl_game_overround_fires_with_proof():
    out = dutchbook.find_dutch_books([_game("Kansas City", "u-kc", yes_bid_c=55, yes_ask_c=58),
                                      _game("Denver", "u-den", yes_bid_c=57, yes_ask_c=60)])
    assert len(out) == 1 and out[0]["direction"] == "overround"
    assert out[0]["settlement_basis"] == "tie_half"


def test_nfl_game_no_tie_winner_basis_via_overtime_wording():
    rules = "This playoff game is played in overtime until a winner is determined."
    out = dutchbook.find_dutch_books([_game("Kansas City", "u-kc", yes_bid_c=43, yes_ask_c=45, rules_secondary=rules),
                                      _game("Denver", "u-den", yes_bid_c=46, yes_ask_c=48, rules_secondary=rules)])
    assert len(out) == 1 and out[0]["settlement_basis"] == "no_tie_winner"


def test_nfl_game_REJECTED_when_fixed_sum_not_proven():
    # The SAME mispriced book, but with settlement text that does NOT prove fixed-sum → NO finding
    # (the core safety assertion: never a false dutch book on a tie-capable game).
    plain = "The team that wins the game resolves to Yes."
    diag: dict = {}
    out = dutchbook.find_dutch_books(
        [_game("Kansas City", "u-kc", yes_bid_c=43, yes_ask_c=45, rules_secondary=plain),
         _game("Denver", "u-den", yes_bid_c=46, yes_ask_c=48, rules_secondary=plain)], diag)
    assert out == []
    assert any("fixed-sum" in r["reason"] for r in diag.get("rejected", []))


def test_nfl_game_no_tie_not_inferred_from_bare_winner_or_me():
    # "winner"/"final result"/mutually_exclusive must NOT prove no_tie_winner (tie still pays $0.50).
    bare = "The market refers to the winner; resolves on the official final result. One winner."
    assert dutchbook._proves_fixed_sum(
        [{"rules_primary": "", "rules_secondary": bare}, {"rules_primary": "", "rules_secondary": bare}]
    ).proved is False


def test_nfl_game_rejected_when_legs_disagree_on_basis():
    # One leg proves tie_half, the other has no proof → fails closed (no shared basis).
    out = dutchbook.find_dutch_books(
        [_game("Kansas City", "u-kc", yes_bid_c=43, yes_ask_c=45, rules_secondary=TIE_HALF_RULES),
         _game("Denver", "u-den", yes_bid_c=46, yes_ask_c=48, rules_secondary="plain text")])
    assert out == []


# ============================================================================================
# Cross-sport regression: the gate is a NO-OP for draw-free (game_mece_by_shape=True) sports
# ============================================================================================
def test_draw_free_game_still_books_without_proof_gate():
    # An NHL game (game_mece_by_shape=True) has NO rules text yet still dutch-books — proving the new
    # gate only constrains tie-capable sports and leaves _detect_pair byte-identical elsewhere.
    def _nhl_game(team, uuid, yes_bid_c, yes_ask_c):
        return {"series": "KXNHLGAME", "event_ticker": "KXNHLGAME-26JUN05BOSTOR", "kind": "game",
                "player": team, "player_key": uuid, "contract": f"Beat opponent ({team})",
                "tournament": "Pro Hockey · 26", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c,
                "no_ask_c": None, "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight",
                "status": "active", "market_ticker": f"KXNHLGAME-{team[:3].upper()}",
                "kalshi_url": "https://kalshi.com/markets/nhl", "event_title": "BOS vs TOR"}
    out = dutchbook.find_dutch_books([_nhl_game("Bruins", "u-bos", 43, 45),
                                      _nhl_game("Leafs", "u-tor", 46, 48)])
    assert len(out) == 1 and out[0]["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK
    assert "settlement_basis" not in out[0]          # no NFL-style proof stamp on draw-free sports
