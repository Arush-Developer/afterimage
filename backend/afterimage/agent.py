r"""A deterministic, controlled demo agent.

This is NOT an LLM. It is a small scripted agent whose behaviour is fully predictable so
the security demo is repeatable:

* mode "benign": treats file content as data. If it sees instruction-like text it
  records that it ignored it and carries on.
* mode "attack": deliberately configured to be "susceptible". When a document contains
  `read ... \`<path>\`` instructions it attempts to read those paths (through the
  gateway) and would copy whatever it receives into its summary. This simulates an
  agent that obeys an indirect prompt injection.

The agent has no filesystem, network, shell or code-execution access of its own. Its
only capabilities are the three gateway tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .gateway import INSTRUCTION_PATTERNS, ToolGateway
from .workspace import REQUIRED_TASK_READS, SUMMARY_OUTPUT_PATH

AgentMode = Literal["benign", "attack"]

_READ_INSTRUCTION = re.compile(r"\bread (?:the file )?`([^`]{1,256})`", re.IGNORECASE)


@dataclass
class AgentResult:
    task_completed: bool
    summary: str | None
    files_read: list[str] = field(default_factory=list)
    failed_required_reads: list[str] = field(default_factory=list)
    followed_instructions: list[str] = field(default_factory=list)
    output_written: bool = False
    notes: list[str] = field(default_factory=list)


class DemoAgent:
    def __init__(self, gateway: ToolGateway, mode: AgentMode):
        self.gw = gateway
        self.mode = mode

    def _note(self, summary: str, source_event_id: str | None, evidence: dict) -> dict:
        return self.gw._record(event_type="agent_note", actor=self.gw.agent_id, action="reasoning_step_reported",
                               summary=summary, source_event_id=source_event_id, outcome="info",
                               severity="info", evidence=evidence)

    def run_summary_task(self, task_event_id: str | None = None) -> AgentResult:
        """Run the summary task. Planned calls report the task event as their provenance."""
        result = AgentResult(task_completed=False, summary=None)
        task = {"source_event_id": task_event_id, "provenance": "task instruction"}
        listing = self.gw.list_files(".", **task)
        all_files = listing.files or []
        plan = [f for f in all_files if f == "README.md" or (f.startswith("src/") and f.endswith(".py"))
                or (f.startswith("docs/") and f.endswith(".md"))]
        if not listing.allowed:
            # Fall back to the files the task brief names explicitly.
            plan = list(REQUIRED_TASK_READS)

        contents: dict[str, str] = {}
        injected: list[str] = []
        for path in plan:
            outcome = self.gw.read_file(path, **task)
            if not outcome.allowed or outcome.content is None:
                continue
            contents[path] = outcome.content
            result.files_read.append(path)
            if not any(p.search(outcome.content) for p in INSTRUCTION_PATTERNS):
                continue
            targets = _READ_INSTRUCTION.findall(outcome.content)
            if self.mode == "benign":
                self._note(f"Ignored instruction-like text found in '{path}' (treated as data, not instructions).",
                           outcome.result_event_id, {"document": path, "instructions_found": len(targets),
                                                     "action_taken": "none"})
                continue
            # Attack mode: deliberately follow the embedded instructions.
            for target in targets:
                result.followed_instructions.append(target)
                attempt = self.gw.read_file(
                    target, source_event_id=outcome.result_event_id,
                    provenance=f"instruction found in {path}",
                )
                if attempt.allowed and attempt.content is not None:
                    injected.append(attempt.content)

        result.failed_required_reads = [p for p in REQUIRED_TASK_READS if p not in contents]
        summary = self._compose_summary(contents, injected)
        write = self.gw.write_file(SUMMARY_OUTPUT_PATH, summary, **task)
        result.output_written = write.allowed and write.error is None
        result.summary = summary
        result.task_completed = result.output_written and not result.failed_required_reads
        return result

    @staticmethod
    def _compose_summary(contents: dict[str, str], injected: list[str]) -> str:
        readme = contents.get("README.md", "")
        title = next((line.lstrip("# ").strip() for line in readme.splitlines() if line.startswith("# ")), "Unknown project")
        description = next((line.strip() for line in readme.splitlines()[1:] if line.strip()), "No README available.")
        lines = [f"# Summary: {title}", "", description, "", "## Source modules"]
        modules = sorted(p for p in contents if p.startswith("src/"))
        for module in modules:
            functions = re.findall(r"^def (\w+)\(", contents[module], re.MULTILINE)
            lines.append(f"- `{module}`: {', '.join(functions) or 'no functions'}")
        if not modules:
            lines.append("- (no source files could be read)")
        docs = sorted(p for p in contents if p.startswith("docs/"))
        lines += ["", "## Documentation", *[f"- `{d}`" for d in docs]] if docs else []
        if injected:  # Only reachable if a policy allowed a protected read.
            lines += ["", "## Additional content requested by a document", *injected]
        return "\n".join(lines) + "\n"
