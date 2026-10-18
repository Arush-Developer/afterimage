"""SQLite persistence layer.

A single connection guarded by a re-entrant lock keeps things simple and safe for a
local prototype (FastAPI runs sync endpoints in a thread pool). The `events` table is
append-only: database triggers reject UPDATE and DELETE statements on it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    scenario          TEXT NOT NULL,
    kind              TEXT NOT NULL,              -- 'scenario' | 'replay'
    status            TEXT NOT NULL,              -- 'running' | 'completed' | 'failed'
    policy_version    INTEGER NOT NULL,
    workspace_path    TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    task_completed    INTEGER,
    sensitive_exposed INTEGER,
    output_summary    TEXT,
    result_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);

CREATE TABLE IF NOT EXISTS events (
    seq                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id           TEXT NOT NULL UNIQUE,
    run_id             TEXT REFERENCES runs(run_id),
    incident_id        TEXT,
    timestamp          TEXT NOT NULL,
    event_type         TEXT NOT NULL,
    actor              TEXT NOT NULL,
    action             TEXT NOT NULL,
    resource_id        TEXT,
    source_event_id    TEXT,
    policy_decision_id TEXT,
    outcome            TEXT NOT NULL,
    severity           TEXT NOT NULL,
    summary            TEXT NOT NULL,
    evidence_metadata  TEXT NOT NULL,
    prev_hash          TEXT NOT NULL,
    event_hash         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_incident ON events(incident_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_resource ON events(resource_id);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_event_id);

CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS policy_decisions (
    decision_id     TEXT PRIMARY KEY,
    run_id          TEXT REFERENCES runs(run_id),
    agent_id        TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    action          TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    allowed         INTEGER NOT NULL,
    decision        TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    matched_rules   TEXT NOT NULL,
    policy_version  INTEGER NOT NULL,
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_run ON policy_decisions(run_id);

CREATE TABLE IF NOT EXISTS policies (
    version         INTEGER PRIMARY KEY,
    document        TEXT NOT NULL,
    change_summary  TEXT NOT NULL,
    applied_changes TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    created_at      TEXT NOT NULL,
    incident_type   TEXT NOT NULL,
    title           TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    status          TEXT NOT NULL,
    resource_id     TEXT,
    rule_id         TEXT,
    trigger_resource TEXT,
    first_event_at  TEXT NOT NULL,
    last_event_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_run ON incidents(run_id);

CREATE TABLE IF NOT EXISTS incident_events (
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    event_id    TEXT NOT NULL REFERENCES events(event_id),
    role        TEXT NOT NULL,
    PRIMARY KEY (incident_id, event_id)
);

CREATE TABLE IF NOT EXISTS replays (
    replay_id               TEXT PRIMARY KEY,
    baseline_run_id         TEXT NOT NULL REFERENCES runs(run_id),
    replay_run_id           TEXT NOT NULL REFERENCES runs(run_id),
    scenario                TEXT NOT NULL,
    baseline_policy_version INTEGER NOT NULL,
    replay_policy_version   INTEGER NOT NULL,
    status                  TEXT NOT NULL,
    verified                INTEGER NOT NULL,
    report_json             TEXT NOT NULL,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    file_path   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (file_path, version)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idem_key      TEXT PRIMARY KEY,
    endpoint      TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id   TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    provider_real   INTEGER NOT NULL,
    task            TEXT NOT NULL,
    trials          INTEGER NOT NULL,
    status          TEXT NOT NULL,
    report_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self.lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after the first release, for existing databases."""
        extra_run_columns = {
            "agent_kind": "TEXT NOT NULL DEFAULT 'scripted'",
            "enforcement": "TEXT NOT NULL DEFAULT 'protected'",
            "provider": "TEXT",
            "model": "TEXT",
            "agent_steps": "INTEGER",
            "provider_error": "TEXT",
            "transcript_json": "TEXT",
            "experiment_id": "TEXT",
        }
        have = {r[1] for r in self._conn.execute("PRAGMA table_info(runs)")}
        for name, decl in extra_run_columns.items():
            if name not in have:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {decl}")
        self._conn.executescript(SCHEMA_V2)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run several statements atomically. Nested calls join the outer transaction."""
        with self.lock:
            if self._conn.in_transaction:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        with self.transaction() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self.lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self.lock:
            row = self._conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def close(self) -> None:
        with self.lock:
            self._conn.close()


def dumps(value: Any) -> str:
    """Canonical JSON used for storage and hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(value: str | None) -> Any:
    return json.loads(value) if value else None
