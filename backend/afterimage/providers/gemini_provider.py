"""Google Gemini provider using the official Google Gen AI SDK (`google-genai`).

Uses structured function calling (`FunctionDeclaration` with a JSON-schema
`parameters_json_schema`) with the SDK's *automatic* function calling disabled: the
model only proposes calls, and AFTERIMAGE's agent executes them through the gateway.
The conversation is rebuilt from the neutral `Turn` list on every call.

Gemini thinking models attach an opaque `thought_signature` to function-call parts and
require it to be sent back unchanged on the next turn. We carry it on
`ToolCall.provider_meta`; it never contains credentials or file contents.

Credentials: the SDK's zero-argument client reads GEMINI_API_KEY (or GOOGLE_API_KEY)
from the process environment. This provider never stores the key in application state,
never puts it into the transcript, and scrubs key-like strings from every error message.
"""

from __future__ import annotations

import os
import re
import threading
import time
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

# The API rejects gemini-2.5-flash for new keys and recommends this model (verified live
# 2026-10-19); overridable via AFTERIMAGE_LLM_MODEL or the model field.
DEFAULT_MODEL = "gemini-3.8-flash"
KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

_REFUSAL_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
# Google API keys ("AIza..."), newer "AQ." keys, OAuth tokens, and key= query parameters.
_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_.-]{20,}|ya29\.[0-9A-Za-z_.-]+|"
                          r"(?i:key=)[^&\s\"']+")


# Process-wide pacing so back-to-back agent steps stay under a low requests-per-minute quota
# (the Gemini free tier allows 5 RPM). It never retries; it only waits before sending.
_PACE_LOCK = threading.Lock()
_last_request_at = 0.0


def _pace(min_interval_s: float) -> None:
    global _last_request_at
    if min_interval_s <= 0:
        return
    with _PACE_LOCK:
        wait = _last_request_at + min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def gemini_credentials_present(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    return any(env.get(name) for name in KEY_ENV_VARS)


def sanitize(message: str) -> str:
    """Remove any credential material from a provider message before it leaves this module."""
    for name in KEY_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            message = message.replace(value, "[REDACTED:credential]")
    return _KEY_PATTERN.sub("[REDACTED:credential]", message)[:500]


def _turns_to_contents(types: Any, turns: list[Turn]) -> list[Any]:
    contents: list[Any] = []
    names_by_id: dict[str, str] = {}
    for turn in turns:
        if turn.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=turn.text or "")]))
        elif turn.role == "assistant":
            parts: list[Any] = []
            if turn.text:
                parts.append(types.Part(text=turn.text))
            for call in turn.tool_calls:
                names_by_id[call.id] = call.name
                part = types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments))
                signature = (call.provider_meta or {}).get("thought_signature")
                if signature:
                    part.thought_signature = signature
                parts.append(part)
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="...")]))
        elif turn.role == "tool_results":
            parts = []
            for r in turn.results:
                key = "error" if r.get("is_error") else "output"
                parts.append(types.Part.from_function_response(
                    name=names_by_id.get(r["id"], "unknown_tool"), response={key: r["content"]}))
            contents.append(types.Content(role="user", parts=parts))
    return contents


class GeminiProvider(LLMProvider):
    name = "gemini"
    is_real = True

    def __init__(self, model: str | None = None, *, base_url: str | None = None, api_key: str | None = None,
                 min_interval_s: float = 0.0):
        super().__init__(model or DEFAULT_MODEL)
        self.min_interval_s = min_interval_s
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderConfigError("the 'google-genai' package is not installed") from exc
        self._errors = errors
        self._types = types
        if not api_key and not gemini_credentials_present():
            raise ProviderConfigError("Gemini is not configured: set GEMINI_API_KEY in the backend environment",
                                      kind="missing_credentials")
        try:
            kwargs: dict[str, Any] = {}
            if api_key:  # tests only; production relies on the SDK reading the environment
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["http_options"] = types.HttpOptions(base_url=base_url)
            self.client = genai.Client(**kwargs)
        except Exception as exc:
            raise ProviderConfigError(f"could not create the Gemini client: {sanitize(str(exc))}") from None

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec],
                 max_tokens: int, timeout: float) -> LLMResponse:
        types, errors = self._types, self._errors
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters_json_schema=t.input_schema)
                for t in tools
            ])] if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            # One attempt: AFTERIMAGE never silently retries billable calls.
            http_options=types.HttpOptions(timeout=int(timeout * 1000),
                                           retry_options=types.HttpRetryOptions(attempts=1)),
        )
        _pace(self.min_interval_s)
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=_turns_to_contents(types, turns), config=config)
        except errors.ClientError as exc:
            code = getattr(exc, "code", None)
            detail = sanitize(getattr(exc, "message", None) or str(exc))
            if code in (401, 403) or "API_KEY_INVALID" in str(exc) or "API key not valid" in str(exc):
                raise ProviderConfigError(f"Gemini authentication failed: {detail}") from None
            if code == 404:
                raise ProviderConfigError(f"model '{self.model}' not found or not available: {detail}") from None
            if code == 429:
                raise ProviderUnavailableError(f"Gemini rate limit or quota exceeded: {detail}",
                                               kind="rate_limit") from None
            raise ProviderError(f"Gemini rejected the request ({code}): {detail}", kind="bad_request") from None
        except errors.ServerError as exc:
            raise ProviderUnavailableError(f"Gemini API error ({getattr(exc, 'code', '5xx')})",
                                           kind="api_error") from None
        except errors.APIError as exc:
            raise ProviderUnavailableError(f"Gemini API error ({getattr(exc, 'code', '?')})",
                                           kind="api_error") from None
        except Exception as exc:  # transport errors from the SDK's HTTP client
            if "timeout" in type(exc).__name__.lower():
                raise ProviderUnavailableError(f"Gemini request timed out after {timeout}s", kind="timeout") from None
            raise ProviderUnavailableError(f"cannot reach the Gemini API ({type(exc).__name__})",
                                           kind="connection") from None
        return self._parse(response)

    def _parse(self, response: Any) -> LLMResponse:
        feedback = getattr(response, "prompt_feedback", None)
        if not response.candidates:
            reason = getattr(getattr(feedback, "block_reason", None), "name", None)
            if reason:
                raise ProviderRefusal("the model declined to respond to this request", category=reason)
            raise ProviderError("Gemini returned no candidates", kind="bad_response")
        candidate = response.candidates[0]
        finish = getattr(candidate.finish_reason, "name", None) or str(candidate.finish_reason or "")
        if finish in _REFUSAL_REASONS:
            raise ProviderRefusal("the model declined to respond to this request", category=finish)
        if finish in ("MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"):
            raise ProviderError(f"Gemini produced an invalid tool call ({finish})", kind="bad_response")

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        parts = (candidate.content.parts if candidate.content and candidate.content.parts else [])
        for i, part in enumerate(parts):
            if part.function_call is not None:
                fc = part.function_call
                meta = {"thought_signature": part.thought_signature} if part.thought_signature else {}
                tool_calls.append(ToolCall(id=fc.id or f"gemini_call_{i}", name=fc.name or "",
                                           arguments=dict(fc.args) if isinstance(fc.args, dict) else {},
                                           provider_meta=meta))
            elif part.text and not part.thought:
                text_parts.append(part.text)
        meta = response.usage_metadata
        usage = TokenUsage(
            input_tokens=(getattr(meta, "prompt_token_count", 0) or 0) if meta else 0,
            output_tokens=((getattr(meta, "candidates_token_count", 0) or 0)
                           + (getattr(meta, "thoughts_token_count", 0) or 0)) if meta else 0,
        )
        stop = "tool_use" if tool_calls else ("max_tokens" if finish == "MAX_TOKENS" else "end_turn")
        return LLMResponse(text="\n".join(text_parts).strip(), tool_calls=tool_calls, stop_reason=stop, usage=usage)
