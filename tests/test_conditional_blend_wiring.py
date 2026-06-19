"""Phase-1 isolation tests: the conditional-blend detector is wired into the scanner but DEFAULT-OFF, is
display-only, and can NEVER become Actionable or alter executable rows. The audit's hard requirements."""
from __future__ import annotations

import pandas as pd

import config
import consistency
import scanner
import sports


# --- a tiny multi-detector fixture: a real executable dutch book + (when enabled) a blend candidate ----
def _match(player, *, event, series="KXATPMATCH", pk=None, yes_bid_c=None, yes_ask_c=None):
    return {"series": series, "event_ticker": event, "kind": "match", "player": player,
            "player_key": pk or player.lower(), "tournament": "T", "tour": "ATP",
            "yes_bid_c": yes_bid_c, "yes_ask_c": yes_ask_c, "no_ask_c": (100 - yes_bid_c if yes_bid_c else None),
            "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
            "kalshi_url": "x", "ladder_node": None, "market_family": "match"}


def _blend_rows():
    # WC final-decider that fires a MODEL_BLEND_CANDIDATE
    def row(node, key, bid, ask):
        s = "KXMENWORLDCUP" if node == "Win the World Cup" else "KXWCROUND"
        return {"series": s, "event_ticker": f"{s}-{key}", "market_ticker": f"{s}-{key}-M", "player": key.upper(),
                "player_key": key, "kind": "advance", "market_family": "advance", "ladder_node": node, "stage": "",
                "tour": "", "yes_bid_c": bid, "yes_ask_c": ask, "no_ask_c": (100 - bid), "display_c": ask,
                "yes_bid_size": 100, "yes_ask_size": 100, "quote_quality": "Tight", "status": "active",
                "tournament": "World Cup 2026", "kalshi_url": "x", "time_value": "t", "rules_primary": "w"}
    RF, W = "Reach Finals", "Win the World Cup"
    return [row(RF, "a", 99, 100), row(W, "a", 66, 68), row(RF, "b", 58, 62), row(W, "b", 16, 20),
            row(RF, "c", 38, 42), row(W, "c", 6, 10)]


def _dutch_rows():
    # an executable underround dutch book (Σ yes_ask < 100)
    return [_match("Alcaraz", event="E", yes_bid_c=43, yes_ask_c=45),
            _match("Sinner", event="E", yes_bid_c=46, yes_ask_c=48)]


def _scan(rows):
    # mirror production: each sport's fetch returns ONLY its own contracts (partition by resolved sport)
    def fetch(sid):
        sub = [r for r in rows if sports.sport_for_series(r.get("series")).sport_id == sid]
        return pd.DataFrame(sub) if sub else None
    return scanner.unified_opportunities(fetch)[0]


def test_routing_table_invariant_preserved():
    assert set(scanner.BUCKET_PRIORITY) == set(consistency.DASHBOARD_BUCKETS)
    assert "speculative_model" in consistency.DASHBOARD_BUCKETS
    assert consistency.STATUS_GROUP["MODEL_BLEND_CANDIDATE"] == "Speculative model"
    assert consistency.bucket_of({"status": "MODEL_BLEND_CANDIDATE"}) == "speculative_model"
    # never sorts ahead of a real actionable edge
    assert scanner.BUCKET_PRIORITY["actionable"] < scanner.BUCKET_PRIORITY["speculative_model"]


def test_default_off_emits_no_blend_rows(monkeypatch):
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", False)
    monkeypatch.delenv("CONDITIONAL_BLEND_ENABLED", raising=False)
    out = _scan(_blend_rows())
    assert (out["status"] != "MODEL_BLEND_CANDIDATE").all()
    assert "speculative_model" not in set(out["bucket"])


def test_enabling_detector_leaves_executable_rows_identical(monkeypatch):
    # the audit's hard requirement: turning the detector ON must not change any executable row
    rows = _dutch_rows() + _blend_rows()
    monkeypatch.delenv("CONDITIONAL_BLEND_ENABLED", raising=False)
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", False)
    off = _scan(rows)
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", True)
    on = _scan(rows)
    off_exec = off[off["status"] == "EXECUTABLE_DUTCH_BOOK"].reset_index(drop=True)
    on_exec = on[on["status"] == "EXECUTABLE_DUTCH_BOOK"].reset_index(drop=True)
    assert len(off_exec) == 1                                     # the executable edge is present
    pd.testing.assert_frame_equal(off_exec, on_exec)             # …and byte-identical with the detector on


def test_enabled_surfaces_speculative_never_actionable(monkeypatch):
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", True)
    out = _scan(_blend_rows())
    blend = out[out["status"] == "MODEL_BLEND_CANDIDATE"]
    assert len(blend) == 1
    row = blend.iloc[0]
    assert row["bucket"] == "speculative_model"
    assert row["exec_gap_c"] is None or row["exec_gap_c"] != row["exec_gap_c"]   # None/NaN — never an edge
    assert row["tradable_now"] != "Yes" and not str(row["tradable_now"]).startswith("Yes")
    assert row["source"] == "conditional_blend"


def test_enabled_blend_rows_never_rank_above_actionable(monkeypatch):
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", True)
    out = _scan(_dutch_rows() + _blend_rows())
    actionable_idx = out.index[out["bucket"] == "actionable"].tolist()
    spec_idx = out.index[out["bucket"] == "speculative_model"].tolist()
    assert actionable_idx and spec_idx
    assert max(actionable_idx) < min(spec_idx)                    # every actionable row ranks above every blend row


def test_env_var_enables_detector(monkeypatch):
    monkeypatch.setattr(config, "CONDITIONAL_BLEND_DEFAULT_ENABLED", False)
    monkeypatch.setenv("CONDITIONAL_BLEND_ENABLED", "1")
    assert scanner._conditional_blend_enabled() is True
    out = _scan(_blend_rows())
    assert (out["status"] == "MODEL_BLEND_CANDIDATE").any()
