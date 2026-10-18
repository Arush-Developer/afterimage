import { useMemo } from "react";
import type { IncidentGraph } from "../api";
import { formatClock } from "../format";
import { categoryMeta } from "./ui";

const NODE_W = 184;
const NODE_H = 66;
const COL_GAP = 40;
const ROW_GAP = 26;
const PAD = 16;

// Dash patterns make categories distinguishable without relying on colour.
const DASH: Record<string, string | undefined> = { denied: "6 4", suspicious: "2 3", allowed: undefined, info: undefined };

/** SVG rendering of an evidence graph. Layout positions (column/row) come from the backend,
 *  which derives them from NetworkX topological generations of the persisted event links. */
export function EventGraph({ graph, selectedId, onSelect }: {
  graph: IncidentGraph; selectedId?: string; onSelect: (id: string) => void;
}) {
  const layout = useMemo(() => {
    const pos = new Map<string, { x: number; y: number }>();
    graph.nodes.forEach((n) => pos.set(n.id, { x: PAD + n.column * (NODE_W + COL_GAP), y: PAD + n.row * (NODE_H + ROW_GAP) }));
    const cols = Math.max(0, ...graph.nodes.map((n) => n.column)) + 1;
    const rows = Math.max(0, ...graph.nodes.map((n) => n.row)) + 1;
    return { pos, width: PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP, height: PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP };
  }, [graph]);

  return (
    <div className="scroll-thin overflow-x-auto rounded-lg border border-ink-800 bg-ink-950/60">
      <svg width={layout.width} height={layout.height} role="group" aria-label="Evidence graph of recorded events" className="block">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#4a5562" />
          </marker>
        </defs>
        {graph.edges.map((e) => {
          const a = layout.pos.get(e.source);
          const b = layout.pos.get(e.target);
          if (!a || !b) return null;
          const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x - 2, y2 = b.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          return (
            <g key={`${e.source}-${e.target}`}>
              <path d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none" stroke="#3a434e" strokeWidth={1.5} markerEnd="url(#arrow)">
                <title>{e.relation}</title>
              </path>
            </g>
          );
        })}
        {graph.nodes.map((n) => {
          const p = layout.pos.get(n.id)!;
          const meta = categoryMeta[n.category];
          const selected = n.id === selectedId;
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${meta.label}: ${n.label} at ${formatClock(n.timestamp)}`}
              onClick={() => onSelect(n.id)}
              onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && (ev.preventDefault(), onSelect(n.id))}
              className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-white"
            >
              <rect width={NODE_W} height={NODE_H} rx={10} fill={selected ? "#1d242c" : "#14181d"} stroke={selected ? "#e6eaee" : meta.ring}
                strokeWidth={selected ? 2 : 1.4} strokeDasharray={DASH[n.category]} />
              <rect x={0} y={0} width={4} height={NODE_H} rx={2} fill={meta.ring} />
              <text x={14} y={20} fontSize={10.5} fontWeight={600} fill={meta.ring} letterSpacing={0.6}>
                {meta.label.toUpperCase()} · {n.event_type.replace(/_/g, " ")}
              </text>
              <text x={14} y={39} fontSize={12.5} fill="#e6eaee">{truncate(n.label, 25)}</text>
              <text x={14} y={56} fontSize={10.5} fill="#7c8794" fontFamily="var(--font-mono)">{formatClock(n.timestamp)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function GraphLegend() {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-ink-400">
      {(Object.keys(categoryMeta) as (keyof typeof categoryMeta)[]).map((k) => {
        const m = categoryMeta[k];
        const Icon = m.icon;
        return (
          <span key={k} className="inline-flex items-center gap-1.5">
            <svg width="22" height="10" aria-hidden><rect x="1" y="1" width="20" height="8" rx="2" fill="none" stroke={m.ring} strokeDasharray={DASH[k]} /></svg>
            <Icon className={`size-3.5 ${m.text}`} aria-hidden /> {m.label}
          </span>
        );
      })}
    </div>
  );
}
