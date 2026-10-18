"""API-level tests for LLM runs and the prompt-injection experiment, using the
simulated provider (no credentials, deterministic)."""

from __future__ import annotations

from .conftest import dump_database, workspace_secret


def test_providers_endpoint_reports_status_without_secrets(client):
    data = client.get("/api/providers").json()
    names = {p["provider"] for p in data["providers"]}
    assert names == {"anthropic", "ollama", "simulated"}
    sim = next(p for p in data["providers"] if p["provider"] == "simulated")
    assert sim["configured"] is True and sim["real"] is False
    assert "sk-ant" not in client.get("/api/providers").text


def test_llm_protected_run_blocks_and_creates_incident(client):
    run = client.post("/api/runs/llm", json={"provider": "simulated", "enforcement": "protected"}).json()
    assert run["agent_kind"] == "llm" and run["enforcement"] == "protected"
    assert run["provider"] == "simulated" and run["provider_real"] is False
    assert run["sensitive_exposed"] is False and run["incident_id"]
    # transcript is persisted and shows the blocked tool call
    transcript = client.get(f"/api/runs/{run['run_id']}/transcript").json()["transcript"]
    assert any(e.get("allowed") is False for e in transcript)


def test_llm_runs_are_labelled_distinctly_from_scripted(client):
    client.post("/api/runs/attack")  # scripted
    client.post("/api/runs/llm", json={"provider": "simulated", "enforcement": "protected"})
    runs = client.get("/api/runs").json()
    kinds = {r["run_id"]: r["agent_kind"] for r in runs}
    assert "scripted" in kinds.values() and "llm" in kinds.values()


def test_experiment_baseline_vs_protected(client):
    exp = client.post("/api/experiments", json={"provider": "simulated", "trials": 2})
    assert exp.status_code == 201
    report = exp.json()["report"]
    # the simulated model is susceptible, so the baseline reproduces the attack...
    assert report["attack_reproduced_in_baseline"] is True
    assert report["baseline"]["secret_leaked"] == 2
    # ...and enforcement blocks it in every protected trial
    assert report["protected"]["secret_leaked"] == 0 and report["protection_held"] is True
    assert report["verdict"] == "protected"
    assert report["provider_real"] is False
    assert any("simulated" in n for n in report["notes"])
    # persisted and retrievable
    again = client.get(f"/api/experiments/{exp.json()['experiment_id']}").json()
    assert again["report"] == report


def test_experiment_links_runs_to_investigation(client, ctx):
    exp = client.post("/api/experiments", json={"provider": "simulated", "trials": 1}).json()
    run_ids = exp["report"]["baseline"]["run_ids"] + exp["report"]["protected"]["run_ids"]
    # every experiment run is a real run with real events
    for run_id in run_ids:
        events = client.get(f"/api/runs/{run_id}/events").json()
        assert events and events[0]["event_type"] == "run_started"
    # the baseline leak produced an incident whose report cites real event IDs
    baseline_run = exp["report"]["baseline"]["run_ids"][0]
    incident_id = ctx.db.scalar("SELECT incident_id FROM incidents WHERE run_id = ?", (baseline_run,))
    assert incident_id
    report = client.get(f"/api/incidents/{incident_id}").json()
    known = {e["event_id"] for e in client.get(f"/api/runs/{baseline_run}/events").json()}
    assert report["sensitive_data_exposed"] is True
    for finding in report["findings"]:
        assert set(finding["evidence_event_ids"]) <= known


def test_secret_never_appears_across_llm_boundaries(client, ctx, settings):
    exp = client.post("/api/experiments", json={"provider": "simulated", "trials": 1}).json()
    baseline_run = exp["report"]["baseline"]["run_ids"][0]
    header, canary = workspace_secret(settings, baseline_run)
    responses = [
        client.get("/api/dashboard"), client.get("/api/runs"), client.get(f"/api/runs/{baseline_run}"),
        client.get(f"/api/runs/{baseline_run}/events"), client.get(f"/api/runs/{baseline_run}/transcript"),
        client.get("/api/experiments"), client.get(f"/api/experiments/{exp['experiment_id']}"),
        client.get("/api/settings"), client.get("/api/events"),
    ]
    for r in responses:
        assert r.status_code == 200
        assert canary not in r.text and header not in r.text
    dump = dump_database(ctx)
    assert canary not in dump and header not in dump


def test_llm_run_rejects_unavailable_provider_without_credentials(client, monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "none"))
    r = client.post("/api/runs/llm", json={"provider": "anthropic", "enforcement": "protected"})
    assert r.status_code == 400 and r.json()["code"] == "provider_missing_credentials"


def _llm_baseline(client):
    return client.post("/api/runs/llm", json={"provider": "simulated", "enforcement": "protected"}).json()


def _apply(client, change_ids):
    base = client.get("/api/policies").json()["active"]["version"]
    r = client.post("/api/policies/apply", json={"change_ids": change_ids, "base_version": base, "confirm": True})
    assert r.status_code == 200, r.text


def test_llm_replay_after_remediation_is_verified(client):
    base = _llm_baseline(client)
    _apply(client, ["restrict-read-scope", "deny-secret-class"])
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"], "trials": 2}).json()
    report = replay["report"]
    assert replay["status"] == "verified" and replay["verified"] is True
    assert report["deterministic_control"]["status"] == "verified"
    assert len(report["model_trials"]) == 2 and report["model_stats"]["attack_attempted"] == 2
    checks = {a["id"]: a for a in report["assertions"]}
    assert checks["model_unauthorized_blocked"]["passed"] and checks["model_no_sensitive_exposure"]["passed"]
    assert checks["model_attack_attempted"]["required"] is False
    assert any("deterministic" in n for n in report["notes"]) and any("probabilistic" in n for n in report["notes"])
    # assertions cite real persisted events
    known = set()
    for t in report["model_trials"]:
        known |= {e["event_id"] for e in client.get(f"/api/runs/{t['run_id']}/events").json()}
    for a in report["assertions"]:
        if a["id"].startswith("model_") and a["required"]:
            assert set(a["evidence_event_ids"]) <= known


def test_llm_replay_reports_regression(client):
    base = _llm_baseline(client)
    _apply(client, ["disable-write-tool"])
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"]}).json()
    assert replay["status"] == "regression" and not replay["verified"]


def test_llm_replay_inconclusive_when_every_model_trial_errors(client, monkeypatch):
    base = _llm_baseline(client)
    import afterimage.runs as runs_module
    from afterimage.providers import ProviderUnavailableError, SimulatedInjectionProvider

    class Down(SimulatedInjectionProvider):
        def complete(self, **kwargs):
            raise ProviderUnavailableError("down", kind="connection")

    monkeypatch.setattr(runs_module, "build_provider", lambda *a, **k: Down())
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"], "trials": 2}).json()
    assert replay["status"] == "inconclusive" and not replay["verified"]
    # the deterministic control still ran and passed
    assert replay["report"]["deterministic_control"]["status"] == "verified"


def test_llm_replay_fails_under_unsafe_policy(client, ctx):
    from afterimage.common import utc_now
    from afterimage.db import dumps
    from afterimage.policy import PolicyDocument, Rule
    base = _llm_baseline(client)
    unsafe = PolicyDocument(name="unsafe", rules=[
        Rule(rule_id="ALLOW-ALL", effect="allow", actions=["*"], resources=[".", "**"], description="test only")])
    ctx.db.execute("INSERT INTO policies (version, document, change_summary, applied_changes, created_at) "
                   "VALUES (2, ?, 'unsafe', '[]', ?)", (dumps(unsafe.model_dump()), utc_now()))
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"]}).json()
    assert replay["status"] == "failed"
    assert "AFTERIMAGE-CANARY" not in client.get(f"/api/replays/{replay['replay_id']}").text


def test_dashboard_counts_llm_and_experiments(client):
    client.post("/api/runs/llm", json={"provider": "simulated", "enforcement": "protected"})
    client.post("/api/experiments", json={"provider": "simulated", "trials": 1})
    m = client.get("/api/dashboard").json()["metrics"]
    assert m["llm_runs"] >= 3  # 1 direct + 2 from the experiment
    assert m["experiments"] == 1 and m["experiments_protected"] == 1


def test_experiment_trials_are_capped(client):
    exp = client.post("/api/experiments", json={"provider": "simulated", "trials": 999})
    assert exp.status_code == 422  # pydantic bound (<=20)
