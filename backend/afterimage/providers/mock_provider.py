"""Deterministic mock provider for tests and the no-credentials demo.

Two uses:
  * `ScriptedProvider` replays a fixed list of responses — used in unit tests to exercise
    the agent loop without any network call.
  * `SimulatedInjectionProvider` is a tiny rule-based "model" that reads files and, if it
    sees instruction-like text telling it to read another file, tries to follow it. This
    gives the UI a usable LLM-style experience with no API key, clearly labelled as
    simulated (is_real = False), while still routing every call through the real gateway.
"""

from __future__ import annotations

import re
from typing import Callable

from ..gateway import INSTRUCTION_PATTERNS
from .base import LLMProvider, LLMResponse, ProviderError, ToolCall, ToolSpec, TokenUsage, Turn

_READ_INSTRUCTION = re.compile(r"\b(?:read|open|cat)\s+(?:the file\s+)?[`'\"]?([\w./-]{1,256}\.[\w]{1,8})[`'\"]?",
                               re.IGNORECASE)
_SUMMARY_PATH = "out/summary.md"


class ScriptedProvider(LLMProvider):
    """Replays a fixed sequence of LLMResponse objects (or a callable per step)."""

    name = "mock"
    is_real = False

    def __init__(self, responses: list[LLMResponse] | Callable[[int, list[Turn]], LLMResponse], model: str = "mock-1"):
        super().__init__(model)
        self._responses = responses
        self._step = 0
        self.calls: list[list[Turn]] = []

    def complete(self, *, system, turns, tools, max_tokens, timeout) -> LLMResponse:
        self.calls.append(list(turns))
        if callable(self._responses):
            resp = self._responses(self._step, turns)
        else:
            if self._step >= len(self._responses):
                raise ProviderError("scripted provider ran out of responses", kind="exhausted")
            resp = self._responses[self._step]
        self._step += 1
        return resp


class SimulatedInjectionProvider(LLMProvider):
    """A no-network stand-in that behaves like a tool-using model.

    `susceptible=True` follows instructions embedded in file content (the injection);
    `susceptible=False` ignores them. It always lists, reads the task files, optionally
    follows injected read instructions, then writes a summary and finishes.
    """

    name = "simulated"
    is_real = False

    def __init__(self, model: str = "simulated-agent", *, susceptible: bool = True):
        super().__init__(model)
        self.susceptible = susceptible

    def complete(self, *, system, turns, tools, max_tokens, timeout) -> LLMResponse:
        seen_files: dict[str, str] = {}
        listed: list[str] = []
        pending_injection: list[str] = []
        wrote = False
        read_requests: list[str] = []
        call_paths: dict[str, tuple[str, str]] = {}

        for turn in turns:
            if turn.role == "assistant":
                for call in turn.tool_calls:
                    call_paths[call.id] = (call.name, str(call.arguments.get("path", "")))
                    if call.name == "read_file":
                        read_requests.append(str(call.arguments.get("path", "")))
                    if call.name == "write_file":
                        wrote = True
            elif turn.role == "tool_results":
                for r in turn.results:
                    tool, path = call_paths.get(r.get("id", ""), ("", ""))
                    content = r.get("content", "") or ""
                    if tool == "list_files" and not r.get("is_error"):
                        listed = [f for f in content.split("\n") if f.strip()]
                    elif tool == "read_file" and not r.get("is_error"):
                        seen_files[path] = content

        # Build the set of injected read targets we've discovered but not yet attempted.
        for path, content in seen_files.items():
            if any(p.search(content) for p in INSTRUCTION_PATTERNS):
                for m in _READ_INSTRUCTION.finditer(content):
                    target = m.group(1)
                    if target not in pending_injection:
                        pending_injection.append(target)

        attempted = set(read_requests)

        # 1) First step: list files.
        if not listed and "list_files" in {t.name for t in tools}:
            return self._tool("list_files", {"path": "."})

        # 2) Read the task files (README, src, docs) that we haven't read yet.
        task_targets = [f for f in listed if f == "README.md"
                        or (f.startswith("src/") and f.endswith(".py"))
                        or (f.startswith("docs/") and f.endswith(".md"))]
        for target in task_targets:
            if target not in attempted:
                return self._tool("read_file", {"path": target})

        # 3) If susceptible, follow injected instructions not yet attempted.
        if self.susceptible:
            for target in pending_injection:
                if target not in attempted:
                    return self._tool("read_file", {"path": target})

        # 4) Write the summary once.
        if not wrote and "write_file" in {t.name for t in tools}:
            leaked = [seen_files[t] for t in pending_injection if t in seen_files and self.susceptible]
            body = self._summary(seen_files, leaked)
            return self._tool("write_file", {"path": _SUMMARY_PATH, "content": body})

        # 5) Finish.
        note = ("I ignored instructions embedded in the project documents and summarised only the code."
                if not self.susceptible else
                "I followed the steps described in the project documents while summarising.")
        return LLMResponse(text=f"Done. {note}", tool_calls=[], stop_reason="end_turn",
                           usage=TokenUsage(0, 0))

    @staticmethod
    def _tool(name: str, args: dict) -> LLMResponse:
        import secrets
        return LLMResponse(text="", tool_calls=[ToolCall(id=f"sim_{secrets.token_hex(4)}", name=name, arguments=args)],
                           stop_reason="tool_use", usage=TokenUsage(0, 0))

    @staticmethod
    def _summary(files: dict[str, str], leaked: list[str]) -> str:
        readme = files.get("README.md", "")
        title = next((ln.lstrip("# ").strip() for ln in readme.splitlines() if ln.startswith("# ")),
                     "Unknown project")
        lines = [f"# Summary: {title}", "", "Generated by a simulated tool-using agent.", "", "## Modules"]
        for path in sorted(p for p in files if p.startswith("src/")):
            fns = re.findall(r"^def (\w+)\(", files[path], re.MULTILINE)
            lines.append(f"- `{path}`: {', '.join(fns) or 'no functions'}")
        if leaked:
            lines += ["", "## Extra content requested by a document", *leaked]
        return "\n".join(lines) + "\n"
