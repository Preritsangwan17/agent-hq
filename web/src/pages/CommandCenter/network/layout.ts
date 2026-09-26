/**
 * Fixed layouts for the agent network (pipeline order, Strategist as a hub connected to every agent).
 *  • `row`: agents on a shallow arc left → right, the hub above the middle, fan edges into each orb.
 *  • `column`: compact pills top → bottom (a "metro line" through the orbs), hub arcs on the right.
 * Node geometry here must match the CSS sizes in AgentNode.tsx.
 */
import type { Edge, Node } from '@xyflow/react';

export type NetworkLayout = 'row' | 'column';
export type NodeVariant = 'orb' | 'pill' | 'hub' | 'hubPill';

export interface AgentNodeData extends Record<string, unknown> {
  agentId: string;
  variant: NodeVariant;
}

export interface ParticleEdgeData extends Record<string, unknown> {
  kind: 'pipe' | 'hub';
  shape: 'bezier' | 'arc';
  sourceColor: string;
  targetColor: string;
}

export type AgentFlowNode = Node<AgentNodeData, 'agent'>;
export type ParticleFlowEdge = Edge<ParticleEdgeData, 'particle'>;

/** Pipeline order (CONTRACT §6 starting team); user-created agents are appended after these. */
export const PIPELINE_ORDER = [
  'scout',
  'verifier',
  'writer',
  'factchecker',
  'reviewer',
  'resume',
  'applicant',
  'inbox',
  'followup',
] as const;
export const HUB_ID = 'strategist';

/** node geometry (flow units) */
export const GEOM = {
  orb: { w: 116, h: 112, orb: 54 },
  hub: { w: 232, h: 64, orb: 62 },
  pill: { w: 200, h: 42, orb: 30 },
  hubPill: { w: 200, h: 50, orb: 38 },
  rowDx: 128,
  rowArc: 54,
  rowTop: 150,
  colRow: 58,
  colTop: 92,
} as const;

export interface Bounds {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BuiltLayout {
  nodes: AgentFlowNode[];
  edges: ParticleFlowEdge[];
  bounds: Bounds;
  order: string[];
  hub: string | null;
}

/** Arc bulge for column hub edges (must match ParticleEdge's arc path). */
export function arcBulge(dy: number): number {
  return 22 + Math.abs(dy) * 0.15;
}

export function buildLayout(
  layout: NetworkLayout,
  agentIds: string[],
  colorOf: (id: string) => string,
): BuiltLayout {
  const known = new Set(agentIds);
  const order = [
    ...PIPELINE_ORDER.filter((id) => known.has(id)),
    ...agentIds.filter((id) => id !== HUB_ID && !(PIPELINE_ORDER as readonly string[]).includes(id)),
  ];
  const hub = known.has(HUB_ID) ? HUB_ID : null;
  const nodes: AgentFlowNode[] = [];
  const edges: ParticleFlowEdge[] = [];
  const common = { draggable: false, selectable: false, connectable: false, focusable: false } as const;

  const edge = (kind: 'pipe' | 'hub', s: string, t: string, sh: string, th: string, shape: 'bezier' | 'arc') => {
    edges.push({
      id: `${kind}:${s}>${t}`,
      source: s,
      target: t,
      sourceHandle: sh,
      targetHandle: th,
      type: 'particle',
      selectable: false,
      focusable: false,
      data: { kind, shape, sourceColor: colorOf(s), targetColor: colorOf(t) },
      zIndex: kind === 'hub' ? 0 : 1,
    });
  };

  if (layout === 'row') {
    const n = order.length;
    const mid = (n - 1) / 2;
    order.forEach((id, i) => {
      const norm = mid > 0 ? (i - mid) / mid : 0;
      nodes.push({
        id,
        type: 'agent',
        position: { x: i * GEOM.rowDx, y: GEOM.rowTop + GEOM.rowArc * (1 - norm * norm) },
        data: { agentId: id, variant: 'orb' },
        ...common,
      });
    });
    const rowW = Math.max(GEOM.orb.w, (n - 1) * GEOM.rowDx + GEOM.orb.w);
    if (hub) {
      const cx = rowW / 2;
      nodes.push({
        id: hub,
        type: 'agent',
        position: { x: cx - GEOM.hub.orb / 2, y: 0 },
        data: { agentId: hub, variant: 'hub' },
        ...common,
      });
    }
    for (let i = 0; i < n - 1; i++) edge('pipe', order[i], order[i + 1], 'r', 'l', 'bezier');
    if (hub) for (const id of order) edge('hub', hub, id, 'b', 't', 'bezier');
    const bottom = GEOM.rowTop + GEOM.rowArc + GEOM.orb.h;
    const hubRight = hub ? rowW / 2 - GEOM.hub.orb / 2 + GEOM.hub.w : 0;
    return {
      nodes,
      edges,
      bounds: { x: -14, y: -12, w: Math.max(rowW, hubRight) + 28, h: bottom + 20 },
      order,
      hub,
    };
  }

  // column
  const top = hub ? GEOM.colTop : 0;
  order.forEach((id, i) => {
    nodes.push({
      id,
      type: 'agent',
      position: { x: 0, y: top + i * GEOM.colRow },
      data: { agentId: id, variant: 'pill' },
      ...common,
    });
  });
  if (hub) {
    nodes.push({
      id: hub,
      type: 'agent',
      position: { x: 0, y: 0 },
      data: { agentId: hub, variant: 'hubPill' },
      ...common,
    });
  }
  for (let i = 0; i < order.length - 1; i++) edge('pipe', order[i], order[i + 1], 'b', 't', 'bezier');
  if (hub) for (const id of order) edge('hub', hub, id, 'r', 'rt', 'arc');
  const lastY = top + Math.max(0, order.length - 1) * GEOM.colRow;
  const maxDy = lastY + GEOM.pill.h / 2 - GEOM.hubPill.h / 2;
  const bulge = hub ? arcBulge(maxDy) * 0.78 : 0;
  return {
    nodes,
    edges,
    bounds: { x: -10, y: -10, w: GEOM.pill.w + bulge + 22, h: lastY + GEOM.pill.h + 20 },
    order,
    hub,
  };
}
