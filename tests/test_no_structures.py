"""Unit tests for the NO-anchored structures detector (`no_structures.find_no_structures`) + its viewmodel
section. Synthetic rows shaped like `data.build_contracts` output; assertions on band/outright economics,
duplicate suppression, skip rules, and the speculative-isolation contract.
"""
import pandas as pd

import api
import config
import consistency
import no_structures
import scanner
import sports
import webui.viewmodel as vm

# Tennis advance ladder (broad→deep): Reach Semifinal ⊇ Reach Final ⊇ Win Tournament.
_PARENT = "Reach Semifinal"   # broader
_CHILD = "Reach Final"        # deeper


def market(node, *, yes_ask_c=None, yes_bid_c=None, no_ask_c=None, display_c=None,
           yes_bid_size=200, yes_ask_size=200, quality="Tight", status="active", subpenny=False,
           player="Sinner", player_key="uuid-sinner", tournament="French Open", kind="advance",
           series="KXATPADVANCE", category="Stage advancement"):
    """One advance-market row as produced by data.build_contracts (only the fields the detector reads)."""
    return {
        "player": player, "player_key": player_key, "tournament": tournament, "tour": "ATP",
        "series": series, "kind": kind, "ladder_node": node, "stage": None, "category": category,
        "quote_quality": quality, "status": status, "subpenny": subpenny,
        "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_ask_c": no_ask_c,
        "yes_bid_size": yes_bid_size, "yes_ask_size": yes_ask_size,
        "display_c": display_c, "display_pct": None,
        "contract": node, "market_ticker": f"KXATPADVANCE-{node.replace(' ', '')}",
        "kalshi_url": "https://kalshi.com/x",
    }


def _bands(findings):
    return [f for f in findings if f["status"] == no_structures.NO_STRUCTURE_BAND]


def _outrights(findings):
    return [f for f in findings if f["status"] == no_structures.NO_STRUCTURE_OUTRIGHT]


# --- band economics ----------------------------------------------------------------------------------
def test_band_cost_over_100_is_bounded_loss():
    # parent Reach SF YES ask 96; child Reach Final NO ask 10 → cost 106, max loss 6, band pays 200.
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    bands = _bands(no_structures.find_no_structures([parent, child]))
    assert len(bands) == 1
    b = bands[0]
    assert b["cost_c"] == 106 and b["max_loss_c"] == 6
    assert b["worst_case_profit_c"] == -6 and b["best_case_profit_c"] == 94
    assert b["buy_no_c"] == 10 and b["action_1_price_c"] == 96
    assert b["child_node"] == _CHILD and b["parent_node"] == _PARENT
    assert b["exec_min_size"] == 200 and b["display_spread_c"] == 6


def test_band_cost_below_100_suppressed_as_strict_cross():
    # parent ask 80, child NO ask 10 (child YES bid 90 > parent ask 80) → cost 90 < 100 = an EXECUTABLE
    # containment cross the consistency checker owns. No band emitted.
    parent = market(_PARENT, yes_ask_c=80, yes_bid_c=78, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=92, yes_bid_c=90, no_ask_c=10)
    assert _bands(no_structures.find_no_structures([parent, child])) == []


def test_band_cost_exactly_100_emitted_zero_loss_with_caveat():
    parent = market(_PARENT, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    child = market(_CHILD, yes_ask_c=88, yes_bid_c=86, no_ask_c=10, display_c=85)
    bands = _bands(no_structures.find_no_structures([parent, child]))
    assert len(bands) == 1 and bands[0]["cost_c"] == 100 and bands[0]["max_loss_c"] == 0
    assert "free money" in bands[0]["settlement_caveat"]


def test_band_over_maxloss_cap_skipped():
    # cost 141 → max loss 41 > NO_STRUCTURE_BAND_MAX_LOSS_C (40) → skipped.
    assert config.NO_STRUCTURE_BAND_MAX_LOSS_C == 40
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=50, yes_bid_c=48, no_ask_c=45)   # cost 96+45=141
    assert _bands(no_structures.find_no_structures([parent, child])) == []


def test_band_breakeven_equals_max_loss():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    band = scanner._to_unified_no_structure(_bands(no_structures.find_no_structures([parent, child]))[0],
                                            sports.TENNIS)
    assert vm._breakeven_pct(band) == 6.0          # == max loss ¢, by the containment band identity


# --- outright economics ------------------------------------------------------------------------------
def test_outright_cheap_no_emitted_dear_no_skipped():
    cheap = market(_CHILD, yes_ask_c=92, yes_bid_c=90, no_ask_c=10)   # buy NO 10 ≤ 25 → emitted
    dear = market(_PARENT, yes_ask_c=72, yes_bid_c=70, no_ask_c=30)   # buy NO 30 > 25 → skipped
    outs = _outrights(no_structures.find_no_structures([cheap, dear]))
    assert {o["buy_no_c"] for o in outs} == {10}
    o = outs[0]
    assert o["cost_c"] == 10 and o["max_loss_c"] == 10
    assert o["worst_case_profit_c"] == -10 and o["best_case_profit_c"] == 90
    assert o["action_2_side"] == "buy_no" and o["action_1_side"] is None


def test_outright_buy_no_falls_back_to_yes_bid():
    # no no_ask_c field → buy NO = 100 − yes_bid_c = 100 − 88 = 12.
    r = market(_CHILD, yes_ask_c=90, yes_bid_c=88)
    outs = _outrights(no_structures.find_no_structures([r]))
    assert len(outs) == 1 and outs[0]["buy_no_c"] == 12


# --- skip rules --------------------------------------------------------------------------------------
def test_skips_inactive_no_quote_crossed_subpenny_zero_size():
    base = dict(yes_ask_c=92, yes_bid_c=90, no_ask_c=10)
    assert no_structures.find_no_structures([market(_CHILD, status="finalized", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="No quote", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="Crossed", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, quality="One-sided", **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, subpenny=True, **base)]) == []
    assert no_structures.find_no_structures([market(_CHILD, yes_bid_size=0, **base)]) == []


def test_band_requires_both_legs_firm():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, status="finalized")
    assert _bands(no_structures.find_no_structures([parent, child])) == []


# --- viewmodel: filtering, ranking, isolation --------------------------------------------------------
def _unified(rows):
    def fetch(sid):
        return pd.DataFrame(rows) if sid == "tennis" else None
    unified, _ = scanner.unified_opportunities(fetch)
    return unified.to_dict("records")


def test_view_filters_kind_maxloss_and_buy_no():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    opps = _unified([parent, child])
    assert all(o["exec_gap_c"] != o["exec_gap_c"] or o["exec_gap_c"] is None      # exec_gap_c NaN/None
               for o in opps if o["bucket"] == "no_structure")
    bands = vm.no_structure_view(opps, max_loss_c=10, kind="band")
    assert len(bands) == 1 and bands[0]["status"] == no_structures.NO_STRUCTURE_BAND
    outs = vm.no_structure_view(opps, max_loss_c=100, kind="outright")
    assert outs and all(not vm._is_band(o) for o in outs)
    # max Buy-NO gate: the 6¢ outright (parent NO) passes a 6¢ cap; the 10¢ child NO does not.
    capped = vm.no_structure_view(opps, max_loss_c=100, kind="outright", max_buy_no_c=6)
    assert {o["action_2_price_c"] for o in capped} == {6}


def test_view_good_quote_only_default_filters_wide():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95, quality="Wide")
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89, quality="Wide")
    opps = _unified([parent, child])
    assert vm.no_structure_view(opps, max_loss_c=100) == []                       # wide hidden by default
    assert vm.no_structure_view(opps, max_loss_c=100, good_quote_only=False)      # shown when opted out


def test_order_leads_with_lowest_max_loss_then_breakeven():
    a = {"opportunity_id": "a", "bucket": "no_structure", "worst_case_profit_c": -12,
         "best_case_profit_c": 88, "best_payout": 100, "action_2_price_c": 12}
    b = {"opportunity_id": "b", "bucket": "no_structure", "worst_case_profit_c": -3,
         "best_case_profit_c": 97, "action_2_price_c": 3}
    ordered = vm._no_structure_order([a, b])
    assert [o["opportunity_id"] for o in ordered] == ["b", "a"]   # lower max loss (3) first


def test_row_builder_fields():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    opps = _unified([parent, child])
    band = vm.no_structure_view(opps, max_loss_c=10, kind="band")[0]
    row = vm.no_structure_row(band, set())
    assert row["kind"] == "Band" and row["buy_no"] == 10 and row["parent_yes"] == 96
    assert row["cost"] == 106 and row["max_loss"] == 6 and row["bonus_profit"] == 94
    assert row["convexity"] == round(200 / 106, 2) and row["breakeven"] == 6.0
    assert "but not" in row["wins_if"]


def test_bucket_sets_in_sync():
    assert set(scanner.BUCKET_PRIORITY) == set(consistency.DASHBOARD_BUCKETS)
    assert consistency.bucket_of({"status": "NO_STRUCTURE_BAND"}) == "no_structure"
    assert consistency.bucket_of({"status": "NO_STRUCTURE_OUTRIGHT"}) == "no_structure"


# --- settlement-LEVEL taxonomy (Event / Tournament / Championship split) ------------------------------
def _sc(cfg, family, stage=None):
    return no_structures.scope_for(cfg, family, stage)


# Families that family_fn can emit but the NO-fade taxonomy intentionally excludes.
_ACCEPTED_EXCLUDED = frozenset({"other", "prop", "exact_order", "group_bottom", "stage_of_elim", ""})


def test_scope_for_classification_matrix():
    """The non-negotiable matrix: settlement LEVEL by sport. The SAME family name maps to DIFFERENT levels
    per sport (tennis 'match' = a single match = Event; NBA 'match' = the bo7 series = Tournament; tennis
    'winner' = win the tournament = Tournament; NBA 'winner' = the title = Championship)."""
    T = sports.TENNIS
    # Event (0) — a single contest (incl. field results: golf / motorsport).
    assert _sc(T, "match") == "event" and _sc(T, "set_winner") == "event" and _sc(T, "exact_score") == "event"
    for sp in ("NBA", "NHL", "MLB", "SOCCER", "ESPORTS"):
        assert _sc(getattr(sports, sp), "game") == "event"
    assert _sc(sports.GOLF, "advance") == "event" and _sc(sports.GOLF, "winner") == "event"
    assert _sc(sports.MOTORSPORT, "race_winner") == "event" and _sc(sports.MOTORSPORT, "pole") == "event"
    assert _sc(sports.MOTORSPORT, "advance") == "event"
    # Tournament (1) — one level up (a group of contests within one competition/season).
    assert _sc(T, "advance") == "tournament" and _sc(T, "winner") == "tournament"
    assert _sc(sports.NBA, "match") == "tournament"          # bo7 series (NBA's "match" family)
    assert _sc(sports.NHL, "match") == "tournament" and _sc(sports.WNBA, "match") == "tournament"
    assert _sc(sports.NFL, "advance") == "tournament" and _sc(sports.NFL, "winner") == "tournament"
    assert _sc(sports.SOCCER, "advance") == "tournament" and _sc(sports.SOCCER, "winner") == "tournament"
    assert _sc(sports.SOCCER, "group_winner") == "tournament"
    assert _sc(sports.MOTORSPORT, "winner") == "tournament"
    assert _sc(sports.ESPORTS, "winner") == "tournament"
    # Championship (2) — two levels up (above a series layer, or across tournaments).
    assert _sc(sports.NBA, "advance") == "championship" and _sc(sports.NBA, "winner") == "championship"
    assert _sc(sports.NHL, "winner") == "championship"
    assert _sc(sports.MLB, "advance") == "championship" and _sc(sports.MLB, "winner") == "championship"
    assert _sc(T, "grand_slam") == "championship"
    # The owner's asymmetry, asserted directly: "win the NBA title" ≠ "win the World Cup".
    assert _sc(sports.NBA, "winner") == "championship" and _sc(sports.SOCCER, "winner") == "tournament"
    assert _sc(sports.NFL, "winner") == "tournament"        # Super Bowl (no series layer) = Tournament
    # Excluded (prop / other / diagnostic-only families) → None.
    assert _sc(T, "other") is None and _sc(T, "prop") is None and _sc(T, "") is None
    assert _sc(sports.SOCCER, "exact_order") is None and _sc(sports.SOCCER, "stage_of_elim") is None


def test_scope_stage_aware_reach_playoffs():
    """The "Reach Playoffs" fix: team `advance` SPANS levels by stage. Regular-season qualification
    (stage "Playoffs") = tournament; the series-chain rungs (conference/league/semis/finals) = championship."""
    assert _sc(sports.NBA, "advance", "Playoffs") == "tournament"
    assert _sc(sports.NBA, "advance", "Conference") == "championship"
    assert _sc(sports.NHL, "advance", "Playoffs") == "tournament"
    assert _sc(sports.NHL, "advance", "Conference") == "championship"
    assert _sc(sports.MLB, "advance", "Playoffs") == "tournament"
    assert _sc(sports.MLB, "advance", "League") == "championship"
    assert _sc(sports.WNBA, "advance", "Playoffs") == "tournament"
    assert _sc(sports.WNBA, "advance", "Semifinals") == "championship"
    assert _sc(sports.WNBA, "advance", "Finals") == "championship"
    # winner (the title) is always championship for these.
    assert _sc(sports.NBA, "winner") == "championship" and _sc(sports.MLB, "winner") == "championship"
    # Stage normalisation (whitespace) + unknown stage → the "*" default (championship), intentionally.
    assert _sc(sports.NBA, "advance", " Playoffs ") == "tournament"
    assert _sc(sports.NBA, "advance", "Some-New-Round") == "championship"
    # NFL is single-elimination → `advance` does NOT span levels: every stage is tournament.
    assert _sc(sports.NFL, "advance", "Playoffs") == "tournament"
    assert _sc(sports.NFL, "advance", "Conference") == "tournament"


def test_reach_playoffs_tickers_classify_as_tournament():
    """Live ticker → family/stage/scope, so a casing/string drift in a stage_fn is caught (audit #10)."""
    cases = [(sports.NBA, "KXNBAPLAYOFF"), (sports.WNBA, "KXWNBAPLAYOFF"), (sports.NHL, "KXNHLPLAYOFF"),
             (sports.MLB, "KXMLBPLAYOFFS"), (sports.NFL, "KXNFLPLAYOFF")]
    for cfg, ticker in cases:
        mc = cfg.classify(ticker, {"ticker": f"{ticker}-26X"})
        assert mc.family == "advance" and mc.stage == "Playoffs", f"{ticker} → {mc.family}/{mc.stage}"
        assert no_structures.scope_for(cfg, mc.family, mc.stage) == "tournament"
    # the conference/league rungs are the deeper (championship) stage for the series-layer sports
    assert sports.NBA.classify("KXNBAEAST", {"ticker": "KXNBAEAST-26"}).stage == "Conference"
    assert sports.MLB.classify("KXMLBAL", {"ticker": "KXMLBAL-26"}).stage == "League"


def test_scope_registry_guard_every_owned_family_is_mapped_or_excluded():
    """Fail-closed: every family any sport's family_fn emits over its OWNED tickers
    (default_series + winner_tickers + exact_series) is either in that sport's `family_levels` or an
    explicitly accepted-excluded family. A new, unmapped family makes this test fail. Also: scope_for
    never raises, returns only event/tournament/championship/None, and every level is 0/1/2."""
    for cfg in sports._REGISTRY.values():
        for fam, lvl in (cfg.family_levels or {}).items():
            vals = lvl.values() if isinstance(lvl, dict) else (lvl,)   # a family may span levels by stage
            for v in vals:
                assert v in (0, 1, 2), f"{cfg.sport_id}: family {fam!r} has invalid level {v}"
        for t in set(cfg.default_series) | set(cfg.winner_tickers) | set(cfg.exact_series):
            fam = cfg.family_of(t)
            assert fam in (cfg.family_levels or {}) or fam in _ACCEPTED_EXCLUDED, (
                f"{cfg.sport_id}: family {fam!r} (ticker {t}) is neither in family_levels nor accepted-excluded")
            assert no_structures.scope_for(cfg, fam) in {"event", "tournament", "championship", None}


def test_outright_excluded_family_still_emits_with_scope_none():
    # No source suppression (audit): an excluded-kind cheap NO still EMITS (audit evidence) — only tagged None.
    r = market(_CHILD, yes_ask_c=92, yes_bid_c=90, no_ask_c=10, kind="other",
               series="KXFOOTHER", category="Other")
    outs = _outrights(no_structures.find_no_structures([r]))
    assert len(outs) == 1 and outs[0]["scope"] is None


def test_band_scope_is_its_child_rung_level():
    # The default `market(...)` rows are tennis `advance` (level 1) → a band over them is Tournament.
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    assert _bands(no_structures.find_no_structures([parent, child]))[0]["scope"] == "tournament"


def _nba_row(node, stage, no_ask, series, ticker):
    """One NBA advance-ladder row (Reach Playoffs / Win Conference …) for the stage-aware fix tests."""
    return {"player": "Lakers", "player_key": "uuid-lal", "tournament": "NBA · 2026", "tour": "",
            "series": series, "kind": "advance", "ladder_node": node, "stage": stage, "stage_rank": 0,
            "category": "", "quote_quality": "Tight", "status": "active", "subpenny": False,
            "yes_bid_c": 100 - no_ask - 2, "yes_ask_c": 100 - no_ask, "no_ask_c": no_ask,
            "yes_bid_size": 500, "yes_ask_size": 500, "display_c": 100 - no_ask, "display_pct": 100 - no_ask,
            "contract": node, "market_ticker": ticker, "kalshi_url": "x"}


def test_outright_reach_playoffs_is_tournament():
    # THE FIX: an outright NO on "Reach Playoffs" (regular-season qualification) → Tournament, not Championship.
    r = _nba_row("Reach Playoffs", "Playoffs", 10, "KXNBAPLAYOFF", "KXNBAPLAYOFF-26-LAL")
    outs = _outrights(no_structures.find_no_structures([r]))
    assert len(outs) == 1 and outs[0]["scope"] == "tournament"


def test_band_team_child_conference_is_championship():
    # A team band fades the deeper rung (Win Conference) → its stage governs → Championship.
    parent = _nba_row("Reach Playoffs", "Playoffs", 7, "KXNBAPLAYOFF", "KXNBAPLAYOFF-26-LAL")   # Buy YES ask 93
    child = _nba_row("Win Conference", "Conference", 12, "KXNBAEAST", "KXNBAEAST-26-LAL")        # Buy NO 12
    bands = _bands(no_structures.find_no_structures([parent, child]))
    assert len(bands) == 1 and bands[0]["scope"] == "championship"


def test_scope_survives_unified_pipeline():
    parent = market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95)
    child = market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)
    opps = [o for o in _unified([parent, child]) if o["bucket"] == "no_structure"]
    assert opps and all(o["no_structure_scope"] == "tournament" for o in opps)   # tennis advance band + outright


# --- viewmodel: scope partition + legacy + isolation -------------------------------------------------
def _ns_opp(oid, scope, **kw):
    base = {"opportunity_id": oid, "bucket": "no_structure", "worst_case_profit_c": -10,
            "best_case_profit_c": 90, "action_2_price_c": 10, "comp_quote_quality": "Tight"}
    if scope is not _SENTINEL:
        base["no_structure_scope"] = scope
    base.update(kw)
    return base


_SENTINEL = object()


def test_scoped_views_partition_and_excluded_count():
    opps = [_ns_opp("e1", "event"), _ns_opp("t1", "tournament"),
            _ns_opp("c1", "championship"), _ns_opp("c2", "championship"),
            _ns_opp("x1", None), _ns_opp("x2", "series"),       # None + retired value → excluded
            _ns_opp("x3", "bogus"), _ns_opp("L", _SENTINEL)]    # invalid + legacy-missing → excluded
    v = vm.no_structure_scoped_views(opps, max_loss_c=100)
    assert len(v["event"]) == 1 and len(v["tournament"]) == 1 and len(v["championship"]) == 2
    assert v["_excluded_count"] == 4                            # None + series + bogus + legacy


def test_scoped_views_all_union_equals_partition():
    # The "All" view = the union of the three level buckets (no double-count, no drop).
    opps = [_ns_opp("e1", "event"), _ns_opp("t1", "tournament"), _ns_opp("c1", "championship")]
    v = vm.no_structure_scoped_views(opps, max_loss_c=100)
    union = {o["opportunity_id"] for s in ("event", "tournament", "championship") for o in v[s]}
    assert union == {"e1", "t1", "c1"}


def test_no_scope_taxonomy_is_legacy_detects_retired_values():
    assert vm.no_scope_taxonomy_is_legacy([_ns_opp("a", "series")]) is True
    assert vm.no_scope_taxonomy_is_legacy([_ns_opp("a", "match_game")]) is True
    assert vm.no_scope_taxonomy_is_legacy([_ns_opp("a", "championship")]) is False   # new value
    assert vm.no_scope_taxonomy_is_legacy([_ns_opp("a", "event")]) is False
    assert vm.no_scope_taxonomy_is_legacy([]) is False


def test_scope_of_excludes_retired_and_missing_never_defaulting():
    assert vm._scope_of({"opportunity_id": "x"}) is None        # no field → None, never a silent default
    assert vm._scope_of({"no_structure_scope": "event"}) == "event"
    assert vm._scope_of({"no_structure_scope": "tournament"}) == "tournament"
    assert vm._scope_of({"no_structure_scope": "series"}) is None     # retired
    assert vm._scope_of({"no_structure_scope": "bogus"}) is None


def test_no_structure_scope_isolation_from_bucket_and_rank():
    band = {"status": "NO_STRUCTURE_BAND"}
    assert consistency.bucket_of(band) == consistency.bucket_of({**band, "no_structure_scope": "championship"})
    r = {"bucket": "no_structure", "exec_gap_c": None, "opportunity_id": "z"}
    assert scanner._rank_key(r) == scanner._rank_key({**r, "no_structure_scope": "event"})


def test_no_structure_scope_declared_in_api_and_export_schema():
    assert "no_structure_scope" in api.Opportunity.model_fields            # extra="ignore" would drop it
    assert api.Opportunity(no_structure_scope="event").no_structure_scope == "event"
    assert "no_structure_scope" in scanner.UNIFIED_COLUMNS                 # export pins it in opportunities.csv


def test_championship_columns_are_display_only():
    """HARD isolation (audit #4): scope + title-path cells must NEVER change executable classification,
    bucketing, or ranking. The full executable projection is identical with vs without those display fields."""
    rows = [market(_PARENT, yes_ask_c=96, yes_bid_c=94, no_ask_c=6, display_c=95),
            market(_CHILD, yes_ask_c=90, yes_bid_c=88, no_ask_c=10, display_c=89)]
    opps = _unified(rows)

    def proj(o):
        return (o.get("opportunity_id"), o.get("bucket"), o.get("status"), o.get("tradable_now"),
                o.get("exec_gap_c"), scanner._rank_key(o))
    before = [proj(o) for o in opps]
    # Attach the display-only fields the way the dashboard would, then re-project — nothing executable moves.
    polluted = [{**o, "no_structure_scope": "championship",
                 "title_tournaments": "4", "title_events_label": "16–28", "title_events_max": 28} for o in opps]
    assert [proj(o) for o in polluted] == before
    # bucket_of ignores them too.
    for o in opps:
        assert consistency.bucket_of(o) == consistency.bucket_of(
            {**o, "no_structure_scope": "championship", "title_events_max": 28})


def test_title_path_fields_not_in_unified_or_api_schema():
    """No schema leak: the title-path cells are render-time only — never in the stored opp / REST model."""
    for f in ("title_tournaments", "title_events_label", "title_events_max"):
        assert f not in scanner.UNIFIED_COLUMNS
        assert f not in api.Opportunity.model_fields


def test_title_path_cells_for_only_championship_rows():
    champ_nba = {"bucket": "no_structure", "no_structure_scope": "championship", "sport": "nba"}
    cells = vm.title_path_cells_for(champ_nba)
    assert cells["title_tournaments"] == "4" and cells["title_events_label"] == "16–28" and cells["title_events_max"] == 28
    champ_mlb = vm.title_path_cells_for({"no_structure_scope": "championship", "sport": "mlb"})
    assert champ_mlb["title_tournaments"] == "3–4" and champ_mlb["title_events_label"] == "11–22"
    # tennis grand slam → 28 (min==max → single number, no en-dash)
    gs = vm.title_path_cells_for({"no_structure_scope": "championship", "sport": "tennis"})
    assert gs["title_tournaments"] == "4" and gs["title_events_label"] == "28"
    # An ordinary "Win French Open" is TOURNAMENT scope → no title-path cells (audit #9/#42).
    assert vm.title_path_cells_for({"no_structure_scope": "tournament", "sport": "tennis"})["title_tournaments"] is None
    # A non-championship sport (golf=Event, soccer=Tournament) → blank even if mis-tagged championship.
    assert vm.title_path_cells_for({"no_structure_scope": "championship", "sport": "golf"})["title_events_max"] is None


def test_sportconfig_title_path_cells():
    assert sports.NBA.title_path_cells()["title_events_max"] == 28
    assert sports.MLB.title_path_cells()["title_tournaments"] == "3–4"
    assert sports.WNBA.title_path_cells()["title_events_label"] == "9–15"
    assert sports.NFL.title_path_cells()["title_tournaments"] is None       # single-elim → no title_path
    assert all(v in (0, 1, 2) for v in sports.NBA.family_levels["advance"].values())   # dict-valued advance


# --- ladder-depth metrics (display-only diagnostics) -------------------------------------------------
def test_ladder_metrics_values():
    rungs = [{"rung": "Reach SF", "no_c": 10, "cheap": True},
             {"rung": "Reach Final", "no_c": 20, "cheap": True},
             {"rung": "Win Tournament", "no_c": 40, "cheap": False}]
    m = vm._ladder_metrics(rungs, ("Reach SF", "Reach Final", "Win Tournament"))
    assert m["depth"] == 3 and m["steps"] == 2 and m["n_cheap"] == 2
    assert m["avg_no_c"] == round((10 + 20 + 40) / 3, 1) and m["deepest_no_c"] == 40
    assert m["deepest_per_step"] == 20.0 and m["total_fade_c"] == 70.0
    assert m["gradient_c_per_step"] == 15.0 and m["span_c"] == 30.0
    assert m["cheapest_no_c"] == 10 and m["cheapest_rung"] == "Reach SF"


def test_ladder_metrics_single_firm_rung_is_none_safe():
    m = vm._ladder_metrics([{"rung": "Win", "no_c": None, "cheap": False}], ("Win",))
    assert m["depth"] == 1 and m["steps"] == 0
    assert m["avg_no_c"] is None and m["deepest_per_step"] is None and m["gradient_c_per_step"] is None


def test_widened_default_filters_show_all_stored():
    # Defaults sit at the persisted caps so the section shows every stored NO fade by default (quote-gated).
    assert config.NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C == config.NO_STRUCTURE_OUTRIGHT_MAX_C == 25
    assert config.NO_STRUCTURE_DEFAULT_MAX_LOSS_C == config.NO_STRUCTURE_BAND_MAX_LOSS_C == 40


def test_scoped_views_good_quote_only_threading():
    wide = _ns_opp("w", "championship", comp_quote_quality="Wide")
    assert vm.no_structure_scoped_views([wide], max_loss_c=100)["championship"] == []   # default: Tight/OK only
    widened = vm.no_structure_scoped_views([wide], max_loss_c=100, good_quote_only=False)
    assert len(widened["championship"]) == 1                                            # opt-in includes wide


def test_ladder_summary_row_surfaces_metrics():
    card = {"player": "France", "player_key": "uuid-fr", "sport_label": "Soccer", "win_label": "Win the World Cup",
            "card_score": 36.0, "implied_win_pct": 12.0, "inverted": False,
            "metrics": vm._ladder_metrics([{"rung": "RO16", "no_c": 10, "cheap": True},
                                           {"rung": "Win", "no_c": 30, "cheap": True}], ("RO16", "Win"))}
    row = vm.ladder_summary_row(card)
    assert row["player"] == "France" and row["depth"] == 2 and row["avg_no"] == 20.0
    assert row["max_cascade"] == 36.0 and row["implied_yes"] == 12.0 and row["inverted"] == ""
