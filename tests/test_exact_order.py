"""PR4 — World Cup exact-order diagnostic (#4). Fixture-backed happy path + fail-closed gate coverage,
plus the hard guarantee that exact-order rows never leak into the dutch-book / containment / synthetic
/ participant paths.
"""

import itertools
import json
from pathlib import Path

import consistency
import data
import dutchbook
import exact_order
import scanner
import sports
import synthetic_bundle

_FIX = Path(__file__).parent / "fixtures" / "wc_qualifier"


def _load(name):
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


# --- synthetic row builders (precise control of the gates) ------------------------------------------
def _order_row(ev, order, *, ask=10, size=100, quality="OK", status="active"):
    """One exact-order ORDERING market. `order` = [1st, 2nd, 3rd, 4th] team names."""
    cs = {f"{i+1}{'st' if i==0 else 'nd' if i==1 else 'rd' if i==2 else 'th'} Place Team": t
          for i, t in enumerate(order)}
    return {"series": "KXWCGROUPORDER", "event_ticker": ev, "kind": "exact_order",
            "market_ticker": f"{ev}-" + "".join(t[:3].upper() for t in order),
            "player": "1: " + order[0], "raw_custom_strike": cs, "subpenny": False,
            "yes_ask_c": ask, "yes_ask_size": size, "quote_quality": quality, "status": status,
            "kalshi_url": "https://kalshi.com/x"}


def _qual_row(ev, team, *, ask=50, size=100, quality="OK", status="active", uuid=None):
    return {"series": "KXWCGROUPQUAL", "event_ticker": ev, "kind": "advance", "player": team,
            "competitor_uuid": uuid or f"uuid-{team.lower()}", "player_key": f"k-{team.lower()}",
            "tournament": "2026 World Cup", "yes_ask_c": ask, "yes_ask_size": size,
            "quote_quality": quality, "status": status, "market_ticker": f"{ev}-{team[:3].upper()}",
            "kalshi_url": "https://kalshi.com/q"}


def _full_group(teams=("Alpha", "Bravo", "Charlie", "Delta"), *, order_ask=10, qual_ask=50,
                order_ev="KXWCGROUPORDER-A26", qual_ev="KXWCGROUPQUAL-26A"):
    """All 24 orderings + 4 qualifiers for one group (group letter A)."""
    orders = [_order_row(order_ev, list(p), ask=order_ask) for p in itertools.permutations(teams)]
    quals = [_qual_row(qual_ev, t, ask=qual_ask) for t in teams]
    return orders + quals


# --- happy path -------------------------------------------------------------------------------------
def _spec_group():
    """A group that PROMOTES to the Speculative tier: synth 84 (12×7) < 100, qualifier 94 → premium +10
    (≥ MIN_SPECULATIVE_DISCOUNT_C), tight quotes, full size."""
    return _full_group(order_ask=7, qual_ask=94)


def test_diagnostic_tier_happy_path():
    out = exact_order.find_exact_order_premiums(_full_group(order_ask=10, qual_ask=50))
    assert len(out) == 4
    for f in out:
        assert f["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC          # synth 120 ≥ 100 → Diagnostic
        assert f["relationship_type"] == "exact_order_top2_bundle"
        assert f["setup_type"] == "exact_order_top2_bundle"
        assert f["opportunity_class"] == "diagnostic_top2_bundle"
        assert f["bucket"] == "qualifier_setup"
        assert f["tradable_now"] == "Diagnostic only"
        assert f["synthetic_top_two_cost_c"] == 120         # 12 legs × 10¢
        assert f["qualifier_yes_ask_c"] == 50
        assert f["qualifier_vs_top2_premium_c"] == -70       # 50 − 120
        assert f["top2_net_if_top2_c"] == -20                # 100 − 120 (a LOSS even if top two)
        assert f["top2_loss_if_not_top2_c"] == 120
        assert f["top2_max_units"] == 100
        assert f["n_legs"] == 12                             # the qualifier is a COMPARATOR, not a leg
        assert all(lg["side"] == "buy_yes" for lg in f["legs"])
        assert not any("qualify" in (lg.get("text") or "").lower() for lg in f["legs"])
        assert "best-third" in f["settlement_caveat"].lower()


def test_speculative_tier_promotion():
    out = {f["name"]: f for f in exact_order.find_exact_order_premiums(_spec_group())}
    assert len(out) == 4
    f = out["Alpha"]
    assert f["status"] == exact_order.SPECULATIVE_TOP2_RELATIVE_VALUE
    assert f["relationship_type"] == "exact_order_top2_relative_value"
    assert f["setup_type"] == "exact_order_top2_relative_value"
    assert f["opportunity_class"] == "speculative_top2_bundle"
    assert f["tradable_now"] == "Review execution"
    assert f["synthetic_top_two_cost_c"] == 84 and f["qualifier_vs_top2_premium_c"] == 10
    assert f["top2_net_if_top2_c"] == 16 and f["top2_loss_if_not_top2_c"] == 84
    assert f["top2_max_units"] == 100 and f["wide_bundle_leg_count"] == 0
    assert f["n_legs"] == 12


def test_below_discount_threshold_stays_diagnostic():
    # synth 84, qualifier 86 → premium 2 < MIN_SPECULATIVE_DISCOUNT_C → stays Diagnostic (still emits).
    out = exact_order.find_exact_order_premiums(_full_group(order_ask=7, qual_ask=86))
    assert len(out) == 4
    assert all(f["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC for f in out)


def test_thin_size_stays_diagnostic():
    rows = _spec_group()
    for r in rows:                       # shrink every bundle leg below the units floor (still firm > 0)
        if r["kind"] == "exact_order":
            r["yes_ask_size"] = 3
    out = exact_order.find_exact_order_premiums(rows)
    assert len(out) == 4
    assert all(f["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC and f["top2_max_units"] == 3 for f in out)


def test_wide_bundle_leg_downgrades_affected_teams_only():
    rows = _spec_group()
    bad = next(r for r in rows if r["kind"] == "exact_order")   # ordering Alpha,Bravo,Charlie,Delta
    bad["quote_quality"] = "Wide"
    out = {f["name"]: f for f in exact_order.find_exact_order_premiums(rows)}
    assert out["Alpha"]["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC and out["Alpha"]["wide_bundle_leg_count"] >= 1
    assert out["Bravo"]["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC
    assert out["Charlie"]["status"] == exact_order.SPECULATIVE_TOP2_RELATIVE_VALUE
    assert out["Charlie"]["wide_bundle_leg_count"] == 0


def test_wide_comparator_downgrades_but_bundle_quality_stays_clean():
    rows = _spec_group()
    q = next(r for r in rows if r["series"] == "KXWCGROUPQUAL" and r["player"] == "Alpha")
    q["quote_quality"] = "Wide"
    f = {x["name"]: x for x in exact_order.find_exact_order_premiums(rows)}["Alpha"]
    assert f["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC          # wide COMPARATOR blocks promotion
    assert f["comparator_quote_quality"] == "Wide"
    assert f["worst_bundle_quote_quality"] != "Wide" and f["wide_bundle_leg_count"] == 0


def test_no_setup_b_hedge_ever_emitted():
    for rows in (_full_group(), _spec_group()):
        for f in exact_order.find_exact_order_premiums(rows):
            assert all(lg["side"] != "buy_no" for lg in f["legs"])           # no qualifier-NO hedge leg
            assert "qualifier_no" not in str(f.get("relationship_type"))
            assert not any("qualify" in (lg.get("text") or "").lower() for lg in f["legs"])  # no Leg 13


def test_fixture_backed_group_b_premiums():
    rows = (data.build_contracts("KXWCGROUPORDER", [_load("KXWCGROUPORDER-B26.json")])
            + data.build_contracts("KXWCGROUPQUAL", [_load("KXWCGROUPQUAL-26B.json")]))
    out = {f["name"]: f for f in exact_order.find_exact_order_premiums(rows)}
    assert set(out) == {"Switzerland", "Qatar", "Bosnia and Herzegovina", "Canada"}
    # Live-probed numbers (the \n-wrapped "Bosnia and Herzegovina" name joins under normalization).
    assert out["Switzerland"]["qualifier_yes_ask_c"] == 94
    assert out["Switzerland"]["synthetic_top_two_cost_c"] == 172
    assert out["Switzerland"]["qualifier_vs_top2_premium_c"] == -78
    assert out["Switzerland"]["top2_net_if_top2_c"] == -72         # 100 − 172 (overround → loss even if top two)
    assert out["Switzerland"]["status"] == exact_order.EXACT_ORDER_DIAGNOSTIC
    assert out["Bosnia and Herzegovina"]["n_legs"] == 12


# --- structural gates (fail closed → no finding, diagnostic counter) --------------------------------
def test_requires_exactly_24_orderings():
    rows = _full_group()
    twenty_three = [r for r in rows if r["kind"] != "exact_order"][:] + \
                   [r for r in rows if r["kind"] == "exact_order"][:23]
    diag = {}
    assert exact_order.find_exact_order_premiums(twenty_three, diag) == []
    assert any("expected 24" in r["reason"] for r in diag.get("rejected", []))


def test_malformed_ordering_skips_group():
    rows = _full_group()
    # Drop a placement key on one ordering → malformed → whole group skipped.
    next(r for r in rows if r["kind"] == "exact_order")["raw_custom_strike"].pop("4th Place Team")
    diag = {}
    assert exact_order.find_exact_order_premiums(rows, diag) == []
    assert any("malformed" in r["reason"] for r in diag.get("rejected", []))


def test_duplicate_orderings_break_the_12_top_two_gate():
    # 24 IDENTICAL orderings → only 4 teams but the pos-1/2 teams appear in top-two far more than 12.
    one = list(("Alpha", "Bravo", "Charlie", "Delta"))
    orders = [_order_row("KXWCGROUPORDER-A26", one) for _ in range(24)]
    quals = [_qual_row("KXWCGROUPQUAL-26A", t) for t in one]
    diag = {}
    assert exact_order.find_exact_order_premiums(orders + quals, diag) == []
    assert any("top-two" in r["reason"] for r in diag.get("rejected", []))


# --- firm-buy gate (price + positive size + non-crossed + active) -----------------------------------
def test_non_firm_order_leg_skips_that_team():
    rows = _full_group()
    # Zero the ask size on one ordering → both top-two teams of that ordering are skipped.
    bad = next(r for r in rows if r["kind"] == "exact_order")
    bad["yes_ask_size"] = 0
    out = exact_order.find_exact_order_premiums(rows)
    assert len(out) == 2          # the 2 teams NOT in that ordering's top two still fire


def test_crossed_qualifier_skips_that_team():
    rows = _full_group()
    next(r for r in rows if r["series"] == "KXWCGROUPQUAL")["quote_quality"] = "Crossed"
    diag = {}
    out = exact_order.find_exact_order_premiums(rows, diag)
    assert len(out) == 3
    assert any("not firm" in r["reason"] for r in diag.get("not_price_proven", []))


def test_missing_qualifier_skips_that_team():
    rows = [r for r in _full_group() if not (r["series"] == "KXWCGROUPQUAL" and r["player"] == "Alpha")]
    out = exact_order.find_exact_order_premiums(rows)
    assert "Alpha" not in {f["name"] for f in out} and len(out) == 3


def test_inactive_order_leg_skips_affected_teams():
    rows = _full_group()
    bad = next(r for r in rows if r["kind"] == "exact_order")   # ordering Alpha,Bravo,Charlie,Delta
    bad["status"] = "finalized"
    out = {f["name"] for f in exact_order.find_exact_order_premiums(rows)}
    assert out == {"Charlie", "Delta"}                          # Alpha + Bravo (its top two) skipped


def test_no_quote_qualifier_skips_that_team():
    rows = _full_group()
    next(r for r in rows if r["series"] == "KXWCGROUPQUAL" and r["player"] == "Alpha")["quote_quality"] = "No quote"
    out = {f["name"] for f in exact_order.find_exact_order_premiums(rows)}
    assert "Alpha" not in out and len(out) == 3


def test_missing_order_ask_skips_affected_teams():
    rows = _full_group()
    bad = next(r for r in rows if r["kind"] == "exact_order")   # ordering Alpha,Bravo,Charlie,Delta
    bad["yes_ask_c"] = None
    out = {f["name"] for f in exact_order.find_exact_order_premiums(rows)}
    assert out == {"Charlie", "Delta"}


# --- exclusion from every other detector ------------------------------------------------------------
def _contract_rows():
    return (data.build_contracts("KXWCGROUPORDER", [_load("KXWCGROUPORDER-B26.json")])
            + data.build_contracts("KXWCGROUPQUAL", [_load("KXWCGROUPQUAL-26B.json")]))


def test_exact_order_excluded_from_dutch_books_even_as_24_way_mece():
    # The 24-way mutually_exclusive set must NEVER be priced as a dutch book.
    books = dutchbook.find_dutch_books(_contract_rows())
    assert all(b.get("status") != dutchbook.EXECUTABLE_DUTCH_BOOK or "ORDER" not in b.get("event_ticker", "")
               for b in books)
    assert not any("GROUPORDER" in b.get("event_ticker", "") for b in books)


def test_exact_order_excluded_from_containment_and_synthetic():
    import pandas as pd
    df = pd.DataFrame(_contract_rows())
    checks = consistency.build_checks(df)
    assert not any("GROUPORDER" in str(t) for t in checks.get("child_ticker", []))
    assert synthetic_bundle.find_synthetic_bundles(_contract_rows()) == []


def test_exact_order_rows_are_non_participant():
    rows = data.build_contracts("KXWCGROUPORDER", [_load("KXWCGROUPORDER-B26.json")])
    assert rows and all(r["is_participant"] is False for r in rows)
    assert all(r["participant_type"] == "exact_order" for r in rows)


# --- unified mapper + NaN round-trip ----------------------------------------------------------------
def test_unified_mapper_shape_and_participant_from_qualifier_uuid():
    f = exact_order.find_exact_order_premiums(_full_group())[0]   # Diagnostic tier
    d = scanner._to_unified_exact_order(f, sports.SOCCER)
    assert d["bucket"] == "qualifier_setup" and d["source"] == "exact_order"
    assert d["exec_gap_c"] is None and d["cost_c"] is None
    assert d["setup_type"] == "exact_order_top2_bundle" and d["opportunity_class"] == "diagnostic_top2_bundle"
    assert d["qualifier_vs_top2_premium_c"] == f["qualifier_vs_top2_premium_c"]
    assert d["top2_net_if_top2_c"] == f["top2_net_if_top2_c"] and d["top2_max_units"] == f["top2_max_units"]
    assert d["comparator_quote_quality"] == f["comparator_quote_quality"]
    assert d["n_legs"] == 12
    # Participant identity is the JOINED QUALIFIER UUID, not an order-market pseudo-key.
    assert d["participant_keys"] == [f["participant_uuid"]]
    assert not any(str(k).startswith("exact_order::") for k in d["participant_keys"])


def test_unified_mapper_speculative_tier():
    f = exact_order.find_exact_order_premiums(_spec_group())[0]
    d = scanner._to_unified_exact_order(f, sports.SOCCER)
    assert d["status"] == "SPECULATIVE_TOP2_RELATIVE_VALUE"
    assert d["setup_type"] == "exact_order_top2_relative_value"
    assert d["opportunity_class"] == "speculative_top2_bundle"
    assert consistency.bucket_of(d) == "qualifier_setup"          # NEVER actionable


def test_unified_row_survives_dataframe_nan_round_trip():
    import pandas as pd
    f = exact_order.find_exact_order_premiums(_full_group())[0]
    d = scanner._to_unified_exact_order(f, sports.SOCCER)
    rt = pd.DataFrame([d], columns=scanner.UNIFIED_COLUMNS).to_dict("records")[0]
    assert rt["status"] == "EXACT_ORDER_DIAGNOSTIC"
    assert scanner._num(rt["qualifier_vs_top2_premium_c"]) == f["qualifier_vs_top2_premium_c"]
    assert scanner._num(rt["top2_net_if_top2_c"]) == f["top2_net_if_top2_c"]
    assert rt["opportunity_class"] == "diagnostic_top2_bundle"
