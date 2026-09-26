/** Generic tinted badge / chip (mode badge, counts, tags). */
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface BadgeProps {
  children: ReactNode;
  /** hex tint; default neutral */
  color?: string;
  icon?: LucideIcon;
  size?: 'xs' | 'sm' | 'md';
  mono?: boolean;
  /** solid background (for counts on nav items) */
  solid?: boolean;
  className?: string;
  title?: string;
}

export function Badge({ children, color, icon: Icon, size = 'sm', mono, solid, className, title }: BadgeProps) {
  const c = color ?? '#8B95A7';
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md border font-medium whitespace-nowrap tabular',
        size === 'xs' && 'h-4 px-1 text-[10px]',
        size === 'sm' && 'h-5 px-1.5 text-[11px]',
        size === 'md' && 'h-6 px-2 text-xs',
        mono && 'font-mono tracking-wider',
        className,
      )}
      style={
        solid
          ? { backgroundColor: c, borderColor: c, color: '#070B14' }
          : { color: c, backgroundColor: withAlpha(c, 0.1), borderColor: withAlpha(c, 0.28) }
      }
    >
      {Icon && <Icon className={size === 'md' ? 'size-3.5' : 'size-3'} aria-hidden />}
      {children}
    </span>
  );
}
