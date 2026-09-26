/**
 * StatCounter: count-up number (motion `animate`, writes textContent directly — no re-render per frame).
 * Animates from the previous value on change; jumps instantly with prefers-reduced-motion.
 * `money` renders the value in the gold pay gradient (use only for pay figures).
 */
import type { LucideIcon } from 'lucide-react';
import { animate, useReducedMotion } from 'motion/react';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { formatNumber } from '@/lib/format';
import { withAlpha } from '@/theme/tokens';

export interface StatCounterProps {
  value: number | null | undefined;
  label: ReactNode;
  /** formatter for the displayed number (default: Indian-grouped integer) */
  format?: (n: number) => string;
  icon?: LucideIcon;
  /** accent color for icon/glow */
  accent?: string;
  /** gold money styling (pay only) */
  money?: boolean;
  /** small line under the number (e.g. "vs ₹32K living cost") */
  sub?: ReactNode;
  /** element on the right of the label row (sparkline, badge) */
  aside?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  /** duration in seconds (default 0.9) */
  duration?: number;
  className?: string;
}

export function StatCounter({
  value,
  label,
  format = (n) => formatNumber(n),
  icon: Icon,
  accent = '#22D3EE',
  money,
  sub,
  aside,
  size = 'md',
  duration = 0.9,
  className,
}: StatCounterProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef<number | null>(null);
  const reduce = useReducedMotion();
  const fmt = useRef(format);
  useLayoutEffect(() => {
    fmt.current = format;
  });

  // The number is written imperatively (React renders an empty span) so per-frame updates skip reconciliation.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (value == null || !Number.isFinite(value)) {
      el.textContent = '—';
      prev.current = null;
      return;
    }
    const from = prev.current ?? 0;
    prev.current = value; // updated per frame below, so an interrupted count continues from what is shown
    if (reduce || from === value) {
      el.textContent = fmt.current(value);
      return;
    }
    el.textContent = fmt.current(from);
    const isInt = Number.isInteger(value);
    const c = animate(from, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        prev.current = v;
        el.textContent = fmt.current(isInt ? Math.round(v) : v);
      },
      onComplete: () => {
        prev.current = value;
      },
    });
    return () => c.stop();
  }, [value, reduce, duration]);

  return (
    <div className={cn('min-w-0', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
          {Icon && <Icon className="size-3.5 shrink-0" style={{ color: money ? '#F5C451' : accent }} aria-hidden />}
          <span className="truncate">{label}</span>
        </div>
        {aside}
      </div>
      <div
        className={cn(
          'mt-1.5 font-display font-semibold leading-none tracking-tight tabular',
          size === 'sm' && 'text-xl',
          size === 'md' && 'text-3xl',
          size === 'lg' && 'text-4xl md:text-5xl',
          money ? 'text-money' : 'text-ink',
        )}
        style={money ? { filter: 'drop-shadow(0 0 18px rgba(245,196,81,0.25))' } : { textShadow: `0 0 28px ${withAlpha(accent, 0.25)}` }}
      >
        <span ref={ref} />
      </div>
      {sub && <div className="mt-1.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}
