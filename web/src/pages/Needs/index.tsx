/**
 * /needs — the "Needs Prerit" lane: everything agents may not or cannot do, pre-filled so each item takes a couple
 * of minutes. Open items are sorted by priority then due date; Done / Snooze / Dismiss PATCH /api/needs/:id with
 * optimistic removal (rolled back with a visible error if the server refuses).
 */
import { AnimatePresence, motion } from 'motion/react';
import {
  BellOff,
  ChevronDown,
  Clock,
  HandHelping,
  Inbox as InboxIcon,
  KeyRound,
  ListChecks,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  X,
} from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { EmptyState, GlassPanel, SectionHeader } from '@/components';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import { resolveNeed, useHQ } from '@/lib/store';
import type { Need } from '@/lib/types';
import { withAlpha } from '@/theme/tokens';
import { Segmented } from '../Agents/formKit';
import { GOLD, filterOf, isAlertKind, kindMeta, type NeedFilter } from './kinds';
import { NeedCard, type NeedAction } from './NeedCard';

const LANE = '#FB923C';

function byUrgency(a: Need, b: Need): number {
  return b.priority - a.priority || (a.due_at ?? '9').localeCompare(b.due_at ?? '9') || a.created_at.localeCompare(b.created_at);
}

export default function Needs() {
  const all = useHQ((s) => s.needs);
  const [filter, setFilter] = useState<NeedFilter>('all');
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [showSnoozed, setShowSnoozed] = useState(false);

  const { open, snoozed } = useMemo(() => {
    const list = Object.values(all);
    return {
      open: list.filter((n) => n.status === 'open').sort(byUrgency),
      snoozed: list.filter((n) => n.status === 'snoozed').sort((a, b) => (a.due_at ?? '').localeCompare(b.due_at ?? '')),
    };
  }, [all]);

  const counts = useMemo(() => {
    const c: Record<NeedFilter, number> = { all: open.length, alerts: 0, forms: 0, decisions: 0, other: 0 };
    for (const n of open) c[filterOf(n.kind)]++;
    return c;
  }, [open]);

  const shown = filter === 'all' ? open : open.filter((n) => filterOf(n.kind) === filter);
  const minutes = open.reduce((s, n) => s + (n.est_minutes ?? 2), 0);
  const alerts = open.filter((n) => isAlertKind(n.kind));

  const act = useCallback(async (need: Need, action: NeedAction) => {
    setError(null);
    setBusy((b) => ({ ...b, [need.id]: true }));
    const st = useHQ.getState();
    st.upsertNeed({ ...need, status: action.status });
    try {
      await resolveNeed(need.id, action.status, action.status === 'snoozed' ? action.hours : undefined);
    } catch (e) {
      useHQ.getState().upsertNeed(need);
      setError(`Couldn't update "${need.title}": ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(({ [need.id]: _, ...rest }) => rest);
    }
  }, []);

  const filterOptions = [
    { value: 'all' as const, label: <FilterLabel text="All" n={counts.all} /> },
    { value: 'alerts' as const, label: <FilterLabel text="Alerts" n={counts.alerts} /> },
    { value: 'forms' as const, label: <FilterLabel text="Forms" n={counts.forms} /> },
    { value: 'decisions' as const, label: <FilterLabel text="Decisions" n={counts.decisions} /> },
    ...(counts.other ? [{ value: 'other' as const, label: <FilterLabel text="Other" n={counts.other} /> }] : []),
  ];

  return (
    <div className="space-y-5 md:space-y-6">
      <SectionHeader
        as="h1"
        size="lg"
        kicker="Your lane"
        title="Needs Prerit"
        right={
          open.length > 0 ? (
            <div className="hidden items-center gap-2 text-sm text-muted sm:flex">
              <Clock className="size-4" style={{ color: LANE }} aria-hidden />
              <span className="tabular">
                <b className="font-display text-ink">{open.length}</b> open · ≈{' '}
                <b className="font-display text-ink">{Math.max(1, Math.round(minutes))}</b> min to clear
              </span>
            </div>
          ) : undefined
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-6">
        <section className="min-w-0 space-y-4" aria-label="Open items">
          {alerts.length > 0 && <AlertStrip needs={alerts} />}

          {open.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Segmented label="Filter needs" value={filter} onChange={setFilter} options={filterOptions} color={LANE} size="sm" />
              <span className="text-xs text-muted sm:hidden tabular">
                {open.length} open · ≈ {Math.max(1, Math.round(minutes))} min
              </span>
            </div>
          )}

          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                role="alert"
                className="flex items-start gap-2.5 rounded-xl border border-red-400/35 bg-red-500/10 px-3.5 py-2.5 text-[13px] text-red-200"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-red-300" aria-hidden />
                <span className="min-w-0 flex-1">{error}</span>
                <button type="button" onClick={() => setError(null)} aria-label="Dismiss error" className="text-red-200/70 hover:text-red-100">
                  <X className="size-4" aria-hidden />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {open.length === 0 ? (
            <GlassPanel glow={LANE} accentTop padding="lg">
              <EmptyState
                icon={HandHelping}
                color={LANE}
                title="Nothing needs you right now"
                hint={
                  <>
                    Agents only ask when a website won&apos;t allow automation, a decision is yours, or a reply is an
                    interview, offer or money matter. Each item arrives pre-filled so it takes under two minutes.
                  </>
                }
              />
            </GlassPanel>
          ) : shown.length === 0 ? (
            <GlassPanel padding="md">
              <EmptyState compact icon={ListChecks} color={LANE} title="Nothing in this filter" hint="Switch back to All to see every open item." />
            </GlassPanel>
          ) : (
            <motion.ul layout className="space-y-4">
              <AnimatePresence initial={false} mode="popLayout">
                {shown.map((n, i) => (
                  <motion.li
                    key={n.id}
                    layout
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i, 6) * 0.04, duration: 0.28, ease: [0.16, 1, 0.3, 1] } }}
                    exit={{ opacity: 0, x: 48, scale: 0.98, transition: { duration: 0.22 } }}
                    className="min-w-0"
                  >
                    <NeedCard need={n} onAction={act} busy={!!busy[n.id]} />
                  </motion.li>
                ))}
              </AnimatePresence>
            </motion.ul>
          )}

          {snoozed.length > 0 && (
            <div className="pt-1">
              <button
                type="button"
                onClick={() => setShowSnoozed((s) => !s)}
                aria-expanded={showSnoozed}
                className="inline-flex items-center gap-2 rounded-lg px-1 py-1 text-sm text-muted transition-colors hover:text-ink"
              >
                <BellOff className="size-4" aria-hidden />
                Snoozed ({snoozed.length})
                <ChevronDown className={cn('size-4 transition-transform', showSnoozed && 'rotate-180')} aria-hidden />
              </button>
              <AnimatePresence initial={false}>
                {showSnoozed && (
                  <motion.ul
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    className="mt-3 space-y-3 opacity-80"
                  >
                    {snoozed.map((n) => (
                      <li key={n.id}>
                        <NeedCard need={n} onAction={act} busy={!!busy[n.id]} />
                      </li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>
          )}
        </section>

        <aside className="min-w-0 space-y-4 xl:sticky xl:top-24 xl:self-start" aria-label="About this lane">
          <LaneSummary open={open} minutes={minutes} />
          <GlassPanel padding="md" glow="#22D3EE" glowStrength={0.18}>
            <SectionHeader size="sm" kicker="Ground rules" title="What agents never do" icon={ShieldCheck} color="#2DD4BF" />
            <ul className="mt-3 space-y-2.5 text-[13px] leading-relaxed text-muted">
              <Rule icon={ShieldAlert} color={GOLD}>
                Reply to interviews, accept offers, or touch money, contracts and legal matters — they land here as alerts.
              </Rule>
              <Rule icon={KeyRound} color="#FB923C">
                Enter passwords, create accounts, solve CAPTCHAs or attempt assessments.
              </Rule>
              <Rule icon={InboxIcon} color="#60A5FA">
                Submit forms on sites that forbid bots — you get a pre-filled pack and a direct link instead.
              </Rule>
            </ul>
          </GlassPanel>
        </aside>
      </div>
    </div>
  );
}

function FilterLabel({ text, n }: { text: string; n: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {text}
      <span className="rounded-md bg-white/[.07] px-1.5 text-[10.5px] text-muted tabular">{n}</span>
    </span>
  );
}

function Rule({ icon: Icon, color, children }: { icon: typeof ShieldAlert; color: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color }} aria-hidden />
      <span>{children}</span>
    </li>
  );
}

function AlertStrip({ needs }: { needs: Need[] }) {
  const gold = needs.some((n) => kindMeta(n.kind).alert === 'gold');
  const c = gold ? GOLD : '#F87171';
  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className="relative flex items-center gap-3 overflow-hidden rounded-2xl border px-4 py-3"
      style={{ borderColor: withAlpha(c, 0.4), background: `linear-gradient(90deg, ${withAlpha(c, 0.16)}, ${withAlpha(c, 0.04)})` }}
      role="status"
    >
      <span className="relative grid size-8 shrink-0 place-items-center">
        <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ backgroundColor: withAlpha(c, 0.5) }} aria-hidden />
        <ShieldAlert className="relative size-5" style={{ color: c }} aria-hidden />
      </span>
      <div className="min-w-0 text-[13.5px]">
        <div className="font-display font-semibold text-ink">
          {needs.length} alert{needs.length > 1 ? 's' : ''} waiting for you
        </div>
        <div className="truncate text-muted">
          {needs.map((n) => kindMeta(n.kind).label).join(' · ')} — agents never act on these; the threads are locked for outbound.
        </div>
      </div>
    </motion.div>
  );
}

function LaneSummary({ open, minutes }: { open: Need[]; minutes: number }) {
  const oldest = open.reduce<string | null>((o, n) => (!o || n.created_at < o ? n.created_at : o), null);
  const byKind = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of open) m.set(n.kind, (m.get(n.kind) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [open]);
  const max = Math.max(1, ...byKind.map(([, v]) => v));
  return (
    <GlassPanel padding="md" glow={LANE} glowStrength={0.25} accentTop>
      <SectionHeader size="sm" kicker="Lane" title="At a glance" icon={HandHelping} color={LANE} />
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-white/[.07] bg-white/[.03] p-3">
          <div className="text-[10.5px] tracking-[0.12em] text-muted uppercase">Open</div>
          <div className="mt-1 font-display text-2xl font-semibold text-ink tabular">{open.length}</div>
        </div>
        <div className="rounded-xl border border-white/[.07] bg-white/[.03] p-3">
          <div className="text-[10.5px] tracking-[0.12em] text-muted uppercase">Your time</div>
          <div className="mt-1 font-display text-2xl font-semibold text-ink tabular">
            ≈{Math.round(minutes)}
            <span className="ml-1 text-sm font-normal text-muted">min</span>
          </div>
        </div>
      </div>
      {byKind.length > 0 ? (
        <ul className="mt-4 space-y-2">
          {byKind.map(([kind, n]) => {
            const m = kindMeta(kind);
            const Icon = m.icon;
            return (
              <li key={kind} className="flex items-center gap-2.5 text-[13px]">
                <Icon className="size-3.5 shrink-0" style={{ color: m.color }} aria-hidden />
                <span className="w-28 shrink-0 truncate text-muted">{m.label}</span>
                <span className="relative h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/[.06]">
                  <span
                    className="absolute inset-0 origin-left rounded-full transition-transform duration-500"
                    style={{ transform: `scaleX(${n / max})`, backgroundColor: m.color, boxShadow: `0 0 8px ${withAlpha(m.color, 0.6)}` }}
                  />
                </span>
                <span className="w-5 text-right font-medium text-ink tabular">{n}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-3 text-[13px] text-muted">The lane is clear.</p>
      )}
      {oldest && <p className="mt-4 text-xs text-faint">Oldest open item arrived {formatRelative(oldest)}.</p>}
    </GlassPanel>
  );
}
