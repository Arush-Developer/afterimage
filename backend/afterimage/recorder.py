"""Event recorder: append-only, hash-chained structured events.

Every event stores `prev_hash` (the hash of the previous event) and `event_hash`
(SHA-256 over its own canonical fields plus `prev_hash`). `verify_chain()` recomputes
the chain and reports the first mismatch.

Limitation (documented in docs/SECURITY.md): this is tamper-EVIDENT against casual edits
of individual rows, not tamper-PROOF. Anyone with write access to the SQLite file can
rewrite the entire chain consistently. There is no external anchor or signature.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from .common import new_id, utc_now
from .db import Database, dumps, loads

GENESIS_HASH = "0" * 64
REDACTED = "[REDACTED:protected-content]"

HASHED_FIELDS = (
    "event_id", "run_id", "incident_id", "timestamp", "event_type", "actor", "action",
    "resource_id", "source_event_id", "policy_decision_id", "outcome", "severity",
    "summary", "evidence_metadata", "prev_hash",
)

SEVERITIES = ("info", "low", "medium", "high", "critical")


def _redact(value: Any, sensitive: tuple[str, ...]) -> Any:
    if not sensitive:
        return value
    if isinstance(value, str):
        for secret in sensitive:
            if secret and secret in value:
                value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {k: _redact(v, sensitive) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, sensitive) for v in value]
    return value


def compute_event_hash(row: dict[str, Any]) -> str:
    material = dumps({field: row.get(field) for field in HASHED_FIELDS})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class EventRecorder:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        event_type: str,
        actor: str,
        action: str,
        summary: str,
        run_id: str | None = None,
        incident_id: str | None = None,
        resource_id: str | None = None,
        source_event_id: str | None = None,
        policy_decision_id: str | None = None,
        outcome: str = "info",
        severity: str = "info",
        evidence: dict[str, Any] | None = None,
        sensitive_values: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Append one event. Any `sensitive_values` are scrubbed before persistence."""
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity {severity!r}")
        sensitive = tuple(v for v in sensitive_values if v)
        with self.db.transaction() as conn:
            prev = conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            row: dict[str, Any] = {
                "event_id": new_id("evt"),
                "run_id": run_id,
                "incident_id": incident_id,
                "timestamp": utc_now(),
                "event_type": event_type,
                "actor": actor,
                "action": action,
                "resource_id": _redact(resource_id, sensitive),
                "source_event_id": source_event_id,
                "policy_decision_id": policy_decision_id,
                "outcome": outcome,
                "severity": severity,
                "summary": _redact(summary, sensitive),
                "evidence_metadata": dumps(_redact(evidence or {}, sensitive)),
                "prev_hash": prev[0] if prev else GENESIS_HASH,
            }
            row["event_hash"] = compute_event_hash(row)
            columns = ", ".join(row)
            placeholders = ", ".join(f":{k}" for k in row)
            conn.execute(f"INSERT INTO events ({columns}) VALUES ({placeholders})", row)
        return deserialize_event(row)

    def verify_chain(self) -> dict[str, Any]:
        rows = self.db.query("SELECT * FROM events ORDER BY seq ASC")
        expected_prev = GENESIS_HASH
        for row in rows:
            if row["prev_hash"] != expected_prev:
                return {"valid": False, "checked": len(rows), "first_invalid_event_id": row["event_id"],
                        "reason": "prev_hash does not match the preceding event"}
            if compute_event_hash(row) != row["event_hash"]:
                return {"valid": False, "checked": len(rows), "first_invalid_event_id": row["event_id"],
                        "reason": "event content does not match its stored hash"}
            expected_prev = row["event_hash"]
        return {"valid": True, "checked": len(rows), "first_invalid_event_id": None, "reason": None}


def deserialize_event(row: dict[str, Any]) -> dict[str, Any]:
    event = dict(row)
    event.pop("seq", None)
    if isinstance(event.get("evidence_metadata"), str):
        event["evidence_metadata"] = loads(event["evidence_metadata"]) or {}
    return event
