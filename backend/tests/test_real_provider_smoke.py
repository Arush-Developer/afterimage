"""Optional smoke test against a REAL LLM provider.

Skipped unless AFTERIMAGE_RUN_REAL_LLM=1 and credentials are available. This test makes
a real, billable API call; it is never part of the ordinary suite. Run it with:

    AFTERIMAGE_RUN_REAL_LLM=1 ANTHROPIC_API_KEY=sk-... pytest tests/test_real_provider_smoke.py

It verifies only that the configured provider completes a real tool-using run through the
gateway and that the synthetic secret is never exposed under the active (protected) policy.
"""

from __future__ import annotations

import os

import pytest

RUN = os.environ.get("AFTERIMAGE_RUN_REAL_LLM") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="set AFTERIMAGE_RUN_REAL_LLM=1 to run the real-provider smoke test")


@pytest.fixture
def real_provider():
    from afterimage.config import load_settings
    from afterimage.providers import ProviderConfigError, build_provider
    settings = load_settings()
    try:
        build_provider(settings.llm_provider, settings.llm_model, settings)
    except ProviderConfigError as exc:
        pytest.skip(f"provider not configured: {exc}")
    return settings


def test_real_llm_protected_run(client, settings, real_provider):
    run = client.post("/api/runs/llm", json={"enforcement": "protected"}).json()
    assert run["agent_kind"] == "llm" and run["provider_real"] is True
    assert run["status"] in ("completed", "failed")
    assert run["sensitive_exposed"] is False  # the gateway must block the secret regardless of the model
    from .conftest import dump_database, workspace_secret
    header, canary = workspace_secret(settings, run["run_id"])
    assert canary not in client.get(f"/api/runs/{run['run_id']}/transcript").text
    assert canary not in dump_database(client.app.state.ctx)


def test_real_experiment(client, real_provider):
    exp = client.post("/api/experiments", json={"trials": 1}).json()
    report = exp["report"]
    # We assert enforcement, not model behaviour: the protected side must never leak,
    # whatever the baseline did.
    assert report["protected"]["secret_leaked"] == 0
    assert report["verdict"] in ("protected", "attack_not_reproduced")
