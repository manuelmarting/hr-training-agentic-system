// Hand-rolled SVG layered DAG (plan §6). No graph library: 25 nodes and one predicate
// (prerequisite_of) are far better served by a topological left→right layering than by a
// force-directed blob. Prerequisites always sit to the left of what depends on them, so
// edge direction is visually unambiguous.

import { useMemo } from "react";
import type { Domain, ProposedEdge, ProposedKC } from "./api";

const BOX_W = 158;
const BOX_H = 56;
const COL_W = 224;
const ROW_H = 82;
const MARGIN = 32;

// Tuned for the light gray canvas — distinct, readable on #eceef0.
const DOMAIN_COLORS: Record<Domain, string> = {
  safety: "#e11d48",
  equipment: "#d97706",
  process: "#2563eb",
  systems: "#7c3aed",
  behavioural: "#16a34a",
};

type Placed = { kc: ProposedKC; x: number; y: number };

/** Longest-prerequisite-chain layering. Cycle back-edges contribute 0 so a graph that is
 *  temporarily invalid during editing still lays out instead of recursing forever. */
function computeLayers(kcs: ProposedKC[], edges: ProposedEdge[]): Map<string, number> {
  const prereqs = new Map<string, string[]>();
  const ids = new Set(kcs.map((k) => k.id));
  for (const e of edges) {
    if (ids.has(e.source_kc_id) && ids.has(e.target_kc_id)) {
      prereqs.set(e.target_kc_id, [...(prereqs.get(e.target_kc_id) ?? []), e.source_kc_id]);
    }
  }
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const resolve = (id: string): number => {
    if (layer.has(id)) return layer.get(id)!;
    if (visiting.has(id)) return 0; // cycle guard
    visiting.add(id);
    const parents = prereqs.get(id) ?? [];
    const value = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(resolve));
    visiting.delete(id);
    layer.set(id, value);
    return value;
  };
  for (const kc of kcs) resolve(kc.id);
  return layer;
}

function layout(kcs: ProposedKC[], edges: ProposedEdge[]): {
  placed: Placed[];
  width: number;
  height: number;
} {
  const layer = computeLayers(kcs, edges);
  const byLayer = new Map<number, ProposedKC[]>();
  for (const kc of [...kcs].sort((a, b) => a.id.localeCompare(b.id))) {
    const l = layer.get(kc.id) ?? 0;
    byLayer.set(l, [...(byLayer.get(l) ?? []), kc]);
  }
  const placed: Placed[] = [];
  let maxRows = 0;
  let maxLayer = 0;
  for (const [l, group] of byLayer) {
    maxLayer = Math.max(maxLayer, l);
    maxRows = Math.max(maxRows, group.length);
    group.forEach((kc, row) => {
      placed.push({ kc, x: MARGIN + l * COL_W, y: MARGIN + row * ROW_H });
    });
  }
  return {
    placed,
    width: MARGIN * 2 + (maxLayer + 1) * COL_W,
    height: MARGIN * 2 + Math.max(maxRows, 1) * ROW_H,
  };
}

type Props = {
  kcs: ProposedKC[];
  edges: ProposedEdge[];
  selectedId: string | null;
  highlightIds: Set<string>;
  onSelect: (kcId: string) => void;
};

export default function GraphCanvas({
  kcs,
  edges,
  selectedId,
  highlightIds,
  onSelect,
}: Props) {
  const { placed, width, height } = useMemo(() => layout(kcs, edges), [kcs, edges]);
  const pos = useMemo(() => {
    const m = new Map<string, Placed>();
    for (const p of placed) m.set(p.kc.id, p);
    return m;
  }, [placed]);

  if (kcs.length === 0) {
    return <div className="studio-empty">No KCs yet — add one, or seed from the graph.</div>;
  }

  return (
    <div className="graph-canvas">
      <svg width={width} height={height} role="img" aria-label="Knowledge graph">
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--graph-edge, #94a3b8)" />
          </marker>
        </defs>

        {edges.map((e) => {
          const s = pos.get(e.source_kc_id);
          const t = pos.get(e.target_kc_id);
          if (!s || !t) return null;
          const x1 = s.x + BOX_W;
          const y1 = s.y + BOX_H / 2;
          const x2 = t.x;
          const y2 = t.y + BOX_H / 2;
          const mx = (x1 + x2) / 2;
          return (
            <path
              key={`${e.source_kc_id}->${e.target_kc_id}`}
              d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke="var(--graph-edge, #94a3b8)"
              strokeWidth={1.5}
              markerEnd="url(#arrow)"
            />
          );
        })}

        {placed.map(({ kc, x, y }) => {
          const color = DOMAIN_COLORS[kc.domain];
          const selected = kc.id === selectedId;
          const highlighted = highlightIds.has(kc.id);
          return (
            <g
              key={kc.id}
              transform={`translate(${x}, ${y})`}
              className="graph-node"
              onClick={() => onSelect(kc.id)}
              style={{ cursor: "pointer" }}
            >
              <rect
                width={BOX_W}
                height={BOX_H}
                rx={8}
                fill="var(--graph-node-bg)"
                stroke={
                  highlighted
                    ? "var(--danger)"
                    : selected
                      ? "var(--accent)"
                      : color
                }
                strokeWidth={selected || highlighted ? 3 : 1.5}
              />
              <rect width={6} height={BOX_H} rx={3} fill={color} />
              <text x={16} y={22} className="graph-node__id" fontSize={12} fontWeight={700}>
                {kc.id}
              </text>
              <text x={16} y={40} className="graph-node__name" fontSize={11}>
                {kc.name.length > 24 ? `${kc.name.slice(0, 23)}…` : kc.name}
              </text>
              {kc.origin !== "extracted" && (
                <circle cx={BOX_W - 12} cy={12} r={5} fill="var(--accent)">
                  <title>human-edited ({kc.origin})</title>
                </circle>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
