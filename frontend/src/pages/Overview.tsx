import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight, Ban, CheckCircle2, Cloud, Database, FlaskConical, Play, PlayCircle, ShieldAlert, ShieldCheck, Swords, Syringe,
  ArrowUpRight
} from "lucide-react";
import { api, type Run } from "../api";
import { relativeTime } from "../format";
import { useAction, useApi } from "../hooks";
import {
  Badge, Button, Card, EmptyState, ErrorState, InlineError, Loading, PageHeader, PassFail, RunKindBadge,
  SeverityBadge, SimulatedNotice, StatTile, cx,
} from "../components/ui";

export function RunOutcome({ run }: { run: Run }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      <span className="text-ink-300">Task: <PassFail passed={!!run.task_completed} label={run.task_completed ? "completed" : "not completed"} /></span>
      <span className="text-ink-300">Denied requests: <span className="font-semibold text-ink-100 tabular-nums">{run.result?.denied_calls ?? 0}</span></span>
      <span className="text-ink-300">Sensitive data exposed: <PassFail passed={!run.sensitive_exposed} label={run.sensitive_exposed ? "yes" : "no"} /></span>
    </div>
  );
}

export function Overview() {
  const navigate = useNavigate();
  const dash = useApi(api.dashboard);
  const [lastRun, setLastRun] = useState<Run>();
  const start = useAction(async (scenario: "benign" | "attack") => {
    const run = await api.startRun(scenario);
    setLastRun(run);
    await dash.reload();
    return run;
  });
  const [which, setWhich] = useState<"benign" | "attack">();

  const go = (s: "benign" | "attack") => { setWhich(s); void start.run(s); };
  const d = dash.data;
  const steps = d ? [
    { label: "Observe", done: d.metrics.runs > 0, hint: "Run a scenario" },
    { label: "Enforce", done: d.metrics.unauthorized_blocked > 0, hint: "Deny a restricted request" },
    { label: "Investigate", done: d.metrics.incidents > 0, hint: "Open an incident" },
    { label: "Remediate", done: d.policy.version > 1, hint: "Apply a policy change" },
    { label: "Replay", done: d.metrics.replays > 0, hint: "Replay the scenario" },
    { label: "Verify", done: d.metrics.verified_replays > 0, hint: "Pass all assertions" },
  ] : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description="Every AI action leaves an observable trace. Execute deterministic scenario runs to see server-side policy enforcement, automated incident reconstruction, and verifiable policy remediation."
        actions={<>
          <Button onClick={() => go("benign")} pending={start.pending && which === "benign"} disabled={start.pending} icon={<PlayCircle className="size-4 text-emerald-400" />}>Run Safe Scenario</Button>
          <Button variant="danger" onClick={() => go("attack")} pending={start.pending && which === "attack"} disabled={start.pending} icon={<Swords className="size-4" />}>Simulate Attack</Button>
          <Button variant="secondary" onClick={() => navigate("/replay")} icon={<FlaskConical className="size-4 text-accent-400" />}>Open Replay Lab</Button>
          <Button variant="primary" onClick={() => navigate("/experiment")} icon={<Syringe className="size-4" />}>Injection Lab (LLM)</Button>
        </>}
      />
      <InlineError message={start.error} onDismiss={start.clearError} />

      {lastRun && (
        <div className="rounded-xl border border-ink-700 bg-ink-900/90 p-5 shadow-lg shadow-black/20" data-testid="last-run">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 text-sm">
              <span className="grid size-8 place-items-center rounded-lg bg-ink-800 border border-ink-700/60">
                {lastRun.simulated_attack ? <Swords className="size-4 text-rose-400" aria-hidden /> : <Play className="size-4 text-accent-400" aria-hidden />}
              </span>
              <div>
                <div className="font-semibold text-ink-100 flex items-center gap-2">
                  {lastRun.scenario_title}
                  <span className="font-mono text-xs font-normal text-ink-400">({lastRun.run_id})</span>
                </div>
                <div className="text-xs text-ink-400">Enforced under policy v{lastRun.policy_version}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => navigate(`/events?run_id=${lastRun.run_id}`)}>View event timeline</Button>
              {lastRun.incident_id && (
                <Button variant="primary" onClick={() => navigate(`/investigation/${lastRun.incident_id}`)} icon={<ArrowRight className="size-4" />}>Investigate incident</Button>
              )}
            </div>
          </div>
          <div className="mt-4 pt-3.5 border-t border-ink-800/80"><RunOutcome run={lastRun} /></div>
          {lastRun.simulated_attack && <div className="mt-3.5"><SimulatedNotice /></div>}
          {!lastRun.incident_id && <p className="mt-3 text-xs text-ink-400">No unauthorized access was recorded in this run, so no incident was opened.</p>}
        </div>
      )}

      {dash.error && <ErrorState message={dash.error} onRetry={dash.reload} />}
      {!d && !dash.error && <Loading />}
      {d && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
            <StatTile label="Runs recorded" value={d.metrics.runs} hint={`${d.metrics.scenario_runs} scenario · ${d.metrics.replay_runs} replay`} icon={<Play className="size-4" />} />
            <StatTile label="Incidents detected" value={d.metrics.incidents} hint={`${d.metrics.exposures} confirmed exposure${d.metrics.exposures === 1 ? "" : "s"}`} icon={<ShieldAlert className="size-4" />} />
            <StatTile label="Unauthorized requests blocked" value={d.metrics.unauthorized_blocked} hint={`${d.metrics.denied_total} denials in total`} icon={<Ban className="size-4" />} />
            <StatTile label="Verified replays" value={d.metrics.verified_replays} hint={`of ${d.metrics.replays} replay${d.metrics.replays === 1 ? "" : "s"}`} icon={<ShieldCheck className="size-4" />} />
          </div>

          <Card title="Workflow progress" subtitle="Each stage completes only when backed by recorded event verification in the backend.">
            <ol className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
              {steps.map((s, i) => (
                <li key={s.label} className={cx("rounded-xl border p-3.5 transition-all", s.done ? "border-accent-500/40 bg-accent-500/5 shadow-xs" : "border-ink-800/80 bg-ink-950/40")}>
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {s.done ? <CheckCircle2 className="size-4 text-accent-400 shrink-0" aria-label="done" /> : <span className="grid size-4 shrink-0 place-items-center rounded-full border border-ink-600 text-[10px] text-ink-400 font-mono" aria-label="not done">{i + 1}</span>}
                    <span className={s.done ? "text-ink-100" : "text-ink-400"}>{s.label}</span>
                  </div>
                  <div className="mt-1 text-xs text-ink-500">{s.hint}</div>
                </li>
              ))}
            </ol>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            <Card title="Recent incidents" actions={<Link to="/incidents" className="text-xs text-accent-400 hover:text-accent-300 inline-flex items-center gap-1 font-medium">All incidents <ArrowUpRight className="size-3" /></Link>} bodyClassName="p-0">
              {d.recent_incidents.length === 0 ? (
                <div className="p-5"><EmptyState title="No incidents yet">Run <b>Simulate Attack</b> to generate a controlled, recorded incident.</EmptyState></div>
              ) : (
                <ul className="divide-y divide-ink-800/70">
                  {d.recent_incidents.map((inc) => (
                    <li key={inc.incident_id}>
                      <Link to={`/investigation/${inc.incident_id}`} className="flex flex-wrap items-center gap-3 px-5 py-3.5 hover:bg-ink-850/60 transition-colors">
                        <SeverityBadge severity={inc.severity} />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-100">{inc.title}</span>
                        <Badge tone={inc.status === "exposure_confirmed" ? "bad" : "neutral"}>{inc.status.replace(/_/g, " ")}</Badge>
                        <span className="text-xs text-ink-400 tabular-nums">{relativeTime(inc.created_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="space-y-6">
              <Card title="Active policy" actions={<Link to="/policies" className="text-xs text-accent-400 hover:text-accent-300 inline-flex items-center gap-1 font-medium">Manage <ArrowUpRight className="size-3" /></Link>}>
                <div className="flex items-baseline gap-2.5">
                  <span className="text-2xl font-bold tracking-tight text-ink-100">v{d.policy.version}</span>
                  <span className="text-sm font-medium text-ink-300">{d.policy.name}</span>
                </div>
                {d.policy.change_summary !== d.policy.name && <p className="mt-2 text-xs leading-relaxed text-ink-400">{d.policy.change_summary}</p>}
                <div className="mt-3 pt-3 border-t border-ink-800/70 text-xs text-ink-500 font-mono">
                  {d.policy.rule_count} rules · disabled tools: {d.policy.disabled_tools.join(", ") || "none"}
                </div>
              </Card>

              <Card title="Storage & sync">
                <ul className="space-y-2.5 text-sm">
                  <li className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-ink-200">
                      <Database className="size-4 text-accent-400" aria-hidden />
                      {d.sync.local.label}
                    </span>
                    <Badge tone="good">active</Badge>
                  </li>
                  <li className="flex items-center justify-between text-ink-400">
                    <span className="flex items-center gap-2">
                      <Cloud className="size-4 text-ink-500" aria-hidden />
                      {d.sync.cloud.label}
                    </span>
                    <Badge tone="neutral">offline</Badge>
                  </li>
                </ul>
              </Card>
            </div>
          </div>

          <Card title="Recent runs" bodyClassName="p-0">
            {d.recent_runs.length === 0 ? (
              <div className="p-5"><EmptyState title="No runs yet">Start with <b>Run Safe Scenario</b>.</EmptyState></div>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead className="text-left text-xs font-semibold text-ink-400 bg-ink-950/40">
                    <tr className="border-b border-ink-800/80">
                      <th className="px-5 py-3">Run</th>
                      <th className="py-3">Scenario</th>
                      <th className="py-3">Agent</th>
                      <th className="py-3">Policy</th>
                      <th className="py-3">Task</th>
                      <th className="py-3">Denied</th>
                      <th className="py-3">Exposed</th>
                      <th className="py-3 pr-5">Started</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-800/60">
                    {d.recent_runs.map((r) => (
                      <tr key={r.run_id} className="hover:bg-ink-850/50 transition-colors">
                        <td className="px-5 py-3"><Link className="font-mono text-xs font-medium text-accent-400 hover:text-accent-300 hover:underline" to={`/events?run_id=${r.run_id}`}>{r.run_id}</Link></td>
                        <td className="font-medium text-ink-200">{r.scenario_title}{r.kind === "replay" && <Badge className="ml-2" tone="accent">replay</Badge>}{r.enforcement === "baseline" && <Badge className="ml-2" tone="bad">baseline</Badge>}</td>
                        <td><RunKindBadge run={r} /></td>
                        <td className="tabular-nums font-mono text-xs text-ink-300">{r.enforcement === "baseline" ? "—" : `v${r.policy_version}`}</td>
                        <td><PassFail passed={!!r.task_completed} label={r.task_completed ? "done" : "failed"} /></td>
                        <td className="tabular-nums font-semibold text-ink-200">{r.result?.denied_calls ?? 0}</td>
                        <td><PassFail passed={!r.sensitive_exposed} label={r.sensitive_exposed ? "yes" : "no"} /></td>
                        <td className="text-xs text-ink-400 pr-5 tabular-nums">{relativeTime(r.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
