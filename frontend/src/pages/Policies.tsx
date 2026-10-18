import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Eye, FlaskConical, History, RotateCcw } from "lucide-react";
import { api, type PolicyDescription, type PolicyDocument, type PolicyPreview, type Rule } from "../api";
import { formatTime } from "../format";
import { useAction, useApi } from "../hooks";
import { Badge, Button, Card, ConfirmDialog, ErrorState, InlineError, Loading, Mono, PageHeader, PassFail, cx } from "../components/ui";

const effectTone = { allow: "good", deny: "bad", require_approval: "warn" } as const;

function RulesTable({ doc, impact, highlight }: { doc: PolicyDocument; impact?: Record<string, string[]>; highlight?: Set<string> }) {
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="text-left text-xs text-ink-400">
          <tr className="border-b border-ink-800"><th className="py-2 pr-3 font-medium">Rule</th><th className="pr-3 font-medium">Effect</th><th className="pr-3 font-medium">Tools</th><th className="pr-3 font-medium">Resources</th>{impact && <th className="font-medium">Impact on demo requests</th>}</tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {doc.rules.map((r: Rule) => (
            <tr key={r.rule_id} className={cx(highlight?.has(r.rule_id) && "bg-accent-500/5")}>
              <td className="py-2.5 pr-3 align-top"><Mono>{r.rule_id}</Mono><div className="mt-1 max-w-xs text-xs text-ink-400">{r.description}</div></td>
              <td className="pr-3 align-top"><Badge tone={effectTone[r.effect]}>{r.effect.replace("_", " ")}</Badge></td>
              <td className="pr-3 align-top font-mono text-xs">{r.actions.join(", ")}</td>
              <td className="pr-3 align-top font-mono text-xs">{r.resources.join(", ")}</td>
              {impact && <td className="align-top text-xs text-ink-300">{(impact[r.rule_id] ?? ["no demo request decided by this rule"]).map((x) => <div key={x}>{x}</div>)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-400">Disabled tools: {doc.disabled_tools.length ? doc.disabled_tools.map((t) => <Mono key={t}>{t}</Mono>) : "none"}</p>
    </div>
  );
}

export function Policies() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const incident = params.get("incident");
  const policies = useApi(api.policies);
  const [selected, setSelected] = useState<string[]>(() => (params.get("changes") ?? "").split(",").filter(Boolean));
  const [preview, setPreview] = useState<PolicyPreview>();
  const [confirm, setConfirm] = useState(false);
  const [applied, setApplied] = useState<PolicyDescription>();
  const [revertTarget, setRevertTarget] = useState<number>();

  const doPreview = useAction(async () => setPreview(await api.previewPolicy(selected)));
  const doApply = useAction(async () => {
    if (!preview) return;
    const result = await api.applyPolicy(preview.change_ids, preview.base_version);
    setApplied(result);
    setPreview(undefined);
    setConfirm(false);
    setSelected([]);
    await policies.reload();
  });
  const doRevert = useAction(async () => {
    if (!revertTarget || !policies.data) return;
    const result = await api.revertPolicy(revertTarget, policies.data.active.version);
    setApplied(result);
    setRevertTarget(undefined);
    await policies.reload();
  });

  if (policies.error) return <ErrorState message={policies.error} onRetry={policies.reload} />;
  if (!policies.data) return <Loading />;
  const { active, history, catalog } = policies.data;

  const toggle = (id: string) => { setPreview(undefined); setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])); };
  const added = new Set(preview?.diff.added_rules.map((r) => r.rule_id));

  return (
    <div className="space-y-6">
      <PageHeader title="Policies" description="Policies are enforced by the backend gateway on every tool call (deny rules win, then approval rules, then allow rules, else default deny). Changes are versioned and reversible." />

      {applied && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent-500/30 bg-accent-500/5 px-4 py-3 text-sm">
          <span className="flex items-center gap-2"><CheckCircle2 className="size-4 text-accent-400" aria-hidden />Policy v{applied.version} is now active and enforced: {applied.change_summary}</span>
          <Button variant="primary" onClick={() => navigate(incident ? `/replay?incident=${incident}` : "/replay")} icon={<FlaskConical className="size-4" />}>Replay to verify</Button>
        </div>
      )}

      <Card title={`Active policy · v${active.version}`} subtitle={`${active.document.name} · ${active.change_summary} · ${formatTime(active.created_at)}`}>
        <RulesTable doc={active.document} impact={active.rule_impact} />
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-ink-300">Built-in gateway rules (always enforced)</summary>
          <ul className="mt-2 space-y-1.5">
            {active.builtin_rules.map((b) => (
              <li key={b.rule_id} className="text-xs text-ink-400"><Mono>{b.rule_id}</Mono> {b.description}{active.rule_impact[b.rule_id] && <span className="text-ink-300"> — {active.rule_impact[b.rule_id].join("; ")}</span>}</li>
            ))}
          </ul>
        </details>
      </Card>

      <Card title="Propose a change" subtitle="Only safe, reversible changes from this catalogue can be applied in the demo environment.">
        <div className="grid gap-3 md:grid-cols-2">
          {catalog.map((c) => (
            <label key={c.change_id} className={cx("flex cursor-pointer gap-3 rounded-lg border p-3.5 transition-colors",
              selected.includes(c.change_id) ? "border-accent-500/50 bg-accent-500/5" : "border-ink-700 hover:border-ink-600",
              c.already_applied && "opacity-60")}>
              <input type="checkbox" className="mt-1 accent-[var(--color-accent-500)]" checked={selected.includes(c.change_id)}
                disabled={c.already_applied} onChange={() => toggle(c.change_id)} />
              <span>
                <span className="flex flex-wrap items-center gap-2 text-sm font-medium">{c.title}{c.already_applied && <Badge tone="good">active</Badge>}</span>
                <span className="mt-0.5 block text-xs text-ink-500">{c.category}</span>
                <span className="mt-1 block text-xs text-ink-400">{c.explanation}</span>
              </span>
            </label>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => void doPreview.run()} pending={doPreview.pending} disabled={selected.length === 0} icon={<Eye className="size-4" />}>Preview change</Button>
          <span className="text-xs text-ink-400">{selected.length} selected</span>
        </div>
        <InlineError message={doPreview.error} onDismiss={doPreview.clearError} />
      </Card>

      {preview && (
        <Card title="Preview" subtitle={`Based on active v${preview.base_version}. Nothing has changed yet.`}
          actions={<Button variant="primary" onClick={() => setConfirm(true)} disabled={preview.no_op}>Apply as v{preview.base_version + 1}…</Button>}>
          {preview.no_op && <p className="mb-3 text-sm text-ink-300">These changes are already in effect.</p>}
          {preview.impact.warnings.length > 0 && (
            <div className="mb-4 rounded-lg border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-100">
              <div className="flex items-center gap-2 font-medium"><AlertTriangle className="size-4" aria-hidden />Impact warnings</div>
              <ul className="mt-1 list-disc pl-5">{preview.impact.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </div>
          )}
          <div className="grid gap-6 xl:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-ink-400 uppercase">Current policy (v{preview.base_version})</h3>
              <RulesTable doc={preview.current_document} highlight={new Set(preview.diff.removed_rules.map((r) => r.rule_id))} />
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-ink-400 uppercase">Proposed policy (v{preview.base_version + 1})</h3>
              <RulesTable doc={preview.proposed_document} highlight={added} />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-xs text-ink-300">
            <span>Added: {preview.diff.added_rules.map((r) => <Mono key={r.rule_id} className="mr-1">{r.rule_id}</Mono>)}{preview.diff.added_rules.length === 0 && "none"}</span>
            <span>Removed: {preview.diff.removed_rules.map((r) => <Mono key={r.rule_id} className="mr-1">{r.rule_id}</Mono>)}{preview.diff.removed_rules.length === 0 && "none"}</span>
          </div>
          <h3 className="mt-6 mb-2 text-xs font-semibold tracking-wide text-ink-400 uppercase">Impact on the demo scenario's requests (evaluated by the real engine)</h3>
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-xs text-ink-400"><tr className="border-b border-ink-800"><th className="py-2 font-medium">Request</th><th className="font-medium">Purpose</th><th className="font-medium">Before</th><th className="font-medium">After</th></tr></thead>
              <tbody className="divide-y divide-ink-800">
                {preview.impact.probes.map((p) => (
                  <tr key={p.tool + p.path} className={cx(p.changed && "bg-ink-850")}>
                    <td className="py-2"><Mono>{p.tool}("{p.path}")</Mono></td>
                    <td><Badge tone={p.purpose === "attack" ? "warn" : "neutral"}>{p.purpose}</Badge></td>
                    <td><PassFail passed={p.before.allowed} label={`${p.before.decision} · ${p.before.rule_id}`} /></td>
                    <td><PassFail passed={p.after.allowed} label={`${p.after.decision} · ${p.after.rule_id}`} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-ink-400">Green = allowed, red = denied. For attack requests, denied is the desired outcome.</p>
          </div>
        </Card>
      )}

      <Card title={<span className="flex items-center gap-2"><History className="size-4 text-ink-400" aria-hidden />Version history</span>} bodyClassName="p-0">
        <ul className="divide-y divide-ink-800">
          {history.map((h) => (
            <li key={h.version} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
              <span className="w-10 font-semibold tabular-nums">v{h.version}</span>
              <span className="min-w-0 flex-1 text-ink-200">{h.change_summary}</span>
              <span className="text-xs text-ink-400">{formatTime(h.created_at)}</span>
              {h.version === active.version
                ? <Badge tone="accent">active</Badge>
                : <Button variant="ghost" onClick={() => setRevertTarget(h.version)} icon={<RotateCcw className="size-3.5" />}>Restore rules</Button>}
            </li>
          ))}
        </ul>
      </Card>

      <ConfirmDialog open={confirm} title={`Apply policy v${(preview?.base_version ?? 0) + 1}?`} confirmLabel="Apply policy"
        onCancel={() => setConfirm(false)} onConfirm={() => void doApply.run()} pending={doApply.pending}>
        <p>The backend gateway will enforce the new rules on every subsequent tool call. The current version is kept and can be restored at any time.</p>
        <ul className="list-disc pl-5">{preview?.changes.map((c) => <li key={c.change_id}>{c.title}</li>)}</ul>
        {preview && preview.impact.warnings.length > 0 && <p className="text-amber-200">Warning: {preview.impact.warnings.join(" ")}</p>}
        <InlineError message={doApply.error} />
      </ConfirmDialog>

      <ConfirmDialog open={revertTarget !== undefined} title={`Restore the rules of v${revertTarget}?`} confirmLabel="Restore as new version"
        onCancel={() => setRevertTarget(undefined)} onConfirm={() => void doRevert.run()} pending={doRevert.pending}>
        <p>This creates v{active.version + 1} with the same rules as v{revertTarget}. Nothing is deleted from the history.</p>
        <InlineError message={doRevert.error} />
      </ConfirmDialog>
    </div>
  );
}
