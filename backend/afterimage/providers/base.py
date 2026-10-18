"""Provider-neutral LLM abstraction.

A provider turns a provider-neutral conversation (`Turn` list) plus tool specs into a
single assistant response (`LLMResponse`). The LLM agent owns the loop; providers are
stateless and only translate to/from their wire format.

Security note: providers receive ONLY the data the caller passes (task text, tool
descriptions, redacted/allowed tool results). They never receive API keys of other
services, environment secrets, or protected file contents — those never enter the
transcript the agent builds (see llm_agent.py and gateway.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


class ProviderError(Exception):
    """Base class for provider failures. `kind` drives the HTTP status and UI message."""

    def __init__(self, message: str, *, kind: str = "provider_error", retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retryable = retryable


class ProviderConfigError(ProviderError):
    """Missing/invalid credentials or model configuration (fail fast, do not run)."""

    def __init__(self, message: str, *, kind: str = "config_error"):
        super().__init__(message, kind=kind, retryable=False)


class ProviderUnavailableError(ProviderError):
    """Provider could not be reached (network, timeout, 5xx, rate limit, quota)."""

    def __init__(self, message: str, *, kind: str = "unavailable", retryable: bool = True,
                 retry_after_s: float | None = None):
        super().__init__(message, kind=kind, retryable=retryable)
        self.retry_after_s = retry_after_s


class ProviderRefusal(ProviderError):
    """The model declined to respond (safety refusal)."""

    def __init__(self, message: str, *, category: str | None = None):
        super().__init__(message, kind="refusal", retryable=False)
        self.category = category


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    #: set when the provider returned arguments that were not valid JSON / not an object;
    #: the agent rejects such calls without executing them.
    parse_error: str | None = None
    #: provider-specific data needed to replay the call faithfully (never persisted)
    provider_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Turn:
    role: Literal["user", "assistant", "tool_results"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # for role == "tool_results": list of {"id", "content", "is_error"}
    results: list[dict[str, Any]] = field(default_factory=list)
    #: the provider's own representation of an assistant turn (e.g. Gemini Content with
    #: thought signatures). Replayed verbatim by the same provider; never persisted.
    provider_payload: Any = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # end_turn | tool_use | max_tokens | malformed_tool_call | ...
    usage: TokenUsage = field(default_factory=TokenUsage)
    provider_payload: Any = None


class LLMProvider(ABC):
    """Stateless translator between the neutral conversation and a concrete LLM API."""

    #: short machine name, e.g. "anthropic", "ollama", "mock"
    name: str = "base"
    #: whether this provider uses real network/credentials (affects UI labelling)
    is_real: bool = True

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        turns: list[Turn],
        tools: list[ToolSpec],
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        """Produce one assistant response. Must raise a ProviderError subclass on failure."""

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "is_real": self.is_real}
