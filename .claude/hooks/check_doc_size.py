#!/usr/bin/env python3
"""Stop hook — keep always-loaded Claude instruction files lean (advisory only).

Claude Code's docs target **under 200 lines** for CLAUDE.md (longer files consume more
context and reduce adherence). This hook runs once when Claude finishes a response and emits
a *non-blocking* warning if the root CLAUDE.md or any `.claude/rules/*.md` file is over budget,
nudging module-specific detail into a path-scoped rule.

Design: warn-only. It prints a ``systemMessage`` and exits 0, so it never blocks Claude from
stopping and can never loop. **Fails open** (any error → silent exit 0). Wired as a Stop hook
in ``.claude/settings.json``; it scans files directly and ignores stdin.
"""
import glob
import json
import os
import sys

CLAUDE_MD_BUDGET = 200      # root CLAUDE.md — official guidance
RULE_BUDGET = 200           # each .claude/rules/*.md


def _line_count(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def main() -> int:
    # Read (and ignore) stdin so the hook protocol stays happy.
    try:
        sys.stdin.read()
    except Exception:
        pass

    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    targets = [(os.path.join(root, "CLAUDE.md"), CLAUDE_MD_BUDGET)]
    targets += [
        (p, RULE_BUDGET)
        for p in glob.glob(os.path.join(root, ".claude", "rules", "*.md"))
    ]

    over = []
    for path, budget in targets:
        try:
            n = _line_count(path)
        except Exception:
            continue  # missing/unreadable → skip
        if n > budget:
            over.append(f"{os.path.basename(path)} = {n} lines (budget {budget})")

    if over:
        msg = (
            "[claude-docs-guard] Over the line budget: "
            + "; ".join(over)
            + ". Move module-specific detail into a path-scoped .claude/rules/*.md "
            "file so always-loaded instructions stay lean (see CLAUDE.md 'Rules map')."
        )
        print(json.dumps({"systemMessage": msg}))

    return 0


if __name__ == "__main__":
    sys.exit(main())
