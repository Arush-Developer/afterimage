"""Local Ollama provider (optional).

Talks to a local Ollama server's /api/chat endpoint using its OpenAI-style tool calling.
No credentials are needed; the server must be running locally (default
http://127.0.0.1:11434). Enabled only when the provider is explicitly selected, so it
cannot destabilise the default deterministic/Anthropic paths.
"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    LLMProvider,
    LLMResponse,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailableError,
    ToolCall,
    ToolSpec,
    TokenUsage,
    Turn,
)

DEFAULT_MODEL = "llama3.1"
DEFAULT_HOST = "http://127.0.0.1:11434"


def _turns_to_messages(system: str, turns: list[Turn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in turns:
        if turn.role == "user":
            messages.append({"role": "user", "content": turn.text or ""})
        elif turn.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
            if turn.tool_calls:
                msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.arguments}} for c in turn.tool_calls
                ]
            messages.append(msg)
        elif turn.role == "tool_results":
            for r in turn.results:
                messages.append({"role": "tool", "content": r["content"]})
    return messages


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_real = True

    def __init__(self, model: str | None = None, *, host: str = DEFAULT_HOST):
        super().__init__(model or DEFAULT_MODEL)
        self.host = host.rstrip("/")
        try:
            import httpx2 as httpx  # the anthropic SDK pulls this in
        except ImportError:  # pragma: no cover
            try:
                import httpx  # type: ignore
            except ImportError as exc:
                raise ProviderConfigError("no HTTP client available for the Ollama provider") from exc
        self._httpx = httpx

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec],
                 max_tokens: int, timeout: float) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": _turns_to_messages(system, turns),
            "tools": [
                {"type": "function", "function": {"name": t.name, "description": t.description,
                                                   "parameters": t.input_schema}}
                for t in tools
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0},
        }
        try:
            resp = self._httpx.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
        except Exception as exc:
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self.host} (is `ollama serve` running?)", kind="connection"
            ) from exc
        if resp.status_code == 404:
            raise ProviderConfigError(f"model '{self.model}' is not pulled in Ollama (try `ollama pull {self.model}`)")
        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"Ollama server error ({resp.status_code})", kind="api_error")
        if resp.status_code >= 400:
            raise ProviderError(f"Ollama rejected the request ({resp.status_code}): {resp.text[:200]}",
                                kind="bad_request")
        try:
            data = resp.json()
            message = data.get("message", {})
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("Ollama returned a malformed response", kind="bad_response") from exc

        tool_calls: list[ToolCall] = []
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=f"ollama_call_{i}", name=fn.get("name", ""),
                                       arguments=args if isinstance(args, dict) else {}))
        stop_reason = "tool_use" if tool_calls else "end_turn"
        usage = TokenUsage(input_tokens=data.get("prompt_eval_count", 0) or 0,
                           output_tokens=data.get("eval_count", 0) or 0)
        return LLMResponse(text=(message.get("content") or "").strip(), tool_calls=tool_calls,
                           stop_reason=stop_reason, usage=usage)
