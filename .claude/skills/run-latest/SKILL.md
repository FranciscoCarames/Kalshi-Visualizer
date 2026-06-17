---
name: run-latest
description: Discover the most current version of this app's code — the branch with the newest commit, even if it's an unmerged feature branch — check it out, boot serve.py, and open the dashboard in the browser. Use when the user says "run the latest version", "run the newest code", "launch the current app", or similar.
---

# run-latest

Boot the **most current version** of the Kalshi dashboard. "Most current" means the branch
with the newest commit across all local and remote branches — it may NOT be merged to `main`.
Do the work in order; stop and report if a step fails.

> Note (policy 2026-06-16): `origin/main` is the canonical source of truth and "main" always means
> `origin/main`. This skill still picks the *newest branch* to demo in‑progress work, but new feature
> work must branch off the latest `origin/main` (see CLAUDE.md "Git workflow"). Always `git fetch` first
> so "newest" reflects the freshest remote state.

## 1. Find the most current branch

Fetch remotes, then list every branch sorted by last-commit time (newest first):

```powershell
git fetch --all --prune
git for-each-ref --sort=-committerdate --format='%(committerdate:iso8601)  %(refname:short)' refs/heads refs/remotes
```

The top row is the most current branch. Skip noise refs (`origin/HEAD`, duplicate
remote-tracking rows that mirror a local branch). Tell the user which branch won and its
commit date before switching.

## 2. Check it out (preserve uncommitted work)

If the working tree is dirty (`git status --porcelain` non-empty), do NOT blow it away — tell
the user and ask whether to stash, or just stay on the current branch. If clean:

```powershell
git checkout <branch>          # for a remote-only branch: git checkout -t origin/<branch>
git pull --ff-only             # fast-forward to the remote tip if one exists
```

If the most current branch is the one already checked out, skip the checkout and just `git pull --ff-only`.

## 3. Kill any stale serve.py on port 8000

A stale `serve.py` holds port 8000, so a fresh boot would silently hit the OLD process
(see the [[stale-serve-port-8000]] / [[stale-snapshot-gotcha]] gotchas). `pkill`-style name
matching misses it — kill by PID via the port:

```powershell
$pids = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($pids) { $pids | ForEach-Object { Stop-Process -Id $_ -Force } }
```

## 4. Boot serve.py

Install deps only if imports fail or requirements changed; otherwise skip for speed.

```powershell
python serve.py
```

Run it in the **background** (Bash/PowerShell `run_in_background: true`) so the skill can
continue. Capture the log so a boot failure is visible.

## 5. Confirm health, then open the browser

Poll `/healthz` until it returns 200 (give it ~15s), and check `/readyz`:

```powershell
# loop a few times with a short delay
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz   # expect 200
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/readyz    # ready / degraded / not_ready
```

Once `/healthz` is 200, open the dashboard:

```powershell
Start-Process "http://127.0.0.1:8000"
```

## 6. Report

Tell the user: which branch is running, its latest commit (short SHA + subject), the
`/readyz` state, and the URL. If `/readyz` is `degraded`/`not_ready`, note that the snapshot
may be stale and a "Scan now" (or `POST /scan`) will refresh it.

## Notes / gotchas

- The running server caches imported modules — there is no auto-reload. This skill restarts
  cleanly, so editing code then re-running the skill always picks up changes. For a phantom
  `ImportError`, clear bytecode: `Remove-Item -Recurse -Force __pycache__, tests/__pycache__`.
- Live Kalshi calls need network; if the sandbox blocks it, the dashboard still boots and
  serves the last persisted snapshot.
- Never commit or switch off the user's work silently — step 2 guards a dirty tree.
