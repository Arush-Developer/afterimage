"""LLM provider registry: build providers from settings and report configuration status
without ever exposing credentials.

There is deliberately NO fallback between providers: if the selected provider is not
configured or fails, the caller gets a typed error. A free or local provider is never
silently replaced by a paid one (or vice versa).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from .anthropic_provider import AnthropicProvider
from .base import (LLMProvider, LLMResponse, ProviderConfigError, ProviderError, ProviderRefusal,
                   ProviderUnavailableError, ToolCall, ToolSpec, TokenUsage, Turn)
from .gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from .gemini_provider import GeminiProvider, gemini_key_present
from .mock_provider import ScriptedProvider, SimulatedInjectionProvider
from .ollama_provider import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from .ollama_provider import OllamaProvider

PROVIDERS = ("anthropic", "gemini", "ollama", "simulated")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")

DEFAULT_MODELS = {"anthropic": ANTHROPIC_DEFAULT_MODEL, "gemini": GEMINI_DEFAULT_MODEL,
                  "ollama": OLLAMA_DEFAULT_MODEL, "simulated": "simulated-agent"}

LABELS = {"anthropic": "Anthropic Claude", "gemini": "Google Gemini", "ollama": "Ollama (local)",
          "simulated": "Simulated agent (no LLM)"}

__all__ = [
    "PROVIDERS", "DEFAULT_MODELS", "LABELS", "LLMProvider", "LLMResponse", "ToolCall", "ToolSpec", "TokenUsage",
    "Turn", "ProviderError", "ProviderConfigError", "ProviderUnavailableError", "ProviderRefusal",
    "ScriptedProvider", "SimulatedInjectionProvider", "AnthropicProvider", "GeminiProvider", "OllamaProvider",
    "build_provider", "provider_status", "check_provider", "validate_model", "resolved_models",
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


def resolved_models(settings: Any) -> dict[str, str]:
    """The model each provider will use when the caller does not name one."""
    return {name: (settings.model_for(name) if hasattr(settings, "model_for") else None) or DEFAULT_MODELS[name]
            for name in PROVIDERS}


def build_provider(name: str, model: str | None, settings: Any) -> LLMProvider:
    """Construct exactly the requested provider. Raises ProviderConfigError with a
    user-facing message; never substitutes a different provider."""
    if name not in PROVIDERS:
        raise ProviderConfigError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}",
                                  kind="unknown_provider")
    model = validate_model(model or resolved_models(settings)[name])
    if name == "simulated":
        return SimulatedInjectionProvider(model=model, susceptible=True)
    if name == "ollama":
        return OllamaProvider(model=model, host=settings.ollama_host)
    if name == "gemini":
        # GeminiProvider reads GEMINI_API_KEY itself and raises missing_credentials if unset.
        return GeminiProvider(model=model, base_url=settings.gemini_base_url,
                              rate_limit_retries=settings.gemini_rate_limit_retries,
                              max_retry_wait_s=settings.gemini_max_retry_wait_s)
    if not anthropic_credentials_present() and not settings.anthropic_base_url:
        raise ProviderConfigError("Anthropic is not configured: add an API key in Settings or set ANTHROPIC_API_KEY (or run `ant auth login`)",
                                  kind="missing_credentials")
    return AnthropicProvider(model=model, effort=settings.llm_effort or None,
                             base_url=settings.anthropic_base_url or None)


def _ollama_reachable(settings: Any) -> bool:
    try:
        import httpx2 as httpx
        return httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=1.5).status_code == 200
    except Exception:
        return False


def provider_status(settings: Any, *, probe_ollama: bool = True) -> list[dict[str, Any]]:
    """Cheap configuration status for the UI (no paid API calls). Never includes key material.

    `configured` = credentials present (cloud) or server reachable (Ollama). Whether a cloud
    key is actually valid, and whether a model is available, needs `check_provider`."""
    models = resolved_models(settings)
    anthropic_ok = anthropic_credentials_present() or bool(settings.anthropic_base_url)
    gemini_ok = gemini_key_present()
    ollama_ok = _ollama_reachable(settings) if probe_ollama else False
    return [
        {"provider": "anthropic", "label": LABELS["anthropic"], "real": True, "local": False, "billing": "paid",
         "configured": anthropic_ok, "default_model": models["anthropic"],
         "detail": ("Credentials detected in the backend environment (value never shown)." if anthropic_ok
                    else "Add an API key below, or set ANTHROPIC_API_KEY in the backend environment. Paid API.")},
        {"provider": "gemini", "label": LABELS["gemini"], "real": True, "local": False, "billing": "free tier or paid",
         "configured": gemini_ok, "default_model": models["gemini"],
         "detail": ("GEMINI_API_KEY detected in the backend environment (value never shown). Free-tier limits "
                    "depend on your Google project; use Check to verify the key and model." if gemini_ok
                    else "Add an API key below, or set GEMINI_API_KEY in the backend environment (a free-tier key works).")},
        {"provider": "ollama", "label": LABELS["ollama"], "real": True, "local": True, "billing": "local",
         "configured": ollama_ok, "default_model": models["ollama"],
         "detail": (f"Local server at {settings.ollama_host} is " + ("reachable." if ollama_ok else
                    "not reachable (start it with `ollama serve`).") + " Inference stays on this machine.")},
        {"provider": "simulated", "label": LABELS["simulated"], "real": False, "local": True, "billing": "none",
         "configured": True, "default_model": models["simulated"],
         "detail": "Rule-based stand-in for demos without credentials. Not a language model."},
    ]


def check_provider(name: str, model: str | None, settings: Any) -> dict[str, Any]:
    """Live check of one provider + model. Never generates content (so it does not use
    generation quota) and never returns key material."""
    base = {"provider": name, "label": LABELS.get(name, name)}
    try:
        provider = build_provider(name, model, settings)
    except ProviderConfigError as exc:
        return {**base, "model": model, "configured": False, "reachable": False, "model_available": False,
                "tool_calling": "unknown", "error_kind": exc.kind, "detail": exc.message}
    base.update({"model": provider.model, "configured": True})
    if name == "simulated":
        return {**base, "reachable": True, "model_available": True, "tool_calling": "supported",
                "detail": "Built-in simulated agent; always available. Not a language model."}
    if name == "anthropic":
        try:
            provider.client.models.retrieve(provider.model)  # type: ignore[attr-defined]
            return {**base, "reachable": True, "model_available": True, "tool_calling": "supported",
                    "detail": f"Model '{provider.model}' is available to these credentials."}
        except Exception as exc:  # map via the provider's own error handling where possible
            import anthropic
            if isinstance(exc, anthropic.NotFoundError):
                return {**base, "reachable": True, "model_available": False, "tool_calling": "unknown",
                        "error_kind": "model_unavailable", "detail": f"Model '{provider.model}' was not found."}
            if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
                return {**base, "reachable": True, "model_available": False, "tool_calling": "unknown",
                        "error_kind": "invalid_credentials", "detail": "Anthropic rejected the credentials."}
            return {**base, "reachable": False, "model_available": False, "tool_calling": "unknown",
                    "error_kind": "connection", "detail": "Could not reach the Anthropic API."}
    return {**base, **provider.check()}  # gemini / ollama implement check()
