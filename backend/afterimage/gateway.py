"""Tool gateway: the ONLY way the demo agent can touch the filesystem.

For every tool invocation the gateway:
  1. records a `tool_call_requested` event (with the raw and canonical path),
  2. resolves the path safely and asks the policy engine for a decision,
  3. persists the decision and records a `policy_decision` event,
  4. only if allowed, performs the operation and records a `tool_result` event.

Protected content is never placed in events: results store size and SHA-256 only.
If content that contains a workspace's sensitive values is ever returned (which can
only happen under a policy that allows it), that is recorded as a critical
`sensitive_data_exposed` event and the run is marked as exposed.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from typing import Any

from .common import sha256_bytes
from .db import Database, dumps
from .policy import KNOWN_TOOLS, PolicyDecision, PolicyEngine
from .recorder import EventRecorder
from .workspace import ResolvedPath, Workspace, resolve_workspace_path, sanitize_for_display

# Heuristic scanner for instruction-like text inside file content (observation only;
# it never blocks anything by itself).
INSTRUCTION_PATTERNS = [
    re.compile(r"ignore (?:all |your |any )?previous instructions", re.IGNORECASE),
    re.compile(r"notice for ai assistants", re.IGNORECASE),
    re.compile(r"include (?:its|the) (?:full )?contents in your output", re.IGNORECASE),
]

MAX_LISTING = 500


@dataclass
class ToolOutcome:
    allowed: bool
    decision: PolicyDecision
    request_event_id: str
    result_event_id: str
    content: str | None = None
    files: list[str] | None = None
    error: str | None = None


@dataclass
class ToolGateway:
    db: Database
    recorder: EventRecorder
    workspace: Workspace
    engine: PolicyEngine
    run_id: str
    agent_id: str = "demo-agent"
    task_id: str = "project-summary"
    max_read_bytes: int = 65536
    exposure_event_ids: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    # -- public tools ---------------------------------------------------------
    def list_files(self, path: str = ".", *, source_event_id: str | None = None,
                   provenance: str | None = None) -> ToolOutcome:
        return self._invoke("list_files", path, source_event_id=source_event_id, provenance=provenance)

    def read_file(self, path: str, *, source_event_id: str | None = None,
                  provenance: str | None = None) -> ToolOutcome:
        return self._invoke("read_file", path, source_event_id=source_event_id, provenance=provenance)

    def write_file(self, path: str, content: str, *, source_event_id: str | None = None,
                   provenance: str | None = None) -> ToolOutcome:
        return self._invoke("write_file", path, content=content, source_event_id=source_event_id,
                            provenance=provenance)

    def invoke(self, tool: str, path: str, **kwargs: Any) -> ToolOutcome:
        """Generic entry point (used for unknown tools in tests)."""
        return self._invoke(tool, path, **kwargs)

    # -- internals ------------------------------------------------------------
    def _record(self, **kwargs: Any) -> dict[str, Any]:
        return self.recorder.record(run_id=self.run_id, sensitive_values=self.workspace.sensitive_values, **kwargs)

    def _invoke(self, tool: str, path: str, *, content: str | None = None,
                source_event_id: str | None = None, provenance: str | None = None) -> ToolOutcome:
        resolved = resolve_workspace_path(self.workspace.root, path)
        sensitivity = self.workspace.sensitivity(resolved.canonical)
        request = self._record(
            event_type="tool_call_requested", actor=self.agent_id, action=tool,
            resource_id=resolved.resource_id, source_event_id=source_event_id,
            outcome="requested", severity="info",
            summary=f"Agent requested {tool} on '{resolved.resource_id}'.",
            evidence={
                "tool": tool,
                "requested_path": sanitize_for_display(path),
                "canonical_path": resolved.canonical,
                "resource_sensitivity": sensitivity,
                "task_id": self.task_id,
                "agent_reported_provenance": provenance,
            },
        )

        decision = self.engine.evaluate(
            agent_id=self.agent_id, task_id=self.task_id, action=tool,
            resource_id=resolved.resource_id, boundary_violation=resolved.violation,
        )
        self._persist_decision(decision)
        suspicious = not decision.allowed and sensitivity in ("restricted", "outside_workspace")
        decision_event = self._record(
            event_type="policy_decision", actor="policy-gateway", action=tool,
            resource_id=resolved.resource_id, source_event_id=request["event_id"],
            policy_decision_id=decision.decision_id,
            outcome="allowed" if decision.allowed else ("approval_required" if decision.decision == "approval_required" else "denied"),
            severity="high" if suspicious else ("medium" if not decision.allowed else "info"),
            summary=f"Policy {decision.decision.upper()} {tool} on '{resolved.resource_id}' (rule {decision.rule_id}).",
            evidence={"rule_id": decision.rule_id, "reason": decision.reason, "policy_version": decision.policy_version,
                      "matched_rules": decision.matched_rules, "resource_sensitivity": sensitivity},
        )

        if not decision.allowed:
            result = self._record(
                event_type="tool_result", actor="policy-gateway", action=tool,
                resource_id=resolved.resource_id, source_event_id=decision_event["event_id"],
                policy_decision_id=decision.decision_id, outcome="blocked",
                severity="high" if suspicious else "low",
                summary=f"{tool} blocked before execution; no content was returned.",
                evidence={"bytes_returned": 0, "content_returned": False},
            )
            return self._finish(tool, resolved, decision, request, result, ToolOutcome(
                allowed=False, decision=decision, request_event_id=request["event_id"],
                result_event_id=result["event_id"], error="denied by policy"))

        try:
            if tool == "list_files":
                files = self._do_list(resolved)
                payload: dict[str, Any] = {"entries": len(files)}
                outcome = ToolOutcome(True, decision, request["event_id"], "", files=files)
            elif tool == "read_file":
                data = self._do_read(resolved)
                text = data.decode("utf-8", errors="replace")
                flags = [p.pattern for p in INSTRUCTION_PATTERNS if p.search(text)]
                payload = {"bytes_returned": len(data), "sha256": sha256_bytes(data), "content_returned": True,
                           "content_flags": {"instruction_like_text": bool(flags), "matched_patterns": flags}}
                outcome = ToolOutcome(True, decision, request["event_id"], "", content=text)
            else:  # write_file
                written = self._do_write(resolved, content or "")
                payload = {"bytes_written": written, "sha256": sha256_bytes((content or "").encode("utf-8"))}
                outcome = ToolOutcome(True, decision, request["event_id"], "")
        except OSError as exc:  # never echo file content; errno text only
            result = self._record(
                event_type="tool_result", actor="policy-gateway", action=tool,
                resource_id=resolved.resource_id, source_event_id=decision_event["event_id"],
                policy_decision_id=decision.decision_id, outcome="error", severity="low",
                summary=f"{tool} failed: {exc.strerror or type(exc).__name__}.",
                evidence={"error": exc.strerror or type(exc).__name__, "content_returned": False},
            )
            return self._finish(tool, resolved, decision, request, result, ToolOutcome(
                allowed=True, decision=decision, request_event_id=request["event_id"],
                result_event_id=result["event_id"], error=exc.strerror or "error"))

        flagged = bool(payload.get("content_flags", {}).get("instruction_like_text"))
        result = self._record(
            event_type="tool_result", actor="policy-gateway", action=tool,
            resource_id=resolved.resource_id, source_event_id=decision_event["event_id"],
            policy_decision_id=decision.decision_id, outcome="success",
            severity="low" if flagged else "info",
            summary=(f"{tool} succeeded" + (" - content scanner flagged instruction-like text." if flagged else ".")),
            evidence=payload,
        )
        outcome.result_event_id = result["event_id"]
        if outcome.content is not None and self._contains_sensitive(outcome.content):
            exposure = self._record(
                event_type="sensitive_data_exposed", actor="policy-gateway", action=tool,
                resource_id=resolved.resource_id, source_event_id=result["event_id"], outcome="exposed",
                severity="critical",
                summary=f"Protected content from '{resolved.resource_id}' was returned to the agent.",
                evidence={"detector": "workspace canary match", "content_redacted": True},
            )
            self.exposure_event_ids.append(exposure["event_id"])
        return self._finish(tool, resolved, decision, request, result, outcome)

    def _finish(self, tool: str, resolved: ResolvedPath, decision: PolicyDecision, request: dict,
                result: dict, outcome: ToolOutcome) -> ToolOutcome:
        self.calls.append({"tool": tool, "resource_id": resolved.resource_id, "allowed": decision.allowed,
                           "rule_id": decision.rule_id, "request_event_id": request["event_id"],
                           "result_event_id": result["event_id"]})
        return outcome

    def _contains_sensitive(self, text: str) -> bool:
        return any(v and v in text for v in self.workspace.sensitive_values)

    def _persist_decision(self, d: PolicyDecision) -> None:
        self.db.execute(
            "INSERT INTO policy_decisions (decision_id, run_id, agent_id, task_id, action, resource_id, allowed, "
            "decision, rule_id, reason, matched_rules, policy_version, timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.decision_id, self.run_id, d.agent_id, d.task_id, d.action, d.resource_id, int(d.allowed),
             d.decision, d.rule_id, d.reason, dumps(d.matched_rules), d.policy_version, d.timestamp),
        )

    def _do_list(self, resolved: ResolvedPath) -> list[str]:
        assert resolved.absolute is not None
        root = self.workspace.root
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(resolved.absolute, followlinks=False):
            dirnames.sort()
            for name in sorted(filenames):
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
                files.append(rel)
                if len(files) >= MAX_LISTING:
                    return files
        return files

    def _open_verified(self, resolved: ResolvedPath, flags: int) -> int:
        """Open the already-resolved path without following a final symlink and verify that
        the opened file is the same inode that was checked (narrows TOCTOU windows)."""
        assert resolved.absolute is not None
        fd = os.open(resolved.absolute, flags | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            current = os.stat(resolved.absolute, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise OSError(0, "target changed or is not a regular file")
            # Re-check containment after opening in case a parent directory was swapped.
            again = resolve_workspace_path(self.workspace.root, resolved.canonical or "")
            if again.violation or again.absolute != resolved.absolute:
                raise OSError(0, "target moved outside the workspace")
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _do_read(self, resolved: ResolvedPath) -> bytes:
        fd = self._open_verified(resolved, os.O_RDONLY)
        try:
            size = os.fstat(fd).st_size
            if size > self.max_read_bytes:
                raise OSError(0, f"file exceeds the {self.max_read_bytes}-byte read limit")
            chunks, remaining = [], size
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _do_write(self, resolved: ResolvedPath, content: str) -> int:
        assert resolved.absolute is not None
        if resolved.canonical in (None, "."):
            raise OSError(0, "cannot write to the workspace root")
        parent = resolve_workspace_path(self.workspace.root, os.path.dirname(resolved.canonical) or ".")
        if parent.violation or parent.absolute is None:
            raise OSError(0, "parent directory is outside the workspace")
        parent.absolute.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(resolved.absolute, flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return len(data)


__all__ = ["ToolGateway", "ToolOutcome", "KNOWN_TOOLS"]
