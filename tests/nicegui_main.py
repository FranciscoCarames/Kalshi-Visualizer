"""Standalone NiceGUI entrypoint for the headless `User` browser smoke tests (PR 26c).

`nicegui.testing.user_simulation` runs this via `runpy.run_path(..., run_name='__main__')`, so it must NOT
start a server (that's why we can't point the harness at `serve.py` — its `uvicorn.run` would hang). We
register the dashboard `@ui.page('/')` and call `ui.run()`, which is a no-op under `NICEGUI_USER_SIMULATION`.
The dashboard reads the engine IN-PROCESS, so a standalone app (no FastAPI mount, no HTTP) renders fully
against whatever the test seeded into the snapshot store.

`nicegui.testing` resets the page registry before each simulation, then runs this file. A plain
`import webui.dashboard` is a cached no-op if an earlier test already imported it, so the `@ui.page('/')`
decorator wouldn't re-run and the page would be missing ("/ not found"). `importlib.reload` re-executes the
module body so the decorator re-registers the page in the fresh registry every run.
"""
import importlib

from nicegui import ui

import webui.dashboard
import webui.terminal

importlib.reload(webui.dashboard)
importlib.reload(webui.terminal)   # re-register the @ui.page('/terminal') Terminal Pro shell each run

ui.run()
