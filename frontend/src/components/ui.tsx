import { useEffect, useRef, type ReactNode } from "react";
import {
  AlertTriangle, Ban, CheckCircle2, CircleDashed, Info, Loader2, RefreshCw, ShieldAlert, X, XCircle,
} from "lucide-react";
import type { Category, Severity } from "../api";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function Card({ title, subtitle, actions, children, className, bodyClassName }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-ink-800/80 bg-ink-900/70 shadow-sm backdrop-blur-xs", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-800/60 px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold tracking-tight text-ink-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({ children, variant = "secondary", pending, icon, className, ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; pending?: boolean; icon?: ReactNode }) {
  const styles: Record<ButtonVariant, string> = {
    primary: "bg-gradient-to-r from-accent-500 to-accent-600 text-ink-950 font-semibold hover:brightness-110 border-accent-400/40 shadow-sm shadow-accent-500/20",
    secondary: "bg-ink-850/90 text-ink-200 hover:bg-ink-800 hover:text-ink-100 border-ink-700/80",
    danger: "bg-rose-500/15 text-rose-200 hover:bg-rose-500/25 border-rose-500/40",
    ghost: "bg-transparent text-ink-400 hover:bg-ink-800/50 hover:text-ink-100 border-transparent",
  };
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || pending}
      aria-busy={pending || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all active:scale-[0.98]",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        styles[variant], className,
      )}
    >
      {pending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

const severityStyle: Record<Severity, string> = {
  critical: "bg-rose-500/15 text-rose-200 border-rose-500/40",
  high: "bg-orange-500/15 text-orange-200 border-orange-500/40",
  medium: "bg-amber-500/15 text-amber-200 border-amber-500/40",
  low: "bg-sky-500/10 text-sky-200 border-sky-400/30",
  info: "bg-ink-800/80 text-ink-300 border-ink-700/60",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium capitalize", severityStyle[severity])}>
      <ShieldAlert className="size-3.5" aria-hidden />
      {severity}
    </span>
  );
}

export function Badge({ children, tone = "neutral", className }: {
  children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" | "accent"; className?: string;
}) {
  const tones = {
    neutral: "bg-ink-800/70 text-ink-300 border-ink-700/70",
    good: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    bad: "bg-rose-500/10 text-rose-300 border-rose-500/30",
    warn: "bg-amber-500/10 text-amber-300 border-amber-500/30",
    accent: "bg-accent-500/10 text-accent-300 border-accent-400/30",
  };
  return <span className={cx("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium", tones[tone], className)}>{children}</span>;
}

export const categoryMeta: Record<Category, { label: string; icon: typeof Info; text: string; ring: string; fill: string }> = {
  allowed: { label: "Allowed", icon: CheckCircle2, text: "text-emerald-400", ring: "#34d399", fill: "rgba(52,211,153,0.08)" },
  denied: { label: "Denied", icon: Ban, text: "text-rose-400", ring: "#fb7185", fill: "rgba(251,113,133,0.10)" },
  suspicious: { label: "Suspicious", icon: AlertTriangle, text: "text-amber-400", ring: "#fbbf24", fill: "rgba(251,191,36,0.10)" },
  info: { label: "Informational", icon: Info, text: "text-ink-400", ring: "#7c8794", fill: "rgba(124,135,148,0.08)" },
};

export function CategoryBadge({ category }: { category: Category }) {
  const meta = categoryMeta[category];
  const Icon = meta.icon;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium", meta.text)}>
      <Icon className="size-3.5" aria-hidden />
      {meta.label}
    </span>
  );
}

export function outcomeCategory(outcome: string): Category {
  if (["allowed", "success", "verified", "applied"].includes(outcome)) return "allowed";
  if (["denied", "blocked", "approval_required", "failed", "error", "hash_mismatch"].includes(outcome)) return "denied";
  if (["exposed", "exposure_confirmed", "regression", "modified"].includes(outcome)) return "suspicious";
  return "info";
}

export function OutcomeTag({ outcome }: { outcome: string }) {
  const cat = outcomeCategory(outcome);
  const meta = categoryMeta[cat];
  const Icon = meta.icon;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-medium", meta.text)}>
      <Icon className="size-3.5" aria-hidden />
      {outcome.replace(/_/g, " ")}
    </span>
  );
}

export function PassFail({ passed, label }: { passed: boolean; label?: string }) {
  return passed ? (
    <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-400"><CheckCircle2 className="size-4" aria-hidden />{label ?? "Pass"}</span>
  ) : (
    <span className="inline-flex items-center gap-1 text-sm font-medium text-rose-400"><XCircle className="size-4" aria-hidden />{label ?? "Fail"}</span>
  );
}

export function StatTile({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-800/80 bg-ink-900/80 p-4.5 shadow-sm">
      <div className="flex items-center justify-between text-xs font-medium text-ink-400">
        <span>{label}</span>
        <span className="text-ink-500">{icon}</span>
      </div>
      <div className="mt-2 text-2xl font-bold tracking-tight tabular-nums text-ink-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-400">{hint}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-sm text-ink-400">
      <Loader2 className="size-4 animate-spin text-accent-400" aria-hidden /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
      <span className="flex items-center gap-2"><XCircle className="size-4 shrink-0 text-rose-400" aria-hidden />{message}</span>
      {onRetry && <Button variant="ghost" onClick={onRetry} icon={<RefreshCw className="size-4" />}>Retry</Button>}
    </div>
  );
}

export function InlineError({ message, onDismiss }: { message?: string; onDismiss?: () => void }) {
  if (!message) return null;
  return (
    <div role="alert" className="mt-3 flex items-start justify-between gap-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
      <span>{message}</span>
      {onDismiss && <button aria-label="Dismiss" onClick={onDismiss} className="text-rose-200 hover:text-white"><X className="size-4" /></button>}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-800/80 px-6 py-12 text-center bg-ink-900/30">
      <div className="text-ink-500">{icon ?? <CircleDashed className="size-7" aria-hidden />}</div>
      <p className="mt-3 text-sm font-medium text-ink-200">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-ink-400">{children}</div>}
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs font-medium text-ink-400">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink-100">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cx("rounded bg-ink-800/80 px-1.5 py-0.5 font-mono text-[0.8em] text-ink-200 border border-ink-700/50", className)}>{children}</code>;
}

export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onCancel, pending, variant = "primary", confirmDisabled }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void;
  pending?: boolean; variant?: "primary" | "danger"; confirmDisabled?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !pending && onCancel();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, pending, onCancel]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4" onMouseDown={() => !pending && onCancel()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-ink-700 bg-ink-850 shadow-2xl shadow-black/80 outline-none"
      >
        <div className="border-b border-ink-750 px-5 py-4"><h3 className="text-base font-semibold text-ink-100">{title}</h3></div>
        <div className="space-y-3 px-5 py-4 text-sm text-ink-300">{children}</div>
        <div className="flex justify-end gap-2 border-t border-ink-750 px-5 py-3.5 bg-ink-900/50 rounded-b-xl">
          <Button variant="ghost" onClick={onCancel} disabled={pending}>Cancel</Button>
          <Button variant={variant} onClick={onConfirm} pending={pending} disabled={confirmDisabled}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-ink-100 sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SimulatedNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/25 bg-amber-500/5 px-3.5 py-2.5 text-xs text-amber-200/90">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" aria-hidden />
      <span className="leading-relaxed">{children ?? "Controlled simulation on synthetic data. No real system, credential or user data is involved."}</span>
    </div>
  );
}

const RUN_PROVIDER_LABEL: Record<string, string> = { anthropic: "Claude", gemini: "Gemini", ollama: "Ollama · local" };

export function RunKindBadge({ run }: { run: { agent_kind: string; provider?: string | null; model?: string | null; provider_real?: boolean | null } }) {
  if (run.agent_kind !== "llm") return <Badge tone="neutral">scripted</Badge>;
  if (!run.provider_real) return <Badge tone="warn">simulated{run.model ? ` · ${run.model}` : ""}</Badge>;
  const label = RUN_PROVIDER_LABEL[run.provider ?? ""] ?? run.provider ?? "LLM";
  return <Badge tone={run.provider === "ollama" ? "good" : "accent"}>{label}{run.model ? ` · ${run.model}` : ""}</Badge>;
}

export function EnforcementBadge({ enforcement }: { enforcement: string }) {
  return enforcement === "baseline"
    ? <Badge tone="bad">enforcement OFF</Badge>
    : <Badge tone="good">enforcement ON</Badge>;
}
