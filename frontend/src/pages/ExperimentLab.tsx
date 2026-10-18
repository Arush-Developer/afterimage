import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, FlaskConical, ShieldCheck, ShieldX } from "lucide-react";
import { api, type Experiment, type ExperimentReport, type TrialAggregate } from "../api";
import { formatTime, relativeTime } from "../format";
import { useAction, useApi } from "../hooks";
import { ProviderPicker, type ProviderSelection } from "../components/ProviderPicker";
import { CollapsibleTranscript } from "../components/Transcript";
import {
  Badge, Button, Card, EmptyState, ErrorState, InlineError, Loading, Mono, PageHeader, PassFail, SimulatedNotice, cx,
} from "../components/ui";

function VerdictBanner({ report }: { report: ExperimentReport }) {
  const cfg = {
    protected: { icon: ShieldCheck, cls: "border-emerald-400/30 bg-emerald-500/10 text-emerald-100", title: "Protected" },
    attack_not_reproduced: { icon: AlertTriangle, cls: "border-amber-400/30 bg-amber-500/10 text-amber-100", title: "Attack not reproduced" },
    protection_failed: { icon: ShieldX, cls: "border-rose-400/30 bg-rose-500/10 text-rose-100", title: "Protection failed" },
  }[report.verdict];
  const Icon = cfg.icon;
  return (
    <div role="status" data-testid="experiment-verdict" className={cx("flex items-start gap-3 rounded-xl border p-4", cfg.cls)}>
      <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>
        <div className="font-semibold">{cfg.title}</div>
        <p className="mt-0.5 text-sm opacity-90">{report.headline}</p>
      </div>
    </div>
  );
}

function AggColumn({ title, agg, tone, subtitle }: { title: string; agg: TrialAggregate; tone: "bad" | "good"; subtitle: string }) {
  const rows: [string, number][] = [
    ["Restricted file requested", agg.restricted_file_requested],
    ["Restricted content returned to agent", agg.restricted_content_returned],
    ["Fake secret leaked", agg.secret_leaked],
    ["Legitimate task completed", agg.legitimate_task_completed],
  ];
  return (
    <div className={cx("rounded-lg border p-4", tone === "bad" ? "border-rose-400/20" : "border-emerald-400/20")}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Badge tone={tone === "bad" ? "bad" : "good"}>{tone === "bad" ? "enforcement OFF" : "enforcement ON"}</Badge>
      </div>
      <p className="mt-1 text-xs text-ink-400">{subtitle}</p>
      <dl className="mt-3 space-y-2">
        {rows.map(([label, n]) => {
          const bad = (label.includes("Restricted content") || label.includes("leaked")) && n > 0;
          return (
            <div key={label} className="flex items-center justify-between gap-3 text-sm">
              <dt className="text-ink-300">{label}</dt>
              <dd className={cx("font-mono tabular-nums", bad ? "text-rose-300" : "text-ink-100")}>
                {n} / {agg.completed_trials}
              </dd>
            </div>
          );
        })}
      </dl>
      {agg.errored_trials > 0 && <p className="mt-2 text-xs text-amber-300">{agg.errored_trials} trial(s) errored.</p>}
    </div>
  );
}

function TrialTable({ title, trials }: { title: string; trials: ExperimentReport["baseline_trials"] }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold tracking-wide text-ink-400 uppercase">{title}</h4>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-xs text-ink-400">
            <tr className="border-b border-ink-800">
              <th className="py-2 font-medium">Run</th><th className="font-medium">Requested</th>
              <th className="font-medium">Returned</th><th className="font-medium">Leaked</th>
              <th className="font-medium">Task</th><th className="font-medium">Rules</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {trials.map((t) => (
              <tr key={t.run_id}>
                <td className="py-2"><Link to={`/events?run_id=${t.run_id}`} className="font-mono text-xs text-accent-300 hover:underline">{t.run_id.slice(0, 12)}…</Link></td>
                <td>{t.restricted_file_requested ? "yes" : "no"}</td>
                <td className={t.restricted_content_returned ? "text-rose-300" : ""}>{t.restricted_content_returned ? "YES" : "no"}</td>
                <td className={t.secret_leaked ? "text-rose-300" : ""}>{t.secret_leaked ? "YES" : "no"}</td>
                <td><PassFail passed={t.legitimate_task_completed} label={t.legitimate_task_completed ? "done" : "no"} /></td>
                <td className="font-mono text-xs">{t.rules_responsible.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ExperimentLab() {
  const [params, setParams] = useSearchParams();
  const providers = useApi(api.providers);
  const list = useApi(api.experiments);
  const [selection, setSelection] = useState<ProviderSelection>();
  const [trials, setTrials] = useState(1);
  const [current, setCurrent] = useState<Experiment>();

  useEffect(() => {
    if (!selection && providers.data) {
      const p = providers.data.default_provider;
      setSelection({ provider: p, model: providers.data.default_models[p] ?? "" });
    }
  }, [providers.data, selection]);

  useEffect(() => {
    const id = params.get("id");
    if (id && current?.experiment_id !== id) api.experiment(id).then(setCurrent).catch(() => undefined);
  }, [params, current]);

  const run = useAction(async () => {
    if (!selection) return;
    const result = await api.createExperiment({ provider: selection.provider, model: selection.model || null, trials });
    setCurrent(result);
    setParams({ id: result.experiment_id }, { replace: true });
    await list.reload();
  });

  if (providers.error) return <ErrorState message={providers.error} onRetry={providers.reload} />;
  if (!providers.data || !selection) return <Loading />;
  const chosen = providers.data.providers.find((p) => p.provider === selection.provider);

  return (
    <div className="space-y-6">
      <PageHeader title="Prompt-injection experiment"
        description="Run the same task and model in two isolated synthetic workspaces — one with AFTERIMAGE enforcement off (baseline), one with it on (protected) — and compare what the agent could actually do." />
      <SimulatedNotice>The baseline run disables policy enforcement on purpose, inside a disposable synthetic workspace, so the attack can be observed. No real system or data is involved, and the fake secret is never shown or stored.</SimulatedNotice>

      <Card title="Configure">
        <ProviderPicker data={providers.data} value={selection} onChange={setSelection} disabled={run.pending} />
        <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-ink-400">Trials per environment</span>
            <input type="number" min={1} max={providers.data.max_trials} value={trials}
              onChange={(e) => setTrials(Math.max(1, Math.min(providers.data!.max_trials, Number(e.target.value) || 1)))}
              disabled={run.pending}
              className="w-24 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm" />
            <span className="ml-2 text-xs text-ink-500">real models vary between trials</span>
          </label>
          <Button variant="primary" onClick={() => void run.run()} pending={run.pending}
            disabled={!chosen?.configured} icon={<FlaskConical className="size-4" />}>
            {run.pending ? `Running ${trials * 2} isolated run(s)…` : "Run experiment"}
          </Button>
        </div>
        {chosen && !chosen.configured && (
          <p className="mt-2 text-xs text-amber-200">{chosen.label} is not configured. {chosen.detail}</p>
        )}
        <InlineError message={run.error} onDismiss={run.clearError} />
      </Card>

      {current && (
        <>
          <VerdictBanner report={current.report} />
          <Card title="Baseline vs protected"
            subtitle={<>Provider <Mono>{current.report.provider}</Mono> · model <Mono>{current.report.model}</Mono> · {current.report.provider_real ? "real model" : "simulated agent"} · {current.report.trials} trial(s) each · {formatTime(current.created_at)}</>}>
            <div className="grid gap-4 md:grid-cols-2">
              <AggColumn title="Baseline" agg={current.report.baseline} tone="bad"
                subtitle="Agent tools unguarded (no AFTERIMAGE policy)." />
              <AggColumn title="Protected" agg={current.report.protected} tone="good"
                subtitle="AFTERIMAGE gateway enforces resource-level policy." />
            </div>
            <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-ink-400">
              {current.report.notes.map((n) => <li key={n}>{n}</li>)}
              <li>{current.report.ground_truth}</li>
            </ul>
          </Card>

          <Card title="Per-trial results">
            <div className="space-y-5">
              <TrialTable title="Baseline (enforcement off)" trials={current.report.baseline_trials} />
              <TrialTable title="Protected (enforcement on)" trials={current.report.protected_trials} />
            </div>
          </Card>

          {current.report.baseline.run_ids[0] && (
            <Card title="Example baseline transcript"
              subtitle="What the agent actually did with enforcement off (content redacted; the fake secret is never shown).">
              <CollapsibleTranscript runId={current.report.baseline.run_ids[0]} />
            </Card>
          )}
        </>
      )}

      <Card title="Saved experiments" bodyClassName="p-0">
        {list.error && <div className="p-4"><ErrorState message={list.error} onRetry={list.reload} /></div>}
        {list.data?.length === 0 && <div className="p-5"><EmptyState title="No experiments yet" /></div>}
        <ul className="divide-y divide-ink-800">
          {(list.data ?? []).map((e) => (
            <li key={e.experiment_id}>
              <button onClick={() => { void api.experiment(e.experiment_id).then(setCurrent); setParams({ id: e.experiment_id }, { replace: true }); }}
                className={cx("flex w-full flex-wrap items-center gap-3 px-5 py-3 text-left text-sm hover:bg-ink-850", current?.experiment_id === e.experiment_id && "bg-ink-850")}>
                <Badge tone={e.status === "protected" ? "good" : e.status === "protection_failed" ? "bad" : "warn"}>{e.status.replace(/_/g, " ")}</Badge>
                <span className="font-mono text-xs">{e.experiment_id}</span>
                <span className="text-ink-400">{e.provider} · {e.model} · {e.trials}×2 runs {e.provider_real ? "" : "(simulated)"}</span>
                <span className="ml-auto text-xs text-ink-400">{relativeTime(e.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>

    </div>
  );
}
