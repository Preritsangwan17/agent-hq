/**
 * Pipeline toolbar: search (focus with "/"), sim / real toggle, minimum ₹/month and sort. Inline on desktop;
 * on phones the controls fold into a panel behind a "Filters" button so the board keeps the screen.
 */
import { AnimatePresence, motion } from 'motion/react';
import { ArrowDownWideNarrow, CalendarClock, Coins, FlaskConical, Globe, Layers, RotateCcw, Search, SlidersHorizontal, Target, X, History } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { MIN_PAY_OPTIONS, DEFAULT_FILTERS, type PipelineFilters, type SimFilter, type SortKey } from './filters';
import { Segmented, type SegmentedOption } from './Segmented';

const SIM_OPTIONS: readonly SegmentedOption<SimFilter>[] = [
  { value: 'all', label: 'All', icon: Layers },
  { value: 'sim', label: 'Sim', icon: FlaskConical, title: 'Simulated rows only' },
  { value: 'real', label: 'Real', icon: Globe, title: 'Real rows only (legacy import in phase a)' },
];

const SORT_OPTIONS: readonly SegmentedOption<SortKey>[] = [
  { value: 'pay', label: 'Pay', icon: Coins, title: 'Highest ₹/month first (hourly and unknown after)' },
  { value: 'deadline', label: 'Deadline', icon: CalendarClock, title: 'Soonest deadline first' },
  { value: 'fit', label: 'Fit', icon: Target, title: 'Best fit score first' },
  { value: 'recent', label: 'Recent', icon: History, title: 'Most recently updated first' },
];

const PAY_OPTIONS: readonly SegmentedOption<number>[] = MIN_PAY_OPTIONS.map((o) => ({
  value: o.value,
  label: o.label,
  title: o.value ? `Only roles whose monthly pay reaches ${o.label} (hourly-only and unknown pay are hidden)` : 'Any pay',
}));

const GOLD = '#F5C451';

export interface FilterBarProps {
  value: PipelineFilters;
  onChange: (f: PipelineFilters) => void;
  shown: number;
  total: number;
  mobile: boolean;
}

export function FilterBar({ value, onChange, shown, total, mobile }: FilterBarProps) {
  const [open, setOpen] = useState(false);
  const set = <K extends keyof PipelineFilters>(k: K, v: PipelineFilters[K]) => onChange({ ...value, [k]: v });
  const active = (value.sim !== 'all' ? 1 : 0) + (value.minPay > 0 ? 1 : 0) + (value.q.trim() ? 1 : 0);
  const reset = () => onChange({ ...DEFAULT_FILTERS, sort: value.sort });

  const sim = <Segmented ariaLabel="Simulated or real" value={value.sim} onChange={(v) => set('sim', v)} options={SIM_OPTIONS} block={mobile} />;
  const pay = (
    <Segmented ariaLabel="Minimum pay per month" value={value.minPay} onChange={(v) => set('minPay', v)} options={PAY_OPTIONS} color={GOLD} block={mobile} />
  );
  const sort = <Segmented ariaLabel="Sort cards" value={value.sort} onChange={(v) => set('sort', v)} options={SORT_OPTIONS} color="#A78BFA" block={mobile} />;

  if (mobile) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <SearchField value={value.q} onChange={(q) => set('q', q)} className="flex-1" />
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className={cn(
              'relative grid size-9 shrink-0 place-items-center rounded-xl border transition-colors',
              open ? 'border-cyan-300/40 bg-cyan-300/10 text-cyan-200' : 'border-white/10 bg-white/[.04] text-muted',
            )}
            aria-label="Filters and sort"
          >
            <SlidersHorizontal className="size-4" aria-hidden />
            {active > 0 && (
              <span className="absolute -right-1 -top-1 grid size-4 place-items-center rounded-full bg-cyan-300 text-[9px] font-bold text-[#041018]">
                {active}
              </span>
            )}
          </button>
        </div>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              key="panel"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.16 }}
              className="glass space-y-2.5 rounded-2xl p-3"
            >
              <Labeled label="Show">{sim}</Labeled>
              <Labeled label="Min pay / month">{pay}</Labeled>
              <Labeled label="Sort by">{sort}</Labeled>
              <div className="flex items-center justify-between pt-0.5 text-xs text-muted">
                <span className="tabular">
                  {shown} of {total} shown
                </span>
                {active > 0 && (
                  <button type="button" onClick={reset} className="inline-flex items-center gap-1 text-cyan-300">
                    <RotateCcw className="size-3" aria-hidden /> Reset
                  </button>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <SearchField value={value.q} onChange={(q) => set('q', q)} className="w-full sm:w-64" />
      {sim}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-faint">Min/mo</span>
        {pay}
      </div>
      <div className="flex items-center gap-1.5">
        <ArrowDownWideNarrow className="size-3.5 text-faint" aria-hidden />
        {sort}
      </div>
      <div className="ml-auto flex items-center gap-2 text-xs text-muted">
        {active > 0 && (
          <button
            type="button"
            onClick={reset}
            className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-cyan-300 transition-colors hover:bg-cyan-300/10"
          >
            <RotateCcw className="size-3" aria-hidden /> Reset
          </button>
        )}
        <span className="tabular">
          <span className="text-ink">{shown}</span> of {total} shown
        </span>
      </div>
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-faint">{label}</div>
      {children}
    </div>
  );
}

export function SearchField({
  value,
  onChange,
  className,
  placeholder = 'Search company, role, city…',
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
  placeholder?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      ref.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return (
    <label
      className={cn(
        'group relative flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[.04] px-3 transition-colors focus-within:border-cyan-300/40 focus-within:bg-white/[.06]',
        className,
      )}
    >
      <Search className="size-4 shrink-0 text-faint group-focus-within:text-cyan-300" aria-hidden />
      <input
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            onChange('');
            ref.current?.blur();
          }
        }}
        placeholder={placeholder}
        aria-label="Search opportunities"
        className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-faint focus:outline-none"
        style={{ outline: 'none' }}
      />
      {value ? (
        <button type="button" onClick={() => onChange('')} className="grid size-5 place-items-center rounded text-faint hover:text-ink" aria-label="Clear search">
          <X className="size-3.5" aria-hidden />
        </button>
      ) : (
        <kbd className="hidden rounded border border-white/10 px-1.5 font-mono text-[10px] text-faint sm:inline">/</kbd>
      )}
    </label>
  );
}
