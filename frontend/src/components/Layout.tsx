import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity, Archive, FlaskConical, LayoutDashboard, ListTree, Menu, Network, Settings, Shield, ShieldAlert, Syringe, X,
} from "lucide-react";
import { api } from "../api";
import { cx } from "./ui";

/** Navigation items organised by workflow phase. */
const NAV_PHASES = [
  {
    phase: "Observe",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
    ],
  },
  {
    phase: "Enforce",
    items: [
      { to: "/incidents", label: "Incidents", icon: ShieldAlert },
      { to: "/investigation", label: "Investigation", icon: Network },
    ],
  },
  {
    phase: "Remediate",
    items: [
      { to: "/policies", label: "Policies", icon: Shield },
    ],
  },
  {
    phase: "Replay",
    items: [
      { to: "/replay", label: "Replay Lab", icon: FlaskConical },
      { to: "/experiment", label: "Injection Lab", icon: Syringe },
    ],
  },
  {
    phase: "Verify",
    items: [
      { to: "/recovery", label: "Recovery Vault", icon: Archive },
      { to: "/events", label: "Event Explorer", icon: ListTree },
    ],
  },
];

const NAV_SETTINGS = { to: "/settings", label: "Settings", icon: Settings };

// Flat list for breadcrumb lookups
const NAV = NAV_PHASES.flatMap((p) => p.items).concat(NAV_SETTINGS);

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden>
        <circle cx="14" cy="16" r="8" fill="none" stroke="#2dd4b0" strokeWidth="2.5" />
        <circle cx="18" cy="16" r="8" fill="none" stroke="#2dd4b0" strokeOpacity=".3" strokeWidth="2.5" />
      </svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-[0.18em] text-ink-100">AFTERIMAGE</div>
        <div className="text-[10px] text-ink-500">Agent incident forensics</div>
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
    <span className="inline-flex items-center gap-2 text-xs text-ink-400" title="Polls GET /api/health every 15 s">
      <span className={cx("size-2 rounded-full", status === "ok" ? "bg-emerald-400" : status === "down" ? "bg-rose-400" : "bg-ink-500")} aria-hidden />
      {label}
    </span>
  );
}

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => cx(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        isActive ? "bg-accent-500/10 text-accent-300 font-medium" : "text-ink-400 hover:bg-ink-800/60 hover:text-ink-200",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {label}
    </NavLink>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const current = NAV.find((n) => ("end" in n && n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)));

  const navContent = (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV_PHASES.map(({ phase, items }) => (
        <div key={phase}>
          <div className="mb-1 mt-4 first:mt-0 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-ink-500">
            {phase}
          </div>
          {items.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </div>
      ))}
      <div className="mt-auto border-t border-ink-800/60 pt-2">
        <NavItem {...NAV_SETTINGS} />
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
      {/* Desktop sidebar */}
      <aside className="hidden border-r border-ink-800/60 bg-ink-900/40 lg:block">
        <div className="sticky top-0 flex h-screen flex-col px-3 py-5">
          <div className="px-2"><Logo /></div>
          <div className="mt-6 flex-1 overflow-y-auto scroll-thin">{navContent}</div>
          <div className="rounded-lg border border-ink-800/50 bg-ink-900/60 px-3 py-2.5 text-[10px] leading-relaxed text-ink-500">
            <Activity className="mb-1 size-3.5 text-accent-500" aria-hidden />
            Observe → Enforce → Investigate → Remediate → Replay → Verify
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-72 border-r border-ink-700 bg-ink-900 px-3 py-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between px-2">
              <Logo />
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="text-ink-400 hover:text-ink-200">
                <X className="size-5" />
              </button>
            </div>
            {navContent}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-ink-800/50 bg-ink-950/95 px-4 backdrop-blur-lg sm:px-6">
          <div className="flex items-center gap-3">
            <button aria-label="Open navigation" className="text-ink-400 hover:text-ink-200 lg:hidden" onClick={() => setOpen(true)}>
              <Menu className="size-5" />
            </button>
            <span className="text-sm text-ink-500 font-medium">AFTERIMAGE</span>
            <span className="text-ink-700">/</span>
            <span className="text-sm font-medium text-ink-100">{current?.label ?? "Overview"}</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden rounded-md border border-ink-800/60 bg-ink-900/40 px-2.5 py-1 text-[10px] font-medium tracking-wide text-ink-500 sm:inline">
              SYNTHETIC DEMO
            </span>
            <BackendStatus />
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
