import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, FlaskConical, ShieldCheck, ShieldX } from "lucide-react";
import { api, type Replay, type RunEvaluation } from "../api";
import { formatTime, relativeTime } from "../format";
import { useAction, useApi } from "../hooks";
import { PROVIDER_META, ProviderErrorNotice } from "../providers";
import {
  Badge, Button, Card, EmptyState, ErrorState, InlineError, Loading, Mono, OutcomeTag, PageHeader, PassFail, cx,
} from "../components/ui";

function StatusBanner({ replay }: { replay: Replay }) {
  const cfg = {
    verified: { icon: ShieldCheck, cls: "border-emerald-400/30 bg-emerald-500/10 text-emerald-100", title: "Verified",
      text: "Every required assertion passed: the attack was exercised and blocked, nothing sensitive was exposed, and the legitimate task still completed." },
    regression: { icon: AlertTriangle, cls: "border-amber-400/30 bg-amber-500/10 text-amber-100", title: "Not verified — regression",
      text: "The attack was blocked, but the legitimate task failed. The policy is too restrictive, so this is not a successful remediation." },
    failed: { icon: ShieldX, cls: "border-rose-400/30 bg-rose-500/10 text-rose-100", title: "Not verified — security failure",
      text: "At least one unauthorized request succeeded or sensitive data was exposed." },
    inconclusive: { icon: AlertTriangle, cls: "border-amber-400/30 bg-amber-500/10 text-amber-100", title: "Inconclusive",
      text: "Every model trial failed with a provider error, so the model side could not be verified." },
  }[replay.status];
  const Icon = cfg.icon;
  return (
    <div role="status" data-testid="replay-status" className={cx("flex items-start gap-3 rounded-xl border p-4", cfg.cls)}>
      <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>
        <div className="font-semibold">{cfg.title}</div>
        <p className="mt-0.5 text-sm opacity-90">{cfg.text}</p>
        {replay.report.notes.map((n) => <p key={n} className="mt-1 text-sm opacity-90">{n}</p>)}
      </div>
    </div>
  );
}

function Row({ label, base, next }: { label: string; base: React.ReactNode; next: React.ReactNode }) {
  return (
    <tr className="border-b border-ink-800 last:border-0">
      <th scope="row" className="py-2.5 pr-4 text-left text-sm font-normal text-ink-400">{label}</th>
      <td className="py-2.5 pr-4 text-sm">{base}</td>
      <td className="py-2.5 text-sm">{next}</td>
    </tr>
  );
}

function Comparison({ replay }: { replay: Replay }) {
  const b: RunEvaluation = replay.report.baseline;
  const r: RunEvaluation = replay.report.replay;
  return (
    <table className="w-full">
      <thead>
        <tr className="border-b border-ink-700 text-left text-xs text-ink-400">
          <th className="py-2 font-medium" />
          <th className="py-2 font-medium">Baseline · <Link className="font-mono text-accent-300 hover:underline" to={`/events?run_id=${b.run_id}`}>{b.run_id}</Link></th>
          <th className="py-2 font-medium">Replay · <Link className="font-mono text-accent-300 hover:underline" to={`/events?run_id=${r.run_id}`}>{r.run_id}</Link></th>
        </tr>
      </thead>
      <tbody>
        <Row label="Policy version" base={b.policy_version === 0 ? "enforcement off" : `v${b.policy_version}`} next={<span>v{r.policy_version} {replay.report.policy_changed && <Badge tone="accent">changed</Badge>}</span>} />
        <Row label="Unauthorized access attempted" base={b.unauthorized_attempted} next={r.unauthorized_attempted} />
        <Row label="Unauthorized access blocked" base={`${b.unauthorized_blocked} / ${b.unauthorized_attempted}`} next={`${r.unauthorized_blocked} / ${r.unauthorized_attempted}`} />
        <Row label="Sensitive data exposed" base={<PassFail passed={!b.sensitive_data_exposed} label={b.sensitive_data_exposed ? "Yes" : "No"} />} next={<PassFail passed={!r.sensitive_data_exposed} label={r.sensitive_data_exposed ? "Yes" : "No"} />} />
        <Row label="Legitimate task completed" base={<PassFail passed={b.task_completed} label={b.task_completed ? "Yes" : "No"} />} next={<PassFail passed={r.task_completed} label={r.task_completed ? "Yes" : "No"} />} />
        <Row label="Policy rule(s) responsible" base={b.rules_responsible.map((x) => <Mono key={x} className="mr-1">{x}</Mono>)} next={r.rules_responsible.map((x) => <Mono key={x} className="mr-1">{x}</Mono>)} />
        <Row label="Overall" base={<Badge>{b.status ?? "—"}</Badge>} next={<Badge tone={replay.verified ? "good" : "bad"}>{replay.status}</Badge>} />
      </tbody>
    </table>
  );
}

export function ReplayLab() {
  const [params, setParams] = useSearchParams();
  const runs = useApi(api.runs);
  const replays = useApi(api.replays);
  const policies = useApi(api.policies);
  const [baseline, setBaseline] = useState("");
  const [trials, setTrials] = useState(1);
  const [current, setCurrent] = useState<Replay>();

  const candidates = useMemo(() => (runs.data ?? []).filter((r) => r.kind === "scenario" && r.status === "completed"), [runs.data]);
  const incidentParam = params.get("incident");

  useEffect(() => {
    if (baseline || !runs.data) return;
    const fromIncident = incidentParam ? runs.data.find((r) => r.incident_id === incidentParam) : undefined;
    const pick = (fromIncident?.kind === "replay" ? undefined : fromIncident) ?? candidates.find((r) => r.scenario === "attack") ?? candidates[0];
    if (pick) setBaseline(pick.run_id);
  }, [runs.data, candidates, baseline, incidentParam]);

  useEffect(() => {
    const id = params.get("replay");
    if (id && current?.replay_id !== id) api.replay(id).then(setCurrent).catch(() => undefined);
  }, [params, current]);

  const execute = useAction(async () => {
    const result = await api.createReplay({ baseline_run_id: baseline, trials: base?.agent_kind === "llm" ? trials : 1 });
    setCurrent(result);
    setParams({ replay: result.replay_id }, { replace: true });
    await Promise.all([replays.reload(), runs.reload()]);
  });

  const base = candidates.find((r) => r.run_id === baseline);
  const activeVersion = policies.data?.active.version;

  return (
    <div className="space-y-6">
      <PageHeader title="Replay Lab" description="Re-run the same predefined scenario in a fresh, isolated synthetic workspace under the active policy, then grade it with policy-independent assertions." />

      <Card title="Configure replay">
        {runs.error && <ErrorState message={runs.error} onRetry={runs.reload} />}
        {!runs.data && !runs.error && <Loading />}
        {runs.data && candidates.length === 0 && (
          <EmptyState title="No baseline run available" icon={<FlaskConical className="size-6" />}>Run a scenario from the <Link className="text-accent-300 underline" to="/">Overview</Link> first.</EmptyState>
        )}
        {candidates.length > 0 && (
          <div className="grid gap-5 lg:grid-cols-[1fr_auto] lg:items-end">
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="text-sm sm:col-span-1">
                <span className="mb-1 block text-xs font-medium text-ink-400">Baseline run</span>
                <select aria-label="Baseline run" value={baseline} onChange={(e) => setBaseline(e.target.value)} className="w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-xs">
                  {candidates.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} · {r.agent_kind === "llm"
                        ? (r.provider_real ? `${PROVIDER_META[r.provider ?? ""]?.short ?? "LLM"} ${r.model ?? ""}` : `simulated ${r.model ?? ""}`)
                        : `scripted ${r.scenario}`}
                      {r.enforcement === "baseline" ? " · enforcement off" : ` · v${r.policy_version}`}
                    </option>
                  ))}
                </select>
              </label>
              <div>
                <div className="mb-1 text-xs font-medium text-ink-400">Baseline policy</div>
                <div className="text-sm">{base ? (base.enforcement === "baseline" ? "enforcement off" : `v${base.policy_version}`) : "—"} <span className="text-ink-400">{base && formatTime(base.started_at)}</span></div>
                {base?.agent_kind === "llm" && (
                  <label className="mt-2 block text-xs text-ink-400">Model trials
                    <input type="number" min={1} max={20} value={trials} aria-label="Model trials"
                      onChange={(e) => setTrials(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                      className="ml-2 w-16 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm text-ink-100" />
                    <span className="mt-1 block">plus one deterministic scripted control trial</span>
                  </label>
                )}
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-ink-400">Replay will use</div>
                <div className="text-sm">{activeVersion ? `Active policy v${activeVersion}` : "—"}
                  {base && activeVersion === base.policy_version && <span className="block text-xs text-amber-300">Same version as baseline — this tests reproducibility, not a fix.</span>}
                </div>
              </div>
            </div>
            <Button variant="primary" onClick={() => void execute.run()} pending={execute.pending} disabled={!baseline} icon={<FlaskConical className="size-4" />}>
              {execute.pending ? (base?.agent_kind === "llm" ? `Running ${trials} model trial(s) + control…` : "Executing in fresh workspace…") : "Run replay"}
            </Button>
          </div>
        )}
        {execute.error && (execute.errorCode?.startsWith("provider_")
          ? <ProviderErrorNotice message={execute.error} code={execute.errorCode} provider={base?.provider} retryAfterS={execute.retryAfterS} />
          : <InlineError message={execute.error} onDismiss={execute.clearError} />)}
      </Card>

      {current && (
        <>
          <StatusBanner replay={current} />
          <div className="grid gap-6 xl:grid-cols-2">
            <Card title="Baseline vs remediated run" subtitle={`Replay ${current.replay_id} · ${formatTime(current.created_at)} · saved report`}>
              <div className="scroll-thin overflow-x-auto"><Comparison replay={current} /></div>
            </Card>
            <Card title="Verification assertions" subtitle="Computed from the replay run's persisted events.">
              <ul className="space-y-3">
                {current.report.assertions.map((a) => (
                  <li key={a.id} className="rounded-lg border border-ink-700 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium">{a.title}</span>
                      {a.required ? <PassFail passed={a.passed} /> : <Badge>informational · {a.passed ? "yes" : "no"}</Badge>}
                    </div>
                    <p className="mt-1 text-xs text-ink-400">{a.detail}</p>
                    {a.evidence_event_ids.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {a.evidence_event_ids.map((id) => <span key={id} className="rounded border border-ink-700 bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-ink-300">{id}</span>)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
          {current.report.model_trials && current.report.model_stats && (
            <Card title="Model trials (probabilistic)" bodyClassName="p-0"
              subtitle={`${current.report.model_stats.provider} · ${current.report.model_stats.model} — the model attempted the injected request in ${current.report.model_stats.attack_attempted} of ${current.report.model_stats.completed_trials} completed trial(s). Deterministic control run: ${current.report.deterministic_control?.status ?? "—"}.`}>
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="text-left text-xs text-ink-400">
                    <tr className="border-b border-ink-800"><th className="px-5 py-2 font-medium">Run</th><th className="font-medium">Attempted</th><th className="font-medium">Blocked</th><th className="font-medium">Exposed</th><th className="font-medium">Task</th><th className="pr-5 font-medium">Rules / error</th></tr>
                  </thead>
                  <tbody className="divide-y divide-ink-800">
                    {current.report.model_trials.map((t) => (
                      <tr key={t.run_id}>
                        <td className="px-5 py-2.5"><Link to={`/events?run_id=${t.run_id}`} className="font-mono text-xs text-accent-300 hover:underline">{t.run_id}</Link></td>
                        <td>{t.errored ? "—" : t.attack_attempted ? "yes" : "no"}</td>
                        <td className="tabular-nums">{t.errored ? "—" : `${t.unauthorized_blocked} / ${t.unauthorized_attempted}`}</td>
                        <td>{t.errored ? "—" : <PassFail passed={!t.sensitive_data_exposed} label={t.sensitive_data_exposed ? "yes" : "no"} />}</td>
                        <td>{t.errored ? "—" : <PassFail passed={t.task_completed} label={t.task_completed ? "done" : "no"} />}</td>
                        <td className="pr-5 font-mono text-xs">{t.errored ? <span className="text-amber-300">{t.provider_error}</span> : t.rules_responsible.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          <Card title="Differences between runs" subtitle="Each tool request matched by tool + canonical resource." bodyClassName="p-0">
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-ink-400">
                  <tr className="border-b border-ink-800"><th className="px-5 py-2 font-medium">Request</th><th className="font-medium">Type</th><th className="font-medium">Baseline</th><th className="font-medium">Replay</th><th className="pr-5 font-medium">Changed</th></tr>
                </thead>
                <tbody className="divide-y divide-ink-800">
                  {current.report.differences.map((d) => (
                    <tr key={d.tool + d.resource_id} className={cx(d.changed && "bg-ink-850")}>
                      <td className="px-5 py-2.5"><Mono>{d.tool}</Mono> <span className="font-mono text-xs">{d.resource_id}</span></td>
                      <td>{d.unauthorized ? <Badge tone="warn">unauthorized</Badge> : <Badge>legitimate</Badge>}</td>
                      <td>{d.baseline ? <span className="flex items-center gap-2"><OutcomeTag outcome={d.baseline.decision} /><span className="font-mono text-xs text-ink-400">{d.baseline.rule_id}</span></span> : "not attempted"}</td>
                      <td>{d.replay ? <span className="flex items-center gap-2"><OutcomeTag outcome={d.replay.decision} /><span className="font-mono text-xs text-ink-400">{d.replay.rule_id}</span></span> : "not attempted"}</td>
                      <td className="pr-5">{d.changed ? "yes" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      <Card title="Saved replay reports" bodyClassName="p-0">
        {replays.error && <div className="p-4"><ErrorState message={replays.error} onRetry={replays.reload} /></div>}
        {replays.data?.length === 0 && <div className="p-5"><EmptyState title="No replays yet" /></div>}
        <ul className="divide-y divide-ink-800">
          {(replays.data ?? []).map((r) => (
            <li key={r.replay_id}>
              <button onClick={() => { setCurrent(r); setParams({ replay: r.replay_id }, { replace: true }); }}
                className={cx("flex w-full flex-wrap items-center gap-3 px-5 py-3 text-left text-sm hover:bg-ink-850", current?.replay_id === r.replay_id && "bg-ink-850")}>
                <Badge tone={r.status === "verified" ? "good" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Badge>
                <span className="font-mono text-xs">{r.replay_id}</span>
                <span className="text-ink-400">{r.scenario} · v{r.baseline_policy_version} → v{r.replay_policy_version}</span>
                <span className="ml-auto text-xs text-ink-400">{relativeTime(r.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
