import { useState } from "react";
import { Camera, CheckCircle2, FileCode2, Info, RotateCcw, Wand2, XCircle } from "lucide-react";
import { api, type RestoreResult, type Snapshot } from "../api";
import { formatBytes, formatTime, shortHash } from "../format";
import { useAction, useApi } from "../hooks";
import {
  Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, InlineError, Loading, Mono, PageHeader, SimulatedNotice, cx,
} from "../components/ui";

export function RecoveryVault() {
  const files = useApi(api.vaultFiles);
  const snaps = useApi(api.snapshots);
  const [path, setPath] = useState<string>();
  const [selected, setSelected] = useState<Snapshot>();
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<RestoreResult>();

  const refresh = async () => { await Promise.all([files.reload(), snaps.reload()]); };
  const activePath = path ?? files.data?.[0]?.path;

  const simulate = useAction(async (p: string) => {
    const r = await api.simulateChange(p);
    setResult(undefined);
    await refresh();
    setSelected(await api.snapshot(r.snapshot.snapshot_id));
  });
  const snapshotNow = useAction(async (p: string) => {
    const s = await api.createSnapshot(p, "manual snapshot");
    await refresh();
    setSelected(await api.snapshot(s.snapshot_id));
  });
  const open = useAction(async (id: string) => setSelected(await api.snapshot(id)));
  const restore = useAction(async () => {
    if (!selected) return;
    const r = await api.restoreSnapshot(selected.snapshot_id);
    setResult(r);
    setConfirm(false);
    await refresh();
    setSelected(await api.snapshot(selected.snapshot_id));
  });

  const err = files.error || snaps.error;
  if (err) return <ErrorState message={err} onRetry={() => void refresh()} />;
  if (!files.data || !snaps.data) return <Loading />;
  const current = files.data.find((f) => f.path === activePath);
  const versions = snaps.data.filter((s) => s.file_path === activePath).sort((a, b) => b.version - a.version);

  return (
    <div className="space-y-6">
      <PageHeader title="Recovery Vault" description="Versioned, hash-verified snapshots of synthetic project files. Snapshots are taken automatically before simulated modifications and before every restore." />
      <SimulatedNotice>Restoring a file returns its bytes to a previous version. It does not reverse external side effects such as network requests or changes in other systems.</SimulatedNotice>
      <InlineError message={simulate.error || snapshotNow.error || open.error} onDismiss={() => { simulate.clearError(); snapshotNow.clearError(); open.clearError(); }} />

      <div className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <Card title="Protected files" bodyClassName="p-0">
          <ul className="divide-y divide-ink-800">
            {files.data.map((f) => (
              <li key={f.path}>
                <button onClick={() => { setPath(f.path); setSelected(undefined); setResult(undefined); }}
                  className={cx("w-full px-5 py-3 text-left hover:bg-ink-850", activePath === f.path && "bg-ink-850")}>
                  <div className="flex items-center gap-2 text-sm"><FileCode2 className="size-4 text-ink-400" aria-hidden /><span className="font-mono">{f.path}</span></div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-400">
                    <span className="font-mono">{shortHash(f.sha256)}</span>
                    <span>{formatBytes(f.size_bytes)}</span>
                    <span>{f.snapshot_count} snapshot{f.snapshot_count === 1 ? "" : "s"}</span>
                    {f.matches_original ? <Badge tone="good">matches original</Badge> : <Badge tone="warn">modified</Badge>}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-6">
          {current && (
            <Card title={<span className="font-mono">{current.path}</span>} subtitle={<>Current SHA-256 <span className="font-mono break-all">{current.sha256}</span></>}
              actions={<>
                <Button onClick={() => void snapshotNow.run(current.path)} pending={snapshotNow.pending} icon={<Camera className="size-4" />}>Snapshot now</Button>
                <Button variant="danger" onClick={() => void simulate.run(current.path)} pending={simulate.pending} disabled={!current.matches_original}
                  icon={<Wand2 className="size-4" />} title={current.matches_original ? "" : "Restore the file before simulating another edit"}>Simulate unauthorized edit</Button>
              </>}>
              {versions.length === 0 ? (
                <EmptyState title="No snapshots for this file yet">Use <b>Simulate unauthorized edit</b> — it snapshots the file first, then changes it.</EmptyState>
              ) : (
                <ul className="space-y-2">
                  {versions.map((s) => (
                    <li key={s.snapshot_id}>
                      <button onClick={() => void open.run(s.snapshot_id)}
                        className={cx("flex w-full flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm",
                          selected?.snapshot_id === s.snapshot_id ? "border-accent-500/50 bg-accent-500/5" : "border-ink-700 hover:border-ink-600")}>
                        <span className="font-semibold tabular-nums">v{s.version}</span>
                        <span className="font-mono text-xs text-ink-300">{shortHash(s.sha256, 16)}</span>
                        <span className="flex-1 text-xs text-ink-400">{s.reason}</span>
                        {s.sha256 === current.sha256 && <Badge tone="good">= current</Badge>}
                        <span className="text-xs text-ink-500">{formatTime(s.created_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          {selected && (
            <Card title={`Snapshot v${selected.version}`} subtitle={<span className="font-mono">{selected.snapshot_id}</span>}
              actions={<Button variant="primary" onClick={() => setConfirm(true)} disabled={selected.current_sha256 === selected.sha256} icon={<RotateCcw className="size-4" />}>Restore this version…</Button>}>
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium text-ink-400">Snapshot content (synthetic)</div>
                  <pre className="scroll-thin max-h-64 overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-relaxed text-ink-200">{selected.content}</pre>
                </div>
                <div>
                  <div className="mb-1 text-xs font-medium text-ink-400">Diff: current file → snapshot</div>
                  <pre className="scroll-thin max-h-64 overflow-auto rounded-lg bg-ink-950 p-3 font-mono text-[11px] leading-relaxed">
                    {selected.diff_to_current ? selected.diff_to_current.split("\n").map((l, i) => (
                      <span key={i} className={cx("block", l.startsWith("+") && !l.startsWith("+++") ? "text-emerald-300" : l.startsWith("-") && !l.startsWith("---") ? "text-rose-300" : "text-ink-400")}>{l || " "}</span>
                    )) : <span className="text-ink-400">No differences — the current file matches this snapshot.</span>}
                  </pre>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-400">
                <span>Stored object integrity: {selected.store_integrity_ok ? <span className="text-emerald-300">hash verified</span> : <span className="text-rose-300">FAILED</span>}</span>
                <span>Size: {formatBytes(selected.size_bytes)}</span>
              </div>
            </Card>
          )}

          {result && (
            <Card title="Recovery result" subtitle={result.note}>
              <div data-testid="restore-result" className={cx("mb-4 flex items-center gap-2 text-sm font-medium", result.verified ? "text-emerald-300" : "text-rose-300")}>
                {result.verified ? <CheckCircle2 className="size-4" aria-hidden /> : <XCircle className="size-4" aria-hidden />}
                {result.verified ? "Restored and hash-verified" : "Restore hash mismatch"}
              </div>
              <table className="w-full text-sm">
                <tbody className="divide-y divide-ink-800">
                  <tr><th scope="row" className="py-2 pr-4 text-left font-normal text-ink-400">Original version (snapshot v{result.snapshot.version})</th><td className="font-mono text-xs break-all">{result.expected_sha256}</td></tr>
                  <tr><th scope="row" className="py-2 pr-4 text-left font-normal text-ink-400">Modified version (before restore)</th><td className="font-mono text-xs break-all">{result.before_sha256}</td></tr>
                  <tr><th scope="row" className="py-2 pr-4 text-left font-normal text-ink-400">Restored version (re-hashed from disk)</th><td className="font-mono text-xs break-all">{result.restored_sha256}</td></tr>
                </tbody>
              </table>
              <p className="mt-3 flex items-center gap-2 text-xs text-ink-400"><Info className="size-3.5" aria-hidden />The modified version was saved as snapshot v{result.pre_restore_backup.version} first, so this restore can be undone.</p>
            </Card>
          )}
        </div>
      </div>

      <ConfirmDialog open={confirm} title={`Restore ${selected?.file_path} to v${selected?.version}?`} confirmLabel="Restore file"
        onCancel={() => setConfirm(false)} onConfirm={() => void restore.run()} pending={restore.pending}>
        <p>The current contents will be snapshotted first, then replaced with snapshot v{selected?.version} (<Mono>{shortHash(selected?.sha256)}</Mono>). The result is re-hashed and compared.</p>
        <InlineError message={restore.error} />
      </ConfirmDialog>
    </div>
  );
}
