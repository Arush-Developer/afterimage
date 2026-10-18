"""Snapshot and recovery vault for synthetic files.

* Only files in VAULT_FILES (fictional, non-secret) can be snapshotted or restored.
* Snapshot content is stored content-addressed (objects/<sha256>) with metadata in SQLite.
* Every restore first snapshots the current state, so a restore can itself be undone.
* Restoring a file does NOT undo external side effects (network calls, other systems).
"""

from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path
from typing import Any

from .common import NotFoundError, ValidationFailure, new_id, sha256_bytes, utc_now
from .db import Database
from .policy import glob_match
from .recorder import EventRecorder
from .workspace import resolve_workspace_path

VAULT_FILES: dict[str, str] = {
    "config/app_settings.json": """{
  "app": "orbit-inventory",
  "environment": "demo",
  "debug_mode": false,
  "reorder_threshold": 10,
  "report_recipients": ["ops-team@example.invalid"]
}
""",
    "src/inventory.py": '''"""Stock level helpers for the fictional Orbit Inventory app."""

REORDER_THRESHOLD = 10


def needs_reorder(stock):
    return sorted(sku for sku, qty in stock.items() if qty < REORDER_THRESHOLD)
''',
}

# Deterministic "unauthorized agent edits" used for the recovery demo.
SIMULATED_EDITS: dict[str, tuple[str, str]] = {
    "config/app_settings.json": ('"debug_mode": false', '"debug_mode": true,\n  "telemetry_endpoint": "http://collector.example.invalid/upload"'),
    "src/inventory.py": ("REORDER_THRESHOLD = 10", "REORDER_THRESHOLD = 0  # SIMULATED unauthorized agent edit"),
}

PROTECTED_PATTERNS = ("**/secret*", "**/*.env", "**/.env*", "**/*.pem", "**/*.key", "**/credentials*")
MAX_VAULT_FILE = 64 * 1024


class RecoveryVault:
    def __init__(self, root: Path, db: Database, recorder: EventRecorder):
        self.root = root
        self.files_dir = root / "files"
        self.objects_dir = root / "objects"
        self.db = db
        self.recorder = recorder

    def ensure(self, reset: bool = False) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        for rel, content in VAULT_FILES.items():
            target = self.files_dir / rel
            if reset or not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

    # -- helpers ----------------------------------------------------------------
    def _resolve(self, path: str) -> Path:
        if any(glob_match(p, path) for p in PROTECTED_PATTERNS):
            raise ValidationFailure("protected files can never be snapshotted")
        if path not in VAULT_FILES:
            raise ValidationFailure(f"'{path}' is not a vault-managed synthetic file")
        resolved = resolve_workspace_path(self.files_dir, path)
        if resolved.violation or resolved.absolute is None or resolved.canonical != path:
            raise ValidationFailure("invalid vault path")
        return resolved.absolute

    def _read(self, path: str) -> bytes:
        target = self._resolve(path)
        data = target.read_bytes()
        if len(data) > MAX_VAULT_FILE:
            raise ValidationFailure("file too large for the demo vault")
        return data

    def _object(self, sha: str) -> Path:
        return self.objects_dir / sha

    def _write_atomic(self, target: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".restore-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -- operations -------------------------------------------------------------
    def list_files(self) -> list[dict[str, Any]]:
        out = []
        for rel in VAULT_FILES:
            data = self._read(rel)
            sha = sha256_bytes(data)
            snaps = self.db.query("SELECT snapshot_id, version, sha256 FROM snapshots WHERE file_path = ? ORDER BY version",
                                  (rel,))
            out.append({"path": rel, "sha256": sha, "size_bytes": len(data), "snapshot_count": len(snaps),
                        "matches_original": sha == sha256_bytes(VAULT_FILES[rel].encode("utf-8")),
                        "matching_snapshot_ids": [s["snapshot_id"] for s in snaps if s["sha256"] == sha]})
        return out

    def snapshot(self, path: str, reason: str) -> dict[str, Any]:
        data = self._read(path)
        sha = sha256_bytes(data)
        obj = self._object(sha)
        if not obj.exists():
            self._write_atomic(obj, data)
        snapshot_id = new_id("snp")
        with self.db.transaction() as conn:
            version = (conn.execute("SELECT MAX(version) FROM snapshots WHERE file_path = ?", (path,)).fetchone()[0] or 0) + 1
            conn.execute("INSERT INTO snapshots (snapshot_id, file_path, version, sha256, size_bytes, reason, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (snapshot_id, path, version, sha, len(data), reason, utc_now()))
            self.recorder.record(event_type="snapshot_created", actor="recovery-vault", action="snapshot",
                                 resource_id=f"vault:{path}", outcome="success", severity="info",
                                 summary=f"Snapshot v{version} of {path} created ({reason}).",
                                 evidence={"snapshot_id": snapshot_id, "sha256": sha, "size_bytes": len(data)})
        return self.get(snapshot_id)

    def get(self, snapshot_id: str, include_content: bool = False) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        if not row:
            raise NotFoundError(f"snapshot {snapshot_id} not found")
        if include_content:
            stored = self._object(row["sha256"]).read_bytes()
            current = self._read(row["file_path"])
            row["content"] = stored.decode("utf-8", errors="replace")
            row["store_integrity_ok"] = sha256_bytes(stored) == row["sha256"]
            row["current_sha256"] = sha256_bytes(current)
            row["diff_to_current"] = "".join(difflib.unified_diff(
                current.decode("utf-8", errors="replace").splitlines(keepends=True),
                row["content"].splitlines(keepends=True), fromfile="current", tofile=f"snapshot v{row['version']}"))
        return row

    def list(self, path: str | None = None) -> list[dict[str, Any]]:
        if path:
            self._resolve(path)
            return self.db.query("SELECT * FROM snapshots WHERE file_path = ? ORDER BY version DESC", (path,))
        return self.db.query("SELECT * FROM snapshots ORDER BY created_at DESC")

    def simulate_change(self, path: str) -> dict[str, Any]:
        """Snapshot the file, then apply a deterministic simulated unauthorized edit."""
        before = self.snapshot(path, "automatic pre-modification snapshot")
        old, new = SIMULATED_EDITS[path]
        data = self._read(path).decode("utf-8")
        if old not in data:
            raise ValidationFailure("the file has already been modified; restore it before simulating again")
        modified = data.replace(old, new, 1).encode("utf-8")
        self._write_atomic(self._resolve(path), modified)
        self.recorder.record(event_type="file_modified", actor="demo-agent", action="write_file",
                             resource_id=f"vault:{path}", outcome="modified", severity="medium",
                             summary=f"SIMULATED unauthorized edit applied to {path}.",
                             evidence={"before_sha256": before["sha256"], "after_sha256": sha256_bytes(modified),
                                       "pre_change_snapshot_id": before["snapshot_id"], "simulated": True})
        return {"path": path, "snapshot": before, "modified_sha256": sha256_bytes(modified)}

    def restore(self, snapshot_id: str) -> dict[str, Any]:
        snap = self.get(snapshot_id)
        stored = self._object(snap["sha256"]).read_bytes()
        if sha256_bytes(stored) != snap["sha256"]:
            raise ValidationFailure("snapshot object failed its integrity check; refusing to restore")
        current = self._read(snap["file_path"])
        before_sha = sha256_bytes(current)
        backup = self.snapshot(snap["file_path"], f"automatic pre-restore backup (before restoring v{snap['version']})")
        self._write_atomic(self._resolve(snap["file_path"]), stored)
        restored_sha = sha256_bytes(self._read(snap["file_path"]))
        verified = restored_sha == snap["sha256"]
        self.recorder.record(event_type="file_restored", actor="operator", action="restore_snapshot",
                             resource_id=f"vault:{snap['file_path']}", outcome="verified" if verified else "hash_mismatch",
                             severity="info" if verified else "high",
                             summary=(f"Restored {snap['file_path']} to snapshot v{snap['version']}; hash "
                                      f"{'matches' if verified else 'DOES NOT match'}."),
                             evidence={"snapshot_id": snapshot_id, "expected_sha256": snap["sha256"],
                                       "before_sha256": before_sha, "restored_sha256": restored_sha,
                                       "pre_restore_backup_id": backup["snapshot_id"]})
        return {"snapshot": snap, "path": snap["file_path"], "before_sha256": before_sha,
                "expected_sha256": snap["sha256"], "restored_sha256": restored_sha, "verified": verified,
                "pre_restore_backup": backup,
                "note": "Restoring a file does not reverse external side effects such as network requests."}
