/**
 * /activity — a virtualised JetBrains Mono terminal of every event. Filter chips for agents, levels and event
 * types (with live counts), a search box, follow-tail with a "N new" jump button, older history paged from the
 * server, and a drawer with the event's JSON, its task and neighbouring events.
 */
import './activity.css';
import { ArrowDown, History, LoaderCircle, Search, SquareTerminal, X } from 'lucide-react';
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import { GlassPanel, SectionHeader, Sparkline } from '@/components';
import { useIsMobile, useNow, usePersistentState } from '@/lib/hooks';
import { useHQ } from '@/lib/store';
import type { EventLevel, HQEvent } from '@/lib/types';
import { EventDrawer } from './terminal/EventDrawer';
import { ChipRow, type ChipSpec } from './terminal/FilterChips';
import { LogRow, type RowContext } from './terminal/LogRow';
import {
  DEFAULT_ACTIVITY_FILTERS,
  LEVELS,
  LEVEL_META,
  SYSTEM,
  TYPE_GROUPS,
  agentKey,
  makePredicate,
  normalizeActivityFilters,
  perMinute,
  toggleHidden,
  typeGroup,
  type ActivityFilters,
} from './terminal/model';
import { useEventLog } from './terminal/useEventLog';

export default function Activity() {
  const mobile = useIsMobile();
  const now = useNow(5000);
  const agents = useHQ((s) => s.agents);
  const agentOrder = useHQ((s) => s.agentOrder);
  const log = useEventLog();
  const [stored, setStored] = usePersistentState<ActivityFilters>('hq.activity.filters', DEFAULT_ACTIVITY_FILTERS);
  const filters = normalizeActivityFilters(stored);
  const q = useDeferredValue(filters.q);
  const [selected, setSelected] = useState<HQEvent | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [liveAfterId] = useState(() => useHQ.getState().events.at(-1)?.id ?? 0);
  const virtuoso = useRef<VirtuosoHandle>(null);
  const seenAtBottom = useRef(0);

  const visible = useMemo(() => log.events.filter(makePredicate(filters, q)), [log.events, filters, q]);
  const newBelow = atBottom ? 0 : Math.max(0, visible.length - seenAtBottom.current);
  useEffect(() => {
    if (atBottom) seenAtBottom.current = visible.length;
  }, [atBottom, visible.length]);

  const counts = useMemo(() => {
    const agentsC = new Map<string, number>();
    const levelsC = new Map<string, number>();
    const typesC = new Map<string, number>();
    for (const e of log.events) {
      agentsC.set(agentKey(e), (agentsC.get(agentKey(e)) ?? 0) + 1);
      levelsC.set(e.level, (levelsC.get(e.level) ?? 0) + 1);
      const g = typeGroup(e.type);
      typesC.set(g, (typesC.get(g) ?? 0) + 1);
    }
    return { agentsC, levelsC, typesC };
  }, [log.events]);

  const agentChips: ChipSpec[] = useMemo(
    () => [
      ...agentOrder.map((id) => ({
        key: id,
        label: agents[id]?.name.replace(/\s*\(.*\)$/, '') ?? id,
        color: agents[id]?.color ?? '#94A3B8',
        count: counts.agentsC.get(id) ?? 0,
        lead: <span aria-hidden>{agents[id]?.avatar && agents[id].avatar.length <= 3 ? agents[id].avatar : '•'}</span>,
      })),
      { key: SYSTEM, label: 'system', color: '#8B95A7', count: counts.agentsC.get(SYSTEM) ?? 0 },
    ],
    [agentOrder, agents, counts],
  );
  const levelChips: ChipSpec[] = LEVELS.map((l) => ({ key: l, label: LEVEL_META[l].label, color: LEVEL_META[l].color, count: counts.levelsC.get(l) ?? 0 }));
  const typeChips: ChipSpec[] = TYPE_GROUPS.map((g) => ({ key: g.id, label: g.label, color: '#93C5FD', count: counts.typesC.get(g.id) ?? 0 }));

  const setFilters = useCallback((patch: Partial<ActivityFilters>) => setStored((p) => ({ ...normalizeActivityFilters(p), ...patch })), [setStored]);
  const rate = useMemo(() => perMinute(log.events, now, 30), [log.events, now]);

  const ctx: RowContext = { now, q, selectedId: selected?.id ?? null, onOpen: setSelected, mobile, agents, liveAfterId };

  return (
    <div className="space-y-4">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Terminal"
        title="Activity"
        right={
          <div className="hidden items-center gap-3 text-xs text-muted md:flex">
            <Sparkline data={rate} color="#A3E635" width={120} height={26} label="events per minute, last 30 minutes" />
            <span className="tabular">{rate.reduce((a, b) => a + b, 0)} events · 30 min</span>
          </div>
        }
      />

      <GlassPanel padding="md" glow="#A3E635" glowStrength={0.15} className="space-y-2.5">
        <label className="flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[.03] px-3 focus-within:border-lime-300/40">
          <Search className="size-4 text-faint" aria-hidden />
          <input
            value={filters.q}
            onChange={(e) => setFilters({ q: e.target.value })}
            placeholder="Search messages, types, agents…"
            aria-label="Search events"
            className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-ink placeholder:text-faint outline-none"
          />
          {filters.q && (
            <button type="button" onClick={() => setFilters({ q: '' })} aria-label="Clear search" className="text-faint hover:text-ink">
              <X className="size-4" />
            </button>
          )}
          <span className="shrink-0 font-mono text-[11px] text-faint tabular">
            {visible.length}/{log.events.length}
          </span>
        </label>
        <ChipRow label="agents" chips={agentChips} hidden={filters.hiddenAgents} nowrap={mobile}
          onToggle={(k, solo) => setFilters({ hiddenAgents: toggleHidden(filters.hiddenAgents, k, agentChips.map((c) => c.key), solo) })} />
        <ChipRow label="level" chips={levelChips} hidden={filters.hiddenLevels} nowrap={mobile}
          onToggle={(k, solo) => setFilters({ hiddenLevels: toggleHidden<EventLevel>(filters.hiddenLevels, k as EventLevel, LEVELS, solo) })} />
        <ChipRow label="type" chips={typeChips} hidden={filters.hiddenTypes} nowrap={mobile}
          onToggle={(k, solo) => setFilters({ hiddenTypes: toggleHidden(filters.hiddenTypes, k, TYPE_GROUPS.map((g) => g.id), solo) })} />
      </GlassPanel>

      <GlassPanel padding="none" className="relative overflow-hidden bg-[#060A12]/80">
        <div className="flex items-center justify-between border-b border-white/[.06] px-4 py-2 font-mono text-[10.5px] text-faint">
          <span className="inline-flex items-center gap-1.5">
            <SquareTerminal className="size-3.5 text-lime-300" aria-hidden /> hq://events
          </span>
          <button
            type="button"
            disabled={log.loadingOlder || log.exhausted}
            onClick={() => void log.loadOlder()}
            className="inline-flex items-center gap-1.5 text-muted hover:text-ink disabled:opacity-40"
          >
            {log.loadingOlder ? <LoaderCircle className="size-3 animate-spin" /> : <History className="size-3" />}
            {log.exhausted ? 'start of history' : 'load older'}
          </button>
        </div>
        {log.olderError && <div className="px-4 py-1 text-xs text-red-300">{log.olderError}</div>}
        <div className="h-[calc(100dvh-420px)] min-h-[360px] md:h-[calc(100dvh-380px)]">
          {visible.length === 0 ? (
            <div className="grid h-full place-items-center font-mono text-xs text-faint">
              {log.events.length === 0 ? '$ waiting for events…' : 'no events match these filters'}
            </div>
          ) : (
            <Virtuoso
              ref={virtuoso}
              data={visible}
              computeItemKey={(_, e) => e.id}
              followOutput={(bottom) => (bottom ? 'auto' : false)}
              atBottomStateChange={setAtBottom}
              atBottomThreshold={40}
              initialTopMostItemIndex={Math.max(0, visible.length - 1)}
              startReached={() => {
                if (!log.exhausted && !log.loadingOlder) void log.loadOlder();
              }}
              itemContent={(_, e) => <LogRow e={e} ctx={ctx} />}
              className="scrollbar-none"
            />
          )}
        </div>
        {!atBottom && (
          <button
            type="button"
            onClick={() => virtuoso.current?.scrollToIndex({ index: visible.length - 1, behavior: 'smooth' })}
            className="absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-lime-300/30 bg-[#0B111D]/90 px-3 py-1.5 font-mono text-[11px] text-lime-200 shadow-lg backdrop-blur"
          >
            <ArrowDown className="size-3.5" aria-hidden />
            {newBelow > 0 ? `${newBelow} new` : 'latest'}
          </button>
        )}
      </GlassPanel>

      <EventDrawer event={selected} onClose={() => setSelected(null)} onSelect={setSelected} log={log.events} agents={agents} mobile={mobile} now={now} />
    </div>
  );
}
