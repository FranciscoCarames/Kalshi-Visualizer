"""Capture sanitized offline fixtures for the World Cup Qualifier Setups feature.

Run from an UNTHROTTLED network (the Kalshi market-data API is read-only, no auth):

    python scripts/probe_wc_qualifier_setups.py            # writes tests/fixtures/wc_qualifier/
    python scripts/probe_wc_qualifier_setups.py --group C  # a different group

It fetches, for ONE group, the four series the feature depends on and trims each event to the
fields ``data.build_contracts`` consumes plus prices/sizes — matching the existing
``tests/fixtures/soccer`` convention so the PR4/PR5 detector tests can run fully offline.

Discovery facts this script documents (verified live 2026-06-08; NOT in the public Kalshi docs):
  * ``with_nested_markets=true`` is MANDATORY — ``/events?series_ticker=KXWCGAME`` returns 0 without
    it but 72 with it (``kalshi_client.get_events`` already passes it).
  * ``KXWCGROUPORDER`` markets carry the four placement TEAM NAMES in ``custom_strike``
    (``1st Place Team`` … ``4th Place Team``, with stray newlines) and have NO ``soccer_team`` UUID,
    so the join to ``KXWCGROUPQUAL`` is by normalized display name within the same group.
  * ``KXWCGROUPQUAL`` / ``KXWCGROUPWIN`` / ``KXWCGAME`` carry the stable ``soccer_team`` UUID.

This script writes fixtures only; it adds no product behaviour.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kalshi_client  # noqa: E402

FIX_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "wc_qualifier"

# Fields build_contracts reads + the prices/sizes the detectors need. Anything else is dropped.
_MARKET_KEEP = (
    "ticker", "yes_sub_title", "strike_type", "custom_strike", "status", "title",
    "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "last_price_dollars",
    "yes_bid_size_fp", "yes_ask_size_fp", "volume_fp", "open_interest_fp", "rules_primary",
)
_EVENT_KEEP = ("event_ticker", "title", "mutually_exclusive", "competition_scope", "product_metadata")


def _trim_market(m: dict) -> dict:
    return {k: m[k] for k in _MARKET_KEEP if k in m}


def _trim_event(ev: dict, note: str) -> dict:
    out = {"_fixture_meta": {"captured": "2026-06-08", "ticker": ev.get("event_ticker"),
                             "source": "probe_wc_qualifier_setups.py live probe", "note": note}}
    for k in _EVENT_KEEP:
        if k in ev:
            out[k] = ev[k]
    out["markets"] = [_trim_market(m) for m in ev.get("markets", [])]
    return out


def _pick(events: list[dict], *, suffix: str) -> dict | None:
    """The event whose ticker ends with `suffix` (e.g. '-26B' or '-B26')."""
    for ev in events:
        if str(ev.get("event_ticker", "")).endswith(suffix):
            return ev
    return None


def _team_names(ev: dict) -> set[str]:
    names = set()
    for m in ev.get("markets", []):
        sub = str(m.get("yes_sub_title") or "").strip()
        if sub and sub.lower() != "tie":
            names.add(sub.lower())
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="B", help="group letter (default B: SUI/QAT/BIH/CAN)")
    args = ap.parse_args()
    g = args.group.upper()
    FIX_DIR.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    def _save(name: str, payload: dict) -> None:
        (FIX_DIR / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(name)

    # Group qualifiers (4) — soccer_team UUID + name. Event key shape: KXWCGROUPQUAL-26<G>.
    qual = _pick(kalshi_client.get_events("KXWCGROUPQUAL"), suffix=f"-26{g}")
    if qual:
        _save(f"KXWCGROUPQUAL-26{g}.json",
              _trim_event(qual, f"Group {g} qualifiers (Reach RO32); soccer_team UUID; 4 teams"))
    # Group winners (4).
    gw = _pick(kalshi_client.get_events("KXWCGROUPWIN"), suffix=f"-26{g}")
    if gw:
        _save(f"KXWCGROUPWIN-26{g}.json", _trim_event(gw, f"Group {g} 'win the group' leaf; 4 teams"))
    # Exact order (24) — event key shape: KXWCGROUPORDER-<G>26. custom_strike = 4 placement NAMES, no UUID.
    order = _pick(kalshi_client.get_events("KXWCGROUPORDER"), suffix=f"-{g}26")
    if order:
        _save(f"KXWCGROUPORDER-{g}26.json",
              _trim_event(order, f"Group {g} exact standings; mutually_exclusive=True; 24 orderings; "
                                 "custom_strike carries 1st-4th place TEAM NAMES (stray \\n), NO soccer_team UUID"))

    # Games (3-way) — date-keyed tickers, NOT group-lettered. Keep every game played among this group's
    # four teams (a round-robin → up to 6). Needs the qualifier event for the team-name set.
    if qual:
        group_team_names = _team_names(qual)
        games = kalshi_client.get_events("KXWCGAME")
        saved_games = 0
        for ev in games:
            names = _team_names(ev)
            # A group game: both non-tie participants belong to this group's four teams.
            if names and names <= group_team_names and len(names) == 2:
                _save(f"{ev.get('event_ticker')}.json",
                      _trim_event(ev, f"Group {g} 3-way game (Home/Away/Tie); soccer_team UUID per side"))
                saved_games += 1
        if saved_games == 0:
            print("WARN: no group games matched — capture skipped (games may be unlisted)", file=sys.stderr)

    print(f"wrote {len(written)} fixtures to {FIX_DIR}:")
    for n in sorted(written):
        print("  ", n)
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
