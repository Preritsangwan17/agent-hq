/** Thin progress bar animated with scaleX (never width). `value` 0..1; null → indeterminate shimmer. */
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface ProgressBarProps {
  value: number | null | undefined;
  color?: string;
  height?: number;
  className?: string;
}

export function ProgressBar({ value, color = '#22D3EE', height = 4, className }: ProgressBarProps) {
  const v = value == null ? null : Math.max(0, Math.min(1, value));
  return (
    <div
      className={cn('relative overflow-hidden rounded-full', className)}
      style={{ height, backgroundColor: withAlpha(color, 0.12) }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v == null ? undefined : Math.round(v * 100)}
    >
      {v == null ? (
        <div className="absolute inset-y-0 left-0 w-1/2 animate-shimmer" style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(color, 0.7)}, transparent)` }} />
      ) : (
        <div
          className="absolute inset-0 origin-left rounded-full transition-transform duration-300 ease-out"
          style={{ transform: `scaleX(${v})`, background: `linear-gradient(90deg, ${withAlpha(color, 0.55)}, ${color})`, boxShadow: `0 0 10px ${withAlpha(color, 0.6)}` }}
        />
      )}
    </div>
  );
}
