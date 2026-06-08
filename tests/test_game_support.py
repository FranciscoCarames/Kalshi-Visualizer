"""PR5 — World Cup game-support signal (#5). Ask-implied support score (3·win + draw over 3 games),
diagnostic-only, never an edge. Synthetic round-robin for precise gate control + a fixture-backed score.
"""

import itertools
import json
from pathlib import Path

import game_support
import scanner
import sports
from sports import SOCCER_TIE_UUID

_FIX = Path(__file__).parent / "fixtures" / "wc_qualifier"
_TEAMS = [("Alpha", "ua"), ("Bravo", "ub"), ("Charlie", "uc"), ("Delta", "ud")]


def _team_row(ev, name, uuid, ask, *, size=100, quality="OK", status="active"):
    return {"series": "KXWCGAME", "event_ticker": ev, "kind": "game", "player": name,
            "competitor_uuid": uuid, "player_key": uuid, "participant_type": "participant",
            "yes_ask_c": ask, "yes_ask_size": size, "quote_quality": quality, "status": status,
            "market_ticker": f"{ev}-{name[:3].upper()}", "kalshi_url": "https://kalshi.com/g",
            "custom_strike": {"soccer_team": uuid}}


def _tie_row(ev, ask, *, quality="OK", status="active", ptype="tie"):
    return {"series": "KXWCGAME", "event_ticker": ev, "kind": "game", "player": "Tie",
            "competitor_uuid": SOCCER_TIE_UUID, "player_key": f"tie::{ev}", "participant_type": ptype,
            "yes_ask_c": ask, "yes_ask_size": 100, "quote_quality": quality, "status": status,
            "market_ticker": f"{ev}-TIE", "kalshi_url": "https://kalshi.com/g",
            "custom_strike": {"soccer_team": SOCCER_TIE_UUID}}


def _qual_row(name, uuid, ask=50):
    return {"series": "KXWCGROUPQUAL", "event_ticker": "KXWCGROUPQUAL-26X", "kind": "advance",
            "player": name, "competitor_uuid": uuid, "player_key": uuid, "tournament": "2026 World Cup",
            "yes_ask_c": ask, "yes_ask_size": 100, "quote_quality": "OK", "status": "active",
            "market_ticker": f"KXWCGROUPQUAL-26X-{name[:3].upper()}", "kalshi_url": "https://kalshi.com/q"}


def _round_robin(*, win_ask=50, draw_ask=25, qual_ask=50):
    """6 games (4-team round-robin) + 4 qualifiers. Each game's two team asks = win_ask, tie = draw_ask."""
    games = []
    for i, (a, b) in enumerate(itertools.combinations(range(4), 2)):
        ev = f"KXWCGAME-26X{i}"
        (na, ua), (nb, ub) = _TEAMS[a], _TEAMS[b]
        games += [_team_row(ev, na, ua, win_ask), _team_row(ev, nb, ub, win_ask), _tie_row(ev, draw_ask)]
    quals = [_qual_row(n, u, ask=qual_ask) for n, u in _TEAMS]
    return games + quals


# --- happy path + math ------------------------------------------------------------------------------
def test_happy_path_score_math_and_shape():
    out = game_support.find_game_support_signals(
        _round_robin(win_ask=50, draw_ask=25, qual_ask=50), strong_score_c=500, qualifier_band_c=(40, 60))
    assert len(out) == 4
    f = out[0]
    assert f["status"] == game_support.GAME_SUPPORT_SIGNAL and f["bucket"] == "qualifier_setup"
    assert f["tradable_now"] == "Diagnostic only"
    assert f["ask_support_score_total_c"] == 525     # 3 games × (3·50 + 25)
    assert f["ask_support_score_per_game_c"] == 175
    assert f["qualifier_yes_ask_c"] == 50 and f["n_legs"] == 3


def test_below_strong_score_not_flagged():
    out = game_support.find_game_support_signals(
        _round_robin(win_ask=50, draw_ask=25), strong_score_c=600, qualifier_band_c=(0, 100))
    assert out == []


def test_qualifier_outside_band_not_flagged():
    out = game_support.find_game_support_signals(
        _round_robin(qual_ask=90), strong_score_c=0, qualifier_band_c=(35, 75))
    assert out == []


# --- inert / structural gates -----------------------------------------------------------------------
def test_inert_when_no_games():
    quals = [_qual_row(n, u) for n, u in _TEAMS]
    assert game_support.find_game_support_signals(quals, strong_score_c=0, qualifier_band_c=(0, 100)) == []


def test_needs_exactly_three_games():
    rows = _round_robin()
    # Add a 4th game for Alpha vs Bravo → both now have 4 games → skipped.
    rows += [_team_row("KXWCGAME-26XEXTRA", "Alpha", "ua", 50),
             _team_row("KXWCGAME-26XEXTRA", "Bravo", "ub", 50), _tie_row("KXWCGAME-26XEXTRA", 25)]
    diag = {}
    out = game_support.find_game_support_signals(rows, strong_score_c=0, qualifier_band_c=(0, 100), _diag=diag)
    names = {f["name"] for f in out}
    assert "Alpha" not in names and "Bravo" not in names
    assert {"Charlie", "Delta"} <= names
    assert any("expected 3" in r["reason"] for r in diag.get("rejected", []))


def test_string_only_tie_is_not_a_tie_fail_closed():
    rows = _round_robin()
    # Turn one game's tie into a string-"Tie" PARTICIPANT (no structured signal) → event has 3 parts /
    # 0 tie → invalid → its two teams drop to 2 games → skipped.
    tie = next(r for r in rows if r["participant_type"] == "tie")
    tie["participant_type"] = "participant"             # strip BOTH structured tie signals → string-only
    tie["competitor_uuid"] = "not-the-tie-uuid"
    tie["custom_strike"] = {"soccer_team": "not-the-tie-uuid"}
    diag = {}
    game_support.find_game_support_signals(rows, strong_score_c=0, qualifier_band_c=(0, 100), _diag=diag)
    assert any("2 teams + 1 tie" in r["reason"] for r in diag.get("rejected", []))


def test_two_tie_rows_is_malformed():
    rows = _round_robin()
    ev = "KXWCGAME-26X0"
    rows.append(_tie_row(ev, 25))                 # a second tie on one event
    diag = {}
    game_support.find_game_support_signals(rows, strong_score_c=0, qualifier_band_c=(0, 100), _diag=diag)
    assert any(r["event_ticker"] == ev for r in diag.get("rejected", []))


# --- firm / join gates ------------------------------------------------------------------------------
def test_crossed_win_leg_skips_team():
    rows = _round_robin()
    # Cross one of Alpha's win legs → Alpha has a non-firm game → skipped.
    bad = next(r for r in rows if r["player"] == "Alpha")
    bad["quote_quality"] = "Crossed"
    out = game_support.find_game_support_signals(rows, strong_score_c=0, qualifier_band_c=(0, 100))
    assert "Alpha" not in {f["name"] for f in out}


def test_uuid_miss_skips_team_with_diag():
    rows = [r for r in _round_robin() if not (r["series"] == "KXWCGROUPQUAL" and r["player"] == "Alpha")]
    diag = {}
    out = game_support.find_game_support_signals(rows, strong_score_c=0, qualifier_band_c=(0, 100), _diag=diag)
    assert "Alpha" not in {f["name"] for f in out}
    assert any("UUID match" in r["reason"] for r in diag.get("uuid_miss", []))


# --- fixture-backed scores --------------------------------------------------------------------------
def test_fixture_backed_group_b_scores():
    import data
    fix = _FIX
    rows = data.build_contracts("KXWCGROUPQUAL", [json.loads((fix / "KXWCGROUPQUAL-26B.json").read_text("utf-8"))])
    for p in fix.glob("KXWCGAME-*.json"):
        rows += data.build_contracts("KXWCGAME", [json.loads(p.read_text("utf-8"))])
    out = {f["name"]: f for f in game_support.find_game_support_signals(
        rows, strong_score_c=0, qualifier_band_c=(0, 100))}
    assert out["Switzerland"]["ask_support_score_total_c"] == 625
    assert out["Qatar"]["ask_support_score_total_c"] == 152


# --- mapper + wording -------------------------------------------------------------------------------
def test_unified_mapper_diagnostic_shape():
    f = game_support.find_game_support_signals(
        _round_robin(), strong_score_c=0, qualifier_band_c=(0, 100))[0]
    d = scanner._to_unified_game_support(f, sports.SOCCER)
    assert d["bucket"] == "qualifier_setup" and d["source"] == "game_support"
    assert d["exec_gap_c"] is None and d["setup_type"] == "game_support_signal"
    assert d["ask_support_score_total_c"] == f["ask_support_score_total_c"]
    assert d["participant_keys"] == [f["participant_uuid"]]
    # Never present ROI / size / profit for a ranking signal.
    assert d["exec_min_size"] is None and d["exec_max_profit_dollars"] is None


def test_no_expected_points_wording():
    f = game_support.find_game_support_signals(_round_robin(), strong_score_c=0, qualifier_band_c=(0, 100))[0]
    blob = f"{f['detail']} {f['settlement_caveat']} {f['action_1_text']}".lower()
    assert "xpts" not in blob
    # The only mention of "expected points" is the honest DENIAL ("NOT expected points"), never an
    # affirmative claim — i.e. every occurrence is immediately preceded by "not ".
    assert all(blob[max(0, i - 4):i].endswith("not ") for i in _find_all(blob, "expected points"))
    assert "not expected points" in f["settlement_caveat"].lower()


def _find_all(s, sub):
    i = s.find(sub)
    while i != -1:
        yield i
        i = s.find(sub, i + 1)


def test_new_engine_modules_are_ui_free():
    # The pure-logic layer must never import a UI framework (CLAUDE.md hard rule).
    from pathlib import Path
    for mod in ("game_support.py", "exact_order.py", "wc_groups.py"):
        src = Path(__file__).parent.parent.joinpath(mod).read_text(encoding="utf-8")
        assert "import nicegui" not in src and "import streamlit" not in src
        assert "from nicegui" not in src and "from streamlit" not in src
