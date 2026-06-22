#!/usr/bin/env python3
"""PreToolUse guard — block destructive git, tailored to this repo's workflow.

Enforces CLAUDE.md "Git workflow" (never push/merge to origin/main; deliver on feature branches) and
blocks irreversible local ops — WITHOUT breaking the normal flow (feature-branch pushes, commits, fetch,
merges, branch switches, single-file checkout all pass).

It parses the ACTUAL git invocation (subcommand + flags), not raw substrings, so a commit *message* that
mentions "reset --hard" or "git push origin main" is never mistaken for the command. Heredoc bodies are
stripped first; each `;`/`&&`/`|`/newline segment is tokenized with shlex; only segments that are a git
call are inspected.

Reads the tool payload on stdin. Exit 2 + stderr = blocked (PreToolUse surfaces the message and the command
never runs). Exit 0 = allowed. Fails OPEN (any error → exit 0) so it can't wedge the session. Customized
from mattpocock/skills `git-guardrails-claude-code` (MIT); rewritten in Python (no jq).

BLOCKS: push to main (explicit main/master refspec dst, or a bare/remote-only push while HEAD is on
        main/master); force-push (--force / -f; --force-with-lease allowed); push --all / --mirror;
        reset --hard; clean -f; branch -D; checkout . / restore . (mass discard).
ALLOWS: git push -u origin <feature-branch>, commit (any message), add, fetch, pull, merge, rebase,
        switch -c, checkout <branch>, checkout <single-file>, reset (soft/mixed), branch -d.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;\n|&]")
# git global options that consume the following token (so we can find the real subcommand)
VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def _strip_heredocs(command: str) -> str:
    """Remove heredoc bodies (e.g. commit messages) so their text isn't parsed as commands."""
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = re.search(r"<<-?\s*[\"']?([A-Za-z_]\w*)[\"']?", line)
        out.append(re.sub(r"<<-?\s*[\"']?[A-Za-z_]\w*[\"']?", "", line) if m else line)
        i += 1
        if m:
            delim = m.group(1)
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1  # skip the closing delimiter line
    return "\n".join(out)


def _git_tokens(segment: str):
    """Return the token list of a git invocation in this segment, or None if it isn't one."""
    try:
        toks = shlex.split(segment, comments=False, posix=True)
    except ValueError:
        toks = segment.split()
    # drop leading env assignments (VAR=val) and sudo
    while toks and (re.match(r"^\w+=", toks[0]) or toks[0] == "sudo"):
        toks = toks[1:]
    if not toks or os.path.basename(toks[0]) != "git":
        return None
    return toks[1:]


def _subcommand(rest):
    """Find (subcommand, args_after_subcommand), skipping git global options."""
    i = 0
    while i < len(rest):
        t = rest[i]
        if t in VALUE_OPTS:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, rest[i + 1:]
    return None, []


def _check_push(args, cwd):
    has_lease = "--force-with-lease" in args
    for a in args:
        if not has_lease and (a == "--force" or a == "-f" or a.startswith("--force=")):
            return "force-push is destructive to shared history (--force-with-lease is allowed)."
        if a in ("--all", "--mirror"):
            return "`git push --all/--mirror` can push protected branches (e.g. main)."
    positionals = [a for a in args if not a.startswith("-")]
    # first positional is the remote; the rest are refspecs/branches (dst = part after ':')
    dsts = [p.split(":")[-1] for p in positionals[1:]]
    if any(d in PROTECTED for d in dsts):
        return "pushing to origin/main is forbidden — the owner merges via PR (CLAUDE.md Git workflow)."
    if not dsts:  # bare `git push` or remote-only → targets the current branch
        branch = _current_branch(cwd)
        if branch in PROTECTED:
            return f"pushing while on '{branch}' targets origin/main (forbidden — deliver on a feature branch)."
    return None


def _blocked(command: str, cwd: str):
    for seg in SEGMENT_SPLIT.split(_strip_heredocs(command)):
        rest = _git_tokens(seg)
        if rest is None:
            continue
        sub, args = _subcommand(rest)
        if sub == "push":
            r = _check_push(args, cwd)
            if r:
                return r
        elif sub == "reset" and "--hard" in args:
            return "`git reset --hard` discards committed/working state irreversibly."
        elif sub == "clean" and any(a.startswith("-") and "f" in a for a in args):
            return "`git clean -f` permanently deletes untracked files (scratch you may want)."
        elif sub == "branch" and ("-D" in args or ("--delete" in args and "--force" in args)):
            return "`git branch -D` force-deletes a branch (use -d for a safe, merged-only delete)."
        elif sub in ("checkout", "restore") and "." in args:
            return "`git checkout .` / `git restore .` discards ALL local changes at once."
    return None


def _current_branch(cwd: str):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or None, capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None  # undeterminable → don't block (fail open)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    try:
        reason = _blocked(command, cwd)
    except Exception:
        return 0  # fail open
    if reason:
        sys.stderr.write(
            f"[git-guardrails] BLOCKED: {reason}\n"
            "If you genuinely intend this, run it yourself in the terminal (prefix with `!`).\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
