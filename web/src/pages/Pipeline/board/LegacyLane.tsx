/**
 * "Frozen (legacy)" swimlane under the board: items imported from the old shortlist. They are historical and
 * were never sent by Agent HQ, so they sit outside the live flow, frosted, in a horizontal row.
 */
import { ChevronDown, HandHelping, Snowflake } from 'lucide-react';
import { forwardRef } from 'react';
import { Link } from 'react-router';
import { cn } from '@/lib/cn';
import { useOpenNeeds } from '@/lib/store';
import type { OppSummary } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import type { CardListContext } from './BoardColumn';
import { OppCard } from './OppCard';
import { FROST } from './shared';

export interface LegacyLaneProps extends CardListContext {
  items: readonly OppSummary[];
  open: boolean;
  onToggle: () => void;
}

export const LegacyLane = forwardRef<HTMLElement, LegacyLaneProps>(function LegacyLane({ items, open, onToggle, ...ctx }, ref) {
  const confirmNeed = useOpenNeeds().find((n) => n.kind === 'confirm_legacy');
  return (
    <section
      ref={ref}
      aria-label="Frozen legacy items"
      className="relative scroll-mt-24 overflow-hidden rounded-2xl border border-dashed"
      style={{ borderColor: withAlpha(FROST, 0.22), background: `linear-gradient(180deg, ${withAlpha(FROST, 0.05)}, ${withAlpha(FROST, 0.012)})` }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage: `repeating-linear-gradient(135deg, ${withAlpha(FROST, 0.05)} 0 1px, transparent 1px 14px)`,
        }}
      />
      <header className="relative flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3">
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex min-w-0 items-center gap-2.5 text-left">
          <span
            className="grid size-8 shrink-0 place-items-center rounded-xl border"
            style={{ borderColor: withAlpha(FROST, 0.3), backgroundColor: withAlpha(FROST, 0.08), boxShadow: `0 0 22px -8px ${FROST}` }}
          >
            <Snowflake className="size-4" style={{ color: FROST }} aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-2">
              <span className="font-display text-[14px] font-semibold tracking-tight text-ink">Frozen (legacy)</span>
              <span
                className="grid h-5 min-w-5 place-items-center rounded-md px-1.5 font-display text-[11px] font-semibold tabular"
                style={{ color: FROST, backgroundColor: withAlpha(FROST, 0.12) }}
              >
                {items.length}
              </span>
            </span>
            <span className="block truncate text-xs text-muted">Historical — imported from the old shortlist, not sent by Agent HQ.</span>
          </span>
          <ChevronDown className={cn('size-4 shrink-0 text-muted transition-transform duration-200', !open && '-rotate-90')} aria-hidden />
        </button>
        {confirmNeed && (
          <Link
            to="/needs"
            className="ml-auto inline-flex h-7 items-center gap-1.5 rounded-lg border border-orange-300/30 bg-orange-300/10 px-2.5 text-xs font-medium text-orange-200 transition-colors hover:bg-orange-300/15"
          >
            <HandHelping className="size-3.5" aria-hidden />
            Confirm which you sent
          </Link>
        )}
      </header>
      {open && (
        <div className="relative -mt-1 pb-3">
          {items.length === 0 ? (
            <p className="px-4 pb-1 text-xs text-faint">No legacy items match the current filters.</p>
          ) : (
            <div className="scrollbar-none flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1 md:snap-none">
              {items.map((o) => (
                <OppCard
                  key={o.id}
                  opp={o}
                  variant="legacy"
                  flash={ctx.flashes[o.id]}
                  enter={ctx.isNew(o.id)}
                  tooltips={ctx.tooltips}
                  className="w-[min(80vw,300px)] shrink-0 snap-start md:w-[272px]"
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
});
