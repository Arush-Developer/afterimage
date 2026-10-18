"""Policy changes, replay verification and duplicate-request safety."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from afterimage.db import dumps
from afterimage.policy import PolicyDocument, Rule
from afterimage.common import utc_now

from .conftest import apply_policy, dump_database, workspace_secret


def test_preview_shows_previous_and_new_policy_and_impact(client):
    r = client.post("/api/policies/preview", json={"change_ids": ["restrict-read-scope", "deny-secret-class"]})
    assert r.status_code == 200
    p = r.json()
    assert p["base_version"] == 1 and not p["no_op"]
    before = {x["rule_id"] for x in p["current_document"]["rules"]}
    after = {x["rule_id"] for x in p["proposed_document"]["rules"]}
    assert "POL-READ-WORKSPACE" in before and "POL-READ-WORKSPACE" not in after
    assert {"POL-READ-TASK-SCOPE", "POL-DENY-SECRET-CLASS"} <= after
    assert p["impact"]["legitimate_operations_broken"] == 0 and p["impact"]["warnings"] == []
    # Preview does not change anything.
    assert client.get("/api/policies").json()["active"]["version"] == 1


def test_preview_warns_about_regressions(client):
    p = client.post("/api/policies/preview", json={"change_ids": ["disable-write-tool"]}).json()
    assert p["impact"]["legitimate_operations_broken"] == 1
    assert "Save the summary" in p["impact"]["warnings"][0]


def test_policy_change_affects_backend_enforcement(client):
    run = client.post("/api/runs/attack").json()
    events = client.get(f"/api/runs/{run['run_id']}/events").json()
    assert any(e["event_type"] == "policy_decision" and e["resource_id"] == "secret.txt"
               and e["evidence_metadata"]["rule_id"] == "POL-DENY-SECRET-FILE" for e in events)
    apply_policy(client, ["restrict-read-scope", "deny-secret-class"])
    run2 = client.post("/api/runs/attack").json()
    assert run2["policy_version"] == 2
    events2 = client.get(f"/api/runs/{run2['run_id']}/events").json()
    secret = next(e for e in events2 if e["event_type"] == "policy_decision" and e["resource_id"] == "secret.txt")
    assert secret["evidence_metadata"]["rule_id"] == "POL-DENY-SECRET-CLASS"
    readme = next(e for e in events2 if e["event_type"] == "policy_decision" and e["resource_id"] == "README.md")
    assert readme["evidence_metadata"]["rule_id"] == "POL-READ-TASK-SCOPE"
    # A tool disabled by policy is denied at the gateway.
    apply_policy(client, ["disable-write-tool"])
    run3 = client.post("/api/runs/benign").json()
    assert run3["task_completed"] is False
    events3 = client.get(f"/api/runs/{run3['run_id']}/events").json()
    write = next(e for e in events3 if e["event_type"] == "policy_decision" and e["action"] == "write_file")
    assert write["outcome"] == "denied" and write["evidence_metadata"]["rule_id"] == "AI-TOOL-001"


def test_replay_after_remediation_is_verified(client):
    base = client.post("/api/runs/attack").json()
    apply_policy(client, ["restrict-read-scope", "deny-secret-class"])
    r = client.post("/api/replays", json={"incident_id": base["incident_id"]})
    assert r.status_code == 201
    replay = r.json()
    rep = replay["report"]
    assert replay["status"] == "verified" and replay["verified"] is True
    assert replay["baseline_policy_version"] == 1 and replay["replay_policy_version"] == 2 and rep["policy_changed"]
    checks = {a["id"]: a for a in rep["assertions"]}
    assert all(a["passed"] for a in checks.values())
    # attack still blocked, benign task still works
    assert rep["replay"]["unauthorized_attempted"] == 2 and rep["replay"]["unauthorized_blocked"] == 2
    assert rep["replay"]["task_completed"] is True and rep["replay"]["sensitive_data_exposed"] is False
    assert "POL-DENY-SECRET-CLASS" in rep["replay"]["rules_responsible"]
    assert any(d["resource_id"] == "secret.txt" and d["changed"] for d in rep["differences"])
    # assertions cite real events of the replay run
    run_events = {e["event_id"] for e in client.get(f"/api/runs/{replay['replay_run_id']}/events").json()}
    for a in rep["assertions"]:
        if a["required"]:
            assert set(a["evidence_event_ids"]) <= run_events and a["evidence_event_ids"]
    # persisted: available after "refresh"
    assert client.get(f"/api/replays/{replay['replay_id']}").json() == replay
    assert client.get("/api/dashboard").json()["metrics"]["verified_replays"] == 1


def test_replay_report_matches_actual_execution(client, ctx):
    base = client.post("/api/runs/attack").json()
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"]}).json()
    run = client.get(f"/api/runs/{replay['replay_run_id']}").json()
    assert run["kind"] == "replay"
    rep = replay["report"]
    assert rep["replay"]["task_completed"] == run["task_completed"]
    denied = ctx.db.scalar("SELECT COUNT(*) FROM policy_decisions WHERE run_id = ? AND allowed = 0", (run["run_id"],))
    assert rep["replay"]["unauthorized_blocked"] == denied == 2
    assert not rep["policy_changed"] and rep["notes"]  # honest: same policy => reproducibility only


def test_regression_is_not_reported_as_success(client):
    base = client.post("/api/runs/attack").json()
    apply_policy(client, ["disable-write-tool"])
    replay = client.post("/api/replays", json={"incident_id": base["incident_id"]}).json()
    assert replay["status"] == "regression" and replay["verified"] is False
    checks = {a["id"]: a["passed"] for a in replay["report"]["assertions"]}
    assert checks["unauthorized_blocked"] and not checks["legitimate_task_completed"]
    assert any("too restrictive" in n for n in replay["report"]["notes"])


def test_failed_security_is_reported_and_secret_still_not_persisted(client, ctx, settings):
    """Inject a deliberately unsafe policy directly into storage (not possible via the API)
    and confirm the replay reports FAILED with an exposure, without persisting the secret."""
    base = client.post("/api/runs/attack").json()
    unsafe = PolicyDocument(name="unsafe test policy", rules=[
        Rule(rule_id="ALLOW-ALL", effect="allow", actions=["*"], resources=[".", "**"], description="test only")])
    ctx.db.execute("INSERT INTO policies (version, document, change_summary, applied_changes, created_at) "
                   "VALUES (2, ?, 'unsafe', '[]', ?)", (dumps(unsafe.model_dump()), utc_now()))
    replay = client.post("/api/replays", json={"baseline_run_id": base["run_id"]}).json()
    assert replay["status"] == "failed" and not replay["verified"]
    assert replay["report"]["replay"]["sensitive_data_exposed"] is True
    header, canary = workspace_secret(settings, replay["replay_run_id"])
    assert canary not in dump_database(ctx)
    incident = client.get("/api/incidents").json()[0]
    assert incident["severity"] == "critical" and incident["status"] == "exposure_confirmed"
    assert canary not in client.get(f"/api/runs/{replay['replay_run_id']}").text


def test_duplicate_apply_does_not_create_two_versions(client):
    body = {"change_ids": ["deny-secret-class"], "base_version": 1, "confirm": True}
    first = client.post("/api/policies/apply", json=body)
    second = client.post("/api/policies/apply", json=body)
    assert first.status_code == 200 and second.status_code == 409
    assert [h["version"] for h in client.get("/api/policies").json()["history"]] == [2, 1]


def test_idempotency_key_replays_response(client):
    headers = {"Idempotency-Key": "click-0001-abcdef"}
    a = client.post("/api/runs/attack", headers=headers)
    b = client.post("/api/runs/attack", headers=headers)
    assert a.status_code == b.status_code == 201
    assert a.json()["run_id"] == b.json()["run_id"] and b.headers.get("idempotent-replay") == "true"
    assert len(client.get("/api/runs").json()) == 1
    # Same key on another endpoint is rejected.
    assert client.post("/api/runs/benign", headers=headers).status_code == 409


def test_concurrent_requests_do_not_corrupt_state(client, ctx):
    def fire(i):
        return client.post("/api/runs/attack", headers={"Idempotency-Key": "same-key-123"}).json()["run_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(fire, range(4)))
    assert len(set(ids)) == 1
    assert ctx.db.scalar("SELECT COUNT(*) FROM runs") == 1
    assert client.get("/api/events/verify").json()["valid"] is True


def test_revert_restores_previous_rules(client):
    apply_policy(client, ["restrict-read-scope"])
    r = client.post("/api/policies/revert", json={"target_version": 1, "base_version": 2, "confirm": True})
    assert r.status_code == 200 and r.json()["version"] == 3
    rules = {x["rule_id"] for x in r.json()["document"]["rules"]}
    assert "POL-READ-WORKSPACE" in rules and "POL-READ-TASK-SCOPE" not in rules
    stale = client.post("/api/policies/revert", json={"target_version": 1, "base_version": 2, "confirm": True})
    assert stale.status_code == 409


def test_demo_reset_keeps_evidence(client):
    client.post("/api/runs/attack")
    apply_policy(client, ["deny-secret-class"])
    assert client.post("/api/settings/reset", json={"mode": "demo", "confirm_text": "nope"}).status_code == 400
    r = client.post("/api/settings/reset", json={"mode": "demo", "confirm_text": "RESET DEMO"})
    assert r.status_code == 200
    assert client.get("/api/dashboard").json()["metrics"]["incidents"] == 1
    active = client.get("/api/policies").json()["active"]
    assert active["version"] == 3 and "POL-DENY-SECRET-CLASS" not in {x["rule_id"] for x in active["document"]["rules"]}


def test_full_reset_archives_before_wiping(client, settings):
    client.post("/api/runs/attack")
    assert client.post("/api/settings/reset", json={"mode": "full", "confirm_text": "RESET"}).status_code == 400
    r = client.post("/api/settings/reset", json={"mode": "full", "confirm_text": "ARCHIVE AND RESET"})
    assert r.status_code == 200
    assert (settings.archives_dir / r.json()["archive"]).exists()
    assert client.get("/api/dashboard").json()["metrics"]["incidents"] == 0
    assert client.post("/api/runs/attack").status_code == 201
