/**
 * The Strategist's daily reviews: the latest (or a picked earlier) report in full, what it changed on its own
 * (whitelisted low-risk actions), what it proposes, and "Run review now".
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Compass, History, Lightbulb, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge, Button, EmptyState, GlassPanel, SectionHeader } from '@/components';
import { ApiError, api } from '@/lib/api';
import { formatDateIST, formatDateTimeIST } from '@/lib/format';
import type { StrategyAction, StrategyReport } from '@/lib/types';
import { Markdownish } from '@/pages/Needs/markdown';

const STRAT = '#E879F9';
const RISK: Record<string, string> = { low: '#34D399', medium: '#FBBF24', high: '#F87171' };
const TYPE_LABEL: Record<string, string> = {
  add_ats_slug: 'Add job board',
  disable_source: 'Turn off source',
  tune_keywords: 'Tune title keywords',
  change_threshold: 'Change a threshold',
  note: 'Note',
};

export function useRunReview() {
  const qc = useQueryClient();
  const [state, setState] = useState<{ busy: boolean; msg: string | null; since: number | null }>({ busy: false, msg: null, since: null });
  // poll for the new report for up to 2 minutes after a run request
  useEffect(() => {
    if (!state.since) return;
    const t = setInterval(() => {
      void qc.invalidateQueries({ queryKey: ['strategy'] });
      if (Date.now() - (state.since ?? 0) > 120_000) setState((s) => ({ ...s, since: null }));
    }, 4000);
    return () => clearInterval(t);
  }, [state.since, qc]);
  const run = async () => {
    setState({ busy: true, msg: null, since: null });
    try {
      const r = await api.strategyRun();
      setState({
        busy: false,
        since: Date.now(),
        msg: r.queued
          ? r.paused
            ? 'Queued — the Strategist is paused, so it runs when you resume it.'
            : 'Queued — the review appears here in a few seconds.'
          : (r.detail ?? 'A review is already on its way.'),
      });
    } catch (e) {
      setState({ busy: false, since: null, msg: e instanceof ApiError ? e.message : String(e) });
    }
  };
  return { ...state, run };
}

export function StrategistPanel() {
  const latest = useQuery({ queryKey: ['strategy', 'latest'], queryFn: api.strategyLatest, refetchInterval: 60_000 });
  const history = useQuery({ queryKey: ['strategy', 'reports'], queryFn: () => api.strategyReports(30) });
  const [picked, setPicked] = useState<string | null>(null);
  const runner = useRunReview();
  const reports = history.data?.items ?? [];
  const report: StrategyReport | null | undefined =
    (picked && reports.find((r) => r.date === picked)) || latest.data?.report;

  return (
    <GlassPanel padding="lg" glow={STRAT} glowStrength={0.22}>
      <SectionHeader
        kicker={report ? `Daily review · ${formatDateIST(report.created_at)}` : 'Daily review'}
        title="Strategist"
        icon={Compass}
        color={STRAT}
        right={
          <Button size="sm" variant="secondary" icon={Play} loading={runner.busy} onClick={() => void runner.run()}>
            Run review now
          </Button>
        }
      />
      {runner.msg && <p className="mt-2 text-[12.5px] text-muted" role="status">{runner.msg}</p>}
      {!report ? (
        <EmptyState
          compact
          color={STRAT}
          title="No review yet"
          hint={
            latest.data
              ? `The first review runs ${formatDateTimeIST(latest.data.next_run_at)} IST — or press Run review now.`
              : 'Reviews run every morning at 07:30 IST.'
          }
        />
      ) : (
        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="min-w-0 text-[13.5px] leading-relaxed text-ink/85">
            <Markdownish source={report.report_md ?? ''} />
          </div>
          <div className="min-w-0 space-y-4">
            <ActionList title="Done automatically" icon={CheckCircle2} color="#34D399" actions={report.applied_actions}
              empty="Nothing changed on its own." />
            <ActionList title="Proposals for you" icon={Lightbulb} color={STRAT} actions={report.proposed_actions}
              empty="No proposals." />
            {reports.length > 1 && (
              <div>
                <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.14em] text-muted">
                  <History className="size-3.5" aria-hidden /> Earlier reviews
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {reports.slice(0, 14).map((r) => {
                    const active = (picked ?? latest.data?.report?.date) === r.date;
                    return (
                      <button
                        key={r.date}
                        type="button"
                        onClick={() => setPicked(r.date)}
                        aria-pressed={active}
                        className={`rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors ${active ? 'border-fuchsia-300/40 bg-fuchsia-300/10 text-ink' : 'border-white/10 text-muted hover:text-ink'}`}
                      >
                        {r.date.slice(5)}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </GlassPanel>
  );
}

function ActionList({ title, icon: Icon, color, actions, empty }: {
  title: string;
  icon: typeof CheckCircle2;
  color: string;
  actions: StrategyAction[];
  empty: string;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.14em] text-muted">
        <Icon className="size-3.5" style={{ color }} aria-hidden /> {title}
      </div>
      {actions.length === 0 ? (
        <p className="text-[12.5px] text-faint">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {actions.map((a, i) => (
            <li key={i} className="rounded-xl border border-white/[.07] bg-white/[.02] px-3 py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[12.5px] font-medium text-ink">{TYPE_LABEL[a.type] ?? a.type}</span>
                {a.risk && <Badge color={RISK[a.risk] ?? '#8B95A7'} size="xs">{a.risk} risk</Badge>}
                {a.status === 'not_verified' && <Badge color="#FBBF24" size="xs">not verified</Badge>}
              </div>
              {a.rationale && <p className="mt-0.5 text-[12.5px] text-muted">{a.rationale}</p>}
              {a.params && Object.keys(a.params).length > 0 && (
                <p className="mt-0.5 truncate font-mono text-[11px] text-faint" title={JSON.stringify(a.params)}>
                  {Object.entries(a.params).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join(' · ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
