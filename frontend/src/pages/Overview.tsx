import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight, Ban, CheckCircle2, Cloud, Database, Play, PlayCircle, ShieldAlert, ShieldCheck, Swords,
  ArrowUpRight, Shield
} from "lucide-react";
import { api, type Run } from "../api";
import { relativeTime } from "../format";
import { useAction, useApi } from "../hooks";
import {
  Badge, Button, Card, EmptyState, ErrorState, InlineError, Loading, PassFail, RunKindBadge,
  SeverityBadge, SimulatedNotice, StatTile, cx,
} from "../components/ui";

export function RunOutcome({ run }: { run: Run }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs font-mono">
      <div className="flex items-center gap-2">
        <span className="text-slate-400">Task:</span>
        <PassFail passed={!!run.task_completed} label={run.task_completed ? "completed" : "not completed"} />
      </div>
      <div className="flex items-center gap-2">
        <span className="text-slate-400">Denied requests: <span className="font-bold text-slate-100 tabular-nums px-2 py-0.5 rounded bg-white/[0.04] border border-white/10">{run.result?.denied_calls ?? 0}</span></span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-slate-400">Sensitive data exposed:</span>
        <PassFail passed={!run.sensitive_exposed} label={run.sensitive_exposed ? "yes" : "no"} />
      </div>
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
    { label: "Observe", done: d.metrics.runs > 0, hint: "Record agent telemetry" },
    { label: "Enforce", done: d.metrics.unauthorized_blocked > 0, hint: "Block boundary violation" },
    { label: "Investigate", done: d.metrics.incidents > 0, hint: "Reconstruct provenance" },
    { label: "Remediate", done: d.policy.version > 1, hint: "Patch security policy" },
    { label: "Replay", done: d.metrics.replays > 0, hint: "Execute replay sandbox" },
    { label: "Verify", done: d.metrics.verified_replays > 0, hint: "Cryptographic check" },
  ] : [];

  return (
    <div className="space-y-8">
      {/* Hero Interactive Execution Deck */}
      <div className="relative overflow-hidden rounded-3xl p-8 border border-white/[0.08] bg-gradient-to-br from-[#0c1322] via-[#070b14] to-[#04060a] shadow-2xl">
        <div className="absolute top-0 right-0 -mt-12 -mr-12 w-96 h-96 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-1/3 -mb-20 w-80 h-80 rounded-full bg-teal-500/5 blur-3xl pointer-events-none" />
        
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-8">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 font-mono text-[11px] font-bold tracking-widest uppercase mb-3">
              <Shield className="size-3.5" /> ZERO TRUST POLICY GATEWAY
            </div>
            <h1 className="text-3xl sm:text-4xl font-black text-white tracking-tight">
              AI Agent Forensics & Security Enforcement
            </h1>
            <p className="mt-3 text-sm text-slate-300 leading-relaxed font-normal">
              AFTERIMAGE intercepts every tool request via a strict server-side policy gateway before any file is accessed. 
              Witness deterministic attacks blocked in flight, inspect cryptographic evidence chains, and verify remediations in fresh sandboxes.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row lg:flex-col gap-3 shrink-0">
            <Button
              variant="primary"
              onClick={() => go("benign")}
              pending={start.pending && which === "benign"}
              disabled={start.pending}
              icon={<PlayCircle className="size-4 text-slate-950" />}
              className="py-3 px-5 text-sm"
            >
              Run Safe Scenario
            </Button>
            <Button
              variant="danger"
              onClick={() => go("attack")}
              pending={start.pending && which === "attack"}
              disabled={start.pending}
              icon={<Swords className="size-4" />}
              className="py-3 px-5 text-sm"
            >
              Simulate Attack
            </Button>
          </div>
        </div>
      </div>

      <InlineError message={start.error} onDismiss={start.clearError} />

      {/* Live Recorded Execution Banner */}
      {lastRun && (
        <div className="glass-panel-glow rounded-2xl p-6 relative overflow-hidden animate-fade-in" data-testid="last-run">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className={cx(
                "size-10 rounded-xl flex items-center justify-center border shadow-md",
                lastRun.simulated_attack ? "bg-rose-500/20 border-rose-500/40 text-rose-300" : "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
              )}>
                {lastRun.simulated_attack ? <Swords className="size-5" /> : <Play className="size-5" />}
              </div>
              <div>
                <div className="font-bold text-slate-100 flex items-center gap-2.5 text-base">
                  {lastRun.scenario_title}
                  <span className="font-mono text-xs font-medium text-slate-400 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.08]">{lastRun.run_id}</span>
                </div>
                <div className="text-xs text-slate-400 font-mono mt-0.5">Enforced at policy revision v{lastRun.policy_version}</div>
              </div>
            </div>
            <div className="flex items-center gap-2.5">
              <Button variant="ghost" onClick={() => navigate(`/events?run_id=${lastRun.run_id}`)}>View Event Trace</Button>
              {lastRun.incident_id && (
                <Button variant="primary" onClick={() => navigate(`/investigation/${lastRun.incident_id}`)} icon={<ArrowRight className="size-4" />}>
                  Investigate incident
                </Button>
              )}
            </div>
          </div>
          <div className="mt-5 pt-4 border-t border-white/[0.08]"><RunOutcome run={lastRun} /></div>
          {lastRun.simulated_attack && <div className="mt-4"><SimulatedNotice /></div>}
          {!lastRun.incident_id && <p className="mt-3 text-xs text-slate-400 font-mono">No unauthorized access was recorded in this run, so no incident was opened.</p>}
        </div>
      )}

      {dash.error && <ErrorState message={dash.error} onRetry={dash.reload} />}
      {!d && !dash.error && <Loading />}
      {d && (
        <div className="space-y-8">
          {/* Telemetry Stat Matrix */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Runs recorded" value={d.metrics.runs} hint={`${d.metrics.scenario_runs} safe · ${d.metrics.replay_runs} replays`} icon={<Play className="size-4" />} />
            <StatTile label="Incidents detected" value={d.metrics.incidents} hint={`${d.metrics.exposures} confirmed leak events`} icon={<ShieldAlert className="size-4" />} />
            <StatTile label="Unauthorized requests blocked" value={d.metrics.unauthorized_blocked} hint={`${d.metrics.denied_total} gateway rejections`} icon={<Ban className="size-4" />} />
            <StatTile label="Verified replays" value={d.metrics.verified_replays} hint={`of ${d.metrics.replays} remediated trials`} icon={<ShieldCheck className="size-4" />} />
          </div>

          {/* Forensic Pipeline Visualizer */}
          <Card title="Forensic Verification Pipeline" subtitle="Lifecycle stages update strictly when backed by cryptographically hashed events in SQLite.">
            <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
              {steps.map((s, i) => (
                <li key={s.label} className={cx(
                  "rounded-2xl border p-4 transition-all duration-200 relative overflow-hidden",
                  s.done ? "border-emerald-500/40 bg-emerald-500/[0.04] shadow-xs" : "border-white/[0.04] bg-white/[0.01]"
                )}>
                  <div className="flex items-center gap-2.5 text-xs font-bold tracking-wide">
                    {s.done ? (
                      <CheckCircle2 className="size-4 text-emerald-400 shrink-0" aria-label="done" />
                    ) : (
                      <span className="grid size-4 shrink-0 place-items-center rounded-full border border-slate-600 text-[10px] text-slate-400 font-mono" aria-label="not done">{i + 1}</span>
                    )}
                    <span className={s.done ? "text-slate-100" : "text-slate-400"}>{s.label}</span>
                  </div>
                  <div className="mt-1.5 text-[11px] text-slate-400 leading-snug">{s.hint}</div>
                </li>
              ))}
            </ol>
          </Card>

          {/* Split Deck: Recent Incidents vs Active Policy */}
          <div className="grid gap-8 xl:grid-cols-[1.5fr_1fr]">
            <Card title="Recent Incident Reports" actions={<Link to="/incidents" className="text-xs font-mono font-bold text-teal-400 hover:text-teal-300 inline-flex items-center gap-1">All incidents <ArrowUpRight className="size-3" /></Link>} bodyClassName="p-0">
              {d.recent_incidents.length === 0 ? (
                <div className="p-6"><EmptyState title="No incidents yet">Run <b>Simulate Attack</b> to generate a controlled, recorded incident.</EmptyState></div>
              ) : (
                <ul className="divide-y divide-white/[0.05]">
                  {d.recent_incidents.map((inc) => (
                    <li key={inc.incident_id}>
                      <Link to={`/investigation/${inc.incident_id}`} className="flex flex-wrap items-center gap-3.5 px-6 py-4 hover:bg-white/[0.02] transition-colors">
                        <SeverityBadge severity={inc.severity} />
                        <span className="min-w-0 flex-1 truncate text-xs font-bold text-slate-100 tracking-tight">{inc.title}</span>
                        <Badge tone={inc.status === "exposure_confirmed" ? "bad" : "neutral"}>{inc.status.replace(/_/g, " ")}</Badge>
                        <span className="text-xs text-slate-400 tabular-nums font-mono">{relativeTime(inc.created_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="space-y-8">
              <Card title="Active Gateway Policy" actions={<Link to="/policies" className="text-xs font-mono font-bold text-teal-400 hover:text-teal-300 inline-flex items-center gap-1">Manage <ArrowUpRight className="size-3" /></Link>}>
                <div className="flex items-baseline gap-3">
                  <span className="text-3xl font-black text-white font-mono tracking-tight">v{d.policy.version}</span>
                  <span className="text-sm font-semibold text-slate-300">{d.policy.name}</span>
                </div>
                {d.policy.change_summary !== d.policy.name && <p className="mt-2 text-xs leading-relaxed text-slate-400">{d.policy.change_summary}</p>}
                <div className="mt-4 pt-3.5 border-t border-white/[0.06] text-[11px] text-slate-400 font-mono">
                  {d.policy.rule_count} active rules · disabled tools: {d.policy.disabled_tools.join(", ") || "none"}
                </div>
              </Card>

              <Card title="Storage & Verification Ledger">
                <ul className="space-y-3 text-xs font-mono">
                  <li className="flex items-center justify-between p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                    <span className="flex items-center gap-2 text-slate-200">
                      <Database className="size-4 text-teal-400" aria-hidden />
                      {d.sync.local.label}
                    </span>
                    <Badge tone="good">ONLINE</Badge>
                  </li>
                  <li className="flex items-center justify-between p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04] text-slate-400">
                    <span className="flex items-center gap-2">
                      <Cloud className="size-4 text-slate-500" aria-hidden />
                      {d.sync.cloud.label}
                    </span>
                    <Badge tone="neutral">AIR-GAPPED</Badge>
                  </li>
                </ul>
              </Card>
            </div>
          </div>

          {/* Recent Runs Audit Table */}
          <Card title="Recent Execution Runs" bodyClassName="p-0">
            {d.recent_runs.length === 0 ? (
              <div className="p-6"><EmptyState title="No runs yet">Start with <b>Run Safe Scenario</b>.</EmptyState></div>
            ) : (
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full min-w-[780px] text-xs">
                  <thead className="text-left font-mono font-bold text-slate-400 bg-white/[0.02]">
                    <tr className="border-b border-white/[0.06]">
                      <th className="px-6 py-3.5">RUN ID</th>
                      <th className="py-3.5">SCENARIO</th>
                      <th className="py-3.5">AGENT</th>
                      <th className="py-3.5">POLICY</th>
                      <th className="py-3.5">TASK</th>
                      <th className="py-3.5">DENIED</th>
                      <th className="py-3.5">EXPOSED</th>
                      <th className="py-3.5 pr-6">TIME</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] font-mono">
                    {d.recent_runs.map((r) => (
                      <tr key={r.run_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="px-6 py-3.5"><Link className="font-bold text-teal-400 hover:text-teal-300 hover:underline" to={`/events?run_id=${r.run_id}`}>{r.run_id}</Link></td>
                        <td className="font-sans font-semibold text-slate-200">{r.scenario_title}{r.kind === "replay" && <Badge className="ml-2" tone="accent">replay</Badge>}{r.enforcement === "baseline" && <Badge className="ml-2" tone="bad">baseline</Badge>}</td>
                        <td><RunKindBadge run={r} /></td>
                        <td className="tabular-nums text-slate-300">{r.enforcement === "baseline" ? "—" : `v${r.policy_version}`}</td>
                        <td><PassFail passed={!!r.task_completed} label={r.task_completed ? "DONE" : "FAIL"} /></td>
                        <td className="tabular-nums font-bold text-slate-100">{r.result?.denied_calls ?? 0}</td>
                        <td><PassFail passed={!r.sensitive_exposed} label={r.sensitive_exposed ? "YES" : "NO"} /></td>
                        <td className="text-slate-400 pr-6 tabular-nums">{relativeTime(r.started_at)}</td>
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
