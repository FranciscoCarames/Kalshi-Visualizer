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
    # Optional SIDE-BRANCH leaf nodes that hang off the linear ladder via an `adjacent_pairs` edge but are
    # deliberately NOT in `node_order` (e.g. soccer "Win group" ⊆ "Reach Round of 32": winning your group
    # implies qualifying, but is incomparable to reaching the Round of 16, so it must never be transitively
    # linearised). When such a leaf (or its anchor) is absent, `build_checks` skips the pair silently rather
    # than emitting MISSING_LAYER noise — the leaf is opportunistic, not a required rung. Default: none.
    optional_children: frozenset[str] = frozenset()
    # Resolution shape (drives the Bounded-Loss "Vertical vs Calendar" split, NOT detection). A
    # finishing-position ladder (golf Top-N, motorsport) settles ALL its rungs at one event's final
    # standings → its containment pairs resolve SIMULTANEOUSLY (`True`). A stage-advancement ladder
    # (tennis/playoff knockouts) settles rungs across successive rounds → SEQUENTIAL (`False`, the
    # conservative default). Per-pair overrides (match-alignment equivalences) live in `_classify`.
    simultaneous: bool = False
    # Survivor-slot count per node ("k"), the field-de-vig normalizer (DISPLAY-ONLY conditional panel,
    # never executable): how many participants a node's MECE-ish field resolves to (champion / "Win …"
    # node = 1, finalist = 2, semifinalist = 4, golf Top-5 = 5, soccer Reach-RO16 = 16…). CONSERVATIVE BY
    # DESIGN — map a node ONLY when its survivor count is unambiguous; leave fragile nodes ("Reach
    # Playoffs" with play-in churn, soccer "Win group", dead-heat-capable buckets) UNMAPPED so the de-vig
    # is skipped there (raw ratio still shown). A node absent from this map ⇒ `survivors_of(node)` is None
    # ⇒ no field-implied number for that node (fail-soft, never a wrong-k fake-precision). See
    # `probability.devig_field`.
    node_survivors: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GroupBasketRule:
    """A cardinality-floor 'group basket' rule for a per-group EVENT (e.g. World Cup group qualifiers).

    Unlike a MECE field, a qualifier set is NOT mutually exclusive — it is a CARDINALITY-FLOOR set: of
    ``team_count`` independent binary markets, the tournament FORMAT guarantees that at least ``yes_floor``
    settle YES and at least ``no_floor`` settle NO (for 2026 World Cup groups of 4: top-2 always advance →
    ``yes_floor=2``; the 4th-placed team never advances → ``no_floor=1``; the best-third rule is exactly WHY
    these are *floors*, not equalities). Buying YES on all legs then pays ≥ ``yes_floor×100¢`` in every
    outcome (and buying NO on all legs ≥ ``no_floor×100¢``) — a hard gross floor, proven from the format,
    NEVER inferred from discovered prices. Consumed by ``dutchbook.find_group_baskets``.

    ``yes_ceiling_count`` / ``no_ceiling_count`` are the format's MAXIMUM settle counts for the two
    directions (e.g. 2026 WC group of 4: up to 3 can qualify when the 3rd-placed team takes a best-third
    slot → ``yes_ceiling_count=3``; the 4th never qualifies so at most 2 fail → ``no_ceiling_count=2``).
    They drive a CONDITIONAL best-case (NOT guaranteed — it depends on the best-third outcome); the
    guaranteed worst-case stays the floor. Default ``None`` ⇒ flat (best == worst == floor gap)."""
    team_count: int
    yes_floor: int
    no_floor: int
    label: str
    yes_ceiling_count: int | None = None
    no_ceiling_count: int | None = None
    # Trader-facing noun for the legs in the finding text (e.g. "qualifier" / "bottom-finisher"). Default
    # "qualifier" preserves the existing World Cup group-qualifier wording byte-for-byte.
    noun: str = "qualifier"


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
    # NO-fade SETTLEMENT LEVEL per family (display-only; consumed by no_structures.scope_for): how many
    # "grouping" levels a market sits above a single contest — 0=Event, 1=Tournament, 2=Championship. Keyed
    # on family because the same name differs per sport (tennis "match"=a match=0; NBA "match"=the bo7
    # series=1). A family absent here is EXCLUDED from the NO-fade tables (fail-closed; registry-guard-tested).
    # A value may be a ``dict[stage,int]`` (with a ``"*"`` default) when one family spans levels by stage —
    # e.g. team ``advance``: "Reach Playoffs"=tournament, conference/title=championship.
    family_levels: dict[str, int | dict[str, int]] = field(default_factory=dict)
    # Championship TITLE-PATH decomposition (display-only): the CANONICAL longest path to the title as
    # ``(tournaments_min, tournaments_max, events_min, events_max)``. None for sports with no
    # Championship-scope market. STATIC sport-format data — re-verify on format changes (see per-sport comment).
    title_path: tuple[int, int, int, int] | None = None
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
    # Whether a 2-market game of this sport is MECE by SHAPE alone (draw-free: exactly one side wins, so
    # dutchbook._detect_pair is safe to treat the pair as a 100¢-floor book). True (default) = every existing
    # sport, byte-for-byte no-op. False (NFL) = a tie is possible, so the per-game two-way book is GATED on a
    # settlement-rule proof (dutchbook._proves_fixed_sum) that the tie settles fixed-sum ($0.50 each) or
    # cannot occur — otherwise the book is skipped (never a false dutch book on a tie-capable game).
    game_mece_by_shape: bool = True
    # Optional cardinality-floor "group basket" rules, keyed by EXACT series ticker (e.g. World Cup group
    # qualifiers). Maps a series to its per-group ``GroupBasketRule`` (team count + guaranteed YES/NO settle
    # floors, derived from the tournament format). Empty (default) = no basket for this sport, so adding it
    # stays one register() call and every other sport is a byte-for-byte no-op.
    group_basket_rules: dict[str, "GroupBasketRule"] = field(default_factory=dict)
    # Classified families whose markets are NOT a single selectable competitor (beyond the tie_fn outcome),
    # e.g. soccer's exact-order ORDERING markets (each is a full standings permutation, not one team). These
    # get a per-market synthetic key + is_participant=False so they never pollute the participant selector;
    # the owning detector reads identity from custom_strike. Empty (default) = no-op for every sport.
    non_participant_families: frozenset[str] = field(default_factory=frozenset)
    # Optional DERIVED market-implied indicators for the participant detail panel — quantities that are NOT
    # directly traded but inferred from the ladder's displayed prices (e.g. golf "make the cut": since
    # {finish Top 20} ⊆ {make the cut}, P(make cut) ≥ P(Top 20), so the Top-20 price is a FLOOR). Takes the
    # node→display% map and returns labeled indicators ({label, comparator, value_pct, note}). DISPLAY-ONLY,
    # gross/top-of-book bounds — never an edge, never fed to detection. None (default) = no indicators.
    derived_indicators_fn: Callable[["SportConfig", dict[str, "float | None"]], list[dict[str, Any]]] | None = None

    # ---- convenience API (engine calls these) --------------------------------------------
    def title_path_cells(self) -> dict[str, Any]:
        """Display cells for the Championship title-path columns (or all-None when the sport has no
        Championship market). ``title_tournaments`` shows "4" or "3–4"; ``title_events_label`` shows
        "16–28" or "28" (min==max → single number) and sorts on ``title_events_max``. Display-only."""
        s = self.title_path
        if not s:
            return {"title_tournaments": None, "title_tournaments_max": None,
                    "title_events_label": None, "title_events_max": None}
        t_min, t_max, e_min, e_max = s
        def _rng(a, b):
            return str(a) if a == b else f"{a}–{b}"
        return {"title_tournaments": _rng(t_min, t_max), "title_tournaments_max": t_max,
                "title_events_label": _rng(e_min, e_max), "title_events_max": e_max}

    def family_of(self, series_ticker: str) -> str:
        return self.family_fn(self, series_ticker)

    def derived_indicators(self, node_pct: dict[str, Any]) -> list[dict[str, Any]]:
        """Derived, DISPLAY-ONLY market-implied indicators from the ladder's display prices (detail panel
        only; never executable). Generic for any static-laddered sport: (1) the broadest rung as an
        "In contention" implied chance, (2) guarded conditional ratios P(deeper | broader) over adjacent
        rungs. Then any sport-specific bounds via `derived_indicators_fn` (e.g. golf make-cut floor). All
        labeled Uncalibrated; conditional ratios are SUPPRESSED when the ladder is inconsistent
        (deeper priced ≥ broader → ratio > 1, never asserted as "more than certain")."""
        out: list[dict[str, Any]] = []
        nodes = self.ladder.node_order if self.ladder else ()
        if nodes:
            broad = nodes[0]
            top = node_pct.get(broad)
            if top is not None:
                out.append({"label": f"In contention ({broad})", "comparator": "≈", "value_pct": top,
                            "kind": "absolute",
                            "note": "market-implied chance of being in the running; gross, top-of-book, "
                                    "Uncalibrated"})
            for broader, deeper in zip(nodes, nodes[1:]):
                b, d = node_pct.get(broader), node_pct.get(deeper)
                if b is None or d is None or b <= 0 or d > b:   # missing / degenerate / inconsistent ladder
                    continue
                out.append({"label": f"P({deeper} | {broader})", "comparator": "≈", "value_pct": d / b * 100,
                            "kind": "conditional",
                            "note": "derived conditional estimate; assumes a consistent ladder; gross, "
                                    "top-of-book, Uncalibrated — NOT a fair value"})
        if self.derived_indicators_fn:
            out.extend(self.derived_indicators_fn(self, node_pct))
        return out

    def group_basket_rule_of(self, series_ticker: str) -> "GroupBasketRule | None":
        """The cardinality-floor basket rule for a series ticker, or None when the sport has none."""
        return self.group_basket_rules.get(str(series_ticker or "").upper())

    def ladder_for(self, rows: list) -> "LadderSpec":
        """The containment ladder for a specific group's rows — per-group when ``ladder_fn`` is set
        (e.g. motorsport's per-competition ladders), else the static ``cfg.ladder`` (all existing sports)."""
        return self.ladder_fn(self, rows) if self.ladder_fn else self.ladder

    def survivors_of(self, node: str, ladder: "LadderSpec | None" = None) -> int | None:
        """Survivor-slot count ("k") for a ladder node, or None when the node is deliberately unmapped
        (fragile / ambiguous count). DISPLAY-ONLY de-vig normalizer — never read by classification,
        bucketing, or ranking. Pass an explicit ``ladder`` for per-group / dynamic-ladder sports; defaults
        to the static ``cfg.ladder``."""
        spec = ladder if ladder is not None else self.ladder
        k = getattr(spec, "node_survivors", {}).get(node) if spec else None
        return k if isinstance(k, int) and k > 0 else None

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
    # k: a single-elimination draw has exactly 4 semifinalists, 2 finalists, 1 champion — unambiguous.
    node_survivors={"Reach Semifinal": 4, "Reach Final": 2, "Win Tournament": 1},
)
_WOMEN_WINNER_TICKERS = {"KXFOWOMEN", "KXFOWOMENSINGLES", "KXFOPENWMENSINGLE"}
_MEN_WINNER_TICKERS = {"KXFOMEN", "KXFOMENSINGLES", "KXFOPENMENSINGLE"}
# ITF lower-tier tour matches (W15/W25/M15/M25…) live OUTSIDE the KXATP*/KXWTA* prefixes, so tennis owns
# them explicitly. Live-probed 2026-06-09: both carry custom_strike.tennis_competitor (high-confidence
# identity) and head-to-head events with exactly 2 markets → the standard 2-way dutch-book path
# (_detect_pair) with no detector change. Women = KXITFWMATCH, men = KXITFMATCH.
_TENNIS_EXACT = frozenset({"KXITFWMATCH", "KXITFMATCH"})


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
    if t.startswith("KXITFW"):
        return "WTA"                            # ITF women (KXITFWMATCH); men KXITFMATCH falls through to ATP
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
    # Fetch the FO core + the ITF head-to-head series in the default scan (ITF is exact-owned, not prefixed).
    default_series=tuple(config.DEFAULT_SERIES) + tuple(sorted(_TENNIS_EXACT)),
    winner_tickers=frozenset(config.FO_WINNER_TICKERS),
    exact_series=_TENNIS_EXACT,
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
    # Settlement level: a match/set/score is one contest (0); reach-a-stage / win the tournament is one
    # level up (1); the Grand Slam spans multiple tournaments (2).
    family_levels={"match": 0, "set_winner": 0, "exact_score": 0, "advance": 1, "winner": 1, "grand_slam": 2},
    # Title path (only on a grand-slam-scope row, never an ordinary major): 4 majors × 7 single-elim rounds
    # → 4 tournaments, 28 matches (deterministic).
    title_path=(4, 4, 28, 28),
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
    # k: exactly 1 champion, 2 conference champions (one per conference) league-wide — unambiguous.
    # "Reach Playoffs" UNMAPPED (count varies / play-in churn) → raw-only.
    node_survivors={"Win Conference": 2, "Win Championship": 1},
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
    # Settlement level: a game (0); the best-of-7 series (1); winning the conference / title spans
    # "match" == KXNBASERIES = the bo7 series (1). `advance` SPANS levels by stage: "Reach Playoffs"
    # (regular-season qualification = a group of games) = tournament (1); "Win Conference" (a chain of
    # series = a group of tournaments) = championship (2). winner (title) = championship.
    family_levels={"game": 0, "match": 1, "advance": {"Playoffs": 1, "Conference": 2, "*": 2}, "winner": 2},
    # Title path (current 4-round bracket, each best-of-7): First Round, Conf Semis, Conf Finals, Finals.
    # Play-in excluded (title teams don't all pass it). VERIFY on format changes.
    title_path=(4, 4, 16, 28),
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
    # k: single-bracket knockout → exactly 4 semifinalists, 2 finalists, 1 champion. "Reach Playoffs"
    # UNMAPPED (field size / play-in churn) → raw-only.
    node_survivors={"Reach Semifinals": 4, "Reach Finals": 2, "Win Championship": 1},
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
    # advance spans levels by stage: Playoffs (qualify) = tournament; Semifinals/Finals (won a series) = championship.
    family_levels={"game": 0, "match": 1, "advance": {"Playoffs": 1, "Semifinals": 2, "Finals": 2, "*": 2}, "winner": 2},
    # Title path: First Round(bo3) + Semifinals(bo5) + Finals(bo7, EFFECTIVE 2025) → 3 series, 9–15 games. VERIFY.
    title_path=(3, 3, 9, 15),
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
    simultaneous=True,                         # all finishing rungs settle at the tournament's final standings
    # k = the finishing-position cutoff. DEAD-HEAT CAVEAT: a tie at the cutoff can settle >k players YES
    # (e.g. a 3-way tie for 5th → Top-5 pays 5+ winners), so golf de-vig is a floor-leaning estimate; the
    # detail panel labels it accordingly. Champion (Win) is always exactly 1.
    node_survivors={"Top 20": 20, "Top 10": 10, "Top 5": 5, "Win Tournament": 1},
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


def _golf_make_cut_indicator(cfg: SportConfig, node_pct: dict[str, "float | None"]) -> list[dict[str, Any]]:
    """Golf "make the cut" implied FLOOR (bounds only, v1). Finishing Top 20 requires surviving the cut, so
    {finish Top 20} ⊆ {make the cut} ⟹ P(make cut) ≥ P(Top 20). Read straight off the Top-20 display price
    — a BOUND, not a fair value, and not a traded market. Absent when Top 20 isn't listed."""
    top20 = node_pct.get("Top 20")
    if top20 is None:
        return []
    return [{"label": "Make the cut", "comparator": "≥", "value_pct": top20, "kind": "bound",
             "note": "Derived — not a traded market. Finishing Top 20 requires making the cut, so the market "
                     "implies at least this chance to make the cut (the Top-20 price). Gross, top-of-book; "
                     "a bound, not a fair value."}]


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
    derived_indicators_fn=_golf_make_cut_indicator,
    family_fn=_golf_family,
    # A golf tournament is a single FIELD event (no sub-contests), so Top-N / win = Event (0) — same shape
    # as a motorsport race result. Golf appears only in the Event table.
    family_levels={"advance": 0, "winner": 0},
    stage_fn=_golf_stage,
    node_fn=_golf_node,
    division_fn=_golf_division,
    exact_series=_GOLF_EXACT,
))


# --- Soccer (6th sport): 2026 World Cup ---------------------------------------------------------------
# Owns (via exact_series): KXWCGAME (3-way group game Home/Away/Tie — `game` family, the n-outcome dutch
# book), KXWCROUND (per-team reach-stage RO16..Final — `advance` ladder), KXWCGROUPQUAL (per-team "qualify
# from group for the Round of 32" — the `advance` ladder's BOTTOM rung; 12 per-group events
# KXWCGROUPQUAL-26A..L, joined per-team by the soccer_team UUID; also the cardinality-floor basket source,
# see dutchbook.find_group_baskets), KXWCGROUPWIN (per-team "win the group" — the `group_winner` family →
# a "Win group" containment LEAF that hangs off "Reach Round of 32" but is NOT a linear rung), and
# KXMENWORLDCUP (the live per-team tournament-outright winner field → "Win the World Cup"). Values confirmed
# live 2026-06-08: KXMENWORLDCUP-26 is the OPEN outright (KXMWORLDCUP exists but has no open event);
# KXMENWORLDCUP is deci-cent (sub-cent → subpenny-filtered, so the "Win the World Cup" rung is DISPLAY-ONLY
# for now); KXWCGROUPQUAL/KXWCGROUPWIN are whole-cent. KXWCGROUPWINNER ("Group to Win") is a DIFFERENT
# contract — not owned. The Tie market reuses a CONSTANT soccer_team UUID across all games (non-participant
# draw leg, per-event synthetic key via tie_fn). No head-to-head series (match_family="").
SOCCER_TIE_UUID = "111193d4-9b1f-4bd8-ab7c-9de252737f05"
# World Cup series that are CURRENT on Kalshi but deliberately OUT of detector scope — owned only so they
# resolve to soccer (not the UNKNOWN sport) and surface in the coverage audit / Debug "considered"
# inventory as "recognized + other" rather than silently disappearing. `_soccer_family` returns "other"
# for all of them (the default branch), so they get the "Other" category label, which `data.non_other_
# families` strips from every fetch scope → owned but NEVER fetched and NEVER detected (verified safe even
# under scan_all: discover_series_for_sport returns all exact_series, then series_for_families drops the
# "other" ones). CRITICAL: KXWCBESTHOST / KXWCFURTHESTADVANCING settle FRACTIONALLY ($1/N on co-winners),
# which violates the one-winner assumption in dutchbook.prove_field_mece — keeping them "other" guarantees
# they can never enter field_families and so can never produce a FALSE field dutch book.
_SOCCER_KNOWN_OTHER = frozenset({
    "KXWCSTAGE",              # furthest stage by host/region — synthetic entity, not a soccer_team
    "KXWCBESTHOST",           # best-performing host nation — FRACTIONAL co-winner settlement (excluded)
    "KXWCFURTHESTADVANCING",  # furthest-advancing nation by region — FRACTIONAL co-winner settlement
    "KXWCGOALLEADER",         # Golden Boot / goal leader — award/stat, out of scope
    "KXWCAWARD",              # tournament awards — out of scope
    "KXWCTOTALGOAL",          # scalar total-goals threshold — out of scope
    "KXWCTEAMGOALS",          # per-team goals scalar — out of scope
    "KXWCGROUPGOALS",         # per-group goals scalar — out of scope
    "KXWCGROUPWINNER",        # "Group to Win" — a DIFFERENT contract from KXWCGROUPWIN; not modeled
})
_SOCCER_EXACT = frozenset({"KXWCGAME", "KXWCROUND", "KXWCGROUPQUAL", "KXWCGROUPWIN", "KXMENWORLDCUP",
                           "KXWCGROUPORDER", "KXWCGROUPBOTTOM",
                           "KXWCSTAGEOFELIM"}) | _SOCCER_KNOWN_OTHER
# KXWCSTAGEOFELIM "stage of elimination" partition: per-team, exactly ONE of these 7 buckets settles YES
# (the stage where the team is eliminated; FW = wins the final). Ordered broad→deep by the market-ticker
# suffix; the SAME ordered set the detector (stage_elim.py) uses, so it is single-sourced here. Live-probed
# 2026-06-09: 48 events, mutually_exclusive=True, constant soccer_team UUID across a team's 7 buckets.
WC_STAGE_ELIM_BUCKETS = (
    ("GS", "Eliminated: Group Stage"), ("R32", "Eliminated: Round of 32"),
    ("R16", "Eliminated: Round of 16"), ("QF", "Eliminated: Quarterfinals"),
    ("SF", "Eliminated: Semifinals"), ("FL", "Runner-up (lost Final)"), ("FW", "Winner"),
)
_WC_STAGE_ELIM_LABEL = dict(WC_STAGE_ELIM_BUCKETS)
# `exact_order` MUST have a non-"other" category label, else data.non_other_families would treat it as a
# prop and the cross-sport fetch path would never load KXWCGROUPORDER.
_SOCCER_CATEGORY = {"game": "Match (3-way)", "advance": "Stage advancement",
                    "group_winner": "Group winner", "winner": "Tournament winner",
                    "exact_order": "Exact group order", "group_bottom": "Group bottom",
                    "stage_of_elim": "Stage of elimination", "other": "Other"}
_SOCCER_STAGE_RANK = {"Round of 32": 1, "Round of 16": 2, "Quarterfinals": 3, "Semifinals": 4, "Finals": 5}
_SOCCER_LADDER = LadderSpec(
    node_order=("Reach Round of 32", "Reach Round of 16", "Reach Quarterfinals",
                "Reach Semifinals", "Reach Finals", "Win the World Cup"),
    # "Win group" ⊆ "Reach Round of 32" is a SIDE-BRANCH leaf (winning the group implies qualifying), kept
    # OUT of node_order so the transitive bridge never linearises it against deeper rungs ("Win group" and
    # "Reach Round of 16" are incomparable — a group winner can lose in the R32; a runner-up reaches R16).
    adjacent_pairs=(("Win the World Cup", "Reach Finals"),
                    ("Reach Finals", "Reach Semifinals"),
                    ("Reach Semifinals", "Reach Quarterfinals"),
                    ("Reach Quarterfinals", "Reach Round of 16"),
                    ("Reach Round of 16", "Reach Round of 32"),
                    ("Win group", "Reach Round of 32")),
    match_stage_to_node={},                    # no head-to-head
    advance_stage_to_node={"Round of 32": "Reach Round of 32", "Round of 16": "Reach Round of 16",
                           "Quarterfinals": "Reach Quarterfinals", "Semifinals": "Reach Semifinals",
                           "Finals": "Reach Finals"},
    optional_children=frozenset({"Win group"}),
    # k = knockout-bracket survivor counts (32→16→8→4→2→1), unambiguous. "Win group" is deliberately
    # UNMAPPED: group cardinality (winners across N groups) differs from a knockout rung — raw-only there.
    node_survivors={"Reach Round of 32": 32, "Reach Round of 16": 16, "Reach Quarterfinals": 8,
                    "Reach Semifinals": 4, "Reach Finals": 2, "Win the World Cup": 1},
)


def _soccer_family(cfg, series_ticker):
    t = (series_ticker or "").upper()
    if t == "KXWCGAME":
        return "game"                                                # 3-way group game (n-outcome dutch book)
    if t in ("KXWCROUND", "KXWCGROUPQUAL"):
        return "advance"                                             # per-team reach-stage (GROUPQUAL = Reach RO32)
    if t == "KXWCGROUPWIN":
        return "group_winner"                                        # per-team "win the group" — containment leaf
    if t == "KXWCGROUPORDER":
        return "exact_order"                                         # 24-way exact standings — diagnostic only (#4)
    if t == "KXWCGROUPBOTTOM":
        return "group_bottom"                                        # 4-team "finish bottom" one-winner field
    if t == "KXWCSTAGEOFELIM":
        return "stage_of_elim"                                       # per-team 7-bucket elimination MECE set
    if t in cfg.winner_tickers:
        return "winner"                                              # tournament outright (KXMENWORLDCUP)
    return "other"


def _soccer_stage(cfg, family, market):
    if family == "stage_of_elim":
        # The elimination bucket is the market-ticker suffix (…-GS / …-R32 / … / …-FW). Display-only label;
        # the family is non-laddered, so this never enters a containment comparison.
        suffix = str(market.get("ticker") or "").rsplit("-", 1)[-1].upper()
        return _WC_STAGE_ELIM_LABEL.get(suffix, "")
    if family != "advance":
        return ""
    # The round lives in the market ticker segment (e.g. KXWCROUND-26RO16-PAR / KXWCGROUPQUAL-26L-PAN)
    # and/or the title. Check most-specific first so "Semifinals"/"Quarterfinals" never collapse to "Finals".
    blob = ((market.get("ticker") or "") + " " + (market.get("title") or "")).upper()
    # Round of 32 = qualifying from the group stage (KXWCGROUPQUAL "Group X Qualifiers"); also accept an
    # explicit RO32 marker should KXWCROUND ever list one. "GROUPQUAL" has no "QUAR", so order is safe.
    if "GROUPQUAL" in blob or "RO32" in blob or "ROUND OF 32" in blob:
        return "Round of 32"
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
        return "Win the World Cup"                                   # KXMENWORLDCUP outright (display-only: sub-cent)
    if family == "group_winner":
        return "Win group"                                           # leaf: ⊆ "Reach Round of 32" (qualify) only
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


def _soccer_tournament_key(cfg, event):
    """Canonical season-scoped grouping key for EVERY World Cup series (audit A2).

    All WC scopes — reach-stage (``KXWCROUND``), group qualifier (``KXWCGROUPQUAL``), the outright
    winner (``KXMENWORLDCUP``), games, group baskets — carry DIFFERENT ``competition`` strings, so the
    default ``data.tournament_of`` keys them apart and a team's containment ladder (Reach RO16 ⊇ … ⊇ Win
    the World Cup) fragments across ``(player_key, tournament)`` groups and never forms. Mirroring
    motorsport's ``tournament_key_fn``, this collapses them onto one ``"World Cup · <season>"`` key (season
    token = the leading digit run after the series prefix, e.g. ``KXWCROUND-26RO16-PAR`` → ``26``), so the
    ladder groups correctly while co-loaded editions (a future ``-30``) still stay separate."""
    et = str(event.get("event_ticker") or "")
    token = ""
    if "-" in et:
        m = re.match(r"(\d+)", et.split("-", 1)[1])
        token = m.group(1) if m else ""
    key = f"World Cup · {token}" if token else "World Cup"
    return key, "soccer_event"


SOCCER = register(SportConfig(
    sport_id="soccer", label="Soccer (World Cup)", emoji="⚽",
    # default_series is the bounded fetch subset — the SUPPORTED series only. Known-other tickers are owned
    # (in _SOCCER_EXACT, so they resolve to soccer) but excluded here so they never enter the default scan.
    series_prefixes=(), default_series=tuple(sorted(_SOCCER_EXACT - _SOCCER_KNOWN_OTHER)),
    winner_tickers=frozenset({"KXMENWORLDCUP"}),   # live per-team outright field (KXMENWORLDCUP-26)
    identity=IdentityResolver(candidate_paths=("custom_strike.soccer_team",), id_label="soccer_team"),
    ladder=_SOCCER_LADDER,
    category_labels=_SOCCER_CATEGORY,
    round_patterns=(),
    stage_rank=_SOCCER_STAGE_RANK,
    ladder_families=frozenset({"advance", "winner", "group_winner"}),
    match_family="",                           # no 2-way head-to-head; the 3-way game rides the "game" family
    divisions={},
    division_label="",
    family_fn=_soccer_family,
    # A game (0); advancing / winning the group / winning the World Cup are all within the one tournament
    # (1). exact_order/group_bottom/stage_of_elim are diagnostic-only → absent here → excluded.
    family_levels={"game": 0, "advance": 1, "group_winner": 1, "winner": 1},
    stage_fn=_soccer_stage,
    node_fn=_soccer_node,
    division_fn=_soccer_division,
    exact_series=_SOCCER_EXACT,
    tie_fn=_soccer_tie,
    # Exact-order ORDERING markets are full standings permutations, not single teams (#4 diagnostic reads
    # identity from custom_strike) → non-selectable, per-market key.
    non_participant_families=frozenset({"exact_order"}),
    winner_label="Win the World Cup",
    # Audit A2: collapse every WC scope onto one season-scoped tournament key so a team's containment
    # ladder (Reach RO16 ⊇ … ⊇ Win the World Cup) groups instead of fragmenting by per-series competition.
    tournament_key_fn=_soccer_tournament_key,
    # Each KXWCGROUPQUAL-26<G> event is a group of 4 teams; the 2026 format guarantees >=2 qualify (top-2
    # auto-advance) and >=1 fails (the 4th-placed team never advances) → a hard YES floor of 200¢ and NO
    # floor of 100¢ for the all-four basket. The CONDITIONAL ceilings: up to 3 qualify when the 3rd-placed
    # team takes a best-third slot (YES 300¢), and up to 2 fail otherwise (NO 200¢). See
    # dutchbook.find_group_baskets.
    # KXWCGROUPQUAL = top-2 qualify (floors 2/1, conditional best-third ceiling 3/2). KXWCGROUPBOTTOM =
    # which of the 4 finishes bottom: EXACTLY one does, so exactly 1 leg settles YES and 3 settle NO — an
    # EXACT cardinality basket (floor == ceiling, no conditional band). Live-probed 2026-06-09 the events
    # were mutually_exclusive=False; re-probed 2026-06-10 (kickoff eve) they now flag True. The routing is
    # deliberately FLAG-INDEPENDENT: the basket proof is the format-derived cardinality floor, so the flip
    # changes nothing here, and group_bottom stays OUT of field_families (never a flagged winner field).
    group_basket_rules={
        "KXWCGROUPQUAL": GroupBasketRule(team_count=4, yes_floor=2, no_floor=1,
                                         yes_ceiling_count=3, no_ceiling_count=2,
                                         label="World Cup group"),
        "KXWCGROUPBOTTOM": GroupBasketRule(team_count=4, yes_floor=1, no_floor=3,
                                           yes_ceiling_count=1, no_ceiling_count=3,
                                           label="World Cup group", noun="bottom-finisher"),
    },
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
    # k: exactly 1 World Series champion, 2 league champions (AL + NL) → World Series. "Reach Playoffs"
    # UNMAPPED (12-team field, wild-card churn) → raw-only.
    node_survivors={"Win League": 2, "Win World Series": 1},
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
    # A game (0); the pennant / World Series are won across multiple series (2). MLB has no in-app series
    # advance spans levels by stage: Playoffs (regular-season qualification) = tournament; League (pennant,
    # a chain of series) = championship. (KXMLBSERIES excluded, so MLB has no bo-N series Tournament row.)
    family_levels={"game": 0, "advance": {"Playoffs": 1, "League": 2, "*": 2}, "winner": 2},
    # Title path: WC(bo3, TOP SEEDS BYE) + LDS(bo5) + LCS(bo7) + WS(bo7) → 3–4 series, 11–22 games (a
    # wild-card team plays all 4; a bye team plays 3). Canonical longest path. VERIFY on format changes.
    title_path=(3, 4, 11, 22),
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
    # k: exactly 1 Stanley Cup champion, 2 conference champions (East + West). "Reach Playoffs" UNMAPPED
    # (16-team field) → raw-only.
    node_survivors={"Win Conference": 2, "Win Championship": 1},
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
    # advance spans levels by stage: Playoffs (qualify) = tournament; Conference (series chain) = championship.
    family_levels={"game": 0, "match": 1, "advance": {"Playoffs": 1, "Conference": 2, "*": 2}, "winner": 2},
    title_path=(4, 4, 16, 28),   # 4 rounds × best-of-7 (First/Second/Conf Finals/Stanley Cup Final). VERIFY.
    stage_fn=_nhl_stage,
    node_fn=_nhl_node,
    division_fn=_nhl_division,
    winner_label="Win the Stanley Cup",
))


# --- NFL (9th sport): core futures ladder + full-game moneyline dutch books --------------------------
# Grounded in a read-only live probe (2026-06-08) of /series (cursor-paginated) + nested-market events:
#   * Identity: custom_strike.football_team (stable UUID) on every market; yes_sub_title is the team name.
#   * Futures ladder (NBA/MLB/NHL shape): Reach Playoffs (KXNFLPLAYOFF, mutually_exclusive=False — 14 teams
#     qualify, so "advance", NOT a one-winner field) ⊇ Win Conference (KXNFLAFCCHAMP / KXNFLNFCCHAMP,
#     mutually_exclusive=True) ⊇ Win Super Bowl (KXSB — NOT KXNFL-prefixed → owned via winner_tickers).
#   * KXSB is a one-winner FIELD (32 ME markets) → inherits the default field_families={"winner"} →
#     dutchbook._detect_field overround when priced. AFC/NFC champ are classified "advance" → no field book
#     (advance fields out of scope — same seed as the other sports).
#   * KXNFLGAME (KX*GAME "game" family) is a 2-market single game. NFL games CAN TIE (rules_secondary:
#     "If the game ends in a tie, the market will resolve to $0.50 for each team"), so the pair is NOT
#     MECE-by-shape → game_mece_by_shape=False gates it behind dutchbook._proves_fixed_sum (the tie pays
#     $0.50/side → the 100¢ floor still holds in every state). No head-to-head series → match_family="".
#   * The "KXNFL" prefix FINDS ~200 series (spreads, totals, quarter/half winners, MVP/awards, draft,
#     exact-wins, division winners KXNFLAFCEAST/…, props) — family_fn is a STRICT exact-equality allow-list
#     so every one of those resolves to "other" (discovered, never laddered, filtered out of fetch).
_NFL_STAGE_RANK = {"Playoffs": 1, "Conference": 2, "Champion": 3}
_NFL_CATEGORY = {
    "winner": "Super Bowl", "advance": "Advancement (reach a stage)",
    "game": "Game (not laddered)", "other": "Other",
}
_NFL_LADDER = LadderSpec(
    node_order=("Reach Playoffs", "Win Conference", "Win Super Bowl"),
    adjacent_pairs=(("Win Super Bowl", "Win Conference"), ("Win Conference", "Reach Playoffs")),
    match_stage_to_node={},                                    # no head-to-head series
    advance_stage_to_node={"Playoffs": "Reach Playoffs", "Conference": "Win Conference"},
    # k: exactly 1 Super Bowl champion, 2 conference champions (AFC + NFC). "Reach Playoffs" UNMAPPED
    # (14-team field, seeding churn) → raw-only.
    node_survivors={"Win Conference": 2, "Win Super Bowl": 1},
)


def _nfl_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t == "KXSB":
        return "winner"                                        # win the Super Bowl (winner field)
    if t in ("KXNFLPLAYOFF", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP"):
        return "advance"                                       # reach playoffs / win conference
    if t == "KXNFLGAME":
        return "game"                                          # single game — gated 2-outcome dutch book
    return "other"                                             # spreads/totals/props/awards/draft/divisions


def _nfl_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    if family == "winner":
        return "Champion"
    if family == "advance":
        # Playoff-qualifier series → "Playoffs"; the two conference-champ series → "Conference".
        return "Playoffs" if (market.get("ticker") or "").upper().startswith("KXNFLPLAYOFF") else "Conference"
    return ""


def _nfl_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    if family == "winner":
        return "Win Super Bowl"
    if family == "advance":
        return cfg.ladder.advance_stage_to_node.get(stage)     # Reach Playoffs / Win Conference
    return None


def _nfl_division(cfg: SportConfig, series_ticker: str) -> str:
    return ""   # NFL has no ATP/WTA-style division (conference is a ladder rung, not a UI filter)


NFL = register(SportConfig(
    sport_id="nfl", label="NFL", emoji="🏈",
    series_prefixes=("KXNFL",),
    default_series=("KXSB", "KXNFLPLAYOFF", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXNFLGAME"),
    winner_tickers=frozenset({"KXSB"}),            # Super Bowl winner is not KXNFL-prefixed
    identity=IdentityResolver(candidate_paths=("custom_strike.football_team",), id_label="football_team"),
    ladder=_NFL_LADDER,
    category_labels=_NFL_CATEGORY,
    round_patterns=(),                             # no head-to-head, no round extraction
    stage_rank=_NFL_STAGE_RANK,
    ladder_families=frozenset({"advance", "winner"}),
    match_family="",                               # single-elim; no head-to-head series. KXNFLGAME rides "game"
    divisions={},
    division_label="",
    family_fn=_nfl_family,
    # Single-elimination (no series layer): a game (0); reach playoffs / win conference / win the Super
    # Bowl are all one level above a game (1). NFL is SINGLE-ELIMINATION (no bo-N series layer) → the whole
    # playoffs is ONE tournament, so `advance` does NOT span levels (no stage dict needed) and NFL has no
    # Championship-scope rows.
    family_levels={"game": 0, "advance": 1, "winner": 1},
    stage_fn=_nfl_stage,
    node_fn=_nfl_node,
    division_fn=_nfl_division,
    winner_label="Win the Super Bowl",
    game_mece_by_shape=False,                       # NFL games can tie → gated on _proves_fixed_sum
))


# --- Motorsport (8th sport): F1 / NASCAR / IndyCar / MotoGP — a field sport like golf ----------------
# Grounded in a read-only Phase-0 probe (2026-06-05) of /search/filters_by_sport + nested markets:
#   * Identity: drivers/riders = custom_strike.racing_competitor (UUID); NASCAR teams = nascar_team (UUID);
#     F1 constructors = custom_strike.Participant (a NAME, e.g. "Red Bull Racing" → LOW confidence). The
#     `primary_participant_key` field is a key-NAME pointer ("racing_competitor"), NOT an id value, so it is
#     deliberately not a candidate path. The resolved player_key is role-namespaced (driver/constructor/team)
#     so a constructor that reuses the driver UUID path never merges with a driver.
#   * Each market SCOPE owns its own series ticker, so the family is resolvable from the ticker alone.
#     One-winner FIELDS (mutually_exclusive=True): race winner (Kalshi "Games"), champion futures, pole,
#     fastest lap, top constructor, top team → overround-eligible via `field_families`. Top-N / Podium are
#     mutually_exclusive=False (many qualify) → the finishing-position LADDER, never a field.
#   * No head-to-head (match_family=""); KXF1H2H/KXNASCARH2H are listed-but-deferred → "other".
#   * Grouping is per RACE INSTANCE: competition (F1 / NASCAR Cup Series / NASCAR Truck Series / IndyCar /
#     MotoGP, from product_metadata.competition) + session (sprint vs main-race) + the event-ticker location
#     token (e.g. F1 · main-race · MONGP26). Raw competition_scope (Game/Podium/Top 5 …) is NEVER in the key
#     (it would split a race's own ladder rungs). Ladders are per-competition via ladder_fn.
_MOTOR_PREFIXES = ("KXF1", "KXNASCAR", "KXINDY", "KXMOTOGP")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _looks_like_uuid(v: Any) -> bool:
    return bool(_UUID_RE.match(str(v or "")))


_MOTOR_CATEGORY = {
    "winner": "Champion (futures)", "race_winner": "Race winner", "advance": "Finish position",
    "constructor": "Top constructor", "team": "Top team", "pole": "Pole position",
    "fastest_lap": "Fastest lap", "other": "Other",
}
_MOTOR_STAGE_RANK = {"Top 20": 1, "Top 10": 2, "Top 5": 3, "Top 3": 4, "Podium": 4, "Win Race": 5,
                     "Champion": 6}

# Per-competition finishing-position ladders (broad → deep: the BIGGER finishing set ⊇ the smaller ⊇ win).
# The deepest rung is "Win Race" (the race_winner field). MotoGP / O'Reilly list no finishing markets → no
# ladder. Each ladder is checked only for its own competition's groups (ladder_fn), so no superset noise.
def _motor_ladder(*nodes: str) -> LadderSpec:
    pairs = tuple((nodes[i + 1], nodes[i]) for i in range(len(nodes) - 1))   # (deeper child, broader parent)
    return LadderSpec(node_order=nodes, adjacent_pairs=pairs, match_stage_to_node={},
                      advance_stage_to_node={n: n for n in nodes if n != "Win Race"},
                      simultaneous=True)        # one race's final classification settles every rung at once


_MOTOR_LADDERS = {
    "F1": _motor_ladder("Top 10", "Top 5", "Podium", "Win Race"),
    "NASCAR Cup Series": _motor_ladder("Top 20", "Top 10", "Top 5", "Top 3", "Win Race"),
    "NASCAR Truck Series": _motor_ladder("Top 10", "Top 3", "Win Race"),
    "IndyCar": _motor_ladder("Top 10", "Top 3", "Win Race"),
}
_MOTOR_EMPTY_LADDER = LadderSpec((), (), {}, {})


# Motorsport family resolution is an EXACT-TICKER ALLOW-LIST (audit A7), not substring matching. The old
# form routed ANY ticker containing "RACE"/"SERIES" into a one-winner FIELD family (race_winner/winner),
# so a NEW prop (e.g. a hypothetical "KXF1RACEMARGIN") could be mis-routed into a field dutch book. Here a
# ticker is field-eligible ONLY if it is explicitly listed; anything unrecognized is "other" (never a
# field) and `motorsport_coverage_gaps` surfaces it so the allow-list can't silently rot.
_MOTOR_FAMILY_BY_SERIES: dict[str, str] = {
    # season-champion futures — one-winner FIELD
    "KXF1": "winner", "KXMOTOGP": "winner", "KXNASCAR": "winner",
    "KXNASCARCUPSERIES": "winner", "KXNASCARTRUCKSERIES": "winner", "KXINDYCARSERIES": "winner",
    # per-race winner — one-winner FIELD
    "KXF1RACE": "race_winner", "KXF1RACESPRINT": "race_winner", "KXNASCARRACE": "race_winner",
    "KXINDYCARRACE": "race_winner", "KXINDY500": "race_winner", "KXMOTOGPRACE": "race_winner",
    # pole / fastest lap — one-winner FIELD
    "KXF1POLE": "pole", "KXNASCARPOLE": "pole",
    "KXF1FASTLAP": "fastest_lap", "KXNASCARFASTLAP": "fastest_lap",
    # constructor / team championships — one-winner FIELD
    "KXF1CONSTRUCTORS": "constructor", "KXF1TOPCONSTRUCTOR": "constructor",
    "KXNASCARTOPTEAM": "team", "KXNASCARTOPMANU": "team", "KXMOTOGPTEAMS": "team",
    # finishing-position rungs — `advance` ladder, NOT a field (never enters _detect_field)
    "KXF1RACEPODIUM": "advance", "KXF1TOP5": "advance", "KXF1TOP10": "advance",
    "KXNASCARTOP3": "advance", "KXNASCARTOP5": "advance", "KXNASCARTOP10": "advance",
    "KXNASCARTOP20": "advance", "KXINDYCARTOP3": "advance", "KXINDYCARTOP10": "advance",
}
# Recognized props / deprecated scopes that are deliberately "other" — so a coverage alert fires only for
# a GENUINELY unknown motorsport-tagged series, not for these known exclusions.
_MOTOR_KNOWN_OTHER_TOKENS = ("H2H", "DELAY", "OCCUR", "RETIRE", "QUALIFY", "CHINA", "RACEOLD", "TOPX")


def _motor_family(cfg: SportConfig, series_ticker: str) -> str:
    """Family from the SERIES ticker via the exact allow-list (audit A7). An unlisted ticker is "other"
    and can never be routed into a one-winner field dutch book."""
    return _MOTOR_FAMILY_BY_SERIES.get((series_ticker or "").upper(), "other")


def motorsport_coverage_gaps(series_tickers: Any) -> list[str]:
    """Coverage alert (audit A7): motorsport-prefixed series that are neither in the family allow-list nor a
    recognized prop/deprecated scope — surfaced so the allow-list can't silently rot as Kalshi adds scopes.
    De-duplicated, order-preserving. Empty for the current known universe."""
    out: list[str] = []
    for tk in dict.fromkeys(series_tickers or []):
        T = (tk or "").upper()
        if not T.startswith(_MOTOR_PREFIXES):
            continue
        if T in _MOTOR_FAMILY_BY_SERIES or any(tok in T for tok in _MOTOR_KNOWN_OTHER_TOKENS):
            continue
        out.append(tk)
    return out


def _motor_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    """The rung label, read from the MARKET ticker prefix (classify gives stage_fn only the market)."""
    if family == "winner":
        return "Champion"
    if family == "race_winner":
        return "Win Race"
    if family == "advance":
        t = (market.get("ticker") or "").upper()
        if "TOP20" in t:
            return "Top 20"
        if "TOP10" in t:
            return "Top 10"
        if "TOP5" in t:
            return "Top 5"
        if "TOP3" in t:
            return "Top 3"
        if "PODIUM" in t:
            return "Podium"
    return ""


def _motor_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    """Node names ARE the rung labels (uniform across competitions); ladder_fn decides which pairs apply."""
    if family == "race_winner":
        return "Win Race"
    if family == "advance":
        return stage or None
    return None                                                 # winner futures = flat field (no rung)


def _motor_division(cfg: SportConfig, series_ticker: str) -> str:
    """Coarse Series filter; the precise competition (Cup/Truck/O'Reilly) lives in the tournament key."""
    t = (series_ticker or "").upper()
    if t.startswith("KXF1"):
        return "F1"
    if t.startswith("KXNASCAR"):
        return "NASCAR"
    if t.startswith("KXINDY"):
        return "IndyCar"
    if t.startswith("KXMOTOGP"):
        return "MotoGP"
    return ""


def _motor_role(cfg: SportConfig, family: str) -> str:
    """Role tag for player_key, from the CLASSIFIED family — constructors/teams (Participant/nascar_team)
    must never merge with drivers/riders (racing_competitor), even when they share an id path."""
    if family == "constructor":
        return "constructor"
    if family == "team":
        return "team"
    return "driver"


def _motor_ladder_fn(cfg: SportConfig, rows: list) -> LadderSpec:
    """The finishing-position ladder for THIS group's competition (read from the stamped `competition`)."""
    comp = (rows[0].get("competition") if rows else "") or ""
    return _MOTOR_LADDERS.get(comp, _MOTOR_EMPTY_LADDER)


def _motor_tournament_key(cfg: SportConfig, event: dict[str, Any]) -> tuple[str, str]:
    """Event-instance grouping key: `competition · session · race-token`, e.g. "F1 · main-race · MONGP26".
    Unifies every scope of one race (the location token is shared) while separating sprint vs main race,
    different races, and season futures. Raw competition_scope is intentionally NOT part of the key."""
    et = str(event.get("event_ticker") or "")
    comp = ((event.get("product_metadata") or {}).get("competition") or "Motorsport").strip()
    token = et.split("-", 1)[1] if "-" in et else et            # event_ticker is SERIES-TOKEN
    session = "sprint" if "SPRINT" in et.upper() else "main-race"
    return (f"{comp} · {session} · {token}", "motorsport_event")


MOTORSPORT = register(SportConfig(
    sport_id="motorsport", label="Motorsport", emoji="\U0001f3ce",
    series_prefixes=_MOTOR_PREFIXES,
    default_series=(
        "KXF1", "KXF1CONSTRUCTORS", "KXF1RACE", "KXF1RACEPODIUM", "KXF1TOP5", "KXF1TOP10",
        "KXF1TOPCONSTRUCTOR", "KXF1POLE", "KXF1FASTLAP",
        "KXNASCARCUPSERIES", "KXNASCARRACE", "KXNASCARTOP3", "KXNASCARTOP5", "KXNASCARTOP10",
        "KXNASCARTOP20", "KXNASCARTOPTEAM", "KXNASCARFASTLAP", "KXNASCARPOLE", "KXNASCARTRUCKSERIES",
        "KXINDYCARSERIES", "KXINDYCARRACE", "KXINDYCARTOP3", "KXINDYCARTOP10", "KXINDY500",
        "KXMOTOGP", "KXMOTOGPRACE", "KXMOTOGPTEAMS",
    ),
    winner_tickers=frozenset(),
    identity=IdentityResolver(
        candidate_paths=("custom_strike.racing_competitor", "custom_strike.nascar_team",
                         "custom_strike.Participant"),
        id_label="competitor", id_validator=_looks_like_uuid),
    ladder=_MOTOR_EMPTY_LADDER,                 # static default; real ladders come from ladder_fn per group
    category_labels=_MOTOR_CATEGORY,
    round_patterns=(),
    stage_rank=_MOTOR_STAGE_RANK,
    ladder_families=frozenset({"advance", "race_winner"}),
    match_family="",                            # field sport — no head-to-head, no pair dutch books
    divisions={"F1": ["F1"], "NASCAR": ["NASCAR"], "IndyCar": ["IndyCar"], "MotoGP": ["MotoGP"],
               "All": ["F1", "NASCAR", "IndyCar", "MotoGP"]},
    division_label="Series",
    family_fn=_motor_family,
    # A race result is one contest: race winner / pole / fastest lap / Top-N finish = Event (0). The
    # season champion / top constructor / top team are won across the whole season = Tournament (1).
    family_levels={"race_winner": 0, "pole": 0, "fastest_lap": 0, "advance": 0,
                   "winner": 1, "constructor": 1, "team": 1},
    stage_fn=_motor_stage,
    node_fn=_motor_node,
    division_fn=_motor_division,
    winner_label="Win the Championship",
    field_families=frozenset({"winner", "race_winner", "pole", "fastest_lap", "constructor", "team"}),
    role_fn=_motor_role,
    ladder_fn=_motor_ladder_fn,
    tournament_key_fn=_motor_tournament_key,
))


# --- Esports (10th sport): per-game / per-map two-way dutch books + tournament-winner field -----------
# Grounded in a read-only live probe (2026-06-08) of /series (cursor-paginated) + nested-market events;
# see .kss/topics/sport-generalization/note-20260608-esports-probe.md.
#   * Identity: custom_strike.esports_competitor (stable UUID) on every game/map/winner market;
#     yes_sub_title is the team name.
#   * KX*GAME (match winner) and KX*MAP (map winner) are 2-market mutually_exclusive events and DRAW-FREE
#     (rules_secondary empty; no tie/$0.50 clause — overtime breaks ties), so the pair is MECE by shape →
#     game_mece_by_shape stays True (default) and dutchbook._detect_pair books the "game" family ungated
#     (unlike NFL). Both ride the "game" family. No head-to-head series → match_family="".
#   * Generic per-title winner series (KXCS2, KXDOTA2, …) carry the live tournament event (e.g.
#     KXCS2-IEMCOL26 = 32 ME markets) → "winner" family → inherits field_families={"winner"} →
#     dutchbook._detect_field overround when priced.
#   * family_fn is a STRICT exact-equality allow-list: total-maps, qualifiers, props/MVP/rank/roster,
#     legacy CSGO, dupes, the test series, and event-specific majors all resolve to "other" (and, being
#     unowned, never reach the engine — they resolve to the UNKNOWN sport and are never fetched).
#     Event-specific futures, qualifier ladders, opponent labels, tag discovery and /milestones grouping
#     are deliberately v2 (curated coverage, maintained allow-list).
_ESPORTS_GAME = frozenset({                                     # per-game + per-map two-way "game" family
    "KXCS2GAME", "KXCS2MAP", "KXLOLGAME", "KXLOLMAP", "KXVALORANTGAME", "KXVALORANTMAP",
    "KXDOTA2GAME", "KXDOTA2MAP", "KXCODGAME", "KXCODMAP", "KXR6GAME", "KXR6MAP",
    "KXOWGAME", "KXRLGAME", "KXRLMAP",
})
_ESPORTS_WINNER = frozenset({                                   # per-title tournament-winner FIELDS
    "KXCS2", "KXDOTA2", "KXCOD", "KXVALORANT", "KXR6", "KXOVERWATCH",
    "KXPUBG", "KXBRAWLSTARS", "KXCROSSFIRE", "KXROCKETLEAGUE", "KXLEAGUEWORLDS",
})
_ESPORTS_EXACT = _ESPORTS_GAME | _ESPORTS_WINNER
_ESPORTS_DEFAULT = (                                            # bounded hosted-scan subset (big titles)
    "KXCS2GAME", "KXCS2MAP", "KXLOLGAME", "KXLOLMAP", "KXVALORANTGAME", "KXVALORANTMAP",
    "KXDOTA2GAME", "KXDOTA2MAP", "KXCODGAME", "KXCODMAP", "KXR6GAME", "KXR6MAP",
    "KXCS2", "KXVALORANT", "KXDOTA2", "KXR6", "KXCOD", "KXLEAGUEWORLDS",
)
_ESPORTS_CATEGORY = {
    "game": "Game / map (not laddered)", "winner": "Tournament winner", "other": "Other",
}


def _esports_family(cfg: SportConfig, series_ticker: str) -> str:
    t = (series_ticker or "").upper()
    if t in _ESPORTS_GAME:
        return "game"                                          # 2-outcome game/map → dutch book
    if t in _ESPORTS_WINNER:
        return "winner"                                        # win-the-tournament field → overround
    return "other"                                             # totalmaps/qualifiers/props/dupes/test/…


def _esports_stage(cfg: SportConfig, family: str, market: dict[str, Any]) -> str:
    return "Champion" if family == "winner" else ""


def _esports_node(cfg: SportConfig, family: str, stage: str) -> str | None:
    return None                                                # no containment ladder in v1


def _esports_division(cfg: SportConfig, series_ticker: str) -> str:
    """UI title split from the series ticker (only owned tickers reach this)."""
    t = (series_ticker or "").upper()
    if t.startswith(("KXCS2", "KXCSGO")):
        return "CS2"
    if t.startswith(("KXLOL", "KXLEAGUE")):
        return "LoL"
    if t.startswith("KXVAL"):
        return "Valorant"
    if t.startswith("KXDOTA"):
        return "Dota 2"
    if t.startswith("KXCOD"):
        return "Call of Duty"
    if t.startswith("KXR6"):
        return "R6"
    if t.startswith(("KXOW", "KXOVERWATCH")):
        return "Overwatch"
    if t.startswith("KXPUBG"):
        return "PUBG"
    if t.startswith(("KXRL", "KXROCKETLEAGUE")):
        return "Rocket League"
    if t.startswith("KXBRAWL"):
        return "Brawl Stars"
    if t.startswith("KXCROSSFIRE"):
        return "Crossfire"
    return ""


_ESPORTS_TITLES = ["CS2", "LoL", "Valorant", "Dota 2", "Call of Duty", "R6", "Overwatch",
                   "PUBG", "Rocket League", "Brawl Stars", "Crossfire"]

ESPORTS = register(SportConfig(
    sport_id="esports", label="Esports", emoji="\U0001f3ae",
    series_prefixes=(),                                         # exact-only ownership (curated allow-list)
    default_series=_ESPORTS_DEFAULT,
    winner_tickers=frozenset(),
    identity=IdentityResolver(candidate_paths=("custom_strike.esports_competitor",),
                              id_label="esports_competitor"),
    ladder=_EMPTY_LADDER,                                       # no containment ladder in v1
    category_labels=_ESPORTS_CATEGORY,
    round_patterns=(),
    stage_rank={"Champion": 1},
    ladder_families=frozenset(),                                # nothing laddered
    match_family="",                                            # field sport — games ride the "game" family
    divisions={t: [t] for t in _ESPORTS_TITLES} | {"All": list(_ESPORTS_TITLES)},
    division_label="Title",
    family_fn=_esports_family,
    # A map/game is one contest (0); a per-title event winner is won across a bracket of matches (1).
    family_levels={"game": 0, "winner": 1},
    stage_fn=_esports_stage,
    node_fn=_esports_node,
    division_fn=_esports_division,
    exact_series=_ESPORTS_EXACT,
    # game_mece_by_shape stays True (default): esports game/map markets are draw-free → ungated dutch book.
    # field_families stays {"winner"} (default): one-winner tournament fields get the overround.
))
