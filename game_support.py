"""World Cup game-support signal (#5) — an ASK-IMPLIED support score (no UI imports).

For each team, sums an ``ask_support_score = 3·win_ask + draw_ask`` across its 3 group games
(``KXWCGAME``) and FLAGS the team (diagnostic-only) when the score is strong AND its qualify YES
(``KXWCGROUPQUAL``) sits in a "moderately priced" band — the games look strong but qualification isn't
fully priced.

CRITICAL: this is NOT "expected points" and NOT a probability. Top-of-book YES asks are vig-biased
UPWARD (win+draw+lose > 100¢), so the score overstates. It is a heuristic RANKING signal only — never an
edge, never executable, no ROI / size / profit. Diagnostic-only, gross, fees not modeled.

Fail-closed: a team is skipped (a ``_diag`` counter, never a row) unless it has exactly 3 group games,
each with exactly 2 participant rows + 1 structurally-identified tie row, a firm win + draw ask per game,
and a firm qualifier joined by ``soccer_team`` UUID. Stays inert (returns ``[]``) when no games are listed.
"""

from __future__ import annotations

from typing import Any

import data
import wc_groups
from glossary import GAME_SUPPORT_BASIS

GAME_SUPPORT_SIGNAL = "GAME_SUPPORT_SIGNAL"
GAME_SUPPORT_CHECK_TYPE = "game_support"
_GAME_SERIES = "KXWCGAME"
_QUALIFIER_SERIES = "KXWCGROUPQUAL"
_GAMES_PER_TEAM = 3
_NO_FIRM_QUALITY = ("No quote", "Crossed")


def _num(x: Any) -> Any:
    return None if x is None or (isinstance(x, float) and x != x) else x


def _record(diag: dict | None, kind: str, event_ticker: str, reason: str) -> None:
    if diag is not None:
        diag.setdefault(kind, []).append({"event_ticker": event_ticker, "reason": reason})


def _firm_ask_c(row: dict[str, Any]) -> int | None:
    """Cents of a firm, active, non-crossed YES ask — else None. Size is NOT required (the score is a
    ranking signal, never executed), but a No-quote / Crossed / inactive leg has no meaningful ask."""
    if str(row.get("quote_quality") or "") in _NO_FIRM_QUALITY:
        return None
    if str(row.get("status") or "") != "active":
        return None
    return _num(row.get("yes_ask_c"))


def _qualifier_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``soccer_team UUID → qualifier row`` for the KXWCGROUPQUAL legs (the UUID join key)."""
    index: dict[str, dict[str, Any]] = {}
    for r in rows:
        if str(r.get("series") or "").upper() != _QUALIFIER_SERIES:
            continue
        u = r.get("competitor_uuid")
        if u:
            index[u] = r
    return index


def _valid_game_events(games: list[dict[str, Any]], diag: dict | None) -> dict[str, dict[str, Any]]:
    """Group KXWCGAME rows by event into ``{event: {"parts": [2 team rows], "tie": tie row}}``, keeping
    only events with EXACTLY 2 participants + 1 structurally-identified tie (fail closed on 0/2 tie rows)."""
    events: dict[str, dict[str, Any]] = {}
    for r in games:
        ev = r.get("event_ticker") or ""
        if not ev:
            continue
        slot = events.setdefault(ev, {"parts": [], "tie": None, "bad": False})
        if wc_groups.is_tie_row(r):
            if slot["tie"] is not None:
                slot["bad"] = True          # two tie rows → malformed
            slot["tie"] = r
        else:
            slot["parts"].append(r)
    valid: dict[str, dict[str, Any]] = {}
    for ev, slot in events.items():
        if slot["bad"] or len(slot["parts"]) != 2 or slot["tie"] is None:
            _record(diag, "rejected", ev, "game support: expected exactly 2 teams + 1 tie")
            continue
        valid[ev] = slot
    return valid


def find_game_support_signals(rows: list[dict[str, Any]], *, strong_score_c: int,
                              qualifier_band_c: tuple[int, int],
                              _diag: dict | None = None) -> list[dict[str, Any]]:
    """One flagged finding per team whose 3-game ask-support score ≥ ``strong_score_c`` AND whose qualify
    YES ∈ ``qualifier_band_c``. Consumes ``df.to_dict("records")`` so it is NaN-safe."""
    rows = rows or []
    games = [r for r in rows if r.get("kind") == "game" and str(r.get("series") or "").upper() == _GAME_SERIES]
    if not games:
        return []                                   # inert until KXWCGAME lists
    valid = _valid_game_events(games, _diag)
    qual_index = _qualifier_index(rows)

    # team UUID → list of (event, win row, tie row)
    team_games: dict[str, list[tuple[str, dict, dict]]] = {}
    team_name: dict[str, str] = {}
    for ev, slot in valid.items():
        for p in slot["parts"]:
            u = p.get("competitor_uuid")
            if not u:
                continue
            team_games.setdefault(u, []).append((ev, p, slot["tie"]))
            team_name[u] = str(p.get("player") or "")

    lo, hi = qualifier_band_c
    out: list[dict[str, Any]] = []
    for uuid, gl in team_games.items():
        if len(gl) != _GAMES_PER_TEAM:
            _record(_diag, "rejected", gl[0][0], f"game support: team has {len(gl)} games (expected {_GAMES_PER_TEAM})")
            continue
        per_game: list[dict[str, Any]] = []
        firm = True
        for ev, win, tie in gl:
            w, d = _firm_ask_c(win), _firm_ask_c(tie)
            if w is None or d is None:
                _record(_diag, "not_price_proven", ev, "game support: missing firm win/draw ask")
                firm = False
                break
            per_game.append({"event": ev, "win_ask_c": w, "draw_ask_c": d, "score_c": 3 * w + d,
                             "win": win, "tie": tie})
        if not firm:
            continue
        total = sum(g["score_c"] for g in per_game)
        qrow = qual_index.get(uuid)
        if qrow is None:
            _record(_diag, "uuid_miss", gl[0][0], f"game support: no qualifier UUID match for {team_name.get(uuid)}")
            continue
        q = _firm_ask_c(qrow)
        if q is None:
            _record(_diag, "not_price_proven", "", "game support: qualifier not firm")
            continue
        if total < strong_score_c or not (lo <= q <= hi):
            _record(_diag, "eligible_non_firing", gl[0][0], "game support: below score / outside band")
            continue
        out.append(_build_finding(uuid, team_name.get(uuid, "this team"), qrow, per_game, total, q))
    out.sort(key=lambda f: (-(f["ask_support_score_total_c"]), f["opportunity_id"]))
    return out


def _build_finding(uuid: str, name: str, qrow: dict[str, Any], per_game: list[dict[str, Any]],
                   total: int, q_ask: int) -> dict[str, Any]:
    legs: list[dict[str, Any]] = []
    for g in per_game:
        legs.append({"side": "info", "contract": f"{name} game ({g['event']})",
                     "price_c": g["score_c"], "size": None, "ticker": g["win"].get("market_ticker", ""),
                     "url": g["win"].get("kalshi_url", ""), "player_key": uuid,
                     "text": f"{name}: win {g['win_ask_c']}¢ / draw {g['draw_ask_c']}¢ → support {g['score_c']}¢"})
    return {
        "check_type": GAME_SUPPORT_CHECK_TYPE,
        "relationship_type": "game_support_signal",
        "opportunity_id": data.opportunity_id(GAME_SUPPORT_CHECK_TYPE, uuid or name),
        "status": GAME_SUPPORT_SIGNAL,
        "bucket": "qualifier_setup",
        "tradable_now": "Diagnostic only",
        "series": qrow.get("series", _QUALIFIER_SERIES),
        "tournament": qrow.get("tournament", ""),
        "tour": qrow.get("tour", ""),
        "name": name,
        "participant_key": uuid,
        "participant_uuid": uuid,
        "qualifier_yes_ask_c": q_ask,
        "ask_support_score_total_c": total,
        "ask_support_score_per_game_c": round(total / _GAMES_PER_TEAM),
        "legs": legs, "n_legs": len(legs),
        "action_1_text": f"Ask-implied support score {total}¢ over 3 games (3·win+draw)",
        "action_2_text": f"{name} qualify YES @ {q_ask}¢ (in the moderate band)",
        "action_1_price_c": total, "action_2_price_c": q_ask,
        "ticker_1": (per_game[0]["win"].get("market_ticker") if per_game else ""),
        "ticker_2": qrow.get("market_ticker", ""),
        "url": qrow.get("kalshi_url", ""),
        "game_support_basis": GAME_SUPPORT_BASIS,
        "settlement_caveat": GAME_SUPPORT_BASIS,
        "detail": f"Ask-implied support score {total}¢ — heuristic, not expected points",
    }
