import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, ShieldAlert } from "lucide-react";
import { api, type Severity } from "../api";
import { formatTime, humanize } from "../format";
import { useApi } from "../hooks";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader, SeverityBadge } from "../components/ui";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

export function Incidents() {
  const navigate = useNavigate();
  const incidents = useApi(api.incidents);
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");

  const statuses = useMemo(() => [...new Set((incidents.data ?? []).map((i) => i.status))].sort(), [incidents.data]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (incidents.data ?? []).filter((i) =>
      (!severity || i.severity === severity) && (!status || i.status === status) &&
      (!q || [i.title, i.incident_id, i.run_id, i.resource_id, i.incident_type, i.rule_id].some((v) => v?.toLowerCase().includes(q))));
  }, [incidents.data, query, severity, status]);

  const select = "rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-100";
  return (
    <div>
      <PageHeader title="Incidents" description="Incidents are opened automatically when a run records a request for a restricted resource, a workspace-boundary violation, or a data exposure." />
      <Card bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-ink-800 p-4">
          <label className="relative min-w-[220px] flex-1">
            <span className="sr-only">Search incidents</span>
            <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-ink-500" aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search title, ID, resource, rule…"
              className="w-full rounded-lg border border-ink-700 bg-ink-900 py-2 pr-3 pl-9 text-sm text-ink-100 placeholder:text-ink-500" />
          </label>
          <label className="text-sm"><span className="sr-only">Severity</span>
            <select aria-label="Filter by severity" className={select} value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">All severities</option>{SEVERITIES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
          </label>
          <label className="text-sm"><span className="sr-only">Status</span>
            <select aria-label="Filter by status" className={select} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>{statuses.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
          </label>
        </div>
        {incidents.error && <div className="p-4"><ErrorState message={incidents.error} onRetry={incidents.reload} /></div>}
        {incidents.loading && !incidents.data && <div className="px-5"><Loading /></div>}
        {incidents.data && rows.length === 0 && (
          <div className="p-5">
            <EmptyState title={incidents.data.length ? "No incidents match these filters" : "No incidents recorded"} icon={<ShieldAlert className="size-6" />}>
              {incidents.data.length ? "Clear the search or filters." : "Run the attack simulation from the Overview page."}
            </EmptyState>
          </div>
        )}
        {rows.length > 0 && (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[960px] text-sm">
              <thead className="text-left text-xs text-ink-400">
                <tr className="border-b border-ink-800">
                  <th className="px-5 py-2.5 font-medium">Severity</th><th className="font-medium">Incident</th><th className="font-medium">Resource</th>
                  <th className="font-medium">Detected</th><th className="font-medium">Run</th><th className="font-medium">Status</th><th className="pr-5 font-medium">Investigation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {rows.map((i) => (
                  <tr key={i.incident_id} tabIndex={0} onClick={() => navigate(`/investigation/${i.incident_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/investigation/${i.incident_id}`)}
                    className="cursor-pointer hover:bg-ink-850">
                    <td className="px-5 py-3"><SeverityBadge severity={i.severity} /></td>
                    <td className="max-w-[340px]">
                      <div className="truncate text-ink-100">{i.title}</div>
                      <div className="text-xs text-ink-400">{humanize(i.incident_type)} · <span className="font-mono">{i.incident_id}</span></div>
                    </td>
                    <td className="font-mono text-xs">{i.resource_id}</td>
                    <td className="text-ink-300">{formatTime(i.created_at)}</td>
                    <td><span className="font-mono text-xs">{i.run_id}</span>{i.run_kind === "replay" && <Badge className="ml-2" tone="accent">replay</Badge>}</td>
                    <td><Badge tone={i.status === "exposure_confirmed" ? "bad" : i.status === "contained" ? "good" : "neutral"}>{humanize(i.status)}</Badge></td>
                    <td className="pr-5">{i.investigation_available ? <span className="text-accent-300">Open · {i.evidence_count} events</span> : <span className="text-ink-500">No evidence</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
