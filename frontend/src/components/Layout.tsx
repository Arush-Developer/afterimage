import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity, Archive, FlaskConical, LayoutDashboard, ListTree, Menu, Network, Settings, Shield, ShieldAlert, Syringe, X,
} from "lucide-react";
import { api } from "../api";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/incidents", label: "Incidents", icon: ShieldAlert },
  { to: "/investigation", label: "Investigation", icon: Network },
  { to: "/replay", label: "Replay Lab", icon: FlaskConical },
  { to: "/experiment", label: "Injection Lab", icon: Syringe },
  { to: "/policies", label: "Policies", icon: Shield },
  { to: "/recovery", label: "Recovery Vault", icon: Archive },
  { to: "/events", label: "Event Explorer", icon: ListTree },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <circle cx="14" cy="16" r="8" fill="none" stroke="#34d3a6" strokeWidth="2.5" />
        <circle cx="18" cy="16" r="8" fill="none" stroke="#34d3a6" strokeOpacity=".35" strokeWidth="2.5" />
      </svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-[0.18em] text-ink-100">AFTERIMAGE</div>
        <div className="text-[10px] text-ink-400">Agent incident forensics</div>
      </div>
    </div>
  );
}

function BackendStatus() {
  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking");
  useEffect(() => {
    let alive = true;
    const check = () => api.health().then(() => alive && setStatus("ok")).catch(() => alive && setStatus("down"));
    void check();
    const t = window.setInterval(check, 15000);
    return () => { alive = false; window.clearInterval(t); };
  }, []);
  const label = status === "ok" ? "Backend connected" : status === "down" ? "Backend unreachable" : "Checking backend";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-300" title="Polls GET /api/health every 15 s">
      <span className={cx("size-2 rounded-full", status === "ok" ? "bg-emerald-400" : status === "down" ? "bg-rose-400" : "bg-ink-500")} aria-hidden />
      {label}
    </span>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const current = NAV.find((n) => (n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)));

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => cx(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
            isActive ? "bg-accent-500/10 text-accent-300" : "text-ink-300 hover:bg-ink-800 hover:text-ink-100",
          )}
        >
          <Icon className="size-4" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="hidden border-r border-ink-800 bg-ink-900/60 lg:block">
        <div className="sticky top-0 flex h-screen flex-col px-3 py-5">
          <div className="px-2"><Logo /></div>
          <div className="mt-8 flex-1">{nav}</div>
          <div className="rounded-lg border border-ink-700/70 px-3 py-2.5 text-[11px] leading-relaxed text-ink-400">
            <Activity className="mb-1 size-3.5 text-accent-400" aria-hidden />
            Observe → Enforce → Investigate → Remediate → Replay → Verify
          </div>
        </div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-64 border-r border-ink-700 bg-ink-900 px-3 py-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between px-2">
              <Logo />
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="text-ink-300"><X className="size-5" /></button>
            </div>
            {nav}
          </div>
        </div>
      )}

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-ink-800 bg-ink-950/90 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-3">
            <button aria-label="Open navigation" className="text-ink-300 lg:hidden" onClick={() => setOpen(true)}><Menu className="size-5" /></button>
            <span className="text-sm text-ink-400">AFTERIMAGE</span>
            <span className="text-ink-600">/</span>
            <span className="text-sm font-medium text-ink-100">{current?.label ?? "Overview"}</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden rounded-md border border-ink-700 px-2 py-0.5 text-[11px] text-ink-400 sm:inline">Synthetic demo environment</span>
            <BackendStatus />
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
