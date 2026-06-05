# AGENTS.md

Operating guide for **Codex** and other `AGENTS.md`-aware coding agents.

**This file lists only the differences from [`CLAUDE.md`](CLAUDE.md).** Read `CLAUDE.md` first — it is
the authoritative guide for architecture, API details, pricing model, consistency rules, UI conventions,
code style, and git workflow. Everything there applies here too.

---

## Codex-specific notes

### Running Streamlit

Use `python -m streamlit`, not the bare `streamlit` shim (not executable in the Codex environment):

```bash
python -m streamlit run app.py
python -m streamlit run app.py --server.headless true --server.port 8765  # headless
```

Headless health check: `GET http://localhost:8765/_stcore/health` → `200`.

AppTest smoke: `streamlit.testing.v1.AppTest.from_file("app.py").run()` — assert `not at.exception`.

### Network

Network egress is sandboxed by default. Live Kalshi calls, `pip`, and `git push` require network
access to be explicitly enabled.

`api.kalshi.com` does **not** resolve — always use `external-api.kalshi.com`.

### Multi-line git text

Prefer `--body-file` or a heredoc (`<<'EOF'`) for multi-line commit/PR messages. Inline newline
quoting is unreliable in the Codex shell.

### Verification checklist

Before committing (same steps as CLAUDE.md, but use `python -m streamlit`):

```bash
pytest -q
python -m py_compile config.py kalshi_client.py data.py consistency.py filters.py viz.py app.py serve.py api.py
ruff check .
python -m streamlit run app.py --server.headless true --server.port 8765  # then check /_stcore/health
python serve.py  # on a NON-default port; then GET /healthz, /readyz, /metrics
```

For the LAN deploy artifact, also smoke the builder: `python scripts/build_deploy_repo.py <tmp>
--no-pip-compile` then `cd <tmp> && PYTHONPATH=. python -c "import serve, api, webui.dashboard"` (the
import-graph allowlist must be complete). `serve.py` on a non-default port — never touch the shared `:8000`.
