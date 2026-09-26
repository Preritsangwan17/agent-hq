/** Section header: small uppercase kicker, display-font title, optional icon and right-side slot. */
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface SectionHeaderProps {
  title: ReactNode;
  kicker?: ReactNode;
  icon?: LucideIcon;
  /** icon tint */
  color?: string;
  right?: ReactNode;
  as?: 'h1' | 'h2' | 'h3';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function SectionHeader({ title, kicker, icon: Icon, color, right, as: H = 'h2', size = 'md', className }: SectionHeaderProps) {
  return (
    <div className={cn('flex items-end justify-between gap-3', className)}>
      <div className="min-w-0">
        {kicker && (
          <div className="mb-1 font-mono text-[10px] font-medium uppercase tracking-[0.18em] text-muted">{kicker}</div>
        )}
        <H
          className={cn(
            'flex items-center gap-2 truncate font-display font-semibold tracking-tight text-ink',
            size === 'sm' && 'text-sm',
            size === 'md' && 'text-base md:text-lg',
            size === 'lg' && 'text-2xl md:text-3xl',
          )}
        >
          {Icon && <Icon className="size-4 shrink-0" style={{ color: color ?? '#8B95A7' }} aria-hidden />}
          <span className="truncate">{title}</span>
        </H>
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}
