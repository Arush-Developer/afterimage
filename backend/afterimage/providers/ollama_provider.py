"""Local Ollama provider (optional).

Talks to an Ollama server's /api/chat endpoint using its native tool calling. No
credentials are needed. Inference stays local: the configured host must be a loopback
address unless AFTERIMAGE_OLLAMA_ALLOW_REMOTE=1 is set explicitly (validated in config).

Before the first request the adapter checks, via /api/show, that the selected model is
pulled and advertises the "tools" capability. If the model does not support tool calling,
the run fails with a clear error instead of pretending it works. Older Ollama versions do
not report capabilities; then support is "unknown" and a runtime "does not support tools"
error is mapped to the same clear error.
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
    names: dict[str, str] = {}
    for turn in turns:
        if turn.role == "user":
            messages.append({"role": "user", "content": turn.text or ""})
        elif turn.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
            if turn.tool_calls:
                msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.arguments}} for c in turn.tool_calls
                ]
                names.update({c.id: c.name for c in turn.tool_calls})
            messages.append(msg)
        elif turn.role == "tool_results":
            for r in turn.results:
                # tool_name lets the model associate the result with its call.
                messages.append({"role": "tool", "content": r["content"], "tool_name": names.get(r["id"], "")})
    return messages


def _model_matches(name: str, wanted: str) -> bool:
    return name == wanted or (":" not in wanted and name == f"{wanted}:latest")


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_real = True

    def __init__(self, model: str | None = None, *, host: str = DEFAULT_HOST):
        super().__init__(model or DEFAULT_MODEL)
        self.host = host.rstrip("/")
        try:
            import httpx2 as httpx  # installed with the anthropic SDK
        except ImportError:  # pragma: no cover
            import httpx  # type: ignore
        self._httpx = httpx
        self._tools_checked = False
        self._call_seq = 0

    # -- capability / health ------------------------------------------------------------
    def capabilities(self, timeout: float = 5.0) -> dict[str, Any]:
        """Inspect the local server and model. Raises ProviderError subclasses."""
        try:
            version = self._httpx.get(f"{self.host}/api/version", timeout=timeout)
            tags = self._httpx.get(f"{self.host}/api/tags", timeout=timeout)
        except Exception as exc:
            raise ProviderUnavailableError(f"Ollama is not running or not reachable at {self.host} "
                                           "(start it with `ollama serve`)", kind="connection") from exc
        if tags.status_code != 200:
            raise ProviderUnavailableError(f"Ollama at {self.host} answered {tags.status_code} to /api/tags",
                                           kind="api_error")
        models = [m.get("name", "") for m in (tags.json().get("models") or [])]
        if not any(_model_matches(m, self.model) for m in models):
            raise ProviderConfigError(f"Ollama model '{self.model}' is not pulled (run `ollama pull {self.model}`). "
                                      f"Installed: {', '.join(models) or 'none'}.", kind="model_unavailable")
        try:
            show = self._httpx.post(f"{self.host}/api/show", json={"model": self.model}, timeout=timeout)
            caps = show.json().get("capabilities") if show.status_code == 200 else None
        except Exception:
            caps = None
        if caps is None:
            tool_calling = "unknown"
        else:
            tool_calling = "supported" if "tools" in caps else "unsupported"
        return {"version": (version.json() or {}).get("version") if version.status_code == 200 else None,
                "models": models, "tool_calling": tool_calling, "capabilities": caps}

    def check(self, timeout: float = 5.0) -> dict[str, Any]:
        try:
            info = self.capabilities(timeout)
        except ProviderUnavailableError as exc:
            return {"reachable": False, "model_available": False, "tool_calling": "unknown",
                    "error_kind": exc.kind, "detail": exc.message}
        except ProviderConfigError as exc:
            return {"reachable": True, "model_available": False, "tool_calling": "unknown",
                    "error_kind": exc.kind, "detail": exc.message}
        detail = {
            "supported": f"Model '{self.model}' is pulled and advertises tool calling.",
            "unsupported": (f"Model '{self.model}' is pulled but does NOT support tool calling; "
                            "AFTERIMAGE cannot use it as an agent. Choose a tool-capable model."),
            "unknown": (f"Model '{self.model}' is pulled. This Ollama version does not report capabilities, "
                        "so tool calling is unverified until the first run."),
        }[info["tool_calling"]]
        return {"reachable": True, "model_available": True, "tool_calling": info["tool_calling"],
                "ollama_version": info["version"], "detail": detail}

    def _ensure_tools(self, timeout: float) -> None:
        if self._tools_checked:
            return
        info = self.capabilities(min(timeout, 10.0))
        if info["tool_calling"] == "unsupported":
            raise ProviderConfigError(f"Ollama model '{self.model}' does not support tool calling; choose a "
                                      "tool-capable model (e.g. llama3.1, qwen2.5).", kind="tools_unsupported")
        self._tools_checked = True

    # -- main call ----------------------------------------------------------------------
    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec],
                 max_tokens: int, timeout: float) -> LLMResponse:
        if tools:
            self._ensure_tools(timeout)
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
        except self._httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"Ollama request timed out after {timeout}s", kind="timeout") from exc
        except Exception as exc:
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self.host} (is `ollama serve` running?)", kind="connection"
            ) from exc
        body = resp.text[:300]
        if resp.status_code == 404:
            raise ProviderConfigError(f"Ollama model '{self.model}' is not pulled (run `ollama pull {self.model}`)",
                                      kind="model_unavailable")
        if resp.status_code == 400 and "does not support tools" in body:
            raise ProviderConfigError(f"Ollama model '{self.model}' does not support tool calling; choose a "
                                      "tool-capable model.", kind="tools_unsupported")
        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"Ollama server error ({resp.status_code})", kind="api_error")
        if resp.status_code >= 400:
            raise ProviderError(f"Ollama rejected the request ({resp.status_code}): {body[:200]}", kind="bad_request")
        try:
            data = resp.json()
            message = data.get("message", {})
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("Ollama returned a malformed response", kind="bad_response") from exc

        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {}) or {}
            args = fn.get("arguments", {})
            parse_error = None
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    parse_error, args = "invalid JSON", {}
            if not isinstance(args, dict):
                parse_error, args = parse_error or "arguments were not a JSON object", {}
            self._call_seq += 1
            tool_calls.append(ToolCall(id=call.get("id") or f"ollama_call_{self._call_seq}",
                                       name=fn.get("name", ""), arguments=args, parse_error=parse_error))
        stop_reason = "tool_use" if tool_calls else ("max_tokens" if data.get("done_reason") == "length" else "end_turn")
        usage = TokenUsage(input_tokens=data.get("prompt_eval_count", 0) or 0,
                           output_tokens=data.get("eval_count", 0) or 0)
        return LLMResponse(text=(message.get("content") or "").strip(), tool_calls=tool_calls,
                           stop_reason=stop_reason, usage=usage)
