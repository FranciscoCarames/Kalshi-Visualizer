"""Tests for the Motorsport-shaped engine-adapter hooks (PR 1).

These cover the sport-agnostic generalizations added so a field sport (motorsport) can be registered as a
drop-in: per-sport ``field_families`` (one-winner fields beyond "winner"), an event-only
``tournament_key_fn`` grouping hook, a per-group ``ladder_fn``, role-namespaced ``player_key`` derived from
the classified family, per-value ``IdentityResolver`` confidence, and the variable-tick / subpenny guard.

Every hook is DEFAULTED, so the headline assertion is **no-op for the 7 existing sports**; the opt-in
behaviour is exercised through a throwaway test sport registered on a snapshotted registry.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

import consistency
import data
import dutchbook
import sports


# --------------------------------------------------------------------------------------------------
# A throwaway "racetest" sport (motorsport-shaped) registered on a snapshotted registry.
# --------------------------------------------------------------------------------------------------
def _is_uuid(v) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{16,}", str(v)))


def _rt_family(cfg, t):
    t = (t or "").upper()
    if t.startswith("KXRTRACE"):
        return "race_winner"
    if t.startswith("KXRTPODIUM"):
        return "advance"
    if t.startswith("KXRTCON"):
        return "constructor"
    if t.startswith("KXRTSPRINT"):
        return "race_winner"
    return "other"


def _rt_role(cfg, family):
    if family in ("race_winner", "winner"):
        return "driver"
    if family in ("constructor", "team"):
        return family
    return ""


def _rt_tournament_key(cfg, event):
    et = str(event.get("event_ticker") or "").upper()
    token = et.split("-")[-1] if "-" in et else et
    session = "sprint" if ("SPRINT" in et or "sprint" in str(event.get("sub_title") or "").lower()) \
        else "main-race"
    return (f"RT · {session} · {token}", "motorsport_event")


def _make_racetest() -> sports.SportConfig:
    return sports.SportConfig(
        sport_id="racetest", label="RaceTest", emoji="\U0001f3ce",
        series_prefixes=("KXRT",), default_series=("KXRTRACE",), winner_tickers=frozenset(),
        identity=sports.IdentityResolver(
            candidate_paths=("custom_strike.rt_driver",), id_label="driver", id_validator=_is_uuid),
        ladder=sports._EMPTY_LADDER,
        category_labels={"race_winner": "Race winner", "advance": "Finish position",
                         "constructor": "Constructor", "winner": "Champion", "other": "Other"},
        round_patterns=(), stage_rank={},
        ladder_families=frozenset({"advance", "race_winner"}), match_family="",
        divisions={}, division_label="Series",
        family_fn=_rt_family,
        stage_fn=lambda cfg, fam, m: "",
        node_fn=lambda cfg, fam, stage: None,
        division_fn=lambda cfg, t: "F1",
        field_families=frozenset({"winner", "race_winner", "constructor"}),
        role_fn=_rt_role,
        tournament_key_fn=_rt_tournament_key,
    )


@pytest.fixture
def racetest():
    saved = dict(sports._REGISTRY)
    cfg = sports.register(_make_racetest())
    try:
        yield cfg
    finally:
        sports._REGISTRY.clear()
        sports._REGISTRY.update(saved)


# --------------------------------------------------------------------------------------------------
# PR 1.A — field_families (one-winner generalization)
# --------------------------------------------------------------------------------------------------
def test_field_families_default_is_winner_only_for_existing_sports():
    """No-op proof: every shipped sport keeps the default {"winner"} field-eligibility."""
    for cfg in sports.all_sports():
        if cfg.sport_id == "racetest":
            continue
        assert cfg.field_families == frozenset({"winner"})


def test_is_field_row_respects_field_families(racetest):
    assert dutchbook._is_field_row({"kind": "race_winner", "series": "KXRTRACE"}) is True
    assert dutchbook._is_field_row({"kind": "constructor", "series": "KXRTCON"}) is True
    assert dutchbook._is_field_row({"kind": "other", "series": "KXRTRACE"}) is False
    # an UNKNOWN series is always excluded
    assert dutchbook._is_field_row({"kind": "race_winner", "series": "NOPE"}) is False


def _rt_winner(name, key, *, yes_bid_c, kind="race_winner", series="KXRTRACE", event="KXRTRACE-MONGP26"):
    return {
        "kind": kind, "series": series, "event_ticker": event, "player": name, "player_key": key,
        "is_participant": True, "tournament": "RT · main-race · MONGP26", "tour": "F1",
        "mutually_exclusive": True, "yes_bid_c": yes_bid_c, "no_ask_c": 100 - yes_bid_c,
        "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
        "market_ticker": f"{event}-{key}", "kalshi_url": "https://kalshi.com/x", "event_title": "Race",
    }


def test_field_overround_fires_on_non_winner_field(racetest):
    """A race_winner (NOT "winner") field fires the overround because the sport lists it in field_families."""
    f = dutchbook.find_dutch_books([_rt_winner("A", "a", yes_bid_c=40),
                                    _rt_winner("B", "b", yes_bid_c=35),
                                    _rt_winner("C", "c", yes_bid_c=30)])
    assert len(f) == 1
    g = f[0]
    assert g["status"] == dutchbook.EXECUTABLE_DUTCH_BOOK and g["direction"] == "overround"
    assert g["exec_gap_c"] == 5 and all(leg["side"] == "buy_no" for leg in g["legs"])


# --------------------------------------------------------------------------------------------------
# PR 1.B(i) — event-only tournament_key_fn (event-instance grouping)
# --------------------------------------------------------------------------------------------------
def _rt_event(series_ticker, event_ticker, *, sub_title="", driver_uuid="11111111-2222-3333-aaaa-bbbbbbbbbbbb",
              price="0.40", name="Driver One"):
    return {
        "event_ticker": event_ticker, "title": "Race event", "sub_title": sub_title,
        "product_metadata": {"competition": "F1", "competition_scope": "Game"},
        "markets": [{
            "ticker": f"{event_ticker}-D1", "yes_sub_title": name,
            "custom_strike": {"rt_driver": driver_uuid},
            "yes_bid_dollars": price, "yes_ask_dollars": price, "last_price_dollars": price,
            "yes_bid_size_fp": "100", "yes_ask_size_fp": "100", "status": "active",
            "title": "Will Driver One win?", "close_time": "2026-06-16T09:00:00Z",
        }],
    }


def test_tournament_key_groups_same_race_scopes_together(racetest):
    """The race-winner scope and the podium scope of the SAME race share one grouping key — raw
    competition_scope ("Game" vs "Podium Finishers") is NOT in the key."""
    race = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-MONGP26")])
    podium = data.build_contracts("KXRTPODIUM", [_rt_event("KXRTPODIUM", "KXRTPODIUM-MONGP26")])
    assert race[0]["tournament"] == "RT · main-race · MONGP26"
    assert podium[0]["tournament"] == race[0]["tournament"]          # group together


def test_tournament_key_separates_sprint_and_other_races(racetest):
    sprint = data.build_contracts("KXRTSPRINT", [_rt_event("KXRTSPRINT", "KXRTSPRINT-MONGP26")])
    other = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-SILGP26")])
    main = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-MONGP26")])
    assert sprint[0]["tournament"] == "RT · sprint · MONGP26"
    assert other[0]["tournament"] == "RT · main-race · SILGP26"
    assert len({sprint[0]["tournament"], other[0]["tournament"], main[0]["tournament"]}) == 3


def test_tournament_key_fn_is_noop_for_existing_sports():
    for cfg in sports.all_sports():
        if cfg.sport_id != "racetest":
            assert cfg.tournament_key_of({"event_ticker": "X"}) is None


# --------------------------------------------------------------------------------------------------
# PR 1.B(iii) — role-namespaced player_key derived from the classified family
# --------------------------------------------------------------------------------------------------
def test_role_namespace_keeps_driver_and_constructor_distinct(racetest):
    """A constructor market that REUSES the driver id path must not merge with the driver — the role tag
    comes from the classified family, not the matched identity path."""
    uuid = "11111111-2222-3333-aaaa-bbbbbbbbbbbb"
    drv = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-MONGP26", driver_uuid=uuid)])
    con = data.build_contracts("KXRTCON", [_rt_event("KXRTCON", "KXRTCON-MONGP26", driver_uuid=uuid)])
    assert drv[0]["player_key"] == f"driver:{uuid}"
    assert con[0]["player_key"] == f"constructor:{uuid}"
    assert drv[0]["player_key"] != con[0]["player_key"]


def test_role_fn_is_noop_for_existing_sports():
    for cfg in sports.all_sports():
        if cfg.sport_id != "racetest":
            assert cfg.role_of("winner") == ""


# --------------------------------------------------------------------------------------------------
# PR 1.B(iv) — per-value IdentityResolver confidence
# --------------------------------------------------------------------------------------------------
def test_identity_validator_marks_non_id_value_low():
    r = sports.IdentityResolver(candidate_paths=("custom_strike.p",), id_validator=_is_uuid)
    uuid = "11111111-2222-3333-aaaa-bbbbbbbbbbbb"
    hi = r.resolve({"custom_strike": {"p": uuid}, "yes_sub_title": "Name"})
    lo = r.resolve({"custom_strike": {"p": "Ferrari"}, "yes_sub_title": "Ferrari"})
    assert hi.confidence == "high" and hi.participant_key == uuid
    assert lo.confidence == "low" and lo.participant_key == "Ferrari" and lo.source_field == "id_unverified"


def test_identity_without_validator_keeps_legacy_high_confidence():
    """Default (no validator) — any candidate hit is high, exactly as the 7 shipped sports rely on."""
    r = sports.IdentityResolver(candidate_paths=("custom_strike.p",))
    out = r.resolve({"custom_strike": {"p": "Ferrari"}, "yes_sub_title": "Ferrari"})
    assert out.confidence == "high" and out.participant_key == "Ferrari"


# --------------------------------------------------------------------------------------------------
# PR 1.B(ii) — per-group ladder_fn
# --------------------------------------------------------------------------------------------------
def test_ladder_for_defaults_to_static_ladder():
    assert sports.TENNIS.ladder_for([]) is sports.TENNIS.ladder


def test_ladder_for_uses_ladder_fn_when_set():
    spec = sports.LadderSpec(("A", "B"), (("B", "A"),), {}, {})
    cfg = _make_racetest()
    cfg = sports.SportConfig(**{**cfg.__dict__, "ladder_fn": lambda c, rows: spec})
    assert cfg.ladder_for([{"x": 1}]) is spec


# --------------------------------------------------------------------------------------------------
# PR 1.C — variable-tick / subpenny guard
# --------------------------------------------------------------------------------------------------
def test_price_is_subpenny():
    assert data.price_is_subpenny("0.3725") is True
    assert data.price_is_subpenny("0.0300") is False        # whole cent despite 4 decimals
    assert data.price_is_subpenny("0.37") is False
    assert data.price_is_subpenny("") is False
    assert data.price_is_subpenny(None) is False


def test_market_has_subpenny_price_and_metadata():
    assert data.market_has_subpenny({"yes_ask_dollars": "0.3725"}) is True
    assert data.market_has_subpenny({"yes_ask_dollars": "0.3700"}) is False
    assert data.market_has_subpenny({"price_level_structure": {"min_tick": "0.0025"}}) is True
    assert data.market_has_subpenny({"price_ranges": [{"tick_size": "0.0100"}]}) is False


def test_build_contracts_stamps_subpenny(racetest):
    rows = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-MONGP26", price="0.3725")])
    assert rows[0]["subpenny"] is True
    ok = data.build_contracts("KXRTRACE", [_rt_event("KXRTRACE", "KXRTRACE-MONGP26", price="0.3700")])
    assert ok[0]["subpenny"] is False


def test_dutchbook_skips_subpenny_rows(racetest):
    rows = [_rt_winner("A", "a", yes_bid_c=40), _rt_winner("B", "b", yes_bid_c=35),
            _rt_winner("C", "c", yes_bid_c=30)]
    for r in rows:
        r["subpenny"] = True
    diag: dict = {}
    assert dutchbook.find_dutch_books(rows, diag) == []
    assert any("subpenny" in r["reason"] for r in diag.get("rejected", []))


def test_consistency_excludes_subpenny_rows():
    from tests.test_consistency import _ckey_row
    semi = _ckey_row("P", "uuid-p", "advance", "Semifinal", 40)     # ask 41
    champ = _ckey_row("P", "uuid-p", "winner", "Champion", 70)      # bid 69 > 41 -> would be a violation
    base = consistency.build_checks(pd.DataFrame([semi, champ]))
    assert (base["status"] == "EXECUTABLE_VIOLATION").any()         # control: the edge exists
    semi["subpenny"], champ["subpenny"] = True, True
    guarded = consistency.build_checks(pd.DataFrame([semi, champ]))
    assert guarded.empty                                            # subpenny rows form no edge
