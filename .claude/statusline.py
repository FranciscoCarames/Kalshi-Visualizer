#!/usr/bin/env python3
"""Claude Code status line — model + a context-window gauge that warns when it's time to wrap up.

Reads the session JSON on stdin (schema: https://code.claude.com/docs/en/statusline) and prints a
single line: model, a 10-char context bar coloured by usage, the percentage, a WRAP-UP warning past the
threshold, and session cost. `context_window.used_percentage` is pre-calculated by Claude Code (input
tokens only); it can be null early in a session or right after /compact, which we render as "warming up".

Wired via `statusLine` in `.claude/settings.json` as `python .claude/statusline.py`. Runs locally, costs
no tokens. Fails soft: any error prints a minimal line so the bar never goes blank.
"""
import json
import sys

# Windows Python defaults stdout to cp1252, which can't encode the block/⚠ glyphs — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Usage thresholds (percent of context window). Tune to taste.
CAUTION = 70   # bar turns yellow
WARN = 85      # bar turns red + "WRAP UP" nudge

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("[ctx]")
        return 0

    model = "?"
    try:
        model = (data.get("model") or {}).get("display_name") or "?"
    except Exception:
        pass

    cw = data.get("context_window") or {}
    pct_raw = cw.get("used_percentage")

    cost = (data.get("cost") or {}).get("total_cost_usd")
    cost_str = f" {DIM}· ${cost:.2f}{RESET}" if isinstance(cost, (int, float)) else ""

    if pct_raw is None:
        # null early in the session / immediately after /compact
        print(f"{DIM}[{model}] ctx warming up...{RESET}{cost_str}")
        return 0

    pct = int(pct_raw)
    color = RED if pct >= WARN else YELLOW if pct >= CAUTION else GREEN
    filled = max(0, min(10, round(pct / 10)))
    bar = color + "█" * filled + DIM + "░" * (10 - filled) + RESET

    warn = f" {RED}⚠ WRAP UP — /compact or start fresh{RESET}" if pct >= WARN else ""
    print(f"[{model}] {bar} {color}{pct}%{RESET} ctx{warn}{cost_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
