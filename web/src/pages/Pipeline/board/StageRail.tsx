/**
 * Stage rail: one pill per board column (count per stage, in flow order) plus Filtered and Legacy. Pills of the
 * columns currently in view are lit; tapping a pill scrolls that column (or the legacy lane) into view — on phones
 * this doubles as the swipe position indicator.
 */
import { ChevronRight, Funnel, Snowflake } from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { Fragment, useEffect, useRef } from 'react';
import { cn } from '@/lib/cn';
import { withAlpha } from '@/theme/tokens';
import { FROST } from './shared';

export interface RailItem {
  id: string;
  label: string;
  color: string;
  count: number;
  /** side lanes (Filtered / Legacy) are drawn after a divider without chevrons */
  side?: 'filtered' | 'legacy';
}

export interface StageRailProps {
  items: readonly RailItem[];
  inView: ReadonlySet<string>;
  onJump: (id: string) => void;
  className?: string;
}

export function StageRail({ items, inView, onJump, className }: StageRailProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const main = items.filter((i) => !i.side);
  const side = items.filter((i) => i.side);
  const firstInView = main.find((i) => inView.has(i.id))?.id;
  const reduced = useReducedMotion();

  // keep the lit pill visible in the (phone) rail as the board is swiped
  useEffect(() => {
    if (!firstInView || !scroller.current) return;
    const el = scroller.current.querySelector<HTMLElement>(`[data-rail="${firstInView}"]`);
    if (!el) return;
    const s = scroller.current;
    const left = el.offsetLeft - s.clientWidth / 2 + el.clientWidth / 2;
    s.scrollTo({ left: Math.max(0, left), behavior: reduced ? 'auto' : 'smooth' });
  }, [firstInView, reduced]);

  return (
    <nav aria-label="Pipeline stages" className={cn('relative -mx-4 md:mx-0', className)}>
      <div ref={scroller} className="scrollbar-none relative flex items-center gap-1 overflow-x-auto px-4 md:px-0">
        {main.map((it, i) => (
          <Fragment key={it.id}>
            {i > 0 && <ChevronRight className="size-3 shrink-0 text-white/15" aria-hidden />}
            <Pill item={it} lit={inView.has(it.id)} onJump={onJump} />
          </Fragment>
        ))}
        {side.length > 0 && <span className="mx-2 h-5 w-px shrink-0 bg-white/10" aria-hidden />}
        {side.map((it) => (
          <Pill key={it.id} item={it} lit={inView.has(it.id)} onJump={onJump} />
        ))}
      </div>
    </nav>
  );
}

function Pill({ item, lit, onJump }: { item: RailItem; lit: boolean; onJump: (id: string) => void }) {
  const color = item.side === 'legacy' ? FROST : item.color;
  const Icon = item.side === 'legacy' ? Snowflake : item.side === 'filtered' ? Funnel : null;
  return (
    <button
      type="button"
      data-rail={item.id}
      onClick={() => onJump(item.id)}
      className={cn(
        'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-[background-color,border-color,color,opacity] duration-200',
        lit ? 'text-ink' : 'border-transparent text-muted hover:text-ink',
        item.count === 0 && !lit && 'opacity-60',
      )}
      style={lit ? { borderColor: withAlpha(color, 0.35), backgroundColor: withAlpha(color, 0.1) } : undefined}
      aria-label={`${item.label}: ${item.count}`}
    >
      {Icon ? (
        <Icon className="size-3" style={{ color }} aria-hidden />
      ) : (
        <span className="size-1.5 rounded-full" style={{ backgroundColor: color, boxShadow: lit ? `0 0 8px ${color}` : undefined }} />
      )}
      <span className="whitespace-nowrap">{item.label}</span>
      <span className={cn('font-display tabular', lit ? '' : 'text-faint')} style={lit ? { color } : undefined}>
        {item.count}
      </span>
    </button>
  );
}
