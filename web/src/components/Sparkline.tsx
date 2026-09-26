/** Minimal SVG sparkline (no axes) with a soft gradient fill. */
import { useId } from 'react';
import { cn } from '@/lib/cn';

export interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
  strokeWidth?: number;
  className?: string;
  /** accessible summary, e.g. "tasks per hour, rising" */
  label?: string;
}

export function Sparkline({ data, width = 96, height = 28, color = '#22D3EE', fill = true, strokeWidth = 1.5, className, label }: SparklineProps) {
  const gid = useId().replace(/:/g, '');
  if (data.length < 2) return <svg width={width} height={height} className={className} aria-hidden />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pad = strokeWidth;
  const pts = data.map((d, i) => [
    pad + (i / (data.length - 1)) * (width - pad * 2),
    pad + (1 - (d - min) / span) * (height - pad * 2),
  ]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${height} L${pts[0][0].toFixed(1)},${height} Z`;
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('overflow-visible', className)} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <defs>
        <linearGradient id={`sg${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#sg${gid})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r={strokeWidth + 1} fill={color} />
    </svg>
  );
}
