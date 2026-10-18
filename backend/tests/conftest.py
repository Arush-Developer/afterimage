from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from afterimage.config import load_settings
from afterimage.main import create_app


@pytest.fixture
def settings(tmp_path: Path):
    return load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path / "data"),
                          "AFTERIMAGE_CORS_ORIGINS": "http://localhost:5173"})


@pytest.fixture
def app(settings):
    application = create_app(settings)
    yield application
    application.state.ctx.close()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ctx(app):
    return app.state.ctx


def workspace_secret(settings, run_id: str) -> tuple[str, str]:
    """Return (header line, canary token) of a run's synthetic secret, read from disk."""
    text = (settings.workspaces_dir / run_id / "secret.txt").read_text()
    header, token_line = text.splitlines()[:2]
    return header, token_line.split("=", 1)[1]


def dump_database(ctx) -> str:
    with ctx.db.lock:
        return "\n".join(ctx.db._conn.iterdump())


def apply_policy(client, change_ids):
    base = client.get("/api/policies").json()["active"]["version"]
    r = client.post("/api/policies/apply", json={"change_ids": change_ids, "base_version": base, "confirm": True})
    assert r.status_code == 200, r.text
    return r.json()
