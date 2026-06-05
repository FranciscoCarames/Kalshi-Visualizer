"""Motorsport (8th sport) — registration, classification, identity, fields, ladders, grouping.

Fixtures mirror the Phase-0 live probe (2026-06-05): F1 / NASCAR Cup / NASCAR Truck / IndyCar / MotoGP,
the one-winner fields (race winner = Kalshi "Games", pole, fastest lap, top constructor/team, champion
futures) vs the mutually_exclusive=False finishing-position rungs (Top-N / Podium). No network.
"""
from __future__ import annotations

import pandas as pd

import consistency
import data
import dutchbook
import sports

UUID_A = "463e968e-3572-4a49-89dd-958f7f1f42da"
UUID_B = "9ee35edd-5ce8-4404-9d90-43c56f71df73"
UUID_C = "29cb88fe-eb30-47b8-8d5f-5394742c0f67"


# --------------------------------------------------------------------------------------------------
# Registration & resolution
# --------------------------------------------------------------------------------------------------
def test_motorsport_registered():
    assert "motorsport" in {c.sport_id for c in sports.all_sports()}
    assert sports.get_sport("motorsport").label == "Motorsport"


def test_series_resolution_per_competition():
    for tk in ("KXF1RACE", "KXF1", "KXNASCARRACE", "KXNASCARTRUCKSERIES", "KXINDYCARRACE",
               "KXINDY500", "KXMOTOGP", "KXMOTOGPRACE"):
        assert sports.sport_for_series(tk).sport_id == "motorsport", tk


def test_non_motorsport_kx_not_captured():
    # KXRACE is "Ferrari KPI" (Financials) — the prefixes must not swallow it.
    assert sports.sport_for_series("KXRACE").sport_id != "motorsport"
    assert sports.sport_for_series("KXNBA").sport_id == "nba"


def test_family_map_matches_live_scopes():
    cfg = sports.get_sport("motorsport")
    expect = {
        "KXF1RACE": "race_winner", "KXF1RACESPRINT": "race_winner", "KXINDY500": "race_winner",
        "KXNASCARRACE": "race_winner", "KXMOTOGPRACE": "race_winner",
        "KXF1": "winner", "KXNASCARCUPSERIES": "winner", "KXNASCARTRUCKSERIES": "winner",
        "KXINDYCARSERIES": "winner", "KXMOTOGP": "winner",
        "KXF1RACEPODIUM": "advance", "KXF1TOP5": "advance", "KXF1TOP10": "advance",
        "KXNASCARTOP3": "advance", "KXNASCARTOP20": "advance", "KXINDYCARTOP3": "advance",
        "KXF1TOPCONSTRUCTOR": "constructor", "KXF1CONSTRUCTORS": "constructor",
        "KXNASCARTOPTEAM": "team", "KXNASCARTOPMANU": "team", "KXMOTOGPTEAMS": "team",
        "KXF1POLE": "pole", "KXNASCARPOLE": "pole", "KXF1FASTLAP": "fastest_lap",
        "KXNASCARFASTLAP": "fastest_lap",
        "KXF1H2H": "other", "KXNASCARH2H": "other", "KXF1QUALIFY": "other", "KXNASCARRACEOLD": "other",
    }
    for tk, fam in expect.items():
        assert cfg.family_of(tk) == fam, (tk, cfg.family_of(tk))


def test_division_is_coarse_competition():
    cfg = sports.get_sport("motorsport")
    assert cfg.division_of("KXF1RACE") == "F1"
    assert cfg.division_of("KXNASCARTRUCKSERIES") == "NASCAR"   # Cup/Truck/O'Reilly all coarse "NASCAR"
    assert cfg.division_of("KXINDYCARRACE") == "IndyCar"
    assert cfg.division_of("KXMOTOGP") == "MotoGP"


# --------------------------------------------------------------------------------------------------
# Identity, confidence, role namespacing (via build_contracts)
# --------------------------------------------------------------------------------------------------
def _event(series, event_ticker, markets, *, competition="F1", scope="Game", sub_title="GP 2026"):
    return {
        "event_ticker": event_ticker, "title": "Motorsport event", "sub_title": sub_title,
        "product_metadata": {"competition": competition, "competition_scope": scope},
        "mutually_exclusive": True, "markets": markets,
    }


def _mkt(event_ticker, code, name, cs, *, bid="0.10", ask="0.12"):
    return {
        "ticker": f"{event_ticker}-{code}", "yes_sub_title": name, "custom_strike": cs,
        "yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": ask,
        "no_ask_dollars": f"{1 - float(ask):.4f}", "no_bid_dollars": f"{1 - float(bid):.4f}",
        "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active",
        "title": f"Will {name} win?", "close_time": "2026-06-16T09:00:00Z",
    }


def test_driver_identity_high_confidence_and_role_namespace():
    ev = _event("KXF1RACE", "KXF1RACE-MONGP26",
                [_mkt("KXF1RACE-MONGP26", "PIA", "Oscar Piastri", {"racing_competitor": UUID_A})])
    rows = data.build_contracts("KXF1RACE", [ev])
    assert rows[0]["player_key"] == f"driver:{UUID_A}"
    assert rows[0]["mapping_confidence"] == "high"
    assert rows[0]["kind"] == "race_winner"


def test_constructor_name_is_low_confidence_and_distinct_role():
    """F1 constructors carry custom_strike.Participant = a NAME → low confidence, role-namespaced
    'constructor:' so it never merges with a driver keyed by the same string."""
    ev = _event("KXF1CONSTRUCTORS", "KXF1CONSTRUCTORS-26",
                [_mkt("KXF1CONSTRUCTORS-26", "RED", "Red Bull Racing", {"Participant": "Red Bull Racing"})],
                competition="F1", scope="Future")
    rows = data.build_contracts("KXF1CONSTRUCTORS", [ev])
    assert rows[0]["player_key"] == "constructor:Red Bull Racing"
    assert rows[0]["mapping_confidence"] == "low"
    assert rows[0]["kind"] == "constructor"


def test_nascar_team_uuid_high_confidence():
    ev = _event("KXNASCARTOPTEAM", "KXNASCARTOPTEAM-FIRC26",
                [_mkt("KXNASCARTOPTEAM-FIRC26", "JOEG", "Joe Gibbs Racing",
                      {"nascar_team": "68f00799-a17a-4cbe-96a3-116706267149"})],
                competition="NASCAR Cup Series", scope="Top Team")
    rows = data.build_contracts("KXNASCARTOPTEAM", [ev])
    assert rows[0]["player_key"].startswith("team:")
    assert rows[0]["mapping_confidence"] == "high"


# --------------------------------------------------------------------------------------------------
# Event-instance grouping (tournament_key_fn)
# --------------------------------------------------------------------------------------------------
def test_same_race_scopes_share_grouping_key():
    race = data.build_contracts("KXF1RACE", [_event(
        "KXF1RACE", "KXF1RACE-MONGP26",
        [_mkt("KXF1RACE-MONGP26", "PIA", "Oscar Piastri", {"racing_competitor": UUID_A})])])
    top5 = data.build_contracts("KXF1TOP5", [_event(
        "KXF1TOP5", "KXF1TOP5-MONGP26",
        [_mkt("KXF1TOP5-MONGP26", "PIA", "Oscar Piastri", {"racing_competitor": UUID_A})],
        scope="Top 5 Finishers")])
    assert race[0]["tournament"] == "F1 · main-race · MONGP26"
    assert top5[0]["tournament"] == race[0]["tournament"]            # group together for the ladder


def test_sprint_and_futures_separate_from_main_race():
    main = data.build_contracts("KXF1RACE", [_event(
        "KXF1RACE", "KXF1RACE-MONGP26",
        [_mkt("KXF1RACE-MONGP26", "P", "P", {"racing_competitor": UUID_A})])])
    sprint = data.build_contracts("KXF1RACESPRINT", [_event(
        "KXF1RACESPRINT", "KXF1RACESPRINT-MONGP26",
        [_mkt("KXF1RACESPRINT-MONGP26", "P", "P", {"racing_competitor": UUID_A})])])
    futures = data.build_contracts("KXF1", [_event(
        "KXF1", "KXF1-26", [_mkt("KXF1-26", "P", "P", {"racing_competitor": UUID_A})], scope="Future")])
    keys = {main[0]["tournament"], sprint[0]["tournament"], futures[0]["tournament"]}
    assert len(keys) == 3
    assert sprint[0]["tournament"] == "F1 · sprint · MONGP26"


# --------------------------------------------------------------------------------------------------
# One-winner field overround vs non-ME finishing rungs
# --------------------------------------------------------------------------------------------------
def _field_row(name, key, *, kind, series, event, yes_bid_c, me=True):
    return {
        "kind": kind, "series": series, "event_ticker": event, "player": name,
        "player_key": f"driver:{key}", "is_participant": True, "tournament": "F1 · main-race · X",
        "tour": "F1", "mutually_exclusive": me, "yes_bid_c": yes_bid_c, "no_ask_c": 100 - yes_bid_c,
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
        "market_ticker": f"{event}-{key}", "kalshi_url": "https://kalshi.com/x", "event_title": "F",
    }


def test_race_winner_field_overround_fires():
    rows = [_field_row("A", "a", kind="race_winner", series="KXF1RACE", event="KXF1RACE-X", yes_bid_c=40),
            _field_row("B", "b", kind="race_winner", series="KXF1RACE", event="KXF1RACE-X", yes_bid_c=35),
            _field_row("C", "c", kind="race_winner", series="KXF1RACE", event="KXF1RACE-X", yes_bid_c=30)]
    f = dutchbook.find_dutch_books(rows)
    assert len(f) == 1 and f[0]["direction"] == "overround" and f[0]["exec_gap_c"] == 5


def test_pole_and_constructor_fields_are_overround_eligible():
    for kind, series, ev in (("pole", "KXF1POLE", "KXF1POLE-X"),
                             ("constructor", "KXF1TOPCONSTRUCTOR", "KXF1TOPCONSTRUCTOR-X")):
        rows = [_field_row("A", "a", kind=kind, series=series, event=ev, yes_bid_c=40),
                _field_row("B", "b", kind=kind, series=series, event=ev, yes_bid_c=35),
                _field_row("C", "c", kind=kind, series=series, event=ev, yes_bid_c=30)]
        assert len(dutchbook.find_dutch_books(rows)) == 1, kind


def test_topn_finishers_not_a_field():
    """Top-N rungs are mutually_exclusive=False (many qualify) → never an overround field, even priced high."""
    rows = [_field_row("A", "a", kind="advance", series="KXF1TOP5", event="KXF1TOP5-X", yes_bid_c=80, me=False),
            _field_row("B", "b", kind="advance", series="KXF1TOP5", event="KXF1TOP5-X", yes_bid_c=80, me=False),
            _field_row("C", "c", kind="advance", series="KXF1TOP5", event="KXF1TOP5-X", yes_bid_c=80, me=False)]
    assert dutchbook.find_dutch_books(rows) == []


# --------------------------------------------------------------------------------------------------
# Per-competition ladder (ladder_fn) + node alignment
# --------------------------------------------------------------------------------------------------
def _ladder_row(key, kind, stage, comp, display_c, *, series="KXF1RACE", event="KXF1RACE-X"):
    return {
        "player": key, "player_key": f"driver:{key}", "kind": kind, "stage": stage,
        "competition": comp, "tournament": f"{comp} · main-race · X",
        "contract": f"{kind}-{stage}", "ladder_node": stage if kind == "advance" else "Win Race",
        "display_pct": float(display_c), "display_c": display_c,
        "yes_bid_c": max(display_c - 1, 0), "yes_ask_c": min(display_c + 1, 100),
        "yes_bid_pct": float(max(display_c - 1, 0)), "yes_ask_pct": float(min(display_c + 1, 100)),
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
        "series": series, "event_ticker": event, "market_ticker": f"T-{key}-{stage}", "kalshi_url": "x",
    }


def test_f1_ladder_checks_only_f1_rungs_correct_order():
    """A driver with Top 10 / Top 5 / Podium / Win Race in one F1 race ladders Top10⊇Top5⊇Podium⊇WinRace —
    and emits NO Cup-only rungs (Top 20 / Top 3)."""
    rows = [_ladder_row("p", "advance", "Top 10", "F1", 60),
            _ladder_row("p", "advance", "Top 5", "F1", 45),
            _ladder_row("p", "advance", "Podium", "F1", 25),
            _ladder_row("p", "race_winner", "Win Race", "F1", 10)]
    checks = consistency.build_checks(pd.DataFrame(rows))
    chains = {c["chain"] for _, c in checks.iterrows()}
    assert "Top 5 ≤ Top 10" in chains
    assert "Podium ≤ Top 5" in chains
    assert "Win Race ≤ Podium" in chains
    assert not any("Top 20" in ch or "Top 3" in ch for ch in chains)   # no cross-competition rungs


def test_f1_ladder_flags_finishing_inconsistency():
    """A deeper rung priced ABOVE a broader one is an executable cross (Podium bid > Top 5 ask)."""
    rows = [_ladder_row("p", "advance", "Top 5", "F1", 30),     # ask 31
            _ladder_row("p", "advance", "Podium", "F1", 70)]    # bid 69 > 31
    checks = consistency.build_checks(pd.DataFrame(rows))
    row = next(c for _, c in checks.iterrows() if c["chain"] == "Podium ≤ Top 5")
    assert row["status"] == "EXECUTABLE_VIOLATION"


def test_motogp_has_no_ladder():
    cfg = sports.get_sport("motorsport")
    assert cfg.ladder_for([{"competition": "MotoGP"}]).adjacent_pairs == ()
    assert cfg.ladder_for([{"competition": "NASCAR O'Reilly Auto Parts Series"}]).adjacent_pairs == ()


# --------------------------------------------------------------------------------------------------
# Contract labels
# --------------------------------------------------------------------------------------------------
def test_contract_labels():
    cfg = sports.get_sport("motorsport")
    m = {"title": "Will X win?"}
    assert data._contract_label("race_winner", m, "", "Win Race", cfg, "Win Race") == "Win the race"
    assert data._contract_label("winner", m, "", "Champion", cfg, None) == "Win the Championship"
    assert data._contract_label("pole", m, "", "", cfg, None) == "Pole position"
    assert data._contract_label("fastest_lap", m, "", "", cfg, None) == "Fastest lap"
    assert data._contract_label("advance", m, "", "Top 5", cfg, "Top 5") == "Top 5"
