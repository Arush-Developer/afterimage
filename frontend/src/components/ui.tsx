import { useEffect, useRef, type ReactNode } from "react";
import {
  AlertTriangle, Ban, CheckCircle2, CircleDashed, Info, Loader2, RefreshCw, X, XCircle,
} from "lucide-react";
import type { Category, Severity } from "../api";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function Card({ title, subtitle, actions, children, className, bodyClassName }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={cx("glass-panel rounded-2xl relative overflow-hidden transition-all duration-200", className)}>
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent pointer-events-none" />
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-6 py-4 bg-white/[0.01]">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-bold tracking-tight text-slate-100 flex items-center gap-2">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400 font-normal">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2.5">{actions}</div>}
        </header>
      )}
      <div className={cx("p-6", bodyClassName)}>{children}</div>
    </section>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export function Button({ children, variant = "secondary", pending, icon, className, ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; pending?: boolean; icon?: ReactNode }) {
  const styles: Record<ButtonVariant, string> = {
    primary: "bg-gradient-to-r from-emerald-400 to-teal-400 text-slate-950 font-bold hover:brightness-110 shadow-lg shadow-emerald-500/20 border-white/20 active:scale-[0.98]",
    secondary: "bg-slate-800/80 hover:bg-slate-800 text-slate-100 border-white/10 shadow-sm hover:border-white/20 active:scale-[0.98]",
    danger: "bg-gradient-to-r from-rose-500/20 to-pink-500/10 text-rose-200 hover:bg-rose-500/30 border-rose-500/30 active:scale-[0.98]",
    ghost: "bg-transparent text-slate-400 hover:text-slate-100 hover:bg-white/[0.04] border-transparent",
  };
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || pending}
      aria-busy={pending || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-xs tracking-wide font-semibold transition-all duration-150 cursor-pointer",
        "disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100",
        styles[variant], className,
      )}
    >
      {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

const severityStyle: Record<Severity, string> = {
  critical: "bg-rose-500/10 text-rose-300 border-rose-500/30 shadow-xs shadow-rose-500/10",
  high: "bg-orange-500/10 text-orange-300 border-orange-500/30",
  medium: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  low: "bg-sky-500/10 text-sky-300 border-sky-400/30",
  info: "bg-slate-800/70 text-slate-300 border-white/10",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide capitalize", severityStyle[severity])}>
      <span className="size-1.5 rounded-full bg-current opacity-80" />
      {severity}
    </span>
  );
}

export function Badge({ children, tone = "neutral", className }: {
  children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" | "accent"; className?: string;
}) {
  const tones = {
    neutral: "bg-slate-800/80 text-slate-300 border-white/10",
    good: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    bad: "bg-rose-500/10 text-rose-300 border-rose-500/30",
    warn: "bg-amber-500/10 text-amber-300 border-amber-500/30",
    accent: "bg-teal-500/10 text-teal-300 border-teal-500/30 shadow-xs shadow-teal-500/10",
  };
  return <span className={cx("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-[11px] font-medium tracking-wide", tones[tone], className)}>{children}</span>;
}

export const categoryMeta: Record<Category, { label: string; icon: typeof Info; text: string; ring: string; fill: string }> = {
  allowed: { label: "Allowed", icon: CheckCircle2, text: "text-emerald-400", ring: "#34d399", fill: "rgba(52,211,153,0.08)" },
  denied: { label: "Denied", icon: Ban, text: "text-rose-400", ring: "#fb7185", fill: "rgba(251,113,133,0.10)" },
  suspicious: { label: "Suspicious", icon: AlertTriangle, text: "text-amber-400", ring: "#fbbf24", fill: "rgba(251,191,36,0.10)" },
  info: { label: "Informational", icon: Info, text: "text-slate-400", ring: "#7c8794", fill: "rgba(124,135,148,0.08)" },
};

export function CategoryBadge({ category }: { category: Category }) {
  const meta = categoryMeta[category];
  const Icon = meta.icon;
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-semibold", meta.text)}>
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
    <span className={cx("inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-0.5 rounded-md bg-white/[0.02] border border-white/[0.04]", meta.text)}>
      <Icon className="size-3.5" aria-hidden />
      {outcome.replace(/_/g, " ")}
    </span>
  );
}

export function PassFail({ passed, label }: { passed: boolean; label?: string }) {
  return passed ? (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="size-3.5" aria-hidden />{label ?? "Pass"}</span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-rose-400"><XCircle className="size-3.5" aria-hidden />{label ?? "Fail"}</span>
  );
}

export function StatTile({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="glass-panel rounded-2xl p-5 relative overflow-hidden group hover:border-white/15 transition-all duration-300">
      <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider">
        <span>{label}</span>
        <div className="p-2 rounded-xl bg-white/[0.03] border border-white/[0.06] text-teal-400">{icon}</div>
      </div>
      <div className="mt-3 text-3xl font-extrabold tracking-tight tabular-nums text-slate-50">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400 font-normal">{hint}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-10 text-sm font-medium text-slate-400 justify-center">
      <Loader2 className="size-5 animate-spin text-teal-400" aria-hidden /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-500/20 bg-rose-500/[0.08] p-4 text-sm text-rose-100 backdrop-blur-md">
      <span className="flex items-center gap-2.5 font-medium"><XCircle className="size-4 shrink-0 text-rose-400" aria-hidden />{message}</span>
      {onRetry && <Button variant="ghost" onClick={onRetry} icon={<RefreshCw className="size-3.5" />}>Retry</Button>}
    </div>
  );
}

export function InlineError({ message, onDismiss }: { message?: string; onDismiss?: () => void }) {
  if (!message) return null;
  return (
    <div role="alert" className="mt-3 flex items-start justify-between gap-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.08] px-4 py-3 text-xs text-rose-200">
      <span>{message}</span>
      {onDismiss && <button aria-label="Dismiss" onClick={onDismiss} className="text-rose-300 hover:text-white cursor-pointer"><X className="size-4" /></button>}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-8 py-14 text-center bg-white/[0.01]">
      <div className="p-3.5 rounded-2xl bg-white/[0.03] border border-white/[0.06] text-slate-400">{icon ?? <CircleDashed className="size-6" aria-hidden />}</div>
      <p className="mt-4 text-sm font-bold text-slate-200 tracking-tight">{title}</p>
      {children && <div className="mt-1.5 max-w-sm text-xs text-slate-400 leading-relaxed">{children}</div>}
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3.5 sm:grid-cols-2">
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0 p-3 rounded-xl bg-white/[0.01] border border-white/[0.03]">
          <dt className="text-[11px] font-semibold text-slate-400 tracking-wide uppercase">{k}</dt>
          <dd className="mt-1 break-words text-sm font-medium text-slate-100">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cx("rounded-md bg-slate-900/80 px-2 py-0.5 font-mono text-[11px] text-teal-300 border border-teal-500/20", className)}>{children}</code>;
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-fade-in" onMouseDown={() => !pending && onCancel()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0c1018] shadow-2xl shadow-black/90 outline-none p-1"
      >
        <div className="border-b border-white/[0.08] px-6 py-5"><h3 className="text-base font-bold text-slate-100">{title}</h3></div>
        <div className="space-y-3.5 px-6 py-5 text-xs text-slate-300 leading-relaxed">{children}</div>
        <div className="flex justify-end gap-2.5 border-t border-white/[0.08] px-6 py-4 bg-white/[0.01] rounded-b-2xl">
          <Button variant="ghost" onClick={onCancel} disabled={pending}>Cancel</Button>
          <Button variant={variant} onClick={onConfirm} pending={pending} disabled={confirmDisabled}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-5 border-b border-white/[0.06] pb-6">
      <div>
        <div className="text-[11px] font-bold text-teal-400 uppercase tracking-widest mb-1.5 font-mono">FORENSIC OPERATION</div>
        <h1 className="text-2xl font-black tracking-tight text-slate-50 sm:text-3xl">{title}</h1>
        {description && <p className="mt-1.5 max-w-3xl text-xs sm:text-sm text-slate-400 font-normal leading-relaxed">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </div>
  );
}

export function SimulatedNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-amber-500/20 bg-amber-500/[0.06] p-4 text-xs text-amber-200/90 backdrop-blur-sm">
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
