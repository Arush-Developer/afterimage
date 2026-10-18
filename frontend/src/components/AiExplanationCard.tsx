import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api, type AiExplanation } from "../api";
import { formatTime } from "../format";
import { useAction, useApi } from "../hooks";
import { Badge, Button, Card, InlineError } from "./ui";

/** Optional LLM-written explanation of an incident. Every statement shown cites recorded
 *  event IDs; the backend drops claims citing unknown or no IDs before they reach the UI. */
export function AiExplanationCard({ incidentId, onSelect }: { incidentId: string; onSelect: (eventId: string) => void }) {
  const providers = useApi(api.providers);
  const saved = useApi(() => api.incidentExplanation(incidentId), [incidentId]);
  const [fresh, setFresh] = useState<AiExplanation>();
  const realConfigured = (providers.data?.providers ?? []).filter((p) => p.real && p.configured);
  const [provider, setProvider] = useState<string>();
  const chosen = provider ?? realConfigured[0]?.provider;
  const explain = useAction(async () => {
    if (!chosen) return;
    setFresh(await api.explainIncident(incidentId, { provider: chosen }));
  });
  const ex = fresh ?? saved.data?.explanation ?? undefined;

  const chips = (ids: string[]) => (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {ids.map((id) => (
        <button key={id} onClick={() => onSelect(id)}
          className="rounded border border-ink-700 bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-ink-300 hover:border-accent-500/50 hover:text-accent-300">
          {id}
        </button>
      ))}
    </div>
  );

  return (
    <Card title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-accent-400" aria-hidden />AI-assisted explanation</span>}
      subtitle="Optional. Written by a language model from the recorded evidence; every statement must cite event IDs."
      actions={realConfigured.length > 0 && (
        <div className="flex items-center gap-2">
          {realConfigured.length > 1 && (
            <select aria-label="Explanation provider" value={chosen} onChange={(e) => setProvider(e.target.value)}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs">
              {realConfigured.map((p) => <option key={p.provider} value={p.provider}>{p.label}</option>)}
            </select>
          )}
          <Button onClick={() => void explain.run()} pending={explain.pending}>{ex ? "Regenerate" : "Generate"}</Button>
        </div>
      )}>
      {providers.data && realConfigured.length === 0 && !ex && (
        <p className="text-sm text-ink-400">No real LLM provider is configured, so no AI explanation is available. The rule-based findings above are the deterministic explanation. Configure a provider in the backend environment to enable this.</p>
      )}
      <InlineError message={explain.error} onDismiss={explain.clearError} />
      {ex && (
        <div className="space-y-4" data-testid="ai-explanation">
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-400">
            <Badge tone="accent">{ex.provider} · {ex.model}</Badge>
            {ex.created_at && <span>{formatTime(ex.created_at)}</span>}
            <span>stored as event <span className="font-mono">{ex.event_id}</span></span>
          </div>
          {ex.summary && <p className="text-sm text-ink-200">{ex.summary}</p>}
          <section>
            <h3 className="text-xs font-semibold tracking-wide text-ink-400 uppercase">Observed (cited)</h3>
            <ul className="mt-1 space-y-2">{ex.observed.map((o, i) => <li key={i} className="text-sm text-ink-200">{o.statement}{chips(o.event_ids)}</li>)}</ul>
            {ex.observed.length === 0 && <p className="text-sm text-ink-500">None.</p>}
          </section>
          <section>
            <h3 className="text-xs font-semibold tracking-wide text-amber-300/80 uppercase">Hypotheses</h3>
            <ul className="mt-1 space-y-2">{ex.hypotheses.map((o, i) => <li key={i} className="text-sm text-ink-200">{o.statement}{chips(o.event_ids)}</li>)}</ul>
            {ex.hypotheses.length === 0 && <p className="text-sm text-ink-500">None.</p>}
          </section>
          <section>
            <h3 className="text-xs font-semibold tracking-wide text-ink-400 uppercase">Uncertainty</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-300">{ex.uncertainty.map((u, i) => <li key={i}>{u}</li>)}</ul>
          </section>
          {ex.rejected_claims.length > 0 && (
            <p className="text-xs text-amber-200">{ex.rejected_claims.length} claim(s) were rejected because they cited unknown or no event IDs.</p>
          )}
        </div>
      )}
    </Card>
  );
}
