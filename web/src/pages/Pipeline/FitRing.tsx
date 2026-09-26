/**
 * FitRing: circular fit score (0–100). Arc drawn with stroke-dasharray (static per render — only the reveal
 * uses a transform/opacity transition). null → dashed ring with "—". Shared by the kanban cards and /o/:id.
 * Candidate for promotion to src/components.
 */
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';
import { fitColor } from './model';

export interface FitRingProps {
  score: number | null | undefined;
  size?: number;
  stroke?: number;
  /** show the "FIT" caption under the number (large rings) */
  caption?: boolean;
  className?: string;
}

export function FitRing({ score, size = 34, stroke, caption, className }: FitRingProps) {
  const sw = stroke ?? Math.max(2.5, size * 0.085);
  const r = (size - sw) / 2 - 1;
  const c = 2 * Math.PI * r;
  const v = score == null ? 0 : Math.max(0, Math.min(100, score));
  const color = fitColor(score);
  const big = size >= 64;
  return (
    <span
      className={cn('relative inline-grid shrink-0 place-items-center', className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={score == null ? 'Match not scored yet' : `Match ${Math.round(v)} of 100`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={score == null ? 'rgba(255,255,255,0.14)' : withAlpha(color, 0.16)}
          strokeWidth={sw}
          strokeDasharray={score == null ? '2 3' : undefined}
        />
        {score != null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={sw}
            strokeLinecap="round"
            strokeDasharray={`${(v / 100) * c} ${c}`}
            style={{ filter: `drop-shadow(0 0 ${big ? 6 : 3}px ${withAlpha(color, 0.7)})` }}
          />
        )}
      </svg>
      <span className="relative flex flex-col items-center leading-none">
        <span
          className={cn('font-display font-semibold tabular', big ? 'text-3xl' : size >= 40 ? 'text-sm' : 'text-[11px]')}
          style={{ color: score == null ? '#5B6577' : color }}
        >
          {score == null ? '—' : Math.round(v)}
        </span>
        {caption && <span className="mt-1 font-mono text-[9px] uppercase tracking-[0.2em] text-faint">match</span>}
      </span>
    </span>
  );
}
