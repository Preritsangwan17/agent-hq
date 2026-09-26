/**
 * Filter chip rows for the terminal: agents (+ system), levels and event types, each with live counts.
 * Click hides/shows a chip; Shift/Alt/⌘-click shows only that one (again → everything).
 */
import type { MouseEvent, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { formatCompact } from '@/lib/format';
import { withAlpha } from '@/theme/tokens';

export interface ChipSpec {
  key: string;
  label: ReactNode;
  color: string;
  count: number;
  /** leading glyph (emoji / dot) */
  lead?: ReactNode;
  title?: string;
}

export interface ChipRowProps {
  label: string;
  chips: readonly ChipSpec[];
  hidden: readonly string[];
  onToggle: (key: string, solo: boolean) => void;
  className?: string;
  /** one scrolling line on phones */
  nowrap?: boolean;
}

export function ChipRow({ label, chips, hidden, onToggle, className, nowrap }: ChipRowProps) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2', className)}>
      <span className="w-[46px] shrink-0 font-mono text-[9.5px] uppercase tracking-[0.18em] text-faint">{label}</span>
      <div
        className={cn(
          'flex min-w-0 flex-1 gap-1.5',
          nowrap ? 'scrollbar-none overflow-x-auto [mask-image:linear-gradient(to_right,#000_calc(100%-24px),transparent)] pr-6' : 'flex-wrap',
        )}
      >
        {chips.map((c) => {
          const on = !hidden.includes(c.key);
          return (
            <button
              key={c.key}
              type="button"
              aria-pressed={on}
              title={c.title ?? `${on ? 'Hide' : 'Show'} ${typeof c.label === 'string' ? c.label : c.key} · Shift-click: only this`}
              onClick={(e: MouseEvent) => onToggle(c.key, e.shiftKey || e.altKey || e.metaKey || e.ctrlKey)}
              className={cn(
                'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border px-2 font-mono text-[11px] transition-[background-color,border-color,color,opacity] duration-150',
                on ? 'text-ink' : 'border-white/[.06] text-faint opacity-60 hover:opacity-90',
              )}
              style={on ? { borderColor: withAlpha(c.color, 0.35), backgroundColor: withAlpha(c.color, 0.09) } : undefined}
            >
              {c.lead ?? (
                <span
                  className="size-1.5 rounded-full"
                  style={{ backgroundColor: on ? c.color : 'rgba(255,255,255,0.2)', boxShadow: on ? `0 0 6px ${c.color}` : undefined }}
                />
              )}
              <span className={cn(!on && 'line-through decoration-white/25')} style={on ? { color: c.color } : undefined}>
                {c.label}
              </span>
              <span className="tabular text-[10px] text-faint">{formatCompact(c.count)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
