"""Unit tests for NHL (8th sport) — registration, classification + false-positive guards, sport-aware
labels (consuming the shipped winner_label / ladder-node advance fix), the KXNHLSERIES round parser,
the futures ladder, identity, season-scoped grouping, fetch scope, and the playoff-series / per-game
dutch books (incl. the new same-series guard). Pure — crafted fixtures, no network.
"""
from __future__ import annotations

import pandas as pd

import consistency
import data
import dutchbook
import sports


# ============================================================================================
# Fixtures
# ============================================================================================
def _mkt(ticker, team, uuid, bid, ask, title="x", *, status="active", rules_primary=""):
    return {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"hockey_team": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": status, "title": title, "rules_primary": rules_primary}


def _event(event_ticker, markets, competition="Pro Hockey"):
    meta = {"competition": competition} if competition is not None else {}
    return {"event_ticker": event_ticker, "title": "NHL", "product_metadata": meta, "markets": markets}


# ============================================================================================
# Registration + resolution
# ============================================================================================
def test_nhl_registered():
    ids = {c.sport_id for c in sports.all_sports()}
    assert {"tennis", "nba", "wnba", "golf", "soccer", "mlb", "nhl"} <= ids
    assert sports.get_sport("nhl").label == "NHL"
    assert sports.get_sport("nhl").winner_label == "Win the Stanley Cup"


def test_nhl_family_allowlist_and_guards():
    cfg = sports.get_sport("nhl")
    assert cfg.family_of("KXNHL") == "winner"
    assert cfg.family_of("KXNHLEAST") == "advance" and cfg.family_of("KXNHLWEST") == "advance"
    assert cfg.family_of("KXNHLPLAYOFF") == "advance"
    assert cfg.family_of("KXNHLSERIES") == "match"
    assert cfg.family_of("KXNHLGAME") == "game"
    # Exact-equality ownership: lookalike props/derivatives are NOT laddered/two-way.
    for excluded in ("KXNHLSERIESGAMES", "KXNHLSERIESSCORE", "KXNHLSERIESTOTALGOALS",
                     "KXNHLFINALSEXACT", "KXNHL30COMEBACK"):
        assert cfg.family_of(excluded) == "other", excluded


def test_nhl_series_resolve_to_nhl_but_lookalikes_classify_other():
    for t in ("KXNHL", "KXNHLGAME", "KXNHLSERIES", "KXNHLSERIESGAMES"):
        assert sports.sport_for_series(t).sport_id == "nhl", t
    # sport resolves to NHL by prefix, yet the family stays "other" (scope is the allow-list).
    assert sports.get_sport("nhl").family_of("KXNHLSERIESGAMES") == "other"
    # A non-NHL hockey-ish ticker that doesn't match the prefix stays UNKNOWN (no silent default).
    assert sports.sport_for_series("KXHOCKEY1").sport_id == "unknown"


def test_nhl_excluded_ticker_is_other_through_build_contracts():
    evt = _event("KXNHLFINALSEXACT-26", [_mkt("KXNHLFINALSEXACT-26-X", "Exact 4-2", "u-x", "0.10", "0.12")])
    rows = data.build_contracts("KXNHLFINALSEXACT", [evt])
    assert rows and all(r["kind"] == "other" and r["ladder_eligible"] is False for r in rows)
    assert consistency.build_checks(pd.DataFrame(rows)).empty
    assert dutchbook.find_dutch_books(rows) == []


# ============================================================================================
# Contract labels — consume the shipped winner_label + ladder-node advance fix
# ============================================================================================
def _label(cfg, series, market):
    mc = cfg.classify(series, market)
    return data._contract_label(mc.family, market, "", mc.stage, cfg, mc.ladder_node)


def test_nhl_contract_labels():
    nhl = sports.get_sport("nhl")
    assert _label(nhl, "KXNHL", {"ticker": "KXNHL-26-BOS"}) == "Win the Stanley Cup"
    assert _label(nhl, "KXNHLEAST", {"ticker": "KXNHLEAST-26-BOS"}) == "Win Conference"
    assert _label(nhl, "KXNHLWEST", {"ticker": "KXNHLWEST-26-VGK"}) == "Win Conference"
    assert _label(nhl, "KXNHLPLAYOFF", {"ticker": "KXNHLPLAYOFF-26-BOS"}) == "Reach Playoffs"


# ============================================================================================
# KXNHLSERIES round parser
# ============================================================================================
def test_nhl_series_rounds_never_map_to_championship():
    nhl = sports.get_sport("nhl")
    # Real Step-0 wording: "1st/2nd Round" must classify as a round stage with NO ladder node.
    mc2 = nhl.classify("KXNHLSERIES", {"ticker": "KXNHLSERIES-26MTLBUFR2",
                                       "title": "Will Montreal win their 2026 2nd Round series?",
                                       "rules_primary": "… 2nd Round series in the 2026 NHL playoffs"})
    assert mc2.stage == "Second Round" and mc2.ladder_node is None
    mc1 = nhl.classify("KXNHLSERIES", {"ticker": "KXNHLSERIES-26BOSTORR1",
                                       "title": "Will Boston win their 1st Round series?",
                                       "rules_primary": "1st Round series"})
    assert mc1.stage == "First Round" and mc1.ladder_node is None


def test_nhl_best_effort_finals_patterns_map_when_present():
    nhl = sports.get_sport("nhl")
    scf = nhl.classify("KXNHLSERIES", {"ticker": "KXNHLSERIES-26X", "title": "Stanley Cup Final series"})
    assert scf.stage == "Stanley Cup Final" and scf.ladder_node == "Win Championship"
    cf = nhl.classify("KXNHLSERIES", {"ticker": "KXNHLSERIES-26Y", "title": "Conference Finals series"})
    assert cf.stage == "Conference Finals" and cf.ladder_node == "Win Conference"


# ============================================================================================
# Categories + ladder end-to-end
# ============================================================================================
def _ladder_rows(champ_bid, champ_ask, conf_bid, conf_ask):
    champ = _event("KXNHL-26", [_mkt("KXNHL-26-BOS", "Bruins", "u-bos", champ_bid, champ_ask,
                                     "Will the Bruins win the 2026 Stanley Cup?")])
    conf = _event("KXNHLEAST-26", [_mkt("KXNHLEAST-26-BOS", "Bruins", "u-bos", conf_bid, conf_ask,
                                        "Will the Bruins win the Eastern Conference?")])
    return data.build_contracts("KXNHL", [champ]) + data.build_contracts("KXNHLEAST", [conf])


def test_nhl_categories_and_ladder_violation():
    # Win Championship (deeper) priced ABOVE Win Conference (broader) → executable violation.
    rows = _ladder_rows("0.60", "0.62", "0.50", "0.55")
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"]: c for _, c in checks.iterrows()}
    assert "Win Championship ≤ Win Conference" in chains
    row = chains["Win Championship ≤ Win Conference"]
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5
    assert row["child_category"] == "Championship"                  # NHL winner label
    assert row["parent_category"] == "Advancement (reach a stage)"  # NHL advance label


def test_nhl_ladder_clean_when_ordered():
    rows = _ladder_rows("0.40", "0.42", "0.55", "0.57")
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win Championship ≤ Win Conference")
    assert row["status"] == "CLEAN"


def test_nhl_east_and_west_both_win_conference_without_collapsing():
    # Two different teams, one in each conference, both map to "Win Conference" but stay distinct nodes.
    east = data.build_contracts("KXNHLEAST", [_event("KXNHLEAST-26", [
        _mkt("KXNHLEAST-26-BOS", "Bruins", "u-bos", "0.30", "0.32", "Win the Eastern Conference")])])
    west = data.build_contracts("KXNHLWEST", [_event("KXNHLWEST-26", [
        _mkt("KXNHLWEST-26-VGK", "Golden Knights", "u-vgk", "0.28", "0.30", "Win the Western Conference")])])
    assert {r["player_key"] for r in east + west} == {"u-bos", "u-vgk"}
    assert all(r["ladder_node"] == "Win Conference" for r in east + west)


# ============================================================================================
# Identity + season-scoped grouping
# ============================================================================================
def test_nhl_identity_uuid_high_else_name_low():
    r = data.build_contracts("KXNHL", [_event("KXNHL-26", [
        _mkt("KXNHL-26-BOS", "Bruins", "u-bos", "0.40", "0.42")])])[0]
    assert r["player_key"] == "u-bos" and r["mapping_confidence"] == "high"
    m = _mkt("KXNHL-26-BOS", "Bruins", "u-bos", "0.40", "0.42")
    m["custom_strike"] = {}
    r2 = data.build_contracts("KXNHL", [_event("KXNHL-26", [m])])[0]
    assert r2["mapping_confidence"] == "low"


def test_season_token_parsing():
    assert data._season_token("KXNHL", "KXNHL-26") == "26"
    assert data._season_token("KXNHLSERIES", "KXNHLSERIES-26MTLBUFR2") == "26"
    assert data._season_token("KXNHL", "kxnhl-26") == "26"          # case-insensitive
    assert data._season_token("KXNHL", "KXNBA-26") == ""            # prefix mismatch
    assert data._season_token("KXNHL", "KXNHL") == ""               # no digits


def test_nhl_grouping_is_season_scoped():
    g26 = data.tournament_of("Pro Hockey", "KXNHL", "KXNHL-26", "Stanley Cup")[0]
    g27 = data.tournament_of("Pro Hockey", "KXNHL", "KXNHL-27", "Stanley Cup")[0]
    assert g26 == "Pro Hockey · 26" and g27 == "Pro Hockey · 27" and g26 != g27   # cross-season separated
    # Same season, two series tickers → same key (one ladder).
    s26 = data.tournament_of("Pro Hockey", "KXNHLEAST", "KXNHLEAST-26", "x")[0]
    assert s26 == "Pro Hockey · 26"


def test_nhl_same_team_two_seasons_do_not_ladder_together():
    champ27 = data.build_contracts("KXNHL", [_event("KXNHL-27", [
        _mkt("KXNHL-27-BOS", "Bruins", "u-bos", "0.60", "0.62", "Win the 2027 Stanley Cup")])])
    conf26 = data.build_contracts("KXNHLEAST", [_event("KXNHLEAST-26", [
        _mkt("KXNHLEAST-26-BOS", "Bruins", "u-bos", "0.40", "0.45", "Win the Eastern Conference")])])
    checks = consistency.build_checks(pd.DataFrame(champ27 + conf26))
    # Season scoping puts the two rows in different tournaments (· 27 vs · 26), so the 2027 championship
    # price is never paired against the 2026 conference price → no FALSE executable violation. (Without the
    # fix both rows would share "Pro Hockey" and cross into an EXECUTABLE_VIOLATION.) Each season is its own
    # group, so the only Championship-vs-Conference rows are within-season MISSING_LAYER diagnostics.
    assert not (checks["status"] == "EXECUTABLE_VIOLATION").any()
    assert {"Pro Hockey · 26", "Pro Hockey · 27"} <= set(checks["tournament"])


def test_nhl_grouping_fallback_when_competition_missing():
    r = data.build_contracts("KXNHL", [_event("KXNHL-26", [
        _mkt("KXNHL-26-BOS", "Bruins", "u-bos", "0.40", "0.42")], competition=None)])[0]
    assert r["tournament"].startswith("Unknown")    # never blank → never silently mis-pairs


# ============================================================================================
# Fetch scope (shared non_other_families helper)
# ============================================================================================
def test_nhl_fetch_scope_includes_series_game_excludes_props():
    nhl = sports.get_sport("nhl")
    fams = data.non_other_families(nhl)
    assert "Other" not in fams
    all_series = ["KXNHL", "KXNHLEAST", "KXNHLWEST", "KXNHLPLAYOFF", "KXNHLSERIES", "KXNHLGAME",
                  "KXNHLSERIESGAMES", "KXNHLFINALSEXACT"]
    fetched = set(data.series_for_families(all_series, fams))
    assert {"KXNHL", "KXNHLEAST", "KXNHLWEST", "KXNHLPLAYOFF", "KXNHLSERIES", "KXNHLGAME"} <= fetched
    assert fetched.isdisjoint({"KXNHLSERIESGAMES", "KXNHLFINALSEXACT"})


# ============================================================================================
# Dutch books: per-game (caveat) + playoff series (no game caveat) + the same-series guard
# ============================================================================================
def _leg(series, event_ticker, kind, team, uuid, *, yes_bid_c=None, yes_ask_c=None, no_ask_c=None):
    return {
        "series": series, "event_ticker": event_ticker, "kind": kind,
        "player": team, "player_key": uuid, "contract": f"Beat opponent ({team})",
        "tournament": "Pro Hockey · 26", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c,
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
        "market_ticker": f"{series}-{team[:3].upper()}", "kalshi_url": "https://kalshi.com/markets/nhl",
        "event_title": "BOS vs TOR",
    }


def _game(team, uuid, **kw):
    return _leg("KXNHLGAME", "KXNHLGAME-26JUN05BOSTOR", "game", team, uuid, **kw)


def _series(team, uuid, **kw):
    return _leg("KXNHLSERIES", "KXNHLSERIES-26BOSTORR1", "match", team, uuid, **kw)


def test_nhl_game_underround_fires_with_caveat():
    out = dutchbook.find_dutch_books([_game("Bruins", "u-bos", yes_bid_c=43, yes_ask_c=45),
                                      _game("Leafs", "u-tor", yes_bid_c=46, yes_ask_c=48)])
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and f["direction"] == "underround"
    assert f["settlement_caveat"]                       # non-empty per-game caveat
    assert f["series"] == "KXNHLGAME"


def test_nhl_game_overround_uses_no_ask_fallback():
    out = dutchbook.find_dutch_books([_game("Bruins", "u-bos", yes_bid_c=55, yes_ask_c=58),
                                      _game("Leafs", "u-tor", yes_bid_c=57, yes_ask_c=60)])
    assert len(out) == 1 and out[0]["direction"] == "overround" and out[0]["settlement_caveat"]


def test_nhl_series_book_has_no_game_caveat():
    out = dutchbook.find_dutch_books([_series("Bruins", "u-bos", yes_bid_c=43, yes_ask_c=45),
                                      _series("Leafs", "u-tor", yes_bid_c=46, yes_ask_c=48)])
    assert len(out) == 1 and out[0]["series"] == "KXNHLSERIES"
    assert out[0]["settlement_caveat"] == ""            # match/series settle together → no game caveat


def test_nhl_same_series_guard_blocks_cross_series_pair():
    # Two legs sharing an event ticker but DIFFERENT series must never pair (defensive guard).
    a = {**_game("Bruins", "u-bos", yes_bid_c=43, yes_ask_c=45), "event_ticker": "EVT"}
    b = {**_series("Leafs", "u-tor", yes_bid_c=46, yes_ask_c=48), "event_ticker": "EVT"}
    assert dutchbook.find_dutch_books([a, b]) == []


def test_nhl_winner_field_pair_and_conference_pair_not_two_way():
    # Two KXNHL winner rows are a FIELD, not a 2-way head-to-head → no _detect_pair book.
    w = [{**_game("Bruins", "u-bos", yes_bid_c=20, yes_ask_c=22), "series": "KXNHL", "kind": "winner",
          "event_ticker": "KXNHL-26"},
         {**_game("Leafs", "u-tor", yes_bid_c=18, yes_ask_c=20), "series": "KXNHL", "kind": "winner",
          "event_ticker": "KXNHL-26"}]
    assert all(f["status"] != dutchbook.EXECUTABLE_DUTCH_BOOK or f.get("direction") for f in dutchbook.find_dutch_books(w))
    # Two conference (advance) rows are not two-way either.
    c = [{**_game("Bruins", "u-bos", yes_bid_c=40, yes_ask_c=42), "series": "KXNHLEAST", "kind": "advance",
          "event_ticker": "KXNHLEAST-26"},
         {**_game("Rangers", "u-nyr", yes_bid_c=44, yes_ask_c=46), "series": "KXNHLEAST", "kind": "advance",
          "event_ticker": "KXNHLEAST-26"}]
    assert dutchbook.find_dutch_books(c) == []


# ============================================================================================
# Game-time stamping
# ============================================================================================
def test_nhl_game_gets_game_time():
    m = {"ticker": "KXNHLGAME-26-X", "yes_sub_title": "Bruins", "custom_strike": {"hockey_team": "u"},
         "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42", "last_price_dollars": "0.42",
         "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "1",
         "status": "active", "title": "g", "occurrence_datetime": "2026-06-05T23:00:00Z"}
    evt = {"event_ticker": "KXNHLGAME-26", "title": "g",
           "product_metadata": {"competition": "Pro Hockey"}, "markets": [m]}
    r = data.build_contracts("KXNHLGAME", [evt])[0]
    assert r["kind"] == "game" and r["time_kind"] == "Game time"
    assert r["time_value"] == "2026-06-05T23:00:00Z"
