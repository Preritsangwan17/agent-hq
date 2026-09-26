/**
 * Kanban columns: a stage column (header with count + median ₹/mo, scrollable card list), the shared
 * Offer / Rejected outcome column (two sections), and the collapsible Filtered column (scam / ineligible / expired).
 * Scroll containers are `layoutScroll` so cross-column layoutId transitions account for their scroll offsets.
 */
import { ChevronsRight, Funnel, Trophy, UserX } from 'lucide-react';
import { motion } from 'motion/react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { formatINRCompact } from '@/lib/format';
import type { OppSummary } from '@/lib/types';
import { STAGE_META, withAlpha } from '@/theme/tokens';
import { medianMonthly, type ColumnDef } from './filters';
import { OppCard, type CardVariant, type StageFlash } from './OppCard';
import { FILTER_META, filterCategory, type FilterCategory } from './shared';

export interface CardListContext {
  flashes: Readonly<Record<string, StageFlash>>;
  isNew: (id: string) => boolean;
  tooltips: boolean;
}

const EMPTY_HINT: Record<string, string> = {
  found: 'Scout is watching the boards.',
  verified: 'Verifier checks link, deadline, pay and scam signals.',
  drafted: 'Writer drafts from verified facts only.',
  checked: 'Fact-Checker and Reviewer gates.',
  applied: 'Nothing has gone out yet.',
  replied: 'No replies yet.',
  interview: 'Interviews raise an alert for you.',
  outcome: 'No offers or rejections yet.',
};

const COL_W = 'w-[min(84vw,330px)] md:w-[272px]';

function ColumnShell({
  id,
  color,
  header,
  children,
  className,
}: {
  id: string;
  color: string;
  header: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      data-col={id}
      aria-label={id}
      className={cn(
        'relative flex h-full shrink-0 snap-start flex-col overflow-hidden rounded-2xl border border-white/[.07] bg-[linear-gradient(180deg,rgba(255,255,255,0.035),rgba(255,255,255,0.012))]',
        COL_W,
        className,
      )}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-5 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(color, 0.85)}, transparent)` }}
      />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-16"
        style={{ background: `radial-gradient(80% 100% at 50% 0%, ${withAlpha(color, 0.1)}, transparent)` }}
      />
      {header}
      {children}
    </section>
  );
}

function ColumnHeader({ label, color, count, median }: { label: string; color: string; count: number; median: number | null }) {
  return (
    <header className="relative flex items-center gap-2 px-3.5 pb-2.5 pt-3">
      <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color, boxShadow: `0 0 10px ${color}` }} />
      <h3 className="truncate font-display text-[13.5px] font-semibold tracking-tight text-ink">{label}</h3>
      <span
        className="grid h-5 min-w-5 shrink-0 place-items-center rounded-md px-1.5 font-display text-[11px] font-semibold tabular"
        style={{ color, backgroundColor: withAlpha(color, 0.12) }}
      >
        {count}
      </span>
      {median != null && (
        <span className="ml-auto flex shrink-0 items-baseline gap-1" title="Median ₹/month of the cards in this column">
          <span className="text-[9.5px] uppercase tracking-[0.12em] text-faint">med</span>
          <span className="font-display text-[12px] font-semibold tabular text-money">{formatINRCompact(median)}</span>
        </span>
      )}
    </header>
  );
}

function CardScroller({ children }: { children: ReactNode }) {
  return (
    <motion.div
      layoutScroll
      className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3 [mask-image:linear-gradient(to_bottom,transparent,#000_6px,#000_calc(100%-18px),transparent)]"
    >
      <div className="flex flex-col gap-2 pt-1">{children}</div>
    </motion.div>
  );
}

function renderCards(items: readonly OppSummary[], ctx: CardListContext, variant: CardVariant = 'board') {
  return items.map((o) => (
    <OppCard key={o.id} opp={o} variant={variant} flash={ctx.flashes[o.id]} enter={ctx.isNew(o.id)} tooltips={ctx.tooltips} />
  ));
}

function EmptyColumn({ color, hint }: { color: string; hint: string }) {
  return (
    <div
      className="mx-0.5 flex flex-col items-center gap-1.5 rounded-xl border border-dashed px-3 py-6 text-center"
      style={{ borderColor: withAlpha(color, 0.2) }}
    >
      <span className="size-1.5 rounded-full opacity-60" style={{ backgroundColor: color }} />
      <span className="text-[11.5px] text-faint">{hint}</span>
    </div>
  );
}

export interface StageColumnProps extends CardListContext {
  def: ColumnDef;
  items: readonly OppSummary[];
}

export function StageColumn({ def, items, ...ctx }: StageColumnProps) {
  return (
    <ColumnShell
      id={def.id}
      color={def.color}
      header={<ColumnHeader label={def.label} color={def.color} count={items.length} median={medianMonthly(items)} />}
    >
      <CardScroller>{items.length ? renderCards(items, ctx) : <EmptyColumn color={def.color} hint={EMPTY_HINT[def.id] ?? 'Nothing here.'} />}</CardScroller>
    </ColumnShell>
  );
}

export interface OutcomeColumnProps extends CardListContext {
  def: ColumnDef;
  items: readonly OppSummary[];
}

export function OutcomeColumn({ def, items, ...ctx }: OutcomeColumnProps) {
  const offers = items.filter((o) => o.stage === 'offer');
  const rejected = items.filter((o) => o.stage === 'rejected');
  const offerColor = STAGE_META.offer.color;
  const rejColor = STAGE_META.rejected.color;
  return (
    <ColumnShell
      id={def.id}
      color={def.color}
      header={<ColumnHeader label={def.label} color={def.color} count={items.length} median={medianMonthly(offers)} />}
    >
      <CardScroller>
        {!items.length && <EmptyColumn color={def.color} hint={EMPTY_HINT.outcome} />}
        {items.length > 0 && (
          <>
            <SectionLabel icon={Trophy} color={offerColor} label="Offer" count={offers.length} />
            {offers.length ? renderCards(offers, ctx) : <p className="px-1 pb-1 text-[11px] text-faint">No offers yet.</p>}
            <SectionLabel icon={UserX} color={rejColor} label="Rejected" count={rejected.length} className="mt-2" />
            {rejected.length ? renderCards(rejected, ctx, 'rejected') : <p className="px-1 text-[11px] text-faint">None.</p>}
          </>
        )}
      </CardScroller>
    </ColumnShell>
  );
}

function SectionLabel({
  icon: Icon,
  color,
  label,
  count,
  className,
}: {
  icon: typeof Trophy;
  color: string;
  label: string;
  count: number;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center gap-1.5 px-1 pt-0.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]', className)} style={{ color }}>
      <Icon className="size-3" aria-hidden />
      {label}
      <span className="tabular text-faint">{count}</span>
      <span className="ml-1 h-px flex-1" style={{ background: `linear-gradient(90deg, ${withAlpha(color, 0.35)}, transparent)` }} />
    </div>
  );
}

export interface FilteredColumnProps extends CardListContext {
  def: ColumnDef;
  items: readonly OppSummary[];
  open: boolean;
  onToggle: () => void;
}

export function FilteredColumn({ def, items, open, onToggle, ...ctx }: FilteredColumnProps) {
  const counts: Record<FilterCategory, number> = { scam: 0, ineligible: 0, expired: 0, other: 0 };
  for (const o of items) counts[filterCategory(o)]++;
  const cats = (Object.keys(counts) as FilterCategory[]).filter((k) => counts[k] > 0);

  if (!open) {
    return (
      <button
        type="button"
        data-col={def.id}
        onClick={onToggle}
        aria-expanded={false}
        aria-label={`Filtered: ${items.length} items. Expand`}
        className="group relative flex h-full w-[52px] shrink-0 snap-start flex-col items-center gap-3 overflow-hidden rounded-2xl border border-white/[.07] bg-white/[.02] py-3.5 transition-colors hover:border-white/[.14] hover:bg-white/[.04]"
      >
        <Funnel className="size-4 text-muted transition-colors group-hover:text-ink" aria-hidden />
        <span className="grid h-5 min-w-5 place-items-center rounded-md bg-white/[.06] px-1 font-display text-[11px] font-semibold tabular text-ink/80">
          {items.length}
        </span>
        <span className="flex flex-col items-center gap-1.5">
          {cats.map((c) => (
            <span
              key={c}
              title={`${FILTER_META[c].label}: ${counts[c]}`}
              className="size-2 rounded-full"
              style={{ backgroundColor: FILTER_META[c].color, boxShadow: `0 0 6px ${FILTER_META[c].color}` }}
            />
          ))}
        </span>
        <span className="mt-1 rotate-180 font-display text-[12px] font-semibold tracking-[0.08em] text-muted [writing-mode:vertical-rl] group-hover:text-ink">
          Filtered — scam · ineligible · expired
        </span>
      </button>
    );
  }

  return (
    <ColumnShell
      id={def.id}
      color={def.color}
      header={
        <header className="relative flex items-center gap-2 px-3.5 pb-2 pt-3">
          <Funnel className="size-3.5 text-muted" aria-hidden />
          <h3 className="font-display text-[13.5px] font-semibold tracking-tight text-ink">Filtered</h3>
          <span className="grid h-5 min-w-5 place-items-center rounded-md bg-white/[.06] px-1.5 font-display text-[11px] font-semibold tabular text-ink/80">
            {items.length}
          </span>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded
            className="ml-auto grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-white/[.06] hover:text-ink"
            aria-label="Collapse Filtered column"
            title="Collapse"
          >
            <ChevronsRight className="size-4" aria-hidden />
          </button>
        </header>
      }
    >
      {cats.length > 0 && (
        <div className="relative flex flex-wrap gap-1.5 px-3.5 pb-2">
          {cats.map((c) => {
            const m = FILTER_META[c];
            return (
              <span
                key={c}
                className="inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-[10.5px] font-medium"
                style={{ color: m.color, borderColor: withAlpha(m.color, 0.25), backgroundColor: withAlpha(m.color, 0.07) }}
              >
                <m.icon className="size-3" aria-hidden />
                {m.label} <span className="tabular opacity-80">{counts[c]}</span>
              </span>
            );
          })}
        </div>
      )}
      <CardScroller>
        {items.length ? renderCards(items, ctx, 'filtered') : <EmptyColumn color={def.color} hint="Nothing filtered out." />}
      </CardScroller>
    </ColumnShell>
  );
}
