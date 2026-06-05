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
    # Optional per-VALUE validator: when set, a found candidate value is "high" confidence only if it passes
    # (e.g. UUID-shaped); a value that fails is still used as the key but marked "low" (collision-prone).
    # Default None → any candidate hit is high (byte-for-byte the existing behavior for all 7 sports). Needed
    # because some fields (e.g. motorsport `custom_strike.Participant`) can be a plain NAME, not a stable id.
    id_validator: Callable[[Any], bool] | None = None

    def resolve(self, market: dict[str, Any]) -> IdentityResult:
        name = str((market.get(self.display_field) or "")).strip()
        for path in self.candidate_paths:
            val = _dig(market, path)
            if val:
                if self.id_validator is not None and not self.id_validator(val):
                    # Value present but not a stable id (e.g. a team NAME): key on it, flag low confidence.
                    return IdentityResult(
                        participant_key=str(val), display_name=name, confidence="low",
                        source_field="id_unverified", raw_value=str(val),
                        reason=f"{self.id_label} value {val!r} is not id-shaped; keyed but may drift/collide",
                    )
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
    # Exact ticker ownership (optional). When non-empty, these tickers resolve to THIS sport BEFORE any
    # prefix/winner match (exact is the most specific signal). Lets a sport own specific tickers without a
    # broad prefix that would swallow unrelated series. Empty for prefix-owned sports -> no behavior change.
    exact_series: frozenset[str] = field(default_factory=frozenset)
    # Optional "non-participant outcome" detector (e.g. soccer's Tie/draw market). Returns True for a
    # market that is NOT a real competitor; build_contracts then gives it a per-event synthetic key
    # (never selectable, never merges across events). None (default) → every outcome is a participant.
    tie_fn: Callable[["SportConfig", dict], bool] | None = None
    # Human-readable label for the "winner" family. The default suits tennis/golf/soccer (the event IS a
    # tournament); NBA/WNBA/MLB override with their championship wording (see data._contract_label).
    winner_label: str = "Win the tournament"
    # ---- Motorsport-shaped adapter hooks (all DEFAULTED → byte-for-byte no-op for existing sports) ------
    # Families that form a one-winner MECE FIELD (overround-only dutch book via dutchbook._detect_field).
    # Default {"winner"} preserves every existing sport; a field sport can add pole/fastest_lap/constructor/
    # team/race_winner so those one-winner fields are detected too.
    field_families: frozenset[str] = field(default_factory=lambda: frozenset({"winner"}))
    # Optional per-sport grouping key, computed ONCE PER EVENT (data.tournament_of). Returns (key, source)
    # or None to fall back to the default competition-based key. Lets a sport build an event-instance key
    # (e.g. motorsport: competition + race/session + season) instead of the broad competition string.
    tournament_key_fn: Callable[["SportConfig", dict], tuple[str, str] | None] | None = None
    # Optional per-GROUP ladder selector (consistency.build_checks). Returns the LadderSpec for THIS group's
    # rows (e.g. motorsport: the competition-specific ladder) so a sport with several disjoint per-competition
    # ladders never emits cross-competition MISSING_LAYER noise. Default None → the static cfg.ladder.
    ladder_fn: Callable[["SportConfig", list], "LadderSpec"] | None = None
    # Optional role tag derived from the CLASSIFIED family (NOT the identity path — an F1 Top Constructor
    # shares the driver UUID path). Returns a non-empty role to namespace player_key as "role:key" so a
    # driver and a same-named team never merge in (player_key, tournament) grouping. Default None → no tag.
    role_fn: Callable[["SportConfig", str], str] | None = None

    # ---- convenience API (engine calls these) --------------------------------------------
    def family_of(self, series_ticker: str) -> str:
        return self.family_fn(self, series_ticker)

    def ladder_for(self, rows: list) -> "LadderSpec":
        """The containment ladder for a specific group's rows — per-group when ``ladder_fn`` is set
        (e.g. motorsport's per-competition ladders), else the static ``cfg.ladder`` (all existing sports)."""
        return self.ladder_fn(self, rows) if self.ladder_fn else self.ladder

    def tournament_key_of(self, event: dict[str, Any]) -> tuple[str, str] | None:
        """Sport-specific event-instance grouping key, or None to use the default competition path."""
        return self.tournament_key_fn(self, event) if self.tournament_key_fn else None

    def role_of(self, family: str) -> str:
        """Participant-role tag for ``family`` (namespaces player_key), or '' when the sport has none."""
        return self.role_fn(self, family) if self.role_fn else ""

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
    """Resolve the sport that owns a series ticker, by exact-ticker then prefix / winner-ticker membership.

    Returns `UNKNOWN` (an explicit unsupported sport) when nothing matches — NEVER a silent tennis
    default. (For unit-test rows that carry no series, the engine applies its own tennis back-compat
    where documented; this resolver itself never guesses.)
    """
    t = str(series_ticker or "").upper()
    if not t:
        return UNKNOWN
    # Pass 1: exact ownership is the most specific signal — it wins regardless of registry order, so a
    # future sport's broad prefix can never shadow another sport's exact ticker.
    for cfg in _REGISTRY.values():
        if t in cfg.exact_series:
            return cfg
    # Pass 2: existing prefix / winner-ticker ownership.
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
    winner_label="Win the Championship",
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
    winner_label="Win the Championship",
))


# --- Golf (5th sport): finishing-position containment ladder; exact-series ownership; no head-to-head ---
# Top 20 ⊇ Top 10 ⊇ Top 5 ⊇ Win Tournament. "Simple" placement contracts only. Props, round-finishers
# (KXPGAR1TOP5…), and H2H share the golf_competitor UUID + competition string, so golf owns EXACTLY its
# four tickers via exact_series; everything else resolves to UNKNOWN (the false-positive guard).
# match_family="" → golf yields no dutch books. Step-0 live discovery confirmed every value (see the kss
# research-gates note); competition strings confirmed on 2 tournaments — extend to ≥3 before fully trusting.
_GOLF_STAGE_RANK = {"Top 20": 1, "Top 10": 2, "Top 5": 3, "Champion": 4}
_GOLF_CATEGORY = {"advance": "Finish position", "winner": "Tournament winner", "other": "Other"}
_GOLF_EXACT = frozenset({"KXPGATOP20", "KXPGATOP10", "KXPGATOP5", "KXPGATOUR"})
_GOLF_LADDER = LadderSpec(
    node_order=("Top 20", "Top 10", "Top 5", "Win Tournament"),
    adjacent_pairs=(("Win Tournament", "Top 5"), ("Top 5", "Top 10"), ("Top 10", "Top 20")),
    match_stage_to_node={},                    # no head-to-head
    advance_stage_to_node={"Top 20": "Top 20", "Top 10": "Top 10", "Top 5": "Top 5"},
)


def _golf_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t == "KXPGATOUR":
        return "winner"                                              # win the tournament
    if t in ("KXPGATOP5", "KXPGATOP10", "KXPGATOP20"):
        return "advance"                                             # finish within Top N (incl. ties)
    return "other"                                                   # defensive — golf owns only the four


def _golf_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # The rung lives in the SERIES (the market ticker), not the title (NBA/WNBA-style). No prefix
        # collision among 5/10/20: "KXPGATOP10"/"KXPGATOP20" never start with "KXPGATOP5".
        tk = (market.get("ticker") or "").upper()
        if tk.startswith("KXPGATOP5"):
            return "Top 5"
        if tk.startswith("KXPGATOP10"):
            return "Top 10"
        if tk.startswith("KXPGATOP20"):
            return "Top 20"
    return ""


def _golf_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Tournament"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)
    return None


def _golf_division(cfg: SportConfig, series_ticker: str) -> str:
    return ""   # no tour split (one coherent rung set per tournament)


GOLF = register(SportConfig(
    sport_id="golf", label="Golf", emoji="⛳",
    series_prefixes=(), default_series=tuple(sorted(_GOLF_EXACT)),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.golf_competitor",), id_label="golf_competitor"),
    ladder=_GOLF_LADDER,
    category_labels=_GOLF_CATEGORY,
    round_patterns=(),
    stage_rank=_GOLF_STAGE_RANK,
    ladder_families=frozenset({"advance", "winner"}),
    match_family="",                           # no head-to-head → no dutch books
    divisions={},
    division_label="",
    family_fn=_golf_family,
    stage_fn=_golf_stage,
    node_fn=_golf_node,
    division_fn=_golf_division,
    exact_series=_GOLF_EXACT,
))


# --- Soccer (6th sport): 2026 World Cup ---------------------------------------------------------------
# Owns KXWCGAME (3-way group game Home/Away/Tie — `game` family, the n-outcome dutch book) + KXWCROUND
# (per-team reach-stage — `advance` ladder) via exact_series. The Tie market reuses a CONSTANT soccer_team
# UUID across all games, so it's a non-participant draw leg with a per-event synthetic key (tie_fn). No
# head-to-head series (match_family=""). Values confirmed live (kss research-gates note, 2026-06-04).
SOCCER_TIE_UUID = "111193d4-9b1f-4bd8-ab7c-9de252737f05"
_SOCCER_EXACT = frozenset({"KXWCGAME", "KXWCROUND"})
_SOCCER_CATEGORY = {"game": "Match (3-way)", "advance": "Stage advancement",
                    "winner": "Tournament winner", "other": "Other"}
_SOCCER_STAGE_RANK = {"Round of 16": 1, "Quarterfinals": 2, "Semifinals": 3, "Finals": 4}
_SOCCER_LADDER = LadderSpec(
    node_order=("Reach Round of 16", "Reach Quarterfinals", "Reach Semifinals", "Reach Finals"),
    adjacent_pairs=(("Reach Finals", "Reach Semifinals"),
                    ("Reach Semifinals", "Reach Quarterfinals"),
                    ("Reach Quarterfinals", "Reach Round of 16")),
    match_stage_to_node={},                    # no head-to-head
    advance_stage_to_node={"Round of 16": "Reach Round of 16", "Quarterfinals": "Reach Quarterfinals",
                           "Semifinals": "Reach Semifinals", "Finals": "Reach Finals"},
)


def _soccer_family(cfg, series_ticker):
    t = (series_ticker or "").upper()
    if t == "KXWCGAME":
        return "game"                                                # 3-way group game (n-outcome dutch book)
    if t == "KXWCROUND":
        return "advance"                                             # per-team reach-stage
    return "other"


def _soccer_stage(cfg, family, market):
    if family != "advance":
        return ""
    # The round lives in the market ticker segment (e.g. KXWCROUND-26RO16-PAR) and/or the title. Check
    # most-specific first so "Semifinals"/"Quarterfinals" never collapse to "Finals".
    blob = ((market.get("ticker") or "") + " " + (market.get("title") or "")).upper()
    if "RO16" in blob or "ROUND OF 16" in blob:
        return "Round of 16"
    if "QUAR" in blob:
        return "Quarterfinals"
    if "SEMI" in blob:
        return "Semifinals"
    if "FINAL" in blob:
        return "Finals"
    return ""


def _soccer_node(cfg, family, stage):
    if family == "winner":
        return "Win Tournament"                                      # declared for the future outright series
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)
    return None                                                      # game is dutch-only, not laddered


def _soccer_division(cfg, series_ticker):
    return ""


def _soccer_tie(cfg, market):
    """True for the soccer draw outcome — the constant Tie UUID or a 'Tie' display title."""
    cs = market.get("custom_strike") or {}
    return cs.get("soccer_team") == SOCCER_TIE_UUID or \
        str(market.get("yes_sub_title") or "").strip().lower() == "tie"


SOCCER = register(SportConfig(
    sport_id="soccer", label="Soccer (World Cup)", emoji="⚽",
    series_prefixes=(), default_series=tuple(sorted(_SOCCER_EXACT)),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.soccer_team",), id_label="soccer_team"),
    ladder=_SOCCER_LADDER,
    category_labels=_SOCCER_CATEGORY,
    round_patterns=(),
    stage_rank=_SOCCER_STAGE_RANK,
    ladder_families=frozenset({"advance", "winner"}),
    match_family="",                           # no 2-way head-to-head; the 3-way game rides the "game" family
    divisions={},
    division_label="",
    family_fn=_soccer_family,
    stage_fn=_soccer_stage,
    node_fn=_soccer_node,
    division_fn=_soccer_division,
    exact_series=_SOCCER_EXACT,
    tie_fn=_soccer_tie,
))


# --- MLB (7th sport): NBA-shape futures ladder + per-game dutch books ---------------------------------
# Futures map onto Reach Playoffs (KXMLBPLAYOFFS, a many-Yes qualifier reach-market) ⊇ Win League /
# AL+NL pennant (KXMLBAL/KXMLBNL) ⊇ Win World Series (KXMLB). KXMLBGAME is a 2-outcome single game →
# "game" family (dutch-book eligible; inherits the per-game settlement_caveat). Identity = the stable
# custom_strike.baseball_team UUID; grouping rides event-level competition="Pro Baseball". The "KXMLB"
# prefix only FINDS baseball-like series — the family_fn allow-list defines MLB's in-scope markets, so the
# ~110 KXMLB* props/awards/division series resolve to "other" (never laddered, not fetched in the normal
# view). KXMLBSERIES is excluded: a regular-season series can tie 2-2, so 2 markets are NOT MECE.
_MLB_STAGE_RANK = {"Playoffs": 1, "League": 2, "Champion": 3}
_MLB_CATEGORY = {
    "winner": "World Series", "advance": "Advancement (reach a stage)", "match": "Playoff series",
    "game": "Game (not laddered)", "other": "Other",
}
_MLB_LADDER = LadderSpec(
    node_order=("Reach Playoffs", "Win League", "Win World Series"),
    adjacent_pairs=(("Win World Series", "Win League"), ("Win League", "Reach Playoffs")),
    match_stage_to_node={},                    # no head-to-head ladder rung (KXMLBSERIES excluded)
    advance_stage_to_node={"Playoffs": "Reach Playoffs", "League": "Win League"},
)


def _mlb_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t == "KXMLB":
        return "winner"                                              # win the World Series
    if t == "KXMLBPLAYOFFS":
        return "advance"                                             # reach the playoffs (qualifier field)
    if t in ("KXMLBAL", "KXMLBNL"):
        return "advance"                                             # win the AL/NL pennant (= reach the WS)
    if t == "KXMLBGAME":
        return "game"                                                # single game — 2-outcome dutch book
    return "other"                                                   # KXMLBSERIES, KXMLBWS, divisions, props


def _mlb_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # The rung comes from which advance series the market is in (NBA-style; MLB has no title round).
        tk = (market.get("ticker") or "").upper()
        if tk.startswith("KXMLBPLAYOFFS"):
            return "Playoffs"
        if tk.startswith(("KXMLBAL", "KXMLBNL")):
            return "League"
        return ""   # no ticker evidence → unmapped, NOT a false "League" guess
    return ""


def _mlb_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win World Series"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)
    return None


MLB = register(SportConfig(
    sport_id="mlb", label="MLB", emoji="⚾",
    series_prefixes=("KXMLB",),
    default_series=("KXMLB", "KXMLBAL", "KXMLBNL", "KXMLBPLAYOFFS", "KXMLBGAME"),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.baseball_team",), id_label="baseball_team"),
    ladder=_MLB_LADDER,
    category_labels=_MLB_CATEGORY,
    round_patterns=(),
    stage_rank=_MLB_STAGE_RANK,
    ladder_families=frozenset({"advance", "winner"}),
    match_family="",                           # no 2-way head-to-head; KXMLBGAME rides the "game" family
    divisions={},
    division_label="",
    family_fn=_mlb_family,
    stage_fn=_mlb_stage,
    node_fn=_mlb_node,
    division_fn=lambda cfg, t: "",
    winner_label="Win the World Series",
))


# --- NHL (8th sport): NBA-shape futures ladder + playoff-series/per-game dutch books ------------------
# Futures map onto Reach Playoffs (KXNHLPLAYOFF, 32-team qualifier field) ⊇ Win Conference (KXNHLEAST/
# KXNHLWEST) ⊇ Win Championship / Stanley Cup (KXNHL). KXNHLSERIES is a 2-market playoff series ("match"
# family) and KXNHLGAME a 2-market single game ("game" family) — both dutch-book eligible; the game
# inherits the per-game settlement_caveat. Identity = the stable custom_strike.hockey_team UUID. The
# "KXNHL" prefix only FINDS series — family_fn defines scope, so KXNHL* props/awards resolve to "other"
# (never laddered; discovered but filtered out of fetch by non_other_families). Live data carries only
# "1st/2nd Round" KXNHLSERIES wording (no Conference-Final/Stanley-Cup-Final series), so series rounds map
# to NO ladder rung today → match-alignment is safely absent (UNKNOWN_RELATIONSHIP); NHL's value is the
# advance+winner ladder + the series/game dutch books.
_NHL_ROUND_PATTERNS = (
    # Specific finals guards FIRST (best-effort — not present in current data, where the championship is the
    # KXNHL field, but harmless if such SERIES text ever appears). No bare \bfinals?\b fallback; the round
    # text is read from title + rules_primary, never a ticker suffix (the suffix grammar is "Rn").
    ("Stanley Cup Final", r"stanley cup final(?:s)?"),
    ("Conference Finals", r"conference final(?:s)?|\b[ew]cf\b"),
    ("First Round", r"\b1st round\b|\bfirst round\b|\bround 1\b"),
    ("Second Round", r"\b2nd round\b|\bsecond round\b|\bround 2\b"),
    ("Third Round", r"\b3rd round\b|\bthird round\b|\bround 3\b"),
)
_NHL_STAGE_RANK = {
    "Playoffs": 1, "First Round": 2, "Second Round": 3, "Third Round": 4,
    "Conference Finals": 5, "Stanley Cup Final": 6, "Conference": 7, "Champion": 8,
}
_NHL_CATEGORY = {
    "winner": "Championship", "advance": "Advancement (reach a stage)", "match": "Playoff series",
    "game": "Game (not laddered)", "other": "Other",
}
_NHL_LADDER = LadderSpec(
    node_order=("Reach Playoffs", "Win Conference", "Win Championship"),
    adjacent_pairs=(("Win Championship", "Win Conference"), ("Win Conference", "Reach Playoffs")),
    # Best-effort match rungs; currently unhit (no Final-series wording) → series → UNKNOWN_RELATIONSHIP.
    match_stage_to_node={"Stanley Cup Final": "Win Championship", "Conference Finals": "Win Conference"},
    advance_stage_to_node={"Playoffs": "Reach Playoffs", "Conference": "Win Conference"},
)


def _nhl_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t == "KXNHL":
        return "winner"                                              # win the Stanley Cup
    if t in ("KXNHLEAST", "KXNHLWEST", "KXNHLPLAYOFF"):
        return "advance"                                             # win conference / reach the playoffs
    if t == "KXNHLSERIES":
        return "match"                                               # playoff series head-to-head
    if t == "KXNHLGAME":
        return "game"                                                # single game — 2-outcome dutch book
    return "other"                                                   # KXNHLSERIESGAMES, props, awards, …


def _nhl_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # NHL has no title round, so the advance "stage" comes from which series the market is in.
        return "Playoffs" if (market.get("ticker") or "").upper().startswith("KXNHLPLAYOFF") else "Conference"
    if family == "match":
        return extract_round(cfg.round_patterns, market.get("title"), market.get("rules_primary"))
    return ""


def _nhl_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Championship"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)           # Playoffs / Conference
    if family == "match":
        return cfg.ladder.match_stage_to_node.get(stage)             # Final rungs only (currently unhit)
    return None


def _nhl_division(cfg: SportConfig, series_ticker: str) -> str:
    return ""   # NHL has no ATP/WTA-style division (conference is a ladder rung, not a UI filter)


NHL = register(SportConfig(
    sport_id="nhl", label="NHL", emoji="🏒",
    series_prefixes=("KXNHL",),
    default_series=("KXNHL", "KXNHLEAST", "KXNHLWEST", "KXNHLPLAYOFF", "KXNHLSERIES", "KXNHLGAME"),
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.hockey_team",), id_label="hockey_team"),
    ladder=_NHL_LADDER,
    category_labels=_NHL_CATEGORY,
    round_patterns=_NHL_ROUND_PATTERNS,
    stage_rank=_NHL_STAGE_RANK,
    ladder_families=frozenset({"match", "advance", "winner"}),
    match_family="match",                          # KXNHLSERIES head-to-head; KXNHLGAME rides "game"
    divisions={},
    division_label="",
    family_fn=_nhl_family,
    stage_fn=_nhl_stage,
    node_fn=_nhl_node,
    division_fn=_nhl_division,
    winner_label="Win the Stanley Cup",
))
