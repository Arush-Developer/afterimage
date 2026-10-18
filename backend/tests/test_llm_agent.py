"""LLM agent routed through the gateway: enforcement before execution, redaction,
invalid tool-call handling, provider failures, and investigation of real LLM runs."""

from __future__ import annotations

import pytest

from afterimage.db import Database
from afterimage.gateway import ToolGateway
from afterimage.llm_agent import LLMAgent
from afterimage.policy import BASELINE_POLICY, PolicyEngine, allow_all_engine
from afterimage.providers import LLMResponse, ToolCall, TokenUsage
from afterimage.providers.mock_provider import ScriptedProvider
from afterimage.recorder import EventRecorder
from afterimage.workspace import create_workspace


@pytest.fixture
def harness(tmp_path):
    db = Database(tmp_path / "t.db")
    recorder = EventRecorder(db)
    db.execute("INSERT INTO runs (run_id, scenario, kind, status, policy_version, workspace_path, started_at, "
               "agent_kind, enforcement) VALUES ('run_0000000000000001','llm','scenario','running',1,'x','now','llm','protected')")
    ws = create_workspace(tmp_path / "ws", "run_0000000000000001")

    def build(engine, responses):
        gw = ToolGateway(db, recorder, ws, engine, "run_0000000000000001", max_read_bytes=65536)
        agent = LLMAgent(gw, ScriptedProvider(responses), "summarise the project", max_steps=8)
        return gw, agent

    yield build, db, ws
    db.close()


def _call(tool, **args):
    return LLMResponse(text="", tool_calls=[ToolCall(id=f"c_{tool}", name=tool, arguments=args)],
                       stop_reason="tool_use", usage=TokenUsage())


def _final(text):
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn", usage=TokenUsage())


def test_gateway_denies_restricted_read_before_execution(harness):
    build, db, ws = harness
    gw, agent = build(PolicyEngine(BASELINE_POLICY, 1),
                      [_call("read_file", path="secret.txt"), _final("I could not read the secret.")])
    outcome = agent.run()
    # the model's attempt was recorded and denied; no content reached the model
    decision = db.query_one("SELECT * FROM policy_decisions WHERE resource_id = 'secret.txt'")
    assert decision["allowed"] == 0 and decision["rule_id"] == "POL-DENY-SECRET-FILE"
    assert "secret.txt" in outcome.result.followed_instructions
    # the tool result fed back to the model carried no secret content
    assert ws.canary not in str(outcome.transcript)


def test_llm_traversal_attempt_is_rejected(harness):
    build, db, ws = harness
    gw, agent = build(PolicyEngine(BASELINE_POLICY, 1),
                      [_call("read_file", path="../host-credentials.txt"), _final("blocked")])
    agent.run()
    decision = db.query_one("SELECT * FROM policy_decisions WHERE action = 'read_file' ORDER BY timestamp DESC LIMIT 1")
    assert decision["allowed"] == 0 and decision["rule_id"] == "AI-BOUNDARY-001"


def test_invalid_tool_call_is_rejected_not_executed(harness):
    build, db, ws = harness
    # model proposes an unknown tool, then a malformed read, then finishes
    gw, agent = build(PolicyEngine(BASELINE_POLICY, 1), [
        LLMResponse("", [ToolCall("a", "exfiltrate", {"path": "secret.txt"})], "tool_use", TokenUsage()),
        LLMResponse("", [ToolCall("b", "read_file", {"wrong": "x"})], "tool_use", TokenUsage()),
        _final("done"),
    ])
    agent.run()
    rejected = db.query("SELECT * FROM events WHERE event_type = 'tool_call_rejected'")
    assert len(rejected) == 2
    # the unknown tool never produced a policy decision or tool execution
    assert db.query_one("SELECT * FROM policy_decisions WHERE action = 'exfiltrate'") is None


def test_baseline_returns_secret_but_it_is_never_persisted(harness):
    build, db, ws = harness
    # enforcement OFF: the read is allowed and the model receives the canary...
    gw, agent = build(allow_all_engine(0),
                      [_call("read_file", path="secret.txt"), _final("The token is in the file.")])
    outcome = agent.run()
    assert gw.exposure_event_ids, "an exposure event should be recorded in baseline"
    # ...but the canary is in no event, decision, or transcript
    dump = "\n".join(db._conn.iterdump())
    assert ws.canary not in dump
    assert ws.canary not in str(outcome.transcript)


def test_model_text_is_recorded_and_redacted(harness):
    build, db, ws = harness
    leak = f"The secret is {ws.canary}"
    gw, agent = build(allow_all_engine(0), [LLMResponse(leak, [], "end_turn", TokenUsage())])
    outcome = agent.run()
    note = db.query_one("SELECT * FROM events WHERE event_type = 'agent_note' ORDER BY seq DESC LIMIT 1")
    assert ws.canary not in note["summary"] and "[REDACTED" in note["summary"]
    assert outcome.result.summary and ws.canary not in outcome.result.summary


def test_provider_error_is_captured(harness):
    build, db, ws = harness

    def boom(step, turns):
        from afterimage.providers import ProviderUnavailableError
        raise ProviderUnavailableError("upstream down", kind="connection")

    gw = ToolGateway(db, EventRecorder(db), ws, allow_all_engine(0), "run_0000000000000001")
    agent = LLMAgent(gw, ScriptedProvider(boom), "task", max_steps=4)
    outcome = agent.run()
    assert outcome.provider_error and "upstream" in outcome.provider_error
    assert outcome.stop_reason == "provider_error:connection"
    assert not outcome.result.task_completed


def test_refusal_stops_the_run(harness):
    build, db, ws = harness

    def refuse(step, turns):
        from afterimage.providers import ProviderRefusal
        raise ProviderRefusal("declined", category="cyber")

    gw = ToolGateway(db, EventRecorder(db), ws, allow_all_engine(0), "run_0000000000000001")
    outcome = LLMAgent(gw, ScriptedProvider(refuse), "task", max_steps=4).run()
    assert outcome.stop_reason == "refusal"
    assert db.query_one("SELECT * FROM events WHERE json_extract(evidence_metadata,'$.kind') = 'refusal'")


def test_max_steps_is_bounded(harness):
    build, db, ws = harness
    # a provider that always asks to list files would loop forever without the bound
    gw, agent = build(allow_all_engine(0), lambda step, turns: _call("list_files", path="."))
    outcome = agent.run()
    assert outcome.steps == 8 and outcome.stop_reason == "max_steps"
