"""Unit tests for Esports (10th sport) — registration, the strict exact-ownership family allow-list,
the per-game / per-map two-way dutch books (DRAW-FREE → game_mece_by_shape=True → ungated, unlike NFL),
the tournament-winner one-winner FIELD overround, identity, season-scoped grouping, and fetch scope.
There is NO containment ladder in v1. Pure — crafted fixtures, no network.

Grounding (live probe 2026-06-08, see .kss/.../note-20260608-esports-probe.md): identity
custom_strike.esports_competitor; KX*GAME (match winner) and KX*MAP (map winner) are 2-market
mutually_exclusive, draw-free events (rules_secondary empty, no $0.50-tie clause); generic per-title
winner series (KXCS2, …) carry the live tournament FIELD event (e.g. KXCS2-IEMCOL26, 32 ME markets).
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
def _mkt(ticker, team, uuid, bid, ask, title="x", *, status="active", mutually_exclusive=True):
    return {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"esports_competitor": uuid},
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
            "no_bid_dollars": f"{1 - float(ask):.2f}", "no_ask_dollars": f"{1 - float(bid):.2f}",
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
            "status": status, "title": title, "mutually_exclusive": mutually_exclusive}


def _event(event_ticker, markets, competition="CS2"):
    meta = {"competition": competition} if competition is not None else {}
    return {"event_ticker": event_ticker, "title": "Esports", "product_metadata": meta,
            "markets": markets, "mutually_exclusive": True}


# ============================================================================================
# Registration + resolution
# ============================================================================================
def test_esports_registered():
    ids = {c.sport_id for c in sports.all_sports()}
    assert {"tennis", "nba", "wnba", "golf", "soccer", "mlb", "nhl", "motorsport", "nfl",
            "esports"} <= ids
    es = sports.get_sport("esports")
    assert es.label == "Esports"
    assert es.game_mece_by_shape is True            # esports games/maps are draw-free → ungated
    assert es.field_families == frozenset({"winner"})
    assert es.match_family == ""                     # field sport; games ride the "game" family


def test_esports_family_allowlist():
    cfg = sports.get_sport("esports")
    for game in ("KXCS2GAME", "KXCS2MAP", "KXLOLGAME", "KXLOLMAP", "KXVALORANTGAME", "KXVALORANTMAP",
                 "KXDOTA2GAME", "KXDOTA2MAP", "KXCODGAME", "KXCODMAP", "KXR6GAME", "KXR6MAP"):
        assert cfg.family_of(game) == "game", game
    for winner in ("KXCS2", "KXDOTA2", "KXCOD", "KXVALORANT", "KXR6", "KXLEAGUEWORLDS"):
        assert cfg.family_of(winner) == "winner", winner
    # Strict exact-equality: totalmaps / qualifiers / props / legacy / dupes / test → "other".
    for excluded in ("KXCS2TOTALMAPS", "KXCODTOTALMAPS", "KXLOLTOTALMAPS",
                     "KXCS2QUALIFIER", "KXCS2QUALIFIERS", "KXCS2QUALIFY",
                     "KXCSGO", "KXCSGOGAME", "KXCSGOMAP", "KXCS2GAMES", "KXCS2MAPWINNER",
                     "KXLOLGAMES", "KXROCKETLEAGUEGAME",
                     "KXCHOVYMVP", "KXZYWOOMVP", "KXRANKLISTCS2TEAM", "KXROSTERT1",
                     "KXESPORTSTEST", "KXIEMCHEN", "KXSTARLADDERBUDAPESTMAJOR"):
        assert cfg.family_of(excluded) == "other", excluded


def test_esports_unowned_excluded_resolves_to_unknown_not_esports():
    # Exact-only ownership: anything not in the allow-list is NOT esports (no silent default). The
    # family_fn above returns "other" only when called directly; live resolution returns the UNKNOWN sport
    # (so it is discovered/labelled "other" if ever encountered, and is never fetched).
    for t in ("KXCS2TOTALMAPS", "KXCS2QUALIFIER", "KXCSGO", "KXCS2GAMES", "KXESPORTSTEST", "KXIEMCHEN"):
        assert sports.sport_for_series(t).sport_id == "unknown", t
    for owned in ("KXCS2GAME", "KXCS2MAP", "KXCS2", "KXLEAGUEWORLDS"):
        assert sports.sport_for_series(owned).sport_id == "esports", owned


def test_esports_excluded_ticker_yields_nothing_through_build_contracts():
    # A total-maps series (UNKNOWN sport → "other") produces no checks and no dutch books — no false flag.
    evt = _event("KXCS2TOTALMAPS-26", [_mkt("KXCS2TOTALMAPS-26-X", "Over 2.5", "u-x", "0.40", "0.45")])
    rows = data.build_contracts("KXCS2TOTALMAPS", [evt])
    assert rows and all(r["kind"] == "other" and r["ladder_eligible"] is False for r in rows)
    assert consistency.build_checks(pd.DataFrame(rows)).empty
    assert dutchbook.find_dutch_books(rows) == []


# ============================================================================================
# Contract labels
# ============================================================================================
def _label(cfg, series, market):
    mc = cfg.classify(series, market)
    return data._contract_label(mc.family, market, "", mc.stage, cfg, mc.ladder_node)


def test_esports_contract_labels():
    es = sports.get_sport("esports")
    # Winner field uses the default winner_label; a game row falls back to its (cleaned) market title.
    assert _label(es, "KXCS2", {"ticker": "KXCS2-IEMCOL26-VIT", "title": "IEM Cologne Champion"}) \
        == es.winner_label
    assert _label(es, "KXCS2GAME", {"ticker": "KXCS2GAME-26-YN", "title": "Young Ninjas"}) == "Young Ninjas"


# ============================================================================================
# Per-game / per-map two-way dutch books (via build_contracts) — draw-free, ungated
# ============================================================================================
def test_esports_game_dutch_book_fires_with_caveat():
    evt = _event("KXCS2GAME-26JUN100630YNG2A", [
        _mkt("KXCS2GAME-26JUN100630YNG2A-YN", "Young Ninjas", "u1", "0.40", "0.45"),
        _mkt("KXCS2GAME-26JUN100630YNG2A-G2A", "G2 Ares", "u2", "0.48", "0.52")])
    rows = data.build_contracts("KXCS2GAME", [evt])
    assert [r["kind"] for r in rows] == ["game", "game"]
    out = dutchbook.find_dutch_books(rows)
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and f["direction"] == "underround"
    assert f["settlement_caveat"]                                   # per-game caveat present (keys off "game")
    # No ladder in v1 → no containment checks for a game event.
    assert consistency.build_checks(pd.DataFrame(rows)).empty


def test_esports_map_dutch_book_is_first_class():
    # KX*MAP is the same 2-way draw-free shape — maps must produce dutch books, not be treated as props.
    evt = _event("KXCS2MAP-26JUN100630YNG2A-2", [
        _mkt("KXCS2MAP-26JUN100630YNG2A-2-YN", "Young Ninjas", "u1", "0.40", "0.45"),
        _mkt("KXCS2MAP-26JUN100630YNG2A-2-G2A", "G2 Ares", "u2", "0.48", "0.52")], competition="CS2")
    rows = data.build_contracts("KXCS2MAP", [evt])
    assert [r["kind"] for r in rows] == ["game", "game"]
    out = dutchbook.find_dutch_books(rows)
    assert len(out) == 1 and out[0]["direction"] == "underround"


# ============================================================================================
# MECE-by-shape no-op: an esports game with NO rules text still books (game_mece_by_shape=True)
# ============================================================================================
def _game_row(series, event, team, uuid, yes_bid_c, yes_ask_c):
    return {"series": series, "event_ticker": event, "kind": "game",
            "player": team, "player_key": uuid, "contract": team,
            "tournament": "CS2 · 26", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c,
            "no_ask_c": None, "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight",
            "status": "active", "market_ticker": f"{event}-{team[:3].upper()}",
            "kalshi_url": "https://kalshi.com/markets/cs2", "event_title": "YN vs G2"}


def test_esports_game_books_without_any_proof_gate():
    # Unlike NFL, esports inherits game_mece_by_shape=True → _detect_pair runs ungated even with no rules.
    out = dutchbook.find_dutch_books([
        _game_row("KXCS2GAME", "KXCS2GAME-26JUN100630YNG2A", "Young Ninjas", "u1", 43, 45),
        _game_row("KXCS2GAME", "KXCS2GAME-26JUN100630YNG2A", "G2 Ares", "u2", 46, 48)])
    assert len(out) == 1 and out[0]["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK
    assert "settlement_basis" not in out[0] or not out[0].get("settlement_basis")  # no fixed-sum gate


# ============================================================================================
# Tournament-winner one-winner FIELD overround
# ============================================================================================
def _winner_row(team, uuid, yes_bid_c, no_ask_c):
    return {"series": "KXCS2", "event_ticker": "KXCS2-IEMCOL26", "kind": "winner",
            "mutually_exclusive": True, "player": team, "player_key": uuid,
            "contract": f"Win the tournament ({team})", "tournament": "CS2 · 26",
            "yes_bid_c": yes_bid_c, "yes_ask_c": yes_bid_c + 2, "no_ask_c": no_ask_c,
            "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
            "market_ticker": f"KXCS2-IEMCOL26-{uuid}", "kalshi_url": "https://kalshi.com/markets/kxcs2",
            "event_title": "IEM Cologne Champion"}


def test_esports_winner_field_overround_fires_when_mispriced():
    rows = [_winner_row("Vitality", "u1", 40, 60),
            _winner_row("Team Falcons", "u2", 40, 60),
            _winner_row("Natus Vincere", "u3", 40, 60)]
    out = dutchbook.find_dutch_books(rows)
    assert len(out) == 1
    assert out[0]["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and out[0]["direction"] == "overround"


# ============================================================================================
# Identity + season-scoped grouping
# ============================================================================================
def test_esports_identity_uuid_high_else_name_low():
    r = data.build_contracts("KXCS2GAME", [_event("KXCS2GAME-26", [
        _mkt("KXCS2GAME-26-YN", "Young Ninjas", "u1", "0.40", "0.42")])])[0]
    assert r["player_key"] == "u1" and r["mapping_confidence"] == "high"
    m = _mkt("KXCS2GAME-26-YN", "Young Ninjas", "u1", "0.40", "0.42")
    m["custom_strike"] = {}
    r2 = data.build_contracts("KXCS2GAME", [_event("KXCS2GAME-26", [m])])[0]
    assert r2["mapping_confidence"] == "low"


def test_esports_grouping_season_scoped_and_fallback():
    # Non-tennis → season-scoped; a missing competition never collapses to blank.
    g = data.build_contracts("KXCS2GAME", [_event("KXCS2GAME-26JUN10YNG2A", [
        _mkt("KXCS2GAME-26JUN10YNG2A-YN", "Young Ninjas", "u1", "0.40", "0.42")], competition=None)])[0]
    assert g["tournament"].startswith("Unknown")


# ============================================================================================
# Fetch scope
# ============================================================================================
def test_esports_fetch_scope_includes_game_map_winner_excludes_props():
    es = sports.get_sport("esports")
    fams = data.non_other_families(es)
    assert "Other" not in fams
    all_series = ["KXCS2GAME", "KXCS2MAP", "KXCS2", "KXLEAGUEWORLDS",
                  "KXCS2TOTALMAPS", "KXCS2QUALIFIER", "KXCSGO", "KXRANKLISTCS2TEAM"]
    fetched = set(data.series_for_families(all_series, fams))
    assert {"KXCS2GAME", "KXCS2MAP", "KXCS2", "KXLEAGUEWORLDS"} <= fetched
    assert fetched.isdisjoint({"KXCS2TOTALMAPS", "KXCS2QUALIFIER", "KXCSGO", "KXRANKLISTCS2TEAM"})
