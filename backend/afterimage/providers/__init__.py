"""LLM provider registry: build providers from settings and report configuration status
without ever exposing credentials."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from .anthropic_provider import AnthropicProvider
from .base import (LLMProvider, LLMResponse, ProviderConfigError, ProviderError, ProviderRefusal,
                   ProviderUnavailableError, ToolCall, ToolSpec, TokenUsage, Turn)
from .mock_provider import ScriptedProvider, SimulatedInjectionProvider
from .ollama_provider import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from .ollama_provider import OllamaProvider

PROVIDERS = ("anthropic", "ollama", "simulated")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")

DEFAULT_MODELS = {"anthropic": ANTHROPIC_DEFAULT_MODEL, "ollama": OLLAMA_DEFAULT_MODEL,
                  "simulated": "simulated-agent"}

__all__ = [
    "PROVIDERS", "DEFAULT_MODELS", "LLMProvider", "LLMResponse", "ToolCall", "ToolSpec", "TokenUsage", "Turn",
    "ProviderError", "ProviderConfigError", "ProviderUnavailableError", "ProviderRefusal",
    "ScriptedProvider", "SimulatedInjectionProvider", "AnthropicProvider", "OllamaProvider",
    "build_provider", "provider_status", "validate_model",
]


def validate_model(model: str) -> str:
    if not MODEL_RE.match(model):
        raise ProviderConfigError(f"invalid model name {model!r}", kind="invalid_model")
    return model


def anthropic_credentials_present(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    config_dir = Path(env.get("ANTHROPIC_CONFIG_DIR") or Path.home() / ".config" / "anthropic")
    return config_dir.is_dir() and any(config_dir.iterdir())


def build_provider(name: str, model: str | None, settings: Any) -> LLMProvider:
    """Construct a provider. Raises ProviderConfigError with a user-facing message."""
    if name not in PROVIDERS:
        raise ProviderConfigError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}",
                                  kind="unknown_provider")
    model = validate_model(model or getattr(settings, "llm_model", None) or DEFAULT_MODELS[name])
    if name == "simulated":
        return SimulatedInjectionProvider(model=model, susceptible=True)
    if name == "ollama":
        return OllamaProvider(model=model, host=settings.ollama_host)
    if not anthropic_credentials_present() and not settings.anthropic_base_url:
        raise ProviderConfigError("Anthropic is not configured: set ANTHROPIC_API_KEY (or run `ant auth login`)",
                                  kind="missing_credentials")
    return AnthropicProvider(model=model, effort=settings.llm_effort or None,
                             base_url=settings.anthropic_base_url or None)


def provider_status(settings: Any, *, probe_ollama: bool = True) -> list[dict[str, Any]]:
    """Configuration status for the UI. Never includes key material."""
    out = [{
        "provider": "anthropic", "label": "Anthropic Claude", "real": True,
        "configured": anthropic_credentials_present() or bool(settings.anthropic_base_url),
        "default_model": DEFAULT_MODELS["anthropic"],
        "detail": ("Credentials detected in the backend environment (value never shown)."
                   if anthropic_credentials_present()
                   else "Set ANTHROPIC_API_KEY in the backend environment to enable."),
    }]
    reachable = False
    if probe_ollama:
        try:
            import httpx2 as httpx
            reachable = httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=1.5).status_code == 200
        except Exception:
            reachable = False
    out.append({
        "provider": "ollama", "label": "Ollama (local)", "real": True, "configured": reachable,
        "default_model": DEFAULT_MODELS["ollama"],
        "detail": f"Local server at {settings.ollama_host} is " + ("reachable." if reachable else "not reachable."),
    })
    out.append({
        "provider": "simulated", "label": "Simulated agent (no LLM)", "real": False, "configured": True,
        "default_model": DEFAULT_MODELS["simulated"],
        "detail": "Rule-based stand-in for demos without credentials. Not a language model.",
    })
    return out
