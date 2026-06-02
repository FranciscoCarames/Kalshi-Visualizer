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
