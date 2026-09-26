/**
 * /pipeline — the kanban. Found → Verified → Drafted → Checked → Applied → Replied → Interview → Offer/Rejected,
 * a collapsible "Filtered" column (with reasons) and the "Frozen (legacy)" lane underneath.
 *
 * Live: cards come from the zustand store (snapshot + SSE). On `opp.stage` a card glides to its new column via a
 * shared motion layoutId and flashes in the new stage color; new finds fade in. Filters (search, sim/real,
 * min ₹/month) and sort (pay / deadline / fit / recent) are per-browser preferences. Mobile: snap-scrolling
 * columns driven by the stage strip. The board is display-only — nothing here triggers agent actions.
 */
import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { ChevronLeft, ChevronRight, Clock, Coins, Hourglass, RotateCcw, SquareKanban, Target } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { EmptyState, GlassPanel, StatusDot } from '@/components';
import { eventBus } from '@/lib/bus';
import { cn } from '@/lib/cn';
import { formatINRCompact } from '@/lib/format';
import { useIsMobile, usePersistentState } from '@/lib/hooks';
import { useHQ } from '@/lib/store';
import type { OppSummary } from '@/lib/types';
import { STAGE_META } from '@/theme/tokens';
import { FilteredColumn, FlowColumn, type CardState } from './Column';
import { Segmented, SearchField } from './controls';
import { FrozenLane } from './FrozenLane';
import {
  COLUMNS,
  DEFAULT_FILTERS,
  MIN_PAY_PRESETS,
  applyFilters,
  columnOf,
  medianMonthly,
  sortOpps,
  type PipelineFilters,
  type SimFilter,
  type SortKey,
} from './model';
import { StageStrip, type StripItem } from './StageStrip';

const FLASH_MS = 6000;

const SIM_OPTIONS = [
  { value: 'all' as SimFilter, label: 'All' },
  { value: 'real' as SimFilter, label: 'Real', title: 'Real rows only (legacy import, live finds)' },
  { value: 'sim' as SimFilter, label: 'SIM', title: 'Simulated rows only' },
];

const PAY_OPTIONS = MIN_PAY_PRESETS.map((v) => ({
  value: v,
  label: v === 0 ? 'Any ₹' : `${formatINRCompact(v)}+`,
  title: v === 0 ? 'No minimum' : `Listed minimum ≥ ${formatINRCompact(v)}/month (programs covering stay + food always pass)`,
}));

const SORT_OPTIONS = [
  { value: 'pay' as SortKey, label: 'Pay', icon: Coins, title: 'Highest ₹/month first' },
  { value: 'deadline' as SortKey, label: 'Deadline', icon: Hourglass, title: 'Soonest deadline first' },
  { value: 'fit' as SortKey, label: 'Fit', icon: Target, title: 'Best fit first' },
  { value: 'recent' as SortKey, label: 'Recent', icon: Clock, title: 'Recently updated first' },
];

export default function Pipeline() {
  const oppsMap = useHQ((s) => s.opportunities);
  const legacyNeedOpen = useHQ((s) => {
    for (const k in s.needs) if (s.needs[k].status === 'open' && s.needs[k].kind === 'confirm_legacy') return true;
    return false;
  });
  const [stored, setStored] = usePersistentState<PipelineFilters>('hq.pipeline.filters.v1', DEFAULT_FILTERS);
  const filters = useMemo(() => ({ ...DEFAULT_FILTERS, ...stored }), [stored]);
  const setFilter = useCallback(
    <K extends keyof PipelineFilters>(k: K, v: PipelineFilters[K]) => setStored((p) => ({ ...DEFAULT_FILTERS, ...p, [k]: v })),
    [setStored],
  );
  const [filteredOpen, setFilteredOpen] = usePersistentState('hq.pipeline.filteredOpen', false);
  const mobile = useIsMobile();
  const reduce = useReducedMotion();

  const all = useMemo(() => Object.values(oppsMap), [oppsMap]);
  const visible = useMemo(() => sortOpps(applyFilters(all, filters), filters.sort), [all, filters]);
  const groups = useMemo(() => {
    const g: Record<string, OppSummary[]> = {};
    for (const o of visible) (g[columnOf(o.stage)] ??= []).push(o);
    return g;
  }, [visible]);
  const working = useMemo(() => all.filter((o) => o.active_agent_id).length, [all]);
  const filtersActive = filters.q.trim() !== '' || filters.sim !== 'all' || filters.minPay > 0;

  // ── live flashes on stage changes + entrance for new finds ─────────
  const [flashes, setFlashes] = useState<Record<string, number>>({});
  useEffect(
    () =>
      eventBus.on((e) => {
        if (e.type !== 'opp.stage' || !e.opportunity_id) return;
        const id = e.opportunity_id;
        const now = Date.now();
        setFlashes((prev) => {
          const next: Record<string, number> = {};
          for (const [k, t] of Object.entries(prev)) if (now - t < FLASH_MS) next[k] = t;
          next[id] = now;
          return next;
        });
      }),
    [],
  );
  const seen = useRef<Set<string> | null>(null);
  if (seen.current === null) seen.current = new Set(Object.keys(oppsMap));
  useEffect(() => {
    for (const id in oppsMap) seen.current!.add(id);
  }, [oppsMap]);
  const cardState: CardState = useMemo(() => ({ flashes, isNew: (id: string) => !seen.current!.has(id) }), [flashes]);

  // ── board scrolling (edge buttons, mobile active column) ───────────
  const boardRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const [activeCol, setActiveCol] = useState<string | null>(null);

  const measure = useCallback(() => {
    const b = boardRef.current;
    if (!b) return;
    const left = b.scrollLeft > 4;
    const right = b.scrollLeft + b.clientWidth < b.scrollWidth - 4;
    setEdges((p) => (p.left === left && p.right === right ? p : { left, right }));
    if (mobile) {
      let best: string | null = null;
      let dist = Infinity;
      b.querySelectorAll<HTMLElement>('[data-col]').forEach((el) => {
        const d = Math.abs(el.offsetLeft - b.scrollLeft);
        if (d < dist) {
          dist = d;
          best = el.dataset.col ?? null;
        }
      });
      setActiveCol(best);
    }
  }, [mobile]);

  useEffect(() => {
    const b = boardRef.current;
    if (!b) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    };
    measure();
    b.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      cancelAnimationFrame(raf);
      b.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, [measure, filteredOpen]);

  const scrollToCol = useCallback(
    (id: string) => {
      const behavior: ScrollBehavior = reduce ? 'auto' : 'smooth';
      if (id === 'frozen') {
        laneRef.current?.scrollIntoView({ behavior, block: 'start' });
        return;
      }
      if (id === 'filtered' && !filteredOpen) setFilteredOpen(true);
      requestAnimationFrame(() => {
        const b = boardRef.current;
        const el = b?.querySelector<HTMLElement>(`[data-col="${id}"]`);
        if (b && el) b.scrollTo({ left: Math.max(0, el.offsetLeft - (mobile ? 0 : 4)), behavior });
      });
      if (mobile) setActiveCol(id);
    },
    [filteredOpen, mobile, reduce, setFilteredOpen],
  );

  const page = (dir: 1 | -1) => {
    const b = boardRef.current;
    if (b) b.scrollBy({ left: dir * Math.max(280, b.clientWidth - 300), behavior: reduce ? 'auto' : 'smooth' });
  };

  const strip: StripItem[] = useMemo(
    () => [
      ...COLUMNS.map((c) => {
        const list = groups[c.id] ?? [];
        return {
          id: c.id,
          label: c.id === 'outcome' ? 'Outcome' : c.label,
          color: c.color,
          count: list.length,
          median: medianMonthly(c.id === 'outcome' ? list.filter((o) => o.stage === 'offer') : list),
        };
      }),
      { id: 'filtered', label: 'Filtered', color: STAGE_META.filtered.color, count: groups.filtered?.length ?? 0, median: null, side: true },
      { id: 'frozen', label: 'Frozen', color: STAGE_META.frozen.color, count: groups.frozen?.length ?? 0, median: null, side: true },
    ],
    [groups],
  );

  if (all.length === 0) {
    return (
      <GlassPanel padding="lg" glow="#A78BFA">
        <EmptyState
          icon={SquareKanban}
          color="#A78BFA"
          title="The board is warming up"
          hint="Scout sweeps the boards every minute — the first finds will glide in here as soon as they're parsed."
        />
      </GlassPanel>
    );
  }

  return (
    <div className="space-y-3 md:space-y-4">
      {/* toolbar */}
      <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center md:gap-3">
        <SearchField
          value={filters.q}
          onChange={(v) => setFilter('q', v)}
          placeholder="Search company, role, city…"
          className="w-full md:w-72"
        />
        <div className="-mx-4 flex items-center gap-2 overflow-x-auto px-4 scrollbar-none md:mx-0 md:overflow-visible md:px-0">
          <Segmented aria-label="Simulated or real" value={filters.sim} options={SIM_OPTIONS} onChange={(v) => setFilter('sim', v)} color="#22D3EE" />
          <Segmented aria-label="Minimum pay per month" value={filters.minPay} options={PAY_OPTIONS} onChange={(v) => setFilter('minPay', v)} color="#F5C451" />
          <Segmented aria-label="Sort cards" value={filters.sort} options={SORT_OPTIONS} onChange={(v) => setFilter('sort', v)} color="#A78BFA" />
        </div>
        <div className="flex items-center gap-3 text-xs text-muted md:ml-auto">
          {working > 0 && (
            <span className="inline-flex items-center gap-1.5">
              <StatusDot color="#34D399" pulse size={7} />
              <span className="tabular">{working}</span> in progress
            </span>
          )}
          <span className="tabular">
            {visible.length} of {all.length}
          </span>
          {filtersActive && (
            <button
              type="button"
              onClick={() => setStored(DEFAULT_FILTERS)}
              className="inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-muted hover:bg-white/[.06] hover:text-ink"
            >
              <RotateCcw className="size-3.5" aria-hidden /> Reset
            </button>
          )}
        </div>
      </div>

      <StageStrip items={strip} active={activeCol} onSelect={scrollToCol} />

      {/* board */}
      <LayoutGroup id="pipeline">
        <div className="relative">
          <motion.div
            ref={boardRef}
            layoutScroll
            className={cn(
              'relative flex h-[calc(100dvh-20.5rem)] min-h-[420px] snap-x snap-mandatory gap-3 overflow-x-auto overflow-y-hidden pb-1 scrollbar-none',
              'md:h-[calc(100dvh-17rem)] md:min-h-[520px] md:snap-none',
            )}
          >
            {COLUMNS.map((def, i) => (
              <motion.div
                key={def.id}
                data-col={def.id}
                className="h-full shrink-0"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: Math.min(i, 8) * 0.035, ease: 'easeOut' }}
              >
                <FlowColumn def={def} opps={groups[def.id] ?? []} state={cardState} />
              </motion.div>
            ))}
            <motion.div
              data-col="filtered"
              className="h-full shrink-0"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: 0.3, ease: 'easeOut' }}
            >
              <FilteredColumn opps={groups.filtered ?? []} open={filteredOpen} onToggle={() => setFilteredOpen((o) => !o)} />
            </motion.div>
            <span className="w-px shrink-0" aria-hidden />
          </motion.div>

          {/* edge affordances (desktop) */}
          <EdgeButton side="left" show={edges.left && !mobile} onClick={() => page(-1)} />
          <EdgeButton side="right" show={edges.right && !mobile} onClick={() => page(1)} />
        </div>

        {filtersActive && visible.length === 0 && (
          <p className="text-center text-sm text-muted">
            No cards match these filters.{' '}
            <button type="button" className="text-cyan-300 hover:text-cyan-200" onClick={() => setStored(DEFAULT_FILTERS)}>
              Reset filters
            </button>
          </p>
        )}

        <div ref={laneRef} className="scroll-mt-24">
          <FrozenLane opps={groups.frozen ?? []} state={cardState} needsOpen={legacyNeedOpen} />
        </div>
      </LayoutGroup>
    </div>
  );
}

function EdgeButton({ side, show, onClick }: { side: 'left' | 'right'; show: boolean; onClick: () => void }) {
  const Icon = side === 'left' ? ChevronLeft : ChevronRight;
  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-y-0 z-10 flex w-16 items-center transition-opacity duration-200',
        side === 'left' ? 'left-0 justify-start bg-gradient-to-r' : 'right-0 justify-end bg-gradient-to-l',
        'from-[#070B14] via-[#070B14]/60 to-transparent',
        show ? 'opacity-100' : 'opacity-0',
      )}
      aria-hidden={!show}
    >
      <button
        type="button"
        onClick={onClick}
        tabIndex={show ? 0 : -1}
        className={cn(
          'grid size-9 place-items-center rounded-full border border-white/15 bg-[#0D1422]/90 text-ink shadow-[0_8px_24px_-8px_rgba(0,0,0,0.9)] backdrop-blur transition-transform hover:scale-105',
          show ? 'pointer-events-auto' : 'pointer-events-none',
        )}
        aria-label={side === 'left' ? 'Scroll to earlier stages' : 'Scroll to later stages'}
      >
        <Icon className="size-4" aria-hidden />
      </button>
    </div>
  );
}
