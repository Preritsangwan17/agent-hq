/**
 * Custom React Flow node for the agent network. Reads its agent + live line from the store so the node array
 * stays stable. States: working (breathing glow + orbiting arc in the agent colour), idle (dim), error/stuck
 * (red ring + shake; a failed task flashes the same once), paused (grey + pause glyph). Arriving particles
 * fire a ring burst in the particle's colour.
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Pause } from 'lucide-react';
import { memo, useEffect, useRef, useState, type CSSProperties } from 'react';
import { cn } from '@/lib/cn';
import { eventBus } from '@/lib/bus';
import { useAgent, useAgentLive, useIsPaused } from '@/lib/store';
import { agentColor } from '@/theme/tokens';
import { modelLabel, shortName, stateLabel, STATE_META, visualState, type VisualState } from '../util';
import { GEOM, type AgentFlowNode, type NodeVariant } from './layout';
import { arrivals } from './particles';

interface Burst {
  key: number;
  color: string;
}

function useArrivalBursts(agentId: string): Burst[] {
  const [bursts, setBursts] = useState<Burst[]>([]);
  const seq = useRef(0);
  useEffect(() => {
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const off = arrivals.on(({ agentId: to, color }) => {
      if (to !== agentId) return;
      const key = ++seq.current;
      setBursts((b) => [...b.slice(-2), { key, color }]);
      const t = setTimeout(() => {
        timers.delete(t);
        setBursts((b) => b.filter((x) => x.key !== key));
      }, 800);
      timers.add(t);
    });
    return () => {
      off();
      for (const t of timers) clearTimeout(t);
    };
  }, [agentId]);
  return bursts;
}

function useFailureFlash(agentId: string): boolean {
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = eventBus.on((e) => {
      if ((e.type === 'task.failed' || e.type === 'task.dead') && e.agent_id === agentId) {
        setFlash(true);
        clearTimeout(t);
        t = setTimeout(() => setFlash(false), 1500);
      }
    });
    return () => {
      off();
      clearTimeout(t);
    };
  }, [agentId]);
  return flash;
}

const HANDLES: Record<NodeVariant, { id: string; type: 'source' | 'target'; pos: Position; on: 'orb' | 'box' }[]> = {
  orb: [
    { id: 'l', type: 'target', pos: Position.Left, on: 'orb' },
    { id: 'r', type: 'source', pos: Position.Right, on: 'orb' },
    { id: 't', type: 'target', pos: Position.Top, on: 'orb' },
  ],
  hub: [{ id: 'b', type: 'source', pos: Position.Bottom, on: 'orb' }],
  pill: [
    { id: 't', type: 'target', pos: Position.Top, on: 'orb' },
    { id: 'b', type: 'source', pos: Position.Bottom, on: 'orb' },
    { id: 'rt', type: 'target', pos: Position.Right, on: 'box' },
  ],
  hubPill: [{ id: 'r', type: 'source', pos: Position.Right, on: 'box' }],
};

function Handles({ variant, on }: { variant: NodeVariant; on: 'orb' | 'box' }) {
  return (
    <>
      {HANDLES[variant]
        .filter((h) => h.on === on)
        .map((h) => (
          <Handle key={h.id} id={h.id} type={h.type} position={h.pos} isConnectable={false} />
        ))}
    </>
  );
}

interface OrbProps {
  size: number;
  avatar: string;
  state: VisualState;
  flash: boolean;
  bursts: Burst[];
  variant: NodeVariant;
}

function Orb({ size, avatar, state, flash, bursts, variant }: OrbProps) {
  const glyph = Math.round(size * 0.46);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div className="cc-shaker absolute inset-0">
        {state === 'working' && (
          <>
            <span className="cc-breath" aria-hidden />
            <span className="cc-spin" aria-hidden />
          </>
        )}
        {(state === 'error' || flash) && state !== 'paused' && <span className="cc-err-ring" aria-hidden />}
        {bursts.map((b) => (
          <span key={b.key} className="cc-burst" style={{ '--burst': b.color } as CSSProperties} aria-hidden />
        ))}
        <span className="cc-orb">
          <span className="cc-orb-glyph" style={{ fontSize: glyph }} aria-hidden>
            {avatar}
          </span>
        </span>
        {state === 'paused' && (
          <span
            className="absolute -bottom-0.5 -right-0.5 grid place-items-center rounded-full border border-white/15 bg-[#1a2030]"
            style={{ width: Math.max(14, size * 0.36), height: Math.max(14, size * 0.36) }}
            aria-hidden
          >
            <Pause className="text-muted" style={{ width: size * 0.2, height: size * 0.2 }} fill="currentColor" />
          </span>
        )}
      </div>
      <Handles variant={variant} on="orb" />
    </div>
  );
}

function StatusChip({ state, label, tokS }: { state: VisualState; label: string; tokS: number | null }) {
  const c = STATE_META[state].color;
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[9.5px] font-medium uppercase tracking-[0.08em] tabular" style={{ color: c }}>
      <span className="size-1.5 rounded-full" style={{ backgroundColor: c, boxShadow: `0 0 6px ${c}` }} />
      {state === 'working' && tokS ? `${tokS} tok/s` : label}
    </span>
  );
}

function AgentNodeImpl({ data }: NodeProps<AgentFlowNode>) {
  const { agentId, variant } = data;
  const agent = useAgent(agentId);
  const live = useAgentLive(agentId);
  const globalPause = useIsPaused();
  const bursts = useArrivalBursts(agentId);
  const failFlash = useFailureFlash(agentId);
  const state = visualState(agent, globalPause);
  const flash = failFlash && state !== 'paused';
  const color = agent?.color ?? agentColor(agentId);
  const name = shortName(agent?.name ?? agentId);
  const model = modelLabel(live?.model_id ?? agent?.model);
  const label = stateLabel(agent, state);
  const tokS = state === 'working' ? (live?.tok_s ?? null) : null;
  const avatar = agent?.avatar ?? '🤖';
  const common = {
    className: cn('cc-node', variant === 'orb' && 'flex flex-col items-center'),
    'data-state': state,
    'data-flash': flash ? 'true' : 'false',
    title: `${agent?.name ?? agentId} — ${label}`,
  };

  if (variant === 'orb') {
    const g = GEOM.orb;
    return (
      <div {...common} style={{ '--c': color, width: g.w, height: g.h } as CSSProperties}>
        <Orb size={g.orb} avatar={avatar} state={state} flash={flash} bursts={bursts} variant={variant} />
        <div className="cc-label mt-2 flex w-full min-w-0 flex-col items-center leading-tight transition-opacity duration-300">
          <span className="max-w-full truncate font-display text-[12.5px] font-semibold tracking-tight text-ink">{name}</span>
          <span className="mt-0.5 max-w-full truncate font-mono text-[9.5px] text-faint">{model}</span>
          <span className="mt-1">
            <StatusChip state={state} label={label} tokS={tokS} />
          </span>
        </div>
      </div>
    );
  }

  if (variant === 'hub') {
    const g = GEOM.hub;
    return (
      <div {...common} className={cn(common.className, 'flex items-center gap-3')} style={{ '--c': color, width: g.w, height: g.h } as CSSProperties}>
        <Orb size={g.orb} avatar={avatar} state={state} flash={flash} bursts={bursts} variant={variant} />
        <div className="cc-label min-w-0 leading-tight transition-opacity duration-300">
          <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-faint">Hub · reviews all</div>
          <div className="truncate font-display text-[14px] font-semibold tracking-tight text-ink">{name}</div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="truncate font-mono text-[9.5px] text-faint">{model}</span>
            <StatusChip state={state} label={label} tokS={tokS} />
          </div>
        </div>
      </div>
    );
  }

  const g = variant === 'hubPill' ? GEOM.hubPill : GEOM.pill;
  return (
    <div
      {...common}
      className={cn(common.className, 'relative flex items-center gap-2.5 rounded-full border border-white/[.08] bg-[#0B111D]/80 pl-1.5 pr-3')}
      style={{ '--c': color, width: g.w, height: g.h } as CSSProperties}
    >
      <Orb size={g.orb} avatar={avatar} state={state} flash={flash} bursts={bursts} variant={variant} />
      <div className="cc-label min-w-0 flex-1 leading-tight transition-opacity duration-300">
        <div className="flex items-baseline gap-1.5">
          <span className="truncate font-display text-[12.5px] font-semibold tracking-tight text-ink">{name}</span>
          {variant === 'hubPill' && <span className="shrink-0 font-mono text-[8.5px] uppercase tracking-[0.16em] text-faint">hub</span>}
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
          <StatusChip state={state} label={label} tokS={tokS} />
          <span className="truncate font-mono text-[9px] text-faint">· {model}</span>
        </div>
      </div>
      <Handles variant={variant} on="box" />
    </div>
  );
}

export const AgentNode = memo(AgentNodeImpl);
