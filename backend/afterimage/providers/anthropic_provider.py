"""Anthropic (Claude) provider using the official `anthropic` SDK.

Uses structured tool calling (`tools=[...]` with `strict` schemas). The conversation is
reconstructed from the neutral `Turn` list on every call, so the agent never has to hold
provider-native state. We assign our own tool_use ids, which the API accepts.

Credentials come from the environment the SDK already resolves (ANTHROPIC_API_KEY or an
`ant auth login` profile). This provider never reads a key into application state and
never puts a key into the transcript.
"""

from __future__ import annotations

from typing import Any

from .base import (
    LLMProvider,
    LLMResponse,
    ProviderConfigError,
    ProviderError,
    ProviderRefusal,
    ProviderUnavailableError,
    ToolCall,
    ToolSpec,
    TokenUsage,
    Turn,
)

# Default model per the Claude API guidance; overridable via configuration.
DEFAULT_MODEL = "claude-opus-5-5"


def _turns_to_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if turn.role == "user":
            messages.append({"role": "user", "content": [{"type": "text", "text": turn.text or ""}]})
        elif turn.role == "assistant":
            content: list[dict[str, Any]] = []
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            for call in turn.tool_calls:
                content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            # An assistant turn must have at least one block.
            messages.append({"role": "assistant", "content": content or [{"type": "text", "text": "..."}]})
        elif turn.role == "tool_results":
            content = [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"],
                 "is_error": bool(r.get("is_error"))}
                for r in turn.results
            ]
            messages.append({"role": "user", "content": content})
    return messages


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    is_real = True

    def __init__(self, model: str | None = None, *, max_retries: int = 1, effort: str | None = "medium",
                 base_url: str | None = None, api_key: str | None = None):
        super().__init__(model or DEFAULT_MODEL)
        self.effort = effort
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderConfigError("the 'anthropic' package is not installed") from exc
        self._anthropic = anthropic
        try:
            # Zero-arg client resolves credentials from the environment / profile.
            kwargs: dict[str, Any] = {"max_retries": max_retries}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:  # tests only; production relies on the SDK's own credential resolution
                kwargs["api_key"] = api_key
            self.client = anthropic.Anthropic(**kwargs)
        except Exception as exc:  # credentials not resolvable
            raise ProviderConfigError(
                "no Anthropic credentials found; set ANTHROPIC_API_KEY or run `ant auth login`"
            ) from exc

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec],
                 max_tokens: int, timeout: float) -> LLMResponse:
        anthropic = self._anthropic
        tool_defs = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema, "strict": True}
            for t in tools
        ]
        try:
            response = self.client.with_options(timeout=timeout).messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tool_defs,
                messages=_turns_to_messages(turns),
                **({"output_config": {"effort": self.effort}} if self.effort else {}),
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderConfigError(f"Anthropic authentication failed: {exc}") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderConfigError(f"Anthropic permission denied: {exc}") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderConfigError(f"model '{self.model}' not found or not available") from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"Anthropic rejected the request: {exc}", kind="bad_request") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(f"Anthropic rate limit exceeded: {exc}", kind="rate_limit") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderUnavailableError(f"Anthropic request timed out after {timeout}s", kind="timeout") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(f"cannot reach Anthropic API: {exc}", kind="connection") from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500
            raise ProviderUnavailableError(
                f"Anthropic API error ({exc.status_code})", kind="api_error", retryable=retryable
            ) from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ProviderRefusal("the model declined to respond to this request", category=category)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=args))
        usage = TokenUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )
        return LLMResponse(text="\n".join(text_parts).strip(), tool_calls=tool_calls,
                           stop_reason=response.stop_reason or "end_turn", usage=usage)
