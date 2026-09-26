/**
 * Stage strip above the board: per-column counts, median ₹/month and a share bar — an at-a-glance funnel for
 * columns that are scrolled off-screen. Clicking a stage scrolls the board to it; on mobile it doubles as the
 * tab bar of the snap-scrolling board (the column in view is highlighted).
 */
import { ChevronRight } from 'lucide-react';
import { Fragment, useEffect, useRef } from 'react';
import { cn } from '@/lib/cn';
import { formatINRCompact } from '@/lib/format';
import { withAlpha } from '@/theme/tokens';

export interface StripItem {
  id: string;
  label: string;
  color: string;
  count: number;
  median: number | null;
  /** separated side lane (filtered / frozen) */
  side?: boolean;
}

export function StageStrip({
  items,
  active,
  onSelect,
}: {
  items: StripItem[];
  active: string | null;
  onSelect: (id: string) => void;
}) {
  const max = Math.max(1, ...items.filter((i) => !i.side).map((i) => i.count));
  const scroller = useRef<HTMLDivElement>(null);

  // keep the active pill visible on mobile
  useEffect(() => {
    const el = scroller.current?.querySelector<HTMLElement>(`[data-strip="${active}"]`);
    const box = scroller.current;
    if (!el || !box || box.scrollWidth <= box.clientWidth) return;
    const left = el.offsetLeft - box.clientWidth / 2 + el.clientWidth / 2;
    box.scrollTo({ left, behavior: 'smooth' });
  }, [active]);

  return (
    <nav aria-label="Pipeline stages" className="relative">
      <div ref={scroller} className="-mx-4 flex items-stretch gap-1 overflow-x-auto px-4 scrollbar-none md:mx-0 md:px-0">
        {items.map((it, i) => {
          const on = active === it.id;
          const prev = items[i - 1];
          return (
            <Fragment key={it.id}>
              {i > 0 && prev && !prev.side && !it.side && (
                <ChevronRight className="hidden size-3.5 shrink-0 self-center text-white/15 lg:block" aria-hidden />
              )}
              {i > 0 && it.side && !prev?.side && <span className="mx-1 w-px shrink-0 self-stretch bg-white/[.08]" aria-hidden />}
              <button
                type="button"
                data-strip={it.id}
                onClick={() => onSelect(it.id)}
                aria-current={on ? 'true' : undefined}
                className={cn(
                  'group relative flex min-w-[92px] shrink-0 flex-col rounded-xl border px-2.5 py-1.5 text-left transition-[background-color,border-color] duration-200 md:min-w-0 md:flex-1',
                  on ? 'bg-white/[.06]' : 'border-transparent hover:bg-white/[.04]',
                )}
                style={on ? { borderColor: withAlpha(it.color, 0.4) } : undefined}
              >
                <span className="flex items-center gap-1.5">
                  <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: it.color, boxShadow: `0 0 6px ${it.color}` }} />
                  <span className={cn('truncate text-[11px] font-medium', on ? 'text-ink' : 'text-muted group-hover:text-ink')}>{it.label}</span>
                </span>
                <span className="mt-0.5 flex items-baseline gap-1.5">
                  <span className="font-display text-[17px] font-semibold leading-6 tabular text-ink">{it.count}</span>
                  {it.median != null && (
                    <span className="truncate text-[10.5px] font-medium tabular text-money">{formatINRCompact(it.median)}</span>
                  )}
                </span>
                {!it.side && (
                  <span className="mt-1 h-[3px] w-full overflow-hidden rounded-full bg-white/[.05]">
                    <span
                      className="block h-full origin-left rounded-full transition-transform duration-500 ease-out"
                      style={{ transform: `scaleX(${it.count / max})`, backgroundColor: withAlpha(it.color, 0.85) }}
                    />
                  </span>
                )}
              </button>
            </Fragment>
          );
        })}
      </div>
    </nav>
  );
}
