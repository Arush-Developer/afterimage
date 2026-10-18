"""Ollama provider against a mocked local Ollama server (real HTTP, no Ollama install)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from afterimage.config import load_settings
from afterimage.db import Database
from afterimage.gateway import ToolGateway
from afterimage.llm_agent import TOOL_SPECS, LLMAgent
from afterimage.main import create_app
from afterimage.policy import BASELINE_POLICY, PolicyEngine
from afterimage.providers import (OllamaProvider, ProviderConfigError, ProviderUnavailableError, Turn,
                                   check_provider)
from afterimage.recorder import EventRecorder
from afterimage.workspace import create_workspace

from .mock_http import MockHTTPServer

TAGS = (200, {"models": [{"name": "llama3.1:latest"}, {"name": "gemma:2b"}]})
VERSION = (200, {"version": "0.12.0"})
SHOW_TOOLS = (200, {"capabilities": ["completion", "tools"]})


def ollama_server(show=SHOW_TOOLS, *chat):
    srv = MockHTTPServer().route("GET", r"/api/version$", VERSION).route("GET", r"/api/tags$", TAGS) \
        .route("POST", r"/api/show$", show)
    if chat:
        srv.route("POST", r"/api/chat$", *chat)
    return srv


def chat_tool(name, args):
    return 200, {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name,
                 "arguments": args}}]}, "done": True, "prompt_eval_count": 20, "eval_count": 4}


def chat_text(text):
    return 200, {"message": {"role": "assistant", "content": text}, "done": True, "done_reason": "stop"}


def complete(p, turns=None):
    return p.complete(system="s", turns=turns or [Turn("user", text="go")], tools=TOOL_SPECS, max_tokens=500,
                      timeout=5)


def test_check_reports_tool_support():
    with ollama_server() as srv:
        info = OllamaProvider("llama3.1", host=srv.url).check()
    assert info == {"reachable": True, "model_available": True, "tool_calling": "supported",
                    "ollama_version": "0.12.0", "detail": info["detail"]}


def test_check_and_run_refuse_models_without_tool_calling():
    with ollama_server((200, {"capabilities": ["completion"]})) as srv:
        p = OllamaProvider("gemma:2b", host=srv.url)
        assert p.check()["tool_calling"] == "unsupported"
        with pytest.raises(ProviderConfigError) as exc:
            complete(p)
        assert exc.value.kind == "tools_unsupported"
        assert not srv.calls(r"/api/chat")  # never pretended: no chat request was made


def test_unknown_capability_then_runtime_tools_error_is_reported():
    with ollama_server((200, {"modelfile": "..."}),  # older Ollama: no capabilities field
                       (400, {"error": "registry.ollama.ai/library/llama3.1:latest does not support tools"})) as srv:
        p = OllamaProvider("llama3.1", host=srv.url)
        assert p.check()["tool_calling"] == "unknown"
        with pytest.raises(ProviderConfigError) as exc:
            complete(p)
    assert exc.value.kind == "tools_unsupported"


def test_missing_model_is_a_clear_error():
    with ollama_server() as srv:
        info = OllamaProvider("mistral", host=srv.url).check()
        with pytest.raises(ProviderConfigError) as exc:
            complete(OllamaProvider("mistral", host=srv.url))
    assert info["reachable"] and not info["model_available"] and info["error_kind"] == "model_unavailable"
    assert "ollama pull mistral" in exc.value.message and "llama3.1:latest" in exc.value.message


def test_not_running_is_a_clear_error():
    info = OllamaProvider("llama3.1", host="http://127.0.0.1:9").check()
    assert info["reachable"] is False and "ollama serve" in info["detail"]
    with pytest.raises(ProviderUnavailableError) as exc:
        complete(OllamaProvider("llama3.1", host="http://127.0.0.1:9"))
    assert exc.value.kind == "connection"


def test_tool_roundtrip_sends_tool_name_and_parses_calls():
    with ollama_server(SHOW_TOOLS, chat_tool("read_file", {"path": "README.md"}), chat_text("ok")) as srv:
        p = OllamaProvider("llama3.1", host=srv.url)
        first = complete(p)
        assert first.tool_calls[0].name == "read_file" and first.tool_calls[0].arguments == {"path": "README.md"}
        complete(p, [Turn("user", text="go"), Turn("assistant", tool_calls=first.tool_calls),
                     Turn("tool_results", results=[{"id": first.tool_calls[0].id, "content": "# Orbit",
                                                    "is_error": False}])])
    messages = srv.calls(r"/api/chat")[1]["body"]["messages"]
    assert messages[-1] == {"role": "tool", "content": "# Orbit", "tool_name": "read_file"}
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert len(srv.calls(r"/api/show")) == 1  # capability check cached per provider


def test_malformed_arguments_are_flagged():
    with ollama_server(SHOW_TOOLS, chat_tool("read_file", "{not json")) as srv:
        call = complete(OllamaProvider("llama3.1", host=srv.url)).tool_calls[0]
    assert call.parse_error == "invalid JSON" and call.arguments == {}


@pytest.fixture
def gateway(tmp_path):
    db = Database(tmp_path / "t.db")
    db.execute("INSERT INTO runs (run_id, scenario, kind, status, policy_version, workspace_path, started_at, "
               "agent_kind, enforcement) VALUES ('run_0000000000000001','llm','scenario','running',1,'x','now','llm','protected')")
    ws = create_workspace(tmp_path / "ws", "run_0000000000000001")
    yield ToolGateway(db, EventRecorder(db), ws, PolicyEngine(BASELINE_POLICY, 1), "run_0000000000000001"), db, ws
    db.close()


def test_ollama_agent_is_enforced_by_the_gateway(gateway):
    gw, db, ws = gateway
    with ollama_server(SHOW_TOOLS, chat_tool("read_file", {"path": "secret.txt"}),
                       chat_tool("read_file", "{broken"), chat_text("Done.")) as srv:
        LLMAgent(gw, OllamaProvider("llama3.1", host=srv.url), "summarise", max_steps=5).run()
    assert db.query_one("SELECT allowed, rule_id FROM policy_decisions WHERE resource_id = 'secret.txt'") == \
        {"allowed": 0, "rule_id": "POL-DENY-SECRET-FILE"}
    rejected = db.query_one("SELECT summary FROM events WHERE event_type = 'tool_call_rejected'")
    assert "not valid JSON" in rejected["summary"]
    tool_msgs = [m for m in srv.calls(r"/api/chat")[1]["body"]["messages"] if m["role"] == "tool"]
    assert "Access denied" in tool_msgs[0]["content"] and ws.canary not in str(tool_msgs)


def test_api_check_and_local_label(tmp_path):
    with ollama_server() as srv:
        settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_OLLAMA_HOST": srv.url})
        app = create_app(settings)
        with TestClient(app) as client:
            check = client.get("/api/providers/ollama/check?model=llama3.1").json()
            status = next(p for p in client.get("/api/providers").json()["providers"] if p["provider"] == "ollama")
        app.state.ctx.close()
    assert check["tool_calling"] == "supported" and check["model_available"]
    assert status["configured"] is True and status["local"] is True and status["billing"] == "local"


def test_remote_ollama_host_is_rejected_unless_explicitly_allowed(tmp_path):
    with pytest.raises(Exception, match="loopback"):
        load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_OLLAMA_HOST": "http://203.0.113.5:11434"})
    ok = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_OLLAMA_HOST": "http://203.0.113.5:11434",
                        "AFTERIMAGE_OLLAMA_ALLOW_REMOTE": "1"})
    assert ok.ollama_allow_remote is True


def test_per_provider_model_settings_do_not_leak(tmp_path):
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path), "AFTERIMAGE_LLM_PROVIDER": "anthropic",
                              "AFTERIMAGE_LLM_MODEL": "claude-opus-5-5", "AFTERIMAGE_OLLAMA_MODEL": "qwen2.5"})
    result = check_provider("ollama", None, settings)  # nothing listens; we only care about the model name
    assert result["model"] == "qwen2.5"
    assert check_provider("simulated", None, settings)["model"] == "simulated-agent"
