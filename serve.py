"""Entrypoint: the FastAPI engine API + the NiceGUI dashboard, served by uvicorn (Stage 5).

The REST API (`api.app`) and the NiceGUI opportunity-first dashboard run on ONE app: importing
`webui.dashboard` registers the `@ui.page('/')`, and `ui.run_with` mounts NiceGUI onto `api.app`. The
Streamlit app (`app.py`) is unchanged and still runs separately until a later retirement milestone.
Run: ``python serve.py``  (UI at ``/``, REST at ``/opportunities`` etc., OpenAPI at ``/docs``).
"""
from __future__ import annotations

import os

import uvicorn
from nicegui import ui

import api
import config
import webui.dashboard  # noqa: F401  — importing registers the @ui.page('/') dashboard

# Real storage secret comes from the env; the config value is only a clearly-labeled dev fallback.
_storage_secret = os.getenv("NICEGUI_STORAGE_SECRET") or config.NICEGUI_STORAGE_SECRET_FALLBACK

ui.run_with(api.app, mount_path="/", storage_secret=_storage_secret)

if __name__ == "__main__":
    uvicorn.run(api.app, host=config.API_HOST, port=config.API_PORT)
