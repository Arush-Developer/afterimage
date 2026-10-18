"""AI-assisted incident explanation: grounding validation against persisted event IDs."""

from __future__ import annotations

import pytest

import afterimage.main as main_module
from afterimage.providers import LLMResponse, ToolCall, TokenUsage
from afterimage.providers.mock_provider import ScriptedProvider
from afterimage.recorder import EventRecorder


def _real_scripted(responses):
    provider = ScriptedProvider(responses, model="test-model")
    provider.is_real = True  # behave like a real provider for the explainer's gate
    return provider


@pytest.fixture
def incident(client):
    return client.post("/api/runs/attack").json()["incident_id"]


def test_explanation_keeps_grounded_claims_and_rejects_fabricated_ids(client, incident, monkeypatch):
    events = client.get(f"/api/incidents/{incident}/events").json()
    decision = next(e for e in events if e["event_type"] == "policy_decision" and e["outcome"] == "denied")
    trigger = next(e for e in events if e.get("evidence_role") == "trigger_input")
    answer = {
        "summary": "An injected instruction led to a denied read of secret.txt.",
        "observed": [
            {"statement": "The gateway denied the read of secret.txt.", "event_ids": [decision["event_id"]]},
            {"statement": "The secret was exfiltrated over HTTP.", "event_ids": ["evt_ffffffffffffffff"]},  # fabricated
            {"statement": "No citation at all.", "event_ids": []},
        ],
        "hypotheses": [
            {"statement": "The integration notes likely triggered the request.", "event_ids": [trigger["event_id"]]},
        ],
        "uncertainty": ["Model intent is not observable."],
    }
    provider = _real_scripted([LLMResponse("", [ToolCall("x", "submit_explanation", answer)], "tool_use", TokenUsage())])
    monkeypatch.setattr(main_module, "build_provider", lambda *a, **k: provider)

    r = client.post(f"/api/incidents/{incident}/explain", json={})
    assert r.status_code == 201, r.text
    data = r.json()
    assert [o["statement"] for o in data["observed"]] == ["The gateway denied the read of secret.txt."]
    assert len(data["hypotheses"]) == 1
    assert len(data["rejected_claims"]) == 2
    assert data["rejected_claims"][0]["unknown_event_ids"] == ["evt_ffffffffffffffff"]
    assert any("language model" in u for u in data["uncertainty"])
    # The model only ever saw persisted evidence records (with their event IDs).
    prompt = provider.calls[0][0].text
    assert decision["event_id"] in prompt
    # Appended to the audit log and retrievable.
    latest = client.get(f"/api/incidents/{incident}/explanation").json()["explanation"]
    assert latest["event_id"] == data["event_id"]
    assert client.get("/api/events/verify").json()["valid"] is True


def test_explanation_requires_a_real_provider(client, incident):
    r = client.post(f"/api/incidents/{incident}/explain", json={"provider": "simulated"})
    assert r.status_code == 400 and "real language model" in r.json()["detail"]


def test_explanation_without_structured_answer_is_an_error(client, incident, monkeypatch):
    provider = _real_scripted([LLMResponse("I think it was bad.", [], "end_turn", TokenUsage())])
    monkeypatch.setattr(main_module, "build_provider", lambda *a, **k: provider)
    r = client.post(f"/api/incidents/{incident}/explain", json={})
    assert r.status_code == 502 and r.json()["code"] == "provider_bad_response"
    assert client.get(f"/api/incidents/{incident}/explanation").json()["explanation"] is None


def test_recorder_scrubs_canary_pattern_even_without_sensitive_values(ctx):
    rec = EventRecorder(ctx.db)
    event = rec.record(event_type="t", actor="a", action="b",
                       summary="token AFTERIMAGE-CANARY-0123456789abcdef0123 leaked",
                       evidence={"nested": ["SYNTHETIC DEMO SECRET - NOT A REAL CREDENTIAL"]})
    assert "AFTERIMAGE-CANARY-0123" not in event["summary"]
    assert "SYNTHETIC DEMO SECRET" not in str(event["evidence_metadata"])
