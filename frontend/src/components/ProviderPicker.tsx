import { AlertTriangle, CheckCircle2, Cpu, XCircle } from "lucide-react";
import type { ProvidersResponse } from "../api";
import { Badge, cx } from "./ui";

export interface ProviderSelection {
  provider: string;
  model: string;
}

/** Radio-style provider picker plus a model field. Shows live configuration status and
 *  never implies credentials are present unless the backend says so. */
export function ProviderPicker({ data, value, onChange, disabled }: {
  data: ProvidersResponse;
  value: ProviderSelection;
  onChange: (next: ProviderSelection) => void;
  disabled?: boolean;
}) {
  const current = data.providers.find((p) => p.provider === value.provider);
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        {data.providers.map((p) => {
          const selected = p.provider === value.provider;
          return (
            <button
              key={p.provider}
              type="button"
              disabled={disabled}
              aria-pressed={selected}
              onClick={() => onChange({ provider: p.provider, model: data.default_models[p.provider] ?? "" })}
              className={cx("rounded-lg border p-3 text-left transition-colors disabled:opacity-50",
                selected ? "border-accent-500/60 bg-accent-500/5" : "border-ink-700 hover:border-ink-600")}
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Cpu className="size-4 text-ink-400" aria-hidden />{p.label}
                </span>
                {p.configured
                  ? <CheckCircle2 className="size-4 text-emerald-400" aria-label="configured" />
                  : <XCircle className="size-4 text-ink-500" aria-label="not configured" />}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-400">
                {p.real ? <Badge tone="accent">real model</Badge> : <Badge tone="warn">simulated</Badge>}
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

      <label className="block text-sm">
        <span className="mb-1 block text-xs font-medium text-ink-400">Model</span>
        <input
          value={value.model}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, model: e.target.value })}
          placeholder={current?.default_model}
          className="w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-xs text-ink-100 placeholder:text-ink-500 disabled:opacity-50"
        />
      </label>
    </div>
  );
}
