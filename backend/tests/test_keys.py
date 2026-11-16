"""API keys added from the Settings page: stored in the backend only, never returned."""
from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from afterimage.config import load_settings
from afterimage.keystore import FILE_NAME
from afterimage.main import create_app

FAKE_GEMINI = "fake-gemini-key-for-tests-0123456789"
FAKE_ANTHROPIC = "fake-anthropic-key-for-tests-0123456789"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # setenv first so monkeypatch restores the original state, whatever the code under test does
    for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-afterimage-test")


def make_client(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path / "data"),
                              "AFTERIMAGE_CORS_ORIGINS": "http://localhost:5173"})
    app = create_app(settings)
    return app, TestClient(app)


def provider(client, name):
    return next(p for p in client.get("/api/providers").json()["providers"] if p["provider"] == name)


def test_set_key_configures_provider_and_is_never_returned(tmp_path):
    app, client = make_client(tmp_path)
    with client:
        assert provider(client, "gemini")["configured"] is False
        r = client.post("/api/keys/gemini", json={"api_key": f"  {FAKE_GEMINI}\n", "remember": True})
        assert r.status_code == 200, r.text
        assert r.json() == {"provider": "gemini", "present": True, "source": "saved"}
        assert os.environ["GEMINI_API_KEY"] == FAKE_GEMINI
        status = provider(client, "gemini")
        assert status["configured"] is True and status["key_source"] == "saved"
        for path in ("/api/keys", "/api/providers", "/api/settings"):
            assert FAKE_GEMINI not in client.get(path).text
    app.state.ctx.close()


def test_remembered_key_is_private_on_disk_and_reloaded(tmp_path):
    app, client = make_client(tmp_path)
    with client:
        client.post("/api/keys/gemini", json={"api_key": FAKE_GEMINI, "remember": True})
    app.state.ctx.close()
    path = tmp_path / "data" / FILE_NAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    os.environ.pop("GEMINI_API_KEY")
    app, client = make_client(tmp_path)  # simulates a backend restart
    with client:
        assert provider(client, "gemini")["configured"] is True
        assert client.get("/api/keys").json()["keys"]["gemini"]["source"] == "saved"
    app.state.ctx.close()


def test_session_only_key_is_not_written(tmp_path):
    app, client = make_client(tmp_path)
    with client:
        r = client.post("/api/keys/anthropic", json={"api_key": FAKE_ANTHROPIC, "remember": False})
        assert r.json()["source"] == "session"
        assert provider(client, "anthropic")["configured"] is True
    app.state.ctx.close()
    assert not (tmp_path / "data" / FILE_NAME).exists()


def test_shell_environment_wins_at_startup_and_cannot_be_deleted_from_ui(tmp_path, monkeypatch):
    app, client = make_client(tmp_path)
    with client:
        client.post("/api/keys/gemini", json={"api_key": FAKE_GEMINI, "remember": True})
    app.state.ctx.close()
    monkeypatch.setenv("GEMINI_API_KEY", "shell-key-0123456789-abcdefgh")
    app, client = make_client(tmp_path)
    with client:
        assert os.environ["GEMINI_API_KEY"] == "shell-key-0123456789-abcdefgh"
        assert client.get("/api/keys").json()["keys"]["gemini"]["source"] == "environment"
        r = client.post("/api/keys/gemini/delete", json={})
        assert r.status_code == 409 and "terminal" in r.json()["detail"]
        assert os.environ["GEMINI_API_KEY"] == "shell-key-0123456789-abcdefgh"
    app.state.ctx.close()


def test_delete_key(tmp_path):
    app, client = make_client(tmp_path)
    with client:
        client.post("/api/keys/gemini", json={"api_key": FAKE_GEMINI, "remember": True})
        r = client.post("/api/keys/gemini/delete", json={})
        assert r.status_code == 200 and r.json()["present"] is False
        assert "GEMINI_API_KEY" not in os.environ
        assert provider(client, "gemini")["configured"] is False
    app.state.ctx.close()
    assert not (tmp_path / "data" / FILE_NAME).exists()


@pytest.mark.parametrize("bad", ["short", "has spaces in the middle of the key 123", "x" * 600, "ключ" * 10])
def test_invalid_keys_rejected_without_echo(tmp_path, bad):
    app, client = make_client(tmp_path)
    with client:
        r = client.post("/api/keys/gemini", json={"api_key": bad})
        assert r.status_code == 400
        assert bad.strip() not in r.text
        assert "GEMINI_API_KEY" not in os.environ
    app.state.ctx.close()


def test_rejects_non_json_and_unknown_provider(tmp_path):
    app, client = make_client(tmp_path)
    with client:
        r = client.post("/api/keys/gemini", content=f'{{"api_key": "{FAKE_GEMINI}"}}',
                        headers={"Content-Type": "text/plain"})
        assert r.status_code in (400, 422)
        assert "GEMINI_API_KEY" not in os.environ
        assert client.post("/api/keys/ollama", json={"api_key": FAKE_GEMINI}).status_code == 422
    app.state.ctx.close()


def test_rejects_requests_from_other_machines(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path / "data"),
                              "AFTERIMAGE_CORS_ORIGINS": "http://localhost:5173"})
    app = create_app(settings)
    with TestClient(app, client=("192.168.1.50", 50000)) as client:
        r = client.post("/api/keys/gemini", json={"api_key": FAKE_GEMINI})
        assert r.status_code == 400 and "computer running the backend" in r.json()["detail"]
        assert "GEMINI_API_KEY" not in os.environ
    app.state.ctx.close()


def test_key_not_written_to_logs(tmp_path, caplog):
    app, client = make_client(tmp_path)
    with caplog.at_level("DEBUG"), client:
        client.post("/api/keys/gemini", json={"api_key": FAKE_GEMINI})
    app.state.ctx.close()
    assert FAKE_GEMINI not in caplog.text
    assert "API key for gemini set" in caplog.text
