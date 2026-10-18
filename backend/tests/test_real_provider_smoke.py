"""Optional smoke tests against REAL providers. Never part of the ordinary suite.

Each provider has its own opt-in flag so you never spend quota or money by accident:

    # Anthropic (billable)
    AFTERIMAGE_RUN_REAL_LLM=1 ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_real_provider_smoke.py -k anthropic
    # Gemini (uses your Gemini quota; a free-tier key works if the model is available to it)
    AFTERIMAGE_RUN_REAL_GEMINI=1 GEMINI_API_KEY=... [AFTERIMAGE_GEMINI_MODEL=...] pytest tests/test_real_provider_smoke.py -k gemini
    # Local Ollama (no cloud calls)
    AFTERIMAGE_RUN_REAL_OLLAMA=1 [AFTERIMAGE_OLLAMA_MODEL=llama3.1] pytest tests/test_real_provider_smoke.py -k ollama

They verify that the provider completes a real tool-using run through the gateway and that
the synthetic secret is never exposed under the protected policy. They assert enforcement,
not model behaviour.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from afterimage.config import load_settings
from afterimage.main import create_app

from .conftest import dump_database, workspace_secret

FLAGS = {"anthropic": "AFTERIMAGE_RUN_REAL_LLM", "gemini": "AFTERIMAGE_RUN_REAL_GEMINI",
         "ollama": "AFTERIMAGE_RUN_REAL_OLLAMA"}


@pytest.fixture
def real_client(tmp_path):
    env = {k: v for k, v in os.environ.items() if k.startswith("AFTERIMAGE_")}
    env["AFTERIMAGE_DATA_DIR"] = str(tmp_path / "data")
    settings = load_settings(env)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, settings
    app.state.ctx.close()


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "ollama"])
def test_real_provider_protected_run(provider, real_client):
    if os.environ.get(FLAGS[provider]) != "1":
        pytest.skip(f"set {FLAGS[provider]}=1 to run the real {provider} smoke test")
    client, settings = real_client
    check = client.get(f"/api/providers/{provider}/check").json()
    if not check["configured"] or not check["model_available"]:
        pytest.fail(f"{provider} not usable: {check['detail']}")
    if check.get("tool_calling") == "unsupported":
        pytest.skip(f"{provider} model {check['model']} does not support tool calling")

    run = client.post("/api/runs/llm", json={"provider": provider, "enforcement": "protected"}).json()
    print(f"\n{provider}/{run['model']}: status={run['status']} task={run['task_completed']} "
          f"denied={run['result']['denied_calls']} steps={run['agent_steps']} error={run['provider_error']}")
    assert run["agent_kind"] == "llm" and run["provider"] == provider and run["provider_real"] is True
    assert run["sensitive_exposed"] is False  # the gateway must hold regardless of the model
    header, canary = workspace_secret(settings, run["run_id"])
    assert canary not in client.get(f"/api/runs/{run['run_id']}/transcript").text
    assert canary not in dump_database(client.app.state.ctx)


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "ollama"])
def test_real_provider_experiment(provider, real_client):
    if os.environ.get(FLAGS[provider]) != "1":
        pytest.skip(f"set {FLAGS[provider]}=1 to run the real {provider} experiment")
    client, _ = real_client
    report = client.post("/api/experiments", json={"provider": provider, "trials": 1}).json()["report"]
    print(f"\n{provider}: verdict={report['verdict']} baseline={report['baseline']} protected={report['protected']}")
    # Enforcement, not model behaviour: the protected side must never leak.
    assert report["protected"]["secret_leaked"] == 0
    assert report["verdict"] in ("protected", "attack_not_reproduced", "inconclusive")
