"""Qualifier-setups table column config (webui.dashboard._QS_COLUMNS / _QS_HIDDEN).

The column chooser (`build_column_menu`) is built directly from `_QS_COLUMNS` (one checkbox per
non-`required` column), so asserting on these lists is the branch-independent way to prove the chooser
exposes the new columns and that the default-visible / hidden split is correct — no browser needed.
"""

from webui import dashboard

_COLS = {c["name"]: c for c in dashboard._QS_COLUMNS}
_LABELS = {c["label"] for c in dashboard._QS_COLUMNS}
_FORBIDDEN = ("riskless", "locked", "hedge", "arbitrage")

_EXPECTED_DEFAULT_VISIBLE = [
    "new", "sport", "name", "setup", "qualifier", "cost", "premium", "if_top2", "if_not_top2",
    "max_units", "worst_leg_quote", "comparator_quote", "legs", "review_status", "caveat"]


def test_renamed_labels_present_old_labels_gone():
    assert "Qualifier YES ask ¢" in _LABELS and "Cheaper vs qualifier ¢" in _LABELS
    assert "Qualify YES ¢" not in _LABELS
    assert "Qualifier − top-two cost ¢" not in _LABELS
    assert "Note" not in _LABELS                       # long prose Note replaced by caveat chips


def test_new_default_visible_columns_present():
    for label in ("Top-two bundle cost ¢", "If top two ¢", "If not top two ¢", "Max units",
                  "Worst leg quote", "Comparator quote", "Review status", "Caveat"):
        assert label in _LABELS, label


def test_default_visible_set_is_focused():
    visible = [c["name"] for c in dashboard._QS_COLUMNS
               if c.get("required") or c["name"] not in dashboard._QS_HIDDEN]
    assert visible == _EXPECTED_DEFAULT_VISIBLE


def test_hidden_columns_exist_and_are_offerable():
    for name in dashboard._QS_HIDDEN:
        assert name in _COLS, name                     # every hidden name is a real column
        assert not _COLS[name].get("required")         # required columns are never hidden/offered
    # The heuristic Support score is hidden, not default-visible.
    assert "support" in dashboard._QS_HIDDEN


def test_quote_columns_sort_on_rank_field():
    assert _COLS["worst_leg_quote"]["field"] == "worst_leg_quote_rank"
    assert _COLS["comparator_quote"]["field"] == "comparator_quote_rank"


def test_group_and_event_ticker_columns_absent():
    # Not in the unified schema; intentionally deferred to a separate schema PR.
    assert "Group" not in _LABELS and "Event ticker" not in _LABELS


def test_column_headers_have_no_arbitrage_wording():
    blob = " ".join(_LABELS).lower()
    for word in _FORBIDDEN:
        assert word not in blob, word
