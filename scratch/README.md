# scratch/ — disposable working files

Everything in this directory is **gitignored** (except this README). Put throwaway artifacts here instead
of the repo root: QA audits, diagnostic JSON dumps, screenshots, one-off probe outputs, pre-compaction
backups, etc.

**Why this exists:** it lets `git add <paths>` stay safe and keeps `git status` clean *mechanically*,
instead of relying on the discipline of "never `git add -A`". Throwaway lands in `scratch/` (ignored) and
never shows up as untracked noise or risks being staged by accident.

Real deliverables still go in their proper place (`docs/` for documentation, `frontend/` for SPA assets,
`tests/` for tests, etc.) — not here.
