import { useState } from "react";
import { Ban, Bot, CheckCircle2, FileText, Wrench } from "lucide-react";
import { api, type TranscriptEntry } from "../api";
import { useApi } from "../hooks";
import { Badge, EmptyState, Loading, Mono, cx } from "./ui";

function Entry({ e }: { e: TranscriptEntry }) {
  if (e.kind === "model_text") {
    return (
      <li className="flex gap-2.5 px-4 py-2.5">
        <Bot className="mt-0.5 size-4 shrink-0 text-accent-400" aria-hidden />
        <div className="min-w-0">
          <div className="text-xs font-medium text-ink-400">Model · step {e.step}</div>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink-200">{e.text}</p>
        </div>
      </li>
    );
  }
  if (e.kind === "error") {
    return (
      <li className="flex gap-2.5 px-4 py-2.5">
        <Ban className="mt-0.5 size-4 shrink-0 text-rose-300" aria-hidden />
        <div className="min-w-0 text-sm">
          <span className="text-xs font-medium text-ink-400">Rejected invalid tool call · step {e.step}</span>
          <p className="mt-0.5 text-rose-200">{e.text}</p>
        </div>
      </li>
    );
  }
  // tool_result
  const allowed = e.allowed;
  return (
    <li className="flex gap-2.5 px-4 py-2.5">
      <Wrench className="mt-0.5 size-4 shrink-0 text-ink-400" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Mono>{e.tool}</Mono>
          {e.resource_id && <span className="font-mono text-xs text-ink-300">{e.resource_id}</span>}
          {allowed
            ? <Badge tone="good"><CheckCircle2 className="size-3" aria-hidden /> allowed</Badge>
            : <Badge tone="bad"><Ban className="size-3" aria-hidden /> denied</Badge>}
          {e.rule_id && <span className="font-mono text-xs text-ink-500">{e.rule_id}</span>}
        </div>
      </div>
    </li>
  );
}

export function Transcript({ runId }: { runId: string }) {
  const t = useApi(() => api.runTranscript(runId), [runId]);
  if (t.loading && !t.data) return <Loading label="Loading tool-call history…" />;
  const entries = t.data?.transcript ?? [];
  if (entries.length === 0) return <EmptyState title="No tool-call history" icon={<FileText className="size-6" />}>This run has no recorded LLM transcript.</EmptyState>;
  return (
    <ol className="scroll-thin max-h-[420px] divide-y divide-ink-800 overflow-y-auto rounded-lg border border-ink-800">
      {entries.map((e, i) => <Entry key={i} e={e} />)}
    </ol>
  );
}

/** A compact, collapsible transcript used inline on run cards. */
export function CollapsibleTranscript({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)} className={cx("text-xs", open ? "text-accent-300" : "text-ink-400 hover:text-ink-200")}>
        {open ? "Hide" : "Show"} model tool-call history
      </button>
      {open && <div className="mt-2"><Transcript runId={runId} /></div>}
    </div>
  );
}
