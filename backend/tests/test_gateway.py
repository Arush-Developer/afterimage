"""Policy engine + gateway: authorized reads, denials, path safety, event records."""

from __future__ import annotations

import os

import pytest

from afterimage.db import Database
from afterimage.gateway import ToolGateway
from afterimage.policy import BASELINE_POLICY, PolicyEngine, glob_match
from afterimage.recorder import EventRecorder
from afterimage.workspace import SECRET_HEADER, create_workspace, resolve_workspace_path


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "t.db")
    recorder = EventRecorder(db)
    db.execute("INSERT INTO runs (run_id, scenario, kind, status, policy_version, workspace_path, started_at) "
               "VALUES ('run_0000000000000001', 'attack', 'scenario', 'running', 1, 'x', 'now')")
    ws = create_workspace(tmp_path / "ws", "run_0000000000000001")
    gw = ToolGateway(db, recorder, ws, PolicyEngine(BASELINE_POLICY, 1), "run_0000000000000001")
    yield gw, db, ws, tmp_path
    db.close()


def events(db, **filters):
    rows = db.query("SELECT * FROM events ORDER BY seq")
    return [r for r in rows if all(r[k] == v for k, v in filters.items())]


def test_authorized_read_succeeds(env):
    gw, db, ws, _ = env
    out = gw.read_file("README.md")
    assert out.allowed and "Orbit Inventory" in out.content
    assert out.decision.rule_id == "POL-READ-WORKSPACE"
    assert {"decision_id", "allowed", "rule_id", "reason", "resource_id", "action", "timestamp"} <= set(out.decision.model_dump())


def test_restricted_read_denied_without_content(env):
    gw, db, ws, _ = env
    out = gw.read_file("secret.txt")
    assert not out.allowed
    assert out.content is None
    assert out.decision.rule_id == "POL-DENY-SECRET-FILE"
    result = events(db, event_id=out.result_event_id)[0]
    assert result["outcome"] == "blocked" and '"bytes_returned":0' in result["evidence_metadata"]


def test_canonicalized_alias_of_secret_is_denied(env):
    gw, *_ = env
    out = gw.read_file("src/../secret.txt")
    assert not out.allowed and out.decision.resource_id == "secret.txt"
    out = gw.read_file("./secret.txt")
    assert not out.allowed


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "..", "docs/../../../etc/passwd"])
def test_path_traversal_rejected(env, path):
    gw, *_ = env
    out = gw.read_file(path)
    assert not out.allowed and out.decision.rule_id == "AI-BOUNDARY-001"
    assert out.decision.resource_id.startswith("external:")


@pytest.mark.parametrize("path", ["/etc/passwd", "C:/Windows/win.ini", "~/secrets", "\\\\server\\share", "a\x00b", ""])
def test_absolute_and_malformed_paths_rejected(env, path):
    gw, *_ = env
    out = gw.read_file(path)
    assert not out.allowed and out.decision.rule_id == "AI-BOUNDARY-001"


def test_symlink_escape_rejected(env):
    gw, db, ws, tmp_path = env
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("outside content")
    os.symlink(outside, ws.root / "docs" / "escape.md")
    os.symlink(tmp_path, ws.root / "src" / "parentdir")
    assert gw.read_file("docs/escape.md").decision.rule_id == "AI-BOUNDARY-001"
    out = gw.read_file("src/parentdir/outside_secret.txt")
    assert not out.allowed and out.content is None


def test_symlink_inside_workspace_to_secret_is_denied(env):
    gw, db, ws, _ = env
    os.symlink(ws.root / "secret.txt", ws.root / "docs" / "notes_alias.md")
    out = gw.read_file("docs/notes_alias.md")
    assert not out.allowed and out.decision.resource_id == "secret.txt"


def test_every_invocation_records_request_decision_result(env):
    gw, db, ws, _ = env
    for call in (lambda: gw.read_file("README.md"), lambda: gw.read_file("secret.txt"),
                 lambda: gw.list_files("."), lambda: gw.write_file("out/x.md", "hi"),
                 lambda: gw.invoke("delete_everything", "README.md")):
        before = len(events(db))
        out = call()
        new = events(db)[before:]
        assert [e["event_type"] for e in new] == ["tool_call_requested", "policy_decision", "tool_result"]
        assert new[1]["source_event_id"] == new[0]["event_id"]
        assert new[2]["source_event_id"] == new[1]["event_id"]
        assert new[1]["policy_decision_id"] == out.decision.decision_id
        assert db.query_one("SELECT * FROM policy_decisions WHERE decision_id = ?", (out.decision.decision_id,))
    assert db.query_one("SELECT rule_id FROM policy_decisions WHERE action = 'delete_everything'")["rule_id"] == "AI-TOOL-002"


def test_write_outside_output_dir_denied(env):
    gw, *_ = env
    assert not gw.write_file("src/inventory.py", "pwned").allowed
    assert not gw.write_file("../evil.txt", "x").allowed
    assert gw.write_file("out/summary.md", "ok").allowed


def test_secret_never_in_event_records(env):
    gw, db, ws, _ = env
    gw.read_file("secret.txt")
    gw.read_file("README.md")
    dump = "\n".join(str(r) for r in db.query("SELECT * FROM events")) + str(db.query("SELECT * FROM policy_decisions"))
    assert ws.canary not in dump and SECRET_HEADER not in dump


def test_permissive_policy_exposure_is_detected_and_redacted(env, tmp_path):
    """If a (deliberately bad) policy allows the secret, the exposure is recorded but the
    secret value itself is still never persisted."""
    gw, db, ws, _ = env
    from afterimage.policy import PolicyDocument, Rule
    gw.engine = PolicyEngine(PolicyDocument(name="permissive", rules=[
        Rule(rule_id="ALLOW-ALL", effect="allow", actions=["*"], resources=["**"], description="everything")]), 99)
    out = gw.read_file("secret.txt")
    assert out.allowed and ws.canary in out.content
    assert gw.exposure_event_ids
    dump = str(db.query("SELECT * FROM events"))
    assert ws.canary not in dump


def test_glob_semantics():
    assert glob_match("**/secret*", "secret.txt")
    assert glob_match("**/secret*", "a/b/secret.bak")
    assert glob_match("src/**", "src/a/b.py")
    assert not glob_match("src/*", "src/a/b.py")
    assert not glob_match("secret.txt", "docs/secret.txt")


def test_resolver_returns_canonical_paths(tmp_path):
    ws = create_workspace(tmp_path, "w")
    assert resolve_workspace_path(ws.root, "./src//inventory.py").canonical == "src/inventory.py"
    assert resolve_workspace_path(ws.root, ".").canonical == "."
    assert resolve_workspace_path(ws.root, "../w/README.md").violation
