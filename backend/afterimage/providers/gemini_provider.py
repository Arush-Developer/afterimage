"""Google Gemini provider using Google's official `google-genai` SDK (Gemini Developer API).

* Credentials: ONLY the `GEMINI_API_KEY` variable from the backend process environment is
  used. It is passed explicitly to the SDK (so GOOGLE_API_KEY / Vertex settings are never
  picked up implicitly) and travels in the `x-goog-api-key` header, never in a URL.
* Tools are declared as function declarations; automatic function calling is disabled, so
  the SDK never executes anything. Every call is returned to the agent, which validates it
  and runs it only through the AFTERIMAGE gateway.
* The model's own `Content` (including thought signatures) is replayed verbatim on the next
  turn via `Turn.provider_payload`, which newer Gemini models require for tool use.
* Errors are mapped to typed provider errors, distinguishing free-tier quota exhaustion
  (daily limits) from per-minute rate limits. Per-minute 429s are retried a bounded number
  of times, honouring the server's RetryInfo delay; quota exhaustion is never retried.

This adapter never falls back to another provider.
"""

from __future__ import annotations

import os
import re
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

# gemini-3.8-flash is closed to new API keys (live 404 on 2026-10-19: "no longer available to new
# users"); the API recommends this model instead. Configurable because availability varies by
# account, region and over time.
DEFAULT_MODEL = "gemini-3.8-flash"
API_KEY_ENV = "GEMINI_API_KEY"

_REFUSAL_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY",
                   "IMAGE_PROHIBITED_CONTENT"}
_MALFORMED_FINISH = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}


def gemini_key_present(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    return bool(env.get(API_KEY_ENV))


def _enum_name(value: Any) -> str:
    return getattr(value, "name", None) or str(value or "")


def _parse_delay(value: Any) -> float | None:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)s\s*$", str(value or ""))
    return float(match.group(1)) if match else None


def classify_429(details: Any) -> tuple[str, float | None]:
    """Return ("quota_exhausted" | "rate_limit", retry_delay_seconds) from a 429 error body."""
    error = details.get("error", details) if isinstance(details, dict) else {}
    quota_ids: list[str] = []
    delay = None
    for item in error.get("details", []) if isinstance(error, dict) else []:
        if not isinstance(item, dict):
            continue
        for violation in item.get("violations", []) or []:
            quota_ids.append(str(violation.get("quotaId", "")))
        if "retryDelay" in item:
            delay = _parse_delay(item["retryDelay"])
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    daily = any("PerDay" in q for q in quota_ids) or "per day" in message.lower()
    return ("quota_exhausted" if daily else "rate_limit"), delay


class GeminiProvider(LLMProvider):
    name = "gemini"
    is_real = True

    def __init__(self, model: str | None = None, *, api_key: str | None = None, base_url: str | None = None,
                 rate_limit_retries: int = 2, max_retry_wait_s: float = 30.0):
        super().__init__(model or DEFAULT_MODEL)
        key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        if not key:
            raise ProviderConfigError(f"Gemini is not configured: set {API_KEY_ENV} in the backend environment",
                                      kind="missing_credentials")
        try:
            import httpx
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderConfigError("the 'google-genai' package is not installed") from exc
        self._genai, self._types, self._errors, self._httpx = genai, types, errors, httpx
        self._key = key
        self._base_url = base_url
        self.rate_limit_retries = rate_limit_retries
        self.max_retry_wait_s = max_retry_wait_s
        self._call_seq = 0

    # -- client --------------------------------------------------------------------
    def _client(self, timeout: float):
        types = self._types
        options: dict[str, Any] = {"timeout": int(timeout * 1000),
                                   "retry_options": types.HttpRetryOptions(attempts=1)}
        if self._base_url:
            options["base_url"] = self._base_url
        # vertexai=False pins the Gemini Developer API; the key is passed explicitly.
        return self._genai.Client(api_key=self._key, vertexai=False, http_options=types.HttpOptions(**options))

    # -- conversion ------------------------------------------------------------------
    def _contents(self, turns: list[Turn]) -> list[Any]:
        types = self._types
        names: dict[str, str] = {}
        native_ids: dict[str, str | None] = {}
        contents: list[Any] = []
        for turn in turns:
            if turn.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=turn.text or "")]))
            elif turn.role == "assistant":
                for call in turn.tool_calls:
                    names[call.id] = call.name
                    native_ids[call.id] = call.provider_meta.get("native_id")
                if isinstance(turn.provider_payload, types.Content):
                    contents.append(turn.provider_payload)  # verbatim: keeps thought signatures
                    continue
                parts = [types.Part(text=turn.text)] if turn.text else []
                parts += [types.Part(function_call=types.FunctionCall(
                    name=c.name, args=c.arguments, id=c.provider_meta.get("native_id"))) for c in turn.tool_calls]
                contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
            elif turn.role == "tool_results":
                parts = []
                for r in turn.results:
                    key = "error" if r.get("is_error") else "output"
                    parts.append(types.Part(function_response=types.FunctionResponse(
                        id=native_ids.get(r["id"]), name=names.get(r["id"], "unknown_tool"),
                        response={key: r["content"]})))
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def _config(self, system: str, tools: list[ToolSpec], max_tokens: int) -> Any:
        types = self._types
        declarations = [types.FunctionDeclaration(name=t.name, description=t.description,
                                                  parameters_json_schema=t.input_schema) for t in tools]
        return types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            # Never let the SDK run functions itself: the gateway must decide every call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # -- errors ----------------------------------------------------------------------
    def _map_api_error(self, exc: Any) -> ProviderError:
        code = getattr(exc, "code", None) or 0
        status = str(getattr(exc, "status", "") or "")
        message = str(getattr(exc, "message", "") or "")
        lowered = message.lower()
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            kind, delay = classify_429(getattr(exc, "details", None))
            if kind == "quota_exhausted":
                return ProviderUnavailableError(
                    f"Gemini quota exhausted for model '{self.model}' (free-tier daily limit or project quota). "
                    "Wait for the quota to reset, choose another model, or enable billing on your Google project.",
                    kind="quota_exhausted", retryable=False, retry_after_s=delay)
            return ProviderUnavailableError(
                f"Gemini rate limit reached for model '{self.model}' (requests per minute)."
                + (f" Retry after about {delay:.0f}s." if delay else " Retry shortly."),
                kind="rate_limit", retryable=True, retry_after_s=delay)
        if code in (401, 403) or "api key not valid" in lowered or "api_key_invalid" in lowered:
            return ProviderConfigError("Gemini rejected the API key (invalid, expired or lacking permission). "
                                       f"Check {API_KEY_ENV}.", kind="invalid_credentials")
        if code == 404 or status == "NOT_FOUND":
            return ProviderConfigError(f"Gemini model '{self.model}' is not available to this API key "
                                       "(unknown model, retired, or not enabled for your project/tier). "
                                       f"Google says: {message[:200]}",
                                       kind="model_unavailable")
        if code == 400 and ("location" in lowered or "not available in your country" in lowered
                            or status == "FAILED_PRECONDITION"):
            return ProviderConfigError(f"Gemini refused the request for this account/region: {message[:200]}",
                                       kind="account_unsupported")
        if code >= 500:
            return ProviderUnavailableError(f"Gemini service error ({code} {status}). Retry later.",
                                            kind="api_error", retryable=True)
        return ProviderError(f"Gemini rejected the request ({code} {status}): {message[:200]}", kind="bad_request")

    # -- main call -------------------------------------------------------------------
    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec],
                 max_tokens: int, timeout: float) -> LLMResponse:
        client = self._client(timeout)
        contents = self._contents(turns)
        config = self._config(system, tools, max_tokens)
        attempt = 0
        while True:
            try:
                response = client.models.generate_content(model=self.model, contents=contents, config=config)
                break
            except self._errors.APIError as exc:
                mapped = self._map_api_error(exc)
                wait = getattr(mapped, "retry_after_s", None) or 2.0
                if (mapped.kind == "rate_limit" and attempt < self.rate_limit_retries
                        and wait <= self.max_retry_wait_s):
                    attempt += 1
                    time.sleep(wait)
                    continue
                raise mapped from exc
            except self._httpx.TimeoutException as exc:
                raise ProviderUnavailableError(f"Gemini request timed out after {timeout}s",
                                               kind="timeout") from exc
            except self._httpx.TransportError as exc:
                raise ProviderUnavailableError("cannot reach the Gemini API (network error)",
                                               kind="connection") from exc
        return self._parse(response)

    def _parse(self, response: Any) -> LLMResponse:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderRefusal("Gemini blocked the prompt", category=_enum_name(feedback.block_reason))
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise ProviderError("Gemini returned no candidates", kind="bad_response")
        candidate = candidates[0]
        finish = _enum_name(getattr(candidate, "finish_reason", None))
        usage_meta = getattr(response, "usage_metadata", None)
        usage = TokenUsage(input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                           output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0)
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for part in parts:
            if getattr(part, "thought", False):
                continue  # reasoning summaries are not part of the answer
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc is not None:
                self._call_seq += 1
                args = fc.args
                parse_error = None
                if args is None:
                    args = {}
                elif not isinstance(args, dict):
                    parse_error, args = "arguments were not a JSON object", {}
                calls.append(ToolCall(id=fc.id or f"gemini_call_{self._call_seq}", name=fc.name or "",
                                      arguments=dict(args), parse_error=parse_error,
                                      provider_meta={"native_id": fc.id}))

        if finish in _REFUSAL_FINISH and not calls:
            raise ProviderRefusal(f"Gemini stopped the response for safety reasons ({finish})", category=finish)
        if finish in _MALFORMED_FINISH and not calls:
            return LLMResponse(text="", tool_calls=[], stop_reason="malformed_tool_call", usage=usage,
                               provider_payload=content)
        stop = "tool_use" if calls else ("max_tokens" if finish == "MAX_TOKENS" else "end_turn")
        return LLMResponse(text="\n".join(text_parts).strip(), tool_calls=calls, stop_reason=stop,
                           usage=usage, provider_payload=content)

    # -- live check ----------------------------------------------------------------------
    def check(self, timeout: float = 10.0) -> dict[str, Any]:
        """Verify the key and that the model exists for this key. Does not generate content."""
        client = self._client(timeout)
        try:
            model = client.models.get(model=self.model)
        except self._errors.APIError as exc:
            mapped = self._map_api_error(exc)  # the server answered, so it is reachable
            return {"reachable": True, "model_available": False, "error_kind": mapped.kind,
                    "detail": mapped.message}
        except (self._httpx.TimeoutException, self._httpx.TransportError):
            return {"reachable": False, "model_available": False, "error_kind": "connection",
                    "detail": "cannot reach the Gemini API"}
        actions = list(getattr(model, "supported_actions", None) or [])
        generates = not actions or "generateContent" in actions
        return {
            "reachable": True,
            "model_available": generates,
            "tool_calling": "unknown",
            "detail": (f"Model '{self.model}' is available to this key" + ("" if generates else
                       " but does not support generateContent") + ". Gemini does not report function-calling "
                       "support in model metadata; it is confirmed on the first real tool call."),
            "input_token_limit": getattr(model, "input_token_limit", None),
            "output_token_limit": getattr(model, "output_token_limit", None),
        }
