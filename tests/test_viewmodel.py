"""Unit tests for webui.viewmodel (PR 22) — pure filtering / options / scope banner / URL state."""
from __future__ import annotations

from webui import viewmodel as vm


def _opp(oid, *, sport="tennis", bucket="blocked", source="containment", tournament="French Open",
         name="Alcaraz", size=100, market_status="active"):
    return {"opportunity_id": oid, "sport": sport, "sport_label": sport.title(), "source": source,
            "bucket": bucket, "tournament": tournament, "name": name,
            "exec_min_size": size, "market_status": market_status, "exec_gap_c": 5}


# --- membership narrows every bucket --------------------------------------------------
def test_membership_sport_and_tournament_narrow_all():
    opps = [_opp("a", sport="tennis", bucket="actionable", tournament="French Open"),
            _opp("b", sport="nba", bucket="blocked", tournament="NBA Finals")]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, sports=["tennis"])] == ["a"]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, tournaments=["NBA Finals"])] == ["b"]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps)] == ["a", "b"]   # no filter = identity


def test_participant_is_a_case_insensitive_substring():
    opps = [_opp("a", name="Alcaraz vs Sinner"), _opp("b", name="Gauff vs Swiatek")]
    assert [o["opportunity_id"] for o in vm.filter_opps(opps, participant="sinner")] == ["a"]
    assert vm.filter_opps(opps, participant="nobody") == []


# --- thresholds spare Actionable + dutch-book -----------------------------------------
def test_min_size_spares_actionable_and_dutchbook():
    opps = [_opp("act", bucket="actionable", source="containment", size=1),   # spared (actionable)
            _opp("db", bucket="blocked", source="dutch_book", size=1),        # spared (dutch_book)
            _opp("blk", bucket="blocked", source="containment", size=1),      # subject -> dropped
            _opp("big", bucket="blocked", source="containment", size=500)]
    assert {o["opportunity_id"] for o in vm.filter_opps(opps, min_size=50)} == {"act", "db", "big"}


def test_active_only_spares_actionable_and_dutchbook():
    opps = [_opp("act", bucket="actionable", source="containment", market_status="finalized"),  # spared
            _opp("db", bucket="blocked", source="dutch_book", market_status="finalized"),        # spared
            _opp("blk_in", bucket="blocked", source="containment", market_status="finalized"),   # dropped
            _opp("blk_ok", bucket="blocked", source="containment", market_status="active")]
    assert {o["opportunity_id"] for o in vm.filter_opps(opps, active_only=True)} == {"act", "db", "blk_ok"}


def test_min_size_is_nan_safe():
    nan = float("nan")
    assert vm.filter_opps([_opp("n", bucket="blocked", source="containment", size=nan)], min_size=10) == []
    # a spared (actionable) row with no size survives — thresholds never touch it.
    assert len(vm.filter_opps([_opp("n", bucket="actionable", size=nan)], min_size=10)) == 1


# --- derive_options -------------------------------------------------------------------
def test_derive_options_only_present_sorted():
    opps = [_opp("a", sport="tennis", tournament="French Open"),
            _opp("b", sport="nba", tournament="NBA Finals"),
            _opp("c", sport="tennis", tournament="French Open")]
    opt = vm.derive_options(opps)
    assert opt["sports"] == {"nba": "Nba", "tennis": "Tennis"}        # id->label, sorted, deduped
    assert opt["tournaments"] == ["French Open", "NBA Finals"]


# --- scope banner ---------------------------------------------------------------------
def test_scope_banner_with_meta_shows_both_counters():
    cov = {"meta_present": True, "fetched_at": "2026-06-04 12:00:00 UTC", "opportunities": 7,
           "scanned": 30, "failed": 2, "contracts_scanned": 1493, "checks_tested": 1098,
           "kalshi_requests": 48}
    s = vm.scope_banner(cov, "UTC")
    assert "7 opportunities" in s and "30 series · 2 failed" in s
    assert "1493 contracts scanned · 1098 checks tested" in s and "48 Kalshi requests" in s


def test_scope_banner_honest_when_no_scan_or_no_meta():
    assert vm.scope_banner({"fetched_at": None}, "UTC").startswith("No scan yet")
    s = vm.scope_banner({"meta_present": False, "fetched_at": "2026-06-04 12:00:00 UTC", "opportunities": 0}, "UTC")
    assert "no coverage meta" in s


# --- URL state round-trip + graceful reset --------------------------------------------
def test_url_state_round_trip():
    state = {"sports": ["tennis", "nba"], "tournaments": ["French Open"], "participant": "Alc",
             "min_size": 50.0, "active_only": True}
    q = vm.query_from_state(state)
    assert q == {"sport": "tennis,nba", "tournament": "French Open", "participant": "Alc",
                 "min_size": "50.0", "active": "1"}
    back = vm.state_from_query(q)   # no options -> accept all
    assert back["sports"] == ["tennis", "nba"] and back["tournaments"] == ["French Open"]
    assert back["participant"] == "Alc" and back["min_size"] == 50.0 and back["active_only"] is True


def test_url_state_gracefully_drops_unknown_sport_and_tournament():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"]}
    q = {"sport": "tennis,golf", "tournament": "Wimbledon", "participant": "x"}
    st = vm.state_from_query(q, options=options)
    assert st["sports"] == ["tennis"]            # golf isn't in the snapshot -> dropped, not errored
    assert "tournaments" not in st               # Wimbledon absent -> the whole (now-empty) key omitted
    assert st["participant"] == "x"              # participant is free text -> kept


def test_active_filter_chips_labels():
    options = {"sports": {"tennis": "Tennis"}, "tournaments": ["French Open"]}
    chips = vm.active_filter_chips({"sports": ["tennis"], "participant": "Alc", "min_size": 50.0,
                                    "active_only": True}, options)
    assert "sport: Tennis" in chips and "participant: “Alc”" in chips
    assert "min size ≥ 50" in chips and "active only" in chips
    assert vm.active_filter_chips({}) == []
