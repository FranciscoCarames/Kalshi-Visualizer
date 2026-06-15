# PR Checklist

A practical pre-merge checklist for **Claude Code** before opening a PR or marking one ready. Short and
command-oriented. Aligns with `CLAUDE.md`, `AGENTS.md`, and `docs/REVIEW_PROTOCOL.md` (the verdict/risk
contract lives there — this is the operational pass).

**Docs-only skip rule:** if the change is docs-only and does not affect commands, dependencies,
deployment, or runtime behavior, the Tests / static / import / serve checks (§3–§6) may be skipped —
**only** with an explicit explanation in the PR handoff (§8).

## 1. Branch hygiene

- [ ] Branch is based on current `main`.
- [ ] One PR per change.
- [ ] No stacking on unmerged branches.
- [ ] Never commit or push to `main`.
- [ ] Changed files match the intended scope (no stray edits).

## 2. Scope guard

- [ ] No trading, order placement, conditional-probability / de-vig models, net-of-fees
      actionability, live WebSocket feeds, or other non-read-only behavior — unless explicitly requested
      (flag/reject otherwise).
- [ ] **Per-user authentication is now IN SCOPE** (owner-requested 2026-06): app-level login over the
      read-only surface, gated behind `AUTH_ENABLED`, per `docs/AUTH.md`. Auth must not touch engine logic
      (scanner/consistency/dutchbook/data) — a regression test pins the opportunity payload unchanged.
- [ ] Adding a new sport via a `SportConfig` drop-in is in scope.

## 3. Tests

- [ ] Behavior changes have targeted tests, **or** a written explanation of existing coverage.
- [ ] `pytest -q` passes.
- [ ] Docs-only changes may skip tests **only** with an explicit explanation.

## 4. Static and import checks

```bash
ruff check .
python -m py_compile config.py kalshi_client.py data.py consistency.py filters.py viz.py serve.py api.py
python -c "import serve, api, webui.dashboard"
```

## 5. Serve smoke

- [ ] Run `python serve.py` on a **non-default port, never :8000** (set `API_PORT`):

  ```powershell
  # PowerShell
  $env:API_PORT=8001; python serve.py
  ```

  ```bash
  # Bash
  API_PORT=8001 python serve.py
  ```

- [ ] `GET /`, `/healthz`, `/readyz`, `/metrics` respond as expected (e.g. `http://127.0.0.1:8001/healthz`).
- [ ] Stop the server after the smoke.

## 6. Deployment smoke (conditional)

If the change touches deployment, the import graph, `scripts/build_deploy_repo.py`, `deploy/`, `serve.py`
binding behavior, packaging, runtime dependencies, or deployment docs:

```bash
python scripts/build_deploy_repo.py <tmp> --no-pip-compile
cd <tmp> && PYTHONPATH=. python -c "import serve, api, webui.dashboard"
```

## 7. Docs and current-facts check

- [ ] Update docs when behavior, workflow, API assumptions, deployment, or user-facing labels change.
- [ ] When the change depends on Kalshi API behavior, market structure, settlement rules, fees, rate
      limits, sports schedules, listed markets, package/library behavior, or deployment behavior, verify
      against **current official docs or live evidence** — not memory. For Kalshi facts, use
      **<https://docs.kalshi.com/llms.txt>** first; if it is unavailable, incomplete, or insufficient,
      fall back to the relevant official Kalshi docs page or live evidence. If network access is
      unavailable, mark the assumption **unverified** — do not treat repo docs as current truth.

## 8. PR handoff

In the PR description, state:

- [ ] What changed (summary).
- [ ] Tests/checks run, with results.
- [ ] Tests/checks **not** run, and why.
- [ ] Residual risks or uncertainty.
- [ ] Whether docs were updated or were not needed.
- [ ] Whether the PR changes user-facing opportunity labels, actionability, or market logic.
