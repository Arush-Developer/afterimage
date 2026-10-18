import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type AfterEvent, type Experiment } from "../api";
import { formatClock } from "../format";
import { Badge, Mono, OutcomeTag } from "./ui";

/** Live view of a running experiment. Shows only what the backend has already recorded:
 *  which runs exist and the policy decisions persisted for the run in progress. */
export function LiveProgress({ experiment }: { experiment: Experiment }) {
  const runs = experiment.progress.runs;
  const active = runs.find((r) => r.status === "running") ?? runs[runs.length - 1];
  const [decisions, setDecisions] = useState<AfterEvent[]>([]);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    const load = () => api.runEvents(active.run_id)
      .then((events) => alive && setDecisions(events.filter((e) => e.event_type === "policy_decision")))
      .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [active?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const done = runs.filter((r) => r.status !== "running").length;
  return (
    <div data-testid="live-progress" className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-ink-200">
        <Loader2 className="size-4 animate-spin text-accent-400" aria-hidden />
        {done} of {experiment.progress.total_runs} isolated run(s) finished
      </div>
      <ol className="flex flex-wrap gap-2">
        {runs.map((r, i) => (
          <li key={r.run_id} className="flex items-center gap-2 rounded-lg border border-ink-700 px-2.5 py-1.5 text-xs">
            <span className="text-ink-400">#{Math.floor(i / 2) + 1}</span>
            <Badge tone={r.enforcement === "baseline" ? "bad" : "good"}>{r.enforcement}</Badge>
            <span className={r.status === "running" ? "text-accent-300" : "text-ink-300"}>{r.status}</span>
          </li>
        ))}
      </ol>
      {active && (
        <div>
          <div className="mb-2 text-xs font-medium text-ink-400">
            Policy decisions recorded for <span className="font-mono">{active.run_id}</span> ({active.enforcement})
          </div>
          {decisions.length === 0 ? (
            <p className="text-sm text-ink-500">Waiting for the model's first tool call…</p>
          ) : (
            <ul className="scroll-thin max-h-64 divide-y divide-ink-800 overflow-y-auto rounded-lg border border-ink-800">
              {decisions.map((d) => (
                <li key={d.event_id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="font-mono text-[11px] text-ink-500">{formatClock(d.timestamp)}</span>
                  <Mono>{d.action}</Mono>
                  <span className="font-mono text-xs text-ink-300">{d.resource_id}</span>
                  <OutcomeTag outcome={d.outcome} />
                  <span className="font-mono text-xs text-ink-500">{String(d.evidence_metadata.rule_id ?? "")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
