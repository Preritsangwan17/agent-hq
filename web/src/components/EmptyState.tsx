/** Empty state: soft icon disc, title, hint and an optional action. */
import type { LucideIcon } from 'lucide-react';
import { Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  /** icon tint (default cyan) */
  color?: string;
  className?: string;
}

export function EmptyState({ icon: Icon = Sparkles, title, hint, action, compact, color = '#22D3EE', className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2 py-6' : 'gap-3 py-14', className)}>
      <div
        className={cn('grid place-items-center rounded-2xl border border-white/10 bg-white/[.03]', compact ? 'size-10' : 'size-14')}
        style={{ boxShadow: `0 0 40px -12px ${color}66` }}
      >
        <Icon className={compact ? 'size-4' : 'size-6'} style={{ color }} aria-hidden />
      </div>
      <div className={cn('font-display font-medium text-ink', compact ? 'text-sm' : 'text-base')}>{title}</div>
      {hint && <div className="max-w-sm text-sm text-muted">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
