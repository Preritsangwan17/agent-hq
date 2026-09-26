/**
 * Live Agent Network: a static React Flow graph (no pan/zoom/drag; page scroll passes through) laid out in
 * pipeline order with the Strategist hub. The viewport is computed to fit the container ("fit view") and the
 * layout switches to a vertical column when the panel is narrow. `task.handoff` events from `handoffBus` fire
 * particles in the source agent's colour; global pause freezes particles and greys the graph.
 */
import '@xyflow/react/dist/base.css';
import { ReactFlow, type EdgeTypes, type NodeTypes, type Viewport } from '@xyflow/react';
import { useReducedMotion } from 'motion/react';
import { Network, Pause } from 'lucide-react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { EmptyState, GlassPanel, SectionHeader, StatusDot } from '@/components';
import { handoffBus } from '@/lib/bus';
import { cn } from '@/lib/cn';
import { useNow } from '@/lib/hooks';
import { useHQ, useIsPaused } from '@/lib/store';
import { agentColor } from '@/theme/tokens';
import { AgentNode } from './AgentNode';
import { buildLayout, type NetworkLayout } from './layout';
import { EngineContext, ParticleEdge } from './ParticleEdge';
import { ParticleEngine } from './particles';

const nodeTypes: NodeTypes = { agent: AgentNode };
const edgeTypes: EdgeTypes = { particle: ParticleEdge };

/** container width at which the horizontal row layout is used */
const ROW_MIN_WIDTH = 760;
const PAD = { row: { x: 12, y: 18 }, column: { x: 8, y: 14 } } as const;
const MAX_ZOOM = { row: 1.08, column: 1.05 } as const;

function useContainerWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function useHandoffRate(windowMs = 5 * 60_000): number {
  const now = useNow(5000);
  const events = useHQ((s) => s.events);
  return useMemo(() => {
    const since = now - windowMs;
    let n = 0;
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      const t = Date.parse(e.ts);
      if (t < since) break;
      if (e.type === 'task.handoff') n++;
    }
    return n;
  }, [events, now, windowMs]);
}

export function AgentNetwork({ className }: { className?: string }) {
  const navigate = useNavigate();
  const paused = useIsPaused();
  const reduce = useReducedMotion() ?? false;
  const agentIds = useHQ((s) => s.agentOrder);
  const agentsById = useHQ((s) => s.agents);
  const idsKey = agentIds.join('|');
  const colorsKey = agentIds.map((id) => agentsById[id]?.color ?? '').join('|');
  const working = useHQ((s) => Object.values(s.agents).filter((a) => a.status === 'working').length);
  const handoffs = useHandoffRate();
  const [wrapRef, width] = useContainerWidth<HTMLDivElement>();
  const mode: NetworkLayout = width >= ROW_MIN_WIDTH ? 'row' : 'column';

  const built = useMemo(() => {
    const agents = useHQ.getState().agents;
    const ids = idsKey ? idsKey.split('|') : [];
    return buildLayout(mode, ids, (id) => agents[id]?.color ?? agentColor(id));
    // colorsKey: rebuild when an agent's colour changes
  }, [mode, idsKey, colorsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const engine = useMemo(() => new ParticleEngine(), []);
  useEffect(() => () => engine.dispose(), [engine]);
  useEffect(() => engine.setTopology({ order: built.order, hub: built.hub }), [engine, built]);
  useEffect(() => engine.setReducedMotion(reduce), [engine, reduce]);
  useEffect(() => engine.setPaused(paused), [engine, paused]);
  useEffect(
    () =>
      handoffBus.on((h) => {
        const color = useHQ.getState().agents[h.from_agent]?.color ?? agentColor(h.from_agent);
        engine.handoff(h.from_agent, h.to_agent, color);
      }),
    [engine],
  );

  const { viewport, height } = useMemo(() => {
    const pad = PAD[mode];
    const b = built.bounds;
    const avail = Math.max(1, width - pad.x * 2);
    const zoom = Math.min(MAX_ZOOM[mode], avail / b.w);
    const vp: Viewport = {
      x: Math.round((width - b.w * zoom) / 2 - b.x * zoom),
      y: Math.round(pad.y - b.y * zoom),
      zoom,
    };
    return { viewport: vp, height: Math.ceil(b.h * zoom + pad.y * 2) };
  }, [built, width, mode]);

  return (
    <GlassPanel as="section" padding="none" glow="#22D3EE" glowStrength={0.22} className={cn('overflow-hidden', className)}>
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 px-4 pt-4 md:px-6 md:pt-5">
        <SectionHeader kicker="Live" title="Agent network" icon={Network} color="#22D3EE" />
        <div className="flex items-center gap-3 text-[11.5px] text-muted tabular">
          {paused ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/25 bg-amber-300/10 px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.14em] text-amber-200">
              <Pause className="size-3" fill="currentColor" aria-hidden /> Frozen
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5">
              <StatusDot color="#34D399" pulse={working > 0} size={7} />
              <span>
                <span className="font-medium text-ink">{working}</span> working
              </span>
            </span>
          )}
          <span className="h-3.5 w-px bg-white/10" aria-hidden />
          <span>
            <span className="font-medium text-ink">{handoffs}</span> handoffs · 5 min
          </span>
        </div>
      </div>

      <div ref={wrapRef} className="relative mx-2 mb-2 mt-1 md:mx-3 md:mb-3">
        {built.nodes.length === 0 ? (
          <EmptyState compact title="No agents yet" hint="Agents appear here as soon as the worker registers them." />
        ) : width > 0 ? (
          <div
            className="cc-network relative"
            data-paused={paused ? 'true' : 'false'}
            data-layout={mode}
            style={{ height }}
            aria-label="Agent network graph"
            role="img"
          >
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  mode === 'row'
                    ? 'radial-gradient(60% 70% at 50% 8%, rgba(232,121,249,0.07), transparent 70%), radial-gradient(80% 60% at 50% 100%, rgba(34,211,238,0.05), transparent 70%)'
                    : 'radial-gradient(90% 40% at 30% 0%, rgba(232,121,249,0.07), transparent 70%)',
              }}
            />
            <EngineContext.Provider value={engine}>
              <ReactFlow
                key={mode}
                nodes={built.nodes}
                edges={built.edges}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                viewport={viewport}
                minZoom={0.1}
                maxZoom={2}
                nodesDraggable={false}
                nodesConnectable={false}
                nodesFocusable={false}
                edgesFocusable={false}
                elementsSelectable={false}
                panOnDrag={false}
                panOnScroll={false}
                zoomOnScroll={false}
                zoomOnPinch={false}
                zoomOnDoubleClick={false}
                preventScrolling={false}
                colorMode="dark"
                proOptions={{ hideAttribution: true }}
                onNodeClick={() => navigate('/agents')}
                style={{ background: 'transparent' }}
              />
            </EngineContext.Provider>
            {paused && (
              <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
                <span className="rounded-full border border-white/10 bg-[#0B111D]/85 px-3 py-1 text-[11px] text-muted backdrop-blur">
                  Network frozen — all agents paused
                </span>
              </div>
            )}
          </div>
        ) : (
          <div style={{ height: 320 }} />
        )}
      </div>
    </GlassPanel>
  );
}
