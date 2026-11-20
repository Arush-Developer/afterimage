import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Archive, FlaskConical, LayoutDashboard, ListTree, Menu, Network, Settings, Shield, ShieldAlert, Syringe, X,
  Radio, Sparkles
} from "lucide-react";
import { api } from "../api";
import { cx } from "./ui";

const NAV_PHASES = [
  {
    phase: "01 // Observe",
    items: [
      { to: "/", label: "Forensic Overview", icon: LayoutDashboard, end: true },
    ],
  },
  {
    phase: "02 // Enforce",
    items: [
      { to: "/incidents", label: "Incident Ledger", icon: ShieldAlert },
      { to: "/investigation", label: "Evidence Chamber", icon: Network },
    ],
  },
  {
    phase: "03 // Remediate",
    items: [
      { to: "/policies", label: "Security Policies", icon: Shield },
    ],
  },
  {
    phase: "04 // Replay",
    items: [
      { to: "/replay", label: "Replay Sandbox", icon: FlaskConical },
      { to: "/experiment", label: "LLM Injection Lab", icon: Syringe },
    ],
  },
  {
    phase: "05 // Verify",
    items: [
      { to: "/recovery", label: "Recovery Vault", icon: Archive },
      { to: "/events", label: "Event Hash Chain", icon: ListTree },
    ],
  },
];

const NAV_SETTINGS = { to: "/settings", label: "System Config", icon: Settings };
const NAV = NAV_PHASES.flatMap((p) => p.items).concat(NAV_SETTINGS);

function Logo() {
  return (
    <div className="flex items-center gap-3">
      <div className="relative size-8 flex items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-lg shadow-emerald-500/25">
        <div className="absolute inset-0 rounded-xl bg-white/20 mix-blend-overlay" />
        <svg viewBox="0 0 24 24" className="size-5 text-slate-950" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="7" />
          <path d="M12 9v6" />
          <path d="M9 12h6" />
        </svg>
      </div>
      <div className="leading-tight">
        <div className="text-sm font-extrabold tracking-[0.2em] text-white font-mono flex items-center gap-1.5">
          AFTERIMAGE
          <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
        </div>
        <div className="text-[10px] text-slate-400 font-mono tracking-wider">AI AGENT FORENSICS</div>
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
  const label = status === "ok" ? "GATEWAY ONLINE" : status === "down" ? "GATEWAY OFFLINE" : "CONNECTING";
  return (
    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.03] border border-white/[0.06] text-[11px] font-mono tracking-wider text-slate-300">
      <span className={cx("size-2 rounded-full", status === "ok" ? "bg-emerald-400 shadow-xs shadow-emerald-400" : status === "down" ? "bg-rose-400" : "bg-amber-400 animate-ping")} aria-hidden />
      <span>{label}</span>
    </div>
  );
}

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => cx(
        "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold tracking-wide transition-all duration-150 group",
        isActive 
          ? "bg-gradient-to-r from-emerald-500/15 to-teal-500/5 text-emerald-300 border border-emerald-500/30 shadow-xs" 
          : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.03] border border-transparent",
      )}
    >
      <Icon className="size-4 shrink-0 transition-transform duration-150 group-hover:scale-110" aria-hidden />
      <span>{label}</span>
    </NavLink>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const current = NAV.find((n) => ("end" in n && n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)));

  const navContent = (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV_PHASES.map(({ phase, items }) => (
        <div key={phase} className="mb-2">
          <div className="mb-1.5 px-3 text-[10px] font-mono font-bold tracking-widest text-slate-500 uppercase">
            {phase}
          </div>
          <div className="space-y-0.5">
            {items.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </div>
        </div>
      ))}
      <div className="mt-4 border-t border-white/[0.06] pt-3">
        <NavItem {...NAV_SETTINGS} />
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[260px_1fr] bg-[#05070c]">
      {/* Desktop sidebar */}
      <aside className="hidden border-r border-white/[0.06] bg-[#070b12]/80 backdrop-blur-xl lg:block z-40">
        <div className="sticky top-0 flex h-screen flex-col p-5">
          <div className="pb-6 border-b border-white/[0.06]"><Logo /></div>
          <div className="mt-5 flex-1 overflow-y-auto scroll-thin pr-1">{navContent}</div>
          
          <div className="mt-4 rounded-xl p-3.5 bg-gradient-to-b from-white/[0.03] to-transparent border border-white/[0.06]">
            <div className="flex items-center gap-2 text-[11px] font-mono font-bold text-teal-400">
              <Radio className="size-3 animate-pulse" />
              <span>ACTIVE ENFORCEMENT</span>
            </div>
            <p className="mt-1 text-[10px] text-slate-400 leading-relaxed font-mono">
              Server-side boundary denies unauthorized tool requests before execution.
            </p>
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-80 border-r border-white/10 bg-[#070b12] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between pb-4 border-b border-white/[0.08]">
              <Logo />
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="text-slate-400 hover:text-white p-1">
                <X className="size-5" />
              </button>
            </div>
            {navContent}
          </div>
        </div>
      )}

      {/* Main Content Arena */}
      <div className="min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-white/[0.06] bg-[#05070c]/80 backdrop-blur-xl px-6 sm:px-8">
          <div className="flex items-center gap-3.5">
            <button aria-label="Open navigation" className="text-slate-400 hover:text-white lg:hidden p-1" onClick={() => setOpen(true)}>
              <Menu className="size-5" />
            </button>
            <span className="text-xs font-mono font-semibold text-slate-400 tracking-wider">AFTERIMAGE</span>
            <span className="text-slate-600 font-mono">/</span>
            <span className="text-xs font-mono font-bold text-slate-200 uppercase tracking-widest">{current?.label ?? "Overview"}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/[0.08] border border-emerald-500/20 text-[10px] font-mono font-semibold text-emerald-400 tracking-wider">
              <Sparkles className="size-3" /> SYNTHETIC SANDBOX
            </span>
            <BackendStatus />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1500px] px-6 py-8 sm:px-8 lg:py-10 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
