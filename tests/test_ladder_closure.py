"""Full transitive ladder-closure logic test (commit e0b541b).

`consistency.build_checks` recognizes EVERY (broader ⊇ deeper) containment pair in a ladder, not
just adjacent rungs (upper-triangular closure over `LadderSpec.node_order`). This file proves the
closure is used CORRECTLY in two layers:

  Part A — structural invariants over the WHOLE sport registry. These guarantee the closure can
           never emit a false/inverted relationship for ANY registered sport: node_order is a
           consistently-ordered total chain, optional side-branch leaves are excluded from it, and
           every adjacent pair agrees with node_order on which leg is broader.

  Part B — the behavioral outcome matrix on a real 3-rung ladder via build_checks: clean,
           non-adjacent cross, missing-middle bridge, direction, dedup/uniqueness, and that a
           closure pair is classified EXACTLY like an adjacent pair.
"""
import pandas as pd
import pytest

import consistency
import sports

# --------------------------------------------------------------------------------------------------
# Part A — structural invariants across every registered sport's static ladder
# --------------------------------------------------------------------------------------------------

def _static_ladders():
    """(sport_id, LadderSpec) for every sport that declares a static containment ladder. Motorsport
    builds its ladder per-race via ladder_fn (cfg.ladder is None) and is exercised in Part B-style
    per-sport tests elsewhere; the closure logic it feeds is identical."""
    out = []
    for cfg in sports.all_sports():
        spec = getattr(cfg, "ladder", None)
        if spec is not None and spec.node_order:
            out.append((cfg.sport_id, spec))
    return out


def test_registry_actually_has_ladders_to_check():
    """Guard against a silently-empty sweep: the static-ladder sports must include the core ones."""
    ids = {sid for sid, _ in _static_ladders()}
    # tennis/NBA/golf/soccer/MLB/NHL/NFL/WNBA all ship a static node_order.
    assert {"tennis", "soccer", "nba", "golf"} <= ids, ids


@pytest.mark.parametrize("sport_id,spec", _static_ladders(), ids=lambda v: v if isinstance(v, str) else "")
def test_node_order_has_no_duplicates(sport_id, spec):
    assert len(spec.node_order) == len(set(spec.node_order)), f"{sport_id}: duplicate rung in node_order"


@pytest.mark.parametrize("sport_id,spec", _static_ladders(), ids=lambda v: v if isinstance(v, str) else "")
def test_optional_children_excluded_from_node_order(sport_id, spec):
    """A side-branch leaf (e.g. soccer 'Win group') MUST NOT be in node_order — otherwise the
    upper-triangular closure would linearise it against deeper rungs it is incomparable to."""
    overlap = set(spec.optional_children) & set(spec.node_order)
    assert not overlap, f"{sport_id}: optional side-branch(es) {overlap} leaked into node_order"


@pytest.mark.parametrize("sport_id,spec", _static_ladders(), ids=lambda v: v if isinstance(v, str) else "")
def test_adjacent_pairs_agree_with_node_order_direction(sport_id, spec):
    """For every adjacent pair (child_deeper, parent_broader): the parent (broader) endpoint must be
    in node_order, and the child must be either in node_order (DEEPER ⇒ later index) or an optional
    leaf. This is the invariant the closure relies on: iterating node_order with i<j yields a deeper
    j, so a closure pair can never be inverted."""
    idx = {n: i for i, n in enumerate(spec.node_order)}
    for child_deeper, parent_broader in spec.adjacent_pairs:
        assert parent_broader in idx, f"{sport_id}: adjacent parent {parent_broader!r} not in node_order"
        if child_deeper in spec.optional_children:
            continue                                          # side-branch: not linearised, OK
        assert child_deeper in idx, f"{sport_id}: adjacent child {child_deeper!r} not in node_order/optional"
        assert idx[parent_broader] < idx[child_deeper], (
            f"{sport_id}: adjacent pair direction disagrees with node_order: "
            f"{parent_broader!r}(broader) is not before {child_deeper!r}(deeper)")


@pytest.mark.parametrize("sport_id,spec", _static_ladders(), ids=lambda v: v if isinstance(v, str) else "")
def test_consecutive_node_order_rungs_are_covered_by_adjacent_pairs(sport_id, spec):
    """The linear chain must be FULLY covered by adjacent_pairs: every consecutive (broader, deeper)
    rung pair in node_order appears as an adjacent pair. This makes the closure's dedup-against-
    adjacent exact — every genuinely-adjacent rung is emitted once as adjacent, never as transitive."""
    adjacent = set(spec.adjacent_pairs)
    for broader, deeper in zip(spec.node_order, spec.node_order[1:]):
        assert (deeper, broader) in adjacent, (
            f"{sport_id}: consecutive rungs {broader!r}->{deeper!r} missing from adjacent_pairs")


def test_soccer_win_group_is_a_side_branch_not_a_rung():
    """Explicit regression lock: soccer 'Win group' stays a side-branch leaf (in adjacent_pairs +
    optional_children) and NEVER enters node_order — adding it there would make the closure compare
    a group winner against 'Reach Round of 16', which is unsound (a group winner can lose in the R32)."""
    spec = sports.get_sport("soccer").ladder
    assert "Win group" in spec.optional_children
    assert "Win group" not in spec.node_order
    assert ("Win group", "Reach Round of 32") in spec.adjacent_pairs


# --------------------------------------------------------------------------------------------------
# Part B — behavioral outcome matrix on the default 3-rung (tennis) ladder via build_checks
# --------------------------------------------------------------------------------------------------
# Node mapping produced by build_player_nodes for these rows:
#   advance/Semifinal -> "Reach Semifinal", advance/Final -> "Reach Final", winner/Champion -> "Win Tournament"
# node_order = (Reach Semifinal, Reach Final, Win Tournament); adjacent = {(Win,Final),(Final,SF)};
# so (Win Tournament <= Reach Semifinal) is the one NON-ADJACENT (closure) pair.
TENNIS_ORDER = ("Reach Semifinal", "Reach Final", "Win Tournament")
TRANSITIVE_CHAIN = "Win Tournament ≤ Reach Semifinal"


def _row(stage_kind, stage, display_c):
    kind = {"advance": "advance", "winner": "winner"}[stage_kind]
    return {
        "player": "P", "player_key": "uuid-p", "kind": kind, "stage": stage,
        "contract": f"{kind}-{stage}", "display_pct": float(display_c), "display_c": display_c,
        "yes_bid_c": max(display_c - 1, 0), "yes_ask_c": min(display_c + 1, 100),
        "yes_bid_pct": float(max(display_c - 1, 0)), "yes_ask_pct": float(min(display_c + 1, 100)),
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "volume": 10,
        "market_ticker": f"TICK-{stage}", "kalshi_url": "x",
    }


def _checks(*rows):
    return consistency.build_checks(pd.DataFrame(list(rows)))


def _by_chain(checks):
    return {c["chain"]: c for _, c in checks.iterrows()}


def _containment(checks):
    return checks[checks["relationship_type"].isin(["containment_adjacent", "containment_transitive"])]


def test_all_present_clean_emits_full_closure_count():
    """3 rungs present + consistent (60 ≥ 40 ≥ 20 broad→deep): containment pairs = n(n-1)/2 = 3
    (2 adjacent + 1 transitive), the closure pair is CLEAN, and it appears exactly once."""
    checks = _checks(_row("advance", "Semifinal", 60), _row("advance", "Final", 40),
                     _row("winner", "Champion", 20))
    cont = _containment(checks)
    assert len(cont) == 3, sorted(cont["chain"])
    by = _by_chain(checks)
    assert TRANSITIVE_CHAIN in by
    t = by[TRANSITIVE_CHAIN]
    assert t["relationship_type"] == "containment_transitive"
    assert t["status"] == "CLEAN"
    assert sum(c["chain"] == TRANSITIVE_CHAIN for _, c in checks.iterrows()) == 1


def test_transitive_direction_is_deeper_child_broader_parent():
    """Every closure row must point the right way: child = deeper node (later in node_order),
    parent = broader node (earlier). A flipped direction would invert the inequality being tested."""
    checks = _checks(_row("advance", "Semifinal", 60), _row("advance", "Final", 40),
                     _row("winner", "Champion", 20))
    idx = {n: i for i, n in enumerate(TENNIS_ORDER)}
    trans = checks[checks["relationship_type"] == "containment_transitive"]
    assert not trans.empty
    for _, r in trans.iterrows():
        assert idx[r["parent_node"]] < idx[r["child_node"]], (r["parent_node"], r["child_node"])


def test_missing_middle_bridge_catches_cross_adjacent_alone_would_miss():
    """The headline value of the closure: with the MIDDLE rung absent, adjacent checks only emit
    MISSING_LAYER for the gap — the closure compares the present endpoints directly and catches a
    real cross. Win bid 69 > Reach-Semifinal ask 41 ⇒ EXECUTABLE_VIOLATION on (Win ≤ SF), gap 28."""
    checks = _checks(_row("advance", "Semifinal", 40), _row("winner", "Champion", 70))  # no Final
    by = _by_chain(checks)
    assert "MISSING_LAYER" in set(checks["status"])               # the absent Final rung is surfaced
    assert TRANSITIVE_CHAIN in by
    t = by[TRANSITIVE_CHAIN]
    assert t["relationship_type"] == "containment_transitive"
    assert t["status"] == "EXECUTABLE_VIOLATION"
    assert t["executable_gap"] == 28                              # child bid 69 − parent ask 41


def test_missing_middle_clean_endpoints_stay_clean():
    """Same missing-middle shape but consistently priced (SF 60 ≥ Win 20): the bridge is CLEAN — the
    closure must not manufacture a violation merely because the middle rung is gone."""
    checks = _checks(_row("advance", "Semifinal", 60), _row("winner", "Champion", 20))  # no Final
    t = _by_chain(checks)[TRANSITIVE_CHAIN]
    assert t["status"] == "CLEAN"


def test_closure_pair_classified_identically_to_an_adjacent_pair():
    """The closure 'checks EXACTLY like an adjacent pair'. Drive the same two legs (SF ask 41,
    Win bid 69) through the closure (via the missing-middle bridge) and directly through _classify,
    and assert identical status + gap — proving no separate/weaker classification path exists."""
    semi = _row("advance", "Semifinal", 40)
    champ = _row("winner", "Champion", 70)
    t = _by_chain(_checks(semi, champ))[TRANSITIVE_CHAIN]
    direct = consistency._classify(champ, semi, False)            # child=deeper(Win), parent=broader(SF)
    assert t["status"] == direct["status"] == "EXECUTABLE_VIOLATION"
    assert t["executable_gap"] == direct["executable_gap"]


def test_closure_opportunity_ids_unique_and_deterministic():
    """No duplicate findings: every emitted row (adjacent + closure) has a unique, stable id that is
    byte-identical across rebuilds — so the closure can't double-count or churn ids between scans."""
    args = (_row("advance", "Semifinal", 60), _row("advance", "Final", 40), _row("winner", "Champion", 20))
    a = _checks(*args)
    b = _checks(*args)
    assert a["opportunity_id"].is_unique
    assert list(a["opportunity_id"]) == list(b["opportunity_id"])
    assert (a["opportunity_id"].str.len() == 16).all()


def test_closure_relationship_types_are_within_the_known_set():
    checks = _checks(_row("advance", "Semifinal", 60), _row("advance", "Final", 40),
                     _row("winner", "Champion", 20))
    assert set(checks["relationship_type"]) <= {
        "containment_adjacent", "containment_transitive", "match_alignment"}
