"""Sport abstraction for the multi-sport Kalshi engine.

One detection engine, swap data per sport. Each sport is a `SportConfig` holding the bits that vary —
series prefixes, a structured identity resolver, market classification (family + ladder node +
eligibility), the containment ladder, and labels. The engine (data.py / consistency.py) resolves the
sport from a series ticker / contract row and reads config off it; it never hardcodes a sport.

Dependency direction: this module imports only `config` + stdlib. `data.py` and `consistency.py` import
FROM here (never the reverse) — that keeps it import-cycle-free and independently testable.

Adding a sport = `register(SportConfig(...))`. Unknown series resolve to `UNKNOWN` (an explicit
unsupported sport), NEVER silently to tennis — so a foreign ticker is visibly unsupported, not mis-parsed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

import config

# ============================================================================================
# Structured results
# ============================================================================================


@dataclass(frozen=True)
class IdentityResult:
    """How a market row is keyed to a participant (player/team)."""
    participant_key: str        # stable key for grouping (UUID when available, else normalized name)
    display_name: str           # user-facing name (yes_sub_title verbatim)
    confidence: str             # "high" (stable id) | "low" (name fallback) | "none"
    source_field: str           # "competitor_uuid" | "name_fallback" | ""
    raw_value: str              # the raw id (or name) the key came from
    reason: str = ""            # human-readable explanation


@dataclass(frozen=True)
class IdentityResolver:
    """Resolve a participant identity from a market dict, sport-agnostically.

    Tries each dotted `candidate_path` (e.g. "custom_strike.tennis_competitor" /
    "custom_strike.basketball_team") for a stable id; falls back to the normalized display name
    (low confidence). Supports multiple candidate paths so a sport with more than one id field
    degrades gracefully.
    """
    candidate_paths: tuple[str, ...]
    id_label: str = "competitor"          # used in the high-confidence reason text
    display_field: str = "yes_sub_title"

    def resolve(self, market: dict[str, Any]) -> IdentityResult:
        name = str((market.get(self.display_field) or "")).strip()
        for path in self.candidate_paths:
            val = _dig(market, path)
            if val:
                return IdentityResult(
                    participant_key=str(val), display_name=name, confidence="high",
                    source_field="competitor_uuid", raw_value=str(val),
                    reason=f"keyed to stable {self.id_label} UUID {val}",
                )
        if name:
            return IdentityResult(
                participant_key=name.casefold(), display_name=name, confidence="low",
                source_field="name_fallback", raw_value=name,
                reason="no competitor UUID; keyed to normalized name (may drift/collide)",
            )
        return IdentityResult("", name, "none", "", "", "no competitor UUID and no name")


@dataclass(frozen=True)
class MarketClassification:
    """Structured classification of one market: its family, ladder placement, and eligibility."""
    family: str                          # "match"/"advance"/"winner"/"series"/"game"/"prop"/"other"/...
    stage: str                           # round/stage label ("Quarterfinal", "Finals", "" if none)
    stage_rank: int                      # progression sort key (0 if unknown)
    ladder_node: str | None              # the containment node this maps to, or None
    eligible_for_ladder_checks: bool     # may this market enter ladder comparisons?
    confidence: str                      # "high" | "low" | "none"
    reason: str                          # why it was (not) placed on the ladder

    @property
    def kind(self) -> str:
        """Back-compat legacy `kind` string (== family)."""
        return self.family


@dataclass(frozen=True)
class LadderSpec:
    """The containment ladder for a sport (broad → deep)."""
    node_order: tuple[str, ...]
    adjacent_pairs: tuple[tuple[str, str], ...]   # (child_deeper, parent_broader)
    match_stage_to_node: dict[str, str]           # head-to-head stage → node (win match ⇔ reach next)
    advance_stage_to_node: dict[str, str]         # reach-a-stage market stage → node


@dataclass(frozen=True)
class SportConfig:
    """Everything the engine needs to handle one sport. Pure data + a few small logic callables."""
    sport_id: str
    label: str
    emoji: str
    series_prefixes: tuple[str, ...]
    default_series: tuple[str, ...]
    winner_tickers: frozenset[str]
    identity: IdentityResolver
    ladder: LadderSpec
    category_labels: dict[str, str]
    round_patterns: tuple[tuple[str, str], ...]
    stage_rank: dict[str, int]
    ladder_families: frozenset[str]          # families that participate in the ladder
    match_family: str                        # the head-to-head family ("match"/"series")
    divisions: dict[str, list[str]]          # UI split (tennis: Tour; {} when none)
    division_label: str                      # "Tour" / ""
    # small per-sport logic (take cfg so they can read the data fields above)
    family_fn: Callable[["SportConfig", str], str]
    stage_fn: Callable[["SportConfig", str, dict], str]
    node_fn: Callable[["SportConfig", str, str], str | None]
    division_fn: Callable[["SportConfig", str], str]
    # Synthetic exact-score state bundles (optional; empty for sports without exact-score markets, so
    # adding a sport stays one register() call). `state_bundles` maps a verified format key to the
    # per-player expected scoreline set; `score_format_fn` resolves an event's (division, tournament)
    # to that key, or None when the format is unprovable (→ no bundle, never a guessed emit).
    state_bundles: dict[str, tuple[str, ...]] = field(default_factory=dict)
    score_format_fn: Callable[["SportConfig", str, str], str | None] | None = None

    # ---- convenience API (engine calls these) --------------------------------------------
    def family_of(self, series_ticker: str) -> str:
        return self.family_fn(self, series_ticker)

    def division_of(self, series_ticker: str) -> str:
        return self.division_fn(self, series_ticker)

    def score_format(self, division: str, tournament: str) -> str | None:
        """Verified best-of format key for an event (e.g. 'tennis_bo5'), or None when unprovable."""
        return self.score_format_fn(self, division, tournament) if self.score_format_fn else None

    def stage_of(self, family: str, market: dict[str, Any]) -> str:
        return self.stage_fn(self, family, market)

    def classify(self, series_ticker: str, market: dict[str, Any]) -> MarketClassification:
        fam = self.family_of(series_ticker)
        stage = self.stage_fn(self, fam, market)
        node = self.node_fn(self, fam, stage)
        eligible = fam in self.ladder_families
        if not eligible:
            conf = "none"
            reason = f"{self.label}: '{fam}' is not a laddered market — excluded from ladder checks"
        elif node is None and fam == self.match_family:
            conf = "high"
            reason = f"{fam} with unmapped stage '{stage or '?'}' — no tracked ladder node (unverifiable)"
        else:
            conf = "high"
            reason = f"{fam}" + (f" → {node}" if node else "")
        return MarketClassification(fam, stage, self.stage_rank.get(stage, 0), node, eligible, conf, reason)


# ============================================================================================
# Helpers
# ============================================================================================


def _dig(d: Any, path: str) -> Any:
    """Walk a dotted path into nested dicts (e.g. 'custom_strike.tennis_competitor')."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def extract_round(round_patterns: tuple[tuple[str, str], ...], *texts: Any) -> str:
    """First matching round label from `round_patterns` over the joined texts (most-specific first)."""
    blob = " ".join(str(t) for t in texts if t)
    for label, pattern in round_patterns:
        if re.search(pattern, blob, re.IGNORECASE):
            return label
    return ""


# ============================================================================================
# Registry + resolution
# ============================================================================================

_REGISTRY: dict[str, SportConfig] = {}


def register(cfg: SportConfig) -> SportConfig:
    _REGISTRY[cfg.sport_id] = cfg
    return cfg


def all_sports() -> list[SportConfig]:
    return list(_REGISTRY.values())


def get_sport(sport_id: str) -> SportConfig:
    return _REGISTRY.get(sport_id, UNKNOWN)


def sport_for_series(series_ticker: Any) -> SportConfig:
    """Resolve the sport that owns a series ticker, by prefix / winner-ticker membership.

    Returns `UNKNOWN` (an explicit unsupported sport) when nothing matches — NEVER a silent tennis
    default. (For unit-test rows that carry no series, the engine applies its own tennis back-compat
    where documented; this resolver itself never guesses.)
    """
    t = str(series_ticker or "").upper()
    if not t:
        return UNKNOWN
    for cfg in _REGISTRY.values():
        if t.startswith(cfg.series_prefixes) or t in cfg.winner_tickers:
            return cfg
    return UNKNOWN


# ============================================================================================
# UNKNOWN sport — explicit, unsupported (no global tennis default)
# ============================================================================================

_EMPTY_LADDER = LadderSpec((), (), {}, {})


def _unknown_family(cfg: SportConfig, t: str) -> str:
    return "other"          # legacy back-compat: an unrecognized series is "other"


UNKNOWN = SportConfig(
    sport_id="unknown", label="Unsupported", emoji="❓",
    series_prefixes=(), default_series=(), winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=()), ladder=_EMPTY_LADDER,
    category_labels={"other": "Other"}, round_patterns=(), stage_rank={},
    ladder_families=frozenset(), match_family="", divisions={}, division_label="",
    family_fn=_unknown_family,
    stage_fn=lambda cfg, fam, m: "",
    node_fn=lambda cfg, fam, stage: None,
    division_fn=lambda cfg, t: "",
)


# ============================================================================================
# TENNIS — registered from the current constants, verbatim behavior
# ============================================================================================

# Order matters: `extract_round` returns the FIRST match, so the more-specific rounds MUST precede the
# generic "Final". A hyphen is a word boundary, so a bare `\bfinal\b` would otherwise swallow
# "semi-final" / "quarter-final" and mis-label them "Final" — list Quarterfinal/Semifinal first.
_TENNIS_ROUND_PATTERNS = (
    ("Quarterfinal", r"\bquarter-?final(?:s)?\b"),
    ("Semifinal", r"\bsemi-?final(?:s)?\b"),
    ("Final", r"\bfinal\b"),
    ("Round of 16", r"\bround of 16\b|\bfourth round\b"),
    ("Round of 32", r"\bround of 32\b|\bthird round\b"),
    ("Round of 64", r"\bround of 64\b|\bsecond round\b"),
    ("Round of 128", r"\bround of 128\b|\bfirst round\b"),
)
_TENNIS_STAGE_RANK = {
    "Round of 128": 1, "Round of 64": 2, "Round of 32": 3, "Round of 16": 4,
    "Quarterfinal": 5, "Semifinal": 6, "Final": 7, "Champion": 8,
}
_TENNIS_CATEGORY = {
    "match": "Match result", "advance": "Stage advancement", "winner": "Tournament winner",
    "set_winner": "Set winner", "exact_score": "Exact score", "grand_slam": "Grand Slam (season)",
    "other": "Other",
}
_TENNIS_LADDER = LadderSpec(
    node_order=("Reach Semifinal", "Reach Final", "Win Tournament"),
    adjacent_pairs=(("Win Tournament", "Reach Final"), ("Reach Final", "Reach Semifinal")),
    match_stage_to_node={"Quarterfinal": "Reach Semifinal", "Semifinal": "Reach Final", "Final": "Win Tournament"},
    advance_stage_to_node={"Semifinal": "Reach Semifinal", "Final": "Reach Final"},
)
_WOMEN_WINNER_TICKERS = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}
_MEN_WINNER_TICKERS = {"KXFOMEN", "KXFOMENSINGLES", "KXFOPENMENSINGLE"}


def _tennis_family(cfg: SportConfig, series_ticker: str) -> str:
    """Order matters: winner tickers + EXACTMATCH/SETWINNER before the generic MATCH check."""
    t = (series_ticker or "").upper()
    if t in cfg.winner_tickers:
        return "winner"
    if "ADVANCE" in t:
        return "advance"
    if "EXACTMATCH" in t or "EXACTSCORE" in t:
        return "exact_score"
    if "SETWINNER" in t:
        return "set_winner"
    if "GRANDSLAM" in t:
        return "grand_slam"
    if "MATCH" in t:
        return "match"
    return "other"


def _tennis_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    return extract_round(cfg.round_patterns, market.get("title"), market.get("rules_primary"))


def _tennis_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Tournament"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)
    if family == "match":
        return cfg.ladder.match_stage_to_node.get(stage)
    return None


def _tennis_division(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t in _WOMEN_WINNER_TICKERS:
        return "WTA"
    if t in _MEN_WINNER_TICKERS:
        return "ATP"
    if t.startswith("KXWTA") or "WOMEN" in t:
        return "WTA"
    return "ATP"


# Match format = which exact-set-score states are possible for a player win. Only **men's Grand Slam
# singles** are best-of-5 ({3-0,3-1,3-2}); WTA and non-Slam ATP are best-of-3 ({2-0,2-1}). Gender comes
# from the division (ATP/WTA); Grand-Slam-ness from the tournament key. NOT keyed off ATP/WTA alone (ATP
# is bo3 outside the Slams). Verified live: French Open men's exact-score events carry 3 states/player.
_GRAND_SLAM_KEYS = ("australian open", "french open", "roland garros", "wimbledon", "us open")


def _tennis_score_format(cfg: SportConfig, division: str, tournament: str) -> str | None:
    t = (tournament or "").strip().lower()
    if not t or t.startswith("unknown"):
        return None  # tournament unprovable → no format → no bundle (never emit on a guess)
    if (division or "").upper() == "WTA":
        return "tennis_bo3"
    return "tennis_bo5" if any(k in t for k in _GRAND_SLAM_KEYS) else "tennis_bo3"


TENNIS = register(SportConfig(
    sport_id="tennis", label="Tennis", emoji="🎾",
    series_prefixes=tuple(config.TENNIS_SERIES_PREFIXES),
    default_series=tuple(config.DEFAULT_SERIES),
    winner_tickers=frozenset(config.FO_WINNER_TICKERS),
    identity=IdentityResolver(candidate_paths=("custom_strike.tennis_competitor",), id_label="tennis_competitor"),
    ladder=_TENNIS_LADDER,
    category_labels=_TENNIS_CATEGORY,
    round_patterns=_TENNIS_ROUND_PATTERNS,
    stage_rank=_TENNIS_STAGE_RANK,
    ladder_families=frozenset({"match", "advance", "winner"}),
    match_family="match",
    divisions={"Women": ["WTA"], "Men": ["ATP"], "Both": ["ATP", "WTA"]},
    division_label="Tour",
    family_fn=_tennis_family,
    stage_fn=_tennis_stage,
    node_fn=_tennis_node,
    division_fn=_tennis_division,
    state_bundles={"tennis_bo5": ("3-0", "3-1", "3-2"), "tennis_bo3": ("2-0", "2-1")},
    score_format_fn=_tennis_score_format,
))


# ============================================================================================
# NBA — additive config, grounded in the live discovery (2026-06-03). See the milestone note.
# ============================================================================================
#
# Containment ladder (broad → deep): Win Conference (KXNBAEAST/WEST = reach the Finals) ⊇
# Win Championship (KXNBA). Playoff series head-to-head (KXNBASERIES) is the match-alignment analog.
# Per-game (KXNBAGAME), spreads/totals, props, awards, draft → NOT laddered (ineligible).
# Team identity: custom_strike.basketball_team (stable UUID, shared across a team's series).

# Order matters: `extract_round` returns the FIRST match, so the conference rounds MUST precede the
# generic "Finals" — otherwise `\bfinals\b` swallows "Conference Finals" and (across the hyphen)
# "Conference Semi-finals". Conference Semifinals carries `semi-?finals?` to catch the hyphenated form.
_NBA_ROUND_PATTERNS = (
    ("Conference Finals", r"conference finals|\bconf\.? finals\b|\b[ew]cf\b"),
    ("Conference Semifinals", r"conference semi-?finals?|2nd round|second round|\br2\b"),
    ("Finals", r"\bnba finals\b|\bthe finals\b|championship series|\bfinals\b"),
    ("First Round", r"1st round|first round|\br1\b"),
)
_NBA_STAGE_RANK = {
    "First Round": 1, "Conference Semifinals": 2, "Conference Finals": 3,
    "Finals": 4, "Conference": 5, "Champion": 6,
}
_NBA_CATEGORY = {
    "winner": "Championship", "advance": "Advancement (reach a stage)", "match": "Playoff series",
    "game": "Game (not laddered)", "other": "Other",
}
# Containment ladder (broad → deep): Reach Playoffs ⊇ Win Conference (= reach the Finals) ⊇ Win
# Championship. To win your conference you must be in the playoffs; to win the title you must win your
# conference. The advance-market "stage" is derived from the series (NBA has no title round), so multiple
# advance series map to different rungs via advance_stage_to_node.
_NBA_LADDER = LadderSpec(
    node_order=("Reach Playoffs", "Win Conference", "Win Championship"),
    adjacent_pairs=(("Win Championship", "Win Conference"), ("Win Conference", "Reach Playoffs")),
    match_stage_to_node={"Finals": "Win Championship", "Conference Finals": "Win Conference"},
    advance_stage_to_node={"Playoffs": "Reach Playoffs", "Conference": "Win Conference"},
)


def _nba_family(cfg: SportConfig, series_ticker: str) -> str:
    """NBA market family is determined by the SERIES (not a title-extracted stage)."""
    t = (series_ticker or "").upper()
    if t == "KXNBA":
        return "winner"                            # win the championship
    if t in ("KXNBAEAST", "KXNBAWEST", "KXNBAPLAYOFF"):
        return "advance"                           # reach-a-stage (conference / playoffs)
    if t == "KXNBASERIES":
        return "match"                             # playoff series head-to-head
    if t == "KXNBAGAME":
        return "game"                              # single game — NOT a series/ladder outcome
    return "other"                                 # spreads/totals/props/awards/draft/etc.


def _nba_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # NBA has no title round, so the advance "stage" comes from which series the market is in.
        return "Playoffs" if (market.get("ticker") or "").upper().startswith("KXNBAPLAYOFF") else "Conference"
    if family == "match":
        return extract_round(cfg.round_patterns, market.get("title"), market.get("rules_primary"))
    return ""


def _nba_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Championship"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)   # Playoffs / Conference
    if family == "match":
        return cfg.ladder.match_stage_to_node.get(stage)     # Finals / Conference Finals only
    return None


def _nba_division(cfg: SportConfig, series_ticker: str) -> str:
    return ""   # NBA has no ATP/WTA-style division (conference filter is a future UI nicety)


NBA = register(SportConfig(
    sport_id="nba", label="NBA", emoji="🏀",
    series_prefixes=("KXNBA",),
    default_series=("KXNBA", "KXNBAEAST", "KXNBAWEST", "KXNBAPLAYOFF", "KXNBASERIES", "KXNBAGAME"),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.basketball_team",), id_label="basketball_team"),
    ladder=_NBA_LADDER,
    category_labels=_NBA_CATEGORY,
    round_patterns=_NBA_ROUND_PATTERNS,
    stage_rank=_NBA_STAGE_RANK,
    ladder_families=frozenset({"match", "advance", "winner"}),
    match_family="match",
    divisions={},
    division_label="",
    family_fn=_nba_family,
    stage_fn=_nba_stage,
    node_fn=_nba_node,
    division_fn=_nba_division,
))


# ============================================================================================
# WNBA — third sport, grounded in live discovery (2026-06-03). Same team identity as the NBA.
# ============================================================================================
#
# WNBA's modern playoffs are a SINGLE bracket (no conference final — KXWNBAEAST/WEST are defunct/empty),
# so the clean, format-agnostic ladder is the reach-stage chain (settlement rules literally say
# "qualifies for the Playoffs / Semifinals / Finals"):
#   Reach Playoffs (KXWNBAPLAYOFF) ⊇ Reach Semifinals (KXWNBASEMIFINAL) ⊇ Reach Finals (KXWNBAFINAL)
#   ⊇ Win Championship (KXWNBA).
# KXWNBASERIES = playoff series head-to-head; KXWNBAGAME/props = ineligible. No conference rung.

# Order matters: Semifinals MUST precede the generic "Finals" — a hyphen is a word boundary, so a bare
# `\bfinals\b` would otherwise swallow "semi-finals" and mis-label it "Finals".
_WNBA_ROUND_PATTERNS = (
    ("Semifinals", r"\bsemi-?finals?\b"),
    ("Finals", r"\bfinals\b"),
    ("First Round", r"\b1st round\b|\bfirst round\b|\bround 1\b|\br1\b"),
)
_WNBA_STAGE_RANK = {"Playoffs": 1, "First Round": 2, "Semifinals": 3, "Finals": 4, "Champion": 5}
_WNBA_CATEGORY = {
    "winner": "Championship", "advance": "Advancement (reach a stage)", "match": "Playoff series",
    "game": "Game (not laddered)", "other": "Other",
}
_WNBA_LADDER = LadderSpec(
    node_order=("Reach Playoffs", "Reach Semifinals", "Reach Finals", "Win Championship"),
    adjacent_pairs=(
        ("Win Championship", "Reach Finals"),
        ("Reach Finals", "Reach Semifinals"),
        ("Reach Semifinals", "Reach Playoffs"),
    ),
    # series head-to-head ≡ a reach node (win the Finals series ⇔ win the title, etc.)
    match_stage_to_node={"Finals": "Win Championship", "Semifinals": "Reach Finals",
                         "First Round": "Reach Semifinals"},
    # reach-a-stage advance markets → their node (stage derived from the series ticker below)
    advance_stage_to_node={"Playoffs": "Reach Playoffs", "Semifinals": "Reach Semifinals",
                           "Finals": "Reach Finals"},
)


def _wnba_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t == "KXWNBA":
        return "winner"                                              # win the championship
    if t in ("KXWNBAPLAYOFF", "KXWNBASEMIFINAL", "KXWNBAFINAL"):
        return "advance"                                             # reach a stage (qualifiers)
    if t == "KXWNBASERIES":
        return "match"                                               # playoff series head-to-head
    if t == "KXWNBAGAME":
        return "game"                                                # single game — NOT laddered
    return "other"                                                   # props/awards/conference(defunct)/etc.


def _wnba_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # The advance "stage" comes from which qualifier series the market is in.
        tk = (market.get("ticker") or "").upper()
        if tk.startswith("KXWNBAPLAYOFF"):
            return "Playoffs"
        if tk.startswith("KXWNBASEMIFINAL"):
            return "Semifinals"
        if tk.startswith("KXWNBAFINAL"):
            return "Finals"
        return ""
    if family == "match":
        return extract_round(cfg.round_patterns, market.get("title"), market.get("rules_primary"))
    return ""


def _wnba_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Championship"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)
    if family == "match":
        return cfg.ladder.match_stage_to_node.get(stage)
    return None


def _wnba_division(cfg: SportConfig, series_ticker: str) -> str:
    return ""   # single bracket — no division concept


WNBA = register(SportConfig(
    sport_id="wnba", label="WNBA", emoji="🏀",
    series_prefixes=("KXWNBA",),   # no collision: "KXWNBA…" never prefix-matches NBA's "KXNBA…"
    default_series=("KXWNBA", "KXWNBAPLAYOFF", "KXWNBASEMIFINAL", "KXWNBAFINAL", "KXWNBASERIES", "KXWNBAGAME"),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.basketball_team",), id_label="basketball_team"),
    ladder=_WNBA_LADDER,
    category_labels=_WNBA_CATEGORY,
    round_patterns=_WNBA_ROUND_PATTERNS,
    stage_rank=_WNBA_STAGE_RANK,
    ladder_families=frozenset({"match", "advance", "winner"}),
    match_family="match",
    divisions={},
    division_label="",
    family_fn=_wnba_family,
    stage_fn=_wnba_stage,
    node_fn=_wnba_node,
    division_fn=_wnba_division,
))
