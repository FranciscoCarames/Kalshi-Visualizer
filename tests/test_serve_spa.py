"""Routing smoke tests for the Terminal Pro SPA static mount (serve.mount_spa).

The SPA is served at /terminal only when its built dist exists (a gitignored build artifact), so the mount
is conditional — these prove both branches without needing a real `npm run build`: a missing dist leaves
/terminal unmounted (never breaks boot), and a present dist serves index.html at /terminal/.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import serve


def test_absent_dist_does_not_mount(tmp_path):
    app = FastAPI()
    assert serve.mount_spa(app, tmp_path / "nope") is False
    assert TestClient(app).get("/terminal/").status_code == 404      # unmounted, but boot is fine


def test_present_dist_serves_the_spa_index(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Kalshi Terminal Pro</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("// built bundle", encoding="utf-8")
    app = FastAPI()
    assert serve.mount_spa(app, dist) is True
    c = TestClient(app)
    root = c.get("/terminal/")
    assert root.status_code == 200 and "Kalshi Terminal Pro" in root.text   # html=True serves index
    assert c.get("/terminal/assets/app.js").status_code == 200              # built assets resolve
