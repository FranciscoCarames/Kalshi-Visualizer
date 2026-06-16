"""Phase 2 B — the SPECULATIVE-ISOLATION invariant + reusable test template.

Canonical rule: every speculative DISPLAY/sort metric is display-only and must NEVER change the strict
executable findings — `consistency.bucket_of`, `scanner._rank_key`, the bucket / status / tradable_now /
blocked_reason / action text / prices / sizes / opportunity_id / rank order / any actionability label. New
speculative fields may exist on a row but must not alter executable behavior (behavioral equivalence, not
literal byte identity).

`assert_executable_unchanged(before, after)` is the helper PR E / F / G reuse to prove their additions are
isolated; the tests here lock down the two engine entry points directly.
"""
import consistency
import glossary
import scanner

# Display-only fields the speculative layer adds (PR M shipped: ev/breakeven/gap_vs_be/signal + the display
# outrights; E/F/G add resolution label, cheap_*, wins_if/max_units/quote_health). bucket_of/_rank_key must
# ignore ALL of these.
SPECULATIVE_FIELDS = {
    "ev": 7, "breakeven": 5.0, "gap_vs_be": 7.0, "signal": "Candidate",
    "display_spread_c": 12, "parent_display_c": 30, "child_display_c": 18,
    "spread_over_parent": 0.4, "spread_over_child": 0.6,
    "resolution_mode": "vertical", "resolution": "Vertical",
    "cheap_cost": True, "cheap_ratio": False, "cheap": "cost",                  # PR F
    # PR E trader columns + $100 sizing + the raw display fields they derive from.
    "wins_if": "Reach Final but not Win Tournament", "max_units": 12, "quote_health": "OK",
    "units_100": 50, "loss_100": 1.0, "upside_100": 49.0,
    "child_node": "Win Tournament", "parent_node": "Reach Final", "comp_quote_quality": "OK",
    # Phase 1 likelihood / comparability (display-only): the firm-quote passthrough (the only persisted new
    # fields) + every viewmodel-derived metric. bucket_of / _rank_key / peer cheapness must ignore ALL.
    "parent_yes_bid_c": 20, "child_yes_ask_c": 25,
    "cond_success": 40.0, "cond_child": 60.0, "firm_gap": -5, "firm_pct": None, "midpoint_only": True,
    "wide_basis": True, "parent_over_maxloss": 5.0, "flags": [{"label": "Midpoint-only"}],
    # NO-fade settlement-scope split + Phase 1 days-to-close + Phase 2 cheapness-vs-field (all display-only).
    "no_structure_scope": "tournament", "scope_label": "Tournament",
    "no_structure_close_time": "2026-07-01T00:00:00Z", "days_to_close": 20.0, "return_per_day": 0.3,
    "no_structure_faded_node": "Win Tournament", "no_structure_faded_display_c": 18, "cheapness_vs_field": 3.0,
}

# The executable fields the invariant protects (the per-row fingerprint).
_EXEC_KEYS = ("bucket", "status", "tradable_now", "blocked_reason",
              "action_1_text", "action_2_text", "action_1_price_c", "action_2_price_c",
              "exec_gap_c", "exec_min_size", "opportunity_id")


def executable_fingerprint(opps):
    """Order-preserving fingerprint of the executable view: rank order (via `scanner._rank_key`) + the
    protected fields per row. PR E/F/G call this before and after adding a speculative metric and assert
    equality with `assert_executable_unchanged`."""
    return [tuple(r.get(k) for k in _EXEC_KEYS) for r in sorted(opps, key=scanner._rank_key)]


def assert_executable_unchanged(before, after):
    assert executable_fingerprint(before) == executable_fingerprint(after)


def _exec_row(oid, status, *, tradable_now="Yes", bucket="actionable", gap=3):
    return {"opportunity_id": oid, "status": status, "tradable_now": tradable_now,
            "blocked_reason": "", "bucket": bucket, "exec_gap_c": gap,
            "action_1_text": "Buy YES broader", "action_2_text": "Buy NO deeper",
            "action_1_price_c": 60, "action_2_price_c": 42, "exec_min_size": 50}


def test_bucket_of_ignores_speculative_fields():
    # Across the executable statuses, adding every speculative display field must not change the bucket.
    for status, trad in (("EXECUTABLE_VIOLATION", "Yes"), ("EXECUTABLE_VIOLATION", "No"),
                         ("EXECUTABLE_DUTCH_BOOK", "Yes"), ("RISK_BUDGET_CANDIDATE", "Yes")):
        base = _exec_row("x", status, tradable_now=trad)
        assert consistency.bucket_of(base) == consistency.bucket_of({**base, **SPECULATIVE_FIELDS}), status


def test_rank_key_ignores_speculative_fields():
    row = _exec_row("a", "EXECUTABLE_VIOLATION", gap=5)
    assert scanner._rank_key(row) == scanner._rank_key({**row, **SPECULATIVE_FIELDS})


def test_no_structure_is_speculative_and_never_actionable():
    # The NO-fade statuses route to their own opt-in bucket regardless of any display fields, and carry no
    # executable gap, so they can never reach Actionable or perturb the edge rank.
    for status in ("NO_STRUCTURE_BAND", "NO_STRUCTURE_OUTRIGHT"):
        base = {"status": status, "bucket": "no_structure", "exec_gap_c": None, "tradable_now": "Speculative"}
        assert consistency.bucket_of(base) == "no_structure"
        assert consistency.bucket_of({**base, **SPECULATIVE_FIELDS}) == "no_structure"
        # exec_gap_c None ⇒ floored within its bucket; adding speculative fields never changes the rank key.
        assert scanner._rank_key(base) == scanner._rank_key({**base, **SPECULATIVE_FIELDS})


def test_rank_order_unchanged_when_speculative_fields_added():
    before = [_exec_row("a", "EXECUTABLE_VIOLATION", gap=5),
              _exec_row("b", "EXECUTABLE_VIOLATION", bucket="blocked", tradable_now="No", gap=9),
              _exec_row("c", "EXECUTABLE_VIOLATION", gap=2)]
    after = [{**r, **SPECULATIVE_FIELDS} for r in before]
    assert_executable_unchanged(before, after)        # the template PR E/F/G reuse


def test_peer_cheapness_ignores_phase1_likelihood_fields():
    # flag_peer_cheapness keys off cost/overpay/spread — adding the Phase 1 likelihood fields must not move
    # the cheap_cost / cheap_ratio verdicts.
    import webui.viewmodel as vm
    base = [{"opportunity_id": "p1", "sport": "tennis", "bucket": "risk_budget",
             "worst_case_profit_c": -4, "display_spread_c": 12, "spread_over_child": 0.6},
            {"opportunity_id": "p2", "sport": "tennis", "bucket": "risk_budget",
             "worst_case_profit_c": -9, "display_spread_c": 12, "spread_over_child": 0.6}]
    aug = [{**r, **SPECULATIVE_FIELDS} for r in base]
    vm.flag_peer_cheapness(base, band_tol_c=50, min_peers=1)
    vm.flag_peer_cheapness(aug, band_tol_c=50, min_peers=1)
    for b, a in zip(base, aug):
        assert (b.get("cheap_cost"), b.get("cheap_ratio")) == (a.get("cheap_cost"), a.get("cheap_ratio"))


def test_terminal_feed_is_a_readonly_view_not_a_second_engine():
    """The Terminal Pro feed (webui.feed) re-presents the engine rows for the SPA. It must NOT perturb the
    executable view (read-only) and must copy bucket/status verbatim — never re-derive them."""
    import copy

    from webui import feed
    opps = [_exec_row("a", "EXECUTABLE_VIOLATION", gap=5),
            _exec_row("b", "EXECUTABLE_VIOLATION", bucket="blocked", tradable_now="No", gap=9),
            _exec_row("c", "EXECUTABLE_VIOLATION", gap=2)]
    before = copy.deepcopy(opps)
    f = feed.feed_from_snapshot({"snapshot_id": 1, "fetched_at": "t", "opportunities": opps, "meta": {}})
    assert_executable_unchanged(before, opps)          # the feed never mutates the engine rows
    by = {r["id"]: r for r in f["opps"]}
    for o in opps:                                      # bucket/status are COPIED, not recomputed
        assert by[o["opportunity_id"]]["bucket"] == o["bucket"]
        assert by[o["opportunity_id"]]["status"] == o["status"]


def test_speculative_zone_basis_is_conservative():
    txt = glossary.SPECULATIVE_ZONE_BASIS.lower()
    assert "not actionable" in txt and "can lose money" in txt and "uncalibrated" in txt
    for banned in ("riskless", "locked", "true arbitrage", "guaranteed"):
        assert banned not in txt
