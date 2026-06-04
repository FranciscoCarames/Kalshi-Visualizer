"""Uvicorn entrypoint for the FastAPI engine API (Stage 4).

Runs the typed REST engine (`api:app`). The Streamlit app (`app.py`) remains the interim UI until the
Stage-5 NiceGUI cutover; this serves the engine to API clients (and, later, the NiceGUI dashboard).
Run: ``python serve.py``.
"""
from __future__ import annotations

import uvicorn

import config

if __name__ == "__main__":
    uvicorn.run("api:app", host=config.API_HOST, port=config.API_PORT)
