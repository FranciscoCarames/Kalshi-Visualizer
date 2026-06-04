"""Synthetic exact-score / state-bundle discrepancy detector — parsing + format layer (Stage m5).

A synthetic bundle replicates a player's "wins / advances" outcome from the MECE set of exact-set-score
contracts (e.g. men's best-of-5 → {3-0, 3-1, 3-2}) and prices it against a broader hedge (the match-winner
or reach-next-round market). When the bundle and hedge are mispriced it is a **gross pricing discrepancy**
— never riskless: on a retirement/no-ball-played the exact-score legs resolve to Fair Market Price while the
hedge settles cleanly (verified live), so every finding carries a settlement caveat.

This module is built in two PRs:
  * **Task 2 (this PR):** the pure, offline-testable parsing + format layer — `parse_scoreline` and the
    format-gated `expected_states`. No detection yet.
  * **Task 3a (next PR):** `find_synthetic_bundles` — grouping, completeness/rule gates, both directions.

NO streamlit / pandas imports, so it stays independently testable. Exact-score data shape (verified live,
French Open 2026): `custom_strike = {"Set Score": "3-0", "tennis_competitor": "<uuid>"}`.
"""
from __future__ import annotations

import re
from typing import Any

# A set score is "<sets won by winner>-<sets won by loser>", each a single digit (0–3 in practice).
_SCORELINE_RE = re.compile(r"\b([0-9])\s*-\s*([0-9])\b")


def parse_scoreline(row: dict[str, Any]) -> str | None:
    """The exact-set-score state for one market, normalized to ``"<w>-<l>"`` (e.g. ``"3-0"``), or None.

    Primary source is the **structured** ``custom_strike["Set Score"]`` (stamped onto the row as
    ``raw_custom_strike`` by ``data.build_contracts`` — verified live). Falls back to a regex over the
    display subtitle ("Jakub Mensik wins 3-0") so a market missing the strike field still parses.
    """
    cs = row.get("raw_custom_strike")
    raw = cs.get("Set Score") if isinstance(cs, dict) else None
    if not raw:
        for text in (row.get("yes_sub_title"), row.get("player_name_raw"), row.get("contract")):
            if text:
                m = _SCORELINE_RE.search(str(text))
                if m:
                    return f"{m.group(1)}-{m.group(2)}"
        return None
    m = _SCORELINE_RE.search(str(raw))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def expected_states(cfg: Any, division: str, tournament: str) -> tuple[str, ...] | None:
    """The per-player **expected** exact-score set for an event, or None when the format is unprovable.

    The format is resolved from a verified *independent* signal (``division`` + ``tournament`` via the
    sport's ``score_format`` resolver), NEVER from the discovered markets — otherwise the downstream
    completeness check (found == expected) would be circular. A ``None`` here means "do not emit".
    """
    fmt = cfg.score_format(division, tournament)
    return cfg.state_bundles.get(fmt) if fmt else None
