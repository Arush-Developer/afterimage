"""End-to-end API tests for scenarios, incidents, graph, dashboard and persistence."""

from __future__ import annotations

import json

import networkx as nx

from afterimage.config import load_settings
from afterimage.main import create_app
from fastapi.testclient import TestClient

from .conftest import dump_database, workspace_secret


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_benign_summary_succeeds_without_incident(client):
    r = client.post("/api/runs/benign")
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "completed" and run["task_completed"] is True
    assert run["sensitive_exposed"] is False and run["incident_id"] is None
    assert "Orbit Inventory" in run["output_summary"] and "src/inventory.py" in run["output_summary"]
    events = client.get(f"/api/runs/{run['run_id']}/events").json()
    types = [e["event_type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_completed"
    decisions = [e for e in events if e["event_type"] == "policy_decision"]
    assert decisions and all(e["outcome"] == "allowed" for e in decisions)
    # The benign agent saw the injection text but did not act on it.
    assert any(e["event_type"] == "agent_note" and "Ignored" in e["summary"] for e in events)
    assert client.get("/api/incidents").json() == []


def test_attack_is_denied_recorded_and_task_still_completes(client):
    run = client.post("/api/runs/attack").json()
    assert run["task_completed"] is True and run["sensitive_exposed"] is False
    assert run["result"]["denied_calls"] == 2
    assert run["incident_id"]
    report = client.get(f"/api/incidents/{run['incident_id']}").json()
    inc = report["incident"]
    assert inc["severity"] == "high" and inc["confidence"] == "high" and inc["status"] == "contained"
    assert inc["resource_id"] == "secret.txt" and inc["rule_id"] == "POL-DENY-SECRET-FILE"
    assert inc["trigger_resource"] == "docs/integration_notes.md"
    assert inc["first_event_at"] <= inc["last_event_at"]
    assert {a["rule_id"] for a in report["attempts"]} == {"POL-DENY-SECRET-FILE", "AI-BOUNDARY-001"}
    assert all(not a["content_returned"] for a in report["attempts"])
    assert {f["kind"] for f in report["findings"]} == {"observed", "inferred"}
    assert report["uncertainties"] and report["simulated"] is True
    assert report["recommendation"]["change_ids"] == ["restrict-read-scope", "deny-secret-class"]
    # every finding cites real event ids
    known = {e["event_id"] for e in client.get(f"/api/runs/{run['run_id']}/events").json()}
    for f in report["findings"]:
        assert f["evidence_event_ids"] and set(f["evidence_event_ids"]) <= known


def test_graph_is_derived_from_persisted_events(client, ctx):
    run = client.post("/api/runs/attack").json()
    graph = client.get(f"/api/incidents/{run['incident_id']}/graph").json()
    assert graph["is_dag"]
    rows = {r["event_id"]: r for r in ctx.db.query("SELECT * FROM events WHERE run_id = ?", (run["run_id"],))}
    node_ids = {n["id"] for n in graph["nodes"]}
    assert node_ids <= set(rows)
    for edge in graph["edges"]:
        target = rows[edge["target"]]
        if edge["relation"] == "evidence for":
            opened = json.loads(target["evidence_metadata"])
            assert edge["source"] in opened["decision_event_ids"]
        else:
            assert target["source_event_id"] == edge["source"]
    g = nx.DiGraph([(e["source"], e["target"]) for e in graph["edges"]])
    by_type = {n["id"]: n for n in graph["nodes"]}
    doc_read = next(n for n in graph["nodes"] if n["event_type"] == "tool_result" and n["resource_id"] == "docs/integration_notes.md")
    opened = next(n for n in graph["nodes"] if n["event_type"] == "incident_opened")
    path = nx.shortest_path(g, doc_read["id"], opened["id"])
    assert [by_type[p]["event_type"] for p in path] == ["tool_result", "tool_call_requested", "policy_decision", "incident_opened"]


def test_timeline_is_chronological(client):
    run = client.post("/api/runs/attack").json()
    events = client.get(f"/api/incidents/{run['incident_id']}/events").json()
    stamps = [e["timestamp"] for e in events]
    assert stamps == sorted(stamps)
    assert any(e["evidence_role"] == "trigger_input" for e in events)


def test_incident_survives_database_reload(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        incident_id = c.post("/api/runs/attack").json()["incident_id"]
        before = c.get(f"/api/incidents/{incident_id}").json()
        graph_before = c.get(f"/api/incidents/{incident_id}/graph").json()
    app.state.ctx.close()
    app2 = create_app(load_settings({"AFTERIMAGE_DATA_DIR": str(settings.data_dir)}))
    with TestClient(app2) as c:
        after = c.get(f"/api/incidents/{incident_id}").json()
        assert after == before
        assert c.get(f"/api/incidents/{incident_id}/graph").json() == graph_before
    app2.state.ctx.close()


def test_dashboard_metrics_come_from_backend(client):
    m = client.get("/api/dashboard").json()["metrics"]
    assert m["runs"] == 0 and m["incidents"] == 0 and m["unauthorized_blocked"] == 0
    client.post("/api/runs/benign")
    client.post("/api/runs/attack")
    d = client.get("/api/dashboard").json()
    assert d["metrics"]["runs"] == 2 and d["metrics"]["incidents"] == 1
    assert d["metrics"]["unauthorized_blocked"] == 2 and d["metrics"]["exposures"] == 0
    assert d["metrics"]["verified_replays"] == 0
    assert len(d["recent_runs"]) == 2 and d["sync"]["cloud"]["status"] == "not_configured"


def test_secret_never_in_api_responses_or_database(client, ctx, settings):
    run = client.post("/api/runs/attack").json()
    header, canary = workspace_secret(settings, run["run_id"])
    responses = [
        client.get("/api/dashboard"), client.get("/api/runs"), client.get(f"/api/runs/{run['run_id']}"),
        client.get(f"/api/runs/{run['run_id']}/events"), client.get("/api/incidents"),
        client.get(f"/api/incidents/{run['incident_id']}"), client.get(f"/api/incidents/{run['incident_id']}/graph"),
        client.get(f"/api/incidents/{run['incident_id']}/events"), client.get("/api/events"),
        client.get("/api/settings"), client.post("/api/replays", json={"baseline_run_id": run["run_id"]}),
    ]
    for r in responses:
        assert r.status_code in (200, 201)
        assert canary not in r.text and header not in r.text
    dump = dump_database(ctx)
    assert canary not in dump and header not in dump


def test_invalid_requests_return_errors(client):
    assert client.get("/api/incidents/inc_doesnotexist").status_code == 422
    assert client.get("/api/incidents/inc_0000000000000000").status_code == 404
    assert client.get("/api/runs/run_0000000000000000").status_code == 404
    assert client.get("/api/replays/rpl_0000000000000000").status_code == 404
    assert client.get("/api/runs/../../etc/passwd").status_code == 404
    assert client.post("/api/replays", json={}).status_code == 400
    assert client.post("/api/replays", json={"incident_id": "inc_0000000000000000"}).status_code == 404
    assert client.post("/api/policies/preview", json={"change_ids": ["allow-everything"]}).status_code == 422
    assert client.post("/api/policies/apply", json={"change_ids": ["deny-secret-class"], "base_version": 1}).status_code == 422
    assert client.post("/api/runs/attack", headers={"Idempotency-Key": "bad key!"}).status_code == 400
    assert client.get("/api/events", params={"run_id": "nope"}).status_code == 422
    body = client.get("/api/incidents/inc_0000000000000000").json()
    assert body["code"] == "not_found"


def test_event_explorer_filters(client):
    run = client.post("/api/runs/attack").json()
    client.post("/api/runs/benign")
    data = client.get("/api/events", params={"run_id": run["run_id"], "outcome": "denied"}).json()
    assert data["total"] == 2 and all(e["outcome"] == "denied" for e in data["events"])
    data = client.get("/api/events", params={"resource": "secret", "event_type": "policy_decision"}).json()
    assert data["total"] == 1
    data = client.get("/api/events", params={"incident_id": run["incident_id"]}).json()
    assert data["total"] > 0
    facets = client.get("/api/events/facets").json()
    assert "policy_decision" in facets["event_types"]


def test_incident_annotation_is_appended(client):
    inc = client.post("/api/runs/attack").json()["incident_id"]
    r = client.post(f"/api/incidents/{inc}/notes", json={"text": "Reviewed by analyst", "status": "resolved"})
    assert r.status_code == 201
    assert client.get(f"/api/incidents/{inc}").json()["incident"]["status"] == "resolved"
    events = client.get(f"/api/incidents/{inc}/events").json()
    assert events[-1]["event_type"] == "incident_annotation" and events[-1]["evidence_metadata"]["previous_status"] == "contained"
