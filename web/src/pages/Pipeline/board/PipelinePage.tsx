/**
 * /pipeline — live kanban. Columns Found → Verified → Drafted → Checked → Applied → Replied → Interview →
 * Offer / Rejected, a collapsed Filtered column and a Frozen (legacy) swimlane. Cards glide between columns
 * (motion layoutId) when `opp.stage` events land and flash in the new stage color. Filters persist per browser.
 * Phones: columns swipe horizontally with snap; the stage rail shows (and jumps to) the column in view.
 */
import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { SearchX } from 'lucide-react';
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { EmptyState } from '@/components';
import { eventBus } from '@/lib/bus';
import { useIsMobile, usePersistentState } from '@/lib/hooks';
import { useOppList } from '@/lib/store';
import type { OppSummary, Stage } from '@/lib/types';
import { FilteredColumn, OutcomeColumn, StageColumn, type CardListContext } from './BoardColumn';
import { FilterBar } from './FilterBar';
import { BOARD_COLUMNS, DEFAULT_FILTERS, FILTERED_COLUMN, buildBoard, type PipelineFilters } from './filters';
import { LegacyLane } from './LegacyLane';
import type { StageFlash } from './OppCard';
import { StageRail, type RailItem } from './StageRail';
import { FROST } from './shared';

const FLASH_MS = 3000;

/** Recent `opp.stage` arrivals → { oppId: {to, at} } (pruned after FLASH_MS). */
function useStageFlashes(): Record<string, StageFlash> {
  const [flashes, setFlashes] = useState<Record<string, StageFlash>>({});
  useEffect(() => {
    const off = eventBus.on((e) => {
      if (e.type !== 'opp.stage') return;
      const id = e.opportunity_id ?? (e.data as { opp?: OppSummary } | null)?.opp?.id;
      const to = (e.data as { to?: Stage } | null)?.to;
      if (!id || !to) return;
      setFlashes((f) => ({ ...f, [id]: { to, at: Date.now() } }));
    });
    const t = setInterval(() => {
      setFlashes((f) => {
        const now = Date.now();
        const keys = Object.keys(f);
        if (!keys.some((k) => now - f[k].at > FLASH_MS)) return f;
        const next: Record<string, StageFlash> = {};
        for (const k of keys) if (now - f[k].at <= FLASH_MS) next[k] = f[k];
        return next;
      });
    }, 1000);
    return () => {
      off();
      clearInterval(t);
    };
  }, []);
  return flashes;
}

/** Ids rendered before → cards that merely move keep `initial={false}`; brand-new ones fade in. */
function useSeenIds(ids: readonly string[]): (id: string) => boolean {
  const seen = useRef<Set<string> | null>(null);
  const firstPaint = seen.current == null;
  useEffect(() => {
    const s = seen.current ?? new Set<string>();
    for (const id of ids) s.add(id);
    seen.current = s;
  }, [ids]);
  return useCallback((id: string) => firstPaint || !seen.current!.has(id), [firstPaint]);
}

function normalizeFilters(f: Partial<PipelineFilters> | null | undefined): PipelineFilters {
  return { ...DEFAULT_FILTERS, ...(f ?? {}) };
}

export function PipelinePage() {
  const opps = useOppList();
  const mobile = useIsMobile();
  const reduced = useReducedMotion();
  const [stored, setStored] = usePersistentState<PipelineFilters>('hq.pipeline.filters', DEFAULT_FILTERS);
  const filters = normalizeFilters(stored);
  const [filteredOpen, setFilteredOpen] = usePersistentState('hq.pipeline.filteredOpen', false);
  const [legacyOpen, setLegacyOpen] = usePersistentState('hq.pipeline.legacyOpen', true);
  const q = useDeferredValue(filters.q);

  const board = useMemo(
    () => buildBoard(opps, { ...filters, q }),
    [opps, q, filters.sim, filters.minPay, filters.sort],
  );
  const flashes = useStageFlashes();
  const ids = useMemo(() => opps.map((o) => o.id), [opps]);
  const isNew = useSeenIds(ids);
  const ctx: CardListContext = { flashes, isNew, tooltips: !mobile };

  // which columns are in view (lights the rail; on phones = the swiped-to column)
  const boardRef = useRef<HTMLDivElement>(null);
  const legacyRef = useRef<HTMLElement>(null);
  const [inView, setInView] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const root = boardRef.current;
    if (!root) return;
    const vis = new Set<string>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          const id = (en.target as HTMLElement).dataset.col;
          if (!id) continue;
          if (en.intersectionRatio >= 0.55) vis.add(id);
          else vis.delete(id);
        }
        setInView(new Set(vis));
      },
      { root, threshold: [0, 0.55, 1] },
    );
    root.querySelectorAll('[data-col]').forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [filteredOpen]);

  const jump = useCallback(
    (id: string) => {
      const behavior: ScrollBehavior = reduced ? 'auto' : 'smooth';
      if (id === 'legacy') {
        if (!legacyOpen) setLegacyOpen(true);
        legacyRef.current?.scrollIntoView({ behavior, block: 'start' });
        return;
      }
      if (id === 'filtered' && !filteredOpen) setFilteredOpen(true);
      const root = boardRef.current;
      const el = root?.querySelector<HTMLElement>(`[data-col="${id}"]`);
      if (!root || !el) return;
      const pad = mobile ? 16 : 0;
      root.scrollTo({ left: el.offsetLeft - pad, behavior });
    },
    [reduced, legacyOpen, filteredOpen, mobile, setLegacyOpen, setFilteredOpen],
  );

  const rail: RailItem[] = [
    ...BOARD_COLUMNS.map((c) => ({ id: c.id, label: c.id === 'outcome' ? 'Outcome' : c.label, color: c.color, count: board.columns[c.id]?.length ?? 0 })),
    { id: 'filtered', label: 'Filtered', color: FILTERED_COLUMN.color, count: board.filtered.length, side: 'filtered' as const },
    ...(filters.sim === 'sim' ? [] : [{ id: 'legacy', label: 'Legacy', color: FROST, count: board.legacy.length, side: 'legacy' as const }]),
  ];

  const nothing = board.shown === 0;

  return (
    <div className="min-w-0 space-y-3 md:space-y-3.5">
      <FilterBar value={filters} onChange={setStored} shown={board.shown} total={board.total} mobile={mobile} />
      <StageRail items={rail} inView={inView} onJump={jump} />

      {nothing && board.total > 0 && (
        <div className="glass rounded-2xl">
          <EmptyState
            compact
            icon={SearchX}
            title="No opportunities match these filters"
            hint="Try a lower minimum pay, switch Sim / Real, or clear the search."
            action={
              <button
                type="button"
                onClick={() => setStored({ ...DEFAULT_FILTERS, sort: filters.sort })}
                className="text-sm font-medium text-cyan-300 hover:text-cyan-200"
              >
                Reset filters
              </button>
            }
          />
        </div>
      )}

      <LayoutGroup id="pipeline-board">
        <motion.div
          ref={boardRef}
          layoutScroll
          className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto overscroll-x-contain px-4 pb-2 md:mx-0 md:snap-none md:px-0"
          style={{ height: mobile ? 'max(420px, calc(100dvh - 252px))' : 'max(480px, calc(100dvh - 262px))' }}
        >
          {BOARD_COLUMNS.map((def) =>
            def.id === 'outcome' ? (
              <OutcomeColumn key={def.id} def={def} items={board.columns[def.id] ?? []} {...ctx} />
            ) : (
              <StageColumn key={def.id} def={def} items={board.columns[def.id] ?? []} {...ctx} />
            ),
          )}
          <FilteredColumn
            def={FILTERED_COLUMN}
            items={board.filtered}
            open={filteredOpen}
            onToggle={() => setFilteredOpen((o) => !o)}
            {...ctx}
          />
          <span className="w-px shrink-0 md:hidden" aria-hidden />
        </motion.div>

        {filters.sim !== 'sim' && (
          <LegacyLane ref={legacyRef} items={board.legacy} open={legacyOpen} onToggle={() => setLegacyOpen((o) => !o)} {...ctx} />
        )}
      </LayoutGroup>
    </div>
  );
}
