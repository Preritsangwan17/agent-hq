/** Pipeline stage pill colored per stage (STAGE_META). */
import { cn } from '@/lib/cn';
import type { Stage } from '@/lib/types';
import { STAGE_META, withAlpha } from '@/theme/tokens';

export interface StageChipProps {
  stage: Stage;
  size?: 'sm' | 'md';
  /** leading dot (default true) */
  dot?: boolean;
  className?: string;
  title?: string;
}

export function StageChip({ stage, size = 'sm', dot = true, className, title }: StageChipProps) {
  const meta = STAGE_META[stage] ?? { label: stage, color: '#8B95A7' };
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium whitespace-nowrap',
        size === 'sm' ? 'h-5 px-2 text-[11px]' : 'h-6 px-2.5 text-xs',
        className,
      )}
      style={{ color: meta.color, backgroundColor: withAlpha(meta.color, 0.1), borderColor: withAlpha(meta.color, 0.3) }}
    >
      {dot && <span className="size-1.5 rounded-full" style={{ backgroundColor: meta.color, boxShadow: `0 0 8px ${meta.color}` }} />}
      {meta.label}
    </span>
  );
}
