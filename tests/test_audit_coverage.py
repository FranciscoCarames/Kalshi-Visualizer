"""Tests for scripts/audit_series_coverage.py — the PURE bucketing (no network).

Verifies that each live-series ticker is routed to the correct coverage bucket using the real
sports.sport_for_series + cfg.family_of, so the audit truthfully reports what the app owns vs misses.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "audit_series_coverage", REPO / "scripts" / "audit_series_coverage.py")
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


def test_supported_series_bucketed_supported():
    # A fetched, detector-eligible series (resolves to a sport, non-"other" family).
    r = audit.classify_series("KXWCGAME")
    assert r["sport_id"] == "soccer" and r["family"] == "game" and r["bucket"] == audit.SUPPORTED
    r2 = audit.classify_series("KXNBA")
    assert r2["sport_id"] == "nba" and r2["bucket"] == audit.SUPPORTED


def test_known_other_series_bucketed_recognized_other():
    # Owned but out-of-scope World Cup series → recognized + other (visible, never fetched/detected).
    for tk in ("KXWCSTAGE", "KXWCBESTHOST", "KXWCGOALLEADER", "KXWCGROUPWINNER"):
        r = audit.classify_series(tk)
        assert r["sport_id"] == "soccer" and r["family"] == "other" and r["bucket"] == audit.OTHER, tk


def test_unknown_sporty_series_flagged_candidate():
    # An unknown ticker whose category looks sports-y → flagged for ownership review.
    r = audit.classify_series("KXNEWLEAGUE", category="Sports", title="New League Winner")
    assert r["sport_id"] == "unknown" and r["bucket"] == audit.SPORTS_CANDIDATE


def test_unknown_nonsporty_series_out_of_scope():
    r = audit.classify_series("KXCPIYOY", category="Economics", title="CPI year-over-year")
    assert r["sport_id"] == "unknown" and r["bucket"] == audit.OUT_OF_SCOPE


def test_classify_coverage_skips_blank_tickers_and_renders():
    rows = audit.classify_coverage([
        {"ticker": "KXWCGAME"},
        {"ticker": "KXWCSTAGE"},
        {"ticker": "", "category": "Sports"},   # skipped
        {"ticker": "KXNEWLEAGUE", "category": "Sports", "title": "x"},
    ])
    assert len(rows) == 3
    report = audit._render_report(rows)
    assert "Series coverage audit" in report and audit.SPORTS_CANDIDATE in report
