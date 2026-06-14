"""Unit tests for the Terminal Pro UI pure helpers (redesign P2).

The DES trade-card itself builds on a client-side row-selection the headless `User` can't drive (see
tests/test_browser.py), so the card is a manual check. These cover the PURE, UI-free helpers that feed it
— the real confidence signals, the quote-quality accent, and the NaN-safe number coercion — so the
card's data layer is regression-guarded without a browser.
"""
from __future__ import annotations

from webui import terminal


def test_num_is_nan_and_type_safe() -> None:
    assert terminal._num(5) == 5
    assert terminal._num(2.5) == 2.5
    assert terminal._num(None) is None
    assert terminal._num("99") is None          # strings are not numbers → '—' upstream, never a crash
    assert terminal._num(float("nan")) is None   # NaN-safe (pandas/JSON round-trips can yield NaN)


def test_quote_css_buckets_by_tradeability() -> None:
    assert terminal._quote_css("Tight") == "tp-green"
    assert terminal._quote_css("OK") == "tp-green"
    assert terminal._quote_css("Wide") == "tp-amber"
    assert terminal._quote_css("Very wide") == "tp-amber"
    assert terminal._quote_css("No quote") == "tp-red"
    assert terminal._quote_css("Crossed") == "tp-red"
    assert terminal._quote_css("One-sided") == "tp-red"


def test_confidence_signals_surface_only_real_fields() -> None:
    """The signals are built strictly from fields the engine produces — never a fabricated 0-100 matrix."""
    opp = {"quote_quality": "OK", "mapping_confidence": "high", "tradable_now": "Yes"}
    sig = terminal._confidence_signals(opp, {})
    labels = {s[0]: (s[1], s[2]) for s in sig}
    assert labels["QUOTE"] == ("OK", "tp-green")
    assert labels["IDENTITY"] == ("high", "tp-green")
    assert labels["TRADABLE"] == ("Yes", "tp-green")
    assert "SETTLEMENT" not in labels             # no rule flag → no settlement-review signal


def test_confidence_signals_flag_low_identity_and_settlement_review() -> None:
    opp = {"quote_quality": "Wide", "mapping_confidence": "low", "tradable_now": "Review rules",
           "rule_flag": "RULE_CHECK_REQUIRED"}
    labels = {s[0]: (s[1], s[2]) for s in terminal._confidence_signals(opp, {})}
    assert labels["QUOTE"] == ("Wide", "tp-amber")
    assert labels["IDENTITY"] == ("low", "tp-amber")
    assert labels["TRADABLE"][1] == "tp-amber"    # anything but "Yes" is amber, not green
    assert labels["SETTLEMENT"] == ("review", "tp-amber")


def test_confidence_signals_fall_back_to_leg_mapping_confidence() -> None:
    """Identity confidence can come from a leg's stored contract row when the opp doesn't carry its own."""
    opp = {"tradable_now": "Yes"}
    lookup = {"TKR": {"mapping_confidence": "high"}}
    labels = {s[0]: s[1] for s in terminal._confidence_signals(opp, lookup)}
    assert labels["IDENTITY"] == "high"


def test_confidence_signals_empty_when_nothing_known() -> None:
    assert terminal._confidence_signals({}, {}) == []


# --- OPS surface: the scan-failure line formatter (P4) ------------------------------------------------
def test_fail_line_formats_dict_location_and_truncates() -> None:
    e = {"sport": "tennis", "series": "KXWTAADVANCE", "error": "boom"}
    assert terminal._fail_line(e) == "KXWTAADVANCE · tennis: boom"


def test_fail_line_truncates_long_traceback_to_a_single_line() -> None:
    e = {"series": "KXNBAGAME", "sport": "nba", "error": "x" * 300 + "\nsecond line"}
    line = terminal._fail_line(e)
    assert line.startswith("KXNBAGAME · nba: ")
    assert line.endswith("…")
    assert "\n" not in line            # newlines flattened so each failure is one red row
    assert len(line) < 160             # bounded, never the full 300-char dump


def test_fail_line_passes_through_a_plain_string() -> None:
    assert terminal._fail_line("series down") == "series down"


def test_fail_line_handles_missing_fields() -> None:
    assert terminal._fail_line({"error": "no location"}) == "?: no location"


# --- P3: the top-of-book depth preview (single firm level each side, never a synthesised DOM) ----------
def _book_row(**over):
    row = {"contract": "Mkt A", "yes_bid_c": 35, "yes_ask_c": 36, "yes_bid_size": 500,
           "yes_ask_size": 625, "no_ask_c": 65, "spread_cents": 1, "last_c": 36, "volume": 360,
           "open_interest": 360, "quote_quality": "Tight"}
    row.update(over)
    return row


def test_depth_preview_reads_firm_top_of_book() -> None:
    bk = terminal._depth_preview({"legs": [{"ticker": "T1"}]}, {"T1": _book_row()})[0]
    assert bk["two_sided"] is True
    assert (bk["market"], bk["bid_c"], bk["ask_c"]) == ("Mkt A", 35, 36)
    assert (bk["bid_size"], bk["ask_size"]) == (500, 625)
    assert bk["no_ask_c"] == 65
    assert bk["no_size"] == 500              # Kalshi has no NO-side size → Buy-NO size = yes_bid_size
    assert (bk["spread_c"], bk["last_c"], bk["volume"], bk["open_interest"]) == (1, 36, 360, 360)


def test_depth_preview_buy_no_falls_back_to_100_minus_bid() -> None:
    """No firm NO-side ask → the documented 100 − yes_bid_c Buy-NO price (never fabricated)."""
    row = _book_row(no_ask_c=None)
    bk = terminal._depth_preview({"legs": [{"ticker": "T1"}]}, {"T1": row})[0]
    assert bk["no_ask_c"] == 65              # 100 − 35


def test_depth_preview_rejects_empty_and_crossed_books() -> None:
    empty = terminal._depth_preview({"legs": [{"ticker": "T"}]},
                                    {"T": _book_row(yes_bid_c=0, yes_ask_c=100)})[0]
    crossed = terminal._depth_preview({"legs": [{"ticker": "T"}]},
                                      {"T": _book_row(yes_bid_c=60, yes_ask_c=55)})[0]
    assert empty["two_sided"] is False       # the 0/100 empty book is never a real two-sided quote
    assert crossed["two_sided"] is False     # bid > ask is crossed, not tradable


def test_depth_preview_marks_a_leg_absent_from_the_snapshot() -> None:
    bk = terminal._depth_preview({"legs": [{"ticker": "GONE"}]}, {})[0]
    assert bk["unavailable"] is True and bk["two_sided"] is False
    assert bk["market"] == "GONE"


def test_depth_preview_falls_back_to_positional_tickers() -> None:
    """A 2-leg shape with no uniform `legs` list still resolves its books via ticker_1 / ticker_2."""
    opp = {"ticker_1": "A", "ticker_2": "B"}
    books = terminal._depth_preview(opp, {"A": _book_row(contract="MA"), "B": _book_row(contract="MB")})
    assert [b["market"] for b in books] == ["MA", "MB"]
