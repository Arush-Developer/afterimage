"""Gemini provider: the real `google-genai` SDK path against a local mock HTTP server.

No real network or API key is used: a local HTTP server returns canned generateContent
responses and the SDK is pointed at it via base_url. Covers function-call round trips
(including thought-signature passthrough), refusals, malformed calls, typed HTTP errors,
timeouts, missing credentials, key redaction, and a full LLM run through the gateway.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from afterimage.config import load_settings
from afterimage.main import create_app
from afterimage.providers import (GeminiProvider, ProviderConfigError, ProviderError, ProviderRefusal,
                                   ProviderUnavailableError, ToolSpec, Turn, build_provider, provider_status)
from afterimage.providers.gemini_provider import sanitize

FAKE_KEY = "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKE0000"
SIGNATURE = base64.b64encode(b"opaque-thought-signature").decode()


class _Handler(BaseHTTPRequestHandler):
    responses: list = []
    received: list = []
    paths: list = []
    index = 0
    delay = 0.0

    def log_message(self, *args):
        pass

    def do_POST(self):
        if type(self).delay:
            time.sleep(type(self).delay)
        length = int(self.headers.get("Content-Length", "0"))
        type(self).received.append(json.loads(self.rfile.read(length)))
        type(self).paths.append(self.path)
        status, payload = type(self).responses[min(type(self).index, len(type(self).responses) - 1)]
        type(self).index += 1
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MockGeminiServer:
    def __init__(self, responses, delay=0.0):
        _Handler.responses, _Handler.received, _Handler.paths = responses, [], []
        _Handler.index, _Handler.delay = 0, delay
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __exit__(self, *a):
        self.server.shutdown()


def _resp(parts, finish="STOP"):
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 5, "thoughtsTokenCount": 3}}


def _fc(name, args, signature=None):
    part = {"functionCall": {"name": name, "args": args}}
    if signature:
        part["thoughtSignature"] = signature
    return part


TOOLS = [ToolSpec("read_file", "read a file", {"type": "object", "properties": {"path": {"type": "string"}},
                                               "required": ["path"], "additionalProperties": False})]


def _provider(url):
    return GeminiProvider(model="gemini-2.5-flash", base_url=url, api_key=FAKE_KEY)


def test_gemini_function_call_roundtrip_preserves_signature():
    with MockGeminiServer([(200, _resp([_fc("read_file", {"path": "README.md"}, SIGNATURE)])),
                           (200, _resp([{"text": "The project is a demo."}]))]) as url:
        provider = _provider(url)
        first = provider.complete(system="sys", turns=[Turn("user", text="summarise")], tools=TOOLS,
                                  max_tokens=1000, timeout=10)
        assert first.stop_reason == "tool_use"
        assert first.tool_calls[0].name == "read_file" and first.tool_calls[0].arguments == {"path": "README.md"}
        assert first.usage.input_tokens == 11 and first.usage.output_tokens == 8
        turns = [Turn("user", text="summarise"), Turn("assistant", tool_calls=first.tool_calls),
                 Turn("tool_results", results=[{"id": first.tool_calls[0].id, "content": "# Demo",
                                                "is_error": False}])]
        second = provider.complete(system="sys", turns=turns, tools=TOOLS, max_tokens=1000, timeout=10)
        assert second.stop_reason == "end_turn" and "demo" in second.text.lower()
    assert _Handler.paths[0].endswith("/models/gemini-2.5-flash:generateContent")
    first_req, last = _Handler.received[0], _Handler.received[-1]
    assert first_req["systemInstruction"]["parts"][0]["text"] == "sys"
    decl = first_req["tools"][0]["functionDeclarations"][0]
    schema = decl.get("parametersJsonSchema") or decl.get("parameters_json_schema")  # SDK wire spelling
    assert decl["name"] == "read_file" and schema["required"] == ["path"]
    model_turn, result_turn = last["contents"][1], last["contents"][2]
    assert model_turn["role"] == "model" and model_turn["parts"][0]["thoughtSignature"] == SIGNATURE
    assert result_turn["parts"][0]["functionResponse"] == {"name": "read_file", "response": {"output": "# Demo"}}


def test_gemini_error_result_is_marked():
    with MockGeminiServer([(200, _resp([{"text": "ok"}]))]) as url:
        turns = [Turn("user", text="x"),
                 Turn("assistant", tool_calls=[__import__("afterimage.providers", fromlist=["ToolCall"])
                                               .ToolCall("c1", "read_file", {"path": "secret.txt"})]),
                 Turn("tool_results", results=[{"id": "c1", "content": "Access denied", "is_error": True}])]
        _provider(url).complete(system="s", turns=turns, tools=TOOLS, max_tokens=10, timeout=10)
    assert _Handler.received[0]["contents"][2]["parts"][0]["functionResponse"]["response"] == {"error": "Access denied"}


@pytest.mark.parametrize("finish", ["SAFETY", "PROHIBITED_CONTENT"])
def test_gemini_safety_finish_is_refusal(finish):
    with MockGeminiServer([(200, _resp([], finish=finish))]) as url:
        with pytest.raises(ProviderRefusal) as exc:
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
    assert exc.value.category == finish


def test_gemini_blocked_prompt_is_refusal():
    with MockGeminiServer([(200, {"promptFeedback": {"blockReason": "SAFETY"}})]) as url:
        with pytest.raises(ProviderRefusal):
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)


def test_gemini_malformed_function_call_is_bad_response():
    with MockGeminiServer([(200, _resp([], finish="MALFORMED_FUNCTION_CALL"))]) as url:
        with pytest.raises(ProviderError) as exc:
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
    assert exc.value.kind == "bad_response"


@pytest.mark.parametrize("status,error_type,kind", [
    (401, ProviderConfigError, "config_error"),
    (403, ProviderConfigError, "config_error"),
    (404, ProviderConfigError, "config_error"),
    (429, ProviderUnavailableError, "rate_limit"),
    (400, ProviderError, "bad_request"),
    (500, ProviderUnavailableError, "api_error"),
])
def test_gemini_http_errors_map_to_typed_failures(status, error_type, kind):
    err = {"error": {"code": status, "message": f"boom key={FAKE_KEY}", "status": "ERR"}}
    with MockGeminiServer([(status, err)] * 3) as url:
        with pytest.raises(error_type) as exc:
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
    assert exc.value.kind == kind
    assert FAKE_KEY not in exc.value.message
    assert len(_Handler.received) == 1  # never silently retried


def test_gemini_invalid_key_400_is_config_error():
    err = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                     "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}
    with MockGeminiServer([(400, err)]) as url:
        with pytest.raises(ProviderConfigError):
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)


def test_gemini_timeout_is_unavailable():
    with MockGeminiServer([(200, _resp([{"text": "late"}]))], delay=1.5) as url:
        with pytest.raises(ProviderUnavailableError) as exc:
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=0.3)
    assert exc.value.kind == "timeout"


def test_gemini_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    with pytest.raises(ProviderConfigError) as exc:
        build_provider("gemini", None, settings)
    assert exc.value.kind == "missing_credentials"
    status = {p["provider"]: p for p in provider_status(settings, probe_ollama=False)}
    assert status["gemini"]["configured"] is False and status["gemini"]["real"] is True


def test_gemini_status_never_exposes_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    status = {p["provider"]: p for p in provider_status(settings, probe_ollama=False)}
    assert status["gemini"]["configured"] is True
    assert FAKE_KEY not in json.dumps(status)
    assert FAKE_KEY not in sanitize(f"error for {FAKE_KEY}") and "AQ.abcdefghijklmnopqrstuvwxyz" not in \
        sanitize("token AQ.abcdefghijklmnopqrstuvwxyz0123")


def test_gemini_llm_run_through_gateway(tmp_path, monkeypatch):
    """A full API-level LLM run: the model's request for secret.txt is denied by the gateway
    and the denial (not the content) is what Gemini receives back."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    responses = [(200, _resp([_fc("read_file", {"path": "secret.txt"}, SIGNATURE)])),
                 (200, _resp([_fc("read_file", {"path": "README.md"})])),
                 (200, _resp([{"text": "Done."}]))]
    with MockGeminiServer(responses) as url:
        settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path / "data"),
                                  "AFTERIMAGE_GEMINI_BASE_URL": url})
        app = create_app(settings)
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            run = client.post("/api/runs/llm", json={"provider": "gemini", "enforcement": "protected"}).json()
            assert run["provider"] == "gemini" and run["model"] == "gemini-3.8-flash" and run["provider_real"] is True
            assert run["sensitive_exposed"] is False
            decisions = client.get(f"/api/runs/{run['run_id']}/events").json()
        canary = (settings.workspaces_dir / run["run_id"] / "secret.txt").read_text().splitlines()[1].split("=", 1)[1]
        app.state.ctx.close()
    sent_back = json.dumps(_Handler.received[1]["contents"][-1])
    assert "Access denied by security policy" in sent_back and canary not in sent_back
    assert canary not in json.dumps(_Handler.received)
    assert "POL-DENY-SECRET-FILE" in json.dumps(decisions)


def test_gemini_pacing_spaces_requests(monkeypatch):
    """Optional pacing (AFTERIMAGE_GEMINI_MIN_INTERVAL_S) waits between requests; it never retries."""
    import afterimage.providers.gemini_provider as gp
    monkeypatch.setattr(gp, "_last_request_at", 0.0)
    with MockGeminiServer([(200, _resp([{"text": "a"}]))]) as url:
        provider = GeminiProvider(model="gemini-3.8-flash", base_url=url, api_key=FAKE_KEY, min_interval_s=0.4)
        start = time.monotonic()
        for _ in range(3):
            provider.complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
        assert time.monotonic() - start >= 0.8
    assert len(_Handler.received) == 3


def test_gemini_min_interval_setting(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_GEMINI_MIN_INTERVAL_S": "13"})
    assert settings.gemini_min_interval_s == 13
    with pytest.raises(Exception):
        load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_GEMINI_MIN_INTERVAL_S": "-1"})
