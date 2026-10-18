"""Provider abstraction: the real Anthropic SDK path against a mock HTTP server,
structured tool-call validation, and error/timeout/credential handling.

No real network or API key is used: a local HTTP server returns canned Messages-API
responses, and the anthropic SDK is pointed at it via base_url.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from afterimage.config import load_settings
from afterimage.llm_agent import validate_tool_call
from afterimage.providers import (AnthropicProvider, ProviderConfigError, ProviderError,
                                   ProviderRefusal, ProviderUnavailableError, ToolCall, ToolSpec, Turn,
                                   build_provider, provider_status)


class _Handler(BaseHTTPRequestHandler):
    responses: list = []
    received: list = []
    index = 0

    def log_message(self, *args):  # silence
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).received.append(json.loads(body))
        status, payload = type(self).responses[min(type(self).index, len(type(self).responses) - 1)]
        type(self).index += 1
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if status == 429:
            self.send_header("retry-after", "1")
        self.end_headers()
        self.wfile.write(data)


class MockAnthropicServer:
    def __init__(self, responses):
        _Handler.responses = responses
        _Handler.received = []
        _Handler.index = 0
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __exit__(self, *a):
        self.server.shutdown()

    @property
    def received(self):
        return _Handler.received


def _message(content, stop_reason="end_turn", stop_details=None):
    msg = {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }
    if stop_details:
        msg["stop_details"] = stop_details
    return msg


TOOLS = [ToolSpec("read_file", "read a file", {"type": "object", "properties": {"path": {"type": "string"}},
                                               "required": ["path"], "additionalProperties": False})]


def _provider(base_url):
    return AnthropicProvider(model="claude-opus-5-5", base_url=base_url, api_key="sk-ant-test", effort=None)


def test_anthropic_tool_call_roundtrip():
    tool_use = _message([{"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "README.md"}}],
                        stop_reason="tool_use")
    final = _message([{"type": "text", "text": "The project is a demo."}], stop_reason="end_turn")
    with MockAnthropicServer([(200, tool_use), (200, final)]) as url:
        provider = _provider(url)
        first = provider.complete(system="s", turns=[Turn("user", text="summarise")], tools=TOOLS,
                                  max_tokens=1000, timeout=10)
        assert first.stop_reason == "tool_use"
        assert len(first.tool_calls) == 1 and first.tool_calls[0].name == "read_file"
        assert first.tool_calls[0].arguments == {"path": "README.md"}
        assert first.usage.input_tokens == 12
        # Feed a tool result back; the neutral turns reconstruct correct wire messages.
        turns = [Turn("user", text="summarise"),
                 Turn("assistant", tool_calls=first.tool_calls),
                 Turn("tool_results", results=[{"id": "toolu_1", "content": "# Demo", "is_error": False}])]
        second = provider.complete(system="s", turns=turns, tools=TOOLS, max_tokens=1000, timeout=10)
        assert second.stop_reason == "end_turn" and "demo" in second.text.lower()
    # the second request carried the tool_result referencing the same id, plus strict tools
    last = _Handler.received[-1]
    assert last["tools"][0]["strict"] is True
    assert any(block.get("type") == "tool_result" and block["tool_use_id"] == "toolu_1"
               for m in last["messages"] for block in (m["content"] if isinstance(m["content"], list) else []))


def test_anthropic_refusal_is_raised():
    refusal = _message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"})
    with MockAnthropicServer([(200, refusal)]) as url:
        with pytest.raises(ProviderRefusal) as exc:
            _provider(url).complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
        assert exc.value.category == "cyber"


@pytest.mark.parametrize("status,error_type,kind", [
    (401, ProviderConfigError, "config_error"),
    (403, ProviderConfigError, "config_error"),
    (404, ProviderConfigError, "config_error"),
    (429, ProviderUnavailableError, "rate_limit"),
    (500, ProviderUnavailableError, "api_error"),
])
def test_anthropic_http_errors_map_to_typed_failures(status, error_type, kind):
    err = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    with MockAnthropicServer([(status, err)] * 5) as url:
        provider = AnthropicProvider(model="claude-opus-5-5", base_url=url, api_key="sk-ant-test",
                                     max_retries=0, effort=None)
        with pytest.raises(error_type) as exc:
            provider.complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=10)
        assert exc.value.kind == kind


def test_anthropic_timeout_is_unavailable():
    slow = _message([{"type": "text", "text": "late"}])

    class SlowHandler(_Handler):
        def do_POST(self):
            time.sleep(1.5)
            super().do_POST()

    server = HTTPServer(("127.0.0.1", 0), SlowHandler)
    SlowHandler.responses = [(200, slow)]
    SlowHandler.index = 0
    SlowHandler.received = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        provider = AnthropicProvider(model="claude-opus-5-5", base_url=url, api_key="sk-ant-test",
                                     max_retries=0, effort=None)
        with pytest.raises(ProviderUnavailableError) as exc:
            provider.complete(system="s", turns=[Turn("user", text="x")], tools=TOOLS, max_tokens=10, timeout=0.3)
        assert exc.value.kind == "timeout"
    finally:
        server.shutdown()


def test_missing_credentials_is_config_error(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "empty"))
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    with pytest.raises(ProviderConfigError) as exc:
        build_provider("anthropic", "claude-opus-5-5", settings)
    assert exc.value.kind == "missing_credentials"


def test_unknown_provider_and_invalid_model(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    with pytest.raises(ProviderConfigError):
        build_provider("gpt", "x", settings)
    with pytest.raises(ProviderConfigError):
        build_provider("simulated", "bad model!", settings)


def test_simulated_provider_builds_without_credentials(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    provider = build_provider("simulated", None, settings)
    assert provider.is_real is False and provider.name == "simulated"


def test_provider_status_reports_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "none"))
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    status = {p["provider"]: p for p in provider_status(settings, probe_ollama=False)}
    assert status["anthropic"]["configured"] is False
    assert status["simulated"]["configured"] is True and status["simulated"]["real"] is False
    # Status never contains key material.
    assert "sk-ant" not in json.dumps(status)


@pytest.mark.parametrize("call,expected_ok", [
    (ToolCall("1", "read_file", {"path": "README.md"}), True),
    (ToolCall("1", "write_file", {"path": "out/x.md", "content": "hi"}), True),
    (ToolCall("1", "read_file", {}), False),              # missing required
    (ToolCall("1", "read_file", {"path": 5}), False),     # wrong type
    (ToolCall("1", "read_file", {"path": "a", "extra": "b"}), False),  # unexpected arg
    (ToolCall("1", "delete_all", {"path": "a"}), False),  # unknown tool
    (ToolCall("1", "read_file", {"path": "x" * 300}), False),  # too long
])
def test_tool_call_validation(call, expected_ok):
    assert (validate_tool_call(call) is None) is expected_ok
