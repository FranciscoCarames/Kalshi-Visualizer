"""Pure, fail-closed helpers for the World Cup Qualifier Setups feature (no UI imports).

These are the join primitives the exact-order (#4) and game-support (#5) detectors depend on. They
are deliberately conservative: anything unexpected returns ``None`` / ``False`` rather than guessing,
because a wrong group/name/tie join would silently corrupt a diagnostic. Unit-tested offline in
``tests/test_wc_groups.py`` against captured fixtures.

Live-verified facts (2026-06-08) these encode:
  * Event-ticker shapes differ across the WC group series — ``KXWCGROUPQUAL-26B`` / ``KXWCGROUPWIN-26B``
    put the group letter AFTER the season token, while ``KXWCGROUPORDER-B26`` puts it BEFORE. Both
    resolve to the same group ``"B"``.
  * ``KXWCGROUPORDER`` custom-strike placement names carry stray newlines and full country names
    (``"\\nBosnia and Herzegovina\\n"``) and there is NO ``soccer_team`` UUID, so the join to
    ``KXWCGROUPQUAL`` must go through a symmetric name normalizer.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sports import SOCCER_TIE_UUID

# 2026 World Cup has 12 groups, A–L. Two ticker shapes (see module docstring); each is anchored on the
# 2-digit season token so a stray letter elsewhere in the ticker can't be mistaken for the group.
_GROUP_AFTER_SEASON = re.compile(r"-\d{2}([A-L])(?:-|$)")    # KXWCGROUPQUAL-26B / KXWCGROUPQUAL-26B-CAN
_GROUP_BEFORE_SEASON = re.compile(r"-([A-L])\d{2}(?:-|$)")   # KXWCGROUPORDER-B26 / KXWCGROUPORDER-B26-CANBIH...


def parse_wc_group_key(event_or_market_ticker: Any) -> str | None:
    """The group letter (``"A"``..``"L"``) for a WC group event/market ticker, or ``None``.

    Handles both ticker shapes and the per-market suffix. Fails closed (``None``) on anything that
    doesn't match exactly one shape — never a best-effort guess."""
    t = str(event_or_market_ticker or "").upper()
    if not t:
        return None
    after = _GROUP_AFTER_SEASON.search(t)
    before = _GROUP_BEFORE_SEASON.search(t)
    # Exactly one shape must match (they are mutually exclusive by construction: digits-then-letter vs
    # letter-then-digits). If both or neither match, the ticker is unexpected → fail closed.
    if bool(after) == bool(before):
        return None
    return (after or before).group(1)


def normalize_country_name(name: Any) -> str:
    """Canonical key for a team display name, robust to the stray-newline / accented variants Kalshi
    emits. Strips, collapses internal whitespace (incl. newlines), strips accents, casefolds. Empty
    string on falsy input (an empty key never matches a real team)."""
    s = str(name or "")
    # Decompose accents and drop the combining marks (é → e) so "Türkiye"/"Turkiye" key alike.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


def is_tie_row(row: dict[str, Any]) -> bool:
    """True for the draw outcome of a 3-way KXWCGAME, by STRUCTURED fields only — never the bare
    display string. Primary signal is ``participant_type == "tie"`` (set by ``data.build_contracts``
    via the soccer ``tie_fn``); falls back to the constant tie ``soccer_team`` UUID. Fails closed."""
    if str(row.get("participant_type") or "") == "tie":
        return True
    cs = row.get("custom_strike") or row.get("raw_custom_strike") or {}
    return isinstance(cs, dict) and cs.get("soccer_team") == SOCCER_TIE_UUID
