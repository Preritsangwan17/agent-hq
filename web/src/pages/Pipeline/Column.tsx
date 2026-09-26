/**
 * Kanban columns: a flow column (header with count + median pay, scrollable card list, empty state), the
 * outcome column (Offer / Rejected sections) and the collapsible "Filtered" column with reason breakdown.
 */
import { AnimatePresence, motion } from 'motion/react';
import { ChevronsLeft, Funnel } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { AgentAvatar, PayBadge, SimTag, Tooltip } from '@/components';
import { cn } from '@/lib/cn';
import { formatINRCompact } from '@/lib/format';
import type { OppSummary } from '@/lib/types';
import { STAGE_META, withAlpha } from '@/theme/tokens';
import { FILTER_REASON_META, filterReason, medianMonthly, type ColumnDef, type FilterReason } from './model';
import { OppCard } from './OppCard';

export interface CardState {
  flashes: Record<string, number>;
  isNew: (id: string) => boolean;
}

const COL_W = 'w-[84vw] max-w-[340px] md:w-[276px] md:max-w-none';

function ColumnShell({
  color,
  children,
  className,
}: {
  color: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn('glass relative flex h-full shrink-0 snap-start flex-col overflow-hidden rounded-2xl', className)}
      style={{ ['--glow' as string]: withAlpha(color, 0.14) }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-5 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${withAlpha(color, 0.85)}, transparent)` }}
      />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-24"
        style={{ background: `radial-gradient(120% 100% at 50% 0%, ${withAlpha(color, 0.09)}, transparent 70%)` }}
      />
      {children}
    </section>
  );
}

function ColumnHeader({ def, count, medianPay }: { def: ColumnDef; count: number; medianPay: number | null }) {
  const Icon = def.icon;
  return (
    <header className="relative flex items-center gap-2 px-3.5 pb-2.5 pt-3">
      <span
        className="grid size-7 shrink-0 place-items-center rounded-lg border"
        style={{ borderColor: withAlpha(def.color, 0.3), backgroundColor: withAlpha(def.color, 0.1), boxShadow: `0 0 16px -6px ${def.color}` }}
      >
        <Icon className="size-3.5" style={{ color: def.color }} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <h3 className="truncate font-display text-[13.5px] font-semibold tracking-tight text-ink">{def.label}</h3>
          <span className="font-display text-[13px] font-semibold tabular" style={{ color: def.color }}>
            {count}
          </span>
        </div>
        <div className="truncate text-[10.5px] text-faint">
          {medianPay != null ? (
            <>
              median <span className="font-medium text-money tabular">{formatINRCompact(medianPay)}</span>/mo
            </>
          ) : (
            'no pay data'
          )}
        </div>
      </div>
      {def.agent && <AgentAvatar id={def.agent} size={24} className="opacity-90" />}
    </header>
  );
}

function EmptyColumn({ def }: { def: ColumnDef }) {
  const Icon = def.icon;
  return (
    <div className="mx-0.5 flex flex-col items-center gap-2 rounded-xl border border-dashed border-white/[.08] px-4 py-8 text-center">
      <span className="grid size-9 place-items-center rounded-xl bg-white/[.03]" style={{ boxShadow: `0 0 28px -10px ${def.color}` }}>
        <Icon className="size-4 opacity-70" style={{ color: def.color }} aria-hidden />
      </span>
      <div className="text-[12px] font-medium text-muted">Nothing here yet</div>
      <div className="max-w-[210px] text-[11px] leading-snug text-faint">{def.hint}</div>
    </div>
  );
}

function CardList({ opps, state }: { opps: OppSummary[]; state: CardState }) {
  return (
    <>
      {opps.map((o) => (
        <OppCard key={o.id} opp={o} flashKey={state.flashes[o.id]} isNew={state.isNew(o.id)} />
      ))}
    </>
  );
}

export function FlowColumn({ def, opps, state }: { def: ColumnDef; opps: OppSummary[]; state: CardState }) {
  const isOutcome = def.id === 'outcome';
  const offers = isOutcome ? opps.filter((o) => o.stage === 'offer') : [];
  const rejected = isOutcome ? opps.filter((o) => o.stage === 'rejected') : [];
  return (
    <ColumnShell color={def.color} className={COL_W}>
      <ColumnHeader def={def} count={opps.length} medianPay={medianMonthly(isOutcome ? offers : opps)} />
      <motion.div layoutScroll className="relative flex-1 space-y-2.5 overflow-y-auto overscroll-contain px-2.5 pb-3">
        {opps.length === 0 ? (
          <EmptyColumn def={def} />
        ) : isOutcome ? (
          <>
            <SectionLabel color={STAGE_META.offer.color} label="Offer" count={offers.length} />
            {offers.length ? (
              <CardList opps={offers} state={state} />
            ) : (
              <p className="px-1 pb-1 text-[11px] text-faint">No offers yet — they arrive notify-only.</p>
            )}
            <SectionLabel color={STAGE_META.rejected.color} label="Rejected" count={rejected.length} />
            {rejected.length ? (
              <div className="space-y-2.5 opacity-75 transition-opacity hover:opacity-100">
                <CardList opps={rejected} state={state} />
              </div>
            ) : (
              <p className="px-1 text-[11px] text-faint">None.</p>
            )}
          </>
        ) : (
          <CardList opps={opps} state={state} />
        )}
      </motion.div>
    </ColumnShell>
  );
}

function SectionLabel({ color, label, count }: { color: string; label: string; count: number }) {
  return (
    <div className="flex items-center gap-2 px-1 pt-1">
      <span className="size-1.5 rounded-full" style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }} />
      <span className="font-mono text-[10px] font-medium uppercase tracking-[0.16em]" style={{ color }}>
        {label}
      </span>
      <span className="font-mono text-[10px] text-faint tabular">{count}</span>
      <span className="h-px flex-1 bg-white/[.06]" />
    </div>
  );
}

// ── filtered (collapsible) ───────────────────────────────────────────

const REASONS: FilterReason[] = ['scam', 'ineligible', 'expired', 'pay', 'other'];

export function FilteredColumn({
  opps,
  open,
  onToggle,
}: {
  opps: OppSummary[];
  open: boolean;
  onToggle: () => void;
}) {
  const color = STAGE_META.filtered.color;
  const byReason = new Map<FilterReason, number>();
  for (const o of opps) {
    const r = filterReason(o);
    byReason.set(r, (byReason.get(r) ?? 0) + 1);
  }

  return (
    <ColumnShell color="#64748B" className={cn(open ? COL_W : 'w-[58px]', 'transition-none')}>
      <AnimatePresence initial={false} mode="wait">
        {open ? (
          <motion.div
            key="open"
            className="flex h-full min-h-0 flex-col"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            <header className="relative flex items-center gap-2 px-3.5 pb-2 pt-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[.04]">
                <Funnel className="size-3.5 text-muted" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <h3 className="font-display text-[13.5px] font-semibold tracking-tight text-ink">Filtered</h3>
                  <span className="font-display text-[13px] font-semibold tabular text-muted">{opps.length}</span>
                </div>
                <div className="text-[10.5px] text-faint">kept out by the gates</div>
              </div>
              <button
                type="button"
                onClick={onToggle}
                className="grid size-7 place-items-center rounded-lg text-muted hover:bg-white/[.06] hover:text-ink"
                aria-label="Collapse filtered column"
                title="Collapse"
              >
                <ChevronsLeft className="size-4" aria-hidden />
              </button>
            </header>
            <div className="flex flex-wrap gap-1 px-3.5 pb-2">
              {REASONS.filter((r) => byReason.get(r)).map((r) => {
                const m = FILTER_REASON_META[r];
                const Icon = m.icon;
                return (
                  <span
                    key={r}
                    className="inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-[10.5px] font-medium"
                    style={{ color: m.color, borderColor: withAlpha(m.color, 0.28), backgroundColor: withAlpha(m.color, 0.08) }}
                  >
                    <Icon className="size-3" aria-hidden />
                    {m.label} <span className="tabular opacity-80">{byReason.get(r)}</span>
                  </span>
                );
              })}
            </div>
            <motion.div layoutScroll className="flex-1 space-y-2 overflow-y-auto overscroll-contain px-2.5 pb-3">
              {opps.length === 0 ? (
                <p className="px-2 py-8 text-center text-[11px] text-faint">Nothing filtered — every find passed the gates.</p>
              ) : (
                opps.map((o) => <FilteredRow key={o.id} opp={o} />)
              )}
            </motion.div>
          </motion.div>
        ) : (
          <motion.button
            key="closed"
            type="button"
            onClick={onToggle}
            className="group flex h-full w-full flex-col items-center gap-3 px-1 pb-4 pt-3 text-muted hover:text-ink"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            aria-label={`Show ${opps.length} filtered opportunities`}
            aria-expanded={false}
          >
            <span className="grid size-8 place-items-center rounded-lg border border-white/10 bg-white/[.04] transition-colors group-hover:border-white/20">
              <Funnel className="size-3.5" style={{ color }} aria-hidden />
            </span>
            <span className="font-display text-base font-semibold tabular text-ink">{opps.length}</span>
            <span className="flex flex-col items-center gap-2">
              {REASONS.filter((r) => byReason.get(r)).map((r) => {
                const m = FILTER_REASON_META[r];
                const Icon = m.icon;
                return (
                  <Tooltip key={r} content={`${m.label}: ${byReason.get(r)}`}>
                    <span className="flex flex-col items-center gap-0.5">
                      <Icon className="size-3.5" style={{ color: m.color }} aria-hidden />
                      <span className="font-mono text-[10px] tabular text-muted">{byReason.get(r)}</span>
                    </span>
                  </Tooltip>
                );
              })}
            </span>
            <span className="mt-2 font-mono text-[10px] font-medium uppercase tracking-[0.3em] text-faint [writing-mode:vertical-rl] group-hover:text-muted">
              Filtered
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </ColumnShell>
  );
}

function FilteredRow({ opp }: { opp: OppSummary }) {
  const reason = FILTER_REASON_META[filterReason(opp)];
  const Icon = reason.icon;
  return (
    <motion.div layoutId={`opp-${opp.id}`} layout="position" transition={{ layout: { type: 'spring', stiffness: 320, damping: 34 } }}>
      <Link
        to={`/o/${opp.id}`}
        className="block rounded-xl border border-white/[.06] bg-white/[.02] p-2.5 transition-colors hover:border-white/15 hover:bg-white/[.04]"
      >
        <div className="flex min-w-0 items-center gap-1.5">
          <Icon className="size-3.5 shrink-0" style={{ color: reason.color }} aria-label={reason.label} />
          <span className="min-w-0 truncate text-[12.5px] font-medium text-ink/85">{opp.company_name}</span>
          <SimTag show={opp.is_simulated} className="shrink-0" />
        </div>
        <div className="mt-0.5 truncate text-[11px] text-faint">{opp.title}</div>
        {opp.stage_reason && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-muted">{opp.stage_reason}</p>}
        <PayBadge pay={opp.pay} size="sm" compact showRatio={false} showOriginal={false} className="mt-1.5 opacity-70" />
      </Link>
    </motion.div>
  );
}
