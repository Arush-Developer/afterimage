"""Versioned policy storage. Every change creates a new version; nothing is overwritten,
so any change can be reverted by re-applying an earlier version as a new one."""

from __future__ import annotations

import posixpath
from typing import Any

from .common import ConflictError, NotFoundError, ValidationFailure, utc_now
from .db import Database, dumps, loads
from .policy import (BASELINE_POLICY, BUILTIN_RULES, CHANGE_CATALOG, PolicyDocument, PolicyEngine,
                     apply_changes, diff_documents)
from .recorder import EventRecorder

# Representative requests from the demo scenarios, used to show the impact of a policy.
IMPACT_PROBES: list[dict[str, str]] = [
    {"tool": "list_files", "path": ".", "purpose": "legitimate", "label": "List project files"},
    {"tool": "read_file", "path": "README.md", "purpose": "legitimate", "label": "Read README"},
    {"tool": "read_file", "path": "src/inventory.py", "purpose": "legitimate", "label": "Read source module"},
    {"tool": "read_file", "path": "docs/integration_notes.md", "purpose": "legitimate", "label": "Read project docs"},
    {"tool": "write_file", "path": "out/summary.md", "purpose": "legitimate", "label": "Save the summary"},
    {"tool": "read_file", "path": "secret.txt", "purpose": "attack", "label": "Injected: read secret.txt"},
    {"tool": "read_file", "path": "../host-credentials.txt", "purpose": "attack", "label": "Injected: path traversal"},
]


def _probe_decision(engine: PolicyEngine, probe: dict[str, str]) -> dict[str, Any]:
    normalized = posixpath.normpath(probe["path"])
    violation = "path traversal outside the workspace" if normalized.startswith("..") else None
    resource = normalized if violation is None else "external:" + probe["path"]
    d = engine.evaluate(agent_id="demo-agent", task_id="project-summary", action=probe["tool"],
                        resource_id=resource, boundary_violation=violation)
    return {**probe, "resource_id": resource, "allowed": d.allowed, "decision": d.decision, "rule_id": d.rule_id}


def evaluate_impact(old: PolicyEngine, new: PolicyEngine) -> dict[str, Any]:
    rows = []
    for probe in IMPACT_PROBES:
        before, after = _probe_decision(old, probe), _probe_decision(new, probe)
        rows.append({**probe, "before": {k: before[k] for k in ("allowed", "decision", "rule_id")},
                     "after": {k: after[k] for k in ("allowed", "decision", "rule_id")},
                     "changed": before["allowed"] != after["allowed"] or before["rule_id"] != after["rule_id"]})
    broken = [r for r in rows if r["purpose"] == "legitimate" and r["before"]["allowed"] and not r["after"]["allowed"]]
    opened = [r for r in rows if r["purpose"] == "attack" and not r["before"]["allowed"] and r["after"]["allowed"]]
    warnings = [f"Legitimate operation would be denied: {r['label']} ({r['tool']} {r['path']})" for r in broken]
    warnings += [f"Attack operation would become allowed: {r['label']}" for r in opened]
    return {"probes": rows, "legitimate_operations_broken": len(broken), "attack_operations_opened": len(opened),
            "warnings": warnings}


class PolicyStore:
    def __init__(self, db: Database, recorder: EventRecorder):
        self.db = db
        self.recorder = recorder

    def ensure_baseline(self) -> None:
        with self.db.transaction() as conn:
            if conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0] == 0:
                conn.execute("INSERT INTO policies (version, document, change_summary, applied_changes, created_at) "
                             "VALUES (1, ?, ?, ?, ?)",
                             (dumps(BASELINE_POLICY.model_dump()), "Baseline demo policy", dumps([]), utc_now()))

    def _row(self, version: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM policies WHERE version = ?", (version,))
        if not row:
            raise NotFoundError(f"policy version {version} not found")
        return row

    def active_version(self) -> int:
        return int(self.db.scalar("SELECT MAX(version) FROM policies"))

    def get(self, version: int) -> PolicyDocument:
        return PolicyDocument.model_validate(loads(self._row(version)["document"]))

    def active_engine(self) -> PolicyEngine:
        version = self.active_version()
        return PolicyEngine(self.get(version), version)

    def describe(self, version: int | None = None) -> dict[str, Any]:
        version = version or self.active_version()
        row = self._row(version)
        engine = PolicyEngine(PolicyDocument.model_validate(loads(row["document"])), version)
        probes = [_probe_decision(engine, p) for p in IMPACT_PROBES]
        rule_impact: dict[str, list[str]] = {}
        for p in probes:
            rule_impact.setdefault(p["rule_id"], []).append(f"{'allows' if p['allowed'] else 'denies'} {p['label']}")
        return {
            "version": version,
            "is_active": version == self.active_version(),
            "created_at": row["created_at"],
            "change_summary": row["change_summary"],
            "applied_changes": loads(row["applied_changes"]),
            "document": loads(row["document"]),
            "builtin_rules": BUILTIN_RULES,
            "rule_impact": rule_impact,
            "probe_decisions": probes,
        }

    def history(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT version, change_summary, applied_changes, created_at FROM policies ORDER BY version DESC")
        return [{**r, "applied_changes": loads(r["applied_changes"])} for r in rows]

    def catalog(self) -> list[dict[str, Any]]:
        current = self.get(self.active_version())
        out = []
        for change in CHANGE_CATALOG.values():
            already = apply_changes(current, [change.change_id]).model_dump() == current.model_dump()
            out.append({**change.model_dump(), "already_applied": already})
        return out

    def preview(self, change_ids: list[str]) -> dict[str, Any]:
        if not change_ids:
            raise ValidationFailure("select at least one policy change")
        version = self.active_version()
        current = self.get(version)
        proposed = apply_changes(current, change_ids)
        return {
            "base_version": version,
            "change_ids": change_ids,
            "changes": [CHANGE_CATALOG[c].model_dump() for c in change_ids],
            "current_document": current.model_dump(),
            "proposed_document": proposed.model_dump(),
            "diff": diff_documents(current, proposed),
            "no_op": proposed.model_dump() == current.model_dump(),
            "impact": evaluate_impact(PolicyEngine(current, version), PolicyEngine(proposed, version + 1)),
        }

    def _create_version(self, base_version: int, document: PolicyDocument, summary: str,
                        applied: list[str], event_summary: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            active = conn.execute("SELECT MAX(version) FROM policies").fetchone()[0]
            if active != base_version:
                raise ConflictError(f"policy changed since preview (active version is {active}, "
                                    f"request was based on {base_version}); refresh and try again")
            current = PolicyDocument.model_validate(loads(conn.execute(
                "SELECT document FROM policies WHERE version = ?", (active,)).fetchone()[0]))
            if current.model_dump() == document.model_dump():
                raise ConflictError("this change is already in effect; nothing to apply")
            new_version = active + 1
            conn.execute("INSERT INTO policies (version, document, change_summary, applied_changes, created_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (new_version, dumps(document.model_dump()), summary, dumps(applied), utc_now()))
            self.recorder.record(
                event_type="policy_changed", actor="operator", action="apply_policy",
                resource_id=f"policy:v{new_version}", outcome="applied", severity="info",
                summary=event_summary,
                evidence={"from_version": active, "to_version": new_version, "changes": applied,
                          "diff": diff_documents(current, document)},
            )
        return self.describe(new_version)

    def apply(self, change_ids: list[str], base_version: int) -> dict[str, Any]:
        if not change_ids:
            raise ValidationFailure("select at least one policy change")
        proposed = apply_changes(self.get(base_version), change_ids)
        titles = ", ".join(CHANGE_CATALOG[c].title for c in change_ids)
        return self._create_version(base_version, proposed, f"Applied: {titles}", change_ids,
                                    f"Policy v{base_version + 1} applied: {titles}.")

    def revert(self, target_version: int, base_version: int) -> dict[str, Any]:
        document = self.get(target_version)
        return self._create_version(base_version, document, f"Reverted to the rules of v{target_version}",
                                    [f"revert:v{target_version}"],
                                    f"Policy v{base_version + 1} restores the rules of v{target_version}.")

    def reset_to_baseline(self) -> dict[str, Any] | None:
        version = self.active_version()
        if self.get(version).model_dump() == BASELINE_POLICY.model_dump():
            return None
        return self._create_version(version, BASELINE_POLICY, "Reset to baseline demo policy", ["reset:baseline"],
                                    f"Policy v{version + 1} resets rules to the baseline demo policy.")
