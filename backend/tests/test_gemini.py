"""Gemini provider: the real google-genai SDK against a local mock of the Gemini API.

No network or real key is used. The SDK is pointed at a local server via
AFTERIMAGE_GEMINI_BASE_URL / base_url, and GEMINI_API_KEY is set to a fake value.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from afterimage.config import load_settings
from afterimage.db import Database
from afterimage.gateway import ToolGateway
from afterimage.llm_agent import TOOL_SPECS, LLMAgent
from afterimage.main import create_app
from afterimage.policy import BASELINE_POLICY, PolicyEngine
from afterimage.providers import (GeminiProvider, ProviderConfigError, ProviderRefusal, ProviderUnavailableError,
                                   ToolCall, Turn, build_provider)
from afterimage.recorder import EventRecorder
from afterimage.workspace import create_workspace

from .mock_http import MockHTTPServer

FAKE_KEY = "AIzaFAKE-test-key-0123456789"
GEN = r"/models/gemini-2\.5-flash:generateContent"


def fc(name, args, call_id=None, signature=None):
    part = {"functionCall": {"name": name, "args": args, **({"id": call_id} if call_id else {})}}
    if signature:
        part["thoughtSignature"] = signature
    return part


def resp(parts, finish="STOP", **extra):
    return 200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
                 "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 3}, **extra}


def err(code, status, message, details=None):
    return code, {"error": {"code": code, "status": status, "message": message, "details": details or []}}


QUOTA_DAY = err(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
     "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}])


def rate_minute(delay="0.05s"):
    return err(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted.", [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}])


@pytest.fixture(autouse=True)
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)


def provider(url, **kw):
    return GeminiProvider(model="gemini-2.5-flash", base_url=url, **kw)


def complete(p, turns=None, timeout=10):
    return p.complete(system="sys", turns=turns or [Turn("user", text="go")], tools=TOOL_SPECS,
                      max_tokens=1000, timeout=timeout)


# -- wire format / tool roundtrip ------------------------------------------------------

def test_tool_call_and_result_roundtrip_preserves_signature():
    with MockHTTPServer().route("POST", GEN, resp([fc("read_file", {"path": "README.md"}, "c1", "c2lnbmF0dXJl")]),
                                resp([{"text": "Summary done."}])) as srv:
        p = provider(srv.url)
        first = complete(p)
        assert first.stop_reason == "tool_use" and first.tool_calls[0].name == "read_file"
        assert first.tool_calls[0].arguments == {"path": "README.md"} and first.usage.input_tokens == 11
        turns = [Turn("user", text="go"),
                 Turn("assistant", tool_calls=first.tool_calls, provider_payload=first.provider_payload),
                 Turn("tool_results", results=[{"id": first.tool_calls[0].id, "content": "# Orbit", "is_error": False}])]
        second = complete(p, turns)
        assert second.stop_reason == "end_turn" and second.text == "Summary done."

    req1, req2 = (r for r in srv.calls(GEN))
    # credentials travel in a header, never the URL
    assert req1["headers"].get("x-goog-api-key") == FAKE_KEY and FAKE_KEY not in req1["path"]
    # tools declared as function declarations; automatic function calling not requested
    decls = req1["body"]["tools"][0]["functionDeclarations"]
    assert {d["name"] for d in decls} == {"list_files", "read_file", "write_file"}
    assert "systemInstruction" in req1["body"]
    contents = req2["body"]["contents"]
    model_turn = contents[1]
    assert model_turn["role"] == "model" and model_turn["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"
    fr = contents[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "read_file" and fr["id"] == "c1" and fr["response"] == {"output": "# Orbit"}


def test_error_results_are_sent_as_error_payloads():
    with MockHTTPServer().route("POST", GEN, resp([{"text": "ok"}])) as srv:
        p = provider(srv.url)
        call = ToolCall(id="x1", name="read_file", arguments={"path": "secret.txt"})
        complete(p, [Turn("user", text="go"), Turn("assistant", tool_calls=[call]),
                     Turn("tool_results", results=[{"id": "x1", "content": "Access denied", "is_error": True}])])
    fr = srv.calls(GEN)[0]["body"]["contents"][2]["parts"][0]["functionResponse"]
    assert fr["response"] == {"error": "Access denied"} and fr["name"] == "read_file"
    assert "id" not in fr  # our synthetic id is not sent as a Gemini id


# -- agent + gateway enforcement ---------------------------------------------------------

@pytest.fixture
def gateway(tmp_path):
    db = Database(tmp_path / "t.db")
    db.execute("INSERT INTO runs (run_id, scenario, kind, status, policy_version, workspace_path, started_at, "
               "agent_kind, enforcement) VALUES ('run_0000000000000001','llm','scenario','running',1,'x','now','llm','protected')")
    ws = create_workspace(tmp_path / "ws", "run_0000000000000001")
    gw = ToolGateway(db, EventRecorder(db), ws, PolicyEngine(BASELINE_POLICY, 1), "run_0000000000000001")
    yield gw, db, ws
    db.close()


def test_gemini_agent_cannot_bypass_the_gateway(gateway):
    gw, db, ws = gateway
    with MockHTTPServer().route("POST", GEN,
                                resp([fc("read_file", {"path": "secret.txt"}, "a1")]),
                                resp([fc("delete_everything", {"path": "README.md"}, "a2")]),
                                resp([fc("read_file", {"path": 42}, "a3")]),
                                resp([{"text": "I could not access it."}])) as srv:
        outcome = LLMAgent(gw, provider(srv.url), "summarise", max_steps=6).run()
    decision = db.query_one("SELECT * FROM policy_decisions WHERE resource_id = 'secret.txt'")
    assert decision["allowed"] == 0 and decision["rule_id"] == "POL-DENY-SECRET-FILE"
    rejected = db.query("SELECT * FROM events WHERE event_type = 'tool_call_rejected'")
    assert len(rejected) == 2  # unknown tool + wrong argument type: never executed
    assert db.query_one("SELECT * FROM policy_decisions WHERE action = 'delete_everything'") is None
    # the denial (no content) is what went back to Gemini
    second = srv.calls(GEN)[1]["body"]["contents"]
    sent = json.dumps(second)
    assert "Access denied by security policy" in sent and ws.canary not in sent
    assert outcome.result.summary == "I could not access it."


def test_malformed_function_call_is_rejected_and_retried(gateway):
    gw, db, ws = gateway
    with MockHTTPServer().route("POST", GEN,
                                resp([], finish="MALFORMED_FUNCTION_CALL"),
                                resp([{"text": "Done."}])) as srv:
        outcome = LLMAgent(gw, provider(srv.url), "summarise", max_steps=4).run()
    assert db.query_one("SELECT * FROM events WHERE event_type = 'tool_call_rejected'")
    retry = srv.calls(GEN)[1]["body"]["contents"]
    assert "could not be parsed" in json.dumps(retry)
    assert outcome.stop_reason == "end_turn" and not db.query("SELECT * FROM policy_decisions")


# -- errors ---------------------------------------------------------------------------

@pytest.mark.parametrize("response,error_type,kind", [
    (err(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
         [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]),
     ProviderConfigError, "invalid_credentials"),
    (err(403, "PERMISSION_DENIED", "Permission denied."), ProviderConfigError, "invalid_credentials"),
    (err(404, "NOT_FOUND", "models/gemini-2.5-flash is not found"), ProviderConfigError, "model_unavailable"),
    (err(400, "FAILED_PRECONDITION", "User location is not supported for the API use."),
     ProviderConfigError, "account_unsupported"),
    (QUOTA_DAY, ProviderUnavailableError, "quota_exhausted"),
    (err(500, "INTERNAL", "boom"), ProviderUnavailableError, "api_error"),
    (err(400, "INVALID_ARGUMENT", "bad request field"), Exception, "bad_request"),
])
def test_api_errors_map_to_typed_failures(response, error_type, kind):
    with MockHTTPServer().route("POST", GEN, response) as srv:
        with pytest.raises(error_type) as exc:
            complete(provider(srv.url))
    assert exc.value.kind == kind
    assert FAKE_KEY not in str(exc.value.message)


def test_quota_exhaustion_is_not_retried():
    with MockHTTPServer().route("POST", GEN, QUOTA_DAY) as srv:
        with pytest.raises(ProviderUnavailableError) as exc:
            complete(provider(srv.url, rate_limit_retries=3))
    assert exc.value.kind == "quota_exhausted" and exc.value.retry_after_s == 40.0
    assert len(srv.calls(GEN)) == 1
    assert "quota" in exc.value.message.lower() and "billing" in exc.value.message.lower()


def test_rate_limit_is_retried_honouring_retry_delay_then_succeeds():
    with MockHTTPServer().route("POST", GEN, rate_minute(), resp([{"text": "ok"}])) as srv:
        result = complete(provider(srv.url, rate_limit_retries=2))
    assert result.text == "ok" and len(srv.calls(GEN)) == 2


def test_rate_limit_retries_are_bounded():
    with MockHTTPServer().route("POST", GEN, rate_minute()) as srv:
        with pytest.raises(ProviderUnavailableError) as exc:
            complete(provider(srv.url, rate_limit_retries=2))
    assert exc.value.kind == "rate_limit" and len(srv.calls(GEN)) == 3


def test_rate_limit_with_long_delay_is_not_waited_out():
    with MockHTTPServer().route("POST", GEN, rate_minute("90s")) as srv:
        with pytest.raises(ProviderUnavailableError) as exc:
            complete(provider(srv.url, rate_limit_retries=2, max_retry_wait_s=30))
    assert exc.value.kind == "rate_limit" and len(srv.calls(GEN)) == 1


def test_timeout_and_connection_errors():
    with MockHTTPServer().route("POST", GEN, resp([{"text": "late"}])) as srv:
        srv.delay = 1.5
        with pytest.raises(ProviderUnavailableError) as exc:
            complete(provider(srv.url), timeout=0.3)
        assert exc.value.kind == "timeout"
    with pytest.raises(ProviderUnavailableError) as exc:
        complete(provider("http://127.0.0.1:9"))  # nothing listens on port 9
    assert exc.value.kind == "connection"


@pytest.mark.parametrize("response,category", [
    ((200, {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}), "SAFETY"),
    (resp([], finish="PROHIBITED_CONTENT"), "PROHIBITED_CONTENT"),
])
def test_safety_blocks_raise_refusal(response, category):
    with MockHTTPServer().route("POST", GEN, response) as srv:
        with pytest.raises(ProviderRefusal) as exc:
            complete(provider(srv.url))
    assert exc.value.category == category


# -- credentials / no fallback ------------------------------------------------------------

def test_missing_key_is_a_config_error_and_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-other-key")    # must NOT be used implicitly
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-present")  # a paid provider IS configured...
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path)})
    with pytest.raises(ProviderConfigError) as exc:
        build_provider("gemini", None, settings)  # ...but is never substituted
    assert exc.value.kind == "missing_credentials" and "GEMINI_API_KEY" in exc.value.message


def test_check_reports_model_availability_without_generating():
    model_meta = {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"],
                  "inputTokenLimit": 1048576, "outputTokenLimit": 65536}
    with MockHTTPServer().route("GET", r"/models/gemini-2\.5-flash$", (200, model_meta)) \
            .route("GET", r"/models/nope$", err(404, "NOT_FOUND", "not found")) as srv:
        ok = provider(srv.url).check()
        missing = GeminiProvider(model="nope", base_url=srv.url).check()
    assert ok["reachable"] and ok["model_available"] and ok["tool_calling"] == "unknown"
    assert missing["reachable"] and not missing["model_available"] and missing["error_kind"] == "model_unavailable"
    assert not srv.calls("generateContent")


# -- API level --------------------------------------------------------------------------

@pytest.fixture
def gemini_api(tmp_path):
    srv = MockHTTPServer()
    srv.__enter__()
    settings = load_settings({"AFTERIMAGE_DATA_DIR": str(tmp_path / "data"), "AFTERIMAGE_GEMINI_BASE_URL": srv.url,
                              "AFTERIMAGE_GEMINI_RATE_LIMIT_RETRIES": "0"})
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, srv, app.state.ctx
    app.state.ctx.close()
    srv.__exit__()


def test_api_gemini_run_is_labelled_and_enforced(gemini_api):
    client, srv, ctx = gemini_api
    srv.route("POST", GEN, resp([fc("read_file", {"path": "secret.txt"}, "k1")]), resp([{"text": "Blocked."}]))
    run = client.post("/api/runs/llm", json={"provider": "gemini", "enforcement": "protected"}).json()
    assert run["provider"] == "gemini" and run["model"] == "gemini-2.5-flash" and run["provider_real"] is True
    assert run["sensitive_exposed"] is False and run["incident_id"]


def test_api_quota_exhaustion_is_reported_and_experiment_stops_early(gemini_api):
    client, srv, ctx = gemini_api
    srv.route("POST", GEN, QUOTA_DAY)
    exp = client.post("/api/experiments", json={"provider": "gemini", "trials": 3}).json()
    report = exp["report"]
    assert exp["status"] == "inconclusive" and report["stopped_early"] == "quota_exhausted"
    assert report["baseline"]["errored_trials"] == 1 and report["baseline"]["trials"] == 1
    assert "quota" in report["headline"].lower()
    assert len(srv.calls(GEN)) == 1  # no requests wasted after quota exhaustion


def test_api_quota_error_on_explain_returns_429(gemini_api):
    client, srv, ctx = gemini_api
    srv.route("POST", GEN, QUOTA_DAY)
    incident = client.post("/api/runs/attack").json()["incident_id"]
    r = client.post(f"/api/incidents/{incident}/explain", json={"provider": "gemini"})
    assert r.status_code == 429 and r.json()["code"] == "provider_quota_exhausted"
    assert r.json()["retry_after_s"] == 40.0 and r.headers["retry-after"] == "41"


def test_api_check_endpoint_and_key_never_exposed(gemini_api, caplog):
    client, srv, ctx = gemini_api
    srv.route("GET", r"/models/gemini-2\.5-flash$", (200, {"name": "models/gemini-2.5-flash",
                                                         "supportedGenerationMethods": ["generateContent"]}))
    srv.route("POST", GEN, resp([fc("list_files", {"path": "."}, "z")]), resp([{"text": "done"}]))
    with caplog.at_level(logging.DEBUG):
        check = client.get("/api/providers/gemini/check").json()
        assert check["configured"] and check["model_available"] and check["provider"] == "gemini"
        client.post("/api/experiments", json={"provider": "gemini", "trials": 1})
        texts = [client.get(p).text for p in ("/api/providers", "/api/settings", "/api/experiments", "/api/runs",
                                              "/api/events", "/api/dashboard")]
    status = next(p for p in client.get("/api/providers").json()["providers"] if p["provider"] == "gemini")
    assert status["configured"] is True and status["local"] is False
    for text in texts + [caplog.text, "\n".join(ctx.db._conn.iterdump())]:
        assert FAKE_KEY not in text
    assert client.get("/api/providers/openai/check").status_code == 422
