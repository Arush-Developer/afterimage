"""AI-assisted incident explanation, grounded in persisted evidence.

The model receives only the incident's persisted (already redacted) event records and
must answer through a structured `submit_explanation` tool. Every statement has to cite
event IDs from that evidence set. The server then validates the answer:

  * statements citing no event IDs, or any ID outside the incident's evidence, are
    rejected (kept in `rejected_claims`, never shown as findings);
  * observed facts and hypotheses stay in separate lists;
  * uncertainty is always included, with a fixed caveat added by the server.

The explanation never changes the incident's facts: tool calls, decisions and outcomes
come only from the event log. The validated result is appended as an `ai_explanation`
event, so it is part of the auditable record.
"""

from __future__ import annotations

from typing import Any

from .common import ValidationFailure
from .db import Database
from .investigator import Investigator
from .providers import LLMProvider, ProviderError, ToolSpec, Turn
from .recorder import EventRecorder

MAX_EVIDENCE_EVENTS = 60
MAX_STATEMENTS = 12

SYSTEM = (
    "You are a security analyst assistant. Explain an incident using ONLY the evidence records provided. "
    "Every statement must cite one or more event_id values from the evidence. Put directly recorded facts in "
    "'observed' and conclusions or causal explanations in 'hypotheses'. State what the evidence cannot show in "
    "'uncertainty'. Do not invent tool calls, outcomes, policy decisions or event IDs. "
    "Answer by calling the submit_explanation tool exactly once."
)

_STATEMENT = {
    "type": "object",
    "properties": {"statement": {"type": "string"}, "event_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["statement", "event_ids"],
    "additionalProperties": False,
}
EXPLAIN_TOOL = ToolSpec(
    name="submit_explanation",
    description="Submit the grounded incident explanation.",
    input_schema={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "observed": {"type": "array", "items": _STATEMENT},
            "hypotheses": {"type": "array", "items": _STATEMENT},
            "uncertainty": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "observed", "hypotheses", "uncertainty"],
        "additionalProperties": False,
    },
)

SERVER_CAVEAT = ("This explanation was written by a language model from the recorded evidence. Statements that "
                 "cited unknown or no event IDs were removed. It does not observe any model's internal reasoning.")


def _evidence_lines(events: list[dict[str, Any]]) -> str:
    lines = []
    for e in events[:MAX_EVIDENCE_EVENTS]:
        meta = e.get("evidence_metadata") or {}
        rule = meta.get("rule_id")
        lines.append(
            f"- event_id={e['event_id']} time={e['timestamp']} type={e['event_type']} actor={e['actor']} "
            f"action={e['action']} resource={e.get('resource_id') or '-'} outcome={e['outcome']}"
            + (f" rule={rule}" if rule else "")
            + f" summary={e['summary']!r}"
        )
    return "\n".join(lines)


def _validate(items: Any, known: set[str], kind: str, rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in (items if isinstance(items, list) else [])[:MAX_STATEMENTS]:
        if not isinstance(item, dict) or not isinstance(item.get("statement"), str):
            continue
        ids = [i for i in item.get("event_ids", []) if isinstance(i, str)]
        unknown = [i for i in ids if i not in known]
        if not ids or unknown:
            rejected.append({"kind": kind, "statement": item["statement"][:500], "unknown_event_ids": unknown,
                             "reason": "cited unknown event IDs" if unknown else "cited no event IDs"})
            continue
        out.append({"statement": item["statement"][:1000], "event_ids": ids})
    return out


class IncidentExplainer:
    def __init__(self, db: Database, recorder: EventRecorder, investigator: Investigator):
        self.db = db
        self.recorder = recorder
        self.investigator = investigator

    def explain(self, incident_id: str, provider: LLMProvider, *, max_tokens: int, timeout: float) -> dict[str, Any]:
        if not provider.is_real:
            raise ValidationFailure("AI explanations need a real language model provider; the rule-based "
                                    "report on this page is the deterministic explanation")
        incident = self.investigator.report(incident_id)["incident"]
        events = self.investigator.incident_events(incident_id)
        known = {e["event_id"] for e in events}
        prompt = (f"Incident {incident_id}: {incident['title']} (severity {incident['severity']}, "
                  f"status {incident['status']}).\n\nEvidence records:\n{_evidence_lines(events)}")
        response = provider.complete(system=SYSTEM, turns=[Turn("user", text=prompt)], tools=[EXPLAIN_TOOL],
                                     max_tokens=max_tokens, timeout=timeout)
        call = next((c for c in response.tool_calls if c.name == "submit_explanation"), None)
        if call is None:
            raise ProviderError("the model did not return a structured explanation", kind="bad_response")

        args = call.arguments
        rejected: list[dict[str, Any]] = []
        observed = _validate(args.get("observed"), known, "observed", rejected)
        hypotheses = _validate(args.get("hypotheses"), known, "hypothesis", rejected)
        uncertainty = [u[:500] for u in args.get("uncertainty", []) if isinstance(u, str)][:MAX_STATEMENTS]
        if not observed and not hypotheses:
            uncertainty.append("The model produced no statements that could be tied to recorded evidence.")
        result = {
            "incident_id": incident_id,
            "provider": provider.name,
            "model": provider.model,
            "summary": str(args.get("summary", ""))[:1500],
            "observed": observed,
            "hypotheses": hypotheses,
            "uncertainty": uncertainty + [SERVER_CAVEAT],
            "rejected_claims": rejected,
        }
        opened = next((e["event_id"] for e in events if e["event_type"] == "incident_opened"), None)
        event = self.recorder.record(
            event_type="ai_explanation", actor="explainer", action="explain_incident", run_id=incident["run_id"],
            incident_id=incident_id, source_event_id=opened, outcome="validated", severity="info",
            summary=(f"AI explanation by {provider.name}/{provider.model}: {len(observed)} observed, "
                     f"{len(hypotheses)} hypotheses, {len(rejected)} rejected claim(s)."),
            evidence=result,
        )
        result["event_id"] = event["event_id"]
        return result

    def latest(self, incident_id: str) -> dict[str, Any] | None:
        self.investigator.report(incident_id)  # 404 if unknown
        row = self.db.query_one(
            "SELECT * FROM events WHERE incident_id = ? AND event_type = 'ai_explanation' ORDER BY seq DESC LIMIT 1",
            (incident_id,))
        if not row:
            return None
        from .recorder import deserialize_event
        event = deserialize_event(row)
        return {**event["evidence_metadata"], "event_id": event["event_id"], "created_at": event["timestamp"]}
