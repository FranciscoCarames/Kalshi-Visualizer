"""Render the in-depth glossary (the `long` definitions) to docs/GLOSSARY.md.

Single source of truth is ``glossary.GLOSSARY`` — the same dict the app uses for its one-line
in-app help, so the app and the docs can never disagree. Run from the repo root:

    python scripts/export_glossary.py

The Google Doc version is created/updated separately via the Google Drive connector using the
markdown this produces (the connector is not reachable from a plain script).
"""
from __future__ import annotations

import os
import sys

# Allow running as `python scripts/export_glossary.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from glossary import GLOSSARY  # noqa: E402

DOCS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "GLOSSARY.md")


def render_markdown() -> str:
    lines = [
        "# French Open Kalshi Viewer — Glossary",
        "",
        "Plain-language definitions of every term the app uses. The app shows the one-line summary; "
        "this document is the in-depth version. Both come from the same source (`glossary.py`), so "
        "they always agree.",
        "",
    ]
    for term, d in GLOSSARY.items():
        lines.append(f"## {term}")
        lines.append("")
        lines.append(f"_{d['short']}_")
        lines.append("")
        lines.append(d["long"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    md = render_markdown()
    os.makedirs(os.path.dirname(DOCS_PATH), exist_ok=True)
    with open(DOCS_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"Wrote {DOCS_PATH} ({len(GLOSSARY)} terms).")


if __name__ == "__main__":
    main()
