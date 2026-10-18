import { useState } from "react";
import { Cloud, Database, FlaskRound, RotateCcw, Trash2 } from "lucide-react";
import { api } from "../api";
import { formatBytes } from "../format";
import { useAction, useApi } from "../hooks";
import { Badge, Button, Card, ConfirmDialog, ErrorState, InlineError, KeyValue, Loading, Mono, PageHeader } from "../components/ui";

export function Settings() {
  const settings = useApi(api.settings);
  const [mode, setMode] = useState<"demo" | "full">();
  const [typed, setTyped] = useState("");
  const [done, setDone] = useState<string>();
  const reset = useAction(async () => {
    if (!mode) return;
    const result = await api.reset(mode, typed);
    setDone(mode === "full"
      ? `Full reset complete. Previous evidence archived as ${String(result.archive)}.`
      : `Demo reset complete. Policy is back to baseline (v${String(result.policy_version)}); evidence was kept.`);
    setMode(undefined);
    setTyped("");
    await settings.reload();
  });

  if (settings.error) return <ErrorState message={settings.error} onRetry={settings.reload} />;
  if (!settings.data) return <Loading />;
  const s = settings.data;
  const phrase = mode === "full" ? s.reset_phrase : "RESET DEMO";

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Local environment status and safe reset controls." />
      {done && <div role="status" className="rounded-xl border border-accent-500/30 bg-accent-500/5 px-4 py-3 text-sm">{done}</div>}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Database className="size-4 text-accent-400" aria-hidden />Local database</span>}>
          <KeyValue items={[
            ["Engine", s.database.engine],
            ["File", <Mono>{s.database.file}</Mono>],
            ["Size", formatBytes(s.database.size_bytes)],
            ["Recorded events", s.database.events],
            ["Hash chain", s.database.hash_chain.valid
              ? <Badge tone="good">intact ({s.database.hash_chain.checked} events)</Badge>
              : <Badge tone="bad">broken at {s.database.hash_chain.first_invalid_event_id}</Badge>],
            ["Archives", s.archives.length ? s.archives.join(", ") : "none"],
          ]} />
          <p className="mt-4 text-xs text-ink-400">The hash chain makes casual edits to individual rows detectable. It is not tamper-proof: anyone with write access to the database file could rebuild the whole chain.</p>
        </Card>

        <Card title={<span className="flex items-center gap-2"><FlaskRound className="size-4 text-accent-400" aria-hidden />Demo environment</span>}>
          <KeyValue items={[
            ["Data", s.demo_environment.synthetic_only ? "Synthetic only (fictional project, fake secret)" : "—"],
            ["Agent / LLM", s.demo_environment.llm],
            ["Scenarios", s.demo_environment.scenarios.join(", ")],
            ["Run workspaces on disk", s.demo_environment.run_workspaces],
            ["Vault files", s.demo_environment.vault_files.map((f) => <Mono key={f} className="mr-1">{f}</Mono>)],
            ["Allowed CORS origins", s.cors_origins.join(", ")],
            ["Version", s.version],
          ]} />
        </Card>
      </div>

      <Card title={<span className="flex items-center gap-2"><Cloud className="size-4 text-ink-400" aria-hidden />Cloud sync</span>}>
        <div className="flex flex-wrap items-center gap-3 text-sm"><Badge>{s.cloud_sync.status.replace("_", " ")}</Badge><span className="text-ink-300">{s.cloud_sync.detail}</span></div>
      </Card>

      <Card title="Reset" subtitle="Resets never silently erase evidence.">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-ink-700 p-4">
            <div className="flex items-center gap-2 text-sm font-medium"><RotateCcw className="size-4" aria-hidden />Reset demo environment</div>
            <p className="mt-1 text-sm text-ink-400">Restores the baseline policy (as a new version), resets vault files (snapshotting them first) and removes per-run synthetic workspaces. All runs, incidents, events and replay reports are kept.</p>
            <Button className="mt-3" onClick={() => { setMode("demo"); setTyped(""); }}>Reset demo…</Button>
          </div>
          <div className="rounded-lg border border-rose-400/20 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-rose-200"><Trash2 className="size-4" aria-hidden />Archive & start fresh</div>
            <p className="mt-1 text-sm text-ink-400">Copies the full database to <Mono>data/archives/</Mono>, then starts a new empty database. Evidence is preserved in the archive file, not deleted.</p>
            <Button variant="danger" className="mt-3" onClick={() => { setMode("full"); setTyped(""); }}>Archive & reset…</Button>
          </div>
        </div>
      </Card>

      <ConfirmDialog open={mode !== undefined} title={mode === "full" ? "Archive evidence and start fresh?" : "Reset the demo environment?"}
        confirmLabel={mode === "full" ? "Archive & reset" : "Reset demo"} variant={mode === "full" ? "danger" : "primary"}
        onCancel={() => setMode(undefined)} onConfirm={() => void reset.run()} pending={reset.pending} confirmDisabled={typed !== phrase}>
        <p>{mode === "full"
          ? "The current database will be archived, then replaced by an empty one. The dashboard will start from zero."
          : "Policy, vault files and run workspaces return to their initial state. Recorded evidence stays."}</p>
        <label className="block">Type <Mono>{phrase}</Mono> to confirm
          <input aria-label="Confirmation phrase" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off"
            className="mt-1 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm text-ink-100" />
        </label>
        <InlineError message={reset.error} />
      </ConfirmDialog>
    </div>
  );
}
