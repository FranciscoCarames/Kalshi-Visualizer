"""Unit tests for MLB (7th sport) — registration, classification, sport-aware labels (incl. the
cross-sport regressions the global label change touches), fetch scope, per-game dutch books, game-time
stamping, and the backlog settlement-caveat propagation. Pure — crafted fixtures, no network.
"""
from __future__ import annotations

import pandas as pd

import api
import consistency
import data
import dutchbook
import lifecycle
import sports
from webui import viewmodel as vm


# ============================================================================================
# Fixtures
# ============================================================================================
def _mkt(ticker, team, uuid, bid, ask, title="x", *, status="active", occurrence=None):
    m = {"ticker": ticker, "yes_sub_title": team, "custom_strike": {"baseball_team": uuid},
         "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
         "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "500",
         "status": status, "title": title}
    if occurrence is not None:
        m["occurrence_datetime"] = occurrence
    return m


def _event(event_ticker, markets, competition="Pro Baseball"):
    meta = {"competition": competition} if competition is not None else {}
    return {"event_ticker": event_ticker, "title": "MLB", "product_metadata": meta, "markets": markets}


# ============================================================================================
# Registration + resolution
# ============================================================================================
def test_mlb_registered():
    ids = {c.sport_id for c in sports.all_sports()}
    assert {"tennis", "nba", "wnba", "golf", "soccer", "mlb"} <= ids
    assert sports.get_sport("mlb").label == "MLB"


def test_mlb_family_allowlist():
    cfg = sports.get_sport("mlb")
    assert cfg.family_of("KXMLB") == "winner"
    assert cfg.family_of("KXMLBPLAYOFFS") == "advance"
    assert cfg.family_of("KXMLBAL") == "advance" and cfg.family_of("KXMLBNL") == "advance"
    assert cfg.family_of("KXMLBGAME") == "game"
    for excluded in ("KXMLBSERIES", "KXMLBSERIESGAMETOTAL", "KXMLBWS", "KXMLBWORLD",
                     "KXMLBALEAST", "KXMLBASGAME", "KXMLBSTGAME", "KXMLB500", "KXMLBALCY",
                     "KXMLBWINS-NYY"):
        assert cfg.family_of(excluded) == "other", excluded


def test_mlb_series_resolve_to_mlb():
    # The KXMLB prefix owns all baseball-like tickers (scope is the family_fn allow-list, not the prefix).
    for t in ("KXMLB", "KXMLBGAME", "KXMLBSERIES", "KXMLBASGAME"):
        assert sports.sport_for_series(t).sport_id == "mlb", t
    # A non-MLB baseball-ish ticker that doesn't match the prefix stays UNKNOWN (no silent default).
    assert sports.sport_for_series("KXBASEBALL").sport_id == "unknown"


def test_mlb_excluded_tickers_classify_as_other_through_build_contracts():
    evt = _event("KXMLBASGAME-26", [_mkt("KXMLBASGAME-26-AL", "AL All-Stars", "u-al", "0.50", "0.52")])
    rows = data.build_contracts("KXMLBASGAME", [evt])
    assert rows and all(r["kind"] == "other" and r["ladder_eligible"] is False for r in rows)
    # And no opportunities come out of an excluded series.
    assert consistency.build_checks(pd.DataFrame(rows)).empty
    assert dutchbook.find_dutch_books(rows) == []


# ============================================================================================
# Contract labels — the global-change regression battery
# ============================================================================================
def _label(cfg, series, market):
    mc = cfg.classify(series, market)
    return data._contract_label(mc.family, market, "", mc.stage, cfg, mc.ladder_node)


def test_mlb_contract_labels():
    mlb = sports.get_sport("mlb")
    assert _label(mlb, "KXMLB", {"ticker": "KXMLB-26-NYY"}) == "Win the World Series"
    assert _label(mlb, "KXMLBPLAYOFFS", {"ticker": "KXMLBPLAYOFFS-26-NYY"}) == "Reach Playoffs"
    assert _label(mlb, "KXMLBAL", {"ticker": "KXMLBAL-26-NYY"}) == "Win League"
    assert _label(mlb, "KXMLBNL", {"ticker": "KXMLBNL-26-LAD"}) == "Win League"


def test_label_change_does_not_regress_other_sports():
    # NBA conference advance becomes "Win Conference" (latent fix); winner uses the championship label.
    nba = sports.get_sport("nba")
    assert _label(nba, "KXNBAEAST", {"ticker": "KXNBAEAST-26-BOS"}) == "Win Conference"
    assert _label(nba, "KXNBA", {"ticker": "KXNBA-26-BOS",
                                 "title": "Will the Boston win the 2026 Pro Basketball Finals?"}) \
        == "Win the Championship"
    # Golf advance loses the awkward "Reach" prefix (node == stage).
    golf = sports.get_sport("golf")
    assert _label(golf, "KXPGATOP5", {"ticker": "KXPGATOP5-USOPEN"}) == "Top 5"
    assert _label(golf, "KXPGATOP10", {"ticker": "KXPGATOP10-USOPEN"}) == "Top 10"
    # Soccer advance is UNCHANGED ("Reach Round of 16", node already carries "Reach").
    soccer = sports.get_sport("soccer")
    assert _label(soccer, "KXWCROUND", {"ticker": "KXWCROUND-26RO16-PAR"}) == "Reach Round of 16"
    # Tennis winner + advance are unchanged.
    tennis = sports.get_sport("tennis")
    assert tennis.winner_label == "Win the tournament"
    assert _label(tennis, "KXATPADVANCE",
                  {"ticker": "KXATPADVANCE-26FOSF", "title": "reach the Semifinal"}) == "Reach Semifinal"


# ============================================================================================
# Category labels + ladder end-to-end
# ============================================================================================
def _ladder_rows(champ_bid, champ_ask, league_bid, league_ask):
    champ = _event("KXMLB-26", [_mkt("KXMLB-26-NYY", "Yankees", "u-nyy", champ_bid, champ_ask,
                                     "Will the Yankees win the 2026 World Series?")])
    league = _event("KXMLBAL-26", [_mkt("KXMLBAL-26-NYY", "Yankees", "u-nyy", league_bid, league_ask,
                                        "Will the Yankees win the American League?")])
    return data.build_contracts("KXMLB", [champ]) + data.build_contracts("KXMLBAL", [league])


def test_mlb_categories_and_ladder_violation():
    # Win World Series (deeper) priced ABOVE Win League (broader) → executable violation.
    rows = _ladder_rows("0.60", "0.62", "0.50", "0.55")
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"]: c for _, c in checks.iterrows()}
    assert "Win World Series ≤ Win League" in chains
    row = chains["Win World Series ≤ Win League"]
    assert row["status"] == "EXECUTABLE_VIOLATION" and row["exec_gap_c"] == 5
    assert row["child_category"] == "World Series"                  # MLB winner label
    assert row["parent_category"] == "Advancement (reach a stage)"  # MLB advance label


def test_mlb_ladder_clean_when_ordered():
    rows = _ladder_rows("0.40", "0.42", "0.55", "0.57")
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Win World Series ≤ Win League")
    assert row["status"] == "CLEAN"


def test_category_fallback_when_row_has_kind_but_no_category():
    # The consistency dispatch resolves off each leg's sport even when a hand-built row lacks "category".
    cfg = sports.get_sport("mlb")
    assert cfg.category_labels.get("winner") == "World Series"
    assert cfg.category_labels.get("advance") == "Advancement (reach a stage)"
    assert cfg.category_labels.get("game") == "Game (not laddered)"


# ============================================================================================
# Identity + grouping fallback
# ============================================================================================
def test_mlb_identity_uuid_high_else_name_low():
    evt = _event("KXMLB-26", [_mkt("KXMLB-26-NYY", "Yankees", "u-nyy", "0.40", "0.42")])
    r = data.build_contracts("KXMLB", [evt])[0]
    assert r["player_key"] == "u-nyy" and r["mapping_confidence"] == "high"
    # No UUID → name fallback, low confidence (NOT collision-safe by design).
    m = _mkt("KXMLB-26-NYY", "Yankees", "u-nyy", "0.40", "0.42")
    m["custom_strike"] = {}
    r2 = data.build_contracts("KXMLB", [_event("KXMLB-26", [m])])[0]
    assert r2["mapping_confidence"] == "low"


def test_mlb_grouping_fallback_when_competition_missing():
    evt = _event("KXMLB-26", [_mkt("KXMLB-26-NYY", "Yankees", "u-nyy", "0.40", "0.42")], competition=None)
    r = data.build_contracts("KXMLB", [evt])[0]
    assert r["tournament"].startswith("Unknown")    # never blank → never silently mis-pairs


# ============================================================================================
# Fetch scope (shared non_other_families helper)
# ============================================================================================
def test_non_other_families_excludes_other_for_every_sport():
    for cfg in sports.all_sports():
        if cfg.sport_id == "unknown":
            continue
        assert "Other" not in data.non_other_families(cfg), cfg.sport_id


def test_mlb_fetch_scope_includes_game_excludes_props():
    mlb = sports.get_sport("mlb")
    fams = data.non_other_families(mlb)
    all_series = ["KXMLB", "KXMLBAL", "KXMLBNL", "KXMLBPLAYOFFS", "KXMLBGAME",
                  "KXMLBSERIES", "KXMLBWS", "KXMLBASGAME", "KXMLBSTGAME", "KXMLBALEAST"]
    fetched = set(data.series_for_families(all_series, fams))
    assert {"KXMLB", "KXMLBAL", "KXMLBNL", "KXMLBPLAYOFFS", "KXMLBGAME"} <= fetched
    assert fetched.isdisjoint({"KXMLBSERIES", "KXMLBWS", "KXMLBASGAME", "KXMLBSTGAME", "KXMLBALEAST"})


# ============================================================================================
# Per-game dutch books + settlement caveat
# ============================================================================================
def _game(team, uuid, *, yes_ask_c=None, no_ask_c=None, yes_bid_c=None):
    return {
        "series": "KXMLBGAME", "event_ticker": "KXMLBGAME-26JUN05NYYBOS", "kind": "game",
        "player": team, "player_key": uuid, "contract": f"Beat opponent ({team})",
        "tournament": "Pro Baseball", "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c,
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
        "market_ticker": f"KXMLBGAME-{team[:3].upper()}", "kalshi_url": "https://kalshi.com/markets/kxmlbgame",
        "event_title": "NYY vs BOS",
    }


def test_mlb_game_underround_fires_with_caveat():
    a = _game("Yankees", "nyy", yes_bid_c=43, yes_ask_c=45)
    b = _game("Red Sox", "bos", yes_bid_c=46, yes_ask_c=48)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1
    f = out[0]
    assert f["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and f["direction"] == "underround"
    assert f["settlement_caveat"]                       # non-empty per-game caveat
    assert f["series"] == "KXMLBGAME"


def test_mlb_game_overround_fires_with_no_ask_fallback():
    # No no_ask → 100 - yes_bid fallback. yes_bid 55,57 → no_ask 45,43 → 88 < 100 overround.
    a = _game("Yankees", "nyy", yes_bid_c=55, yes_ask_c=58)
    b = _game("Red Sox", "bos", yes_bid_c=57, yes_ask_c=60)
    out = dutchbook.find_dutch_books([a, b])
    assert len(out) == 1 and out[0]["direction"] == "overround"
    assert out[0]["settlement_caveat"]


def test_mlb_allstar_game_is_not_owned_so_no_book():
    # KXMLBASGAME resolves to "other" (not "game") → never a dutch book even with 2 markets.
    a = {**_game("AL", "al", yes_bid_c=43, yes_ask_c=45), "series": "KXMLBASGAME", "kind": "other"}
    b = {**_game("NL", "nl", yes_bid_c=46, yes_ask_c=48), "series": "KXMLBASGAME", "kind": "other"}
    assert dutchbook.find_dutch_books([a, b]) == []


def test_mlb_series_two_markets_is_not_automatically_mece():
    # Regression guard: KXMLBSERIES is excluded (a regular-season series can tie 2-2) — no dutch book
    # and (match_family="") no UNKNOWN_RELATIONSHIP ladder spray.
    a = {**_game("Yankees", "nyy", yes_bid_c=43, yes_ask_c=45), "series": "KXMLBSERIES", "kind": "other"}
    b = {**_game("Red Sox", "bos", yes_bid_c=46, yes_ask_c=48), "series": "KXMLBSERIES", "kind": "other"}
    assert dutchbook.find_dutch_books([a, b]) == []
    assert consistency.build_checks(pd.DataFrame([a, b])).empty


# ============================================================================================
# Game-time stamping (all game sports)
# ============================================================================================
def test_game_kind_gets_game_time_across_sports():
    cases = [
        ("KXMLBGAME", "KXMLBGAME-26", {"baseball_team": "u"}),
        ("KXNBAGAME", "KXNBAGAME-26", {"basketball_team": "u"}),
        ("KXWNBAGAME", "KXWNBAGAME-26", {"basketball_team": "u"}),
        ("KXWCGAME", "KXWCGAME-26", {"soccer_team": "u"}),
    ]
    for series, evt_t, cs in cases:
        m = {"ticker": f"{evt_t}-X", "yes_sub_title": "Team", "custom_strike": cs,
             "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42", "last_price_dollars": "0.42",
             "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "volume_fp": "1",
             "status": "active", "title": "x", "occurrence_datetime": "2026-06-05T23:00:00Z"}
        evt = {"event_ticker": evt_t, "title": "g", "product_metadata": {"competition": "C"}, "markets": [m]}
        r = data.build_contracts(series, [evt])[0]
        assert r["kind"] == "game", series
        assert r["time_kind"] == "Game time", series
        assert r["time_value"] == "2026-06-05T23:00:00Z", series


def test_mlb_non_game_rows_are_not_game_time():
    evt = _event("KXMLB-26", [_mkt("KXMLB-26-NYY", "Yankees", "u-nyy", "0.40", "0.42",
                                   occurrence="2026-10-01T00:00:00Z")])
    r = data.build_contracts("KXMLB", [evt])[0]
    assert r["time_kind"] != "Game time"


# ============================================================================================
# Backlog settlement-caveat propagation
# ============================================================================================
def _op(oid, bucket="actionable", **kw):
    return {"opportunity_id": oid, "bucket": bucket, "status": kw.get("status", ""),
            "sport": kw.get("sport", "mlb"), "name": kw.get("name", "NYY vs BOS"),
            "exec_gap_c": kw.get("exec_gap_c", 7), "url": kw.get("url", ""),
            "settlement_caveat": kw.get("settlement_caveat", "")}


def _snap(ts, *rows):
    return {"fetched_at": f"t{ts}", "fetched_ts": float(ts), "opportunities": list(rows)}


def test_backlog_carries_settlement_caveat():
    caveat = "gross quote edge; a postponed/abandoned game can settle differently"
    hist = [_snap(1, _op("g1", "actionable", settlement_caveat=caveat)),
            _snap(2, _op("g1", "blocked", settlement_caveat=caveat))]   # left the actionable set
    out = lifecycle.recently_actionable(hist)
    assert len(out) == 1
    assert out[0]["last_settlement_caveat"] == caveat
    # NiceGUI viewmodel exposes it; FastAPI BacklogItem accepts it.
    assert vm.backlog_row(out[0], "UTC")["caveat"] == caveat
    assert api.BacklogItem(**out[0]).last_settlement_caveat == caveat


def test_backlog_non_game_has_blank_caveat():
    hist = [_snap(1, _op("c1", "actionable")), _snap(2, _op("c1", "blocked"))]
    out = lifecycle.recently_actionable(hist)
    assert out[0]["last_settlement_caveat"] == ""
    assert vm.backlog_row(out[0], "UTC")["caveat"] == ""
