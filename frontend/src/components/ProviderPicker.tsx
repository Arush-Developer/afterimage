import { useState } from "react";
import { AlertTriangle, CheckCircle2, Cpu, HelpCircle, Plug, XCircle } from "lucide-react";
import { api, type ProviderCheck, type ProvidersResponse } from "../api";
import { useAction } from "../hooks";
import { ProviderWhereBadge, explainProviderError } from "../providers";
import { Button, cx } from "./ui";

export interface ProviderSelection {
  provider: string;
  model: string;
}

function Flag({ ok, label }: { ok: boolean | null; label: string }) {
  const Icon = ok === null ? HelpCircle : ok ? CheckCircle2 : XCircle;
  const color = ok === null ? "text-ink-400" : ok ? "text-emerald-300" : "text-rose-300";
  return <span className={cx("inline-flex items-center gap-1 text-xs", color)}><Icon className="size-3.5" aria-hidden />{label}</span>;
}

/** Live result of GET /api/providers/{provider}/check. */
export function CheckResult({ check }: { check: ProviderCheck }) {
  const help = check.error_kind ? explainProviderError(check.error_kind, check.provider) : null;
  return (
    <div data-testid="provider-check" className="rounded-lg border border-ink-700 bg-ink-950/60 p-3 text-sm">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <Flag ok={check.configured} label={check.configured ? "configured" : "not configured"} />
        <Flag ok={check.configured ? check.reachable : null} label={check.reachable ? "reachable" : "not reachable"} />
        <Flag ok={check.reachable ? check.model_available : null} label={check.model_available ? `model ${check.model} available` : `model ${check.model ?? ""} unavailable`} />
        <Flag ok={check.tool_calling === "unknown" ? null : check.tool_calling === "supported"}
          label={`tool calling: ${check.tool_calling}`} />
      </div>
      <p className="mt-1.5 text-xs text-ink-300">{check.detail}</p>
      {help && <ul className="mt-1 list-disc pl-5 text-xs text-ink-400">{help.tips.map((t) => <li key={t}>{t}</li>)}</ul>}
    </div>
  );
}

/** Provider picker plus model field and a live connection check. Shows configuration
 *  status from the backend and never implies credentials are present unless it says so. */
export function ProviderPicker({ data, value, onChange, disabled }: {
  data: ProvidersResponse;
  value: ProviderSelection;
  onChange: (next: ProviderSelection) => void;
  disabled?: boolean;
}) {
  const current = data.providers.find((p) => p.provider === value.provider);
  const [check, setCheck] = useState<ProviderCheck>();
  const runCheck = useAction(async () => setCheck(await api.checkProvider(value.provider, value.model || undefined)));
  const select = (next: ProviderSelection) => { setCheck(undefined); onChange(next); };

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {data.providers.map((p) => {
          const selected = p.provider === value.provider;
          return (
            <button
              key={p.provider}
              type="button"
              disabled={disabled}
              aria-pressed={selected}
              onClick={() => select({ provider: p.provider, model: data.default_models[p.provider] ?? "" })}
              className={cx("rounded-lg border p-3 text-left transition-colors disabled:opacity-50",
                selected ? "border-accent-500/60 bg-accent-500/5" : "border-ink-700 hover:border-ink-600")}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Cpu className="size-4 shrink-0 text-ink-400" aria-hidden />{p.label}
                </span>
                {p.configured
                  ? <CheckCircle2 className="size-4 shrink-0 text-emerald-400" aria-label="configured" />
                  : <XCircle className="size-4 shrink-0 text-ink-500" aria-label="not configured" />}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-400">
                <ProviderWhereBadge provider={p.provider} />
                {!p.configured && <span className="text-ink-500">not configured</span>}
              </div>
            </button>
          );
        })}
      </div>

      {current && (
        <p className={cx("flex items-start gap-2 text-xs", current.configured ? "text-ink-400" : "text-amber-200")}>
          {current.configured ? null : <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
          {current.detail}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[220px] flex-1 text-sm">
          <span className="mb-1 block text-xs font-medium text-ink-400">Model</span>
          <input
            value={value.model}
            disabled={disabled}
            onChange={(e) => { setCheck(undefined); onChange({ ...value, model: e.target.value }); }}
            placeholder={current?.default_model}
            className="w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-xs text-ink-100 placeholder:text-ink-500 disabled:opacity-50"
          />
        </label>
        <Button onClick={() => void runCheck.run()} pending={runCheck.pending} disabled={disabled}
          icon={<Plug className="size-4" />} title="Verify credentials, model and tool-calling support without generating content">
          Check
        </Button>
      </div>
      {value.provider === "gemini" && (
        <p className="text-xs text-ink-500">Free-tier models and limits vary by Google project and change over time; Check verifies that this model is available to your key.</p>
      )}
      {check && <CheckResult check={check} />}
      {runCheck.error && <p role="alert" className="text-xs text-rose-300">{runCheck.error}</p>}
    </div>
  );
}
