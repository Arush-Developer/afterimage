import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Eye, FlaskConical, HelpCircle, Lightbulb, MessageSquarePlus, Network, Shield } from "lucide-react";
import { api, type AfterEvent, type GraphNode } from "../api";
import { formatClock, formatTime, humanize } from "../format";
import { useAction, useApi } from "../hooks";
import { AiExplanationCard } from "../components/AiExplanationCard";
import { EventGraph, GraphLegend } from "../components/EventGraph";
import {
  Badge, Button, Card, CategoryBadge, EmptyState, ErrorState, InlineError, KeyValue, Loading, Mono, OutcomeTag,
  PageHeader, PassFail, SeverityBadge, SimulatedNotice, cx,
} from "../components/ui";

export function Investigation() {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const incidents = useApi(api.incidents);

  useEffect(() => {
    if (!incidentId && incidents.data && incidents.data.length > 0) {
      navigate(`/investigation/${incidents.data[0].incident_id}`, { replace: true });
    }
  }, [incidentId, incidents.data, navigate]);

  if (!incidentId) {
    return (
      <div>
        <PageHeader title="Investigation" description="Evidence-based reconstruction of an incident from recorded events." />
        {incidents.error && <ErrorState message={incidents.error} onRetry={incidents.reload} />}
        {incidents.loading && <Loading />}
        {incidents.data?.length === 0 && (
          <EmptyState title="Nothing to investigate yet" icon={<Network className="size-6" />}>
            Run <Link className="text-accent-300 underline" to="/">Simulate Attack</Link> to create a recorded incident.
          </EmptyState>
        )}
      </div>
    );
  }
  return <IncidentWorkspace key={incidentId} incidentId={incidentId} incidentIds={incidents.data?.map((i) => i.incident_id) ?? []} />;
}

function IncidentWorkspace({ incidentId, incidentIds }: { incidentId: string; incidentIds: string[] }) {
  const navigate = useNavigate();
  const report = useApi(() => api.incident(incidentId), [incidentId]);
  const graph = useApi(() => api.incidentGraph(incidentId), [incidentId]);
  const events = useApi(() => api.incidentEvents(incidentId), [incidentId]);
  const [selected, setSelected] = useState<string>();

  const nodesById = useMemo(() => new Map((graph.data?.nodes ?? []).map((n) => [n.id, n])), [graph.data]);
  const eventsById = useMemo(() => new Map((events.data ?? []).map((e) => [e.event_id, e])), [events.data]);
  useEffect(() => {
    if (!selected && report.data?.attempts[0]?.decision_event_id) setSelected(report.data.attempts[0].decision_event_id);
  }, [report.data, selected]);

  const error = report.error || graph.error || events.error;
  if (error) return <ErrorState message={error} onRetry={() => { void report.reload(); void graph.reload(); void events.reload(); }} />;
  if (!report.data || !graph.data || !events.data) return <Loading label="Loading recorded evidence…" />;

  const r = report.data;
  const inc = r.incident;
  const primary = r.attempts[0];
  const selectedEvent = selected ? eventsById.get(selected) : undefined;
  const selectedNode = selected ? nodesById.get(selected) : undefined;
  const remediateHref = `/policies?changes=${r.recommendation.change_ids.join(",")}&incident=${inc.incident_id}`;

  return (
    <div className="space-y-6">
      <PageHeader
        title={inc.title}
        description={<span className="font-mono text-xs">{inc.incident_id} · run {inc.run_id}</span>}
        actions={<>
          {incidentIds.length > 1 && (
            <select aria-label="Select incident" value={incidentId} onChange={(e) => navigate(`/investigation/${e.target.value}`)}
              className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-xs">
              {incidentIds.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
          )}
          <Button onClick={() => navigate(remediateHref)} icon={<Shield className="size-4" />}>Remediate</Button>
          <Button variant="primary" onClick={() => navigate(`/replay?incident=${inc.incident_id}`)} icon={<FlaskConical className="size-4" />}>Replay & verify</Button>
        </>}
      />
      {r.simulated && <SimulatedNotice>Controlled simulated attack: the demo agent was deliberately configured to follow instructions embedded in a synthetic document. This is not a real-world intrusion.</SimulatedNotice>}

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card title="Incident summary">
          <p className="text-sm leading-relaxed text-ink-200">{r.summary}</p>
          <div className="mt-5">
            <KeyValue items={[
              ["Severity", <span className="flex flex-wrap items-center gap-2"><SeverityBadge severity={inc.severity} /><span className="text-xs text-ink-400">{r.severity_meaning}</span></span>],
              ["Confidence", <span className="flex flex-wrap items-center gap-2"><Badge tone="accent" className="capitalize">{inc.confidence}</Badge><span className="text-xs text-ink-400">{r.confidence_meaning}</span></span>],
              ["Status", <Badge tone={inc.status === "exposure_confirmed" ? "bad" : inc.status === "contained" ? "good" : "neutral"}>{humanize(inc.status)}</Badge>],
              ["Sensitive data exposed", <PassFail passed={!r.sensitive_data_exposed} label={r.sensitive_data_exposed ? "Yes" : "No"} />],
              ["First observed event", formatTime(inc.first_event_at)],
              ["Last observed event", formatTime(inc.last_event_at)],
              ["Triggering input", r.trigger ? <span><Mono>{r.trigger.resource_id}</Mono> <span className="text-xs text-ink-400">({humanize(r.trigger.basis)})</span></span> : "Unknown"],
              ["Attempted tool invocation", primary ? <Mono>{primary.tool}("{primary.requested_path}")</Mono> : "—"],
              ["Requested resource", primary ? <Mono>{primary.resource_id}</Mono> : "—"],
              ["Policy decision & rule", primary ? <span className="flex flex-wrap items-center gap-2"><OutcomeTag outcome={primary.decision} /><Mono>{primary.rule_id}</Mono></span> : "—"],
            ]} />
          </div>
        </Card>

        <Card title="Event details" subtitle="Select a node in the graph or an entry in the timeline.">
          {selectedEvent ? <EventDetail event={selectedEvent} node={selectedNode} /> : <EmptyState title="No event selected" icon={<Eye className="size-6" />} />}
        </Card>
      </div>

      <Card title="Evidence graph" subtitle={`Generated from ${graph.data.nodes.length} persisted events and ${graph.data.edges.length} recorded links (${graph.data.derived_from}).`} actions={<GraphLegend />}>
        <EventGraph graph={graph.data} selectedId={selected} onSelect={setSelected} />
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Event timeline" subtitle="Chronological, from the append-only event log." bodyClassName="p-0">
          <ol className="scroll-thin max-h-[520px] overflow-y-auto">
            {events.data.map((e) => (
              <li key={e.event_id}>
                <button onClick={() => setSelected(e.event_id)} aria-current={selected === e.event_id}
                  className={cx("grid w-full grid-cols-[86px_1fr] gap-3 border-l-2 px-5 py-2.5 text-left hover:bg-ink-850",
                    selected === e.event_id ? "border-accent-400 bg-ink-850" : "border-transparent")}>
                  <span className="pt-0.5 font-mono text-[11px] text-ink-400">{formatClock(e.timestamp)}</span>
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium text-ink-300">{humanize(e.event_type)}</span>
                      <OutcomeTag outcome={e.outcome} />
                      {e.evidence_role && e.evidence_role !== "context" && <Badge tone={e.evidence_role === "suspicious_request" ? "warn" : "neutral"}>{humanize(e.evidence_role)}</Badge>}
                    </span>
                    <span className="mt-0.5 block truncate text-sm text-ink-100">{e.summary}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Policy evaluation" subtitle="Decisions recorded by the server-side gateway before any content was read.">
          <div className="space-y-4">
            {r.attempts.map((a) => (
              <div key={a.request_event_id} className="rounded-lg border border-ink-700 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Mono>{a.tool}("{a.requested_path}")</Mono>
                  <OutcomeTag outcome={a.decision} />
                </div>
                <KeyValue items={[
                  ["Canonical resource", <Mono>{a.resource_id}</Mono>],
                  ["Classification", humanize(a.sensitivity)],
                  ["Rule", <Mono>{a.rule_id}</Mono>],
                  ["Policy version", `v${a.policy_version}`],
                  ["Content returned", a.content_returned ? "Yes" : `No (${a.bytes_returned ?? 0} bytes)`],
                  ["Other matching rules", a.matched_rules.filter((m) => m !== a.rule_id).join(", ") || "none"],
                ]} />
                <p className="mt-3 text-xs text-ink-400">{a.reason}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {[a.request_event_id, a.decision_event_id, a.result_event_id].filter(Boolean).map((id) => (
                    <EvidenceChip key={id} id={id!} onSelect={setSelected} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Findings" subtitle="Observed = directly recorded. Inferred = a conclusion drawn from observations, not proof.">
          <ul className="space-y-3">
            {r.findings.map((f, i) => (
              <li key={i} className="flex gap-3">
                <Badge tone={f.kind === "observed" ? "neutral" : "warn"} className="h-fit shrink-0 uppercase tracking-wide">{f.kind}</Badge>
                <div className="min-w-0">
                  <p className="text-sm text-ink-200">{f.statement}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">{f.evidence_event_ids.map((id) => <EvidenceChip key={id} id={id} onSelect={setSelected} />)}</div>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-6">
          <Card title={<span className="flex items-center gap-2"><Lightbulb className="size-4 text-accent-400" aria-hidden />Recommended mitigation</span>}>
            <ul className="space-y-2">
              {r.recommendation.changes.map((c) => (
                <li key={c.change_id} className="rounded-lg border border-ink-700 p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {c.title}
                    {r.recommendation.already_applied.includes(c.change_id) && <Badge tone="good">already active</Badge>}
                  </div>
                  <p className="mt-1 text-xs text-ink-400">{c.explanation}</p>
                </li>
              ))}
            </ul>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-400">{r.recommendation.rationale.map((x, i) => <li key={i}>{x}</li>)}</ul>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-300">{r.recommendation.next_step}</p>
              {r.recommendation.change_ids.length > 0
                ? <Button variant="primary" onClick={() => navigate(remediateHref)} icon={<ArrowRight className="size-4" />}>Review policy change</Button>
                : <Button variant="primary" onClick={() => navigate(`/replay?incident=${inc.incident_id}`)} icon={<FlaskConical className="size-4" />}>Replay</Button>}
            </div>
          </Card>

          <Card title={<span className="flex items-center gap-2"><HelpCircle className="size-4 text-amber-300" aria-hidden />Uncertainty & missing evidence</span>}>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-300">{r.uncertainties.map((u, i) => <li key={i}>{u}</li>)}</ul>
          </Card>

          <AiExplanationCard incidentId={inc.incident_id} onSelect={setSelected} />

          <AnnotationForm incidentId={inc.incident_id} onSaved={() => { void events.reload(); void report.reload(); }} />
        </div>
      </div>
    </div>
  );
}

function EvidenceChip({ id, onSelect }: { id: string; onSelect: (id: string) => void }) {
  return (
    <button onClick={() => onSelect(id)} className="rounded border border-ink-700 bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-ink-300 hover:border-accent-500/50 hover:text-accent-300">
      {id}
    </button>
  );
}

function EventDetail({ event, node }: { event: AfterEvent; node?: GraphNode }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {node && <CategoryBadge category={node.category} />}
        <span className="text-sm font-medium">{humanize(event.event_type)}</span>
      </div>
      <p className="text-sm text-ink-200">{event.summary}</p>
      <KeyValue items={[
        ["Event ID", <Mono>{event.event_id}</Mono>],
        ["Timestamp (UTC)", <span className="font-mono text-xs">{event.timestamp}</span>],
        ["Actor", event.actor],
        ["Action", event.action],
        ["Outcome", <OutcomeTag outcome={event.outcome} />],
        ["Resource", event.resource_id ? <Mono>{event.resource_id}</Mono> : "—"],
        ["Caused by (source event)", event.source_event_id ? <Mono>{event.source_event_id}</Mono> : "—"],
        ["Policy decision", event.policy_decision_id ? <Mono>{event.policy_decision_id}</Mono> : "—"],
      ]} />
      <div>
        <div className="mb-1 text-xs font-medium text-ink-400">Evidence metadata</div>
        <pre className="scroll-thin max-h-56 overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-relaxed text-ink-300">{JSON.stringify(event.evidence_metadata, null, 2)}</pre>
      </div>
      <div className="text-[11px] text-ink-500">Event hash <span className="font-mono">{event.event_hash.slice(0, 24)}…</span></div>
    </div>
  );
}

function AnnotationForm({ incidentId, onSaved }: { incidentId: string; onSaved: () => void }) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const save = useAction(async () => {
    await api.annotate(incidentId, text.trim(), status || undefined);
    setText("");
    setStatus("");
    onSaved();
  });
  return (
    <Card title={<span className="flex items-center gap-2"><MessageSquarePlus className="size-4 text-ink-400" aria-hidden />Analyst note</span>}
      subtitle="Notes and status changes are appended as new events; history is never overwritten.">
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) void save.run(); }} className="space-y-3">
        <textarea aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={2} placeholder="e.g. Reviewed — attack contained by gateway."
          className="w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm placeholder:text-ink-500" />
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Status change" value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
            <option value="">No status change</option>
            {["investigating", "contained", "resolved"].map((s) => <option key={s} value={s}>Set status: {s}</option>)}
          </select>
          <Button type="submit" pending={save.pending} disabled={!text.trim()}>Append note</Button>
        </div>
        <InlineError message={save.error} onDismiss={save.clearError} />
      </form>
    </Card>
  );
}
