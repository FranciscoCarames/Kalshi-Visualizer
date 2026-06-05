# AGENTS.md

Operating guide for **Codex** and other `AGENTS.md`-aware coding agents.

**This file lists only the differences from [`CLAUDE.md`](CLAUDE.md).** Read `CLAUDE.md` first — it is
the authoritative guide for architecture, API details, pricing model, consistency rules, UI conventions,
code style, and git workflow. Everything there applies here too.

---

## Codex-specific notes

### Network

Network egress is sandboxed by default. Live Kalshi calls, `pip`, and `git push` require network
access to be explicitly enabled.

`api.kalshi.com` does **not** resolve — always use `external-api.kalshi.com`.

### Multi-line git text

Prefer `--body-file` or a heredoc (`<<'EOF'`) for multi-line commit/PR messages. Inline newline
quoting is unreliable in the Codex shell.

### Verification checklist

Before committing (same steps as CLAUDE.md):

```bash
pytest -q
python -m py_compile config.py kalshi_client.py data.py consistency.py filters.py viz.py serve.py api.py
ruff check .
python serve.py  # on a NON-default port; then GET /healthz, /readyz, /metrics
```

For the LAN deploy artifact, also smoke the builder: `python scripts/build_deploy_repo.py <tmp>
--no-pip-compile` then `cd <tmp> && PYTHONPATH=. python -c "import serve, api, webui.dashboard"` (the
import-graph allowlist must be complete). `serve.py` on a non-default port — never touch the shared `:8000`.
