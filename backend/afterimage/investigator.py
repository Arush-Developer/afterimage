"""Rule-based incident investigator.

Everything here is derived from persisted records (events, policy decisions and the
incident/event link table). Findings are labelled:

* observed   - directly recorded by the gateway/recorder (requests, decisions, results)
* inferred   - a conclusion drawn from several observations (e.g. which input most
               likely triggered a request). Never presented as proof of model intent.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from .common import NotFoundError, ValidationFailure, new_id, utc_now
from .db import Database, loads
from .policy import CHANGE_CATALOG, apply_changes
from .policy_store import PolicyStore
from .recorder import EventRecorder, deserialize_event

SEVERITY_MEANING = "Severity = potential impact of what was targeted (critical > high > medium > low)."
CONFIDENCE_MEANING = "Confidence = how strongly the recorded evidence supports the finding (high / medium / low)."
INCIDENT_STATUSES = ("open", "investigating", "contained", "exposure_confirmed", "resolved")

EDGE_LABELS = {
    ("run_started", "task_received"): "assigned task",
    ("task_received", "tool_call_requested"): "task instruction",
    ("tool_result", "tool_call_requested"): "agent-reported provenance",
    ("tool_call_requested", "policy_decision"): "evaluated by gateway",
    ("policy_decision", "tool_result"): "resulted in",
    ("tool_result", "sensitive_data_exposed"): "exposed",
    ("tool_result", "agent_note"): "agent response",
    ("policy_decision", "incident_opened"): "evidence for",
    ("incident_opened", "incident_annotation"): "annotated",
}


def _event_category(e: dict[str, Any]) -> str:
    """Display category; the UI pairs every category with an icon + text, not colour alone."""
    if e["event_type"] in ("incident_opened", "sensitive_data_exposed"):
        return "suspicious"
    if e["event_type"] == "policy_decision":
        return "allowed" if e["outcome"] == "allowed" else "denied"
    if e["event_type"] == "tool_result":
        if e["outcome"] == "blocked":
            return "denied"
        if e["evidence_metadata"].get("content_flags", {}).get("instruction_like_text"):
            return "suspicious"
        return "allowed" if e["outcome"] == "success" else "info"
    if e["event_type"] == "tool_call_requested":
        sens = e["evidence_metadata"].get("resource_sensitivity")
        return "suspicious" if sens in ("restricted", "outside_workspace") else "info"
    return "info"


def _short_label(e: dict[str, Any]) -> str:
    t, res = e["event_type"], e["resource_id"] or ""
    if t == "tool_call_requested":
        return f"Request {e['action']} {res}"
    if t == "policy_decision":
        return f"{e['outcome'].upper()} ({e['evidence_metadata'].get('rule_id')})"
    if t == "tool_result":
        flagged = e["evidence_metadata"].get("content_flags", {}).get("instruction_like_text")
        return f"Result: {e['outcome']}" + (" - instruction-like text" if flagged else "")
    return {"run_started": "Run started", "task_received": "Task received", "incident_opened": "Incident recorded",
            "sensitive_data_exposed": "Sensitive data exposed", "agent_note": "Agent note",
            "incident_annotation": "Analyst note", "run_completed": "Run completed"}.get(t, t)


class Investigator:
    def __init__(self, db: Database, recorder: EventRecorder, policies: PolicyStore):
        self.db = db
        self.recorder = recorder
        self.policies = policies

    # -- detection --------------------------------------------------------------
    def _run_events(self, run_id: str) -> list[dict[str, Any]]:
        return [deserialize_event(r) for r in self.db.query("SELECT * FROM events WHERE run_id = ? ORDER BY seq", (run_id,))]

    def detect(self, run_id: str) -> str | None:
        """Open an incident if the run contains unauthorized requests or exposure. Idempotent per run."""
        existing = self.db.scalar("SELECT incident_id FROM incidents WHERE run_id = ?", (run_id,))
        if existing:
            return existing
        events = self._run_events(run_id)
        by_id = {e["event_id"]: e for e in events}
        suspicious_requests = [e for e in events if e["event_type"] == "tool_call_requested"
                               and e["evidence_metadata"].get("resource_sensitivity") in ("restricted", "outside_workspace")]
        exposures = [e for e in events if e["event_type"] == "sensitive_data_exposed"]
        if not suspicious_requests and not exposures:
            return None

        graph = self._graph_for(events)
        evidence: dict[str, str] = {}
        decisions = []
        for req in suspicious_requests:
            for anc in nx.ancestors(graph, req["event_id"]):
                evidence.setdefault(anc, "context")
            evidence[req["event_id"]] = "suspicious_request"
            for desc in nx.descendants(graph, req["event_id"]):
                ev = by_id[desc]
                role = "decision" if ev["event_type"] == "policy_decision" else (
                    "exposure" if ev["event_type"] == "sensitive_data_exposed" else "result")
                evidence[desc] = role
                if ev["event_type"] == "policy_decision":
                    decisions.append(ev)
            if req["source_event_id"] in by_id and by_id[req["source_event_id"]]["event_type"] == "tool_result":
                evidence[req["source_event_id"]] = "trigger_input"
        for exp in exposures:
            evidence[exp["event_id"]] = "exposure"

        primary = suspicious_requests[0] if suspicious_requests else by_id[exposures[0]["source_event_id"]]
        primary_decision = next((d for d in decisions if d["source_event_id"] == primary["event_id"]), None)
        restricted = any(r["evidence_metadata"].get("resource_sensitivity") == "restricted" for r in suspicious_requests)
        exposed = bool(exposures)
        all_denied = all(d["outcome"] != "allowed" for d in decisions) and not exposed
        severity = "critical" if exposed else ("high" if restricted else "medium")
        trigger = self._trigger_for(primary, by_id, events)
        has_provenance = trigger is not None and trigger["basis"] == "agent_reported_provenance"
        confidence = "high" if (decisions and has_provenance) else ("medium" if decisions else "low")
        status = "exposure_confirmed" if exposed else ("contained" if all_denied else "open")
        resource = primary["resource_id"]
        title = (f"{'Exposure of' if exposed else 'Blocked attempt to access'} {resource}"
                 + (f" after processing {trigger['resource_id']}" if trigger else ""))
        ordered = sorted((by_id[i] for i in evidence), key=lambda e: e["timestamp"])
        incident_id = new_id("inc")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO incidents (incident_id, run_id, created_at, incident_type, title, severity, confidence, "
                "status, resource_id, rule_id, trigger_resource, first_event_at, last_event_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (incident_id, run_id, utc_now(),
                 "sensitive_data_exposure" if exposed else "restricted_resource_access_attempt",
                 title, severity, confidence, status, resource,
                 primary_decision["evidence_metadata"].get("rule_id") if primary_decision else None,
                 trigger["resource_id"] if trigger else None, ordered[0]["timestamp"], ordered[-1]["timestamp"]),
            )
            for event_id, role in evidence.items():
                conn.execute("INSERT INTO incident_events (incident_id, event_id, role) VALUES (?,?,?)",
                             (incident_id, event_id, role))
            opened = self.recorder.record(
                event_type="incident_opened", actor="investigator", action="open_incident", run_id=run_id,
                incident_id=incident_id, resource_id=resource,
                source_event_id=primary_decision["event_id"] if primary_decision else primary["event_id"],
                outcome=status, severity=severity,
                summary=f"Incident recorded: {title}. Severity {severity}, confidence {confidence}.",
                evidence={"evidence_event_ids": list(evidence), "decision_event_ids": [d["event_id"] for d in decisions]},
            )
            conn.execute("INSERT INTO incident_events (incident_id, event_id, role) VALUES (?,?,?)",
                         (incident_id, opened["event_id"], "incident"))
        return incident_id

    @staticmethod
    def _trigger_for(request: dict, by_id: dict[str, dict], events: list[dict]) -> dict[str, Any] | None:
        source = by_id.get(request["source_event_id"] or "")
        if source and source["event_type"] == "tool_result":
            return {"resource_id": source["resource_id"], "event_id": source["event_id"],
                    "basis": "agent_reported_provenance",
                    "content_flagged": bool(source["evidence_metadata"].get("content_flags", {}).get("instruction_like_text"))}
        # Fallback: the most recent flagged read before the request (temporal correlation only).
        earlier = [e for e in events if e["timestamp"] <= request["timestamp"] and e["event_type"] == "tool_result"
                   and e["evidence_metadata"].get("content_flags", {}).get("instruction_like_text")]
        if earlier:
            e = earlier[-1]
            return {"resource_id": e["resource_id"], "event_id": e["event_id"], "basis": "temporal_proximity",
                    "content_flagged": True}
        return None

    # -- graph -----------------------------------------------------------------
    @staticmethod
    def _graph_for(events: list[dict[str, Any]], links: list[dict[str, Any]] | None = None) -> nx.DiGraph:
        g = nx.DiGraph()
        ids = {e["event_id"] for e in events}
        for e in events:
            g.add_node(e["event_id"])
        by_id = {e["event_id"]: e for e in events}
        for e in events:
            src = e["source_event_id"]
            if src in ids:
                g.add_edge(src, e["event_id"],
                           relation=EDGE_LABELS.get((by_id[src]["event_type"], e["event_type"]), "derived from"))
        for link in links or []:
            if link["from"] in ids and link["to"] in ids and not g.has_edge(link["from"], link["to"]):
                g.add_edge(link["from"], link["to"], relation=link["relation"])
        return g

    def graph(self, incident_id: str) -> dict[str, Any]:
        incident = self._incident_row(incident_id)
        events = self.incident_events(incident_id)
        opened = next((e for e in events if e["event_type"] == "incident_opened"), None)
        links = []
        if opened:
            for d in opened["evidence_metadata"].get("decision_event_ids", []):
                links.append({"from": d, "to": opened["event_id"], "relation": "evidence for"})
        g = self._graph_for(events, links)
        positions: dict[str, tuple[int, int]] = {}
        for col, generation in enumerate(nx.topological_generations(g)):
            ordered = sorted(generation, key=lambda n: next(e["timestamp"] for e in events if e["event_id"] == n))
            for row, node in enumerate(ordered):
                positions[node] = (col, row)
        by_id = {e["event_id"]: e for e in events}
        nodes = [{
            "id": n, "label": _short_label(by_id[n]), "event_type": by_id[n]["event_type"],
            "category": _event_category(by_id[n]), "outcome": by_id[n]["outcome"],
            "severity": by_id[n]["severity"], "timestamp": by_id[n]["timestamp"],
            "resource_id": by_id[n]["resource_id"], "actor": by_id[n]["actor"], "summary": by_id[n]["summary"],
            "policy_decision_id": by_id[n]["policy_decision_id"], "evidence_metadata": by_id[n]["evidence_metadata"],
            "column": positions[n][0], "row": positions[n][1],
        } for n in g.nodes]
        edges = [{"source": u, "target": v, "relation": d["relation"]} for u, v, d in g.edges(data=True)]
        return {"incident_id": incident["incident_id"], "nodes": nodes, "edges": edges,
                "derived_from": "persisted events (source_event_id links) and the incident evidence table",
                "is_dag": nx.is_directed_acyclic_graph(g)}

    # -- queries ---------------------------------------------------------------
    def _incident_row(self, incident_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
        if not row:
            raise NotFoundError(f"incident {incident_id} not found")
        return row

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT i.*, r.scenario, r.kind AS run_kind, "
                             "(SELECT COUNT(*) FROM incident_events ie WHERE ie.incident_id = i.incident_id) AS evidence_count "
                             "FROM incidents i JOIN runs r ON r.run_id = i.run_id ORDER BY i.created_at DESC")
        for r in rows:
            r["investigation_available"] = r["evidence_count"] > 0
        return rows

    def incident_events(self, incident_id: str) -> list[dict[str, Any]]:
        self._incident_row(incident_id)
        rows = self.db.query(
            "SELECT e.*, ie.role AS evidence_role FROM events e JOIN incident_events ie ON ie.event_id = e.event_id "
            "WHERE ie.incident_id = ? "
            "UNION ALL "
            "SELECT e.*, 'annotation' AS evidence_role FROM events e WHERE e.incident_id = ? "
            "AND e.event_id NOT IN (SELECT event_id FROM incident_events WHERE incident_id = ?) "
            "ORDER BY seq", (incident_id, incident_id, incident_id))
        return [deserialize_event(r) for r in rows]

    def report(self, incident_id: str) -> dict[str, Any]:
        incident = self._incident_row(incident_id)
        events = self.incident_events(incident_id)
        run_events = self._run_events(incident["run_id"])
        by_id = {e["event_id"]: e for e in run_events}
        by_source: dict[str, list[dict]] = {}
        for e in run_events:
            if e["source_event_id"]:
                by_source.setdefault(e["source_event_id"], []).append(e)

        attempts = []
        for req in (e for e in events if e.get("evidence_role") == "suspicious_request"):
            dec = next((e for e in by_source.get(req["event_id"], []) if e["event_type"] == "policy_decision"), None)
            res = next((e for e in by_source.get(dec["event_id"], []) if e["event_type"] == "tool_result"), None) if dec else None
            drow = self.db.query_one("SELECT * FROM policy_decisions WHERE decision_id = ?", (dec["policy_decision_id"],)) if dec else None
            attempts.append({
                "tool": req["action"], "resource_id": req["resource_id"],
                "requested_path": req["evidence_metadata"].get("requested_path"),
                "sensitivity": req["evidence_metadata"].get("resource_sensitivity"),
                "agent_reported_provenance": req["evidence_metadata"].get("agent_reported_provenance"),
                "requested_at": req["timestamp"],
                "decision": dec["outcome"] if dec else "missing",
                "decision_id": dec["policy_decision_id"] if dec else None,
                "rule_id": drow["rule_id"] if drow else None,
                "reason": drow["reason"] if drow else None,
                "matched_rules": loads(drow["matched_rules"]) if drow else [],
                "policy_version": drow["policy_version"] if drow else None,
                "content_returned": bool(res and res["evidence_metadata"].get("content_returned")),
                "bytes_returned": res["evidence_metadata"].get("bytes_returned", 0) if res else None,
                "request_event_id": req["event_id"], "decision_event_id": dec["event_id"] if dec else None,
                "result_event_id": res["event_id"] if res else None,
            })
        exposures = [e for e in events if e["event_type"] == "sensitive_data_exposed"]
        trigger = None
        if attempts:
            first_req = by_id[attempts[0]["request_event_id"]]
            trigger = self._trigger_for(first_req, by_id, run_events)

        findings: list[dict[str, Any]] = []
        for a in attempts:
            findings.append({"kind": "observed", "statement":
                             f"The agent requested {a['tool']} on '{a['resource_id']}' (requested path "
                             f"'{a['requested_path']}', classified {a['sensitivity']}).",
                             "evidence_event_ids": [a["request_event_id"]]})
            if a["decision_event_id"]:
                findings.append({"kind": "observed", "statement":
                                 f"The gateway returned {a['decision'].upper()} under rule {a['rule_id']} "
                                 f"(policy v{a['policy_version']}): {a['reason']}",
                                 "evidence_event_ids": [a["decision_event_id"]]})
            if a["result_event_id"]:
                findings.append({"kind": "observed", "statement":
                                 ("Content was returned to the agent." if a["content_returned"] else
                                  f"No content was returned to the agent ({a['bytes_returned']} bytes)."),
                                 "evidence_event_ids": [a["result_event_id"]]})
        if trigger:
            src = by_id[trigger["event_id"]]
            findings.append({"kind": "observed", "statement":
                             f"Before the request, the agent read '{trigger['resource_id']}'"
                             + ("; the gateway's content scanner flagged instruction-like text in it."
                                if trigger["content_flagged"] else "."),
                             "evidence_event_ids": [src["event_id"]]})
            if trigger["basis"] == "agent_reported_provenance":
                findings.append({"kind": "observed", "statement":
                                 f"The agent runtime reported the request originated from content in '{trigger['resource_id']}'.",
                                 "evidence_event_ids": [a["request_event_id"] for a in attempts]})
            findings.append({"kind": "inferred", "statement":
                             f"The instruction-like text in '{trigger['resource_id']}' most likely triggered the "
                             "restricted-resource request (simulated indirect prompt injection).",
                             "evidence_event_ids": [src["event_id"], *[a["request_event_id"] for a in attempts]],
                             "basis": trigger["basis"]})
        for e in exposures:
            findings.append({"kind": "observed", "statement": e["summary"], "evidence_event_ids": [e["event_id"]]})

        uncertainties = [
            "AFTERIMAGE does not observe a model's internal reasoning. The trigger is inferred from recorded "
            "provenance, ordering and content flags; it is not proof of intent.",
            "The exposure check covers content returned through the instrumented gateway in this run only; it "
            "cannot observe channels outside the gateway.",
        ]
        if trigger and trigger["basis"] == "temporal_proximity":
            uncertainties.append("No agent-reported provenance was recorded; the trigger was identified by temporal "
                                 "proximity only, which is weaker evidence.")
        if not trigger:
            uncertainties.append("No preceding input could be linked to the request; the trigger is unknown.")
        if any(a["decision_event_id"] is None for a in attempts):
            uncertainties.append("At least one request has no recorded policy decision (missing evidence).")

        exposed = bool(exposures) or any(a["content_returned"] for a in attempts)
        return {
            "incident": incident,
            "severity_meaning": SEVERITY_MEANING,
            "confidence_meaning": CONFIDENCE_MEANING,
            "summary": self._summary_text(incident, attempts, trigger, exposed),
            "trigger": trigger,
            "attempts": attempts,
            "sensitive_data_exposed": exposed,
            "findings": findings,
            "uncertainties": uncertainties,
            "recommendation": self.recommend(attempts, exposed),
            "evidence_event_ids": [e["event_id"] for e in events],
            "simulated": self.db.scalar("SELECT scenario FROM runs WHERE run_id = ?", (incident["run_id"],)) == "attack",
        }

    @staticmethod
    def _summary_text(incident: dict, attempts: list[dict], trigger: dict | None, exposed: bool) -> str:
        denied = sum(1 for a in attempts if a["decision"] != "allowed")
        text = (f"During run {incident['run_id']}, the demo agent made {len(attempts)} request(s) for resources "
                f"outside its legitimate task; {denied} were denied by the policy gateway before execution.")
        if trigger:
            text += f" The requests followed the agent reading '{trigger['resource_id']}'."
        text += " Protected content WAS exposed." if exposed else " No protected content was returned."
        return text

    def recommend(self, attempts: list[dict], exposed: bool) -> dict[str, Any]:
        wanted = ["restrict-read-scope", "deny-secret-class"]
        rationale = [
            "The baseline allows the agent to read ANY workspace file; only one exact path is protected. "
            "Least privilege limits reads to the files the summary task needs.",
            "Protecting the whole class of secret-like files means a renamed or copied secret is still denied.",
        ]
        if any(a["rule_id"] == "AI-BOUNDARY-001" for a in attempts):
            rationale.append("Path traversal attempts were already denied by the built-in workspace boundary rule.")
        if exposed:
            rationale.insert(0, "Protected content was exposed: apply these controls before running the task again.")
        active = self.policies.get(self.policies.active_version())
        pending = [c for c in wanted if apply_changes(active, [c]).model_dump() != active.model_dump()]
        return {
            "change_ids": pending,
            "already_applied": [c for c in wanted if c not in pending],
            "changes": [CHANGE_CATALOG[c].model_dump() for c in wanted],
            "rationale": rationale,
            "next_step": ("Preview and apply the recommended policy, then replay the scenario in the Replay Lab."
                          if pending else "The active policy already contains these controls. Run a replay to verify."),
        }

    def annotate(self, incident_id: str, text: str, status: str | None) -> dict[str, Any]:
        incident = self._incident_row(incident_id)
        if status is not None and status not in INCIDENT_STATUSES:
            raise ValidationFailure(f"status must be one of {', '.join(INCIDENT_STATUSES)}")
        opened = self.db.scalar("SELECT event_id FROM events WHERE incident_id = ? AND event_type = 'incident_opened'",
                                (incident_id,))
        with self.db.transaction() as conn:
            event = self.recorder.record(
                event_type="incident_annotation", actor="analyst", action="annotate", run_id=incident["run_id"],
                incident_id=incident_id, source_event_id=opened, outcome=status or "note", severity="info",
                summary=text, evidence={"previous_status": incident["status"], "new_status": status},
            )
            if status:
                conn.execute("UPDATE incidents SET status = ? WHERE incident_id = ?", (status, incident_id))
        return event
