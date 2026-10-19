"""Recovery vault, hash-chained recorder and configuration validation."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from afterimage.common import sha256_text
from afterimage.config import load_settings
from afterimage.recovery import VAULT_FILES


def test_snapshot_restore_round_trip_with_hash_verification(client, settings):
    path = "config/app_settings.json"
    original_sha = sha256_text(VAULT_FILES[path])
    files = {f["path"]: f for f in client.get("/api/recovery/files").json()}
    assert files[path]["sha256"] == original_sha and files[path]["matches_original"]

    sim = client.post("/api/recovery/simulate-change", json={"path": path})
    assert sim.status_code == 201
    snap = sim.json()["snapshot"]
    assert snap["sha256"] == original_sha and snap["version"] == 1
    modified_sha = sim.json()["modified_sha256"]
    assert modified_sha != original_sha
    on_disk = (settings.vault_dir / "files" / path).read_text()
    assert '"debug_mode": true' in on_disk

    detail = client.get(f"/api/snapshots/{snap['snapshot_id']}").json()
    assert detail["store_integrity_ok"] and detail["current_sha256"] == modified_sha and detail["diff_to_current"]

    assert client.post(f"/api/snapshots/{snap['snapshot_id']}/restore", json={}).status_code == 422
    r = client.post(f"/api/snapshots/{snap['snapshot_id']}/restore", json={"confirm": True})
    assert r.status_code == 200
    res = r.json()
    assert res["verified"] is True
    assert res["before_sha256"] == modified_sha
    assert res["restored_sha256"] == res["expected_sha256"] == original_sha
    assert (settings.vault_dir / "files" / path).read_text() == VAULT_FILES[path]
    # the restore itself is reversible: the modified state was backed up first
    assert res["pre_restore_backup"]["sha256"] == modified_sha
    events = client.get("/api/events", params={"event_type": "file_restored"}).json()["events"]
    assert events and events[0]["outcome"] == "verified"


def test_vault_rejects_unmanaged_protected_and_traversal_paths(client):
    for path in ["../secret.txt", "secret.txt", "/etc/passwd", "config/../../x", "docs/notes.md", "deploy.env"]:
        r = client.post("/api/snapshots", json={"path": path})
        assert r.status_code == 400, path
    assert client.post("/api/snapshots/snp_0000000000000000/restore", json={"confirm": True}).status_code == 404


def test_manual_snapshot_versions_increment(client):
    a = client.post("/api/snapshots", json={"path": "src/inventory.py"}).json()
    b = client.post("/api/snapshots", json={"path": "src/inventory.py", "reason": "second"}).json()
    assert (a["version"], b["version"]) == (1, 2) and a["sha256"] == b["sha256"]
    assert len(client.get("/api/snapshots", params={"path": "src/inventory.py"}).json()) == 2


def test_hash_chain_detects_tampering(client, ctx):
    client.post("/api/runs/attack")
    assert client.get("/api/events/verify").json()["valid"] is True
    # Append-only triggers block normal UPDATE/DELETE.
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.execute("UPDATE events SET summary = 'edited' WHERE seq = 3")
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.execute("DELETE FROM events WHERE seq = 3")
    # Bypass the trigger (simulating someone with raw DB access) and the chain catches it.
    ctx.db.execute("DROP TRIGGER events_no_update")
    ctx.db.execute("UPDATE events SET summary = 'edited' WHERE seq = 3")
    result = client.get("/api/events/verify").json()
    assert result["valid"] is False and result["first_invalid_event_id"]


def test_config_validation(tmp_path):
    ok = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    assert ok.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    for bad in ({"AFTERIMAGE_CORS_ORIGINS": "*"}, {"AFTERIMAGE_CORS_ORIGINS": "localhost:5173"},
                {"AFTERIMAGE_MAX_READ_BYTES": "10"}, {"AFTERIMAGE_CLOUD_SYNC": "supabase"}):
        with pytest.raises((ValidationError, ValueError)):
            load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), **bad})


def test_cors_only_allows_configured_origin(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_env_example_copied_to_backend_env_loads(tmp_path):
    """The documented setup step (copy .env.example to backend/.env) must produce a valid config."""
    from pathlib import Path
    from afterimage.config import _read_dotenv
    example = Path(__file__).resolve().parents[2] / ".env.example"
    values = _read_dotenv(example)
    values["AFTERIMAGE_DATA_DIR"] = str(tmp_path)
    settings = load_settings(values)
    assert settings.llm_provider == "anthropic" and settings.gemini_model is None


def test_dotenv_parser_handles_inline_comments_and_quotes(tmp_path):
    from afterimage.config import _read_dotenv
    env = tmp_path / ".env"
    env.write_text('A=1  # note\nB="x # y"\nC=\'q\'\n# full comment\nD=\nE=http://h:1#frag\n')
    assert _read_dotenv(env) == {"A": "1", "B": "x # y", "C": "q", "D": "", "E": "http://h:1#frag"}
