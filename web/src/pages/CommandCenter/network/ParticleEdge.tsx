/**
 * Custom React Flow edge: a faint gradient conduit (source → target colour; the Strategist's hub links are
 * dashed), a glow overlay the particle engine lights while a particle is on it, and a particle layer. The
 * edge registers its path geometry with the ParticleEngine from context; particles are appended imperatively.
 */
import { getBezierPath, type EdgeProps } from '@xyflow/react';
import { createContext, memo, useContext, useLayoutEffect, useRef } from 'react';
import { arcBulge, type ParticleFlowEdge } from './layout';
import type { ParticleEngine } from './particles';

export const EngineContext = createContext<ParticleEngine | null>(null);

function arcPath(sx: number, sy: number, tx: number, ty: number): string {
  const k = arcBulge(ty - sy);
  return `M${sx},${sy} C${sx + k},${sy} ${tx + k},${ty} ${tx},${ty}`;
}

function ParticleEdgeImpl({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<ParticleFlowEdge>) {
  const engine = useContext(EngineContext);
  const pathRef = useRef<SVGPathElement>(null);
  const layerRef = useRef<SVGGElement>(null);
  const glowRef = useRef<SVGGElement>(null);
  const hub = data?.kind === 'hub';
  const c1 = data?.sourceColor ?? '#8B95A7';
  const c2 = data?.targetColor ?? c1;
  const path =
    data?.shape === 'arc'
      ? arcPath(sourceX, sourceY, targetX, targetY)
      : getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })[0];
  const gid = `cc-grad-${id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;

  useLayoutEffect(() => {
    if (!engine || !pathRef.current || !layerRef.current) return;
    return engine.register(id, source, target, pathRef.current, layerRef.current, glowRef.current);
  }, [engine, id, source, target, path]);

  return (
    <g className="cc-edge">
      {!hub && (
        <defs>
          <linearGradient id={gid} gradientUnits="userSpaceOnUse" x1={sourceX} y1={sourceY} x2={targetX} y2={targetY}>
            <stop offset="0" stopColor={c1} />
            <stop offset="1" stopColor={c2} />
          </linearGradient>
        </defs>
      )}
      <path
        ref={pathRef}
        d={path}
        fill="none"
        stroke={hub ? c1 : `url(#${gid})`}
        strokeOpacity={hub ? 0.2 : 0.5}
        strokeWidth={hub ? 1 : 1.6}
        strokeDasharray={hub ? '2 5' : undefined}
        strokeLinecap="round"
      />
      <g ref={glowRef} className="cc-edge-glow" style={{ stroke: c1 }} fill="none" strokeLinecap="round">
        <path d={path} strokeWidth={hub ? 5 : 7} strokeOpacity={0.14} />
        <path d={path} strokeWidth={hub ? 1.4 : 2} strokeOpacity={0.8} />
      </g>
      <g ref={layerRef} />
    </g>
  );
}

export const ParticleEdge = memo(ParticleEdgeImpl);
