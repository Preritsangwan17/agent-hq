/** Small layout pieces shared by the Settings tabs. */
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { GlassPanel } from '@/components/GlassPanel';
import { SectionHeader } from '@/components/SectionHeader';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface SectionProps {
  title: ReactNode;
  kicker?: ReactNode;
  icon?: LucideIcon;
  color?: string;
  right?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  /** rows are separated by hairlines */
  rows?: boolean;
}

export function Section({ title, kicker, icon, color = '#8B95A7', right, description, children, className, rows = true }: SectionProps) {
  return (
    <GlassPanel padding="lg" glow={color} glowStrength={0.22} className={className}>
      <SectionHeader title={title} kicker={kicker} icon={icon} color={color} right={right} />
      {description && <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-muted">{description}</p>}
      <div className={cn('mt-4', rows && 'divide-y divide-white/[.06]')}>{children}</div>
    </GlassPanel>
  );
}

/** Inline "callout" note (info tone by default). */
export function Callout({
  icon: Icon,
  color = '#22D3EE',
  title,
  children,
  className,
}: {
  icon: LucideIcon;
  color?: string;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn('flex gap-3 rounded-xl border p-3.5 text-[13px] leading-relaxed', className)}
      style={{ borderColor: withAlpha(color, 0.25), backgroundColor: withAlpha(color, 0.06) }}
    >
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color }} aria-hidden />
      <div className="min-w-0 text-ink/85">
        {title && <div className="mb-0.5 font-medium text-ink">{title}</div>}
        {children}
      </div>
    </div>
  );
}

/** Monospace inline code chip. */
export function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-md border border-white/10 bg-white/[.05] px-1.5 py-px font-mono text-[12px] text-ink/90">{children}</code>;
}
