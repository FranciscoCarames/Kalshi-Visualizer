"""Glossary is the single source of help text — guard it against orphan jargon and gaps."""
from __future__ import annotations

import consistency
import glossary


def test_every_term_has_short_and_long():
    assert glossary.GLOSSARY, "glossary must not be empty"
    for term, d in glossary.GLOSSARY.items():
        assert d.get("short", "").strip(), f"{term} missing a short definition"
        assert d.get("long", "").strip(), f"{term} missing a long definition"


def test_column_help_keys_resolve_to_real_terms():
    for label, key in glossary.COLUMN_HELP.items():
        assert key in glossary.GLOSSARY, f"COLUMN_HELP[{label!r}] -> unknown term {key!r}"
        assert glossary.help_for(label) == glossary.GLOSSARY[key]["short"]
    assert glossary.help_for("a label with no glossary entry") == ""


def test_dutch_book_copy_is_conservative_and_single_sourced():
    """The dutch-book glossary entry must NOT call findings 'locked'/'riskless'/'true arbitrage', and the
    canonical basis phrase is single-sourced via DUTCH_BOOK_BASIS (PR 5 — conservative labeling)."""
    db = glossary.GLOSSARY["Dutch book"]
    blob = (db["short"] + " " + db["long"]).lower()
    for banned in ("locked", "riskless", "true arbitrage"):
        assert banned not in blob, f"dutch-book copy still says {banned!r}: {blob!r}"
    assert glossary.DUTCH_BOOK_BASIS in db["long"], "long text must reference DUTCH_BOOK_BASIS (single source)"
    assert "under normal one-winner settlement" in glossary.DUTCH_BOOK_BASIS
    # The renamed column key resolves; the old 'Locked edge' key is gone.
    assert "Gross edge (¢)" in glossary.COLUMN_HELP and "Locked edge (¢)" not in glossary.COLUMN_HELP
    assert glossary.help_for("Gross edge (¢)") == db["short"]


def test_speculative_top2_basis_is_conservative_and_names_the_best_third_hole():
    """The top-two bundle caveat must explain the best-third payoff hole and ban POSITIVE claims, while
    allowing the negations 'not arbitrage' / 'not a hedge'."""
    blob = glossary.SPECULATIVE_TOP2_BASIS.lower()
    assert "best-third" in blob, "must explain why top-two ≠ qualify"
    for banned in ("riskless", "locked", "guaranteed", "true arbitrage"):
        assert banned not in blob, f"top-two caveat still makes a positive claim: {banned!r}"
    assert "not arbitrage" in blob and "not a" in blob  # the conservative negations are present
    assert "comparator" in blob                          # the qualifier is a comparator, not a leg


def test_known_limit_badges_structured_and_universal():
    """The limitation strip is a structured (label, tooltip) constant authored as the UI source of truth —
    short labels, real tooltips, and the four universal gross/top-of-book limits present."""
    assert glossary.KNOWN_LIMIT_STRIP.strip()
    assert glossary.KNOWN_LIMIT_BADGES, "must define at least one universal limit badge"
    labels = {lbl for lbl, _ in glossary.KNOWN_LIMIT_BADGES}
    assert {"Gross", "Top-of-book", "Fees not modeled", "Depth not modeled"} <= labels
    for lbl, tip in glossary.KNOWN_LIMIT_BADGES:
        assert lbl.strip() and len(lbl) <= 24, f"badge label not short: {lbl!r}"
        assert tip.strip() and len(tip) > len(lbl), f"badge {lbl!r} needs a real tooltip"


def test_blockers_are_non_empty_and_format_cleanly():
    assert glossary.BLOCKERS
    for key, template in glossary.BLOCKERS.items():
        assert template.strip(), f"blocker {key} is empty"
        # Templates must format with the placeholders the code supplies (leg / status).
        template.format(leg="broader", status="finalized")
    assert glossary.WATCHLIST_NOTE.strip()


def test_consistency_only_emits_known_blocker_text():
    """Every blocker phrase the classifier can produce comes from glossary.BLOCKERS (no ad-hoc
    jargon). Build the set of all possible rendered blocker strings and confirm membership."""
    known = set()
    for tmpl in glossary.BLOCKERS.values():
        for leg in ("broader", "deeper"):
            for status in ("finalized", "settled", "closed", "initialized"):
                known.add(tmpl.format(leg=leg, status=status))

    def leg(**kw):
        base = {"display_c": None, "yes_bid_c": None, "yes_ask_c": None, "yes_bid_size": 100,
                "yes_ask_size": 100, "quote_quality": "Tight", "rules_primary": "",
                "status": "active", "no_ask_c": None, "contract": "C"}
        base.update(kw)
        return base

    # A representative not-tradable case: display-only violation with a finalized leg.
    out = consistency._classify(
        leg(display_c=50, bid_c=20, ask_c=22, status="finalized"),
        leg(display_c=40, bid_c=58, ask_c=60),
        equivalence=True,
    )
    for phrase in [p for p in out["blockers"].split("; ") if p]:
        assert phrase in known, f"blocker phrase not single-sourced from glossary: {phrase!r}"
