/** Segmented control with a sliding highlight (motion layoutId → transform only). Page-local UI primitive. */
import type { LucideIcon } from 'lucide-react';
import { LayoutGroup, motion } from 'motion/react';
import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';

export interface SegmentedOption<T extends string | number> {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  title?: string;
}

export interface SegmentedProps<T extends string | number> {
  value: T;
  onChange: (v: T) => void;
  options: readonly SegmentedOption<T>[];
  ariaLabel: string;
  /** tint of the active pill (default cyan) */
  color?: string;
  size?: 'sm' | 'md';
  className?: string;
  /** stretch options to fill the width */
  block?: boolean;
}

export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  ariaLabel,
  color = '#22D3EE',
  size = 'sm',
  className,
  block,
}: SegmentedProps<T>) {
  const id = useId();
  return (
    <LayoutGroup id={id}>
      <div
        role="radiogroup"
        aria-label={ariaLabel}
        className={cn(
          'relative inline-flex shrink-0 items-center rounded-lg border border-white/[.08] bg-white/[.03] p-0.5',
          block && 'flex w-full',
          className,
        )}
      >
        {options.map((o) => {
          const active = o.value === value;
          const Icon = o.icon;
          return (
            <button
              key={String(o.value)}
              type="button"
              role="radio"
              aria-checked={active}
              title={o.title}
              onClick={() => onChange(o.value)}
              className={cn(
                'relative inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-md font-medium transition-colors duration-150',
                size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
                block && 'flex-1',
                active ? 'text-ink' : 'text-muted hover:text-ink/90',
              )}
            >
              {active && (
                <motion.span
                  layoutId="seg-pill"
                  className="absolute inset-0 rounded-md border"
                  style={{
                    backgroundColor: withAlpha(color, 0.12),
                    borderColor: withAlpha(color, 0.34),
                    boxShadow: `0 0 16px -6px ${withAlpha(color, 0.9)}`,
                  }}
                  transition={{ type: 'spring', stiffness: 520, damping: 40 }}
                />
              )}
              {Icon && <Icon className="relative size-3.5" aria-hidden style={active ? { color } : undefined} />}
              <span className="relative">{o.label}</span>
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
