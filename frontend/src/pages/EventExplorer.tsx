import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, Link2, ListTree } from "lucide-react";
import { api } from "../api";
import { formatTime, humanize } from "../format";
import { useApi } from "../hooks";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Mono, OutcomeTag, PageHeader } from "../components/ui";

const PAGE = 50;
const FILTERS = ["run_id", "incident_id", "event_type", "resource", "outcome"] as const;

export function EventExplorer() {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(FILTERS.map((f) => [f, params.get(f) ?? ""])) as Record<(typeof FILTERS)[number], string>;
  const offset = Number(params.get("offset") ?? 0) || 0;
  const key = params.toString();
  const page = useApi(() => api.events({ ...filters, limit: PAGE, offset }), [key]);
  const facets = useApi(api.eventFacets);
  const chain = useApi(api.verifyChain, [key]);
  const [expanded, setExpanded] = useState<string>();
  const [resource, setResource] = useState(filters.resource);

  const update = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    next.delete("offset");
    setParams(next);
  };
  const select = "w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-100 outline-none focus:border-accent-400";

  return (
    <div className="space-y-6">
      <PageHeader title="Event Explorer" description="Every recorded event from the append-only, hash-chained log. Audited and cryptographically verified against the local database."
        actions={chain.data && (
          <Badge tone={chain.data.valid ? "good" : "bad"} className="px-3 py-1 text-xs"><Link2 className="size-3.5" aria-hidden />
            {chain.data.valid ? `Hash chain intact · ${chain.data.checked} events` : `Hash chain broken at ${chain.data.first_invalid_event_id}`}</Badge>
        )} />

      <Card>
        <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-xs font-semibold text-ink-400">Run
            <select aria-label="Run" className={select} value={filters.run_id} onChange={(e) => update("run_id", e.target.value)}>
              <option value="">All runs</option>{facets.data?.runs.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-ink-400">Incident
            <select aria-label="Incident" className={select} value={filters.incident_id} onChange={(e) => update("incident_id", e.target.value)}>
              <option value="">All incidents</option>{facets.data?.incidents.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-ink-400">Event type
            <select aria-label="Event type" className={select} value={filters.event_type} onChange={(e) => update("event_type", e.target.value)}>
              <option value="">All types</option>{facets.data?.event_types.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-ink-400">Outcome
            <select aria-label="Outcome" className={select} value={filters.outcome} onChange={(e) => update("outcome", e.target.value)}>
              <option value="">All outcomes</option>{facets.data?.outcomes.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
            </select>
          </label>
          <form className="text-xs font-semibold text-ink-400" onSubmit={(e) => { e.preventDefault(); update("resource", resource.trim()); }}>
            <label>Resource contains
              <input aria-label="Resource" className={select} value={resource} onChange={(e) => setResource(e.target.value)} onBlur={() => update("resource", resource.trim())} placeholder="e.g. secret" />
            </label>
          </form>
        </div>
        {FILTERS.some((f) => filters[f]) && <Button variant="ghost" className="mt-3.5 text-xs text-ink-400" onClick={() => { setResource(""); setParams({}); }}>Clear filters</Button>}
      </Card>

      <Card bodyClassName="p-0" title={page.data ? `${page.data.total} event${page.data.total === 1 ? "" : "s"}` : "Events"} subtitle="Newest first. Expand a row for its full evidence record.">
        {page.error && <div className="p-4"><ErrorState message={page.error} onRetry={page.reload} /></div>}
        {page.loading && !page.data && <div className="px-5"><Loading /></div>}
        {page.data?.events.length === 0 && <div className="p-5"><EmptyState title="No events match" icon={<ListTree className="size-6" />}>Run a scenario or clear the filters.</EmptyState></div>}
        {page.data && page.data.events.length > 0 && (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="text-left text-xs font-semibold text-ink-400 bg-ink-950/40">
                <tr className="border-b border-ink-800/80"><th className="w-8" /><th className="py-2.5 px-3">Time</th><th className="py-2.5 pr-3">Type</th><th className="py-2.5 pr-3">Actor</th><th className="py-2.5 pr-3">Resource</th><th className="py-2.5 pr-3">Outcome</th><th className="py-2.5 pr-3">Severity</th><th className="py-2.5 pr-5">Summary</th></tr>
              </thead>
              <tbody className="divide-y divide-ink-800/60">
                {page.data.events.map((e) => (
                  <Fragment key={e.event_id}>
                    <tr className="cursor-pointer hover:bg-ink-850/50 transition-colors" onClick={() => setExpanded(expanded === e.event_id ? undefined : e.event_id)}>
                      <td className="pl-3 text-ink-500">
                        <button aria-label={expanded === e.event_id ? "Collapse" : "Expand"} aria-expanded={expanded === e.event_id}>
                          {expanded === e.event_id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                        </button>
                      </td>
                      <td className="py-3 px-3 text-xs whitespace-nowrap text-ink-300 font-mono">{formatTime(e.timestamp)}</td>
                      <td className="pr-3 text-xs font-semibold text-ink-200">{humanize(e.event_type)}</td>
                      <td className="pr-3 text-xs text-ink-400 font-mono">{e.actor}</td>
                      <td className="max-w-[200px] truncate pr-3 font-mono text-xs text-ink-300">{e.resource_id ?? "—"}</td>
                      <td className="pr-3"><OutcomeTag outcome={e.outcome} /></td>
                      <td className="pr-3 text-xs capitalize text-ink-300">{e.severity}</td>
                      <td className="max-w-[360px] truncate pr-5 text-ink-200 text-xs">{e.summary}</td>
                    </tr>
                    {expanded === e.event_id && (
                      <tr className="bg-ink-950/80">
                        <td />
                        <td colSpan={7} className="py-4 pr-5">
                          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3 font-mono text-ink-300">
                            <span>Event <Mono>{e.event_id}</Mono></span>
                            <span>Run {e.run_id ? <Mono>{e.run_id}</Mono> : "—"}</span>
                            <span>Source event {e.source_event_id ? <Mono>{e.source_event_id}</Mono> : "—"}</span>
                            <span>Policy decision {e.policy_decision_id ? <Mono>{e.policy_decision_id}</Mono> : "—"}</span>
                            <span>UTC <span className="text-ink-400">{e.timestamp}</span></span>
                            <span>Hash <span className="text-ink-400">{e.event_hash.slice(0, 20)}…</span></span>
                          </div>
                          <pre className="scroll-thin mt-3 max-h-60 overflow-auto rounded-lg bg-ink-900/90 p-3.5 font-mono text-[11px] text-ink-300 border border-ink-800/80">{JSON.stringify(e.evidence_metadata, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page.data && page.data.total > PAGE && (
          <div className="flex items-center justify-between border-t border-ink-800/80 px-5 py-3 text-sm text-ink-400 font-mono">
            <span>{offset + 1}–{Math.min(offset + PAGE, page.data.total)} of {page.data.total}</span>
            <div className="flex gap-2">
              <Button variant="ghost" disabled={offset === 0} onClick={() => { const n = new URLSearchParams(params); n.set("offset", String(Math.max(0, offset - PAGE))); setParams(n); }}>Previous</Button>
              <Button variant="ghost" disabled={offset + PAGE >= page.data.total} onClick={() => { const n = new URLSearchParams(params); n.set("offset", String(offset + PAGE)); setParams(n); }}>Next</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
